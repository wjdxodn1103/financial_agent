"""전일 증시 요약(아침 리포트) — 실제 시세·금리·경제 일정으로 자료 한 건을 만들고, 양식의 표·차트 자리를 그 자료의 칸으로 채운다.

 - prepare(workspace, as_of): 시세(Yahoo 일봉)·미 국채(시장 시계열)·국고채(한국은행 ECOS)·경제 일정을 새로 받고 '증시 요약 데이터 {날짜}' 자료를 만든다.
   표 칸마다 원장 수치가 생겨 리포트 표·차트의 숫자를 누르면 이 자료의 칸이 열린다. 시장 뉴스 제목도 받는다(리뷰 문장의 원인 근거).
 - fill_form(form, doc): 양식의 표·차트 자리(form["market"])를 그 자료로 채운다(LLM 0회).
 - write_section(...): 본문 = 표 자리 줄 + '글로벌 시장 리뷰' 글머리표. 리뷰만 모델이 쓰고, 문장 속 숫자가 사실표·기사 제목에 있을 때만 남긴다.
'전일' = 기준일 하루 전까지의 마지막 거래일(아침 7시 리포트 기준 — 밤사이 끝난 미국 장과 전날 한국·아시아 장).
업종 등락률은 S&P500 업종 지수가 아니라 업종 ETF(SPDR) 종가 기준이다(무료 일봉 출처 — 자료에 그렇게 적는다).
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlmodel import Session, select

from app.db import MarketEvent, engine
from app.docs.store import load_chunks, load_meta

log = logging.getLogger(__name__)
CONNECTOR = "market_daily"
KST = timezone(timedelta(hours=9))
EQUITY = [("S&P500", "^GSPC"), ("Dow", "^DJI"), ("Nasdaq", "^IXIC"), ("반도체 지수", "^SOX"), ("Eurostoxx 50", "^STOXX50E"),
          ("KOSPI", "^KS11"), ("KOSDAQ", "^KQ11"), ("상해종합", "000001.SS"), ("Nikkei 225", "^N225"), ("VIX", "^VIX")]
# (이름, 출처, 키, 변화 단위, 소수 자리)
MACRO = [("미국채 2년", "series", "us_2y", "bp", 2), ("미국채 10년", "series", "us_10y", "bp", 2), ("국고채 3년", "ecos", "010200000", "bp", 2), ("국고채 10년", "ecos", "010210000", "bp", 2),
         ("달러 인덱스", "yahoo", "DX-Y.NYB", "%", 1), ("원/달러", "yahoo", "KRW=X", "%", 1), ("위안/달러", "yahoo", "CNY=X", "%", 2), ("엔/달러", "yahoo", "JPY=X", "%", 1),
         ("WTI", "yahoo", "CL=F", "%", 1), ("금", "yahoo", "GC=F", "%", 1)]
SECTORS = [("에너지", "XLE"), ("유틸리티", "XLU"), ("필수소비재", "XLP"), ("IT", "XLK"), ("산업재", "XLI"), ("헬스케어", "XLV"), ("경기소비재", "XLY"), ("소재", "XLB"),
           ("금융", "XLF"), ("부동산", "XLRE"), ("커뮤니케이션", "XLC")]
HEADS = {
    "equity": ["지수", "종가", "등락률(%)", "기준일"],
    "macro": ["항목", "값", "변화", "변화 단위", "기준일"],
    "sector": ["업종", "등락률(%)", "ETF", "기준일"],
    "prev": ["시각(한국)", "지표", "발표치", "이전치"],
    "today": ["시각(한국)", "지표", "예측치", "이전치"],
}
TITLES = {"equity": "글로벌 주식", "macro": "채권/환율/원자재", "sector": "S&P500 업종별 등락률", "prev": "전일 주요 경제지표", "today": "오늘 주요 경제지표"}
NEWS_QUERIES = ["뉴욕증시 마감", "코스피 마감 시황"]
KANA = "[" + chr(0x3040) + "-" + chr(0x30FF) + "]"


def _cut(as_of: str) -> str:
    return (date.fromisoformat(as_of) - timedelta(days=1)).isoformat()


# ── 값 모으기 ───────────────────────────────────────────────────────────

def _yahoo(ticker: str, cut: str) -> Optional[Tuple[float, float, str]]:
    """→ (종가, 직전 거래일 종가, 기준일). 기준일이 너무 오래됐으면(휴장이 길어도 6일) None."""
    from app.market.prices import view

    bars = [b for b in view(ticker, 30)["bars"] if b["date"] <= cut]
    if len(bars) < 2 or bars[-1]["date"] < (date.fromisoformat(cut) - timedelta(days=6)).isoformat():
        return None
    return float(bars[-1]["close"]), float(bars[-2]["close"]), bars[-1]["date"]


def _series(sid: str, cut: str) -> Optional[Tuple[float, float, str]]:
    from app.market.service import points

    pts, _src = points(sid, as_of=cut)
    return (float(pts[-1][1]), float(pts[-2][1]), pts[-1][0]) if len(pts) >= 2 else None


def _ecos(item: str, cut: str) -> Optional[Tuple[float, float, str]]:
    from app.connectors import ecos

    end = date.fromisoformat(cut)
    try:
        rows = ecos._call("StatisticSearch", "817Y002", "D", (end - timedelta(days=12)).strftime("%Y%m%d"), end.strftime("%Y%m%d"), item, start=1, end=30)
    except Exception:  # noqa: BLE001 — 키 없음·점검 중이면 그 줄만 빈다
        log.exception("daily: ecos %s", item)
        return None
    vals = [(str(r.get("TIME")), float(r["DATA_VALUE"])) for r in rows if r.get("DATA_VALUE") not in (None, "")]
    vals.sort()
    if len(vals) < 2:
        return None
    t = vals[-1][0]
    return vals[-1][1], vals[-2][1], f"{t[:4]}-{t[4:6]}-{t[6:8]}"


def _events(as_of: str) -> Tuple[List[List[str]], List[List[str]], str]:
    """경제 일정 → (전일 발표 행, 오늘 예정 행, 전일 표 제목). 전일 발표가 없으면 최근 발표일(나흘 안)의 것을 날짜와 함께."""
    from app.calendar.service import _num

    day = date.fromisoformat(as_of)
    lo = datetime.combine(day - timedelta(days=5), datetime.min.time(), KST).astimezone(timezone.utc).replace(tzinfo=None)
    hi = datetime.combine(day + timedelta(days=1), datetime.min.time(), KST).astimezone(timezone.utc).replace(tzinfo=None)
    with Session(engine) as s:
        evs = list(s.exec(select(MarketEvent).where(MarketEvent.at >= lo, MarketEvent.at < hi, MarketEvent.category == "release").order_by(MarketEvent.at)))

    def kst(ev: MarketEvent) -> datetime:
        return ev.at.replace(tzinfo=timezone.utc).astimezone(KST)

    done = [e for e in evs if e.status == "released" and e.actual is not None and kst(e).date() < day]
    last_day = max((kst(e).date() for e in done), default=None)
    title = TITLES["prev"] if last_day == day - timedelta(days=1) else "최근 주요 경제지표"
    stamp = (lambda e: kst(e).strftime("%H:%M")) if last_day == day - timedelta(days=1) else (lambda e: kst(e).strftime("%m/%d %H:%M"))
    prev = [[stamp(e), e.title, _num(e.actual, e), _num(e.previous, e)] for e in done if kst(e).date() == last_day]
    today = [[kst(e).strftime("%H:%M"), e.title, _num(e.forecast, e) if e.forecast is not None else "–", _num(e.previous, e)] for e in evs if kst(e).date() == day]
    return prev, today, title


def collect(as_of: str) -> Dict[str, Any]:
    """그날 리포트에 쓸 값 전부 — 표 행(글자)과 사실(리뷰 문장용)."""
    cut = _cut(as_of)
    tables: Dict[str, List[List[str]]] = {k: [h] for k, h in HEADS.items()}
    facts: List[Dict[str, Any]] = []
    for name, ticker in EQUITY:
        q = _yahoo(ticker, cut)
        if q is None:
            continue
        pct = (q[0] / q[1] - 1) * 100
        tables["equity"].append([name, f"{q[0]:,.1f}", f"{pct:+.1f}", q[2]])
        facts.append({"table": "equity", "row": len(tables["equity"]) - 1, "text": f"{name} {q[0]:,.1f} (전일 대비 {pct:+.1f}%)", "name": name, "pct": pct})
    for name, src, key, unit, dec in MACRO:
        q = _yahoo(key, cut) if src == "yahoo" else _series(key, cut) if src == "series" else _ecos(key, cut)
        if q is None:
            continue
        ch = (q[0] - q[1]) * 100 if unit == "bp" else (q[0] / q[1] - 1) * 100
        tables["macro"].append([name, f"{q[0]:,.{dec}f}", f"{ch:+.1f}", unit, q[2]])
        facts.append({"table": "macro", "row": len(tables["macro"]) - 1, "text": f"{name} {q[0]:,.{dec}f} (전일 대비 {ch:+.1f}{unit})", "name": name, "pct": ch})
    sect = []
    for name, ticker in SECTORS:
        q = _yahoo(ticker, cut)
        if q is not None:
            sect.append((name, (q[0] / q[1] - 1) * 100, ticker, q[2]))
    for name, pct, ticker, day in sorted(sect, key=lambda x: -x[1]):
        tables["sector"].append([name, f"{pct:+.1f}", ticker, day])
        facts.append({"table": "sector", "row": len(tables["sector"]) - 1, "text": f"S&P500 {name} 업종 {pct:+.1f}%", "name": name, "pct": pct})
    prev, today, prev_title = _events(as_of)
    tables["prev"] += prev
    tables["today"] += today
    for k, rows in (("prev", prev), ("today", today)):
        for i, r in enumerate(rows):
            facts.append({"table": k, "row": i + 1, "text": f"{'발표' if k == 'prev' else '오늘 예정'} {r[1]}: {'발표치' if k == 'prev' else '예측치'} {r[2]}, 이전치 {r[3]} ({r[0]})", "name": r[1], "pct": None})
    return {"asOf": as_of, "cut": cut, "tables": tables, "facts": facts, "prevTitle": prev_title}


# ── 자료 만들기 ─────────────────────────────────────────────────────────

def refresh(as_of: str) -> None:
    """바깥 값 새로 받기 — 실패해도 있는 값으로 간다."""
    from app.market import prices

    tickers = [t for _n, t in EQUITY] + [k for _n, s, k, _u, _d in MACRO if s == "yahoo"] + [t for _n, t in SECTORS]
    for i in range(0, len(tickers), prices.TICKERS_MAX):
        try:
            prices.load(tickers[i:i + prices.TICKERS_MAX], 30)
        except Exception:  # noqa: BLE001
            log.exception("daily: prices")
    try:
        from app.market.service import refresh_all

        refresh_all(["us_2y", "us_10y"], None)
    except Exception:  # noqa: BLE001
        log.exception("daily: series")
    try:
        from app.calendar.service import fill_values

        fill_values()
    except Exception:  # noqa: BLE001
        log.exception("daily: calendar")


def build_doc(workspace_id: str, as_of: str, added_by: str = "") -> Optional[str]:
    """'증시 요약 데이터 {날짜}' 자료(같은 날 다시 만들면 덮어쓴다) → 문서 id."""
    from app.connectors.base import make_snapshot, snapshot_id
    from app.docs.extract import table_text
    from app.pipeline.docs import attach

    data = collect(as_of)
    paras = []
    for k in ("equity", "macro", "sector", "prev", "today"):
        rows = data["tables"][k]
        if len(rows) < 2:
            continue
        title = data["prevTitle"] if k == "prev" else TITLES[k]
        paras.append({"page": None, "kind": "table", "rows": rows, "text": table_text(rows), "heading": f"{title} ({as_of} 아침 기준, 전일 = {data['cut']}까지)", "unit": None, "sheet": TITLES[k]})
    if not paras:
        return None
    did = snapshot_id(CONNECTOR, workspace_id, as_of)
    make_snapshot(did, file_name=f"증시 요약 데이터 {as_of}.json", file_type="json", paras=paras, raw=data,
                  card={"title": f"증시 요약 데이터 {as_of}", "docType": "경제·산업 자료", "date": as_of, "issuer": "AssociateLM 수집(Yahoo Finance·미 재무부·한국은행 ECOS·경제 일정)",
                        "oneLine": f"전일({data['cut']}) 종가 기준 지수·금리·환율·원자재·업종(ETF) 등락률과 경제지표 발표·일정"},
                  snapshot={"connector": CONNECTOR, "title": f"증시 요약 데이터 {as_of}", "params": {"asOf": as_of}, "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "publishedAt": as_of},
                  figure_source="market")
    attach(did, "workspace", workspace_id, None, added_by)
    try:
        from app.docs.queue import schedule_embed

        schedule_embed(did)
    except Exception:  # noqa: BLE001
        pass
    return did


def prepare(workspace_id: str, as_of: Optional[str], added_by: str = "") -> Optional[str]:
    """루틴이 쓰기 전에 부른다(동기 — 스레드에서). 시세·금리·일정·시장 뉴스 제목을 받고 자료를 만든다."""
    from app.connectors import news
    from app.dashboards.peer import workspace_docs

    day = as_of or datetime.now(KST).date().isoformat()
    if not as_of:  # 날짜를 지정해 다시 만드는 실행은 지금 값을 새로 받지 않는다(그날까지의 값으로)
        refresh(day)
        for q in NEWS_QUERIES:
            try:
                news.collect(workspace_id, q, topic="시장 뉴스", days=2, limit=4, have=workspace_docs(workspace_id), added_by=added_by)
            except Exception:  # noqa: BLE001
                log.exception("daily: news %s", q)
    return build_doc(workspace_id, day, added_by)


# ── 양식 자리 채우기 ────────────────────────────────────────────────────

def _data_doc(doc_ids: Sequence[str], as_of: Optional[str]) -> Optional[str]:
    mine = [d for d in doc_ids if ((load_meta(d) or {}).get("snapshot") or {}).get("connector") == CONNECTOR]
    if as_of:
        mine = [d for d in mine if str((load_meta(d) or {})["snapshot"]["params"].get("asOf")) <= as_of] or mine
    return max(mine, key=lambda d: str((load_meta(d) or {})["snapshot"]["params"].get("asOf"))) if mine else None


def _table(did: str, kind: str) -> Tuple[str, List[List[str]]]:
    """자료의 그 표 → (청크 id, 행들). 머리 행으로 찾는다."""
    for c in load_chunks(did):
        rows = c.get("rows") or []
        if rows and [str(x) for x in rows[0]] == HEADS[kind]:
            return str(c.get("id")), [[str(x) for x in r] for r in rows]
    return "", []


def _num(did: str, chunk: str, r: int, c: int, text: str, title: str = "") -> Dict[str, Any]:
    return {"kind": "number", "text": text, "num": True, "docId": did, "chunk": chunk, "cell": [r, c], "fid": f"{did}:{chunk}.{r}.{c}", "title": title}


def _txt(text: str, bold: bool = False) -> Dict[str, Any]:
    return {"kind": "text", "text": text, "num": False, **({"bold": True} if bold else {})}


def fill_form(form: Dict[str, Any], doc: Dict[str, Any]) -> Dict[str, Any]:
    """양식의 시장 표·차트 자리 → 블록. 자료가 없으면 빈 자리(missing)."""
    kind = str((form.get("market") or {}).get("table") or "")
    as_of = (doc.get("origin") or {}).get("asOf") or (doc.get("setup") or {}).get("asOf") or None
    did = _data_doc(doc.get("documentIds") or [], as_of)
    chunk, rows = _table(did, kind) if did else ("", [])
    base = {"blockId": form.get("id"), "formId": form.get("id"), "title": form.get("title") or "", "caption": form.get("title") or "", "formName": form.get("title") or "",
            "position": form.get("position") or "main", "calcs": [], "sourceDocIds": [did] if did else [], "missing": len(rows) < 2,
            "sourceLine": "자료: " + (str(((load_meta(did) or {}).get("card") or {}).get("title") or "") if did else "자료 없음")}
    look = {"headerFill": "#EAF1FB", "headerText": "#1F2937", "lines": "horizontal", **dict(form.get("look") or {})}
    body = rows[1:]
    if kind == "sector":
        pts = [{"docId": did, "chunk": chunk, "cell": [i + 1, 1], "title": f"{r[0]}({r[2]}) {r[1]}% · {r[3]}"} for i, r in enumerate(body)]
        return {**base, "kind": "chart", "chartType": "bar", "horizontal": True, "categories": [r[0] for r in body], "unit": "%", "legend": "none", "number": "+0.0;-0.0",
                "series": [{"name": "등락률", "values": [float(r[1]) for r in body], "type": "bar"}], "points": [pts],
                "look": {"colors": [str((form.get("chart") or {}).get("color") or "#2E75B6")], "labels": True, "grid": False}, "sourceLine": base["sourceLine"] + " · 업종 ETF(SPDR) 종가 기준"}
    if kind in ("equity", "macro"):
        half = (len(body) + 1) // 2
        out = []
        for i in range(half):
            line: List[Dict[str, Any]] = []
            for j in (i, i + half):
                if j >= len(body):
                    line += [_txt(""), _txt(""), _txt("")]
                    continue
                r = body[j]
                unit = "%" if kind == "equity" else r[3]
                line += [_txt(r[0], bold=True), _num(did, chunk, j + 1, 1, r[1], f"{r[0]} · {r[-1]} 종가"), _num(did, chunk, j + 1, 2, f"{r[2]}{unit}", f"{r[0]} 전일 대비 · {r[-1]}")]
            out.append(line)
        head = ["", "종가" if kind == "equity" else "값", "등락", "", "종가" if kind == "equity" else "값", "등락"]
        return {**base, "kind": "table", "unit": "pt" if kind == "equity" else "%, pt, 달러", "header": head, "rows": out, "look": look}
    cols = ["시각", "지표", "발표치" if kind == "prev" else "예측치", "이전치"]
    title = base["title"]
    if kind == "prev" and body and "/" in body[0][0]:
        title = "최근 주요 경제지표"
    out = [[_txt(r[0]), _txt(r[1]), _num(did, chunk, i + 1, 2, r[2]) if re.search(r"\d", r[2]) else _txt(r[2]), _num(did, chunk, i + 1, 3, r[3]) if re.search(r"\d", r[3]) else _txt(r[3])] for i, r in enumerate(body)]
    return {**base, "title": title, "caption": title, "kind": "table", "unit": "", "header": cols, "rows": out, "look": look}


# ── 본문(시장 리뷰) ─────────────────────────────────────────────────────

REVIEW_PROMPT = """아래 사실과 기사 제목만으로 증권사 아침 시황 리포트의 '글로벌 시장 리뷰'를 글머리표 4~5개로 쓴다. JSON 하나로만 답한다(설명·코드 블록 없이).
{"bullets": [{"text": "한 문장", "f": [사실 번호], "n": [기사 번호]}]}
규칙:
- 증권사 데일리 문체: 주어를 세우고('뉴욕증시는', '미 국채 금리는', '업종별로는', '국제유가는', '코스피는') 명사형으로 끝낸다('~상승 마감', '~하락', '~기록', '~부각').
  '~다.'·'~습니다.'로 끝내지 않는다. 숫자만 늘어놓지 말고 한 문장으로 읽히게 쓴다. 한 줄 70자 안팎.
  꼴: "뉴욕증시는 ○○ 영향으로 3대 지수 모두 상승 마감(S&P500 +0.0%, 다우 +0.0%, 나스닥 +0.0%)" · "미 국채 10년물 금리는 0.0bp 오른 0.00% 기록, 달러 인덱스는 0.0% 하락"
      · "업종별로는 ○○(+0.0%)·○○(+0.0%)가 상승을 주도, ○○(+0.0%)는 상대적으로 부진" · "국제유가(WTI)는 0.0% 내린 00.0달러 기록" (0 자리에는 사실의 숫자를 그대로)
- 숫자는 사실에 적힌 그대로만 쓴다(반올림·환산하지 않는다). 사실에 없는 숫자는 쓰지 않는다.
- 움직임의 원인은 기사 제목에 근거가 있을 때만 쓴다(그 기사 번호를 n 에). 근거가 없으면 원인 없이 움직임만 쓴다.
- 순서: 미국 증시 → 금리·환율 → 업종 → 원자재 → 한국·아시아 증시(사실이 있는 것만). 오늘 예정된 지표가 있으면 마지막 줄에 한 번.
- 매수·매도 의견, 전망 단정은 쓰지 않는다."""


def _news(doc_ids: Sequence[str], as_of: str) -> List[Dict[str, Any]]:
    cut = _cut(as_of)
    out = []
    for d in doc_ids:
        m = load_meta(d) or {}
        card, snap = m.get("card") or {}, m.get("snapshot") or {}
        day = str(card.get("date") or "")
        # 밤사이 끝난 미국 장 기사는 오늘 날짜로도 나온다. 한국 장 마감 기사는 전일 것만(오늘 장 마감 기사가 섞이면 전일 움직임의 근거가 아니다)
        ok = (day == cut) if "코스피" in str(snap.get("query") or "") else (cut <= day <= as_of)
        if snap.get("connector") == "news" and snap.get("topic") == "시장 뉴스" and ok:
            ch = next(iter(load_chunks(d)), None)
            if ch:
                out.append({"docId": d, "chunk": str(ch.get("id")), "text": f"{card.get('title')} ({card.get('issuer')}, {card.get('date')})"})
    out.sort(key=lambda x: x["text"][-11:], reverse=True)
    return out[:8]


def _digits(s: str) -> List[str]:
    return re.findall(r"\d+(?:\.\d+)?", s.replace(",", ""))


def _fallback(facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """모델 글이 검증을 못 넘겼을 때 — 사실표로 코드가 쓴 줄(원인 서술 없음)."""
    by = {f["name"]: (i + 1, f) for i, f in enumerate(facts)}
    out = []

    def line(names: Sequence[str], lead: str) -> None:
        got = [(by[n][0], by[n][1]) for n in names if n in by]
        if got:
            parts = ", ".join(f"{f['name']} {f['pct']:+.1f}{'bp' if 'bp' in f['text'] else '%'}" for _i, f in got)
            out.append({"text": f"{lead} {parts} 기록", "f": [i for i, _f in got], "n": []})

    line(["S&P500", "Dow", "Nasdaq"], "뉴욕증시는")
    line(["미국채 10년", "달러 인덱스", "원/달러"], "금리·환율은")
    line(["WTI", "금"], "원자재는")
    line(["KOSPI", "KOSDAQ", "Nikkei 225"], "아시아 증시는")
    return out


async def write_section(llm: Any, doc: Dict[str, Any], step: str, as_of: Optional[str] = None) -> Dict[str, Any]:
    """→ agent.writer.write_section 과 같은 꼴 {content, checks, warnings, calcs, memo}."""
    from app.llm.base import ChatParams

    day = as_of or datetime.now(KST).date().isoformat()
    doc_ids = doc.get("documentIds") or []
    did = _data_doc(doc_ids, day)
    if not did:
        raise RuntimeError("증시 요약 데이터가 없습니다(시세를 받지 못했습니다).")
    from app.docs.store import doc_dir

    raw = json.loads((doc_dir(did) / "source.json").read_text(encoding="utf-8"))
    facts: List[Dict[str, Any]] = raw.get("facts") or []
    chunk_of = {k: _table(did, k)[0] for k in HEADS}
    news = _news(doc_ids, day)
    lines = "\n".join(f"F{i + 1} {f['text']}" for i, f in enumerate(facts))
    heads = "\n".join(f"N{i + 1} {n['text']}" for i, n in enumerate(news)) or "(없음)"
    content = f"{REVIEW_PROMPT}\n\n## 기준\n{day} 아침, 전일 = {raw.get('cut')} 종가\n\n## 사실\n{lines}\n\n## 기사 제목\n{heads}"
    bullets: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for _ in range(2):
        try:
            res = await llm.complete("writer", ChatParams(messages=[{"role": "user", "content": content}], temperature=0.2, max_tokens=4000, reasoning_effort="low", timeout_s=150))
        except Exception:  # noqa: BLE001
            log.exception("daily review failed")
            continue
        m = re.search(r"\{[\s\S]*\}", re.sub(r"^```(?:json)?|```$", "", (getattr(res, "content", "") or "").strip(), flags=re.M))
        try:
            items = (json.loads(m.group(0)) if m else {}).get("bullets") or []
        except ValueError:
            continue
        kept = []
        for it in items:
            if not isinstance(it, dict):
                continue
            text = re.sub(r"\s+", " ", re.sub(KANA, "", str(it.get("text") or ""))).strip().rstrip(".")  # 모델이 섞어 쓴 일본어 글자는 지운다('니ッ케이')
            fs = [n for n in it.get("f") or [] if isinstance(n, int) and 1 <= n <= len(facts)]
            ns = [n for n in it.get("n") or [] if isinstance(n, int) and 1 <= n <= len(news)]
            src = " ".join([facts[n - 1]["text"] for n in fs] + [news[n - 1]["text"] for n in ns]).replace(",", "")
            if not text or not fs or len(text) > 130 or re.search(r"[一-鿿]|(?:매수|매도)\s*(?:의견|추천|권고)", text) or any(x not in src for x in _digits(text)):
                continue
            kept.append({"text": text, "f": fs, "n": ns})
        if len(kept) > len(bullets):
            bullets = kept
        if len(bullets) >= 4:
            break
    if len(bullets) < 3:
        warnings.append("시장 리뷰: 모델 글이 숫자 확인을 넘지 못해 사실표로 쓴 줄로 대신함")
        bullets = _fallback(facts)
    us = {i + 1 for i, f in enumerate(facts) if f["name"] in ("S&P500", "Dow", "Nasdaq")}
    if us and not any(us & set(b["f"]) for b in bullets):  # 미국 증시 줄이 확인에서 빠졌으면 사실표 줄로 맨 앞에(가장 먼저 보는 줄)
        bullets = _fallback(facts)[:1] + bullets
    out_lines = []
    cites = 0
    for b in bullets[:6]:
        toks = list(dict.fromkeys([f"[@{did}#{chunk_of[facts[n - 1]['table']]}]" for n in b["f"] if chunk_of.get(facts[n - 1]["table"])] + [f"[@{news[n - 1]['docId']}#{news[n - 1]['chunk']}]" for n in b["n"]]))
        cites += len(toks)
        out_lines.append(f"- {b['text']}{''.join(toks)}")
    body = f"[표: {TITLES['equity']}]\n\n[표: {TITLES['macro']}]\n\n### 글로벌 시장 리뷰\n\n" + "\n".join(out_lines)
    return {"content": body, "checks": {"citations": cites, "sentences": len(out_lines), "unitSuspect": []}, "warnings": warnings, "calcs": [], "memo": "", "criteria": []}


__all__ = ["CONNECTOR", "build_doc", "collect", "fill_form", "prepare", "refresh", "write_section"]
