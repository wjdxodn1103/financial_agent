"""고정 양식 리포트 내보내기 — 워드에서 조금만 다듬으면 제출할 수 있는 DOCX + 표·그림 데이터 XLSX.

DOCX: 양식 스타일(남색 제목·표 머리 남색 바탕·숫자 오른쪽 정렬·세로줄 없는 표), 캡션 `<표 n> 제목 (단위: …)`,
      **네이티브 워드 표**(셀 수정)와 **네이티브 워드 차트**(데이터 편집 — report/docx_chart.py), 표·그림 아래 출처 줄.
      글이 아직 없는 섹션도 제목과 표·그림은 넣는다(표는 데이터에서 바로 나온다).
      워드 기본 스타일 이름(Title·Heading 1·Caption)을 써서 디자이너가 InDesign 으로 가져갈 때 스타일이 그대로 연결된다.
XLSX: 블록마다 시트 하나(캡션·단위·머리·값 + 출처), 그림 블록은 엑셀 막대 그래프.
"""
from __future__ import annotations

import io
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill

from app.agent.session import Doc
from app.report.docx_chart import add_chart
from app.report.view import build_report_view, source_line

FONT = "맑은 고딕"
NAVY = RGBColor(0x1F, 0x3A, 0x5F)
GREY = RGBColor(0x6B, 0x6B, 0x6B)
NAVY_HEX = "1F3A5F"
_TOTAL = re.compile(r"합계|총변동|^기금 가치$|투자 포트폴리오 시장가치")


def _style_font(style, size: float, bold: bool = False, color: Optional[RGBColor] = None, italic: bool = False) -> None:
    style.font.name = FONT
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = parse_xml(f"<w:rFonts {nsdecls('w')}/>")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia"):
        rfonts.set(qn(attr), FONT)
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.italic = italic
    if color is not None:
        style.font.color.rgb = color


def _setup_styles(d: Document) -> None:
    _style_font(d.styles["Normal"], 10.5)
    d.styles["Normal"].paragraph_format.space_after = Pt(6)
    d.styles["Normal"].paragraph_format.line_spacing = 1.35
    _style_font(d.styles["Title"], 20, bold=True, color=NAVY)
    _style_font(d.styles["Subtitle"], 10, color=GREY)
    _style_font(d.styles["Heading 1"], 15, bold=True, color=NAVY)
    d.styles["Heading 1"].paragraph_format.space_before = Pt(18)
    d.styles["Heading 1"].paragraph_format.space_after = Pt(8)
    _style_font(d.styles["Caption"], 9.5, bold=True, color=NAVY)
    d.styles["Caption"].paragraph_format.space_before = Pt(10)
    d.styles["Caption"].paragraph_format.space_after = Pt(4)
    d.styles["Caption"].paragraph_format.keep_with_next = True
    if "Source Note" not in [s.name for s in d.styles]:
        from docx.enum.style import WD_STYLE_TYPE

        st = d.styles.add_style("Source Note", WD_STYLE_TYPE.PARAGRAPH)
        st.base_style = d.styles["Normal"]
    _style_font(d.styles["Source Note"], 8, color=GREY)
    d.styles["Source Note"].paragraph_format.space_after = Pt(10)
    for s in d.sections:
        s.left_margin = s.right_margin = Cm(2.2)
        s.top_margin = s.bottom_margin = Cm(2.0)


def _caption(d: Document, b: Dict[str, Any]) -> None:
    unit = f" (단위: {b['unit']}" + (f", 오른쪽 축 {b['unit2']}" if b.get("unit2") else "") + ")" if b.get("unit") else ""
    d.add_paragraph(f"{b['label']}{unit}", style="Caption")


def _source(d: Document, b: Dict[str, Any], view: Dict[str, Any]) -> None:
    if b.get("sourceLine"):  # AI 채팅 표 — 여러 자료
        d.add_paragraph(b["sourceLine"], style="Source Note")
        return
    src = next((s for s in view["sources"] if s["docId"] == b.get("docId")), None)
    name = src["label"] if src else (b.get("docLabel") or "")
    no = f" [{src['n']}]" if src else ""
    d.add_paragraph(f"자료: {name}{no} · 시트 {b.get('sheet')}", style="Source Note")


def _shade(cell, hex_color: str) -> None:
    cell._tc.get_or_add_tcPr().append(parse_xml(f'<w:shd {nsdecls("w")} w:val="clear" w:color="auto" w:fill="{hex_color}"/>'))


def _borders(table, rule: str = NAVY_HEX, grid: bool = False) -> None:
    """NBIM 풍 — 세로줄 없이 가로줄만(머리 아래·행 사이 연한 선, 표 아래 남색 선). 문서 양식의 표 양식이면 위아래 선 색(rule)·세로줄(grid)을 양식대로."""
    tbl_pr = table._tbl.tblPr
    inside_v = '<w:insideV w:val="single" w:sz="4" w:color="D9D9D9"/>' if grid else '<w:insideV w:val="nil"/>'
    tbl_pr.append(
        parse_xml(
            f'<w:tblBorders {nsdecls("w")}>'
            f'<w:top w:val="single" w:sz="8" w:color="{rule}"/><w:left w:val="nil"/><w:right w:val="nil"/>'
            f'<w:bottom w:val="single" w:sz="8" w:color="{rule}"/><w:insideH w:val="single" w:sz="4" w:color="D9D9D9"/>{inside_v}'
            "</w:tblBorders>"
        )
    )


def _hex(v: Any, default: str) -> str:
    t = str(v or "").lstrip("#").upper()
    return t if len(t) == 6 else default


def _cell_text(cell, text: str, *, bold: bool = False, color: Optional[RGBColor] = None, right: bool = False, size: float = 9) -> None:
    p = cell.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.line_spacing = 1.0
    if right:
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p.add_run(text)
    run.font.size = Pt(size)
    run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def _table(d: Document, b: Dict[str, Any]) -> None:
    """표 블록 → Word 표. 문서 양식의 표 양식으로 만든 표(look·headGroups — research/block.py)는 머리 색·글자색·선과 묶음 머리 줄(칸 합치기)을 양식대로."""
    header, rows = b["header"], b["rows"]
    ncol = max(len(header), *(len(r) for r in rows)) if rows else len(header)
    look = b.get("look") or {}
    groups = b.get("headGroups") or []
    head_fill = _hex(look.get("headerFill"), NAVY_HEX)
    head_color = RGBColor.from_string(_hex(look.get("headerText"), "FFFFFF" if head_fill == NAVY_HEX else "000000"))
    top = 1 if groups else 0
    t = d.add_table(rows=1 + top + len(rows), cols=ncol)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _borders(t, _hex(look.get("rule"), NAVY_HEX), look.get("lines") == "grid")

    def head(cell, text: str, right: bool, center: bool = False) -> None:
        _shade(cell, head_fill)
        _cell_text(cell, text, bold=True, color=head_color, right=right)
        if center:
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    if groups:
        # 묶음 머리 줄 — 첫 열·묶음 없는 열은 두 줄을 합치고, 묶음은 그 아래 열만큼 가로로 합친다
        head(t.cell(0, 0).merge(t.cell(1, 0)), header[0] if header else "", False)
        c = 1
        for g in groups:
            span = max(1, int(g.get("span") or 1))
            if c + span - 1 >= ncol:
                break
            if g.get("group"):
                top_cell = t.cell(0, c).merge(t.cell(0, c + span - 1)) if span > 1 else t.cell(0, c)
                head(top_cell, g.get("label") or "", False, center=True)
                for j in range(span):
                    head(t.cell(1, c + j), header[c + j] if c + j < len(header) else "", False, center=True)
            else:
                head(t.cell(0, c).merge(t.cell(1, c)), header[c] if c < len(header) else "", False, center=True)
            c += span
    else:
        for c in range(ncol):
            head(t.cell(0, c), header[c] if c < len(header) else "", c > 0)
    for r, row in enumerate(rows, start=1 + top):
        total = bool(row and _TOTAL.search(row[0]["text"]))
        for c in range(ncol):
            cell_data = row[c] if c < len(row) else {"text": "", "num": False}
            _cell_text(t.cell(r, c), cell_data["text"], bold=total, right=bool(cell_data.get("num")) or (c > 0 and cell_data["text"].strip() in ("-", "–")))
            if total:
                _shade(t.cell(r, c), "EEF2F7")
    widths = [Cm(6.2)] + [Cm(max(2.2, 10.4 / max(1, ncol - 1)))] * (ncol - 1)
    for row in t.rows:
        for c, w in enumerate(widths[:ncol]):
            row.cells[c].width = w


def _chart(d: Document, b: Dict[str, Any]) -> None:
    """차트 블록 → Word 네이티브 차트. 문서 양식의 차트 양식(look)·막대+선·밴드·영역·원은 양식 모양(docx_chart.chart_xml_form)."""
    series = [(s["name"], s["values"]) for s in b["series"]]
    kind = b.get("chartType") or "bar"
    height = Cm(max(6.0, 0.75 * len(b["categories"]) + 2)) if b.get("horizontal") and kind == "bar" else Cm(7.0)
    form = None
    if "look" in b or kind in ("area", "pie", "combo", "band"):
        look = b.get("look") or {}
        form = {
            "meta": [{k: s.get(k) for k in ("type", "axis", "computed") if s.get(k)} for s in b["series"]],
            "colors": look.get("colors") or [],
            "labels": look.get("labels"),
            "legend": b.get("legend") or "",
            "grid": look.get("grid", True),
        }
    add_chart(d.add_paragraph(), categories=b["categories"], series=series, kind=kind, horizontal=bool(b.get("horizontal")), number_format=b.get("number") or "0.0", height=height, form=form)


def _missing(d: Document, b: Dict[str, Any]) -> None:
    p = d.add_paragraph(f"데이터 없음 — 성과 데이터 엑셀에 시트 '{b.get('sheet')}' 를 올리면 채워집니다.", style="Source Note")
    p.runs[0].italic = True


def build_format_docx(doc: Doc) -> Tuple[bytes, str]:
    view = build_report_view(doc)
    d = Document()
    _setup_styles(d)
    d.add_paragraph(view["title"], style="Title")
    d.add_paragraph(view["subtitle"], style="Subtitle")
    for b in view["blocks"]:
        kind = b["kind"]
        if kind == "heading":
            d.add_paragraph(b["text"], style="Heading 1")
        elif kind == "para":
            d.add_paragraph(b["text"])
        elif kind == "list":
            for it in b["items"]:
                d.add_paragraph(it["text"], style="List Bullet")
        elif kind == "empty":
            p = d.add_paragraph("(본문 미작성)", style="Source Note")
            p.runs[0].italic = True
        elif kind in ("table", "chart"):
            _caption(d, b)
            if b.get("missing"):
                _missing(d, b)
                continue
            (_table if kind == "table" else _chart)(d, b)
            _source(d, b, view)
    if view["sources"]:
        d.add_paragraph("참고 자료", style="Heading 1")
        for src in view["sources"]:
            d.add_paragraph(source_line(src), style="Source Note")
    d.add_paragraph("본 자료는 업로드한 자료를 근거로 AI 가 작성한 초안이며, 표·그림의 숫자는 성과 데이터에서 코드가 옮겼습니다. 최종 판단의 책임은 이용자에게 있습니다.", style="Source Note")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue(), f"{_safe(view['title'])}_{time.strftime('%Y%m%d')}.docx"


def _safe(title: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", title or "").strip() or "report"


def _num(text: str) -> Optional[float]:
    t = re.sub(r"[,%\s]", "", text or "").replace("−", "-")
    try:
        return float(t)
    except ValueError:
        return None


def _excel_format(fmt: str) -> str:
    return fmt or "General"


def build_blocks_xlsx(doc: Doc) -> Tuple[bytes, str]:
    """표·그림 데이터 — 블록마다 시트(표 n / 그림 n). 그림은 엑셀 막대 그래프로(데이터를 고치면 다시 그려진다)."""
    view = build_report_view(doc)
    blocks: List[Dict[str, Any]] = [b for b in view["blocks"] if b["kind"] in ("table", "chart")]
    return write_blocks_xlsx(blocks), f"{_safe(view['title'])}_표·그림 데이터_{time.strftime('%Y%m%d')}.xlsx"


def build_table_docx(block: Dict[str, Any], title: str) -> Tuple[bytes, str]:
    """리서치 표·차트 하나 — 캡션·네이티브 워드 표(차트면 네이티브 차트)·출처 줄."""
    d = Document()
    _setup_styles(d)
    _caption(d, {**block, "label": block.get("caption") or title})
    (_chart if block.get("kind") == "chart" else _table)(d, block)
    if block.get("sourceLine"):
        d.add_paragraph(block["sourceLine"], style="Source Note")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue(), f"{_safe(title)}_{time.strftime('%Y%m%d')}.docx"


def build_note_docx(block: Dict[str, Any], title: str) -> Tuple[bytes, str]:
    """리서치 메모 — 제목·본문(출처 링크는 '(문서, p.n)' 글로)·출처 목록."""
    from app.research.notes import plain

    d = Document()
    _setup_styles(d)
    d.add_paragraph(title, style="Heading 1")
    for line in plain(block.get("text") or "").split("\n"):
        if line.strip():
            d.add_paragraph(re.sub(r"^\s*[-*]\s+", "· ", line.strip().replace("**", "")))
    if block.get("cites"):
        d.add_paragraph("출처: " + "; ".join(dict.fromkeys(c.get("label") or "" for c in block["cites"])), style="Source Note")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue(), f"{_safe(title)}_{time.strftime('%Y%m%d')}.docx"


def build_table_xlsx(block: Dict[str, Any], title: str) -> Tuple[bytes, str]:
    return write_blocks_xlsx([{**block, "no": 1, "label": block.get("caption") or title}]), f"{_safe(title)}_{time.strftime('%Y%m%d')}.xlsx"


def write_blocks_xlsx(blocks: List[Dict[str, Any]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    head_fill = PatternFill("solid", fgColor=NAVY_HEX)
    seen = set()
    for b in blocks:
        name = f"{'표' if b['kind'] == 'table' else '그림'} {b['no']}"
        if name in seen:
            continue
        seen.add(name)
        ws = wb.create_sheet(name)
        ws.append([b["label"]])
        ws["A1"].font = Font(bold=True, color=NAVY_HEX, size=12)
        ws.append([f"단위: {b.get('unit') or '-'}"])
        if b.get("missing"):
            ws.append([f"데이터 없음 — 성과 데이터 엑셀에 시트 '{b.get('sheet')}' 를 올리면 채워집니다."])
            continue
        if b["kind"] == "table":
            header = b["header"]
            ws.append(header)
            for row in b["rows"]:
                vals: List[Any] = []
                for c, cell in enumerate(row):
                    v = _num(cell["text"]) if cell.get("num") else None
                    vals.append(v if v is not None else cell["text"])
                ws.append(vals)
                for c, cell in enumerate(ws[ws.max_row]):
                    if isinstance(cell.value, (int, float)):
                        cell.number_format = _excel_format(b.get("number") or "")
            first_data = 4
        else:
            header = ["", *[s["name"] for s in b["series"]]]
            ws.append(header)
            for i, cat in enumerate(b["categories"]):
                ws.append([cat, *[s["values"][i] for s in b["series"]]])
                for cell in ws[ws.max_row][1:]:
                    cell.number_format = _excel_format(b.get("number") or "")
            first_data = 4
            last = ws.max_row
            if last >= first_data:
                if b.get("chartType") == "line":
                    ch = LineChart()
                else:
                    ch = BarChart()
                    ch.type = "bar" if b.get("horizontal") else "col"
                ch.title = b["title"]
                ch.y_axis.title = b.get("unit") or None
                ch.add_data(Reference(ws, min_col=2, max_col=1 + len(b["series"]), min_row=3, max_row=last), titles_from_data=True)
                ch.set_categories(Reference(ws, min_col=1, min_row=first_data, max_row=last))
                ch.height, ch.width = 8, 16
                ws.add_chart(ch, f"{chr(ord('A') + len(header) + 1)}3")
        for cell in ws[3]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = head_fill
            cell.alignment = Alignment(horizontal="center")
        ws.append([])
        ws.append([b["sourceLine"] if b.get("sourceLine") else f"자료: {b.get('docLabel') or ''} · 시트 {b.get('sheet') or ''}" + (f" (표 {b['from']})" if b.get("from") else "")])
        ws.column_dimensions["A"].width = 30
        for col in "BCDEFG":
            ws.column_dimensions[col].width = 15
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


__all__ = ["build_format_docx", "build_blocks_xlsx", "build_note_docx", "build_table_docx", "build_table_xlsx", "write_blocks_xlsx"]
