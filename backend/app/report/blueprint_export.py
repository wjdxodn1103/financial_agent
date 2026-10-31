"""양식 2.0 틀 문서 내보내기 — 원본 샘플의 쪽 모양을 Word 로(report/view 의 블록을 틀의 테마·쪽 짜임대로 놓는다).

쪽 짜임(원본 KIRS 실측 기준 — 크기·색은 doc["layout"]["theme"] 에서):
  머리글·바닥글   layout.page — {subject}·{date}·{page} 자리
  표지           대상 · 제목 · 작성일 · 체크포인트(요약 주장)
  요약 쪽         2칸 표(본문 | 옅은 색 사이드바) — 주장(강조색 굵게)+본문, 본문 칸 표, 사이드바 표
  장             새 쪽 · 띠(채운 칸에 흰 글자) · 번호 소제목(번호 칸 + 강조색 굵게)
  소주제 본문      '핵심 | 본문' 2칸(핵심 문장은 왼쪽 칸, 본문은 오른쪽 본문 칸), 핵심 없는 문단은 본문 칸 들여쓰기
  표             제목(굵게) · 표 양식(머리 굵게·위 선 색·가로줄·행 들여쓰기·굵은 행·열 색) · 자료 줄. 원본에서 넓던 표는 쪽 너비
  부록           새 쪽 · 표 2×2(원본 재무표 쪽처럼)
그림 자리는 우리 자료로 그릴 수 있으면 원본 모양 차트(research/form_charts), 아니면 제목 + 빈 칸. 글꼴은 맑은 고딕(원본 글꼴 대체), 크기·색은 원본대로.
"""
from __future__ import annotations

import io
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Pt, RGBColor

from app.agent.session import Doc
from app.formats.blocks import doc_subject
from app.report.format_export import FONT, _hex, _safe, _shade, _style_font
from app.report.view import build_report_view, source_line

PAGE_W, PAGE_H = 595.3, 841.9  # A4 pt
MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 57.0, 42.0, 56.0, 42.0
BODY_X = 185.0  # 본문 칸 시작(원본 실측) — 왼쪽 칸(57~170)은 핵심 문장
SIDE_W = 187.0  # 요약 쪽 사이드바 너비(원본 374~561)
WIDE_X = 100.0  # 원본에서 이보다 왼쪽에서 시작한 표는 쪽 너비 표
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R
TWIP = 20


def _rgb(v: Any, default: str) -> RGBColor:
    return RGBColor.from_string(_hex(v, default))


class _Theme:
    def __init__(self, lay: Dict[str, Any]):
        th = lay.get("theme") or {}
        self.accent = _hex(th.get("accent"), "C00000")
        self.band = _hex(th.get("bandFill") or th.get("accent"), self.accent)
        self.band_text = _hex(th.get("bandText"), "FFFFFF")
        self.side = _hex(th.get("sidebarFill"), "F2F2F2")
        self.caption = _hex(th.get("captionColor"), "595959")
        self.body = float(th.get("bodySize") or 9)
        self.headline = float(th.get("headlineSize") or 10.5)
        self.band_size = float(th.get("bandSize") or 14)
        self.caption_size = float(th.get("captionSize") or 8.5)
        self.source_size = float(th.get("sourceSize") or 6.5)
        self.table_size = float(th.get("tableSize") or 7)


def _run(p, text: str, size: float, *, bold: bool = False, color: Optional[str] = None):
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.bold = bold
    r.font.name = FONT
    r._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)
    if color:
        r.font.color.rgb = RGBColor.from_string(color)
    return r


def _para(container, *, indent: float = 0.0, before: float = 0.0, after: float = 3.0, align=None, keep: bool = False):
    p = container.add_paragraph()
    f = p.paragraph_format
    f.left_indent = Pt(indent)
    f.space_before = Pt(before)
    f.space_after = Pt(after)
    f.line_spacing = 1.3
    if keep:
        f.keep_with_next = True
    if align is not None:
        p.alignment = align
    return p


def _page_break(d: Document) -> None:
    d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)


def _no_borders(table) -> None:
    table._tbl.tblPr.append(parse_xml(f'<w:tblBorders {nsdecls("w")}><w:top w:val="nil"/><w:left w:val="nil"/><w:bottom w:val="nil"/><w:right w:val="nil"/>'
                                      '<w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>'))


def _fixed(table, widths: List[float], indent: float = 0.0) -> None:
    """표 너비·열 너비 고정(pt) + 왼쪽 들여쓰기."""
    pr = table._tbl.tblPr
    pr.append(parse_xml(f'<w:tblW {nsdecls("w")} w:w="{int(sum(widths) * TWIP)}" w:type="dxa"/>'))
    pr.append(parse_xml(f'<w:tblLayout {nsdecls("w")} w:type="fixed"/>'))
    if indent:
        pr.append(parse_xml(f'<w:tblInd {nsdecls("w")} w:w="{int(indent * TWIP)}" w:type="dxa"/>'))
    pr.append(parse_xml(f'<w:tblCellMar {nsdecls("w")}><w:left w:w="40" w:type="dxa"/><w:right w:w="40" w:type="dxa"/></w:tblCellMar>'))
    grid = table._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(int(w * TWIP)))
    for row in table.rows:
        for c, w in zip(row.cells, widths):
            c.width = Pt(w)


def _cell_border(cell, **sides: str) -> None:
    """칸 선 — sides: top/bottom = 'sz:색'(sz = 1/8pt 단위)."""
    xml = "".join(f'<w:{k} w:val="single" w:sz="{v.split(":")[0]}" w:color="{v.split(":")[1]}"/>' for k, v in sides.items())
    cell._tc.get_or_add_tcPr().append(parse_xml(f'<w:tcBorders {nsdecls("w")}>{xml}</w:tcBorders>'))


def _clear(cell):
    """새 칸의 빈 첫 문단을 지우고 칸을 돌려준다(add_paragraph 가 첫 줄부터 쓰게)."""
    p = cell.paragraphs[0]._p
    p.getparent().remove(p)
    return cell


def _end_cell(cell) -> None:
    """칸 안 마지막 요소가 표면 Word 가 칸을 못 연다 — 빈 문단으로 닫는다."""
    if not cell._tc.findall(qn("w:p")) or cell._tc[-1].tag == qn("w:tbl"):
        p = cell.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 0.5


# ── 표 ────────────────────────────────────────────────────────────────

def _table(container, b: Dict[str, Any], th: _Theme, width: float, indent: float = 0.0) -> None:
    """틀의 표 블록(research/form_rows.fill_form) → Word 표. 제목·표·자료 줄."""
    look = b.get("look") or {}
    size = float(look.get("fontSize") or th.table_size)
    cap = _para(container, indent=indent, before=8, after=2, keep=True)
    cs = (b.get("look") or {})
    _run(cap, b.get("title") or b.get("caption") or "", float(cs.get("captionSize") or th.caption_size), bold=cs.get("captionBold", True) is not False,
         color=_hex(cs.get("captionColor"), "000000"))
    if b.get("unitNote"):  # 원본처럼 제목 줄 오른쪽 끝 '(단위: …)'
        cap.paragraph_format.tab_stops.add_tab_stop(Pt(indent + width), WD_TAB_ALIGNMENT.RIGHT)
        _run(cap, f"\t(단위: {b['unitNote']})", th.source_size + 0.5, color="595959")
    header, rows = b.get("header") or [], b.get("rows") or []
    ncol = max([len(header)] + [len(r) for r in rows]) if rows or header else 1
    first = min(width * 0.36, 110.0) if ncol > 2 else width * 0.55
    widths = [first] + [(width - first) / max(1, ncol - 1)] * (ncol - 1)
    groups = b.get("headGroups") or []  # 묶음 머리 줄(동종 업종 밸류에이션의 '매출액 · PSR · PBR') — 첫 열 뒤 [{label, span, group?}]
    off = 1 if groups else 0
    t = container.add_table(rows=1 + off + len(rows), cols=ncol)
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    _no_borders(t)
    _fixed(t, widths, indent)
    top = _hex(look.get("topRule") or look.get("rule"), "7F7F7F")
    top_sz = max(4, int(round(float(look.get("topRuleWidth") or 0.75) * 8)))
    rule = _hex(look.get("rule"), "BFBFBF")
    fill = _hex(look.get("headerFill"), "FFFFFF")
    head_color = _hex(look.get("headerText"), "000000")
    colors = look.get("columnColors") or []
    stripes = set(look.get("stripeColumns") or [])
    stripe = _hex(look.get("stripeColor"), "F2F2F2")
    col_fills = look.get("columnFills") or []

    def col_fill(j: int) -> Optional[str]:
        """값 열 j 의 바탕 — 열마다 색(columnFills), 없으면 줄무늬 열 색."""
        if j < len(col_fills) and col_fills[j]:
            return _hex(col_fills[j], "F2F2F2")
        return stripe if j in stripes else None

    head_rule = _hex(look.get("headRule") or look.get("rule"), "BFBFBF")
    head_sz = max(2, int(round(float(look.get("headRuleWidth") or 0.5) * 8)))
    bottom_rule = _hex(look.get("bottomRule") or look.get("rule"), "BFBFBF")
    row_rules = set(look.get("rowRules") or [])
    def put_head(cell, text: str, c: int, top_b: Optional[str], bottom_b: Optional[str]) -> None:
        cf = col_fill(c - 1) if c > 0 else None
        if cf or fill != "FFFFFF":
            _shade(cell, cf or fill)  # 원본처럼 머리 칸도 그 열 바탕
        _cell_border(cell, **({"top": top_b} if top_b else {}), **({"bottom": bottom_b} if bottom_b else {}))
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = Pt(size + 3)  # 고정 줄 높이 — 문단 표시(본문 크기)가 줄을 키우지 않게
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT if c == 0 else WD_ALIGN_PARAGRAPH.CENTER
        _run(p, text, size, bold=look.get("headerBold", True) is not False, color=head_color)

    top_b, head_b = f"{top_sz}:{top}", f"{head_sz}:{head_rule}"
    if groups:
        # 두 줄 머리 — 첫 열·묶음 없는 열은 두 줄을 합치고, 묶음은 위 줄을 그 아래 열만큼 가로로 합친다(묶음 아래 가는 선)
        put_head(t.cell(0, 0).merge(t.cell(1, 0)), header[0] if header else "", 0, top_b, head_b)
        c = 1
        for g in groups:
            span = max(1, int(g.get("span") or 1))
            if c + span - 1 >= ncol:
                break
            if g.get("group"):
                put_head(t.cell(0, c).merge(t.cell(0, c + span - 1)) if span > 1 else t.cell(0, c), g.get("label") or "", c, top_b, f"2:{rule}")
                for j in range(span):
                    put_head(t.cell(1, c + j), header[c + j] if c + j < len(header) else "", c + j, None, head_b)
            else:
                put_head(t.cell(0, c).merge(t.cell(1, c)), header[c] if c < len(header) else "", c, top_b, head_b)
            c += span
    else:
        for c in range(ncol):
            put_head(t.cell(0, c), header[c] if c < len(header) else "", c, top_b, head_b)
    lines = look.get("lines") or "horizontal"
    for r, row in enumerate(rows, start=1):
        head = row[0] if row else {}
        bold = bool(head.get("bold") or head.get("group"))
        row_color = _hex(head["color"], "000000") if head.get("color") else None  # 강조 행 — 행 전체 글자색
        for c in range(ncol):
            cell = t.cell(r + off, c)
            data = row[c] if c < len(row) else {"text": ""}
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.line_spacing = Pt(size + 3)
            if c == 0:
                p.paragraph_format.left_indent = Pt(6 * int(head.get("indent") or 0))
            else:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                cf = col_fill(c - 1)
                if cf:
                    _shade(cell, cf)
            color = row_color or (_hex(colors[c - 1], "000000") if c > 0 and c - 1 < len(colors) and colors[c - 1] else None)
            _run(p, str(data.get("text") or ""), size, bold=bold, color=color)
            # 가로줄 — 원본 자리만: 묶음 사이(rowRules, 몸통 행 번호 r-1)·표 아래. 옛 양식(행마다)은 horizontal
            if r == len(rows):
                _cell_border(cell, bottom=f"4:{bottom_rule}")
            elif lines in ("horizontal", "grid"):
                _cell_border(cell, bottom="2:D9D9D9")
            elif r - 1 in row_rules:
                _cell_border(cell, bottom=f"4:{rule}")
    for note in b.get("noteLines") or []:  # 표 아래 '주:' 줄(자료 줄 위)
        np_ = _para(container, indent=indent, before=2, after=0)
        _run(np_, note, th.source_size, color=th.caption)
    if b.get("sourceLine"):
        sp = _para(container, indent=indent, before=2, after=6)
        _run(sp, b["sourceLine"], th.source_size, color=th.caption)


# ── 차트·그림 자리 ──────────────────────────────────────────────────────

def _caption_line(container, b: Dict[str, Any], th: _Theme, width: float, indent: float) -> None:
    cap = _para(container, indent=indent, before=8, after=2, keep=True)
    _run(cap, b.get("title") or b.get("caption") or "", th.caption_size, bold=True, color=_hex((b.get("look") or {}).get("captionColor"), "000000"))
    if b.get("unit"):
        cap.paragraph_format.tab_stops.add_tab_stop(Pt(indent + width), WD_TAB_ALIGNMENT.RIGHT)
        _run(cap, f"\t({b['unit']}{', 오른쪽 ' + b['unit2'] if b.get('unit2') else ''})", th.source_size + 0.5, color="595959")


def _chart(container, b: Dict[str, Any], th: _Theme, width: float, indent: float = 0.0, height: float = 150.0) -> None:
    """차트 블록(research/form_charts) → 제목 · Word 네이티브 차트(원본 계열 색·값 표시·눈금선 없음, 원본 영역 크기) · 자료 줄."""
    from app.report.docx_chart import add_chart

    _caption_line(container, b, th, width, indent)
    look = b.get("look") or {}
    form = {"meta": [{k: s.get(k) for k in ("type", "axis", "computed") if s.get(k)} for s in b["series"]], "colors": look.get("colors") or [],
            "labels": look.get("labels"), "legend": b.get("legend") or "", "grid": look.get("grid", True)}
    p = _para(container, indent=indent, after=0)
    add_chart(p, categories=b["categories"], series=[(s["name"], s["values"]) for s in b["series"]], kind=b.get("chartType") or "bar",
              horizontal=bool(b.get("horizontal")), number_format=b.get("number") or "0.0", width=Pt(width), height=Pt(height), form=form)
    if b.get("sourceLine"):
        sp = _para(container, indent=indent, before=2, after=6)
        _run(sp, b["sourceLine"], th.source_size, color=th.caption)


def _figure_slot(container, b: Dict[str, Any], th: _Theme, width: float, indent: float = 0.0) -> None:
    """그릴 자료가 없는 그림 자리(사진·연혁 그림·산업 차트) — 원본 제목 + 옅은 빈 칸. 사람이 그림을 넣을 자리가 보이게."""
    _caption_line(container, b, th, width, indent)
    t = container.add_table(rows=1, cols=1)
    _no_borders(t)
    _fixed(t, [width], indent)
    cell = t.cell(0, 0)
    _cell_border(cell, top="4:D9D9D9", bottom="4:D9D9D9", left="4:D9D9D9", right="4:D9D9D9")
    t.rows[0]._tr.get_or_add_trPr().append(parse_xml(f'<w:trHeight {nsdecls("w")} w:val="{int(54 * TWIP)}" w:hRule="exact"/>'))
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _run(p, "그림 자리 — 자료를 넣으면 채웁니다", th.source_size + 0.5, color="A6A6A6")
    _para(container, after=4)


def _box_of(forms: Dict[str, Any], b: Dict[str, Any]) -> Optional[List[float]]:
    return (forms.get(b.get("formId") or "") or {}).get("bbox")


def _twins(forms: Dict[str, Any], a: Dict[str, Any], c: Optional[Dict[str, Any]]) -> bool:
    """원본에서 나란히 놓인 두 그림(같은 쪽·같은 높이, 둘 다 쪽 폭 절반쯤) — Word 에서도 한 줄에 둘."""
    if c is None or c.get("kind") not in ("chart", "figure"):
        return False
    fa, fc = forms.get(a.get("formId") or "") or {}, forms.get(c.get("formId") or "") or {}
    ba, bc = fa.get("bbox"), fc.get("bbox")
    return bool(ba and bc and fa.get("page") == fc.get("page") and abs(ba[1] - bc[1]) <= 12 and ba[2] - ba[0] < CONTENT_W * 0.6 and bc[2] - bc[0] < CONTENT_W * 0.6)


def _visual(container, b: Dict[str, Any], th: _Theme, forms: Dict[str, Any], width: Optional[float] = None, indent: Optional[float] = None) -> None:
    """차트면 원본 크기로 그리고, 그림 자리면 자리 칸. 폭·들여쓰기는 원본 영역(본문 칸 안 / 쪽 너비)."""
    box = _box_of(forms, b)
    if width is None:
        wide = bool(box and box[0] < WIDE_X)
        width = min(box[2] - box[0], CONTENT_W) if box and wide else CONTENT_W - (BODY_X - MARGIN_L)
        indent = 0.0 if wide else BODY_X - MARGIN_L
    height = max(90.0, min(220.0, (box[3] - box[1] - 16) if box else 150.0))
    if b.get("kind") == "chart":
        _chart(container, b, th, width, indent or 0.0, height)
    elif not b.get("note"):
        _figure_slot(container, b, th, width, indent or 0.0)


# ── 쪽 부품 ────────────────────────────────────────────────────────────

def _header_footer(d: Document, lay: Dict[str, Any], subject: str, day: str) -> None:
    sec = d.sections[0]
    page = lay.get("page") or {}

    def fill(par, items: List[Dict[str, Any]]) -> None:
        par.paragraph_format.tab_stops.add_tab_stop(Pt(CONTENT_W), WD_TAB_ALIGNMENT.RIGHT)
        left = [i for i in items if i.get("align") != "right"]
        right = [i for i in items if i.get("align") == "right"]
        for k, group in enumerate((left, right)):
            if k:
                par.add_run("\t")
            for i in group:
                text = str(i.get("text") or "")
                if text == "{page}":
                    par._p.append(parse_xml(f'<w:fldSimple {nsdecls("w")} w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>'))
                else:
                    _run(par, text.replace("{subject}", subject).replace("{date}", day), 7.5, color="595959")

    fill(sec.header.paragraphs[0], page.get("header") or [])
    fill(sec.footer.paragraphs[0], page.get("footer") or [])


def _cover(d: Document, view: Dict[str, Any], th: _Theme, subject: str, day: str, claims: List[str]) -> None:
    p = _para(d, before=40, after=4)
    _run(p, subject or "", 11, bold=True, color=th.accent)
    p = _para(d, after=6)
    _run(p, view["title"], 20, bold=True)
    p = _para(d, after=24)
    _run(p, day, 9, color="595959")
    if claims:
        p = _para(d, after=4)
        _run(p, "Check Point", 11, bold=True, color=th.accent)
        for c in claims:
            p = _para(d, indent=10, after=4)
            _run(p, "■ ", 8, color=th.accent)
            _run(p, c, 10)
    _page_break(d)


def _band(d: Document, text: str, th: _Theme) -> None:
    t = d.add_table(rows=1, cols=1)
    _no_borders(t)
    _fixed(t, [168.0], BODY_X - MARGIN_L)
    cell = t.cell(0, 0)
    _shade(cell, th.band)
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    _run(p, text, th.band_size, bold=True, color=th.band_text)
    _para(d, after=4)


def _headline(container, no: Optional[int], text: str, th: _Theme, indent: float) -> None:
    p = _para(container, indent=indent, before=14, after=6, keep=True)
    if no is not None:
        r = _run(p, f" {no} ", th.headline - 1.5, bold=True, color="FFFFFF")
        r._element.get_or_add_rPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="{th.accent}"/>'))
        _run(p, "  ", th.headline)
    _run(p, text, th.headline, bold=True, color=th.accent)


def _body_para(container, text: str, th: _Theme, indent: float) -> None:
    p = _para(container, indent=indent, after=4, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
    _run(p, text, th.body)


def _keyline_group(d: Document, key: str, paras: List[str], th: _Theme) -> None:
    """'핵심 | 본문' 2칸 — 원본의 왼쪽 굵은 요지 칸(57~170)과 본문 칸(185~)."""
    t = d.add_table(rows=1, cols=2)
    _no_borders(t)
    _fixed(t, [BODY_X - MARGIN_L, CONTENT_W - (BODY_X - MARGIN_L)])
    left, right = _clear(t.cell(0, 0)), _clear(t.cell(0, 1))
    for line in key.split("\n"):
        p = _para(left, after=0)
        _run(p, line, th.body, bold=True)
    for text in paras or [""]:
        _body_para(right, text, th, 0)


def _summary(d: Document, blocks: List[Dict[str, Any]], th: _Theme) -> None:
    """요약 쪽 — 본문 칸(주장·본문·본문 칸 표) | 사이드바(옅은 색 바탕, 사이드바 표)."""
    main_w = CONTENT_W - SIDE_W - 8
    t = d.add_table(rows=1, cols=2)
    _no_borders(t)
    _fixed(t, [main_w, SIDE_W])
    main, side = _clear(t.cell(0, 0)), _clear(t.cell(0, 1))
    _shade(side, th.side)
    # 사이드바 바탕은 원본처럼 쪽 끝까지 — 행 높이를 본문 높이로(내용이 길면 늘어난다)
    t.rows[0]._tr.get_or_add_trPr().append(parse_xml(f'<w:trHeight {nsdecls("w")} w:val="{int((PAGE_H - MARGIN_T - MARGIN_B - 40) * TWIP)}" w:hRule="atLeast"/>'))
    for b in blocks:
        k = b.get("kind")
        if k == "para" and b.get("role") == "claim":
            p = _para(main, before=8, after=3, keep=True)
            _run(p, b["text"], th.headline, bold=True, color=th.accent)
        elif k == "para":
            _body_para(main, b["text"], th, 0)
        elif k == "table" and b.get("position") == "sidebar":
            _table(side, b, th, SIDE_W - 12)
        elif k == "table":
            _table(main, b, th, main_w - 6)
        elif k == "chart" and b.get("position") == "sidebar":  # 원본 사이드바 'Price & Relative Performance'
            _chart(side, b, th, SIDE_W - 12, 0.0, 110.0)
        elif k == "chart":
            _chart(main, b, th, main_w - 6, 0.0, 140.0)
    _end_cell(main)
    _end_cell(side)
    _page_break(d)


def _appendix(d: Document, title: str, tables: List[Dict[str, Any]], th: _Theme) -> None:
    """부록 — 새 쪽, 제목, 표 2×2(원본 재무표 쪽: 왼쪽 손익·현금흐름, 오른쪽 재무상태·투자지표 — view 순서가 행 우선이라 그대로 채운다)."""
    _page_break(d)  # 원본 재무표 쪽은 제목 없이 표만(title 은 화면의 부록 띠에만)
    half = (CONTENT_W - 10) / 2
    n_rows = (len(tables) + 1) // 2
    t = d.add_table(rows=n_rows, cols=2)
    _no_borders(t)
    _fixed(t, [half + 5, half + 5])
    for i, b in enumerate(tables):
        cell = _clear(t.cell(i // 2, i % 2))
        _table(cell, b, th, half - 4)
        _end_cell(cell)
    for r in range(n_rows):
        for c in range(2):
            _end_cell(t.cell(r, c))


# ── 조립 ─────────────────────────────────────────────────────────────

def _setup(d: Document, th: _Theme) -> None:
    _style_font(d.styles["Normal"], th.body)
    d.styles["Normal"].paragraph_format.space_after = Pt(3)
    s = d.sections[0]
    s.page_width, s.page_height = Pt(PAGE_W), Pt(PAGE_H)
    s.left_margin, s.right_margin, s.top_margin, s.bottom_margin = Pt(MARGIN_L), Pt(MARGIN_R), Pt(MARGIN_T), Pt(MARGIN_B)
    s.header_distance = s.footer_distance = Pt(24)


def build_blueprint_docx(doc: Doc) -> Tuple[bytes, str]:
    lay = doc.get("layout") or {}
    th = _Theme(lay)
    view = build_report_view(doc)
    subject = doc_subject(doc)
    day = str((doc.get("setup") or {}).get("asOf") or date.today().isoformat())
    d = Document()
    _setup(d, th)
    _header_footer(d, lay, subject, day)
    blocks = view["blocks"]
    claims = [b["text"] for b in blocks if b.get("kind") == "para" and b.get("role") == "claim"]
    if any(p.get("role") == "cover" for p in lay.get("parts") or []):
        _cover(d, view, th, subject, day, claims)
    forms = lay.get("forms") or {}
    i = 0
    mode = ""  # summary | chapter | appendix
    while i < len(blocks):
        b = blocks[i]
        k = b.get("kind")
        if k == "heading" and b.get("role") == "summary":
            j = i + 1
            while j < len(blocks) and blocks[j].get("kind") not in ("band", "heading"):
                j += 1
            if b.get("status") == "written" or any(x.get("kind") == "table" for x in blocks[i + 1:j]):
                _summary(d, blocks[i + 1:j], th)
            i = j
            continue
        if k == "band" and b.get("role") == "appendix":
            j = i + 1
            while j < len(blocks) and blocks[j].get("kind") == "table":
                j += 1
            _appendix(d, b.get("text") or "부록", blocks[i + 1:j], th)
            mode = "appendix"
            i = j
            continue
        if k == "band":
            if mode == "chapter":
                _page_break(d)
            mode = "chapter"
            _band(d, b.get("text") or "", th)
        elif k == "heading":
            # 안 쓴 소주제는 제목도 넣지 않는다(묶인 표는 아래에서 그대로)
            if b.get("status") == "written":
                _headline(d, b.get("no"), b.get("text") or "", th, BODY_X - MARGIN_L)
        elif k == "para" and b.get("role") == "keyline":
            j = i + 1
            paras: List[str] = []
            while j < len(blocks) and blocks[j].get("kind") == "para" and not blocks[j].get("role"):
                paras.append(blocks[j]["text"])
                j += 1
            _keyline_group(d, b["text"], paras, th)
            i = j
            continue
        elif k == "para":
            _body_para(d, b["text"], th, BODY_X - MARGIN_L)
        elif k == "subhead":
            p = _para(d, indent=BODY_X - MARGIN_L, before=6, after=3, keep=True)
            _run(p, b["text"], th.body + 0.5, bold=True)
        elif k == "list":
            for it in b["items"]:
                p = _para(d, indent=BODY_X - MARGIN_L + 10, after=2)
                _run(p, "· " + it["text"], th.body)
        elif k == "table":
            box = (forms.get(b.get("formId") or "") or {}).get("bbox")
            wide = bool(box and box[0] < WIDE_X)
            _table(d, b, th, CONTENT_W if wide else CONTENT_W - (BODY_X - MARGIN_L), 0 if wide else BODY_X - MARGIN_L)
        elif k in ("chart", "figure"):
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            if _twins(forms, b, nxt):  # 원본처럼 두 그림을 한 줄에
                t = d.add_table(rows=1, cols=2)
                _no_borders(t)
                _fixed(t, [CONTENT_W / 2, CONTENT_W / 2])
                for col, blk in ((0, b), (1, nxt)):
                    cell = _clear(t.cell(0, col))
                    _visual(cell, blk, th, forms, CONTENT_W / 2 - 8, 0.0)
                    _end_cell(cell)
                i += 2
                continue
            _visual(d, b, th, forms)
        i += 1
    if view["sources"]:
        p = _para(d, before=16, after=3)
        _run(p, "참고 자료", th.body + 1, bold=True)
        for src in view["sources"]:
            p = _para(d, after=1)
            _run(p, source_line(src), th.source_size + 0.5, color=th.caption)
    p = _para(d, before=10)
    _run(p, "본 자료는 업로드한 자료를 근거로 AI 가 작성한 초안이며, 표의 숫자는 자료에서 코드가 옮겼습니다. 최종 판단의 책임은 이용자에게 있습니다.", th.source_size + 0.5, color=th.caption)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue(), f"{_safe(view['title'])}_{time.strftime('%Y%m%d')}.docx"


__all__ = ["build_blueprint_docx"]
