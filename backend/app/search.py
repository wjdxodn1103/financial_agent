"""통합 검색 — 워크스페이스 **안**의 에셋(표·차트)·문서 제목·데이터 파일·폴더·자료 문단·원장 수치·팀 기록·채널·작업 항목·리포트 섹션을 한 번에.

이름으로 찾는 묶음(에셋·문서·데이터 파일·폴더)을 본문보다 앞에 둔다 — '저번에 만든 Peer 표'처럼 이름을 기억해 찾는 일이 많다.
에셋은 드라이브 ▸ 에셋과 같은 규칙(research/assets.py — 종류·범위·날짜 말을 읽는다). 대화만 한 작업(문서 없음)은 내 것만.

자료 문단은 리포트 작성과 같은 검색(BM25+벡터, store.search_docs). 나머지는 낱말 일치(질의 낱말이 모두 들어간 것 먼저,
없으면 하나라도). 사내 공용 데이터는 찾고, 다른 워크스페이스·공용 자료실에서 붙이지 않은 자료는 찾지 않는다.
리포트 섹션은 리포트 본문(멤버 모두가 보는 것)만 — 에이전트 대화(작성자 개인)는 찾지 않는다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

from sqlmodel import Session, select

from app.auth import require_member
from app.db import ChannelMessage, ReportSession, Task, TeamRecord, User, iso, scope_ids
from app.docs.citations import strip_tokens
from app.docs.store import doc_label, load_meta, search_docs
from app.agent.modes import has_doc
from app.agent.template import report_type
from app.drive import hidden_items, name_hits
from app.ledger.service import ledger_for
from app.records.service import RECORD_TYPES

PER_KIND = 6
TASK_KO = {"todo": "할 일", "doing": "진행", "review": "검토", "done": "완료"}


def _terms(q: str) -> List[str]:
    return [t for t in re.split(r"\s+", (q or "").strip().lower()) if t]


def _snippet(text: str, terms: List[str], width: int = 140) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    low = t.lower()
    at = min((low.find(x) for x in terms if x in low), default=0)
    start = max(0, at - width // 3)
    return ("…" if start else "") + t[start : start + width] + ("…" if start + width < len(t) else "")


def _rank(items: Iterable[Tuple[str, Dict[str, Any]]], terms: List[str]) -> List[Dict[str, Any]]:
    """(검색 대상 글, 결과) → 낱말이 모두 든 것 먼저, 그다음 많이 든 순. 하나도 없으면 뺀다."""
    scored = []
    for text, item in items:
        low = (text or "").lower()
        n = sum(1 for t in terms if t in low)
        if n:
            scored.append((n == len(terms), n, item))
    scored.sort(key=lambda x: (not x[0], -x[1]))
    return [x[2] for x in scored[:PER_KIND]]


def search_workspace(session: Session, workspace_id: str, user: User, q: str) -> Dict[str, Any]:
    ws, _m = require_member(session, workspace_id, user)
    terms = _terms(q)
    if not terms:
        return {"query": q, "groups": []}
    names = {u.id: f"{u.name} {u.title}".strip() for u in session.exec(select(User)).all()}
    hidden = hidden_items(session, workspace_id, user.id)
    doc_ids = [d for d in scope_ids(ws) if d not in hidden]  # 사내 공용 + 이 워크스페이스 데이터(AI 참고를 끈 것도 찾기는 된다, 나에게 안 보이는 폴더 속은 빼고)

    # 자료 문단 — 리포트 작성과 같은 검색
    docs: List[Dict[str, Any]] = []
    if doc_ids:
        for h in search_docs(doc_ids, q, k=PER_KIND, per_doc=2, lexical=True):
            c = h["chunk"]  # 검색 결과는 문단 dict 를 그대로 준다
            if "bm25" not in h["via"] and not any(t in (c.get("text") or "").lower() for t in terms):
                continue  # 벡터만 가까운 문단은 낱말이 하나도 없으면 뺀다(검색창은 '찾기'라 엉뚱한 문단이 더 해롭다)
            docs.append({"kind": "document", "docId": h["docId"], "chunk": c.get("id"), "title": doc_label(load_meta(h["docId"]), h["docId"]), "sub": f"p.{c['page']}" if c.get("page") else (c.get("heading") or ""), "text": _snippet(c.get("text") or "", terms)})

    # 원장 수치
    led = ledger_for(session, workspace_id)
    by_fid = {f["fid"]: f for f in led["figures"]}
    figs = _rank(
        (
            (f"{g['metric']} {g['metricKey']} {g['period']} {g.get('basis') or ''}", {
                "kind": "figure",
                "key": g["key"],
                "title": f"{g['metric']} · {g['period']}{' · ' + g['basis'] if g.get('basis') else ''}",
                "text": " / ".join(v["display"] for v in g["values"]),
                "sub": "채택값 있음" if g.get("chosen") else ("자료마다 다름" if g["conflict"] else f"{g['documents']}개 자료"),
                "docId": (by_fid.get(g["figureIds"][0]) or {}).get("doc"),
                "chunk": (by_fid.get(g["figureIds"][0]) or {}).get("chunk"),
                "cell": (by_fid.get(g["figureIds"][0]) or {}).get("cell"),
            })
            for g in led["groups"]
        ),
        terms,
    )

    # 팀 기록(확정·후보)
    recs = _rank(
        (
            (f"{r.text} {' '.join(q.get('text') or '' for q in r.quotes or [])} {r.scope}", {
                "kind": "record",
                "id": r.id,
                "title": f"[{RECORD_TYPES.get(r.type, r.type)}] {r.text}",
                "text": _snippet(" ".join(q.get("text") or "" for q in r.quotes or []) or r.text, terms),
                "sub": f"{'확정' if r.status == 'confirmed' else '후보' if r.status == 'candidate' else '이전 결정'} · {names.get(r.author_id or '', '')}",
                "at": iso(r.confirmed_at or r.created_at),
            })
            for r in session.exec(select(TeamRecord).where(TeamRecord.workspace_id == workspace_id, TeamRecord.status != "dismissed")).all()
        ),
        terms,
    )

    # 채널
    msgs = _rank(
        (
            (m.text, {"kind": "message", "id": m.id, "title": names.get(m.user_id or "", "에이전트" if m.kind == "agent" else "알림"), "text": _snippet(m.text, terms), "sub": "스레드 답글" if m.thread_id else "", "at": iso(m.created_at), "threadId": m.thread_id})
            for m in session.exec(select(ChannelMessage).where(ChannelMessage.workspace_id == workspace_id).order_by(ChannelMessage.created_at.desc())).all()  # type: ignore[attr-defined]
            if m.text and not (m.meta or {}).get("pending")
        ),
        terms,
    )

    # 작업 항목
    tasks = _rank(
        ((f"{t.title} {t.detail}", {"kind": "task", "id": t.id, "title": t.title, "text": _snippet(t.detail or "", terms), "sub": f"{TASK_KO.get(t.status, t.status)} · 담당 {names.get(t.assignee_id or '', '없음')}"}) for t in session.exec(select(Task).where(Task.workspace_id == workspace_id)).all()),
        terms,
    )

    # 리포트 섹션 본문
    def sections() -> Iterable[Tuple[str, Dict[str, Any]]]:
        for r in session.exec(select(ReportSession).where(ReportSession.workspace_id == workspace_id)).all():
            for s in (r.doc or {}).get("sections") or []:
                body = strip_tokens(s.get("content") or "")
                if body:
                    yield f"{s.get('title') or ''} {body}", {"kind": "report", "reportId": r.id, "step": s.get("step"), "title": f"{r.title or '제목 없는 리포트'} › {s.get('title') or ''}", "text": _snippet(body, terms), "sub": names.get(r.created_by, "")}

    reports = _rank(sections(), terms)

    named = name_hits(session, ws, user, q, folder_max=PER_KIND, data_max=PER_KIND)
    groups = [
        {"kind": "asset", "label": "표·차트·메모", "items": asset_hits(session, workspace_id, user, q)},
        {"kind": "doc", "label": "문서", "items": doc_hits(session, workspace_id, user, terms, names)},
        {"kind": "file", "label": "데이터 파일", "items": [{"kind": "file", "docId": d["id"], "title": d["label"], "sub": " · ".join(x for x in (d["path"], d.get("fileName")) if x)} for d in named["data"]]},
        {"kind": "folder", "label": "폴더", "items": [{"kind": "folder", "id": f["id"], "title": f["name"], "sub": " · ".join(x for x in (f["path"], f"{f['items']}개") if x)} for f in named["folders"]]},
        {"kind": "document", "label": "자료 문단", "items": docs},
        {"kind": "figure", "label": "근거 원장", "items": figs},
        {"kind": "record", "label": "팀 기록", "items": recs},
        {"kind": "report", "label": "리포트", "items": reports},
        {"kind": "message", "label": "대화", "items": msgs},
        {"kind": "task", "label": "할 일", "items": tasks},
    ]
    return {"query": q, "groups": [g for g in groups if g["items"]]}


def asset_hits(session: Session, workspace_id: str, user: User, q: str, limit: int = PER_KIND) -> List[Dict[str, Any]]:
    from app.research.assets import asset_item, search_assets

    rows, parsed = search_assets(session, workspace_id, user, q, limit=limit, min_weight=2)
    if not (parsed["terms"] or parsed.get("kind") or parsed.get("since")):
        return []  # '찾아줘' 같은 군말뿐이면 에셋 전부를 늘어놓지 않는다
    out = []
    for r in rows:
        a = asset_item(session, r, user)
        shape = ("꺾은선 차트" if a.get("chartType") == "line" else "막대 차트") if a["kind"] == "chart" else f"표 {a['rows']}행 × {a['cols']}열"
        out.append({"kind": "asset", "id": a["id"], "title": a["title"], "sub": " · ".join(x for x in (shape, a.get("period") and f"{a['period']} 기준", None if a["mine"] else a["createdBy"], "드라이브에 저장" if a["saved"] else None) if x), "at": a["updatedAt"], "taskId": a["taskId"]})
    return out


def doc_hits(session: Session, workspace_id: str, user: User, terms: List[str], names: Dict[str, str]) -> List[Dict[str, Any]]:
    """문서 제목·대상·유형 — 멤버가 보는 문서(숨은 폴더 속 제외) + 내 대화만 한 작업."""
    hidden = hidden_items(session, workspace_id, user.id)

    def rows() -> Iterable[Tuple[str, Dict[str, Any]]]:
        for r in session.exec(select(ReportSession).where(ReportSession.workspace_id == workspace_id)).all():
            doc = r.doc or {}
            if r.id in hidden or (not has_doc(doc) and r.created_by != user.id):
                continue
            setup = doc.get("setup") or {}
            kind = report_type(r.report_type)["title"] if has_doc(doc) else "대화"
            sections = doc.get("sections") or []
            yield f"{r.title} {setup.get('subject') or ''} {kind}", {
                "kind": "doc",
                "reportId": r.id,
                "title": r.title or ("제목 없는 리포트" if has_doc(doc) else "새 작업"),
                "sub": " · ".join(x for x in (kind, setup.get("subject"), f"{sum(1 for s in sections if s.get('status') == 'written')}/{len(sections)} 섹션" if sections else None, names.get(r.created_by, "")) if x),
                "at": iso(r.updated_at),
            }

    return _rank(rows(), terms)


__all__ = ["asset_hits", "doc_hits", "search_workspace"]
