"""시장 홈 — 네이버 증권·야후 파이낸스처럼 주요 지수·환율·원자재(선물)·금리를 한 화면에(2026-11-03, 금융 데이터 AI 에이전트의 기본 화면).

지수·환율·원자재는 Yahoo Finance 일봉(prices.py 의 price_bar, 사내 공용)에서, 금리는 시장 시계열(FRED·미 재무부 — market.service)에서 가져온다.
숫자는 전부 코드가 계산한다(전일 대비 = 마지막 두 거래일 종가, 52주 고저 = 저장한 일봉). Yahoo 는 개인·비상업 약관이라 로그인 뒤 화면에만 보이고
'시연용'으로 표시한다 — 상용은 라이선스 공급자로 바꿔 끼운다(price_bar 의 source 열).
마지막으로 받은 지 STALE_HOURS 시간이 지나면 보는 사람이 있을 때 뒤에서 다시 받는다(scheduler.spawn — 같은 일은 한 번만 돈다).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app import scheduler
from app.market import prices
from app.market.service import _at_or_before, _minus_month, series_card

log = logging.getLogger(__name__)

STALE_HOURS = 2
SPARK = 30
DAYS = 400  # 52주 고저와 1년 차트를 그릴 만큼
JOB = "market_home"
SOURCE_LABEL = "Yahoo Finance · 지연 시세 · 시연용(상용은 라이선스 데이터로 교체)"
SOURCE_SHORT = "Yahoo Finance(지연 시세·시연용)"  # 오늘의 시장 요약 사실표의 출처 칸

# (Yahoo 표기, 이름, 배율, 소수 자릿수, 단위[, 계산]) — 배율: 원/100엔처럼 표시 단위를 맞출 때.
# 계산 ("div", a, b): Yahoo 에 그 쌍의 일봉이 없을 때(원/위안 CNYKRW=X 는 하루치뿐) 두 표기의 같은 날 종가로 나눈다.
Item = Tuple[Any, ...]
GROUPS: List[Dict[str, Any]] = [
    {"key": "kr", "title": "국내 증시", "items": [("^KS11", "코스피", 1, 2, "pt"), ("^KQ11", "코스닥", 1, 2, "pt")]},
    {"key": "global", "title": "해외 증시", "items": [("^GSPC", "S&P 500", 1, 2, "pt"), ("^IXIC", "나스닥 종합", 1, 2, "pt"), ("^DJI", "다우존스", 1, 2, "pt"),
                                                    ("^N225", "닛케이 225", 1, 2, "pt"), ("^HSI", "항셍", 1, 2, "pt"), ("^STOXX50E", "유로 스톡스 50", 1, 2, "pt")]},
    {"key": "fx", "title": "환율", "items": [("KRW=X", "원/달러", 1, 2, "원"), ("JPYKRW=X", "원/100엔", 100, 2, "원"), ("EURKRW=X", "원/유로", 1, 2, "원"),
                                           ("KRW/CNY", "원/위안", 1, 2, "원", ("div", "KRW=X", "CNY=X")), ("DX-Y.NYB", "달러 인덱스", 1, 2, "pt")]},
    {"key": "cmd", "title": "원자재·선물", "items": [("GC=F", "금 선물", 1, 1, "달러/온스"), ("SI=F", "은 선물", 1, 2, "달러/온스"), ("CL=F", "WTI 선물", 1, 2, "달러/배럴"),
                                                ("BZ=F", "브렌트유 선물", 1, 2, "달러/배럴"), ("HG=F", "구리 선물", 1, 3, "달러/파운드"), ("NG=F", "천연가스 선물", 1, 3, "달러/MMBtu")]},
]
BY_TICKER: Dict[str, Item] = {it[0]: it for g in GROUPS for it in g["items"]}
RATES = ["us_ff", "us_2y", "us_10y", "us_10y2y"]  # 시장 시계열(FRED·미 재무부 실데이터)
MAIN = ["^KS11", "^GSPC", "KRW=X", "GC=F"]  # 큰 차트 탭
RANGES = {"1M": 31, "3M": 92, "6M": 183, "1Y": 366}


def tickers() -> List[str]:
    """받을 Yahoo 표기 — 계산 항목은 재료 두 표기를 받는다."""
    out: List[str] = []
    for it in BY_TICKER.values():
        out += list(it[5][1:]) if len(it) > 5 else [it[0]]
    return list(dict.fromkeys(out))


def _bars(it: Item, days: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """→ ([{date, close}] 배율 적용 전, 가장 오래된 받은 시각). 계산 항목은 두 재료의 같은 날 종가로."""
    if len(it) > 5:
        _op, a, b = it[5]
        va, vb = prices.view(a, days), prices.view(b, days)
        cb = {x["date"]: x["close"] for x in vb["bars"] if x.get("close")}
        bars = [{"date": x["date"], "close": x["close"] / cb[x["date"]]} for x in va["bars"] if x.get("close") is not None and cb.get(x["date"])]
        got = [t for t in (va["fetchedAt"], vb["fetchedAt"])]
        return bars, (min(got) if all(got) else None)
    v = prices.view(it[0], days)
    return [b for b in v["bars"] if b.get("close") is not None], v["fetchedAt"]


def _parse(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.rstrip("Z"))
    except ValueError:
        return None


def _quote(it: Item) -> Dict[str, Any]:
    ticker, name, scale, dec, unit = it[:5]
    bars, fetched = _bars(it, DAYS)
    out: Dict[str, Any] = {"ticker": ticker, "name": name, "unit": unit, "decimals": dec, "value": None, "date": None, "spark": [],
                           "change": None, "pct": None, "high52": None, "low52": None, "fetchedAt": fetched}
    if not bars:
        return out
    closes = [b["close"] * scale for b in bars]
    last = closes[-1]
    out.update(value=round(last, dec), date=bars[-1]["date"], spark=[round(c, dec) for c in closes[-SPARK:]])
    if len(closes) > 1 and closes[-2]:
        out["change"] = round(last - closes[-2], dec)
        out["pct"] = round((last / closes[-2] - 1) * 100, 2)
    since = (date.fromisoformat(bars[-1]["date"]) - timedelta(days=365)).isoformat()
    year = [c for b, c in zip(bars, closes) if b["date"] >= since]
    if year:
        out["high52"], out["low52"] = round(max(year), dec), round(min(year), dec)
    return out


async def _refresh() -> None:
    res = await asyncio.to_thread(prices.load, tickers(), DAYS)
    bad = [r for r in res if r.get("error")]
    if bad:
        log.warning("[market_home] %d/%d tickers failed: %s", len(bad), len(res), "; ".join(f"{r['ticker']}: {r['error'][:80]}" for r in bad[:5]))


def ensure_refresh() -> bool:
    """뒤에서 다시 받기 — 이미 돌고 있으면 띄우지 않는다."""
    return scheduler.spawn(JOB, _refresh())


def _stale(times: List[Optional[datetime]]) -> bool:
    if not times or any(t is None for t in times):  # 하나라도 없으면 받아야 한다
        return True
    return datetime.now(timezone.utc).replace(tzinfo=None) - min(t for t in times if t) > timedelta(hours=STALE_HOURS)


async def refresh_if_stale() -> None:
    """오늘의 시장 요약을 쓰기 직전 — 받은 지 오래됐으면 기다려서 받는다(요약 숫자 = 화면 숫자)."""
    if _stale([_parse(_bars(it, 31)[1]) for it in BY_TICKER.values()]):
        await _refresh()


def quotes(as_of: Optional[str] = None) -> List[Dict[str, Any]]:
    """오늘의 시장 요약(market/summary.py) 사실표용 — 화면과 같은 값, 전일·1주·1달 대비 %(as_of 가 있으면 그날까지의 일봉으로).
    시장 시계열 카드(series_card)와 같은 모양으로 돌려준다(id 대신 ticker)."""
    out: List[Dict[str, Any]] = []
    for g in GROUPS:
        for it in g["items"]:
            ticker, name, scale, dec, unit = it[:5]
            bars = [b for b in _bars(it, DAYS)[0] if not as_of or b["date"] <= as_of]
            if not bars:
                continue
            pts = [(b["date"], b["close"] * scale) for b in bars]
            d, v = pts[-1]
            last = date.fromisoformat(d)
            refs = {"d1": pts[-2] if len(pts) > 1 else None, "w1": _at_or_before(pts, last - timedelta(days=7)), "m1": _at_or_before(pts, _minus_month(last))}
            changes = {}
            for k, ref in refs.items():
                if ref and ref[1]:
                    x = (v / ref[1] - 1) * 100
                    changes[k] = {"value": round(x, 2), "unit": "%", "display": f"{x:+.2f}%"}
            out.append({"id": None, "ticker": ticker, "name": name, "group": g["title"], "unit": unit, "date": d, "value": round(v, dec), "display": f"{v:,.{dec}f}",
                        "changes": changes, "sourceLabel": SOURCE_SHORT, "virtual": False, "fallback": False})
    return out


def view() -> Dict[str, Any]:
    groups = [{"key": g["key"], "title": g["title"], "items": [_quote(it) for it in g["items"]]} for g in GROUPS]
    times = [_parse(q["fetchedAt"]) for g in groups for q in g["items"]]
    if _stale(times):
        ensure_refresh()
    newest = max((t for t in times if t), default=None)
    rates = []
    for sid in RATES:
        try:
            rates.append(series_card(sid))
        except Exception:  # noqa: BLE001 — 금리 하나가 안 돼도 화면은 그린다
            log.exception("[market_home] rate %s failed", sid)
    return {
        "groups": groups,
        "rates": rates,
        "main": MAIN,
        "source": SOURCE_LABEL,
        "fetchedAt": newest.isoformat(timespec="seconds") + "Z" if newest else None,
        "refreshing": scheduler.is_running(JOB),
    }


def chart(ticker: str, rng: str = "1Y") -> Dict[str, Any]:
    """큰 차트 — 시장 홈에 있는 종목만(아무 표기나 받지 않는다)."""
    it = BY_TICKER.get(ticker.strip().upper())
    if it is None:
        raise KeyError(ticker)
    tk, name, scale, dec, unit = it[:5]
    days = RANGES.get(rng, 366)
    bars, _f = _bars(it, days)
    return {"ticker": tk, "name": name, "unit": unit, "decimals": dec, "range": rng if rng in RANGES else "1Y",
            "points": [{"date": b["date"], "value": round(b["close"] * scale, dec)} for b in bars], "source": SOURCE_LABEL}
