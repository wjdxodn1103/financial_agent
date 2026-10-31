"""공식 일정표(연초 공표) — 중앙은행 회의·국가데이터처 공표·휴장, 그리고 FRED 키가 없을 때 쓰는 BLS 공표일.
2026-10-29 공식 페이지에서 옮긴 것만 넣는다(출처 URL). 공식 확인이 안 된 날짜는 confirmed=False 로 두고 화면에 '공식 확인 전'을 보인다.
해마다(또는 기관이 바꾸면) 여기를 고친다 — 관리자 화면 [일정 다시 받기]가 이 표 + FRED 발표일 + 만기 규칙을 합친다.
"""
from __future__ import annotations

from typing import Any, Dict, List

FOMC = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
ECB = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"
BLS_11 = "https://www.bls.gov/schedule/2026/11_sched_list.htm"
BLS_12 = "https://www.bls.gov/schedule/2026/12_sched_list.htm"
KOSTAT = "https://mods.go.kr/lcofNewsPln.es?mid=a60303000000"
ICE = "https://ir.theice.com/press/news-details/2023/NYSE-Group-Announces-2024-2025-and-2026-Holiday-and-Early-Closings-Calendar/default.aspx"


def _ind(ind: str, date: str, period: str, period_key: str, url: str, confirmed: bool = True, note: str = "") -> Dict[str, Any]:
    return {"indicator": ind, "date": date, "period": period, "periodKey": period_key, "url": url, "confirmed": confirmed, "note": note}


def _gen(title: str, country: str, category: str, importance: int, date: str, url: str, time: str = "", tz: str = "", note: str = "") -> Dict[str, Any]:
    return {"title": title, "country": country, "category": category, "importance": importance, "date": date, "time": time, "tz": tz, "url": url, "confirmed": True, "note": note}


FIXED: List[Dict[str, Any]] = [
    # FOMC — 결정일(회의 둘째 날) 14:00 ET. 2027 은 연준 공지상 직전 회의에서 확정되는 잠정 일정
    _ind("us_fomc", "2026-10-28", "2026년 10월 회의", "2026-10-28", FOMC),
    _ind("us_fomc", "2026-12-09", "2026년 12월 회의(경제전망)", "2026-12-09", FOMC),
    *[_ind("us_fomc", d, f"{d[:4]}년 {int(d[5:7])}월 회의", d, FOMC, note="잠정(직전 회의에서 확정)") for d in
      ("2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08")],
    # ECB — 결정일(둘째 날) 14:15 CET
    *[_ind("eu_ecb", d, f"{d[:4]}년 {int(d[5:7])}월 회의", d, ECB) for d in
      ("2026-10-29", "2026-12-17", "2027-02-04", "2027-03-18", "2027-04-29", "2027-06-10", "2027-07-22", "2027-09-09", "2027-10-28", "2027-12-16")],
    # 한국은행 금통위 — 공식 공지로 확인하지 못함(보도 기준)
    _ind("kr_bok", "2026-11-26", "2026년 11월 회의", "2026-11-26", "https://www.bok.or.kr/", confirmed=False, note="보도 기준 — 한국은행 공지 확인 전"),
    # BLS(미 노동통계국) 공표일 — FRED 키가 있으면 FRED 발표일이 같은 자리를 채운다
    _ind("us_jolts", "2026-11-03", "2026년 9월", "2026-09", BLS_11), _ind("us_jolts", "2026-12-01", "2026년 10월", "2026-10", BLS_12),
    _ind("us_nfp", "2026-11-06", "2026년 10월", "2026-10", BLS_11), _ind("us_nfp", "2026-12-04", "2026년 11월", "2026-11", BLS_12),
    _ind("us_unrate", "2026-11-06", "2026년 10월", "2026-10", BLS_11), _ind("us_unrate", "2026-12-04", "2026년 11월", "2026-11", BLS_12),
    _ind("us_cpi", "2026-11-10", "2026년 10월", "2026-10", BLS_11), _ind("us_cpi", "2026-12-10", "2026년 11월", "2026-11", BLS_12),
    _ind("us_core_cpi", "2026-11-10", "2026년 10월", "2026-10", BLS_11), _ind("us_core_cpi", "2026-12-10", "2026년 11월", "2026-11", BLS_12),
    _ind("us_ppi", "2026-11-13", "2026년 10월", "2026-10", BLS_11), _ind("us_ppi", "2026-12-15", "2026년 11월", "2026-11", BLS_12),
    # 국가데이터처 공표일정(보도 08:00 KST)
    _ind("kr_cpi", "2026-11-03", "2026년 10월", "2026-10", KOSTAT), _ind("kr_cpi", "2026-12-02", "2026년 11월", "2026-11", KOSTAT),
    _ind("kr_cpi", "2026-12-31", "2026년 12월 및 연간", "2026-12", KOSTAT),
    _ind("kr_jobs", "2026-11-11", "2026년 10월", "2026-10", KOSTAT), _ind("kr_jobs", "2026-12-16", "2026년 11월", "2026-11", KOSTAT),
    _ind("kr_ip", "2026-11-30", "2026년 10월", "2026-10", KOSTAT), _ind("kr_ip", "2026-12-30", "2026년 11월", "2026-11", KOSTAT),
    # 휴장 — 미국(NYSE)·한국(KRX)
    _gen("미국 증시 휴장(추수감사절)", "US", "holiday", 2, "2026-11-26", ICE),
    _gen("미국 증시 조기 폐장(13:00 ET)", "US", "holiday", 1, "2026-11-27", ICE, time="13:00", tz="America/New_York"),
    _gen("미국 증시 조기 폐장(13:00 ET)", "US", "holiday", 1, "2026-12-24", ICE, time="13:00", tz="America/New_York"),
    _gen("미국 증시 휴장(성탄절)", "US", "holiday", 2, "2026-12-25", ICE),
    _gen("미국 증시 휴장(신정)", "US", "holiday", 2, "2027-01-01", "https://www.nyse.com/markets/hours-calendars"),
    _gen("한국 증시 휴장(성탄절)", "KR", "holiday", 2, "2026-12-25", "https://www.krx.co.kr/"),
    _gen("한국 증시 휴장(연말)", "KR", "holiday", 2, "2026-12-31", "https://www.krx.co.kr/"),
    _gen("한국 증시 휴장(신정)", "KR", "holiday", 2, "2027-01-01", "https://www.krx.co.kr/"),
]

# 만기 규칙이 피해야 할 휴장일(날짜만)
HOLIDAYS = {
    "KR": {"2026-12-25", "2026-12-31", "2027-01-01"},
    "US": {"2026-11-26", "2026-12-25", "2027-01-01"},
}
