"""피어 비교 대시보드(양식 'peer') — 상장사 2~3곳의 실적·밸류에이션·주가를 맞대어 본다. 숫자는 전부 코드가 계산한다(LLM 0회).

 - 재무: 워크스페이스에 붙은 DART 연결 재무제표 스냅샷의 원장(figures.json). 값마다 원문 칸(문서·청크·칸)을 달아 화면에서 누르면 원문이 열린다.
 - 최근 4개 분기 합계(TTM) = 직전 사업연도 − 직전 연도 같은 누적 + 올해 누적. 분기 값 = 누적 차이(research/form_charts 와 같은 규칙).
 - 주가·수익률: 사내 공용 일봉(price_bar). 시가총액 = 종류별 종가 × DART '주식의 총수 현황'의 발행주식 총수(우선주는 종목코드 끝자리 5 일봉이 있을 때).
 - PER = 보통주 종가 ÷ 최근 4분기 기본 EPS · PBR = 시가총액 ÷ 지배기업 소유주지분(최근 분기말) · ROE = 최근 4분기 순이익 ÷ 평균 자본총계.
 - 산업 전망 문장만 LLM 이 쓴다(outlook — 근거 번호가 실제로 있고 문장 속 숫자가 근거에 있을 때만 남긴다). 요청 때 한 번 만들어 구성(spec)에 둔다.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlmodel import Session

from app.db import Repo, engine
from app.docs.store import doc_dir, doc_label, load_chunks, load_meta

log = logging.getLogger(__name__)
METRICS = ("revenue", "op", "opm", "ni", "roe", "per", "pbr", "ret12")
NEWS, REPORT = "뉴스·보도자료", "애널리스트 리포트"
_YTD = {1: "Q1YTD", 2: "H1YTD", 3: "Q3YTD", 4: ""}
_END = {1: "Q1말", 2: "H1말", 3: "Q3말", 4: ""}
_NI = ["당기순이익", "반기순이익", "분기순이익"]
_TRILLION = 1e12
_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}


# ── 자료 ────────────────────────────────────────────────────────────────

def workspace_docs(workspace_id: str) -> List[str]:
    with Session(engine) as s:
        ws = Repo(s).workspace(workspace_id)
        return list(ws.document_ids or []) if ws else []


def _snap(doc_id: str) -> Dict[str, Any]:
    return (load_meta(doc_id) or {}).get("snapshot") or {}


def _card(doc_id: str) -> Dict[str, Any]:
    return (load_meta(doc_id) or {}).get("card") or {}


def fin_docs(doc_ids: Sequence[str], corp_code: str) -> List[str]:
    """그 회사의 DART 재무제표 스냅샷 — 연결이 있으면 연결만(없으면 별도)."""
    mine = [d for d in doc_ids if _snap(d).get("connector") == "dart" and (_snap(d).get("params") or {}).get("corpCode") == corp_code and (_snap(d).get("params") or {}).get("fs")]
    cfs = [d for d in mine if _snap(d)["params"]["fs"] == "CFS"]
    return cfs or mine


def shares_doc(doc_ids: Sequence[str], corp_code: str) -> Optional[str]:
    mine = [d for d in doc_ids if _snap(d).get("connector") == "dart" and (_snap(d).get("params") or {}).get("corpCode") == corp_code and (_snap(d).get("params") or {}).get("what") == "shares"]
    return max(mine, key=lambda d: str(_snap(d).get("asOf") or "")) if mine else None


def resolve_companies(names: Sequence[str]) -> List[Dict[str, Any]]:
    """회사 이름 → DART 고유번호·종목코드·Yahoo 표기. 상장사만(종목코드 없는 회사는 뺀다)."""
    from app.connectors import dart

    out: List[Dict[str, Any]] = []
    for raw in list(dict.fromkeys(str(n).strip() for n in names if str(n).strip()))[:3]:
        hit = next((c for c in dart.search_companies(raw, 5) if c.get("stockCode")), None)
        if hit is None:
            continue
        suffix = dart.corp_market(hit["corpCode"])
        if not suffix or any(o["corpCode"] == hit["corpCode"] for o in out):
            continue
        out.append({"name": hit["corpName"], "corpCode": hit["corpCode"], "stockCode": hit["stockCode"], "ticker": f"{hit['stockCode']}.{suffix}"})
    return out


def _pref_ticker(ticker: str) -> str:
    code, _, suffix = ticker.partition(".")
    return f"{code[:-1]}5.{suffix}" if len(code) == 6 and code.isdigit() and not code.endswith("5") else ""


def ensure_data(workspace_id: str, user_id: str, companies: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """없는 자료만 받는다 — 최근 3개 연도의 정기보고서 재무제표(연결), 주식의 총수, 일봉, 회사 뉴스 제목. 동기(스레드풀에서 부른다)."""
    from app.connectors import dart, news
    from app.connectors.base import ConnectorError
    from app.docs import queue as docs_queue
    from app.market import prices
    from app.services.document_service import attach_document

    made = {"financials": 0, "shares": 0, "prices": 0, "news": 0}
    year = date.today().year

    def attach(doc_id: str) -> None:
        with Session(engine) as s:
            attach_document(s, workspace_id, doc_id)
        docs_queue.schedule_embed(doc_id)

    for c in companies:
        docs = workspace_docs(workspace_id)
        have = {(p.get("year"), p.get("report")) for d in fin_docs(docs, c["corpCode"]) for p in [_snap(d).get("params") or {}]}
        for y in (year - 2, year - 1, year):
            for rep in ("q1", "half", "q3", "annual"):
                if (y, rep) in have or (y == year and rep == "annual"):
                    continue
                try:
                    attach(dart.fetch_financials(c["corpCode"], c["name"], y, rep, "CFS")["id"])
                    made["financials"] += 1
                except ConnectorError as e:
                    if e.code != "NO_DATA":
                        log.warning("peer: %s %s %s — %s", c["name"], y, rep, e.message)
        docs = workspace_docs(workspace_id)
        latest = max(((p.get("year") or 0, {"q1": 1, "half": 2, "q3": 3, "annual": 4}.get(p.get("report"), 0), p.get("report")) for d in fin_docs(docs, c["corpCode"])
                      for p in [_snap(d).get("params") or {}]), default=None)
        sd = shares_doc(docs, c["corpCode"])
        if latest and (sd is None or (_snap(sd).get("params") or {}).get("year") != latest[0] or (_snap(sd).get("params") or {}).get("report") != latest[2]):
            try:
                attach(dart.fetch_shares(c["corpCode"], c["name"], latest[0], latest[2])["id"])
                made["shares"] += 1
            except ConnectorError as e:
                log.warning("peer: %s 주식 수 — %s", c["name"], e.message)
        want = [t for t in (c["ticker"], _pref_ticker(c["ticker"])) if t]
        stale = [t for t in want if not (b := prices.view(t, 12)["bars"]) or b[-1]["date"] < (date.today() - timedelta(days=4)).isoformat()]
        if stale:
            made["prices"] += sum(1 for r in prices.load(stale, 800) if not r.get("error"))
        try:
            made["news"] += len(news.collect(workspace_id, f"{c['name']} 실적 전망", company=c["name"], topic="기업 뉴스", days=10, limit=5, have=docs, added_by=user_id))
        except Exception:  # noqa: BLE001 — 뉴스는 없어도 비교는 된다
            log.exception("peer: news failed %s", c["name"])
    try:  # 두 회사가 함께 나오는 기사 = 업황·산업 기사
        made["news"] += len(news.collect(workspace_id, " ".join(c["name"] for c in companies) + " 업황", topic="산업 뉴스", days=10, limit=6, have=workspace_docs(workspace_id), added_by=user_id))
    except Exception:  # noqa: BLE001
        log.exception("peer: industry news failed")
    return made


# ── 원장에서 값 꺼내기 ──────────────────────────────────────────────────

def _cite(f: Dict[str, Any]) -> Dict[str, Any]:
    return {"docId": f["doc"], "chunk": str(f["chunk"]), "cell": f.get("cell"),
            "label": f"{f.get('docLabel') or ''} · {f.get('metric') or ''} {f.get('period') or ''} · {f.get('display') or f.get('raw') or ''}"}


class _Co:
    """회사 하나의 원장·일봉."""

    def __init__(self, c: Dict[str, Any], doc_ids: Sequence[str], as_of: Optional[str]):
        from app.market.prices import view
        from app.research.form_rows import _Book

        self.c = c
        self.fin = fin_docs(doc_ids, c["corpCode"])
        self.book = _Book(self.fin, "", {}) if self.fin else None
        self.shares_id = shares_doc(doc_ids, c["corpCode"])
        cut = as_of or date.today().isoformat()
        self.bars = [b for b in view(c["ticker"], 800)["bars"] if b["date"] <= cut]
        pt = _pref_ticker(c["ticker"])
        self.pref_bars = [b for b in view(pt, 30)["bars"] if b["date"] <= cut] if pt else []
        self.last = self._last_quarter()

    def fig(self, keys: Sequence[str], pk: str) -> Optional[Dict[str, Any]]:
        if not self.book:
            return None
        if list(keys) == ["EPS"]:
            # 분기·반기보고서의 '기본주당반기순이익'·'기본주당분기순이익'은 지표 사전의 EPS 로 묶이지 않는다 — 계정 이름으로 찾는다
            hits = [f for f in self.book.scope.figs if re.match(r"\s*기본주당", str(f.get("metric") or "")) and f.get("periodKey") == pk]
            return max(hits, key=lambda f: self.book.scope.order.get(f["doc"], 0)) if hits else None
        return self.book.get(list(keys), pk)

    def _ytd(self, keys: Sequence[str], y: int, q: int) -> Optional[Dict[str, Any]]:
        return self.fig(keys, f"{y}{_YTD[q]}")

    def quarter(self, keys: Sequence[str], y: int, q: int) -> Tuple[Optional[float], List[Dict[str, Any]]]:
        cur = self._ytd(keys, y, q)
        if cur is None:
            return None, []
        if q == 1:
            return float(cur["abs"]), [cur]
        prev = self._ytd(keys, y, q - 1)
        return (None, []) if prev is None else (float(cur["abs"]) - float(prev["abs"]), [cur, prev])

    def _last_quarter(self) -> Optional[Tuple[int, int]]:
        year = date.today().year
        return next(((y, q) for y in range(year, year - 3, -1) for q in (4, 3, 2, 1) if self.quarter(["영업이익"], y, q)[0] is not None), None)

    def ttm(self, keys: Sequence[str]) -> Tuple[Optional[float], List[Dict[str, Any]]]:
        """최근 4개 분기 합계 = 직전 사업연도 − 직전 연도 같은 누적 + 올해 누적(4분기까지면 사업연도 그대로)."""
        if self.last is None:
            return None, []
        y, q = self.last
        if q == 4:
            f = self.fig(keys, str(y))
            return (float(f["abs"]), [f]) if f else (None, [])
        cur, base, old = self._ytd(keys, y, q), self.fig(keys, str(y - 1)), self._ytd(keys, y - 1, q)
        if cur is None or base is None or old is None:
            return None, []
        return float(base["abs"]) - float(old["abs"]) + float(cur["abs"]), [cur, base, old]

    def end_key(self, back_years: int = 0) -> str:
        y, q = self.last or (date.today().year - 1, 4)
        return f"{y - back_years}{_END[q]}"

    def owners_equity(self, pk: str) -> Optional[Dict[str, Any]]:
        """재무상태표의 지배기업 소유주지분(같은 이름이 손익계산서 '귀속' 줄에도 있어 시트로 가른다)."""
        if not self.book:
            return None
        hits = [f for f in self.book.scope.figs if f.get("sheet") == "재무상태표" and str(f.get("metricKey") or "").startswith("지배기업") and f.get("periodKey") == pk]
        return hits[-1] if hits else None

    def share_counts(self) -> Dict[str, Dict[str, Any]]:
        """{'보통주'|'우선주'|'합계': 발행주식 총수 칸}"""
        if not self.shares_id:
            return {}
        from app.ledger.figures import load_figures

        label = doc_label(load_meta(self.shares_id), self.shares_id)
        rows = next((c.get("rows") for c in load_chunks(self.shares_id) if c.get("rows")), None) or []
        figs = {tuple(f["cell"]): f for f in load_figures(self.shares_id) if f.get("cell")}
        out: Dict[str, Dict[str, Any]] = {}
        for r, row in enumerate(rows):
            f = figs.get((r, 1))
            if r and f and str(row[0]).strip() in ("보통주", "우선주", "합계"):
                out[str(row[0]).strip()] = {**f, "docLabel": label, "metric": f"{row[0]} 발행주식의 총수", "period": str(_snap(self.shares_id).get("asOf") or "")}
        return out

    def market_cap(self) -> Tuple[Optional[float], List[Dict[str, Any]], str]:
        sc = self.share_counts()
        if not self.bars or "보통주" not in sc:
            return None, [], ""
        cap = self.bars[-1]["close"] * float(sc["보통주"]["abs"])
        note = "보통주 종가 × 발행주식 총수"
        figs = [sc["보통주"]]
        if "우선주" in sc and self.pref_bars:
            cap += self.pref_bars[-1]["close"] * float(sc["우선주"]["abs"])
            figs.append(sc["우선주"])
            note = "보통주·우선주 종가 × 종류별 발행주식 총수"
        return cap, figs, note


def _ret(bars: List[Dict[str, Any]], days: int) -> Optional[float]:
    from app.market.prices import _ret as price_ret

    return price_ret(bars, days) if bars else None


def _won(v: float) -> str:
    """원 → '1,163조원' · '87.4조원' · '3,210억원'."""
    if abs(v) >= 1e14:
        return f"{v / _TRILLION:,.0f}조원"
    if abs(v) >= 1e12:
        return f"{v / _TRILLION:,.1f}조원"
    return f"{v / 1e8:,.0f}억원"


def _cell(value: Optional[float], display: str, figs: Sequence[Dict[str, Any]] = (), calc: str = "") -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    return {"value": value, "display": display, "cites": [_cite(f) for f in figs], "calc": calc}


def _metrics(cos: List[_Co], wanted: Sequence[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    def row(mid: str, label: str, unit: str, cells: List[Optional[Dict[str, Any]]]) -> None:
        if mid in wanted and any(cells):
            rows.append({"id": mid, "label": label, "unit": unit, "values": cells})

    ttm = {k: [co.ttm(keys) for co in cos] for k, keys in (("revenue", ["매출액"]), ("op", ["영업이익"]), ("ni", _NI), ("eps", ["EPS"]))}
    span = "최근 4분기"
    for mid, label in (("revenue", "매출액"), ("op", "영업이익")):
        row(mid, f"{label} ({span})", "조원", [_cell(v / _TRILLION, f"{v / _TRILLION:,.1f}", figs, "올해 누적 + 직전 사업연도 − 직전 연도 같은 누적") if v is not None else None for v, figs in ttm[mid]])
    opm = []
    for (rv, rf), (ov, of) in zip(ttm["revenue"], ttm["op"]):
        opm.append(_cell(ov / rv * 100, f"{ov / rv * 100:.1f}%", [*of[:1], *rf[:1]], "영업이익 ÷ 매출액(최근 4분기)") if rv and ov is not None else None)
    row("opm", "영업이익률", "%", opm)
    row("ni", f"순이익 ({span})", "조원", [_cell(v / _TRILLION, f"{v / _TRILLION:,.1f}", figs, "올해 누적 + 직전 사업연도 − 직전 연도 같은 누적") if v is not None else None for v, figs in ttm["ni"]])
    roe, per, pbr, ret = [], [], [], []
    for co, (nv, nf), (ev, ef) in zip(cos, ttm["ni"], ttm["eps"]):
        e1, e0 = co.fig(["자본총계"], co.end_key()), co.fig(["자본총계"], co.end_key(1))
        if nv is not None and e1 and e0:
            avg = (float(e1["abs"]) + float(e0["abs"])) / 2
            roe.append(_cell(nv / avg * 100, f"{nv / avg * 100:.1f}%", [e1, e0, *nf[:1]], "최근 4분기 순이익 ÷ 평균 자본총계(최근 분기말·1년 전)") if avg else None)
        else:
            roe.append(None)
        close = co.bars[-1]["close"] if co.bars else None
        per.append(_cell(close / ev, f"{close / ev:.1f}", ef, f"보통주 종가 {close:,.0f}원 ÷ 최근 4분기 기본 EPS {ev:,.0f}원") if close and ev and ev > 0 else None)
        cap, cf, _note = co.market_cap()
        own = co.owners_equity(co.end_key())
        pbr.append(_cell(cap / float(own["abs"]), f"{cap / float(own['abs']):.1f}", [own, *cf], "시가총액 ÷ 지배기업 소유주지분(최근 분기말)") if cap and own and float(own["abs"]) > 0 else None)
        r12 = _ret(co.bars, 365)
        ret.append(_cell(r12, f"{r12:+.1f}%", (), f"{co.bars[-1]['date']} 종가의 1년 전 대비") if r12 is not None else None)
    row("roe", "ROE", "%", roe)
    row("per", "PER", "배", per)
    row("pbr", "PBR", "배", pbr)
    row("ret12", "12개월 주가수익률", "%", ret)
    return rows


def _quarters(cos: List[_Co], n: int = 8) -> Optional[Dict[str, Any]]:
    lasts = [co.last for co in cos if co.last]
    if len(lasts) < len(cos):
        return None
    y, q = min(lasts)
    qs: List[Tuple[int, int]] = []
    for _ in range(n):
        qs.append((y, q))
        y, q = (y, q - 1) if q > 1 else (y - 1, 4)
    qs.reverse()
    series = []
    for co in cos:
        vals, points = [], []
        for yy, qq in qs:
            v, figs = co.quarter(["영업이익"], yy, qq)
            vals.append(round(v / _TRILLION, 1) if v is not None else None)
            points.append({**_cite(figs[0]), "title": f"{yy}년 {qq}분기 영업이익 = " + ("1분기 누적" if qq == 1 else "누적 차이")} if figs else None)
        series.append({"name": co.c["name"], "values": vals, "points": points})
    keep = [i for i in range(len(qs)) if any(s["values"][i] is not None for s in series)]
    return {"categories": [f"{qs[i][1]}Q{qs[i][0] % 100:02d}" for i in keep], "unit": "조원",
            "series": [{"name": s["name"], "values": [s["values"][i] for i in keep], "points": [s["points"][i] for i in keep]} for s in series]}


def _relative(cos: List[_Co]) -> Optional[Dict[str, Any]]:
    """최근 1년 주가 — 첫날 = 100(주 단위 점)."""
    if any(len(co.bars) < 30 for co in cos):
        return None
    since = (date.fromisoformat(min(co.bars[-1]["date"] for co in cos)) - timedelta(days=365)).isoformat()
    start = max(next(b["date"] for b in co.bars if b["date"] >= since) for co in cos)
    series = []
    for co in cos:
        bars = [b for b in co.bars if b["date"] >= start]
        pick = bars[::5] + ([bars[-1]] if (len(bars) - 1) % 5 else [])
        base = bars[0]["close"]
        series.append({"name": co.c["name"], "points": [{"date": b["date"], "value": round(b["close"] / base * 100, 1)} for b in pick], "decimals": 1, "unit": ""})
    return {"base": start, "series": series}


def _header(co: _Co) -> Dict[str, Any]:
    c = co.c
    out: Dict[str, Any] = {"name": c["name"], "code": c.get("stockCode") or c["ticker"].split(".")[0], "ticker": c["ticker"]}
    if co.bars:
        last = co.bars[-1]
        prev = co.bars[-2]["close"] if len(co.bars) > 1 else None
        out.update({"close": last["close"], "date": last["date"], "change": (last["close"] - prev) if prev else None, "changePct": round((last["close"] / prev - 1) * 100, 2) if prev else None,
                    "returns": {"m1": _ret(co.bars, 30), "m3": _ret(co.bars, 91), "m12": _ret(co.bars, 365)}})
    cap, figs, note = co.market_cap()
    if cap:
        out["marketCap"] = {"value": cap, "display": _won(cap), "cites": [_cite(f) for f in figs], "calc": note}
    return out


def related_docs(doc_ids: Sequence[str], companies: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """관련 뉴스·증권사 리포트·공시 — 회사 이름이 카드(회사·제목)에 있는 자료."""
    names = [c["name"] for c in companies]
    codes = {c["corpCode"] for c in companies}
    out: Dict[str, List[Dict[str, Any]]] = {"news": [], "reports": [], "filings": []}
    for d in doc_ids:
        m = load_meta(d) or {}
        card, snap = m.get("card") or {}, m.get("snapshot") or {}
        title = str(card.get("title") or m.get("fileName") or "")
        who = [n for n in names if n == card.get("company") or n in title]
        kind = "news" if card.get("docType") == NEWS else "reports" if card.get("docType") == REPORT else "filings" if snap.get("connector") == "dart" and (snap.get("params") or {}).get("corpCode") in codes else ""
        if not kind or (kind != "filings" and not who):
            continue
        if kind == "filings" and not ((snap.get("params") or {}).get("report") == "annual" or "본문" in title or "개황" in title):
            continue  # 공시는 사업보고서·본문·개황만(분기 재무제표 스냅샷까지 늘어놓지 않는다)
        out[kind].append({"docId": d, "title": title, "issuer": str(card.get("issuer") or ""), "date": str(card.get("date") or ""), "company": " · ".join(who) or str(card.get("company") or ""),
                          "url": str(snap.get("url") or ""), "pages": m.get("pageCount")})
    for k in out:
        out[k].sort(key=lambda x: x["date"], reverse=True)
    out["news"] = out["news"][:30]
    return out


def board(workspace_id: str, params: Dict[str, Any], as_of: Optional[str] = None) -> Dict[str, Any]:
    companies = [c for c in params.get("companies") or [] if c.get("corpCode") and c.get("ticker")][:3]
    if len(companies) < 2:
        return {"error": "비교할 회사가 2곳 이상이어야 합니다."}
    docs = workspace_docs(workspace_id)
    stamp = tuple(round((doc_dir(d) / "figures.json").stat().st_mtime, 1) if (doc_dir(d) / "figures.json").exists() else 0 for c in companies for d in fin_docs(docs, c["corpCode"]))
    key = (workspace_id, tuple(c["corpCode"] for c in companies), tuple(params.get("metrics") or ()), stamp, len(docs), as_of, date.today().isoformat())
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < 300:
        data = hit[1]
    else:
        cos = [_Co(c, docs, as_of) for c in companies]
        wanted = [m for m in (params.get("metrics") or METRICS) if m in METRICS] or list(METRICS)
        last = min((co.last for co in cos if co.last), default=None)
        data = {
            "companies": [_header(co) for co in cos],
            "metrics": _metrics(cos, wanted),
            "quarters": _quarters(cos),
            "relative": _relative(cos),
            "period": f"{last[1]}Q{last[0] % 100:02d}까지 최근 4개 분기" if last else "",
            "priceDate": max((co.bars[-1]["date"] for co in cos if co.bars), default=""),
            "basis": "연결" if all(_snap(d)["params"]["fs"] == "CFS" for co in cos for d in co.fin) else "별도 포함",
            "missing": [co.c["name"] for co in cos if not co.fin],
        }
        _CACHE[key] = (time.time(), data)
    return {**data, "outlook": params.get("outlook") or [], "docs": related_docs(docs, companies)}


# ── 산업 전망(근거 달린 문장) ───────────────────────────────────────────

OUTLOOK_PROMPT = """아래 근거 목록만 써서 두 회사가 속한 산업의 전망을 3개 항목으로 정리한다. JSON 하나로만 답한다(설명·코드 블록 없이).
{"items": [{"title": "8자 이내 주제", "text": "증권사 리포트 문체의 한 문장(60자 이내)", "s": [근거 번호]}]}
규칙:
- 문장은 명사형으로 끝낸다('~전망', '~지속', '~예상', '~확대', '~부담'). '~다.'·'~습니다.'로 끝내지 않는다.
- 근거에 없는 사실·숫자를 쓰지 않는다. 숫자는 근거에 적힌 그대로만 쓴다.
- 증권사 리포트·기사 근거가 있으면 사업보고서보다 먼저 쓴다(더 최근 시각이다).
- 항목마다 근거 번호를 1~2개 단다. 주제는 서로 겹치지 않게(예: 메모리 가격, HBM·AI 수요, 설비투자).
- 매수·매도 같은 투자 의견은 쓰지 않는다."""


def _evidence(workspace_id: str, companies: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from app.docs.store import search_docs

    docs = workspace_docs(workspace_id)
    rel = related_docs(docs, companies)
    ev: List[Dict[str, Any]] = []
    short = {x["docId"]: f"{x['issuer']} · {x['company']}" for x in rel["reports"]}  # 같은 증권사의 두 회사 리포트가 구분되게
    short.update({x["docId"]: f"{x['company']} 사업보고서" for x in rel["filings"] if "본문" in x["title"]})
    # 증권사 리포트 → 사업보고서 본문 순으로 따로 찾는다(리포트가 4쪽짜리라 본문에 밀리지 않게)
    for pool, k in (([x["docId"] for x in rel["reports"]], 8), ([d for d in short if d not in {x["docId"] for x in rel["reports"]}], 4)):
        if not pool:
            continue
        try:
            hits = search_docs(pool, ["업황 전망 수요 가격 메모리", "HBM AI 서버 수요 설비투자 계획"], k=k, per_doc=2, kind="prose", exclude_disclaimer=True)
        except Exception:  # noqa: BLE001
            log.exception("peer outlook search failed")
            hits = []
        for h in hits:
            ch = h["chunk"]
            ev.append({"docId": h["docId"], "chunk": str(ch.get("id")), "label": short.get(h["docId"]) or doc_label(load_meta(h["docId"]), h["docId"]), "text": re.sub(r"\s+", " ", str(ch.get("text") or ""))[:420]})
    for x in rel["news"][:10]:
        ch = next(iter(load_chunks(x["docId"])), None)
        if ch:
            ev.append({"docId": x["docId"], "chunk": str(ch.get("id")), "label": x["issuer"] or "기사", "text": f"{x['title']} ({x['date']})"})
    return ev[:24]


async def outlook(workspace_id: str, companies: Sequence[Dict[str, Any]], llm: Any = None) -> List[Dict[str, Any]]:
    from app.llm.base import ChatParams
    from app.llm.client import ReportLlm

    ev = _evidence(workspace_id, companies)
    if not ev:
        return []
    lines = "\n".join(f"[{i + 1}] ({e['label']}) {e['text']}" for i, e in enumerate(ev))
    content = f"{OUTLOOK_PROMPT}\n\n## 회사\n{', '.join(c['name'] for c in companies)}\n\n## 근거\n{lines}"
    best: List[Dict[str, Any]] = []
    for _ in range(2):  # 검증을 통과한 문장이 모자라면 한 번 더 쓴다
        try:
            res = await (llm or ReportLlm()).complete("chat", ChatParams(messages=[{"role": "user", "content": content}], temperature=0.2, max_tokens=3000, reasoning_effort="low", timeout_s=120))
        except Exception:  # noqa: BLE001
            log.exception("peer outlook failed")
            continue
        m = re.search(r"\{[\s\S]*\}", re.sub(r"^```(?:json)?|```$", "", (getattr(res, "content", "") or "").strip(), flags=re.M))
        try:
            items = (json.loads(m.group(0)) if m else {}).get("items") or []
        except ValueError:
            continue
        kept = _checked(items, ev)
        if len(kept) > len(best):
            best = kept
        if len(best) >= 3:
            break
    return best


def _checked(items: List[Any], ev: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """모델이 쓴 전망 문장 가운데 근거 번호가 실제로 있고, 문장 속 숫자가 그 근거에 있는 것만."""
    out: List[Dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        text, title = re.sub(r"\s+", " ", str(it.get("text") or "")).strip(), str(it.get("title") or "").strip()[:14]
        nums = [n for n in (it.get("s") or []) if isinstance(n, int) and 1 <= n <= len(ev)][:2]
        if not text or not title or not nums or len(text) > 110 or re.search(r"[一-鿿]|(?:매수|매도)\s*(?:의견|추천|권고)", text):
            continue
        src = " ".join(ev[n - 1]["text"] for n in nums).replace(",", "")
        if any(x not in src for x in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))):
            continue  # 근거에 없는 숫자가 든 문장은 버린다
        cites = list({ev[n - 1]["docId"]: {"docId": ev[n - 1]["docId"], "chunk": ev[n - 1]["chunk"], "label": ev[n - 1]["label"]} for n in nums}.values())  # 같은 자료는 한 번만
        out.append({"title": title, "text": text.rstrip("."), "cites": cites})
    return out[:3]


__all__ = ["METRICS", "board", "ensure_data", "outlook", "related_docs", "resolve_companies"]
