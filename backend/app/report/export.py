"""리포트 내보내기 — DOCX 한 파일(제목·부제·섹션·본문·참고 자료). 화면과 같은 뷰(build_report_view)에서 만든다."""
from __future__ import annotations

import io
import re
import time
from typing import Tuple

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from app.agent.session import Doc
from app.formats.registry import is_format
from app.report.view import build_report_view, source_line

_FONT = "맑은 고딕"


def _font(run, size: float, bold: bool = False, color: RGBColor | None = None) -> None:
    run.font.name = _FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)
    run.font.size = Pt(size)
    run.bold = bold
    if color is not None:
        run.font.color.rgb = color


def build_docx(doc: Doc) -> Tuple[bytes, str]:
    if is_format(doc.get("reportType")):
        from app.report.format_export import build_format_docx  # 고정 양식 — 표·그림까지 든 양식 스타일 DOCX

        return build_format_docx(doc)
    view = build_report_view(doc)
    d = Document()
    style = d.styles["Normal"]
    style.font.name = _FONT
    style.element.rPr.rFonts.set(qn("w:eastAsia"), _FONT)
    style.font.size = Pt(10.5)

    _font(d.add_paragraph().add_run(view["title"]), 18, bold=True)
    _font(d.add_paragraph().add_run(view["subtitle"]), 9.5, color=RGBColor(0x60, 0x60, 0x60))
    for b in view["blocks"]:
        if b["kind"] == "heading":
            if b.get("status") != "written":
                continue
            _font(d.add_paragraph().add_run(b["text"]), 13, bold=True, color=RGBColor(0x1D, 0x35, 0x57))
        elif b["kind"] == "para":
            _font(d.add_paragraph().add_run(b["text"]), 10.5)
        elif b["kind"] == "list":
            for it in b["items"]:
                _font(d.add_paragraph(style="List Bullet").add_run(it["text"]), 10.5)
        elif b["kind"] == "table":
            # AI 채팅에서 넣은 표 — 네이티브 워드 표(양식 내보내기와 같은 표 모양)
            from app.report.format_export import _table

            _font(d.add_paragraph().add_run(b.get("label") or b.get("title") or ""), 10, bold=True, color=RGBColor(0x1F, 0x3A, 0x5F))
            _table(d, b)
            if b.get("sourceLine"):
                _font(d.add_paragraph().add_run(b["sourceLine"]), 8.5, color=RGBColor(0x60, 0x60, 0x60))
        elif b["kind"] == "chart":
            # 리서치에서 넣은 차트 — 네이티브 워드 차트(막대·꺾은선)
            from app.report.format_export import _chart

            unit = f" (단위: {b['unit']})" if b.get("unit") else ""
            _font(d.add_paragraph().add_run(f"{b.get('label') or b.get('title') or ''}{unit}"), 10, bold=True, color=RGBColor(0x1F, 0x3A, 0x5F))
            _chart(d, b)
            if b.get("sourceLine"):
                _font(d.add_paragraph().add_run(b["sourceLine"]), 8.5, color=RGBColor(0x60, 0x60, 0x60))
    if view["sources"]:
        _font(d.add_paragraph().add_run("참고 자료"), 12, bold=True)
        for src in view["sources"]:
            _font(d.add_paragraph().add_run(source_line(src)), 9)
    _font(d.add_paragraph().add_run("본 자료는 업로드한 문서를 근거로 AI 가 작성한 초안이며, 투자 판단의 최종 책임은 이용자에게 있습니다."), 8, color=RGBColor(0x80, 0x80, 0x80))

    buf = io.BytesIO()
    d.save(buf)
    safe = re.sub(r'[\\/:*?"<>|]+', "_", view["title"]).strip() or "report"
    return buf.getvalue(), f"{safe}_{time.strftime('%Y%m%d')}.docx"
