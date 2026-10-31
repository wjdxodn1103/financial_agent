"""시장 데이터 공급자 — 공급자마다 `ready()`(키가 있나)·`fetch(code, start, end, as_of)` → [(YYYY-MM-DD, 값)].

새 공급자(Bloomberg·LSEG·사내 DB)는 Provider 하나를 더하고 PROVIDERS 에 넣은 뒤 catalog 의 chain 에 (이름, 코드)를 둔다.
네트워크 호출은 짧은 제한 시간과 한 번의 재시도만 — 실패하면 사슬의 다음 공급자로 넘어간다(market.service).
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import math
import random
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import httpx

from app import config

log = logging.getLogger(__name__)
Obs = List[Tuple[str, float]]
TIMEOUT = 20.0
UA = "DCF-market/1.0"


class ProviderError(Exception):
    pass


def _get(url: str, params: Optional[Dict[str, str]] = None) -> httpx.Response:
    last: Optional[Exception] = None
    for attempt in range(2):
        try:
            r = httpx.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True)
            if r.status_code == 429 and attempt == 0:
                time.sleep(2.0)
                continue
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.6)
    raise ProviderError(str(last)[:200])


class Provider:
    name = ""

    def ready(self) -> bool:
        return True

    def fetch(self, code: str, start: date, end: date, as_of: Optional[str] = None) -> Obs:  # pragma: no cover
        raise NotImplementedError


class Fred(Provider):
    """FRED/ALFRED — FRED_API_KEY 필요(무료). 코드 'CPIAUCSL:pc1' = 전년 대비 변화율. as_of 가 있으면 그날의 빈티지(ALFRED)."""

    name = "fred"
    URL = "https://api.stlouisfed.org/fred/series/observations"

    def ready(self) -> bool:
        return bool(getattr(config, "FRED_API_KEY", ""))

    def fetch(self, code: str, start: date, end: date, as_of: Optional[str] = None) -> Obs:
        sid, _, units = code.partition(":")
        params = {"series_id": sid, "api_key": config.FRED_API_KEY, "file_type": "json", "observation_start": start.isoformat(), "observation_end": end.isoformat()}
        if units:
            params["units"] = units
        if as_of:
            params["realtime_start"] = params["realtime_end"] = as_of
        rows = _get(self.URL, params).json().get("observations") or []
        out: Obs = []
        for r in rows:
            v = r.get("value")
            if v in (None, "", "."):
                continue
            try:
                out.append((r["date"], float(v)))
            except (TypeError, ValueError):
                continue
        time.sleep(0.55)  # FRED 상한(분당 120회) 안쪽
        return out


class Treasury(Provider):
    """미 재무부 일별 국채 수익률 곡선(CSV, 키 없음) — 코드 = 열 이름('10 Yr')."""

    name = "treasury"
    URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"

    def fetch(self, code: str, start: date, end: date, as_of: Optional[str] = None) -> Obs:
        out: Obs = []
        for y in range(start.year, end.year + 1):
            r = _get(self.URL.format(y=y), {"type": "daily_treasury_yield_curve", "field_tdr_date_value": str(y), "page": "", "_format": "csv"})
            for row in csv.DictReader(io.StringIO(r.text)):
                v = row.get(code)
                try:
                    d = datetime.strptime(row["Date"], "%m/%d/%Y").date()
                    if start <= d <= end and v not in (None, ""):
                        out.append((d.isoformat(), float(v)))
                except (KeyError, ValueError):
                    continue
        return sorted(out)


class Ecb(Provider):
    """ECB 기준환율(키 없음) — 값은 '유로당 통화'. 코드 USD = 달러/유로, KRW·JPY = 달러당(교차: 통화/유로 ÷ 달러/유로)."""

    name = "ecb"
    URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.{cur}.EUR.SP00.A"

    def _series(self, cur: str, start: date, end: date) -> Dict[str, float]:
        r = _get(self.URL.format(cur=cur), {"startPeriod": start.isoformat(), "endPeriod": end.isoformat(), "format": "csvdata"})
        out: Dict[str, float] = {}
        for row in csv.DictReader(io.StringIO(r.text)):
            try:
                out[row["TIME_PERIOD"]] = float(row["OBS_VALUE"])
            except (KeyError, ValueError):
                continue
        return out

    def fetch(self, code: str, start: date, end: date, as_of: Optional[str] = None) -> Obs:
        usd = self._series("USD", start, end)
        if code == "USD":
            return sorted(usd.items())
        other = self._series(code, start, end)
        return sorted((d, round(v / usd[d], 4)) for d, v in other.items() if d in usd and usd[d])


class NyFed(Provider):
    """뉴욕 연은 실효 연방기금금리(EFFR, 키 없음)."""

    name = "nyfed"
    URL = "https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json"

    def fetch(self, code: str, start: date, end: date, as_of: Optional[str] = None) -> Obs:
        rows = _get(self.URL, {"startDate": start.isoformat(), "endDate": end.isoformat()}).json().get("refRates") or []
        return sorted((r["effectiveDate"], float(r["percentRate"])) for r in rows if r.get("percentRate") is not None)


class Demo(Provider):
    """데모 값('가상') — 시리즈 id 로 시드를 정한 고정 경로(같은 날짜는 언제나 같은 값). 영업일만, 월간 시리즈는 매달 1일."""

    name = "demo"
    START = date(2023, 1, 2)

    def fetch(self, code: str, start: date, end: date, as_of: Optional[str] = None) -> Obs:
        from app.market.catalog import BY_ID

        s = BY_ID.get(code)
        if s is None:
            raise ProviderError(f"데모 값이 없는 시리즈: {code}")
        p = s.demo or {}
        base, vol, level = float(p.get("base", 100)), float(p.get("vol", 0.01)), bool(p.get("level"))
        rng = random.Random(int(hashlib.sha1(code.encode()).hexdigest()[:8], 16))
        out: Obs = []
        v, d = base, self.START
        today = min(end, date.today())
        while d <= today:
            step_ok = d.weekday() < 5 if s.freq == "D" else d.day == 1
            if step_ok:
                shock = rng.gauss(0, 1)
                if level:
                    v = v + vol * shock - 0.02 * (v - base)  # 평균으로 돌아가는 수준 시리즈(금리·스프레드)
                else:
                    v = v * math.exp(vol * shock - 0.002 * math.log(v / base))
                if d >= start:
                    out.append((d.isoformat(), round(v, max(s.decimals, 2))))
            d += timedelta(days=1)
        return out


PROVIDERS: Dict[str, Provider] = {p.name: p for p in (Fred(), Treasury(), Ecb(), NyFed(), Demo())}
