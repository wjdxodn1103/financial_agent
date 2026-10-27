"""SEC EDGAR 연결 — 미국 상장사 연간 재무(XBRL companyfacts)를 스냅샷 문서로 가져온다.

 - 회사 찾기: www.sec.gov/files/company_tickers.json(티커·CIK·회사명)을 data/connectors/edgar_tickers.json 에 7일 캐시.
 - 재무: data.sec.gov/api/xbrl/companyfacts/CIK##########.json 의 us-gaap 항목 중 주요 계정(매출·영업이익·순이익·자산·부채·자본·
   현금·영업현금흐름·EPS)을 연차 보고서(10-K·20-F·40-F) 기준으로 3개 회계연도 표로 만든다. 값은 SEC 원값(달러) 그대로.
   회계연도 이름은 기간 끝 날짜의 연도(예: 2024-09-28 에 끝난 해 = FY2024). 같은 기간이 여러 보고서에 있으면 가장 늦게 낸 것.
 - 인증키는 없지만 SEC 가 **연락처가 든 User-Agent** 를 요구한다(없으면 403) → backend/.env 의 SEC_USER_AGENT
   (예: "회사명 담당자 이메일"). 비어 있으면 ConnectorError(NO_SEC_UA) — 화면은 안내만. 초당 10건 이하로만 부른다(화면 조작 단위).
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from typing import Any, Dict, List, Tuple

import httpx

from app import config
from app.connectors.base import ConnectorError, make_snapshot, register, snapshot_id

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
CACHE = config.CONNECTOR_DIR / "edgar_tickers.json"
CACHE_DAYS = 7
ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A")
# (표에 쓸 이름, 후보 us-gaap 항목, 기간형=flow/시점형=instant, 단위)
ITEMS: List[Tuple[str, List[str], str, str]] = [
    ("매출액", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"], "flow", "USD"),
    ("영업이익", ["OperatingIncomeLoss"], "flow", "USD"),
    ("당기순이익", ["NetIncomeLoss", "ProfitLoss"], "flow", "USD"),
    ("영업활동현금흐름", ["NetCashProvidedByUsedInOperatingActivities"], "flow", "USD"),
    ("자산총계", ["Assets"], "instant", "USD"),
    ("부채총계", ["Liabilities"], "instant", "USD"),
    ("자본총계", ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], "instant", "USD"),
    ("현금및현금성자산", ["CashAndCashEquivalentsAtCarryingValue"], "instant", "USD"),
    ("주당순이익(기본)", ["EarningsPerShareBasic"], "flow", "USD/shares"),
]


def ready() -> bool:
    return bool(config.SEC_USER_AGENT)


register("edgar", "SEC EDGAR", "미국 상장사의 연간 재무(매출·이익·자산·현금흐름·EPS, XBRL)를 가져옵니다.", ready, hint="SEC 는 연락처가 든 User-Agent 를 요구합니다 — backend/.env 에 SEC_USER_AGENT(예: '회사명 담당자 이메일')를 넣어야 합니다.")


def _require_ua() -> str:
    if not config.SEC_USER_AGENT:
        raise ConnectorError("NO_SEC_UA", "SEC 는 연락처가 든 User-Agent 를 요구합니다. backend/.env 에 SEC_USER_AGENT(예: '회사명 담당자 이메일')를 넣고 백엔드를 다시 실행해 주세요.")
    return config.SEC_USER_AGENT


def _http_get(url: str, headers: Dict[str, str], timeout: float = 60.0) -> httpx.Response:
    """외부 호출 한 곳(테스트에서 바꿔 끼운다)."""
    return httpx.get(url, headers=headers, timeout=timeout)


def _get_json(url: str) -> Any:
    try:
        res = _http_get(url, {"User-Agent": _require_ua(), "Accept-Encoding": "gzip, deflate"})
    except httpx.HTTPError as e:
        raise ConnectorError("SEC_UNREACHABLE", f"SEC 에 연결하지 못했습니다: {e}", 502) from e
    if res.status_code == 403:
        raise ConnectorError("SEC_FORBIDDEN", "SEC 가 요청을 거절했습니다(403). SEC_USER_AGENT 에 회사명과 연락 이메일이 들어 있는지 확인해 주세요.")
    if res.status_code == 404:
        raise ConnectorError("NO_DATA", "SEC 에 그 회사의 XBRL 재무 데이터가 없습니다.", 404)
    if res.status_code != 200:
        raise ConnectorError("SEC_UNREACHABLE", f"SEC 응답 오류(HTTP {res.status_code}).", 502)
    return res.json()


# ── 회사 찾기 ───────────────────────────────────────────────────────────

def _load_tickers() -> List[Dict[str, Any]]:
    if CACHE.exists():
        try:
            data = json.loads(CACHE.read_text(encoding="utf-8"))
            if time.time() - float(data.get("fetchedAt", 0)) < CACHE_DAYS * 86400 and data.get("list"):
                return data["list"]
        except (ValueError, OSError):
            pass
    body = _get_json(TICKERS_URL)
    rows = body.values() if isinstance(body, dict) else body
    out = [{"cik": int(r["cik_str"]), "ticker": str(r.get("ticker") or ""), "name": str(r.get("title") or "")} for r in rows if r.get("cik_str")]
    CACHE.write_text(json.dumps({"fetchedAt": time.time(), "list": out}, ensure_ascii=False), encoding="utf-8")
    return out


def search_companies(q: str, limit: int = 10) -> List[Dict[str, Any]]:
    nq = (q or "").strip().lower()
    if not nq:
        return []
    scored = []
    for c in _load_tickers():
        t, n = c["ticker"].lower(), c["name"].lower()
        if t == nq:
            rank = 0
        elif n.startswith(nq):
            rank = 1
        elif nq in n or t.startswith(nq):
            rank = 2
        else:
            continue
        scored.append((rank, len(n), c))
    scored.sort(key=lambda x: x[:2])
    return [c for *_k, c in scored[:limit]]


# ── 재무 ────────────────────────────────────────────────────────────────

def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _annual(entries: List[Dict[str, Any]], kind: str) -> Dict[int, Dict[str, Any]]:
    """연차 보고서의 값만 — 기간형은 330~400일짜리, 시점형은 회계연도 말. → {끝 연도: 항목(가장 늦게 낸 것)}."""
    out: Dict[int, Dict[str, Any]] = {}
    for e in entries:
        if e.get("form") not in ANNUAL_FORMS or not e.get("end"):
            continue
        if kind == "flow":
            if not e.get("start") or not 330 <= _days(e["start"], e["end"]) <= 400:
                continue
        elif e.get("fp") not in (None, "FY"):
            continue
        y = int(e["end"][:4])
        if y not in out or str(e.get("filed") or "") > str(out[y].get("filed") or ""):
            out[y] = e
    return out


def _fmt(v: Any, unit: str) -> str:
    if unit == "USD/shares":
        return f"{float(v):,.2f}"
    return f"{int(round(float(v))):,}"


def fetch_financials(cik: int, name: str, year: int) -> Dict[str, Any]:
    """→ make_snapshot 결과 {"id", "figures"} + {"title"}. 회계연도 year 와 앞 2개년."""
    if not (2009 <= year <= date.today().year):
        raise ConnectorError("SEC_BAD_PARAM", f"회계연도는 2009~{date.today().year} 사이여야 합니다.", 400)
    body = _get_json(FACTS_URL.format(cik=int(cik)))
    gaap = ((body or {}).get("facts") or {}).get("us-gaap") or {}
    if not gaap:
        raise ConnectorError("NO_DATA", "이 회사는 us-gaap XBRL 재무가 없습니다(IFRS 로 내는 외국 회사일 수 있습니다).", 404)
    years = [year, year - 1, year - 2]
    tables: Dict[str, List[List[str]]] = {}
    used: Dict[str, str] = {}
    for label, concepts, kind, unit in ITEMS:
        for concept in concepts:
            entries = ((gaap.get(concept) or {}).get("units") or {}).get(unit) or []
            by_year = _annual(entries, kind)
            if any(y in by_year for y in years):
                row = [label, *[_fmt(by_year[y]["val"], unit) if y in by_year else "" for y in years]]
                tables.setdefault(unit, [["계정", *[f"FY{y}" for y in years]]]).append(row)
                used[label] = concept
                break
    if not tables:
        raise ConnectorError("NO_DATA", f"FY{year} 전후의 연차 재무 값이 SEC 데이터에 없습니다. 회계연도를 바꿔 보세요.", 404)
    from app.docs.extract import table_text

    entity = str(body.get("entityName") or name)
    paras: List[Dict[str, Any]] = []
    for unit, rows in tables.items():
        heading = f"{entity} 연간 재무(US GAAP, SEC XBRL)" if unit == "USD" else f"{entity} 주당 지표(US GAAP)"
        paras.append({"page": None, "text": table_text(rows), "kind": "table", "rows": rows, "heading": heading, "unit": "달러" if unit == "USD" else "달러/주", "sheet": "재무" if unit == "USD" else "주당 지표"})
    paras.append({"page": None, "kind": "text", "heading": "항목 대응(us-gaap)", "text": "; ".join(f"{k} = {v}" for k, v in used.items())})
    today = date.today().isoformat()
    title = f"{entity} FY{year} 연간 재무(SEC EDGAR)"
    doc_id = snapshot_id("edgar", str(int(cik)), str(year), today)
    snap = make_snapshot(
        doc_id,
        file_name=f"EDGAR_{re.sub(r'[^A-Za-z0-9]+', '_', entity)[:40]}_FY{year}.json",
        file_type="EDGAR",
        paras=paras,
        raw={"cik": int(cik), "entityName": entity, "used": used, "years": years},
        card={
            "title": title,
            "docType": "미국 공시 재무(SEC XBRL)",
            "date": today,
            "issuer": "미국 증권거래위원회(SEC EDGAR)",
            "company": entity,
            "oneLine": f"SEC companyfacts 에서 {today}에 가져온 FY{years[-1]}~FY{year} 연차(10-K 등) 값 — 단위: 달러",
        },
        snapshot={
            "connector": "edgar",
            "title": "SEC EDGAR companyfacts(XBRL)",
            "params": {"cik": int(cik), "name": name, "year": year},
            "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(cik):010d}&type=10-K",
        },
        figure_source="edgar",
        basis="연결",
    )
    return {**snap, "title": title}


__all__ = ["fetch_financials", "ready", "search_companies"]
