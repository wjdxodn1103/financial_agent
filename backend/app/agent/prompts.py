"""프롬프트 조립 — 파일(prompts/*.txt)이 정본, 여기서는 동적 블록만 붙인다."""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

from app.agent.progress import status_text
from app.agent.session import Doc
from app.docs.search_tool import doc_index_lines
from app.formats.registry import doc_block_spec, doc_catalog, has_blocks, label, section_blocks_of
from app.records.service import notes_lines

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


@lru_cache(maxsize=None)
def load(name: str) -> str:
    return (PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()


def fill(name: str, values: Dict[str, Any]) -> str:
    out = load(name)
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def setup_lines(doc: Doc) -> list[str]:
    s = doc.get("setup") or {}
    pairs = [("제목", s.get("title")), ("대상", s.get("subject")), ("기준일", s.get("asOf")), ("독자", s.get("audience"))]
    return [f"{k}: {v}" for k, v in pairs if v]


DOC_LINES_MAX = 30


def _current_table(doc: Doc) -> str:
    cur = doc.get("_current") or None
    if not cur:
        return "(없음)"
    data = cur.get("data") or {}
    if data.get("text") is not None:  # 메모
        return f"메모 '{cur['title']}' — " + data["text"][:300]
    rows = ", ".join(s["label"] for s in data.get("subjects") or [])
    cols = ", ".join(it["label"] for it in data.get("items") or [] if not it.get("hidden"))
    period = (data.get("period") or {}).get("label")
    return f"'{cur['title']}' — 행: {rows} / 열: {cols}" + (f" / 기준 {period}" if period else "")


def chat_system(doc: Doc, modes: Optional[Dict[str, bool]] = None) -> str:
    """기본(역할·말투) + 고른 모드의 블록 — 일반(도구 없음) / 리서치(자료 찾기 + 데이터 정리) / 문서 작성(자료 찾기 + 양식대로 쓰기)."""
    from app.research.service import template_line

    modes = modes or {"research": False, "writing": True}
    research, writing = bool(modes.get("research")), bool(modes.get("writing"))
    parts = [fill("chat_base", {"today": date.today().isoformat()})]
    if not research and not writing:
        parts.append(load("chat_plain"))
        if doc.get("decisions"):
            parts.append("## 앞선 대화 메모\n" + "\n".join(doc["decisions"][-8:]))
        return "\n\n".join(parts)
    parts.append(load("chat_lookup"))
    parts.append("## 지금 보는 표·메모\n" + _current_table(doc))
    if research:
        parts.append(load("chat_research"))
        parts.append("## 표 양식\n" + ("\n".join(template_line(t) for t in doc.get("_templates") or []) or "(없음)"))
    if doc.get("_forms"):
        from app.research.forms import form_line

        how = "build_table·build_chart·extract_table 의 form" if research else "insert_form"
        parts.append(
            f"## 이 문서 양식의 표·차트 양식({how} 에 F번호 — 열·머리 묶음·차트 종류·축·색이 양식대로)\n"
            + "\n".join(form_line(i, a) for i, a in enumerate(doc["_forms"]))
            + "\n- 사용자가 이 양식들로 표·차트를 만들자고 하면 쓴다. 값은 자료에서만 — 못 찾은 칸은 빈 칸으로 두고 지어내지 않는다."
            + "\n- 행(대상 — 지수·기업·기간)이 대화·자료 목록에서 분명할 때만 rows 에 넣고, 아니면 사용자에게 묻는다. 자료 속에 같은 내용의 표가 있으면 document(+table)로 옮긴다."
        )
    if writing:
        parts.append(load("chat_writing"))
        parts.append("## 지금 문서\n" + "\n".join([*setup_lines(doc), status_text(doc)]))
        if doc.get("_formats") and (doc.get("reportType") or "free") == "free":
            parts.append("## 문서 양식(use_format — 아직 양식이 없다)\n" + "\n".join(f"- {f['title']}" for f in doc["_formats"]))
    docs = doc_index_lines(doc.get("documentIds") or [])
    more = f"\n… 외 {len(docs) - DOC_LINES_MAX}건" if len(docs) > DOC_LINES_MAX else ""
    parts.append("## 이 작업의 데이터\n" + (("\n".join(docs[:DOC_LINES_MAX]) + more) if docs else "없음 — 데이터 질문에는 드라이브에서 파일을 올리거나 이 작업에서 쓸 데이터를 켜 달라고 안내한다."))
    if writing and has_blocks(doc):
        lines = []
        for s in doc.get("sections") or []:
            ids = section_blocks_of(doc, s)
            lines.append(f"- [{s['step']}] {s['title']}: " + (", ".join(label(doc_block_spec(doc, b)) for b in ids) if ids else "표·그림 없음"))
        parts.append(
            "## 이 양식의 표·그림(섹션 뒤 고정 자리 — 숫자는 코드가 자료에서 채운다. 붙이기 add_block · 빼기 remove_block)\n"
            + "\n".join(lines)
            + "\n양식 목록: " + ", ".join(f"{label(b)}[{b['id']}]" for b in doc_catalog(doc))
        )
        if doc.get("layout"):
            # 양식 2.0 틀 문서 — 소제목은 회사마다 다른 주장 한 줄. 목차를 사용자와 정한다
            parts.append(
                "## 이 문서의 틀(문서 양식 2.0 — 장 아래 소주제 섹션)\n"
                + "\n".join(f"- {p['title']}: " + ", ".join(f"[{s['step']}] {s['title']}" for s in doc.get("sections") or [] if s.get("part") == p["id"])
                            for p in doc["layout"].get("parts") or [] if p.get("role") == "chapter")
                + "\n- 지금 섹션 제목(기업 소개·주요 고객 등)은 양식의 '자리 이름'일 뿐이다. 소제목은 원본처럼 이 회사에 대한 주장 한 줄(25자 안팎, 예: '○○는 로봇용 정밀 부품 전문기업', '주력 제품 매출 비중 확대')로 바꾼다."
                "\n- 사용자가 목차·소제목을 물으면 먼저 소주제 자리마다 따로 search_documents 를 불러 자료를 찾고(여러 자리를 한 질의에 묶지 않는다. kind 는 비워 표·본문을 함께 본다 — 매출 구성·지분은 대개 표에 있다), 장마다 소주제 자리별로 [주장 한 줄 소제목 | 다룰 내용 | 근거 자료] 를 제안한다. 자리 이름을 그대로 되풀이하지 않는다."
                " 자료에 근거가 없는 자리는 소제목을 지어내지 말고 '자료 없음 — 필요한 자료: …' 로 둔다."
                "\n- 사용자가 정하면 update_outline 으로 반영한다(rename = 소제목 바꾸기, add = 장에 소주제 더하기(part 에 장 제목), remove = 빼기). 장 자체는 바꾸지 않는다."
            )
    notes = notes_lines(doc.get("teamNotes") or [])
    if notes:
        parts.append("## 팀 기록(워크스페이스 멤버가 확정한 결정·지시·방침 — 따른다. 사용자가 물으면 작성자·날짜와 원문을 그대로 알려 준다)\n" + "\n".join(notes[:12]))
    if doc.get("_criteria"):
        from app.criteria.prompting import criteria_lines

        parts.append("## 판단 기준(승인된 사내·워크스페이스 기준 — 해석·제안의 틀로 쓴다. 조건 도달 여부는 줄의 코드 판정만 따르고, 도달한 기준은 그 방향을 '○○ 검토 제안(기준 이름·판)'으로만 알린다)\n"
                     + "\n".join(criteria_lines(doc["_criteria"])))
    if doc.get("decisions"):
        parts.append("## 앞선 대화 메모\n" + "\n".join(doc["decisions"][-8:]))
    return "\n\n".join(parts)
