"""종목 일봉(주가) — Yahoo Finance(yfinance, 키 없음)에서 받아 price_bar 표에 쌓는다. 사내 공용.

종목은 Yahoo 표기로 받는다(코스피 005930.KS · 코스닥 389500.KQ · 미국 AAPL · 지수 ^KQ11). 같은 (종목, 날짜)는 덮어쓴다 — 다시 받으면 수정 주가가 갱신된다.
Yahoo 데이터는 개인·비상업 이용 약관이라 실서비스에서는 공급자를 바꿔 끼운다(KRX·공공데이터포털 주식시세 등) — source 열이 그 자리.
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.db import PriceBar, engine, iso

SOURCE = "yahoo"
TICKERS_MAX = 20
BENCHMARKS = {"KQ": ("^KQ11", "KOSDAQ"), "KS": ("^KS11", "KOSPI")}  # 종목 접미 → (지수 표기, 이름)
_TICKER = re.compile(r"^\^?[A-Za-z0-9.\-=]{1,20}$")


class PriceError(ValueError):
    pass


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def fetch_daily(ticker: str, days: int = 365) -> Dict[str, Any]:
    """Yahoo 에서 최근 days 일 일봉 → {"ticker", "currency", "bars": [{date, open, high, low, close, adjClose, volume}]}."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    h = t.history(start=(date.today() - timedelta(days=days)).isoformat(), interval="1d", auto_adjust=False)
    bars = []
    for ts, r in h.iterrows():
        close = _num(r.get("Close"))
        if close is None:
            continue
        bars.append({"date": ts.date().isoformat(), "open": _num(r.get("Open")), "high": _num(r.get("High")), "low": _num(r.get("Low")),
                     "close": close, "adjClose": _num(r.get("Adj Close")), "volume": _num(r.get("Volume"))})
    if not bars:
        raise PriceError(f"Yahoo 에서 '{ticker}' 일봉을 찾지 못했습니다(표기 예: 389500.KQ · 005930.KS · AAPL).")
    try:
        currency = str(t.fast_info.get("currency") or "")
    except Exception:  # noqa: BLE001 — 통화는 없어도 된다
        currency = ""
    return {"ticker": ticker, "currency": currency, "bars": bars}


def load(tickers: List[str], days: int = 365) -> List[Dict[str, Any]]:
    """종목마다 받아 쌓는다 → [{ticker, rows, first, last, lastClose, currency} | {ticker, error}]."""
    out: List[Dict[str, Any]] = []
    for raw in list(dict.fromkeys(t.strip() for t in tickers if t and t.strip()))[:TICKERS_MAX]:
        ticker = raw.upper()
        if not _TICKER.match(ticker):
            out.append({"ticker": raw, "error": "종목 표기가 올바르지 않습니다."})
            continue
        try:
            got = fetch_daily(ticker, days)
        except PriceError as e:
            out.append({"ticker": ticker, "error": str(e)})
            continue
        except Exception as e:  # noqa: BLE001 — 네트워크·Yahoo 응답 오류
            out.append({"ticker": ticker, "error": f"받지 못했습니다: {type(e).__name__}: {str(e)[:200]}"})
            continue
        with Session(engine) as s:
            for b in got["bars"]:
                s.merge(PriceBar(id=f"{ticker}|{b['date']}|{SOURCE}", ticker=ticker, date=b["date"], source=SOURCE, open=b["open"], high=b["high"], low=b["low"],
                                 close=b["close"], adj_close=b["adjClose"], volume=b["volume"], currency=got["currency"]))
            s.commit()
        bars = got["bars"]
        out.append({"ticker": ticker, "rows": len(bars), "first": bars[0]["date"], "last": bars[-1]["date"], "lastClose": bars[-1]["close"], "currency": got["currency"]})
    return out


def _ret(bars: List[Dict[str, Any]], days: int) -> Optional[float]:
    """마지막 종가의 days 일 전 대비 수익률(%) — 그날 이전 마지막 거래일 종가와 비교(1년치만 받았으면 첫 거래일, 7일 안쪽). 자료가 모자라면 None."""
    last = bars[-1]
    since = date.fromisoformat(last["date"]) - timedelta(days=days)
    base = [b for b in bars if b["date"] <= since.isoformat()]
    if not base and date.fromisoformat(bars[0]["date"]) <= since + timedelta(days=7):
        base = bars[:1]
    if not base or not base[-1]["close"]:
        return None
    return round((last["close"] / base[-1]["close"] - 1) * 100, 1)


def snapshot(ticker: str, name: str, days: int = 365) -> Dict[str, Any]:
    """쌓인 일봉 → 스냅샷 문서(주가 요약 + 월말 종가 표). 리포트·표·차트가 이 문서를 인용한다(일봉 원자료는 price_bar 에)."""
    import time

    from app.connectors.base import ConnectorError, make_snapshot, snapshot_id
    from app.docs.extract import table_text

    v = view(ticker, days)
    bars = v["bars"]
    if not bars:
        raise ConnectorError("NO_PRICES", f"'{v['ticker']}' 일봉이 아직 없습니다. 관리자가 먼저 적재해야 합니다.", 404)
    cur = v["currency"] or ""
    unit = "원" if cur == "KRW" else cur
    last = bars[-1]
    hi = max(bars, key=lambda b: b["close"])
    lo = min(bars, key=lambda b: b["close"])
    fmt = (lambda x: f"{x:,.0f}") if cur == "KRW" else (lambda x: f"{x:,.2f}")
    # 칸 하나에 값 하나 — '106,400 (2026-05-13)'처럼 날짜를 섞으면 숫자 확인이 값을 못 맞춘다
    summary = [["항목", "값"], ["기준일", last["date"]], [f"종가({unit})", fmt(last["close"])],
               [f"기간 최고 종가({unit})", fmt(hi["close"])], ["기간 최고 종가일", hi["date"]], [f"기간 최저 종가({unit})", fmt(lo["close"])], ["기간 최저 종가일", lo["date"]]]
    periods = (("1개월", 30), ("3개월", 91), ("6개월", 182), ("1년", 365))
    for label, d in periods:
        r = _ret(bars, d)
        if r is not None:
            summary.append([f"{label} 수익률(%)", f"{r:+.1f}"])
    # 거래 — 최근 60거래일 평균(리포트 Company Data 의 '일평균 거래량·거래액(60일)')
    tail = bars[-60:]
    summary.append(["60일 평균 거래량(주)", f"{sum(b['volume'] or 0 for b in tail) / len(tail):,.0f}"])
    summary.append([f"60일 평균 거래대금({unit})", fmt(sum((b["volume"] or 0) * b["close"] for b in tail) / len(tail))])
    # 시장 지수 대비 — 코스닥(.KQ)·코스피(.KS) 종목은 같은 날까지의 지수 일봉(사내 공용에 먼저 쌓아 둬야 한다)로 상대 수익률(%p = 종목 − 지수)
    bench = BENCHMARKS.get(v["ticker"].rsplit(".", 1)[-1]) if "." in v["ticker"] else None
    ib = [b for b in view(bench[0], days + 14)["bars"] if b["date"] <= last["date"]] if bench else []
    if ib:
        summary.append([f"{bench[1]} 지수(p)", f"{ib[-1]['close']:,.2f}"])
        for label, d in periods:
            r, ri = _ret(bars, d), _ret(ib, d)
            if r is not None and ri is not None:
                summary.append([f"{label} 상대수익률(%p)", f"{r - ri:+.1f}"])
    months: Dict[str, Dict[str, Any]] = {}
    for b in bars:
        m = months.setdefault(b["date"][:7], {"close": None, "volume": 0.0})
        m["close"] = b["close"]
        m["volume"] += b["volume"] or 0
    monthly = [["월", f"월말 종가({unit})", "월 거래량(주)"]] + [[k, fmt(m["close"]), f"{m['volume']:,.0f}"] for k, m in months.items()]
    span = f"{bars[0]['date']}~{last['date']}"
    paras: List[Dict[str, Any]] = [
        {"page": None, "kind": "table", "rows": summary, "heading": f"{name} 주가 요약 ({last['date']} 기준)", "unit": None, "sheet": "주가 요약"},
        {"page": None, "kind": "table", "rows": monthly, "heading": f"{name} 월말 종가·거래량 ({span})", "unit": None, "sheet": "월말 종가"},
    ]
    for p in paras:
        p["text"] = table_text(p["rows"])
    title = f"{name} 주가({v['ticker']}, {last['date']} 기준)"
    snap = make_snapshot(
        snapshot_id("prices", v["ticker"], last["date"]),
        file_name=f"주가_{name}_{v['ticker']}_{last['date']}.json",
        file_type="주가",
        paras=paras,
        raw={"ticker": v["ticker"], "currency": cur, "bars": bars},
        card={"title": title, "docType": "주가(일봉)", "date": last["date"], "issuer": "Yahoo Finance", "company": name,
              "oneLine": f"{span} 일봉 {len(bars)}일 — 종가·기간 최고/최저·수익률·월말 종가"},
        snapshot={"connector": "prices", "title": "주가 일봉(Yahoo Finance)", "params": {"ticker": v["ticker"], "days": days},
                  "fetchedAt": v["fetchedAt"] or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "url": f"https://finance.yahoo.com/quote/{v['ticker']}"},
        figure_source="prices",
    )
    return {**snap, "title": title}


def view(ticker: str, days: int = 365) -> Dict[str, Any]:
    """쌓인 일봉 → {ticker, source, currency, fetchedAt, bars}. 없으면 bars 빈 목록."""
    ticker = ticker.strip().upper()
    since = (date.today() - timedelta(days=days)).isoformat()
    with Session(engine) as s:
        rows = s.exec(select(PriceBar).where(PriceBar.ticker == ticker, PriceBar.source == SOURCE, PriceBar.date >= since).order_by(PriceBar.date)).all()
    return {
        "ticker": ticker, "source": SOURCE, "currency": rows[-1].currency if rows else "",
        "fetchedAt": iso(max(r.fetched_at for r in rows)) if rows else None,
        "bars": [{"date": r.date, "open": r.open, "high": r.high, "low": r.low, "close": r.close, "adjClose": r.adj_close, "volume": r.volume} for r in rows],
    }
