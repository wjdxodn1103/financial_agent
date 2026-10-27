"""데모 자료 만들기 — 가상의 'A사'(데이터센터 인프라) 자료 묶음. 실제 회사·수치가 아니다.

  python demo/make_materials.py            → demo/materials/ 에 6개 파일
  (backend 가상환경의 python-docx·openpyxl·PyMuPDF 를 쓴다: backend/.venv/Scripts/python demo/make_materials.py)

자료끼리 일부러 어긋나게 만든 곳(데모에서 보여 줄 장면):
  - 2024 매출: IR·실적 요약·재무 엑셀 = 3,150억원, 증권사 추정 = 3,160억원 → 근거 원장 '자료마다 다름'
  - 타 부서 초안: 매출 3,200억원(불일치) · 영업이익 증가율 30.0%(계산 오류, 실제 23.9%) · EBITDA 520억원(근거 없음) ·
    요약의 매출 3,150억원(같은 문서 안 불일치) · 변동금리 차입금 1,200억원(일치)
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz  # PyMuPDF
from docx import Document
from docx.shared import Pt
from openpyxl import Workbook

OUT = Path(__file__).resolve().parent / "materials"


def _table(doc: Document, rows):
    t = doc.add_table(rows=len(rows), cols=len(rows[0]))
    t.style = "Table Grid"
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            t.cell(r, c).text = v
    return t


def ir_pdf(path: Path) -> None:
    doc = fitz.open()
    f = "korea"

    def table(page, x0, y0, rows, widths, rh=22):
        x = x0
        for c, w in enumerate(widths):
            for r, row in enumerate(rows):
                rect = fitz.Rect(x, y0 + r * rh, x + w, y0 + (r + 1) * rh)
                page.draw_rect(rect, color=(0.2, 0.2, 0.2), width=0.6)
                page.insert_textbox(rect + (5, 5, -5, 0), row[c], fontsize=9, fontname=f)
            x += w
        return y0 + len(rows) * rh

    p = doc.new_page()
    p.insert_text((60, 70), "A사 2024년 4분기 실적 발표 (IR)", fontsize=17, fontname=f)
    p.insert_text((60, 92), "2025년 1월 · 투자자 설명 자료 (가상 기업 데모 자료)", fontsize=9, fontname=f)
    p.insert_text((60, 125), "2024년 연결 기준 매출액은 3,150억원으로 전년 대비 12.5% 증가했으며, 영업이익은 347억원을 기록했습니다.", fontsize=10, fontname=f)
    p.insert_text((60, 142), "데이터센터 인프라 수주 확대와 클라우드 운영 서비스 성장이 실적을 이끌었습니다.", fontsize=10, fontname=f)
    p.insert_text((60, 175), "연결 손익 요약 (단위: 억원)", fontsize=10, fontname=f)
    y = table(p, 60, 183, [["구분", "2022", "2023", "2024"], ["매출액", "2,450", "2,800", "3,150"], ["영업이익", "230", "280", "347"], ["순이익", "180", "224", "278"], ["영업이익률", "9.4%", "10.0%", "11.0%"]], [140, 100, 100, 100])
    p.insert_text((60, y + 34), "사업 부문별 매출 (2024, 단위: 억원)", fontsize=10, fontname=f)
    table(p, 60, y + 42, [["부문", "매출액", "비중"], ["데이터센터 인프라", "1,890", "60.0%"], ["클라우드 운영 서비스", "945", "30.0%"], ["기타", "315", "10.0%"]], [180, 100, 100])

    p2 = doc.new_page()
    p2.insert_text((60, 70), "재무 상태와 주요 위험", fontsize=15, fontname=f)
    p2.insert_text((60, 100), "재무 상태 요약 (단위: 억원)", fontsize=10, fontname=f)
    y = table(p2, 60, 108, [["구분", "2023", "2024"], ["총차입금", "1,650", "1,800"], ["변동금리 차입금", "1,100", "1,200"], ["현금성자산", "520", "610"], ["부채비율", "118%", "112%"]], [160, 110, 110])
    lines = [
        "금리 위험: 총차입금 중 변동금리 차입금은 1,200억원으로, 기준금리가 1%p 오르면 연간 이자비용이 약 12억원 늘어납니다.",
        "환율 위험: 매출의 약 30%가 달러 표시 계약이라 원/달러 환율이 10% 내리면 연간 매출이 약 95억원 줄어들 수 있습니다.",
        "고객 집중: 상위 3개 고객 매출 비중은 41%로, 대형 고객의 투자 일정 변동이 실적에 영향을 줄 수 있습니다.",
        "전망: 데이터센터 수요 증가로 2025년에도 매출 성장이 이어질 것으로 기대합니다(회사 전망).",
    ]
    for i, t in enumerate(lines):
        p2.insert_textbox(fitz.Rect(60, y + 30 + i * 46, 540, y + 30 + i * 46 + 44), t, fontsize=10, fontname=f)
    doc.save(str(path))


def summary_docx(path: Path) -> None:
    d = Document()
    d.add_heading("A사 2024년 실적 요약", 1)
    d.add_paragraph("A사의 2024년 연결 기준 실적을 요약한다(재무팀 작성).")
    d.add_paragraph("(단위: 억원)")
    _table(d, [["구분", "2023", "2024"], ["매출액", "2,800", "3,150"], ["영업이익", "280", "347"], ["영업이익률", "10.0%", "11.0%"]])
    d.add_paragraph("영업이익은 347억원으로 전년 대비 23.9% 늘었다. 매출 증가율은 12.5%다.")
    d.save(str(path))


def finance_xlsx(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "손익"
    ws.append(["A사 손익 요약"])
    ws.append(["(단위: 억원)"])
    ws.append([])
    ws.append(["계정", "FY2023", "FY2024"])
    ws.append(["매출액", 2800, 3150])
    ws.append(["영업이익", 280, 347])
    ws.append(["순이익", 224, 278])
    ws.append(["영업이익률", 0.10, 0.11])
    ws["B8"].number_format = "0.0%"
    ws["C8"].number_format = "0.0%"
    wb.save(str(path))


def broker_md(path: Path) -> None:
    path.write_text(
        "# B증권 A사 기업 분석 (2025년 1월)\n\n"
        "B증권 리서치센터의 추정치다. 회사 발표치와 다를 수 있다.\n\n"
        "(단위: 억원)\n\n"
        "| 구분 | 2023 | 2024 | 2025E |\n|---|---|---|---|\n"
        "| 매출액 | 2,800 | 3,160 | 3,560 |\n| 영업이익 | 280 | 347 | 405 |\n\n"
        "2025년 매출은 데이터센터 증설 수요로 3,560억원까지 늘 것으로 본다. 목표 PER 15배를 적용했다.\n",
        encoding="utf-8",
    )


def draft_docx(path: Path) -> None:
    d = Document()
    d.add_heading("A사 투자 검토 보고서(투자전략팀 초안)", 1)
    d.add_paragraph("A사의 2024년 연결 기준 매출액은 3,200억원으로 전년 대비 12.5% 증가했다.")
    d.add_paragraph("영업이익은 347억원으로 전년 대비 30.0% 증가했으며, 순이익은 278억원이다.")
    d.add_paragraph("EBITDA는 520억원으로 추정된다.")
    d.add_paragraph("변동금리 차입금은 1,200억원으로 금리 상승에 노출되어 있다.")
    d.add_heading("요약", 2)
    d.add_paragraph("2024년 매출액 3,150억원, 영업이익률 11.0%를 기록했다.")
    d.add_paragraph("(단위: 억원)")
    _table(d, [["구분", "2023", "2024"], ["매출액", "2,800", "3,200"], ["영업이익", "280", "347"]])
    d.save(str(path))


def template_docx(path: Path) -> None:
    """사내 보고서 양식(가상) — 제목 문단이 리포트 섹션이 되고, 아래 안내문이 섹션 작성 지침이 된다."""
    d = Document()
    st = d.styles["Normal"]
    st.font.size = Pt(10.5)
    d.add_heading("투자 검토 보고서", 0)
    _table(d, [["대상 기업", ""], ["작성 부서", "투자전략팀"], ["작성일", ""], ["보안 등급", "대외비"]])
    for title, guide in [
        ("1. 투자 요약", "투자 포인트 3가지와 핵심 수치(매출·이익·성장률)를 3~5문장으로 쓴다."),
        ("2. 회사 개요", "사업 구조와 부문별 매출 비중을 쓴다."),
        ("3. 실적 분석", "최근 3개년 매출·영업이익·이익률 추이와 증감 원인을 쓴다. 증감률은 계산식을 밝힌다."),
        ("4. 리스크 요인", "금리·환율·고객 집중 위험을 수치와 함께 쓴다."),
        ("5. 투자 의견", "투자 의견과 근거, 확인이 더 필요한 사항을 쓴다."),
    ]:
        d.add_heading(title, 1)
        d.add_paragraph(guide)
    d.save(str(path))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    ir_pdf(OUT / "A사_2024_IR.pdf")
    summary_docx(OUT / "A사_2024_실적요약.docx")
    finance_xlsx(OUT / "A사_손익요약.xlsx")
    broker_md(OUT / "B증권_A사_분석.md")
    draft_docx(OUT / "투자검토보고서_초안_투자전략팀.docx")
    template_docx(OUT / "사내양식_투자검토보고서.docx")
    print("\n".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    sys.exit(main())
