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
from typing import Any, Dict, List, Optional, Tuple
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


# ── 기업개황·최근 공시 목록 ──────────────────────────────────────────────

CORP_CLS_KO = {"Y": "유가증권시장", "K": "코스닥", "N": "코넥스", "E": "기타"}


def fetch_overview(corp_code: str, corp_name: str, days: int = 365) -> Dict[str, Any]:
    """기업개황(company.json) + 최근 공시 목록(list.json) → 스냅샷 문서 하나. 공시마다 원문 링크(접수번호)를 칸에 둔다.
    리포트의 '주요 공시·이벤트'가 이 표를 인용한다(공시 본문은 가져오지 않는다 — 제목·날짜·제출인만)."""
    from datetime import timedelta

    from app.docs.extract import table_text

    key = _require_key()
    try:
        co = _http_get(f"{API}/company.json", {"crtfc_key": key, "corp_code": corp_code}).json()
    except httpx.HTTPError as e:
        raise ConnectorError("DART_UNREACHABLE", f"DART 에 연결하지 못했습니다: {e}", 502) from e
    if str(co.get("status") or "") != "000":
        code, msg = _STATUS.get(str(co.get("status")), ("DART_ERROR", f"DART 오류({co.get('status')}): {co.get('message') or ''}"))
        raise ConnectorError(code, msg, 404 if code == "NO_DATA" else 409)
    end = date.today()
    bgn = end - timedelta(days=max(30, min(days, 1095)))
    rows: List[Dict[str, Any]] = []
    for page in range(1, 6):
        j = _http_get(f"{API}/list.json", {"crtfc_key": key, "corp_code": corp_code, "bgn_de": bgn.strftime("%Y%m%d"), "end_de": end.strftime("%Y%m%d"),
                                           "page_no": str(page), "page_count": "100"}).json()
        st = str(j.get("status") or "")
        if st == "013":  # 조회된 자료 없음
            break
        if st != "000":
            code, msg = _STATUS.get(st, ("DART_ERROR", f"DART 오류({st}): {j.get('message') or ''}"))
            raise ConnectorError(code, msg, 409)
        rows += list(j.get("list") or [])
        if page >= int(j.get("total_page") or 1):
            break
        time.sleep(0.2)

    def d8(s: Any) -> str:
        s = str(s or "")
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else s

    profile = [["항목", "내용"],
               ["회사명", str(co.get("corp_name") or corp_name)], ["영문명", str(co.get("corp_name_eng") or "")],
               ["종목코드", str(co.get("stock_code") or "")], ["시장", CORP_CLS_KO.get(str(co.get("corp_cls") or ""), str(co.get("corp_cls") or ""))],
               ["대표자", str(co.get("ceo_nm") or "")], ["설립일", d8(co.get("est_dt"))], ["결산월", f"{co.get('acc_mt') or ''}월"],
               ["업종코드", str(co.get("induty_code") or "")], ["주소", str(co.get("adres") or "")], ["홈페이지", str(co.get("hm_url") or "")]]
    profile = [r for r in profile if r[1].strip(" 월")]
    disc = [["접수일", "공시명", "제출인", "접수번호", "원문"]] + [
        [d8(r.get("rcept_dt")), re.sub(r"\s+", " ", str(r.get("report_nm") or "")).strip(), str(r.get("flr_nm") or ""), str(r.get("rcept_no") or ""),
         f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={r.get('rcept_no')}"] for r in rows]
    paras: List[Dict[str, Any]] = [
        {"page": None, "kind": "table", "rows": profile, "heading": f"{corp_name} 기업개황(DART)", "unit": None, "sheet": "기업개황"},
        {"page": None, "kind": "table", "rows": disc, "heading": f"{corp_name} 최근 공시 목록 ({bgn.isoformat()}~{end.isoformat()}, {len(rows)}건)", "unit": None, "sheet": "공시 목록"},
    ]
    for p in paras:
        p["text"] = table_text(p["rows"])
    today = end.isoformat()
    title = f"{corp_name} 기업개황·최근 공시 목록({today} 기준)"
    snap = make_snapshot(
        snapshot_id("dart", corp_code, "overview", today),
        file_name=f"DART_{corp_name}_기업개황_공시목록_{today}.json",
        file_type="DART",
        paras=paras,
        raw={"company": co, "list": rows},
        card={"title": title, "docType": "공시 목록(DART)", "date": today, "issuer": "금융감독원 전자공시(DART)", "company": corp_name,
              "oneLine": f"DART OpenAPI 에서 {today}에 가져온 기업개황과 최근 {len(rows)}건 공시(제목·접수일·제출인·원문 링크)"},
        snapshot={"connector": "dart", "title": "DART 기업개황·공시 목록", "params": {"corpCode": corp_code, "corpName": corp_name, "days": days},
                  "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "url": f"https://dart.fss.or.kr/dsab007/main.do?corpCode={corp_code}"},
        figure_source="dart",
    )
    return {**snap, "title": title, "disclosures": len(rows)}


# ── 정기보고서 본문(사업의 내용 등) ─────────────────────────────────────

# 기업분석 리포트가 쓰는 절만 — 회사 개요·연혁·주식 총수, 사업의 내용 전부, 경영진단(예측정보 주의 제외), 주주, 임직원 현황.
# 재무제표·주석(III)·감사(V)·이사회(VI)·계열사(IX)·대주주 거래(X)는 뺀다(재무제표는 fetch_financials 가 정확한 칸으로 가져온다).
BODY_PARTS = {"I": ("1", "2", "4"), "II": None, "IV": ("2", "3", "4", "5", "6"), "VII": None, "VIII": ("1",)}
BODY_PARA_CHARS = 1200
CAPTION_CHARS = 80  # 표 위 이 길이 이하 줄(최대 2줄)은 표 제목·단위로 본다
_ROMAN = re.compile(r"^\s*([IVX]+)\.\s")
_NUM = re.compile(r"^\s*(\d+)\.\s")
_UNIT = re.compile(r"단위\s*[:：]\s*([^\s,)]+)")


def _text_of(el: Any) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


_NUMERIC = re.compile(r"[-+(]?[\d,.]+%?\)?|-")


def _span(v: Any) -> int:
    return int(v) if str(v or "").isdigit() and int(v) > 0 else 1


def _table_rows(table: Any) -> List[List[str]]:
    """TABLE → 행 목록. 칸 합치기(ROWSPAN·COLSPAN)를 풀어 열을 맞춘다.
    머리 행(TH 만 있는 앞쪽 행)이 여러 줄이면 열마다 위→아래 글을 이어 한 줄로('소유주식수 및 지분율 기 말 지분율') — 합친 머리를 납작하게 펴면 열이 밀려
    '최대주주 지분율'을 다른 열 값으로 읽는다(2026-10-30 실측). 본문 칸의 합치기는 글(항목 이름)만 되풀이하고 숫자는 비운다(같은 값이 두 번 세지지 않게)."""
    grid: List[List[str]] = []
    heads: List[bool] = []
    carry: Dict[int, Tuple[str, int]] = {}  # 열 → (아래 행에 채울 글, 남은 행 수)
    for tr in table.iter("TR"):
        tds = [td for td in tr if td.tag in ("TD", "TH", "TE", "TU")]
        is_head = bool(tds) and (tr.getparent().tag == "THEAD" or all(td.tag == "TH" for td in tds))
        row: List[str] = []

        def fill_carry() -> None:
            while len(row) in carry:
                c = len(row)
                text, left = carry[c]
                row.append(text)
                if left <= 1:
                    del carry[c]
                else:
                    carry[c] = (text, left - 1)

        for td in tds:
            fill_carry()
            text = _text_of(td)
            rs = _span(td.get("ROWSPAN"))
            for k in range(_span(td.get("COLSPAN"))):
                c = len(row)
                row.append(text if k == 0 or is_head else "")
                if rs > 1:
                    keep = (k == 0 or is_head) and (is_head or not _NUMERIC.fullmatch(text))
                    carry[c] = (text if keep else "", rs - 1)
        fill_carry()
        grid.append(row)
        heads.append(is_head)
    n = 0
    while n < len(grid) and heads[n]:
        n += 1
    if n > 1:
        width = max(len(r) for r in grid[:n])
        merged = [" ".join(dict.fromkeys(grid[r][c] for r in range(n) if c < len(grid[r]) and grid[r][c])) for c in range(width)]
        grid = [merged] + grid[n:]
    return [r for r in grid if any(r)]


def _wanted(path: List[str]) -> bool:
    """heading 경로(['II. 사업의 내용', '2. 주요 제품 및 서비스']) 가 BODY_PARTS 에 드는가."""
    if not path:
        return False
    m = _ROMAN.match(path[0])
    if not m or m.group(1) not in BODY_PARTS:
        return False
    subs = BODY_PARTS[m.group(1)]
    if subs is None or len(path) < 2:
        return subs is None
    n = _NUM.match(path[1])
    return bool(n and n.group(1) in subs)


def _body_paras(xml: bytes, corp_name: str) -> List[Dict[str, Any]]:
    """heading = '회사 · 장 > 절' — 검색(제목+본문 임베딩)이 '○○ 주요 제품' 질의에서 다른 자료의 회사 이름 제목에 밀리지 않게."""
    from lxml import etree

    from app.docs.extract import table_text

    root = etree.fromstring(xml, parser=etree.XMLParser(recover=True, huge_tree=True))
    paras: List[Dict[str, Any]] = []
    buf: List[str] = []
    path: List[str] = []

    def head() -> str:
        return f"{corp_name} · {' > '.join(path)}"

    def flush() -> None:
        if buf and _wanted(path):
            paras.append({"page": None, "kind": "prose", "text": "\n".join(buf), "heading": head(), "heading_path": list(path)})
        buf.clear()

    def walk(el: Any, depth: int) -> None:
        for ch in el:
            tag = ch.tag if isinstance(ch.tag, str) else ""
            if tag.startswith("SECTION-"):
                flush()
                title = ch.find("TITLE")
                level = int(tag.split("-")[1])
                del path[level - 1:]
                path.append(_text_of(title) if title is not None else "")
                walk(ch, level)
                flush()
                del path[level - 1:]
            elif tag == "TITLE":
                continue
            elif tag == "P":
                t = _text_of(ch)
                if t:
                    if sum(len(x) for x in buf) + len(t) > BODY_PARA_CHARS:
                        flush()
                    buf.append(t)
            elif tag == "TABLE":
                if not _wanted(path):
                    continue
                rows = _table_rows(ch)
                if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                    # 표 바로 위 짧은 줄(표 제목 '가. 최대주주 … 현황'·'(단위 : 주, %)')은 표의 머리로 옮긴다 — 표 칸만으로는 무슨 표인지 검색이 모른다
                    cap: List[str] = []
                    while buf and len(buf[-1]) <= CAPTION_CHARS and len(cap) < 2:
                        cap.insert(0, buf.pop())
                    unit = next((m.group(1) for m in map(_UNIT.search, cap) if m), None)
                    flush()
                    title = " ".join(cap)
                    paras.append({"page": None, "kind": "table", "rows": rows, "text": table_text(rows), "heading": head() + (f" · {title}" if title else ""),
                                  "heading_path": list(path), "unit": unit, "sheet": path[-1][:30]})
                elif rows:  # 한 칸 표(상자 글) — 본문으로
                    buf.extend(" ".join(c for c in r if c) for r in rows)
            elif tag in ("TABLE-GROUP", "LIBRARY", "BODY", "COVER", "CORRECTION"):
                walk(ch, depth)

    walk(root, 0)
    flush()
    return paras


def _periodic_reports(key: str, corp_code: str, since: date) -> List[Dict[str, Any]]:
    j = _http_get(f"{API}/list.json", {"crtfc_key": key, "corp_code": corp_code, "bgn_de": since.strftime("%Y%m%d"), "end_de": date.today().strftime("%Y%m%d"),
                                       "pblntf_ty": "A", "page_count": "100"}).json()
    st = str(j.get("status") or "")
    if st == "013":
        return []
    if st != "000":
        code, msg = _STATUS.get(st, ("DART_ERROR", f"DART 오류({st}): {j.get('message') or ''}"))
        raise ConnectorError(code, msg, 409)
    return list(j.get("list") or [])


def fetch_business(corp_code: str, corp_name: str, year: Optional[int] = None, report: str = "annual") -> Dict[str, Any]:
    """정기보고서 본문(document.xml) → 회사 개요·연혁·주식 총수·사업의 내용·경영진단·주주·임직원 절만 스냅샷 문서로.
    year 를 비우면 가장 최근 그 종류 보고서. 문단은 원문 그대로(요약·번역 없음), 표는 칸 구조로."""
    key = _require_key()
    if report not in REPORTS:
        raise ConnectorError("DART_BAD_PARAM", "보고서는 사업보고서·반기·1분기·3분기 가운데 하나여야 합니다.", 400)
    ko = REPORTS[report]["ko"].replace("1분기", "분기").replace("3분기", "분기")
    month = {"annual": "12", "half": "06", "q1": "03", "q3": "09"}[report]
    since = date(year, 1, 1) if year else date(date.today().year - 2, 1, 1)  # Y년 사업보고서는 Y+1년 3월께 접수
    try:
        rows = _periodic_reports(key, corp_code, since)
    except httpx.HTTPError as e:
        raise ConnectorError("DART_UNREACHABLE", f"DART 에 연결하지 못했습니다: {e}", 502) from e
    # 정정 보고서([기재정정]) 도 같은 기간이면 최신 접수가 먼저 온다
    want = [r for r in rows if ko in str(r.get("report_nm") or "") and f".{month})" in str(r.get("report_nm") or "")
            and (year is None or f"({year}.{month})" in str(r.get("report_nm") or ""))]
    if not want:
        raise ConnectorError("NO_DATA", f"DART 에 {corp_name} {year or '최근'} {REPORTS[report]['ko']} 공시가 없습니다.", 404)
    rcept_no = str(want[0]["rcept_no"])
    report_nm = re.sub(r"\s+", " ", str(want[0].get("report_nm") or "")).strip()
    try:
        res = _http_get(f"{API}/document.xml", {"crtfc_key": key, "rcept_no": rcept_no}, timeout=120.0)
    except httpx.HTTPError as e:
        raise ConnectorError("DART_UNREACHABLE", f"DART 에 연결하지 못했습니다: {e}", 502) from e
    if res.status_code != 200 or not res.content.startswith(b"PK"):
        raise ConnectorError("DART_ERROR", f"DART 원문을 받지 못했습니다(HTTP {res.status_code}).", 502)
    z = zipfile.ZipFile(io.BytesIO(res.content))
    main = next((n for n in z.namelist() if n == f"{rcept_no}.xml"), None) or max(z.namelist(), key=lambda n: z.getinfo(n).file_size)
    paras = _body_paras(z.read(main), corp_name)
    if not paras:
        raise ConnectorError("NO_DATA", "DART 원문에서 사업의 내용 절을 찾지 못했습니다.", 404)
    today = date.today().isoformat()
    title = f"{corp_name} {report_nm} 본문(사업의 내용·주주 등)"
    # 본문 표의 기간 머리 '제26기' → 연도(사업보고서는 가장 큰 기수 = 보고서 연도) — 제품별 매출·연구개발비가 연도 칸으로 원장에 든다
    period_map: Dict[str, str] = {}
    fy = re.search(r"\((\d{4})\.\d{2}\)", report_nm)
    terms = sorted({int(m) for p in paras if p["kind"] == "table" for c in p["rows"][0] for m in re.findall(r"제\s*(\d+)\s*기", c)})
    if report == "annual" and fy and terms:
        for n in terms:
            for label in (f"제{n}기", f"제 {n} 기", f"제{n} 기"):
                period_map[label] = str(int(fy.group(1)) - (terms[-1] - n))
    snap = make_snapshot(
        snapshot_id("dart", corp_code, "body", rcept_no),
        file_name=f"DART_{corp_name}_{report_nm}_본문.json",
        file_type="DART",
        paras=paras,
        raw={"rceptNo": rcept_no, "reportName": report_nm, "sections": sorted({" > ".join(p["heading_path"][:2]) for p in paras})},
        card={"title": title, "docType": "공시 본문(DART)", "date": f"{rcept_no[:4]}-{rcept_no[4:6]}-{rcept_no[6:8]}", "issuer": "금융감독원 전자공시(DART)",
              "company": corp_name, "oneLine": f"{report_nm} 원문 중 회사의 개요·사업의 내용·경영진단·주주·임직원 절({len(paras)}개 문단·표, {today}에 가져옴)"},
        snapshot={"connector": "dart", "title": "DART 정기보고서 본문", "params": {"corpCode": corp_code, "corpName": corp_name, "year": year, "report": report},
                  "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rceptNo": rcept_no,
                  "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"},
        figure_source="dart_body",
        period_map=period_map or None,
    )
    return {**snap, "title": title, "paragraphs": len(paras)}
