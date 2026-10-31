"""값 감지 소스 — 공식 기관 API·보도자료에서 '그 기간' 값이 나왔는지 본다. 전부 코드(AI 없음).

- bls: 미 노동통계국 API(키 없으면 v1 — 하루 25회, BLS_API_KEY 가 있으면 v2 — 500회). 여러 시리즈를 한 번에.
- fred: FRED 관측값(units 로 전년비·전월비 변환) — FRED_API_KEY 필요. 발표일 목록(release/dates)도 여기서.
- fomc: 연준 통화정책 보도자료 RSS → 성명 원문에서 '목표 범위 … to … percent' 를 읽는다(키 없음).
- ecos: 한국은행 ECOS(ECOS_API_KEY) — 통계표·항목 코드는 이름으로 처음 한 번 찾는다.
돌려주는 값: [(기간 키, 값)] 오름차순 — 월 'YYYY-MM' · 분기 'YYYYQn' · 일/주 'YYYY-MM-DD'.
"""
from __future__ import annotations

import html
import logging
import re
import threading
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app import config
from app.calendar.catalog import Indicator

log = logging.getLogger(__name__)
UA = {"User-Agent": "DCF research calendar (economic release monitor)"}
TIMEOUT = 20.0
Points = List[Tuple[str, float]]

_bls_used: Dict[str, int] = {}  # 날짜 → 오늘 쓴 BLS 호출 수(키 없으면 25회 한도)
_lock = threading.Lock()


class NoSource(Exception):
    """이 소스를 지금 쓸 수 없음(키 없음·한도)."""


def bls_budget_left() -> int:
    cap = 450 if config.BLS_API_KEY else 20
    return cap - _bls_used.get(date.today().isoformat(), 0)


def bls_fetch(series: List[str]) -> Dict[str, Points]:
    if not series:
        return {}
    with _lock:
        if bls_budget_left() <= 0:
            raise NoSource("BLS 오늘 호출 한도")
        _bls_used[date.today().isoformat()] = _bls_used.get(date.today().isoformat(), 0) + 1
    key = config.BLS_API_KEY
    url = f"https://api.bls.gov/publicAPI/{'v2' if key else 'v1'}/timeseries/data/"
    body: Dict[str, Any] = {"seriesid": list(dict.fromkeys(series))[:25]}
    if key:
        body["registrationkey"] = key
    r = httpx.post(url, json=body, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()
    if d.get("status") != "REQUEST_SUCCEEDED":
        raise NoSource(f"BLS: {d.get('status')} {(d.get('message') or [''])[0]}"[:200])
    out: Dict[str, Points] = {}
    for s in (d.get("Results") or {}).get("series") or []:
        pts = []
        for x in s.get("data") or []:
            p = str(x.get("period") or "")
            if p.startswith("M") and p != "M13":
                try:
                    pts.append((f"{x['year']}-{p[1:]}", float(x["value"])))
                except (KeyError, ValueError):
                    continue
        out[s["seriesID"]] = sorted(pts)
    return out


def transform(points: Points, kind: str) -> Points:
    """원 시계열 → 지표 값(전년비·전월비·차이·천 단위)."""
    if kind in ("level", ""):
        return points
    if kind == "level_k":
        return [(k, v / 1000) for k, v in points]
    by = dict(points)
    out: Points = []
    for i, (k, v) in enumerate(points):
        if kind == "yoy" and len(k) == 7:
            base = by.get(f"{int(k[:4]) - 1}{k[4:]}")
            if base:
                out.append((k, (v / base - 1) * 100))
        elif kind in ("mom", "chg") and i > 0:
            pv = points[i - 1][1]
            if kind == "chg":
                out.append((k, v - pv))
            elif pv:
                out.append((k, (v / pv - 1) * 100))
    return out


def _period_key(d: str, freq: str) -> str:
    if freq == "M":
        return d[:7]
    if freq == "Q":
        return f"{d[:4]}Q{(int(d[5:7]) - 1) // 3 + 1}"
    return d[:10]


def fred_fetch(series: str, kind: str, freq: str, limit: int = 30) -> Points:
    if not config.FRED_API_KEY:
        raise NoSource("FRED 키 없음")
    units = {"yoy": "pc1", "mom": "pch", "chg": "chg"}.get(kind, "lin")
    r = httpx.get("https://api.stlouisfed.org/fred/series/observations", params={"series_id": series, "api_key": config.FRED_API_KEY, "file_type": "json", "units": units,
                                                                                 "sort_order": "desc", "limit": limit}, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    pts = []
    for o in r.json().get("observations") or []:
        try:
            v = float(o["value"])
        except (KeyError, ValueError):
            continue
        pts.append((_period_key(o["date"], freq), v / 1000 if kind == "level_k" else v))
    return sorted(pts)


def fred_release_dates(series: str, start: date, end: date) -> Tuple[Optional[int], str, List[str]]:
    """그 시리즈의 발표(release) 일정 — 앞으로의 날짜도(include_release_dates_with_no_data). 날짜만(시각 없음)."""
    if not config.FRED_API_KEY:
        raise NoSource("FRED 키 없음")
    base = {"api_key": config.FRED_API_KEY, "file_type": "json"}
    rel = httpx.get("https://api.stlouisfed.org/fred/series/release", params={**base, "series_id": series}, headers=UA, timeout=TIMEOUT)
    rel.raise_for_status()
    rs = rel.json().get("releases") or []
    if not rs:
        return None, "", []
    rid, name = int(rs[0]["id"]), str(rs[0].get("name") or "")
    r = httpx.get("https://api.stlouisfed.org/fred/release/dates", params={**base, "release_id": rid, "include_release_dates_with_no_data": "true", "sort_order": "desc", "limit": 60},
                  headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    dates = [x["date"] for x in r.json().get("release_dates") or [] if start.isoformat() <= x.get("date", "") <= end.isoformat()]
    return rid, name, sorted(set(dates))


# ── 연준 성명(RSS) ──
FED_RSS = "https://www.federalreserve.gov/feeds/press_monetary.xml"
_FOMC_RX = re.compile(r"decided to (maintain|raise|lower) the target range for the federal funds rate (?:by [\d/\-]+ percentage points? )?(?:at|to) ([\d/\-]+) to ([\d/\-]+) percent", re.I)
DECISION_KO = {"maintain": "동결", "raise": "인상", "lower": "인하"}


def _frac(s: str) -> float:
    """'3-3/4' → 3.75, '4' → 4, '1/4' → 0.25"""
    whole, _, frac = s.partition("-")
    if "/" in whole and not frac:
        whole, frac = "0", whole
    n, _, d = frac.partition("/")
    return float(whole or 0) + (float(n) / float(d) if frac and d else 0.0)


def fomc_statements(limit: int = 6) -> List[Dict[str, Any]]:
    """최근 FOMC 성명 → [{date(UTC 날짜), lower, upper, decision, url}] 최신 먼저."""
    r = httpx.get(FED_RSS, headers=UA, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    out = []
    for it in re.findall(r"<item>(.*?)</item>", r.text, re.S):
        title = re.search(r"<title>(.*?)</title>", it, re.S)
        if not title or "FOMC statement" not in title.group(1):
            continue
        lm = re.search(r"<link>(.*?)</link>", it, re.S)
        link = re.sub(r"<!\[CDATA\[|\]\]>", "", lm.group(1)).strip() if lm else ""
        pub = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
        when = parsedate_to_datetime(re.sub(r"<!\[CDATA\[|\]\]>", "", pub.group(1)).strip()) if pub else None
        out.append({"date": when.date().isoformat() if when else "", "url": link})
        if len(out) >= limit:
            break
    for s in out[:2]:  # 원문은 최근 두 건만 읽는다(이번 결정·직전)
        s.update(fomc_read(s["url"]))
    return out


def fomc_read(url: str) -> Dict[str, Any]:
    t = httpx.get(url, headers=UA, timeout=TIMEOUT, follow_redirects=True).text
    txt = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
    m = _FOMC_RX.search(txt)
    if not m:
        return {}
    return {"decision": m.group(1).lower(), "lower": _frac(m.group(2)), "upper": _frac(m.group(3)), "sentence": m.group(0)}


# ── 한국은행 ECOS ──
_ecos_codes: Dict[Tuple[str, str, str], Tuple[str, str]] = {}


def ecos_fetch(spec: Tuple[str, str, str]) -> Points:
    from app.connectors import ecos

    if not ecos.ready():
        raise NoSource("ECOS 키 없음")
    table_word, item_name, cycle = spec
    if spec not in _ecos_codes:
        tables = ecos.search_tables(table_word)
        found = None
        for t in tables[:5]:
            items = [i for i in ecos.list_items(t["statCode"]) if i["cycle"] == cycle and (i["itemName"] == item_name or item_name in i["itemName"])]
            if items:
                found = (t["statCode"], items[0]["itemCode"])
                break
        if not found:
            raise NoSource(f"ECOS 에서 '{table_word} · {item_name}' 을 찾지 못함")
        _ecos_codes[spec] = found
    code, item = _ecos_codes[spec]
    today = date.today()
    start, end = ((today - timedelta(days=800)).strftime("%Y%m"), today.strftime("%Y%m")) if cycle == "M" else ((today - timedelta(days=400)).strftime("%Y%m%d"), today.strftime("%Y%m%d"))
    rows = ecos._call("StatisticSearch", code, cycle, start, end, item, start=1, end=1000)
    pts = []
    for r in rows:
        t, v = str(r.get("TIME") or ""), r.get("DATA_VALUE")
        try:
            val = float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            continue
        pts.append((f"{t[:4]}-{t[4:6]}" if cycle == "M" else f"{t[:4]}-{t[4:6]}-{t[6:8]}", val))
    return sorted(pts)


def available(ind: Indicator) -> List[str]:
    """지금 쓸 수 있는 감지 소스(앞에서부터 시도) — 키 상태 반영."""
    out = []
    if ind.fomc:
        out.append("fomc")
    if ind.bls:
        out.append("bls")
    if ind.fred and config.FRED_API_KEY:
        out.append("fred")
    if ind.ecos and config.ECOS_API_KEY:
        out.append("ecos")
    return out


def values(ind: Indicator, via: str, bls_cache: Optional[Dict[str, Points]] = None) -> Points:
    """그 소스에서 지표 값 [(기간 키, 값)] — 회의는 [(결정일, 상단)]."""
    if via == "bls":
        raw = (bls_cache if bls_cache is not None else bls_fetch([ind.bls or ""])).get(ind.bls or "") or []
        return transform(raw, ind.transform)
    if via == "fred":
        return fred_fetch(ind.fred or "", ind.transform, ind.freq if ind.freq in ("M", "Q") else "D")
    if via == "ecos":
        return transform(ecos_fetch(ind.ecos), ind.transform)  # type: ignore[arg-type]
    if via == "fomc":
        return sorted((s["date"], s["upper"]) for s in fomc_statements() if s.get("upper") is not None)
    return []
