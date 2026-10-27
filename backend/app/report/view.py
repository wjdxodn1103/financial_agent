"""리포트 뷰 — OP `paper/export/manuscript_view.py` 처럼 **BE 가 조립하고 FE 는 그리기만** 한다.

blocks:
  {"kind": "heading", "step", "text", "status"}            섹션 제목
  {"kind": "para", "step", "text", "cites": [...]}         본문 문단 — 출처 토큰은 `[n]` 으로 렌더, cites 는 표기 위치·앵커·문장
  {"kind": "list", "step", "items": [{"text", "cites"}]}   "- " 글머리표 문단
  {"kind": "empty", "step", "title", "desc"}               아직 안 쓴 섹션(누르면 "○○ 써줘")
  {"kind": "table" | "chart", "step", "blockId", …}        고정 양식의 표·그림(app/formats/blocks.py) — 섹션 글 뒤 고정 자리
sources: 리포트 전체에서 처음 인용된 순서로 번호 매긴 참고 자료 목록.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.agent.progress import progress
from app.agent.session import Doc
from app.agent.template import item_of, report_type
from app.docs.citations import render, strip_tokens, tokens
from app.docs.store import doc_label, load_meta
from app.formats.blocks import SheetIndex, section_format_blocks
from app.formats.registry import catalog, is_format

_BULLET = re.compile(r"^\s*(?:[-•·*▪]|\d{1,2}[.)])\s+")


class _Numbering:
    def __init__(self) -> None:
        self.order: Dict[str, int] = {}

    def __call__(self, doc_id: str) -> int:
        if doc_id not in self.order:
            self.order[doc_id] = len(self.order) + 1
        return self.order[doc_id]


def subtitle_of(doc: Doc) -> str:
    s = doc.get("setup") or {}
    parts = [report_type(doc.get("reportType"))["title"]]
    if s.get("subject"):
        parts.append(f"대상: {s['subject']}")
    if s.get("asOf"):
        parts.append(f"기준일: {s['asOf']}")
    if s.get("audience"):
        parts.append(f"독자: {s['audience']}")
    return " · ".join(parts)


def section_blocks(step: str, content: str, number_of: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for para in re.split(r"\n\s*\n", content.strip()):
        lines = [l for l in para.split("\n") if l.strip()]
        if not lines:
            continue
        if all(_BULLET.match(l) for l in lines):
            items = []
            for l in lines:
                text, cites = render(_BULLET.sub("", l).strip(), number_of)
                items.append({"text": text, "cites": cites})
            out.append({"kind": "list", "step": step, "items": items})
            continue
        text, cites = render("\n".join(l.strip() for l in lines), number_of)
        out.append({"kind": "para", "step": step, "text": text, "cites": cites})
    return out


def build_report_view(doc: Doc) -> Dict[str, Any]:
    numbering = _Numbering()
    blocks: List[Dict[str, Any]] = []
    chars = 0
    citations = 0
    sheets = SheetIndex(doc.get("documentIds") or []) if is_format(doc.get("reportType")) else None
    # 넣은 표·차트 번호 — 양식의 고정 표·그림 번호 뒤에서 이어 붙인다
    table_no = max([b.get("no") or 0 for b in catalog(doc.get("reportType")) if b.get("kind") == "table"] or [0]) if sheets is not None else 0
    chart_no = max([b.get("no") or 0 for b in catalog(doc.get("reportType")) if b.get("kind") == "chart"] or [0]) if sheets is not None else 0
    for s in doc.get("sections") or []:
        written = s.get("status") == "written" and bool(s.get("content"))
        blocks.append({"kind": "heading", "step": s["step"], "text": s["title"], "status": "written" if written else "empty"})
        if written:
            blocks.extend(section_blocks(s["step"], s["content"], numbering))
            chars += len(strip_tokens(s["content"]))
            citations += len(tokens(s["content"]))
        else:
            item = item_of((s.get("covers") or [""])[0], doc.get("reportType")) if s.get("covers") else None
            blocks.append(
                {
                    "kind": "empty",
                    "step": s["step"],
                    "title": s["title"],
                    "desc": s.get("guide") or (item or {}).get("desc") or "",
                    # 등록 양식의 표·차트 자리(아직 안 채운 것)
                    **({"slots": [{"kind": x.get("kind"), "title": x.get("title")} for x in s.get("slots") or []]} if s.get("slots") and not s.get("tables") else {}),
                }
            )
        if sheets is not None:
            # 고정 양식 — 섹션 글 뒤 고정 자리에 표·그림(글을 쓰기 전에도 보인다)
            blocks.extend(section_format_blocks(doc, s, numbering, sheets))
        for t in s.get("tables") or []:
            # 리서치에서 넣은 표·차트 — 넣을 때의 복사본(research/block.py·chart.py 모양)
            b = {**(t.get("block") or {}), "step": s["step"], "insertedId": t.get("id")}
            if b.get("kind") == "chart":
                chart_no += 1
                b["no"] = chart_no
                b["label"] = f"<그림 {chart_no}> {b.get('caption') or b.get('title') or ''}"
            else:
                table_no += 1
                b["no"] = table_no
                b["label"] = f"<표 {table_no}> {b.get('caption') or b.get('title') or ''}"
            for d in b.get("sourceDocIds") or []:
                numbering(d)
            blocks.append(b)
    sources: List[Dict[str, Any]] = []
    for doc_id, n in numbering.order.items():
        meta: Optional[Dict[str, Any]] = load_meta(doc_id)
        card = (meta or {}).get("card") or {}
        sources.append(
            {
                "n": n,
                "docId": doc_id,
                "label": doc_label(meta, doc_id),
                "docType": card.get("docType") or "",
                "date": card.get("date") or "",
                "issuer": card.get("issuer") or "",
                "fileName": (meta or {}).get("fileName") or "",
                "missing": meta is None,
            }
        )
    p = progress(doc)
    sections = doc.get("sections") or []
    setup = doc.get("setup") or {}
    return {
        "title": setup.get("title") or "제목 없는 리포트",
        "subtitle": subtitle_of(doc),
        "blocks": blocks,
        "sources": sources,
        "progress": p["entries"],
        "stats": {
            "sections": len(sections),
            "written": sum(1 for s in sections if s.get("status") == "written"),
            "chars": chars,
            "citations": citations,
            "documents": len(sources),
            "required": p["required"],
            "requiredCovered": p["requiredCovered"],
        },
        # 이 문서 양식의 표·차트 양식(샘플로 만든 양식만) — 섹션의 '표·차트 넣기' 목록
        "forms": list(report_type(doc.get("reportType")).get("assets") or []) if (doc.get("reportType") or "").startswith("rt:") else [],
    }


def source_line(src: Dict[str, Any]) -> str:
    extra = ", ".join(x for x in (src.get("issuer"), src.get("docType"), src.get("date")) if x)
    return f"[{src['n']}] {src['label']}" + (f" ({extra})" if extra else "") + (f" — {src['fileName']}" if src.get("fileName") else "")
