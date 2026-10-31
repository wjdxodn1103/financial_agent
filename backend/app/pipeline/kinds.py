"""소스 종류마다 모으기 — 모은 것 하나 = 항목(key 로 중복을 막는다) = 보통 문서 하나.

 - series: 시장·거시 시계열 갱신(공급자 사슬) + 그날의 시장 데이터 문서(표 — 작성기가 인용하고 원문 창으로 열린다)
 - rss:    공식 보도자료·성명 피드 → 링크 본문 글(원문 URL·발행일)
 - edgar:  등록 회사의 새 공시(10-Q·10-K·8-K) → 재무제표 엑셀(Financial_Report.xlsx)·본문 글. SEC_USER_AGENT 가 없으면 고정 파일('가상')
 - folder: 서버 수집 폴더(사내 자료공유시스템 연계 자리)에 들어온 파일 → 적재 + 문서 종류·발행처·기준일 분류
as_of(YYYY-MM-DD)가 있으면 그날까지 나온 것만 모은다(날짜 지정 재현).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import httpx

from app import config
from app.ids import now_iso
from app.pipeline.docs import add_file, add_text, html_text

log = logging.getLogger(__name__)
Item = Dict[str, Any]
ROOT = Path(__file__).resolve().parents[3]  # kic_report_agent/
FIXTURE_DIR = ROOT / "demo" / "edgar_fixture"
RSS_MAX = 8  # 피드 하나에서 한 번에 새로 모을 항목 수
EDGAR_MAX = 6  # 회사 하나에서 한 번에 새로 모을 공시 수
FILE_EXT = (".pdf", ".docx", ".xlsx", ".xlsm", ".txt", ".md")

DEFAULT_FEEDS = [
    {"url": "https://www.federalreserve.gov/feeds/press_all.xml", "issuer": "미 연준(Federal Reserve)"},
    {"url": "https://www.ecb.europa.eu/rss/press.html", "issuer": "유럽중앙은행(ECB)"},
]
SEC_FEED = {"url": "https://www.sec.gov/news/pressreleases.rss", "issuer": "미 증권거래위원회(SEC)"}
FORMS = ("10-Q", "10-K", "8-K", "20-F", "6-K")


def default_feeds() -> List[Dict[str, str]]:
    return [*DEFAULT_FEEDS, *([SEC_FEED] if config.SEC_USER_AGENT else [])]


def _http(url: str, sec: bool = False) -> httpx.Response:
    headers = {"User-Agent": config.SEC_USER_AGENT if sec else "Mozilla/5.0 (DCF collector)"}
    last: Optional[Exception] = None
    for _ in range(2):
        try:
            r = httpx.get(url, headers=headers, timeout=25, follow_redirects=True)
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.8)
    raise RuntimeError(str(last)[:200])


def _target(src: Dict[str, Any]) -> Dict[str, Any]:
    return {"scope": src["scope"], "workspace_id": src.get("workspaceId") or "", "folder_id": (src.get("target") or {}).get("folderId"), "added_by": src.get("createdBy") or ""}


def _cut(as_of: Optional[str]) -> Optional[date]:
    return date.fromisoformat(as_of) if as_of else None


# ── series ──

def _market_doc(as_of: Optional[str], src: Dict[str, Any]) -> Optional[str]:
    """그날의 시장·거시 데이터 표 문서(같은 날 다시 모으면 덮어쓴다)."""
    from app.connectors.base import make_snapshot, snapshot_id
    from app.market.catalog import GROUPS
    from app.market.service import board
    from app.pipeline.docs import attach

    b = board(as_of)
    day = b["asOf"]
    paras: List[Dict[str, Any]] = []
    for g in b["groups"]:
        rows = [["항목", "단위", "기준일", "값", "전일 대비", "1주 대비", "1달 대비", "출처"]]
        for c in g["series"]:
            if c.get("value") is None:
                continue
            ch = c.get("changes") or {}
            rows.append([c["name"], c["unit"], c["date"], c["display"], (ch.get("d1") or {}).get("display", ""), (ch.get("w1") or {}).get("display", ""), (ch.get("m1") or {}).get("display", ""), c["sourceLabel"]])
        if len(rows) > 1:
            paras.append({"kind": "table", "rows": rows, "heading": f"{g['group']} ({day})", "text": "\n".join(" | ".join(map(str, r)) for r in rows)})
    if not paras:
        return None
    did = snapshot_id("market", day)
    make_snapshot(did, file_name=f"시장·거시 데이터 {day}.json", file_type="json", paras=paras, raw=b,
                  card={"title": f"시장·거시 데이터 {day}", "docType": "경제·산업 자료", "date": day, "issuer": "DCF 수집(FRED·미 재무부·ECB·뉴욕 연은·데모 가상)", "oneLine": "금리·환율·원자재·주가지수·신용·거시 지표 — 전일·1주·1달 대비"},
                  snapshot={"connector": "market", "title": f"시장·거시 데이터 {day}", "params": {"asOf": day}, "fetchedAt": now_iso(), "publishedAt": day, "sourceId": src["id"]}, figure_source="market")
    t = _target(src)
    attach(did, t["scope"], t["workspace_id"], t["folder_id"], t["added_by"])
    return did


def collect_series(src: Dict[str, Any], as_of: Optional[str], seen: Set[str]) -> List[Item]:
    from app.market.service import refresh_all

    ids = (src.get("params") or {}).get("seriesIds") or None
    r = refresh_all(ids, as_of)
    day = as_of or date.today().isoformat()
    did = _market_doc(as_of, src)
    if src["scope"] == "company":
        try:  # 오늘의 시장 요약(사실표 + [F#] 문장, 숫자 검증) — 전사 시장 대시보드
            from app.market.summary import make_brief

            asyncio.run(make_brief(as_of))
        except Exception:  # noqa: BLE001
            log.exception("market brief failed")
    note = f"시리즈 {r['ok']}/{r['series']} 갱신" + (f" · 대체 소스 {r['fallback']}" if r["fallback"] else "") + (f" · 실패 {r['failed']}" if r["failed"] else "")
    items = [{"key": f"market:{day}", "title": f"시장·거시 데이터 {day}", "docId": did, "publishedAt": day, "status": "ok" if r["ok"] else "error",
              "error": None if r["ok"] else "모든 공급자 실패", "meta": {"note": note, "fallback": r["fallback"], "failed": r["failed"]}, "replace": True}]
    try:  # 경제 일정 문서(발표 일정 한국 시각·서머타임 등 시간대 규칙) — 아침 브리핑이 발표 시각을 이 문서로 쓰고 인용한다
        cal = _calendar_doc(as_of, src)
        if cal:
            items.append({"key": f"calendar:{day}", "title": f"경제 일정 {day}", "docId": cal, "publishedAt": day, "status": "ok", "error": None,
                          "meta": {"note": "발표 일정·시간대 규칙"}, "replace": True})
    except Exception:  # noqa: BLE001
        log.exception("calendar doc failed")
    return items


def _calendar_doc(as_of: Optional[str], src: Dict[str, Any]) -> Optional[str]:
    """그날의 경제 일정 표 문서(app/calendar/snapshot.py — 같은 날 다시 모으면 덮어쓴다)."""
    from app.calendar.snapshot import build
    from app.connectors.base import make_snapshot, snapshot_id
    from app.pipeline.docs import attach

    b = build(as_of)
    if b is None:
        return None
    day = b["day"]
    did = snapshot_id("calendar", day)
    make_snapshot(did, file_name=f"경제 일정 {day}.json", file_type="json", paras=b["paras"], raw=b["raw"],
                  card={"title": f"경제 일정 {day}", "docType": "경제·산업 자료", "date": day, "issuer": "DCF 수집(기관 공식 발표 일정표·FRED 발표일·IANA 시간대 규칙)",
                        "oneLine": "이번 주 주요 발표 일정(한국 시각·현지 시각)과 서머타임 등 시간대 변경"},
                  snapshot={"connector": "calendar", "title": f"경제 일정 {day}", "params": {"asOf": day}, "fetchedAt": now_iso(), "publishedAt": day, "sourceId": src["id"]},
                  figure_source="calendar")
    t = _target(src)
    attach(did, t["scope"], t["workspace_id"], t["folder_id"], t["added_by"])
    try:  # 카드·문단 벡터 — 아침 브리핑(07:00)이 이 문서를 찾으려면 바로 색인해 둔다
        from app.docs.ingest import index_card
        from app.docs.queue import schedule_embed

        index_card(did)
        schedule_embed(did)
    except Exception:  # noqa: BLE001
        log.debug("calendar doc index failed %s", did)
    return did


# ── rss ──

def _rss_items(xml_text: str) -> List[Dict[str, str]]:
    root = ET.fromstring(xml_text)
    out = []
    for it in root.iter():
        if it.tag.rsplit("}", 1)[-1] != "item":
            continue
        f = {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in it}
        if f.get("link"):
            out.append({"title": f.get("title", ""), "link": f["link"], "pubDate": f.get("pubDate") or f.get("date", ""), "description": f.get("description", "")})
    return out


def _pubdate(s: str) -> Optional[str]:
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except Exception:  # noqa: BLE001
        try:
            return datetime.fromisoformat(s[:10]).date().isoformat()
        except Exception:  # noqa: BLE001
            return None


def collect_rss(src: Dict[str, Any], as_of: Optional[str], seen: Set[str]) -> List[Item]:
    feeds = (src.get("params") or {}).get("feeds") or default_feeds()
    cut = _cut(as_of)
    t = _target(src)
    out: List[Item] = []
    for fd in feeds:
        url = fd["url"] if isinstance(fd, dict) else str(fd)
        issuer = fd.get("issuer", "") if isinstance(fd, dict) else ""
        try:
            items = _rss_items(_http(url, sec="sec.gov" in url).text)
        except Exception as e:  # noqa: BLE001
            out.append({"key": f"feed:{url}:{date.today().isoformat()}", "title": f"피드 읽기 실패 — {url}", "url": url, "status": "error", "error": str(e)[:200]})
            continue
        n = 0
        for it in items:
            key = it["link"]
            pub = _pubdate(it["pubDate"])
            if key in seen or (cut and pub and date.fromisoformat(pub) > cut):
                continue
            if n >= RSS_MAX:
                break
            n += 1
            try:
                body = html_text(_http(it["link"], sec="sec.gov" in it["link"]).text)
                if len(body) < 200:
                    body = html_text(it.get("description") or "") or body
                text = f"# {it['title']}\n\n발행: {pub or it['pubDate']} · {issuer}\n원문: {it['link']}\n\n{body}"
                did = add_text(text, f"{issuer[:12]}_{pub or ''}_{it['title'][:40]}", card={"title": it["title"][:200], "docType": "뉴스·보도자료", "date": pub or "", "issuer": issuer, "oneLine": ""},
                               snapshot={"connector": "rss", "url": it["link"], "feed": url, "publishedAt": pub, "sourceId": src["id"]}, **t)
                out.append({"key": key, "title": it["title"][:200], "url": it["link"], "publishedAt": pub, "docId": did, "status": "ok"})
            except Exception as e:  # noqa: BLE001
                out.append({"key": key, "title": it["title"][:200], "url": it["link"], "publishedAt": pub, "status": "error", "error": str(e)[:200]})
    return out


# ── edgar ──

def edgar_mode() -> str:
    return "live" if config.SEC_USER_AGENT else "fixture"


def fixture_companies() -> List[Dict[str, Any]]:
    out = []
    for d in sorted(FIXTURE_DIR.glob("*/submissions.json")):
        sub = json.loads(d.read_text(encoding="utf-8"))
        out.append({"cik": int(sub["cik"]), "ticker": (sub.get("tickers") or [""])[0], "name": sub["name"], "virtual": True})
    return out


def _fixture_sub(cik: int) -> Optional[Dict[str, Any]]:
    for d in FIXTURE_DIR.glob("*/submissions.json"):
        sub = json.loads(d.read_text(encoding="utf-8"))
        if int(sub["cik"]) == int(cik):
            sub["_dir"] = str(d.parent)
            return sub
    return None


def _submissions(cik: int, live: bool) -> Optional[Dict[str, Any]]:
    if live:
        return _http(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", sec=True).json()
    return _fixture_sub(cik)


def collect_edgar(src: Dict[str, Any], as_of: Optional[str], seen: Set[str]) -> List[Item]:
    p = src.get("params") or {}
    forms = tuple(p.get("forms") or ("10-Q", "10-K", "8-K"))
    companies = p.get("companies") or fixture_companies()
    cut = _cut(as_of)
    t = _target(src)
    out: List[Item] = []
    for co in companies:
        cik = int(co.get("cik") or 0)
        name = co.get("name") or str(cik)
        # 회사마다 — 데모(가상) 회사는 SEC_USER_AGENT 가 있어도 늘 고정 파일, 실제 회사는 SEC(연락처가 있을 때)
        live = edgar_mode() == "live" and not co.get("virtual") and _fixture_sub(cik) is None
        try:
            sub = _submissions(cik, live)
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]
            if live and "403" in err:  # SEC 는 연락처를 받아들이지 않으면 403 — 무료 메일 도메인 일부를 막는다
                err = "SEC 가 SEC_USER_AGENT 를 거절했습니다(403). '이름 연락처이메일' 형태로, 받아들여지는 이메일(회사 도메인 등)로 바꿔 주세요."
            out.append({"key": f"sub:{cik}:{date.today().isoformat()}", "title": f"{name} 공시 목록 실패", "status": "error", "error": err})
            continue
        if sub is None:
            out.append({"key": f"sub:{cik}", "title": f"{name} — SEC_USER_AGENT 가 없어 가져오지 못함(고정 파일에 없는 회사)", "status": "error", "error": "SEC_USER_AGENT 없음"})
            continue
        virtual = bool(sub.get("virtual"))
        rec = (sub.get("filings") or {}).get("recent") or {}
        n = 0
        for i, acc in enumerate(rec.get("accessionNumber") or []):
            form, filed, doc = rec["form"][i], rec["filingDate"][i], rec["primaryDocument"][i]
            if form not in forms or acc in seen or (cut and date.fromisoformat(filed) > cut):
                continue
            if n >= EDGAR_MAX:
                break
            n += 1
            acc_nd = acc.replace("-", "")
            base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nd}"
            title = f"{name} {form} ({filed})"
            card = {"title": title, "docType": "공시", "date": filed, "issuer": name, "company": name, "oneLine": f"{form} · 보고 기간 {rec.get('reportDate', [''])[i] if rec.get('reportDate') else ''}"}
            snap = {"connector": "edgar", "accession": acc, "form": form, "filed": filed, "cik": cik, "url": f"{base}/{doc}" if live else "", "publishedAt": filed, "virtual": virtual, "sourceId": src["id"]}
            try:
                if form in ("10-Q", "10-K", "20-F"):
                    if live:
                        r = _http(f"{base}/Financial_Report.xlsx", sec=True)
                        tmp = config.INBOX_DIR / "pipeline" / f"{acc_nd}_Financial_Report.xlsx"
                        tmp.parent.mkdir(parents=True, exist_ok=True)
                        tmp.write_bytes(r.content)
                        snap["url"] = f"{base}/Financial_Report.xlsx"
                        time.sleep(0.15)
                    else:
                        tmp = Path(sub["_dir"]) / doc
                    did = add_file(tmp, f"{name[:30]}_{form}_{filed}_Financial_Report.xlsx", card=card, snapshot=snap, **t)
                else:
                    if live:
                        text = html_text(_http(f"{base}/{doc}", sec=True).text)
                        time.sleep(0.15)
                    else:
                        text = (Path(sub["_dir"]) / doc).read_text(encoding="utf-8")
                    did = add_text(f"# {title}\n\n접수번호 {acc} · 접수일 {filed}\n\n{text}", f"{name[:30]}_{form}_{filed}", card=card, snapshot=snap, **t)
                out.append({"key": acc, "title": title, "url": snap["url"], "publishedAt": filed, "docId": did, "status": "ok", "meta": {"form": form, "cik": cik, "virtual": virtual}})
            except Exception as e:  # noqa: BLE001
                out.append({"key": acc, "title": title, "url": snap["url"], "publishedAt": filed, "status": "error", "error": str(e)[:200]})
    return out


# ── folder ──

def watch_dir(src: Dict[str, Any]) -> Path:
    custom = (src.get("params") or {}).get("path")
    return Path(custom) if custom else config.INBOX_DIR / "watch" / src["id"]


def collect_folder(src: Dict[str, Any], as_of: Optional[str], seen: Set[str]) -> List[Item]:
    from app.docs.card import enrich_card
    from app.docs.store import load_meta, save_meta
    from app.llm.client import ReportLlm, provider_ready

    d = watch_dir(src)
    d.mkdir(parents=True, exist_ok=True)
    t = _target(src)
    out: List[Item] = []
    for f in sorted(d.iterdir()):
        if not f.is_file() or f.suffix.lower() not in FILE_EXT:
            continue
        key = hashlib.sha1(f.read_bytes()).hexdigest()
        if key in seen:
            continue
        try:
            did = add_file(f, f.name, card=None, snapshot={"connector": "folder", "fileName": f.name, "folder": str(d), "sourceId": src["id"]}, **t)
            meta = load_meta(did) or {}
            if provider_ready() and not meta.get("enriched"):
                # 분류(문서 종류·발행처·기준일) — 카드 정리는 생각 끄고 한 번
                got = asyncio.run(enrich_card(ReportLlm(), meta.get("card") or {}, f.name, meta.get("frontText") or ""))
                if got:
                    meta["card"], meta["enriched"] = {**(meta.get("card") or {}), **got}, True
                    save_meta(did, meta)
            c = (load_meta(did) or {}).get("card") or {}
            out.append({"key": key, "title": c.get("title") or f.name, "publishedAt": c.get("date") or None, "docId": did, "status": "ok", "meta": {"fileName": f.name, "docType": c.get("docType")}})
        except Exception as e:  # noqa: BLE001
            out.append({"key": key, "title": f.name, "status": "error", "error": str(e)[:200]})
    return out


COLLECTORS: Dict[str, Callable[[Dict[str, Any], Optional[str], Set[str]], List[Item]]] = {
    "series": collect_series,
    "rss": collect_rss,
    "edgar": collect_edgar,
    "folder": collect_folder,
}
KIND_KO = {"series": "시장·거시 시계열", "rss": "공식 보도자료·성명", "edgar": "공시(SEC EDGAR)", "folder": "수집 폴더"}
