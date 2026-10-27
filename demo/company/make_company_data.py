"""사내 공용 데이터(더미) — 회사가 모든 워크스페이스에 미리 넣어 두는 데이터 자리. 값은 데모용 더미다(공개 수치를 어림한 것 포함, 정확성 보장 없음).

  backend/.venv/Scripts/python demo/company/make_company_data.py   → demo/company/data/ 에 4개 파일
  backend/.venv/Scripts/python demo/company/seed_company.py        → 백엔드(8200)의 사내 공용 데이터로 넣기

워크북 규칙(근거 원장이 칸을 정확히 읽게 — demo/nbim/make_pack.py 와 같다): 시트 1개 = 표 1개, 제목 줄 → (단위: …) 줄 → 머리 행,
빈 줄·병합 없음, 행 이름은 다른 데모 데이터(A사·NBIM)와 겹치지 않게(원장 충돌 방지), 기간 머리는 '2024년'.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

OUT = Path(__file__).resolve().parent / "data"

YEARS = ["2021년", "2022년", "2023년", "2024년", "2025년"]

MACRO_RATES = [
    ["한국 기준금리(연말)", 1.00, 3.25, 3.50, 3.00, 2.50],
    ["미국 기준금리 상단(연말)", 0.25, 4.50, 5.50, 4.50, 3.75],
    ["한국 소비자물가 상승률", 2.5, 5.1, 3.6, 2.3, 2.0],
    ["미국 소비자물가 상승률", 4.7, 8.0, 4.1, 2.9, 2.7],
    ["한국 국고채 10년 금리(연말)", 2.25, 3.73, 3.18, 2.86, 2.80],
    ["미국 국채 10년 금리(연말)", 1.51, 3.88, 3.88, 4.57, 4.20],
]
MACRO_FX = [  # 괄호 안은 지표 키에서 빠지므로 연평균·연말을 이름에 쓴다
    ["원/달러 연평균 환율", 1144, 1292, 1306, 1364, 1410],
    ["원/달러 연말 환율", 1186, 1265, 1289, 1472, 1440],
    ["원/유로 연평균 환율", 1354, 1358, 1413, 1475, 1590],
]
BENCH_YEARS = ["2021년", "2022년", "2023년", "2024년"]
BENCH = [
    ["MSCI ACWI 지수 수익률", 18.5, -18.4, 22.2, 17.5],
    ["MSCI 선진국 지수 수익률", 21.8, -18.1, 23.8, 18.7],
    ["MSCI 신흥국 지수 수익률", -2.5, -20.1, 9.8, 7.5],
    ["KOSPI 지수 수익률", 3.6, -24.9, 18.7, -9.6],
    ["블룸버그 글로벌 종합채권 지수 수익률", -4.7, -16.2, 5.7, -1.7],
    ["미국 국채 지수 수익률", -2.3, -12.5, 4.1, 0.6],
    ["글로벌 리츠 지수 수익률", 26.1, -24.4, 10.9, 0.9],
]
FIN_YEARS = ["2022년", "2023년", "2024년"]
FIN = [
    ["가온전자 매출액", 8420, 9130, 10250],
    ["가온전자 영업이익", 612, 704, 868],
    ["가온전자 당기순이익", 455, 521, 640],
    ["나래바이오 매출액", 2310, 2795, 3420],
    ["나래바이오 영업이익", 184, 251, 377],
    ["나래바이오 당기순이익", 129, 196, 288],
    ["다온에너지 매출액", 15600, 14280, 15910],
    ["다온에너지 영업이익", 1120, 868, 1043],
    ["다온에너지 당기순이익", 790, 571, 702],
]

POLICY = """# 사내 투자정책서 (더미)

관리 부서: 투자전략팀 · 시행일: 2025-01-01 · 데모용 더미 데이터입니다.

## 1. 목적
이 정책서는 기금 자산의 장기 수익을 높이면서 감내할 수 있는 위험 안에서 운용하기 위한 기준을 정한다. 모든 투자 검토 문서와 운용 보고서는 이 정책서의 자산배분 기준과 위험 한도를 따른다.

## 2. 전략적 자산배분
| 기준 | 비중 |
| --- | --- |
| 주식 전략적 목표 비중(사내 정책) | 60% |
| 주식 허용 하한(사내 정책) | 50% |
| 주식 허용 상한(사내 정책) | 70% |
| 채권 전략적 목표 비중(사내 정책) | 30% |
| 대체투자 전략적 목표 비중(사내 정책) | 10% |

## 3. 위험 한도
- 기대 추적오차는 연 1.5% 이내로 관리한다.
- 단일 발행자에 대한 투자는 기금 자산의 5%를 넘지 않는다.
- 비상장 자산(부동산·인프라·사모)의 합계 비중은 15%를 넘지 않는다.

## 4. 투자 의사결정
- 건별 5,000억원 이상 투자는 투자심의위원회 승인을 받는다.
- 투자 검토 보고서에는 투자 요약, 시장·산업 분석, 재무 분석, 위험 요인, 투자 의견을 담는다.
- 수치는 출처(공시·IR 자료·사내 데이터)를 밝히고, 자료마다 값이 다르면 채택한 값과 이유를 적는다.

## 5. 보고
- 운용 성과는 분기마다 투자위원회에 보고하고, 반기마다 운용보고서를 낸다.
- 위험 한도를 넘으면 5영업일 안에 원인과 조정 계획을 보고한다.
"""


def sheet(wb: Workbook, name: str, title: str, unit: str, header: list, rows: list, fmt: str) -> None:
    ws = wb.create_sheet(name)
    ws.append([title])
    ws.append([f"(단위: {unit})"])
    ws.append(header)
    ws["A1"].font = Font(bold=True)
    for c in ws[3]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3864")
        c.alignment = Alignment(horizontal="center")
    for r in rows:
        ws.append(r)
        for c in ws[ws.max_row][1:]:
            c.number_format = fmt
    ws.column_dimensions["A"].width = 36
    for col in "BCDEF":
        ws.column_dimensions[col].width = 12


def book(path: Path, title: str, sheets: list) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    for s in sheets:
        sheet(wb, *s)
    wb.properties.title = title
    wb.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    book(OUT / "거시경제_지표_DB.xlsx", "거시경제 지표 DB(더미)", [
        ("금리_물가", "거시경제 지표 — 금리·물가(연간, 더미 데이터)", "%", ["구분", *YEARS], MACRO_RATES, "0.00"),
        ("환율", "거시경제 지표 — 환율(연간, 더미 데이터)", "원", ["구분", *YEARS], MACRO_FX, "#,##0"),
    ])
    book(OUT / "자산군_벤치마크_수익률_DB.xlsx", "자산군 벤치마크 수익률 DB(더미)", [
        ("벤치마크_연간수익률", "자산군 벤치마크 연간 수익률(현지 통화 기준, 더미 데이터)", "%", ["구분", *BENCH_YEARS], BENCH, "0.0"),
    ])
    book(OUT / "국내상장사_재무_DB.xlsx", "국내 상장사 재무 DB(DART 형식, 더미)", [
        ("재무요약", "국내 상장사 연결 재무 요약(DART 형식, 가상 기업 더미 데이터)", "억원", ["구분", *FIN_YEARS], FIN, "#,##0"),
    ])
    (OUT / "사내_투자정책서.md").write_text(POLICY, encoding="utf-8")
    for p in sorted(OUT.iterdir()):
        print(p.name, p.stat().st_size)


if __name__ == "__main__":
    main()
