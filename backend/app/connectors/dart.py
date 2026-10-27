"""DART(금융감독원 전자공시) 연결 — 국내 상장·공시 회사의 재무제표를 스냅샷 문서로 가져온다.

 - 회사 찾기: corpCode.xml(전체 회사 고유번호, zip)을 받아 data/connectors/dart_corpcode.json 에 7일 캐시.
 - 재무제표: fnlttSinglAcntAll(단일회사 전체 재무제표) — 재무상태표·손익계산서·포괄손익계산서·현금흐름표를 표 칸 구조로.
   금액은 DART 원값(원 단위) 그대로 — 반올림하지 않아 원문 재확인이 정확하다.
 - 하루 요청 한도(약 20,000건)·분당 과다 요청 제한이 있어 화면 조작 단위로만 부른다(일괄 크롤링 없음).
인증키는 backend/.env 의 DART_API_KEY. 없으면 ConnectorError(NO_DART_KEY) — 화면은 안내만 한다.
"""
from __future__ import annotations

import io
import json
import re
import time
import zipfile
from datetime import date
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

import httpx

from app import config
from app.connectors.base import ConnectorError, make_snapshot, register, snapshot_id

API = "https://opendart.fss.or.kr/api"
CORP_CACHE = config.CONNECTOR_DIR / "dart_corpcode.json"
CORP_CACHE_DAYS = 7
REPORTS: Dict[str, Dict[str, str]] = {
    "annual": {"code": "11011", "ko": "사업보고서", "suffix": ""},
    "half": {"code": "11012", "ko": "반기보고서", "suffix": "H1"},
    "q1": {"code": "11013", "ko": "1분기보고서", "suffix": "Q1"},
    "q3": {"code": "11014", "ko": "3분기보고서", "suffix": "Q3"},
}
FS_KO = {"CFS": "연결", "OFS": "별도"}
STATEMENTS = [("BS", "재무상태표"), ("IS", "손익계산서"), ("CIS", "포괄손익계산서"), ("CF", "현금흐름표")]
_STATUS = {
    "010": ("DART_KEY_INVALID", "DART 인증키가 등록되지 않았습니다. backend/.env 의 DART_API_KEY 를 확인해 주세요."),
    "011": ("DART_KEY_INVALID", "DART 인증키를 쓸 수 없는 상태입니다(일시 중지)."),
    "012": ("DART_KEY_INVALID", "이 서버의 IP 로는 DART 에 접근할 수 없습니다."),
    "013": ("NO_DATA", "그 조건의 재무제표가 DART 에 없습니다. 연도·보고서를 바꾸거나, 연결 재무제표가 없는 회사면 별도로 바꿔 보세요."),
    "020": ("DART_LIMIT", "DART 요청 한도를 넘었습니다. 내일 다시 시도해 주세요."),
    "100": ("DART_BAD_PARAM", "DART 요청 값이 올바르지 않습니다."),
    "800": ("DART_MAINTENANCE", "DART 가 점검 중입니다. 잠시 뒤 다시 시도해 주세요."),
}


def ready() -> bool:
    return bool(config.DART_API_KEY)


register("dart", "DART 전자공시", "국내 상장·공시 회사의 재무제표(재무상태표·손익·현금흐름)를 가져옵니다.", ready, hint="backend/.env 에 DART_API_KEY(opendart.fss.or.kr 무료 발급)를 넣어야 합니다.")


def _require_key() -> str:
    if not config.DART_API_KEY:
        raise ConnectorError("NO_DART_KEY", "DART 인증키가 없습니다. backend/.env 에 DART_API_KEY 를 넣고 백엔드를 다시 실행해 주세요(opendart.fss.or.kr 에서 무료 발급).")
    return config.DART_API_KEY


def _http_get(url: str, params: Dict[str, str], timeout: float = 60.0) -> httpx.Response:
    """외부 호출 한 곳(테스트에서 바꿔 끼운다)."""
    return httpx.get(url, params=params, timeout=timeout)


# ── 회사 찾기 ───────────────────────────────────────────────────────────

def _norm_name(s: str) -> str:
    return re.sub(r"\s|\(주\)|㈜|주식회사|\(株\)", "", s or "").lower()


def _load_corps() -> List[Dict[str, str]]:
    if CORP_CACHE.exists():
        try:
            data = json.loads(CORP_CACHE.read_text(encoding="utf-8"))
            if time.time() - float(data.get("fetchedAt", 0)) < CORP_CACHE_DAYS * 86400 and data.get("list"):
                return data["list"]
        except (ValueError, OSError):
            pass
    key = _require_key()
    res = _http_get(f"{API}/corpCode.xml", {"crtfc_key": key}, timeout=120.0)
    if res.status_code != 200:
        raise ConnectorError("DART_UNREACHABLE", f"DART 회사 목록을 받지 못했습니다(HTTP {res.status_code}).", 502)
    try:
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            xml = z.read(z.namelist()[0])
    except zipfile.BadZipFile:
        # 키 오류 등은 zip 이 아니라 상태 XML 로 온다
        m = re.search(rb"<status>(\d+)</status>", res.content or b"")
        code = m.group(1).decode() if m else "900"
        c, msg = _STATUS.get(code, ("DART_ERROR", f"DART 오류({code})"))
        raise ConnectorError(c, msg)
    corps: List[Dict[str, str]] = []
    for el in ElementTree.fromstring(xml).iter("list"):
        get = lambda tag: (el.findtext(tag) or "").strip()  # noqa: E731
        corps.append({"corpCode": get("corp_code"), "corpName": get("corp_name"), "stockCode": get("stock_code"), "engName": get("corp_eng_name")})
    CORP_CACHE.write_text(json.dumps({"fetchedAt": time.time(), "list": corps}, ensure_ascii=False), encoding="utf-8")
    return corps


def search_companies(q: str, limit: int = 10) -> List[Dict[str, Any]]:
    nq = _norm_name(q)
    if not nq:
        return []
    scored = []
    for c in _load_corps():
        n = _norm_name(c["corpName"])
        e = (c.get("engName") or "").lower().replace(" ", "")
        if n == nq or e == nq:
            rank = 0
        elif n.startswith(nq):
            rank = 1
        elif nq in n or (e and nq in e):
            rank = 2
        else:
            continue
        scored.append((rank, 0 if c.get("stockCode") else 1, len(n), c))
    scored.sort(key=lambda x: x[:3])
    return [{**c, "listed": bool(c.get("stockCode"))} for *_k, c in scored[:limit]]


# ── 재무제표 ────────────────────────────────────────────────────────────

def _amount(s: Any) -> Optional[str]:
    t = str(s if s is not None else "").replace(",", "").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", t):
        return None
    neg = t.startswith("-")
    ip = t.lstrip("-")
    frac = ""
    if "." in ip:
        ip, frac = ip.split(".", 1)
        frac = "." + frac
    return ("-" if neg else "") + f"{int(ip):,}" + frac


def _columns(report: str, year: int, sj: str) -> List[Dict[str, str]]:
    """표의 기간 열 — (머리글, 값 필드 우선순위, 기간 키)."""
    if report == "annual":
        return [
            {"label": str(year), "fields": "thstrm_amount", "key": str(year)},
            {"label": str(year - 1), "fields": "frmtrm_amount", "key": str(year - 1)},
            {"label": str(year - 2), "fields": "bfefrmtrm_amount", "key": str(year - 2)},
        ]
    suf = REPORTS[report]["suffix"]
    ko = {"H1": "상반기", "Q1": "1분기", "Q3": "3분기"}[suf]
    if sj == "BS":
        return [{"label": f"{year} {ko}말", "fields": "thstrm_amount", "key": f"{year}{suf}말"}, {"label": f"{year - 1}말", "fields": "frmtrm_amount", "key": f"{year - 1}"}]
    if sj == "CF" or suf == "Q1":
        return [{"label": f"{year} {ko} 누적", "fields": "thstrm_amount", "key": f"{year}{suf}YTD"}, {"label": f"{year - 1} {ko} 누적", "fields": "frmtrm_amount", "key": f"{year - 1}{suf}YTD"}]
    return [
        {"label": f"{year} {ko} 누적", "fields": "thstrm_add_amount,thstrm_amount", "key": f"{year}{suf}YTD"},
        {"label": f"{year - 1} {ko} 누적", "fields": "frmtrm_add_amount,frmtrm_q_amount", "key": f"{year - 1}{suf}YTD"},
    ]


def fetch_financials(corp_code: str, corp_name: str, year: int, report: str = "annual", fs: str = "CFS") -> Dict[str, Any]:
    """→ make_snapshot 결과 {"id", "figures"} + {"title"}. 같은 날 같은 조건은 같은 스냅샷(덮어씀)."""
    key = _require_key()
    if report not in REPORTS:
        raise ConnectorError("DART_BAD_PARAM", "보고서는 사업보고서·반기·1분기·3분기 가운데 하나여야 합니다.", 400)
    if fs not in FS_KO:
        raise ConnectorError("DART_BAD_PARAM", "연결(CFS) 또는 별도(OFS)를 골라 주세요.", 400)
    if not (2015 <= year <= date.today().year):
        raise ConnectorError("DART_BAD_PARAM", f"사업연도는 2015~{date.today().year} 사이여야 합니다.", 400)
    params = {"crtfc_key": key, "corp_code": corp_code, "bsns_year": str(year), "reprt_code": REPORTS[report]["code"], "fs_div": fs}
    try:
        res = _http_get(f"{API}/fnlttSinglAcntAll.json", params)
    except httpx.HTTPError as e:
        raise ConnectorError("DART_UNREACHABLE", f"DART 에 연결하지 못했습니다: {e}", 502) from e
    if res.status_code != 200:
        raise ConnectorError("DART_UNREACHABLE", f"DART 응답 오류(HTTP {res.status_code}).", 502)
    body = res.json()
    status = str(body.get("status") or "")
    if status != "000":
        code, msg = _STATUS.get(status, ("DART_ERROR", f"DART 오류({status}): {body.get('message') or ''}"))
        raise ConnectorError(code, msg, 404 if code == "NO_DATA" else 409)
    rows_all: List[Dict[str, Any]] = list(body.get("list") or [])
    rept = REPORTS[report]
    fs_ko = FS_KO[fs]
    currency = next((r.get("currency") for r in rows_all if r.get("currency")), "KRW")
    unit = "원" if currency in ("KRW", "", None) else currency
    paras: List[Dict[str, Any]] = []
    period_map: Dict[str, str] = {}
    names = {}
    for sj, sj_ko in STATEMENTS:
        items = sorted((r for r in rows_all if r.get("sj_div") == sj), key=lambda r: int(r.get("ord") or 0))
        if not items:
            continue
        cols = _columns(report, year, sj)
        for c in cols:
            period_map[c["label"]] = c["key"]
        names[sj] = {c["label"]: next((items[0].get(f.replace("amount", "nm")) for f in c["fields"].split(",") if items[0].get(f.replace("amount", "nm"))), "") for c in cols}
        table = [["계정과목", *[c["label"] for c in cols]]]
        for r in items:
            cells = []
            for c in cols:
                v = next((_amount(r.get(f)) for f in c["fields"].split(",") if _amount(r.get(f)) is not None), None)
                cells.append(v or "")
            if any(cells):
                table.append([re.sub(r"\s+", " ", str(r.get("account_nm") or "")).strip(), *cells])
        if len(table) < 2:
            continue
        sj_name = items[0].get("sj_nm") or sj_ko
        paras.append({"page": None, "text": "", "kind": "table", "rows": table, "heading": f"{corp_name} {sj_name} ({fs_ko}, {rept['ko']})", "unit": unit, "sheet": sj_name})
    if not paras:
        raise ConnectorError("NO_DATA", "DART 응답에 재무제표 항목이 없습니다.", 404)
    from app.docs.extract import table_text

    for p in paras:
        p["text"] = table_text(p["rows"])
    rcept_no = str(next((r.get("rcept_no") for r in rows_all if r.get("rcept_no")), ""))
    today = date.today().isoformat()
    title = f"{corp_name} {year} {rept['ko']} 재무제표({fs_ko})"
    doc_id = snapshot_id("dart", corp_code, str(year), rept["code"], fs, today)
    snap = make_snapshot(
        doc_id,
        file_name=f"DART_{corp_name}_{year}_{rept['ko']}_{fs_ko}.json",
        file_type="DART",
        paras=paras,
        raw=body,
        card={
            "title": title,
            "docType": "공시 재무제표(DART)",
            "date": f"{rcept_no[:4]}-{rcept_no[4:6]}-{rcept_no[6:8]}" if len(rcept_no) >= 8 else "",
            "issuer": "금융감독원 전자공시(DART)",
            "company": corp_name,
            "oneLine": f"DART OpenAPI 에서 {today}에 가져온 {', '.join(p['sheet'] for p in paras)} — 단위: {unit}",
        },
        snapshot={
            "connector": "dart",
            "title": "DART 단일회사 전체 재무제표",
            "params": {"corpCode": corp_code, "corpName": corp_name, "year": year, "report": report, "fs": fs},
            "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "rceptNo": rcept_no,
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else "https://dart.fss.or.kr",
            "periodNames": names,
        },
        figure_source="dart",
        period_map=period_map,
        basis=fs_ko,
    )
    return {**snap, "title": title}
