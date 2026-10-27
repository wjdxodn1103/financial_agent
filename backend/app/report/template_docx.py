"""DOCX 양식 — 등록한 Word 파일을 **그대로** 결과물의 틀로 쓴다(서식은 코드가 원본을 재사용, LLM 은 서식을 만들지 않는다).

 parse_template: 제목 스타일(Heading/제목·개요 수준) 문단 → 섹션 목록 [{title, level, guide}]. 제목 아래 안내문(작성 요령)은 guide 로 —
                 작성기가 그 섹션의 작성 지침으로 받는다.
 fill_template:  원본 파일을 열어 섹션마다 제목 아래 안내문을 지우고 본문을 넣는다. 본문 문단은 안내문 문단의 서식(문단 스타일·첫 글자 서식)을
                 복제해서 만든다 — 글꼴·크기·색이 양식 그대로. 쓰지 않은 섹션은 안내문을 남긴다. 표·머리글·바닥글·표지는 손대지 않는다.
                 끝에 "참고 자료" 목록을 붙인다(마지막 1수준 제목의 서식으로).
"""
from __future__ import annotations

import io
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from app.report.view import build_report_view, source_line

GUIDE_MAX = 600
_HEADING_STYLE = re.compile(r"^(heading|제목|title)\s*(\d)?", re.I)


class TemplateError(ValueError):
    pass


def _level(p: Paragraph) -> Optional[int]:
    """제목 문단이면 수준(1~), 아니면 None — 스타일 이름(Heading n/제목 n) 또는 개요 수준(outlineLvl)."""
    style = p.style
    name = (style.name if style is not None else "") or ""
    m = _HEADING_STYLE.match(name)
    if m and p.text.strip():
        if m.group(1).lower() == "title":
            return 0
        return int(m.group(2) or 1)
    ppr = p._p.pPr
    lvl = ppr.find(qn("w:outlineLvl")) if ppr is not None else None
    if lvl is None and style is not None and style.element.pPr is not None:
        lvl = style.element.pPr.find(qn("w:outlineLvl"))
    if lvl is not None and p.text.strip():
        v = int(lvl.get(qn("w:val")) or 9)
        return v + 1 if v < 9 else None
    return None


def _body_items(doc: Any) -> List[Tuple[str, Any]]:
    """본문 순서대로 ('p', Paragraph) / ('tbl', 요소)."""
    out: List[Tuple[str, Any]] = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            out.append(("p", Paragraph(child, doc)))
        elif tag == "tbl":
            out.append(("tbl", child))
    return out


def parse_template(path: str | Path) -> Dict[str, Any]:
    try:
        d = Document(str(path))
    except Exception as e:  # noqa: BLE001
        raise TemplateError("DOCX 파일을 열지 못했습니다(Word 문서인지 확인해 주세요).") from e
    items = _body_items(d)
    headings: List[Dict[str, Any]] = []
    for kind, it in items:
        if kind != "p":
            continue
        lvl = _level(it)
        text = re.sub(r"\s+", " ", it.text).strip()
        if lvl is not None and lvl >= 1 and text:
            headings.append({"title": text, "level": lvl, "guide": ""})
        elif headings and text:
            g = headings[-1]["guide"]
            if len(g) < GUIDE_MAX:
                headings[-1]["guide"] = (g + " " + text).strip()[:GUIDE_MAX]
    if not headings:
        raise TemplateError("제목 스타일(Heading·제목 1~3)을 쓴 문단이 없습니다. Word 에서 섹션 이름에 제목 스타일을 지정한 양식을 올려 주세요.")
    top = min(h["level"] for h in headings)
    # 섹션은 가장 높은 두 수준까지(그 아래 소제목은 안내문처럼 본문 지침에 합친다)
    sections = [h for h in headings if h["level"] <= top + 1]
    return {"headings": sections, "levels": sorted({h["level"] for h in headings})}


# ── 채우기 ──────────────────────────────────────────────────────────────

def _proto_run_rpr(p_elm: Any) -> Optional[Any]:
    r = p_elm.find(qn("w:r"))
    return deepcopy(r.find(qn("w:rPr"))) if r is not None and r.find(qn("w:rPr")) is not None else None


def _new_para(proto: Any, text: str, keep_numbering: bool = False) -> Any:
    new = OxmlElement("w:p")
    ppr = proto.find(qn("w:pPr")) if proto is not None else None
    if ppr is not None:
        ppr = deepcopy(ppr)
        if not keep_numbering:
            num = ppr.find(qn("w:numPr"))
            if num is not None:
                ppr.remove(num)
        new.append(ppr)
    run = OxmlElement("w:r")
    rpr = _proto_run_rpr(proto) if proto is not None else None
    if rpr is not None:
        run.append(rpr)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    run.append(t)
    new.append(run)
    return new


def _blocks_by_step(doc: Dict[str, Any]) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Any]]:
    view = build_report_view(doc)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for b in view["blocks"]:
        if b["kind"] in ("para", "list"):
            out.setdefault(b["step"], []).append(b)
    return out, view


def fill_template(template_path: str | Path, doc: Dict[str, Any]) -> bytes:
    d = Document(str(template_path))
    blocks, view = _blocks_by_step(doc)
    sections = doc.get("sections") or []
    by_title = {re.sub(r"\s+", " ", s.get("title") or "").strip(): s for s in sections}
    items = _body_items(d)
    # 제목 문단 위치
    heads: List[int] = [i for i, (k, it) in enumerate(items) if k == "p" and _level(it) is not None and (_level(it) or 0) >= 1]
    styles = {s.name for s in d.styles}
    last_h1: Optional[Any] = None
    for n, hi in enumerate(heads):
        p = items[hi][1]
        title = re.sub(r"\s+", " ", p.text).strip()
        if (_level(p) or 9) <= 1:
            last_h1 = p._p
        sec = by_title.get(title)
        if sec is None or sec.get("status") != "written" or not blocks.get(sec["step"]):
            continue
        end = heads[n + 1] if n + 1 < len(heads) else len(items)
        guide = [it for k, it in items[hi + 1 : end] if k == "p"]
        proto = next((g._p for g in guide if g.text.strip()), None)
        for g in guide:
            if g.text.strip():
                g._p.getparent().remove(g._p)
        anchor = p._p
        for b in blocks[sec["step"]]:
            if b["kind"] == "para":
                for line in b["text"].split("\n"):
                    anchor.addnext(new := _new_para(proto, line))
                    anchor = new
            else:
                for it in b["items"]:
                    if "List Bullet" in styles and proto is None:
                        para = d.add_paragraph(it["text"], style="List Bullet")
                        el = para._p
                        el.getparent().remove(el)
                    else:
                        el = _new_para(proto, f"• {it['text']}")
                    anchor.addnext(el)
                    anchor = el
    # 참고 자료
    if view["sources"]:
        body = d.element.body
        sect = body.find(qn("w:sectPr"))
        h = deepcopy(last_h1) if last_h1 is not None else None
        if h is not None:
            for child in list(h):
                if child.tag != qn("w:pPr"):
                    h.remove(child)
            run = OxmlElement("w:r")
            t = OxmlElement("w:t")
            t.text = "참고 자료"
            run.append(t)
            h.append(run)
        else:
            h = _new_para(None, "참고 자료")
        normal_proto = next((it._p for k, it in items if k == "p" and _level(it) is None and it.text.strip()), None)
        new_elems = [h] + [_new_para(normal_proto, source_line(s)) for s in view["sources"]]
        new_elems.append(_new_para(normal_proto, "본 자료는 업로드한 문서를 근거로 AI 가 작성한 초안이며, 투자 판단의 최종 책임은 이용자에게 있습니다."))
        for el in new_elems:
            if sect is not None:
                sect.addprevious(el)
            else:
                body.append(el)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()
