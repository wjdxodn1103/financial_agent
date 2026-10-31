"""리포트 뷰 — OP `paper/export/manuscript_view.py` 처럼 **BE 가 조립하고 FE 는 그리기만** 한다.

blocks:
  {"kind": "heading", "step", "text", "status"}            섹션 제목
  {"kind": "para", "step", "text", "cites": [...]}         본문 문단 — 출처 토큰은 `[n]` 으로 렌더, cites 는 표기 위치·앵커·문장
  {"kind": "list", "step", "items": [{"text", "cites"}]}   "- " 글머리표 문단
  {"kind": "empty", "step", "title", "desc"}               아직 안 쓴 섹션(누르면 "○○ 써줘")
  {"kind": "table" | "chart", "step", "blockId", …}        고정 양식의 표·그림(app/formats/blocks.py) — 섹션 글 뒤 고정 자리
양식 2.0 틀 문서(doc["layout"]):
  {"kind": "band", "part", "no", "text", "band": bool, "role"}  장이 바뀌는 곳의 장 띠(부록은 band 거짓 — 제목만)
  heading 에 depth·no(장 안 소제목 번호)·role(summary|subsection), para 에 role(claim = '[제목]' 줄, keyline = '[핵심]' 줄 묶음)
  {"kind": "subhead", "step", "text"}                      소주제 안 작은 제목('### …' 줄)
  {"kind": "table", "formId", "position": main|sidebar, "calcs", …}  틀의 표 양식을 원장으로 채운 표(research/form_rows) · {"kind": "figure", "placeholder"} 그림 자리
    본문의 '[그림: 제목]'·'[표: 제목]' 줄 자리에 놓인다(place_slots). 자리 줄이 없으면 섹션 글 뒤
  view["theme"] = 틀의 테마(색·크기), view["layout"] = 부분 목록
sources: 리포트 전체에서 처음 인용된 순서로 번호 매긴 참고 자료 목록.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.agent.progress import progress
from app.agent.session import Doc
from app.agent.template import item_of, report_type
from app.docs.citations import render, strip_tokens, tokens
from app.docs.store import doc_label, load_meta
from app.formats.blocks import SheetIndex, layout_blocks, section_format_blocks
from app.formats.registry import catalog, doc_catalog, is_format

_BULLET = re.compile(r"^\s*(?:[-•·*▪]|\d{1,2}[.)])\s+")
_TAG = re.compile(r"^\s*\[(제목|핵심)\]\s*")
_SLOT = re.compile(r"^\s*\[(그림|표)\s*:\s*([^\]]+)\]\s*$")
_SUBHEAD = re.compile(r"^\s*#{2,4}\s+(.+?)\s*#*\s*$")
_CLAIM_LABEL = re.compile(r"(?:^|(?<=\n\n))\s*\[(?!제목\]|핵심\]|그림\s*:|표\s*:)[^\]\d\n]{1,8}\]\s*")
_LAYOUT_LINE = re.compile(r"^(\s*#{2,4}\s+.+)$|\s*(\[(?:그림|표)\s*:\s*[^\]]+\])\s*", re.M)  # 작은 제목 줄 · 자리 줄(문단 끝에 붙여 써도 떼어 낸다)


def _key(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", s or "").lower()


def place_slots(body: List[Dict[str, Any]], fmt: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """본문 속 자리 줄(slot)에 제목이 맞는 표·그림 블록을 놓는다 → (놓은 본문, 못 놓은 블록 — 섹션 끝에 붙는다). 못 맞춘 자리 줄은 지운다."""
    left = list(fmt)
    out: List[Dict[str, Any]] = []
    for b in body:
        if b.get("kind") != "slot":
            out.append(b)
            continue
        k = _key(b["ref"])
        title = lambda x: _key(x.get("title") or x.get("label") or "")  # noqa: E731
        hit = next((x for x in left if title(x) == k), None) or next((x for x in left if k and title(x) and (k in title(x) or title(x) in k)), None)
        if hit is not None:
            left.remove(hit)
            out.append(hit)
    return out, left


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


def section_blocks(step: str, content: str, number_of: Any, layout: bool = False, summary: bool = False) -> List[Dict[str, Any]]:
    """본문 → 문단·목록 블록. 문단 첫 줄 '[제목] …' = 요약 주장(role claim), 맨 앞 '[핵심] …' 줄들 = 핵심 문장 묶음(role keyline, 양식 2.0).
    틀 문서(layout)는 '### 작은 제목' 줄 = subhead, '[그림: 제목]'·'[표: 제목]' 줄 = slot(그 자리에 표·그림 블록 — build_report_view 가 놓는다).
    요약 자리(summary)는 '[실적] …' 처럼 분류 이름을 붙인 첫 줄도 주장으로 읽는다(모델이 '[제목]' 대신 쓰는 일이 있다, 2026-10-30 실측)."""
    out: List[Dict[str, Any]] = []
    if layout:
        content = _LAYOUT_LINE.sub(lambda m: "\n\n" + (m.group(1) or m.group(2)).strip() + "\n\n", content)
    if summary:
        content = _CLAIM_LABEL.sub("[제목] ", content)
    for para in re.split(r"\n\s*\n", content.strip()):
        lines = [l for l in para.split("\n") if l.strip()]
        if not lines:
            continue
        if layout and len(lines) == 1:
            sm = _SLOT.match(lines[0])
            if sm:
                out.append({"kind": "slot", "step": step, "ref": sm.group(2).strip(), "slotKind": "table" if sm.group(1) == "표" else "figure"})
                continue
            hm = _SUBHEAD.match(lines[0])
            if hm:
                out.append({"kind": "subhead", "step": step, "text": render(hm.group(1).strip(), number_of)[0]})
                continue
        tagged = []
        while lines and _TAG.match(lines[0]):
            tagged.append(lines.pop(0))
        if tagged:
            kind = _TAG.match(tagged[0]).group(1)
            text, cites = render("\n".join(_TAG.sub("", l).strip() for l in tagged), number_of)
            out.append({"kind": "para", "step": step, "text": text, "cites": cites, "role": "claim" if kind == "제목" else "keyline"})
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
    layout = doc.get("layout") or None
    sheets = SheetIndex(doc.get("documentIds") or []) if is_format(doc.get("reportType")) else None
    # 넣은 표·차트 번호 — 양식의 고정 표·그림 번호 뒤에서 이어 붙인다(틀 문서는 원본처럼 번호 없이 제목만)
    table_no = max([b.get("no") or 0 for b in catalog(doc.get("reportType")) if b.get("kind") == "table"] or [0]) if sheets is not None else 0
    chart_no = max([b.get("no") or 0 for b in catalog(doc.get("reportType")) if b.get("kind") == "chart"] or [0]) if sheets is not None else 0
    parts = {p["id"]: p for p in (layout or {}).get("parts") or []}
    cur_part: Optional[str] = None
    chap_no = 0
    sub_no = 0
    for s in doc.get("sections") or []:
        written = s.get("status") == "written" and bool(s.get("content"))
        head: Dict[str, Any] = {"kind": "heading", "step": s["step"], "text": s["title"], "status": "written" if written else "empty"}
        if layout:
            part = s.get("part") or ""
            if part != cur_part:
                cur_part = part
                sub_no = 0
                p = parts.get(part) or {}
                if p.get("role") == "chapter":
                    chap_no += 1
                    blocks.append({"kind": "band", "part": part, "no": chap_no, "text": p.get("title") or "", "band": bool(p.get("band")), "role": "chapter"})
            sub_no += 1
            head.update({"depth": s.get("depth") or 1, "role": s.get("role") or "", "no": sub_no if s.get("role") == "subsection" else None})
        blocks.append(head)
        body = section_blocks(s["step"], s["content"], numbering, layout=bool(layout), summary=bool(layout) and s.get("role") == "summary") if written else []
        fmt = section_format_blocks(doc, s, numbering, sheets) if sheets is not None or layout else []
        if layout and body:
            body, fmt = place_slots(body, fmt)  # 본문의 '[그림: …]'·'[표: …]' 줄 자리에 표·그림(원본 짜임대로)
        if written:
            blocks.extend(body)
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
        # 고정 양식·틀 문서 — 섹션 글 뒤 고정 자리에 표·그림(글을 쓰기 전에도 보인다). 틀 문서는 자리 줄에 못 놓인 것만
        blocks.extend(fmt)
        for t in s.get("tables") or []:
            # 리서치에서 넣은 표·차트 — 넣을 때의 복사본(research/block.py·chart.py 모양)
            b = {**(t.get("block") or {}), "step": s["step"], "insertedId": t.get("id")}
            if layout:
                b["label"] = b.get("caption") or b.get("title") or ""
            elif b.get("kind") == "chart":
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
    # 틀 문서의 부록(재무표 등) — 섹션이 아닌 부분, 표만
    for p in (layout or {}).get("parts") or []:
        if p.get("role") == "appendix" and p.get("blocks"):
            blocks.append({"kind": "band", "part": p["id"], "no": None, "text": p.get("title") or "부록", "band": False, "role": "appendix"})
            blocks.extend(layout_blocks(doc, p["blocks"], f"part:{p['id']}", numbering))
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
        # 이 문서 양식의 표·차트 양식(샘플로 만든 양식만) — 섹션의 '표·차트 넣기' 목록. 틀 문서는 문서에 복사된 틀의 표 양식
        "forms": ([{"id": f["id"], "kind": f["kind"], "name": f.get("title") or "", "desc": "", "chartType": ""} for f in doc_catalog(doc)]
                  if layout else list(report_type(doc.get("reportType")).get("assets") or []) if (doc.get("reportType") or "").startswith("rt:") else []),
        **({"theme": layout.get("theme") or {}, "layout": {"parts": [{"id": p["id"], "role": p["role"], "title": p.get("title") or ""} for p in layout.get("parts") or []],
                                                         "page": layout.get("page") or {}}} if layout else {}),
    }


def source_line(src: Dict[str, Any]) -> str:
    extra = ", ".join(x for x in (src.get("issuer"), src.get("docType"), src.get("date")) if x)
    return f"[{src['n']}] {src['label']}" + (f" ({extra})" if extra else "") + (f" — {src['fileName']}" if src.get("fileName") else "")
