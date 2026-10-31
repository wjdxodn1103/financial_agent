"""규칙으로 만드는 일정 — 파생상품 만기. 휴장일이면 직전 영업일로 당긴다.
한국: 매월 둘째 목요일(KOSPI200 옵션 만기, 3·6·9·12월은 선물·옵션 동시 만기). 미국: 매월 셋째 금요일(옵션 만기, 분기월은 쿼드러플 위칭)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List

from app.calendar.schedule_data import HOLIDAYS

QUARTER = (3, 6, 9, 12)


def _nth_weekday(y: int, m: int, weekday: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _business(d: date, country: str) -> date:
    while d.weekday() >= 5 or d.isoformat() in HOLIDAYS.get(country, set()):
        d -= timedelta(days=1)
    return d


def expiries(start: date, months: int = 4) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    y, m = start.year, start.month
    for _ in range(months):
        kr = _business(_nth_weekday(y, m, 3, 2), "KR")
        us = _business(_nth_weekday(y, m, 4, 3), "US")
        q = m in QUARTER
        out.append({"key": f"rule:kr_expiry:{kr}", "title": "한국 선물·옵션 동시 만기" if q else "한국 옵션 만기", "country": "KR", "category": "issue",
                    "importance": 2 if q else 1, "date": kr.isoformat(), "time": "", "tz": "Asia/Seoul", "url": "https://www.krx.co.kr/", "note": "규칙: 매월 둘째 목요일"})
        out.append({"key": f"rule:us_expiry:{us}", "title": "미국 쿼드러플 위칭" if q else "미국 옵션 만기", "country": "US", "category": "issue",
                    "importance": 2 if q else 1, "date": us.isoformat(), "time": "", "tz": "America/New_York", "url": "https://www.nyse.com/", "note": "규칙: 매월 셋째 금요일"})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return [e for e in out if e["date"] >= start.isoformat()]
