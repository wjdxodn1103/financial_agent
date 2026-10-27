"""양식 샘플 읽기 — 섹션(제목·안내)과 표·차트·그림 자리를 본문 순서대로.

결과 = {
  sections: [{title, level, guide}],
  assets:   [{kind: table|chart|figure, caption, unit, section(섹션 번호|None), rows?, chart?, page?, bbox?}],
  pages, scanned
}
DOCX: 제목 스타일(Heading·제목·개요 수준) 문단 = 섹션, 그 아래 글 = 안내(600자). 제목 스타일이 하나도 없으면 짧은 굵은 줄을 제목으로 본다.
      표 = 칸 그대로(_docx_rows), 차트 = word/charts/chartN.xml 의 종류·계열·범주·캐시 값. 캡션은 '<표 1> …'·'그림 2.'·'Table 3' 줄.
PDF:  40쪽까지. 글이 거의 없으면 스캔본(scanned). 제목 = 본문보다 큰 글씨 또는 굵은 짧은 줄. 표 = find_tables(_pdf_tables),
      그림 = '그림 n'·'Figure n' 캡션 줄(그 아래·위 그림 영역은 5단계 VL 이 읽는다 — 여기서는 자리만).
"""
from __future__ import annotations

import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.docs.extract import UNIT_RX, _digit_ratio, _docx_rows, _is_heading, _pdf_tables, _strip_unit, unit_of
from app.report.template_docx import _body_items, _level

GUIDE_MAX = 600
MAX_ASSETS = 12
PDF_PAGES = 40
# 조판에서 앞 문단에 붙어 버린 캡션 — 괄호로 싼 꼴('<표 1> …')만(문장 속 '표 1에서 보듯'은 아니다)
CAPTION_TAIL = re.compile(r"\s([<\[〈【]\s*(?:표|그림|차트|도표|그래프|Table|Figure|Chart)\s*\d{1,3}\s*[>\]〉】].{0,90})$", re.I)
CAPTION = re.compile(r"^\s*[<\[〈【(]?\s*(표|그림|차트|도표|그래프|Table|Figure|Fig\.?|Chart|Exhibit)\s*(\d{1,3})\s*[>\]〉】)]?\s*[.:：\-–—)]?\s*(.*)$", re.I)
NS_C = "http://schemas.openxmlformats.org/drawingml/2006/chart"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


class SampleError(ValueError):
    pass


def caption_of(text: str) -> Optional[Tuple[str, str]]:
    """'<표 1> 주요 재무 지표 (단위: 억원)' → ('table', '주요 재무 지표'). 캡션 줄이 아니면 None."""
    m = CAPTION.match(text or "")
    if not m or len(text) > 120:
        return None
    kind = "table" if m.group(1).lower() in ("표", "table") else "chart"
    title = _strip_unit(m.group(3) or "").strip(" .:-") or text.strip()
    return kind, title


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


# ── DOCX ────────────────────────────────────────────────────────────────

def _floats(pts: List[Any]) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for v in pts:
        try:
            out.append(float(v) if v not in (None, "") else None)
        except ValueError:
            out.append(None)
    return out


def _cache(el: Any) -> List[str]:
    """c:strCache / c:numCache → 값 목록(idx 순, 빈 칸은 '')."""
    if el is None:
        return []
    cnt = el.find(f"{{{NS_C}}}ptCount")
    n = int(cnt.get("val")) if cnt is not None else 0
    vals = [""] * n
    for pt in el.findall(f"{{{NS_C}}}pt"):
        i = int(pt.get("idx") or 0)
        v = pt.find(f"{{{NS_C}}}v")
        if i >= len(vals):
            vals += [""] * (i + 1 - len(vals))
        vals[i] = (v.text or "") if v is not None else ""
    return vals


def read_chart(xml: bytes) -> Optional[Dict[str, Any]]:
    """차트 부품 XML → {type bar|line, horizontal, title, categories, series:[{name, values}]}. 막대·꺾은선·영역·원만(원은 막대로)."""
    from lxml import etree

    root = etree.fromstring(xml)
    plot = None
    for tag in ("barChart", "bar3DChart", "lineChart", "line3DChart", "areaChart", "pieChart"):
        plot = root.find(f".//{{{NS_C}}}{tag}")
        if plot is not None:
            break
    if plot is None:
        return None
    tag = etree.QName(plot).localname
    bar_dir = plot.find(f"{{{NS_C}}}barDir")
    series: List[Dict[str, Any]] = []
    categories: List[str] = []
    for ser in plot.findall(f"{{{NS_C}}}ser"):
        tx = ser.find(f"{{{NS_C}}}tx")
        v = tx.find(f".//{{{NS_C}}}v") if tx is not None else None  # 캐시 값(c:f 의 'Sheet1!$B$1' 은 빼고)
        name = (v.text or "").strip() if v is not None else ""
        cat = ser.find(f"{{{NS_C}}}cat")
        if cat is not None and not categories:
            categories = _cache(cat.find(f".//{{{NS_C}}}strCache")) or _cache(cat.find(f".//{{{NS_C}}}numCache"))
        val = ser.find(f"{{{NS_C}}}val")
        values = _floats(_cache(val.find(f".//{{{NS_C}}}numCache")) if val is not None else [])
        series.append({"name": name or f"계열 {len(series) + 1}", "values": values})
    if not series:
        return None
    n = max(len(categories), *(len(s["values"]) for s in series))
    categories = (categories + [f"항목 {i + 1}" for i in range(len(categories), n)])[:n]
    for s in series:
        s["values"] = (s["values"] + [None] * n)[:n]
    title_el = root.find(f".//{{{NS_C}}}title")
    title = _clean("".join(t.text or "" for t in title_el.iter(f"{{{NS_A}}}t"))) if title_el is not None else ""
    return {"type": "line" if tag.startswith("line") else "bar", "horizontal": bar_dir is not None and bar_dir.get("val") == "bar", "title": title, "categories": categories, "series": series}


def _chart_ids(p: Any) -> List[str]:
    return [el.get(f"{{{NS_R}}}id") for el in p._p.iter(f"{{{NS_C}}}chart") if el.get(f"{{{NS_R}}}id")]


def _docx(path: str | Path) -> Dict[str, Any]:
    from docx import Document
    from docx.table import Table

    try:
        d = Document(str(path))
    except Exception as e:  # noqa: BLE001
        raise SampleError("Word 파일을 열지 못했습니다.") from e
    items = _body_items(d)
    styled = any(kind == "p" and (_level(it) or 0) >= 1 for kind, it in items)
    sections: List[Dict[str, Any]] = []
    assets: List[Dict[str, Any]] = []
    title = _clean(d.core_properties.title or "")
    pending: Optional[Tuple[str, str]] = None  # 아직 표·차트를 못 만난 캡션
    unit: Optional[str] = None
    last_text = ""

    def here() -> Optional[int]:
        return len(sections) - 1 if sections else None

    for kind, it in items:
        if kind == "p":
            text = _clean(it.text)
            charts = _chart_ids(it)
            lvl = _level(it) if styled else (1 if text and _is_heading(text, bool(it.runs) and all(r.bold for r in it.runs if r.text.strip())) and not caption_of(text) else None)
            if charts:
                for rid in charts:
                    part = d.part.related_parts.get(rid)
                    ch = read_chart(part.blob) if part is not None else None
                    if ch:
                        cap = pending[1] if pending and pending[0] == "chart" else (caption_of(text)[1] if caption_of(text) else "")
                        assets.append({"kind": "chart", "caption": cap or ch["title"], "unit": unit, "section": here(), "chart": ch})
                pending, unit = None, None
                continue
            if not text:
                continue
            if lvl == 0:  # 문서 제목(Title) — 양식 이름 후보
                title = title or text
                continue
            if lvl is not None and lvl >= 1 and not caption_of(text):
                sections.append({"title": text, "level": lvl, "guide": ""})
                pending, unit = None, None
                continue
            cap = caption_of(text)
            if cap:
                # 차트 캡션이 차트 아래에 오는 양식 — 바로 앞 차트에 캡션이 없으면 그것에 붙인다
                last = assets[-1] if assets else None
                if cap[0] == "chart" and last is not None and last["kind"] == "chart" and not last.get("captioned"):
                    last.update({"caption": cap[1], "captioned": True})
                else:
                    pending = cap
                unit = unit_of(text) or unit
                continue
            if UNIT_RX.fullmatch(text):
                unit = unit_of(text)
                continue
            if sections and len(sections[-1]["guide"]) < GUIDE_MAX:
                sections[-1]["guide"] = (sections[-1]["guide"] + " " + text).strip()[:GUIDE_MAX]
            last_text = text
        else:
            rows = _docx_rows(Table(it, d))
            if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                cap = pending[1] if pending else (last_text if len(last_text) <= 40 else "")
                assets.append({"kind": "table", "caption": cap, "captioned": bool(pending), "unit": unit or next((u for u in (unit_of(c) for c in rows[0]) if u), None), "section": here(), "rows": rows})
            pending, unit = None, None
    return {"title": title, "sections": sections, "assets": assets[:MAX_ASSETS], "pages": None, "scanned": False, "more": max(0, len(assets) - MAX_ASSETS)}


# ── PDF ─────────────────────────────────────────────────────────────────

def _pdf(path: str | Path) -> Dict[str, Any]:
    import fitz  # PyMuPDF

    from app.docs.layout import layout_paragraphs

    try:
        doc = fitz.open(str(path))
    except Exception as e:  # noqa: BLE001
        raise SampleError("PDF 파일을 열지 못했습니다.") from e
    try:
        pages = len(doc)
        if pages > PDF_PAGES:
            doc.select(list(range(PDF_PAGES)))
        chars = sum(len(p.get_text("text").strip()) for p in doc)
        if chars < 80 * max(1, min(pages, PDF_PAGES)) // 4:
            return {"title": "", "sections": [], "assets": [], "pages": pages, "scanned": True, "more": 0}
        tables = _pdf_tables(doc)
        exclude = {pno: [t["bbox"] for t in ts] for pno, ts in tables.items()}
        paras = layout_paragraphs(doc, exclude)
        sizes = [p.get("size") or 0 for p in paras if len(p.get("text") or "") > 40]
        body = statistics.median(sizes) if sizes else 10.0
        # (쪽, y) 순서로 제목·캡션·글을 훑으며 섹션을 만들고, 표는 위치로 섹션에 붙인다
        marks: List[Tuple[int, float, str, Dict[str, Any]]] = []
        for p in paras:
            text = _clean(p.get("text") or "")
            if not text:
                continue
            tail = CAPTION_TAIL.search(text)
            if tail and not p.get("caption"):  # 글 + 캡션이 한 문단으로 붙었다 — 나눈다
                body_text, cap_text = text[: tail.start()].strip(), tail.group(1).strip()
                if body_text:
                    marks.append((p["page"], p.get("y0", 0.0), "text", {"text": body_text}))
                cap = caption_of(cap_text)
                if cap:
                    marks.append((p["page"], p.get("y0", 0.0) + 0.1, "caption", {"kind": cap[0], "title": cap[1], "unit": unit_of(cap_text)}))
                continue
            cap = caption_of(text)
            big = (p.get("size") or 0) >= body + 1.5
            if cap and not p.get("caption"):
                marks.append((p["page"], p.get("y0", 0.0), "caption", {"kind": cap[0], "title": cap[1], "unit": unit_of(text), "y1": p.get("y0", 0.0)}))
            elif not p.get("caption") and len(text) <= 80 and (big or (p.get("bold") and _is_heading(text, True))):
                marks.append((p["page"], p.get("y0", 0.0), "heading", {"title": text, "level": 1, "size": p.get("size") or 0}))
            elif not p.get("caption"):
                marks.append((p["page"], p.get("y0", 0.0), "text", {"text": text}))
        for pno, ts in tables.items():
            for t in ts:
                marks.append((pno, t["bbox"][1], "table", t))
        marks.sort(key=lambda m: (m[0], m[1]))
        # 1쪽 맨 위 제목이 다른 제목들보다 크면 문서 제목(양식 이름)이지 섹션이 아니다
        heads = [m for m in marks if m[2] == "heading"]
        title = ""
        if len(heads) >= 2 and heads[0][0] == 1 and heads[0][3]["size"] > max(h[3]["size"] for h in heads[1:]) + 0.5:
            title = heads[0][3]["title"]
            marks.remove(heads[0])
        sections: List[Dict[str, Any]] = []
        assets: List[Dict[str, Any]] = []
        for pno, y, kind, m in marks:
            here = len(sections) - 1 if sections else None
            if kind == "heading":
                sections.append({"title": m["title"], "level": 1, "guide": ""})
            elif kind == "text":
                if _digit_ratio(m["text"]) > 0.3:
                    continue  # 차트 눈금·표 조각 숫자 줄은 안내가 아니다
                if sections and len(sections[-1]["guide"]) < GUIDE_MAX:
                    sections[-1]["guide"] = (sections[-1]["guide"] + " " + m["text"]).strip()[:GUIDE_MAX]
            elif kind == "table":
                cap = caption_of(m.get("caption") or "")
                assets.append({"kind": "table", "caption": cap[1] if cap else (m.get("caption") or ""), "unit": m.get("unit"), "section": here, "rows": m["rows"], "page": pno, "bbox": list(m["bbox"])})
            elif kind == "caption" and m["kind"] == "chart":
                # 그림 자리 — 캡션 아래(없으면 위) 그림 영역은 VL 이 읽는다
                assets.append({"kind": "figure", "caption": m["title"], "unit": m.get("unit"), "section": here, "page": pno, "y": y})
        title = title or _clean((doc.metadata or {}).get("title") or "")
        return {"title": title, "sections": sections, "assets": assets[:MAX_ASSETS], "pages": pages, "scanned": False, "more": max(0, len(assets) - MAX_ASSETS)}
    finally:
        doc.close()


def extract_sample(path: str | Path, file_name: str) -> Dict[str, Any]:
    ext = Path(file_name).suffix.lower()
    if ext == ".docx":
        return _docx(path)
    if ext == ".pdf":
        return _pdf(path)
    raise SampleError("Word(.docx)나 PDF 만 읽습니다.")


__all__ = ["CAPTION", "MAX_ASSETS", "SampleError", "caption_of", "extract_sample", "read_chart"]
