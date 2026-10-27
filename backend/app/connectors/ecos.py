"""한국은행 ECOS 연결 — 경제 통계(금리·환율·물가 등) 시계열을 스냅샷 문서로 가져온다.

통계표 코드를 코드에 박지 않는다 — ECOS 의 목록 서비스로 그때그때 찾는다(코드가 바뀌어도 그대로 동작).
 - 통계표 찾기: StatisticTableList(전체 목록)를 data/connectors/ecos_tables.json 에 7일 캐시 → 이름으로 거른다(검색 가능 표만).
 - 항목 고르기: StatisticItemList/{통계표} → 항목 코드·이름·주기·수록 기간·단위.
 - 값: StatisticSearch/{통계표}/{주기}/{시작}/{끝}/{항목} → "기간 | 값" 표(최대 120개 시점). 기간 키는 주기대로 정확히
   (월 2024M01 · 분기 2024Q1 · 반기 2024S1 · 일 2024-01-15 · 연 2024) — make_snapshot 의 period_map 으로 넘긴다.
응답 모양: {서비스명: {list_total_count, row: [...]}} · 오류 {RESULT: {CODE, MESSAGE}} (INFO-200 = 자료 없음).
인증키는 backend/.env 의 ECOS_API_KEY(ecos.bok.or.kr 무료 발급). 없으면 ConnectorError(NO_ECOS_KEY) — 화면은 안내만.
"""
from __future__ import annotations

import json
import re
import time
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app import config
from app.connectors.base import ConnectorError, make_snapshot, register, snapshot_id

API = "https://ecos.bok.or.kr/api"
CACHE = config.CONNECTOR_DIR / "ecos_tables.json"
CACHE_DAYS = 7
MAX_POINTS = 120
CYCLE_KO = {"A": "연", "S": "반기", "Q": "분기", "M": "월", "SM": "반월", "D": "일"}


def ready() -> bool:
    return bool(config.ECOS_API_KEY)


register("ecos", "한국은행 ECOS", "기준금리·환율·물가 등 한국은행 경제 통계 시계열을 가져옵니다.", ready, hint="backend/.env 에 ECOS_API_KEY(ecos.bok.or.kr 무료 발급)를 넣어야 합니다.")


def _require_key() -> str:
    if not config.ECOS_API_KEY:
        raise ConnectorError("NO_ECOS_KEY", "ECOS 인증키가 없습니다. backend/.env 에 ECOS_API_KEY 를 넣고 백엔드를 다시 실행해 주세요(ecos.bok.or.kr 에서 무료 발급).")
    return config.ECOS_API_KEY


def _http_get(url: str, timeout: float = 60.0) -> httpx.Response:
    """외부 호출 한 곳(테스트에서 바꿔 끼운다). 인증키가 경로에 들어가므로 이 URL 은 로그에 남기지 않는다."""
    return httpx.get(url, timeout=timeout)


def _call(service: str, *path: str, start: int = 1, end: int = 1000) -> List[Dict[str, Any]]:
    key = _require_key()
    url = "/".join([API, service, key, "json", "kr", str(start), str(end), *path])
    try:
        res = _http_get(url)
    except httpx.HTTPError as e:
        raise ConnectorError("ECOS_UNREACHABLE", f"ECOS 에 연결하지 못했습니다({type(e).__name__}).", 502) from e
    if res.status_code != 200:
        raise ConnectorError("ECOS_UNREACHABLE", f"ECOS 응답 오류(HTTP {res.status_code}).", 502)
    body = res.json() if res.content else {}
    if isinstance(body, dict) and body.get("RESULT"):
        code = str(body["RESULT"].get("CODE") or "")
        msg = str(body["RESULT"].get("MESSAGE") or "")
        if code == "INFO-200":
            raise ConnectorError("NO_DATA", "그 조건의 ECOS 자료가 없습니다. 주기·기간을 바꿔 보세요.", 404)
        if code in ("INFO-100", "ERROR-100"):
            raise ConnectorError("ECOS_KEY_INVALID", "ECOS 인증키가 올바르지 않습니다. backend/.env 의 ECOS_API_KEY 를 확인해 주세요.")
        raise ConnectorError("ECOS_ERROR", f"ECOS 오류({code}): {msg}")
    return list(((body or {}).get(service) or {}).get("row") or [])


# ── 통계표·항목 찾기 ────────────────────────────────────────────────────

def _load_tables() -> List[Dict[str, str]]:
    if CACHE.exists():
        try:
            data = json.loads(CACHE.read_text(encoding="utf-8"))
            if time.time() - float(data.get("fetchedAt", 0)) < CACHE_DAYS * 86400 and data.get("list"):
                return data["list"]
        except (ValueError, OSError):
            pass
    rows = _call("StatisticTableList", start=1, end=10000)
    out = [{"statCode": str(r.get("STAT_CODE") or ""), "statName": str(r.get("STAT_NAME") or "").strip(), "cycle": str(r.get("CYCLE") or ""), "searchable": str(r.get("SRCH_YN") or "Y") == "Y"} for r in rows]
    out = [t for t in out if t["statCode"] and t["statName"]]
    CACHE.write_text(json.dumps({"fetchedAt": time.time(), "list": out}, ensure_ascii=False), encoding="utf-8")
    return out


def search_tables(q: str, limit: int = 15) -> List[Dict[str, Any]]:
    words = [w for w in re.split(r"\s+", (q or "").strip()) if w]
    if not words:
        return []
    hits = [t for t in _load_tables() if t["searchable"] and all(w in t["statName"] for w in words)]
    hits.sort(key=lambda t: (len(t["statName"]), t["statCode"]))
    return hits[:limit]


def list_items(stat_code: str) -> List[Dict[str, Any]]:
    if not re.fullmatch(r"[0-9A-Z]{3,12}", stat_code or ""):
        raise ConnectorError("ECOS_BAD_PARAM", "통계표 코드가 올바르지 않습니다.", 400)
    rows = _call("StatisticItemList", stat_code)
    return [
        {
            "itemCode": str(r.get("ITEM_CODE") or ""),
            "itemName": str(r.get("ITEM_NAME") or "").strip(),
            "group": str(r.get("GRP_NAME") or "").strip(),
            "cycle": str(r.get("CYCLE") or ""),
            "start": str(r.get("START_TIME") or ""),
            "end": str(r.get("END_TIME") or ""),
            "count": int(r.get("DATA_CNT") or 0),
            "unit": str(r.get("UNIT_NAME") or "").strip(),
        }
        for r in rows
        if r.get("ITEM_CODE")
    ]


# ── 시계열 ──────────────────────────────────────────────────────────────

def _period(cycle: str, t: str) -> Tuple[str, str]:
    """ECOS TIME → (표에 쓸 이름, 원장 기간 키)."""
    t = str(t).strip()
    if cycle == "M" and re.fullmatch(r"\d{6}", t):
        return f"{t[:4]}-{t[4:]}", f"{t[:4]}M{t[4:]}"
    if cycle == "D" and re.fullmatch(r"\d{8}", t):
        return f"{t[:4]}-{t[4:6]}-{t[6:]}", f"{t[:4]}-{t[4:6]}-{t[6:]}"
    if cycle == "SM" and re.fullmatch(r"\d{6}S[12]", t):
        return f"{t[:4]}-{t[4:6]} {'상순' if t[-1] == '1' else '하순'}", t
    m = re.fullmatch(r"(\d{4})(Q[1-4]|S[12])", t)
    if m:
        return f"{m.group(1)} {m.group(2)}", t
    return t, t


def _value(v: Any) -> Optional[str]:
    s = str(v if v is not None else "").replace(",", "").strip()
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return None
    ip, _, frac = s.lstrip("-").partition(".")
    return ("-" if s.startswith("-") else "") + f"{int(ip):,}" + (f".{frac}" if frac else "")


def fetch_series(stat_code: str, stat_name: str, item_code: str, item_name: str, cycle: str, start: str, end: str) -> Dict[str, Any]:
    """→ make_snapshot 결과 {"id", "figures"} + {"title"}. 시점은 최근 MAX_POINTS 개까지."""
    if cycle not in CYCLE_KO:
        raise ConnectorError("ECOS_BAD_PARAM", "주기는 연·반기·분기·월·반월·일(A·S·Q·M·SM·D) 가운데 하나입니다.", 400)
    if not (re.fullmatch(r"[0-9A-Z]{3,12}", stat_code or "") and re.fullmatch(r"[0-9A-Za-z]{1,20}", item_code or "")):
        raise ConnectorError("ECOS_BAD_PARAM", "통계표·항목 코드가 올바르지 않습니다.", 400)
    if not (re.fullmatch(r"[0-9QS]{4,8}", start or "") and re.fullmatch(r"[0-9QS]{4,8}", end or "")):
        raise ConnectorError("ECOS_BAD_PARAM", "기간은 주기에 맞게 넣어 주세요(예: 월 202401, 분기 2024Q1, 연 2024, 일 20240115).", 400)
    rows = _call("StatisticSearch", stat_code, cycle, start, end, item_code, start=1, end=10000)
    points = sorted(((str(r.get("TIME") or ""), _value(r.get("DATA_VALUE")), str(r.get("UNIT_NAME") or "").strip()) for r in rows), key=lambda x: x[0])
    points = [p for p in points if p[0] and p[1] is not None][-MAX_POINTS:]
    if not points:
        raise ConnectorError("NO_DATA", "그 조건의 ECOS 값이 없습니다.", 404)
    unit = points[-1][2]
    table_unit = "%" if "%" in unit else unit  # '연%' 도 비율이다
    metric = item_name or stat_name
    rows_tbl = [["기간", metric]]
    period_map: Dict[str, str] = {}
    for t, v, _u in points:
        label, key = _period(cycle, t)
        rows_tbl.append([label, v or ""])
        period_map[label] = key
    from app.docs.extract import table_text

    heading = f"{stat_name} — {metric} ({CYCLE_KO[cycle]}, 단위: {unit or '없음'})"
    paras = [{"page": None, "text": table_text(rows_tbl), "kind": "table", "rows": rows_tbl, "heading": heading, "unit": table_unit, "sheet": CYCLE_KO[cycle]}]
    today = date.today().isoformat()
    first, last = rows_tbl[1][0], rows_tbl[-1][0]
    title = f"{metric} {first}~{last} ({CYCLE_KO[cycle]}, ECOS)"
    doc_id = snapshot_id("ecos", stat_code, item_code, cycle, start, end, today)
    snap = make_snapshot(
        doc_id,
        file_name=f"ECOS_{stat_code}_{item_code}_{cycle}_{start}_{end}.json",
        file_type="ECOS",
        paras=paras,
        raw={"statCode": stat_code, "itemCode": item_code, "cycle": cycle, "rows": rows[-MAX_POINTS:]},
        card={
            "title": title,
            "docType": "경제 통계(ECOS)",
            "date": today,
            "issuer": "한국은행 경제통계시스템(ECOS)",
            "company": "",
            "oneLine": f"{stat_name} · {metric} {len(points)}개 시점 — 단위: {unit or '없음'}, {today} 조회",
        },
        snapshot={
            "connector": "ecos",
            "title": f"ECOS {stat_name}",
            "params": {"statCode": stat_code, "statName": stat_name, "itemCode": item_code, "itemName": item_name, "cycle": cycle, "start": start, "end": end},
            "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "url": "https://ecos.bok.or.kr/",
        },
        figure_source="ecos",
        period_map=period_map,
    )
    return {**snap, "title": title}


__all__ = ["fetch_series", "list_items", "ready", "search_tables"]
