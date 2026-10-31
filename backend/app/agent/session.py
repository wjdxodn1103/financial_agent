"""세션 문서(doc) 헬퍼 — OP `paper/agent/session.py` 의 축소판.

doc 은 리포트 1편의 상태:
  reportType · setup{title, subject, asOf, audience} · sections[{step, title, status, covers, content?}]
  evidence{step: {docIds, checks, warnings}} · history(모델용 OpenAI 메시지) · transcript(화면 그대로)
  sectionLog · decisions · userInputs(카드 입력 누적) · documentIds · plan/pendingPlan · pendingApproval · lastWrittenStep
저장은 서비스가 맡고(SQLite JSON 컬럼), 여기 함수들은 dict 를 제자리에서 고친다.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.agent.template import items_of, rank_of
from app.ids import id36, now_iso

Doc = Dict[str, Any]
Section = Dict[str, Any]

HISTORY_MAX_MESSAGES = 40
TOOL_RESULT_MAX = 1500  # 검색 결과는 다음 턴에도 근거가 되므로 OP(600자)보다 넉넉히


def new_section_id() -> str:
    return id36("p", 4)


def new_doc(session_id: str, report_type: str, title: str = "") -> Doc:
    now = now_iso()
    doc: Doc = {
        "id": session_id,
        "createdAt": now,
        "updatedAt": now,
        "reportType": report_type,
        "setup": {"title": title, "subject": "", "asOf": "", "audience": ""},
        "sections": [],
        "evidence": {},
        "history": [],
        "transcript": [],
        "sectionLog": {},
        "decisions": [],
        "userInputs": {},
        "documentIds": [],
    }
    seed_sections(doc)
    return doc


def seed_sections(doc: Doc) -> None:
    """유형의 항목을 빈 섹션으로 깐다(OP 템플릿 시드와 같은 생각 — 리포트 뷰에 목차와 '작성' 버튼이 바로 보인다)."""
    import copy

    from app.agent.template import report_type

    # 양식 2.0 틀 — 문서에 복사해 둔다(양식을 고쳐도 이미 만든 문서는 그대로). 장 띠·부록·테마·표 양식은 doc["layout"] 에서 그린다
    bp = report_type(doc.get("reportType")).get("blueprint")
    if bp:
        doc["layout"] = copy.deepcopy(bp)
    else:
        doc.pop("layout", None)
    # 등록 양식(rt:)은 섹션 뒤 표·차트 자리(slots)도 깐다 — fill_slots 가 채운다. 틀이 있으면 part·role·depth·blocks(묶인 표·그림 자리)
    doc["sections"] = [
        {"step": new_section_id(), "title": it["title"], "status": "empty", "covers": [it["id"]], **({"slots": it["slots"]} if it.get("slots") else {}),
         **{k: copy.deepcopy(it[k]) for k in ("part", "role", "depth", "blocks") if k in it}}
        for it in items_of(doc.get("reportType"))
    ]


# ── 히스토리(OP 그대로) ─────────────────────────────────────────────────

def push_history(doc: Doc, msgs: List[Dict[str, Any]]) -> None:
    history: List[Dict[str, Any]] = doc.setdefault("history", [])
    for m in msgs:
        if m.get("role") == "tool" and isinstance(m.get("content"), str) and len(m["content"]) > TOOL_RESULT_MAX:
            history.append({**m, "content": m["content"][:TOOL_RESULT_MAX] + " …(절단)"})
        else:
            history.append(m)
    decisions: List[str] = doc.setdefault("decisions", [])
    while len(history) > HISTORY_MAX_MESSAGES:
        first = history.pop(0)
        if first.get("role") == "user" and isinstance(first.get("content"), str):
            decisions.append(f"[이전 요청] {first['content'][:120]}")
        while history and history[0].get("role") != "user":
            history.pop(0)
    if len(decisions) > 20:
        doc["decisions"] = decisions[-20:]


def history_messages(doc: Doc) -> List[Dict[str, Any]]:
    """모델에 보낼 히스토리 — 도구 호출 arguments 가 JSON 객체 문자열이 아니면 "{}"(잘린 인자 하나로 NIM 이 400 을 내던 OP 사고)."""
    out: List[Dict[str, Any]] = []
    for m in doc.get("history") or []:
        calls = m.get("tool_calls") if m.get("role") == "assistant" else None
        if not calls:
            out.append(m)
            continue
        fixed = []
        for c in calls:
            fn = dict((c or {}).get("function") or {})
            try:
                ok = isinstance(json.loads(fn.get("arguments") or ""), dict)
            except ValueError:
                ok = False
            if not ok:
                fn["arguments"] = "{}"
            fixed.append({**c, "function": fn})
        out.append({**m, "tool_calls": fixed})
    return out


# ── 섹션 ────────────────────────────────────────────────────────────────

def find_section(doc: Doc, step: Optional[str]) -> Optional[Section]:
    return next((s for s in doc.get("sections") or [] if s.get("step") == step), None) if step else None


def find_by_title(doc: Doc, title: str) -> Optional[Section]:
    t = (title or "").strip()
    return next((s for s in doc.get("sections") or [] if s.get("title", "").strip() == t), None)


def add_section(doc: Doc, title: str, covers: List[str], after: Optional[str] = None) -> Section:
    """새 섹션 — after 가 있으면 그 뒤, 없으면 항목 순서 자리(사용자 정의 섹션은 끝)."""
    node: Section = {"step": new_section_id(), "title": title, "status": "empty", "covers": covers}
    sections: List[Section] = doc.setdefault("sections", [])
    if after:
        i = next((k for k, s in enumerate(sections) if s["step"] == after), None)
        if i is not None:
            sections.insert(i + 1, node)
            return node
    rank = rank_of(covers, doc.get("reportType"))
    at = next((k for k, s in enumerate(sections) if rank_of(s.get("covers") or [], doc.get("reportType")) > rank), None)
    sections.insert(len(sections) if at is None else at, node)
    return node


def set_section(doc: Doc, step: str, content: Optional[str], evidence: Optional[Dict[str, Any]] = None) -> Optional[Section]:
    sec = find_section(doc, step)
    if sec is None:
        return None
    if content is None or not content.strip():
        sec.pop("content", None)
        sec["status"] = "empty"
        (doc.get("evidence") or {}).pop(step, None)
    else:
        sec["content"] = content
        sec["status"] = "written"
        if evidence is not None:
            doc.setdefault("evidence", {})[step] = evidence
    return sec


def mark_ai_draft(doc: Doc, step: str, content: str) -> None:
    """AI 가 쓴 그대로를 섹션에 남긴다 — 사람이 얼마나 고쳤는지(품질 지표 '사용자 수정률')를 나중에 본다.
    근거 고정(앵커)도 여기서 — 인용 토큰·숫자의 원문 위치·글자·값을 저장 시점에 얼려 둔다."""
    sec = find_section(doc, step)
    if sec is None:
        return
    sec["aiDraft"] = {"text": content, "at": now_iso()}
    try:
        from app.anchors import pin_section

        pin_section(doc, sec)
    except ImportError:
        pass


VERSION_MAX = 20


def save_version(doc: Doc, label: str) -> Dict[str, Any]:
    """문서 판 — 그 시점의 섹션·설정·근거를 통째로 남긴다(최근 VERSION_MAX 개). 리서치로 바꿀 때·되돌리기 전에."""
    import copy as _copy

    from app.ids import id36, now_iso

    v = {
        "id": id36("v", 4),
        "at": now_iso(),
        "label": label,
        "written": len(written_sections(doc)),
        "sections": _copy.deepcopy(doc.get("sections") or []),
        "setup": _copy.deepcopy(doc.get("setup") or {}),
        "evidence": _copy.deepcopy(doc.get("evidence") or {}),
    }
    doc["versions"] = [*(doc.get("versions") or []), v][-VERSION_MAX:]
    return v


def restore_version(doc: Doc, version_id: str) -> bool:
    """그 판으로 되돌린다 — 지금 상태는 '되돌리기 전' 판으로 먼저 남긴다."""
    import copy as _copy

    v = next((x for x in doc.get("versions") or [] if x.get("id") == version_id), None)
    if v is None:
        return False
    save_version(doc, "되돌리기 전")
    doc["sections"] = _copy.deepcopy(v.get("sections") or [])
    doc["setup"] = _copy.deepcopy(v.get("setup") or {})
    doc["evidence"] = _copy.deepcopy(v.get("evidence") or {})
    return True


def log_section(doc: Doc, step: str, line: str) -> None:
    doc.setdefault("sectionLog", {}).setdefault(step, []).append(f"{now_iso()[:16]} {line}")


def written_sections(doc: Doc) -> List[Section]:
    return [s for s in doc.get("sections") or [] if s.get("status") == "written" and s.get("content")]


def public_session(doc: Doc) -> Doc:
    """FE 로 가는 세션 — 모델 히스토리는 뺀다(얕은 복사, 저장 문서를 고치지 않는다)."""
    return {k: v for k, v in doc.items() if k != "history"}
