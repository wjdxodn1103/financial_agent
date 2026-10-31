"""가상 포트폴리오(보유 내역) — 가이드라인 점검(사내 투자정책서 한도 대조)·포트폴리오 조회용 데모 데이터. 값은 전부 가상이다.

  backend/.venv/Scripts/python demo/portfolio/make_portfolio.py   → demo/company/data/가상_포트폴리오_2026-09말.xlsx
  backend/.venv/Scripts/python demo/company/seed_company.py       → 사내 공용 데이터로 넣기(이미 든 이름은 건너뜀)

정책서 한도와의 관계(데모 이야기): 주식 64%(허용 50~70% 안), 비상장 대체 13.5%(15% 이하), 단일 발행자 — Helios Data Systems 5.6%(5% 넘음 1건).
워크북 규칙은 demo/company/make_company_data.py 와 같다(시트 1개 = 표 1개, 제목 줄 → 단위 줄 → 머리 행, 빈 줄·병합 없음).
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

OUT = Path(__file__).resolve().parents[1] / "company" / "data" / "가상_포트폴리오_2026-09말.xlsx"
TOTAL = 100_000  # 억원

# (종목·자산, 자산군, 발행자, 상장 여부, 지역, 비중 %) — 위탁·펀드는 발행자 '다수'(단일 발행자 한도 대상 아님)
HOLDINGS = [
    ("Helios Data Systems 보통주", "주식", "Helios Data Systems", "상장", "미국", 5.6),
    ("미국 대형주 인덱스 위탁", "주식", "다수", "상장", "미국", 30.4),
    ("유럽 주식 위탁", "주식", "다수", "상장", "유럽", 12.0),
    ("신흥국 주식 위탁", "주식", "다수", "상장", "신흥국", 8.0),
    ("일본 주식 위탁", "주식", "다수", "상장", "일본", 5.0),
    ("가온전자 보통주", "주식", "가온전자", "상장", "한국", 3.0),
    ("미국 국채 직접 보유", "채권", "미국 정부", "상장", "미국", 4.5),
    ("독일 국채 직접 보유", "채권", "독일 정부", "상장", "유럽", 3.0),
    ("일본 국채 직접 보유", "채권", "일본 정부", "상장", "일본", 2.5),
    ("한국 국고채 직접 보유", "채권", "대한민국 정부", "상장", "한국", 4.0),
    ("글로벌 회사채 위탁", "채권", "다수", "상장", "글로벌", 8.5),
    ("북미 핵심 부동산 펀드", "대체", "다수", "비상장", "미국", 4.5),
    ("유럽 인프라 펀드", "대체", "다수", "비상장", "유럽", 4.0),
    ("글로벌 사모 펀드", "대체", "다수", "비상장", "글로벌", 5.0),
]


def main() -> None:
    assert abs(sum(h[5] for h in HOLDINGS) - 100) < 1e-9
    wb = Workbook()
    ws = wb.active
    ws.title = "보유 내역"
    ws.append(["가상 포트폴리오 보유 내역 (2026-09-30 기준, 가상)"])
    ws["A1"].font = Font(bold=True)
    ws.append(["(단위: 억원, %)"])
    ws.append(["종목·자산", "자산군", "발행자", "상장 여부", "지역", "평가액", "비중"])
    for name, cls, issuer, listed, region, w in HOLDINGS:
        ws.append([name, cls, issuer, listed, region, round(TOTAL * w / 100), w])
    for col, width in zip("ABCDEFG", (28, 8, 22, 10, 10, 12, 8)):
        ws.column_dimensions[col].width = width
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
