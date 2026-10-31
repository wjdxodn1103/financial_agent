"""EDGAR 고정 파일 — SEC_USER_AGENT(연락처가 든 User-Agent)가 없을 때 수집 파이프라인이 쓰는 '가상' 공시.

가상 회사 Helios Data Systems(티커 HLDS, CIK 9990001)의 공시 목록(submissions.json)과 공시마다 SEC 가 만드는 꼴의
재무제표 엑셀(Financial_Report.xlsx — '3 Months Ended Sep. 30, 2026' 머리)·실적 보도자료(8-K 본문 글)를 만든다.
데이터센터 매출 전년 대비 증가율: 2026 2분기 +35.9%(30% 넘음) → 3분기 +24.0%(30% 아래) — 가정 감시 데모용.

실행: backend\\.venv\\Scripts\\python.exe demo\\edgar_fixture\\make_fixture.py
"""
from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).resolve().parent / "HLDS"
CIK = 9990001
NAME = "Helios Data Systems (가상)"

# 분기 실적(백만 달러) — (분기 끝, 표기)
Q = {
    "2025Q1": ("Mar. 31, 2025", {"rev": 2410, "dc": 1310, "gp": 1350, "op": 690, "ni": 540, "eps": 1.62}),
    "2025Q2": ("Jun. 30, 2025", {"rev": 2520, "dc": 1420, "gp": 1430, "op": 735, "ni": 575, "eps": 1.72}),
    "2025Q3": ("Sep. 30, 2025", {"rev": 2610, "dc": 1500, "gp": 1490, "op": 770, "ni": 602, "eps": 1.80}),
    "2025Q4": ("Dec. 31, 2025", {"rev": 2790, "dc": 1640, "gp": 1600, "op": 838, "ni": 655, "eps": 1.96}),
    "2026Q1": ("Mar. 31, 2026", {"rev": 2960, "dc": 1780, "gp": 1700, "op": 890, "ni": 698, "eps": 2.09}),
    "2026Q2": ("Jun. 30, 2026", {"rev": 3150, "dc": 1930, "gp": 1810, "op": 952, "ni": 745, "eps": 2.23}),
    "2026Q3": ("Sep. 30, 2026", {"rev": 3090, "dc": 1860, "gp": 1745, "op": 880, "ni": 690, "eps": 2.06}),
}
ROWS = [("Total revenue", "rev"), ("Data center revenue", "dc"), ("Gross profit", "gp"), ("Operating income", "op"), ("Net income", "ni"), ("Diluted EPS (USD)", "eps")]

FILINGS = [
    # (접수번호, 양식, 접수일, 보고 기간 끝, 분기(현재·전년 같은 분기))
    ("0009990001-26-000004", "10-Q", "2026-05-06", "2026-03-31", ("2026Q1", "2025Q1")),
    ("0009990001-26-000007", "10-Q", "2026-08-05", "2026-06-30", ("2026Q2", "2025Q2")),
    ("0009990001-26-000011", "10-Q", "2026-10-28", "2026-09-30", ("2026Q3", "2025Q3")),
    ("0009990001-26-000012", "8-K", "2026-10-28", "2026-10-28", ("2026Q3", "2025Q3")),
]


def workbook(cur: str, prev: str, path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Income Statement"
    ws.append([f"{NAME} — Condensed Consolidated Statements of Income (USD in Millions, except per share)", "", ""])
    ws.append(["", f"3 Months Ended {Q[cur][0]}", f"3 Months Ended {Q[prev][0]}"])
    for label, k in ROWS:
        ws.append([label, Q[cur][1][k], Q[prev][1][k]])
    wb.save(path)


def press_release(cur: str, prev: str) -> str:
    c, p = Q[cur][1], Q[prev][1]
    g = lambda a, b: (a / b - 1) * 100  # noqa: E731
    return (
        f"{NAME} Reports Third Quarter 2026 Results (가상 — 데모용 보도자료)\n\n"
        f"Total revenue was ${c['rev']:,} million, up {g(c['rev'], p['rev']):.1f}% year over year. "
        f"Data center revenue was ${c['dc']:,} million, up {g(c['dc'], p['dc']):.1f}% from ${p['dc']:,} million a year ago, "
        f"as two hyperscale customers delayed capacity orders. Operating income was ${c['op']:,} million and diluted EPS was ${c['eps']:.2f}.\n\n"
        "Management expects data center revenue growth to remain below 30% for the next two quarters while customers digest prior deployments."
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    recent = {"accessionNumber": [], "filingDate": [], "reportDate": [], "form": [], "primaryDocument": []}
    for acc, form, filed, report, (cur, prev) in reversed(FILINGS):  # SEC 목록은 최신이 먼저
        recent["accessionNumber"].append(acc)
        recent["filingDate"].append(filed)
        recent["reportDate"].append(report)
        recent["form"].append(form)
        if form == "8-K":
            name = f"{acc}-press.txt"
            (OUT / name).write_text(press_release(cur, prev), encoding="utf-8")
        else:
            name = f"{acc}-Financial_Report.xlsx"
            workbook(cur, prev, OUT / name)
        recent["primaryDocument"].append(name)
    sub = {"cik": str(CIK), "name": NAME, "tickers": ["HLDS"], "exchanges": ["가상"], "virtual": True, "filings": {"recent": recent}}
    (OUT / "submissions.json").write_text(json.dumps(sub, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
