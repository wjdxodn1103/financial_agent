"""시장 데이터 — 갱신(공급자 사슬·대체·대조), 보기(값·전일/1주/1달 변화·스파크라인), 상태(공급자별 마지막 갱신·대체 적용).

숫자는 전부 코드가 계산한다(변화 = 저장한 관측값끼리). 한 시리즈의 값은 지금 쓰는 공급자 하나에서만 가져와 섞지 않는다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlmodel import Session, select

from app.db import MarketObservation, MarketStatus, engine, iso, utcnow
from app.market.catalog import BY_ID, GROUPS, PROVIDER_KO, SERIES, Series, full_chain
from app.market.providers import PROVIDERS, ProviderError

log = logging.getLogger(__name__)
HISTORY_DAYS = 430  # 1년 차트 + 여유
SPARK = 60
Point = Tuple[str, float]


def _d(s: str) -> date:
    return date.fromisoformat(s[:10])


def _upsert(s: Session, series_id: str, source: str, rows: Sequence[Point], vintage: str = "") -> int:
    have = {o.date: o for o in s.exec(select(MarketObservation).where(MarketObservation.series_id == series_id, MarketObservation.source == source, MarketObservation.vintage == vintage)).all()}
    n = 0
    now = utcnow()
    for d, v in rows:
        o = have.get(d)
        if o is None:
            s.add(MarketObservation(id=f"{series_id}|{d}|{source}|{vintage}", series_id=series_id, date=d, source=source, vintage=vintage, value=float(v), fetched_at=now))
            n += 1
        elif abs(o.value - float(v)) > 1e-12:
            o.value, o.fetched_at = float(v), now  # 공급자가 고친 값(수정 발표) — 빈티지가 없는 줄은 최신으로
            s.add(o)
            n += 1
    return n


def refresh_series(sr: Series, as_of: Optional[str] = None) -> Dict[str, Any]:
    """사슬 앞에서부터 받아 본다 → 처음 성공한 공급자가 '지금 쓰는 공급자'. 대조 공급자 값도 저장한다."""
    end = _d(as_of) if as_of else date.today()
    start = end - timedelta(days=HISTORY_DAYS)
    vintage = as_of or ""
    result: Dict[str, Any] = {"seriesId": sr.id, "provider": None, "rows": 0, "fallback": False, "providers": {}}
    chain = full_chain(sr)
    with Session(engine) as s:
        st = s.get(MarketStatus, sr.id) or MarketStatus(series_id=sr.id)
        provs: Dict[str, Any] = {}
        for i, (pname, code) in enumerate(chain):
            p = PROVIDERS[pname]
            if not p.ready():
                provs[pname] = {"status": "nokey", "at": iso(utcnow())}
                continue
            try:
                rows = p.fetch(code, start, end, as_of if pname == "fred" else None)
            except (ProviderError, Exception) as e:  # noqa: BLE001 — 다음 공급자로
                provs[pname] = {"status": "error", "error": str(e)[:200], "at": iso(utcnow())}
                continue
            if not rows:
                provs[pname] = {"status": "error", "error": "값 없음", "at": iso(utcnow())}
                continue
            n = _upsert(s, sr.id, pname, rows, vintage if pname == "fred" else "")
            provs[pname] = {"status": "ok", "rows": len(rows), "new": n, "at": iso(utcnow())}
            result.update(provider=pname, rows=len(rows), fallback=i > 0 and not sr.virtual)
            break
        # 대조 공급자(지금 쓰는 공급자와 다르면 따로 받아 둔다)
        for pname, code in sr.check:
            if pname == result["provider"] or pname in provs and provs[pname].get("status") == "ok":
                continue
            try:
                rows = PROVIDERS[pname].fetch(code, start, end)
                _upsert(s, sr.id, pname, rows)
                provs.setdefault(pname, {"status": "ok", "rows": len(rows), "at": iso(utcnow()), "check": True})
            except Exception as e:  # noqa: BLE001
                provs.setdefault(pname, {"status": "error", "error": str(e)[:200], "at": iso(utcnow()), "check": True})
        if result["provider"]:
            last = s.exec(select(MarketObservation.date).where(MarketObservation.series_id == sr.id, MarketObservation.source == result["provider"]).order_by(MarketObservation.date.desc())).first()
            st.provider_in_use, st.fallback, st.last_ok_at, st.last_error, st.last_date = result["provider"], result["fallback"], utcnow(), None, last
        else:
            st.last_error = "; ".join(f"{k}: {v.get('error') or v.get('status')}" for k, v in provs.items())[:500]
        st.providers = provs
        s.add(st)
        s.commit()
    result["providers"] = provs
    return result


def refresh_all(series_ids: Optional[Sequence[str]] = None, as_of: Optional[str] = None) -> Dict[str, Any]:
    ids = [i for i in (series_ids or [s.id for s in SERIES]) if i in BY_ID]
    out = []
    for sid in ids:
        sr = BY_ID[sid]
        if sr.calc:
            continue
        try:
            out.append(refresh_series(sr, as_of))
        except Exception as e:  # noqa: BLE001
            log.exception("market refresh failed: %s", sid)
            out.append({"seriesId": sid, "provider": None, "error": str(e)[:200]})
    ok = [r for r in out if r.get("provider")]
    return {"series": len(out), "ok": len(ok), "fallback": sum(1 for r in ok if r.get("fallback")), "failed": len(out) - len(ok), "results": out}


# ── 보기 ──

def _status(s: Session, sid: str) -> Optional[MarketStatus]:
    return s.get(MarketStatus, sid)


def points(sid: str, as_of: Optional[str] = None, source: Optional[str] = None, session: Optional[Session] = None) -> Tuple[List[Point], Optional[str]]:
    """시리즈 관측값(날짜순) — 지금 쓰는 공급자 하나에서만. 계산 시리즈는 구성 시리즈로 계산."""
    sr = BY_ID[sid]
    own = session is None
    s = session or Session(engine)
    try:
        if sr.calc and sr.calc[0] == "sub":
            a, sa = points(sr.calc[1], as_of, session=s)
            b, _sb = points(sr.calc[2], as_of, session=s)
            bm = dict(b)
            return [(d, round(v - bm[d], 4)) for d, v in a if d in bm], sa
        src = source or ((_status(s, sid) or MarketStatus(series_id=sid)).provider_in_use or None)
        if not src:
            return [], None
        q = select(MarketObservation).where(MarketObservation.series_id == sid, MarketObservation.source == src, MarketObservation.vintage == "")
        if as_of:
            q = q.where(MarketObservation.date <= as_of)
        return [(o.date, o.value) for o in s.exec(q.order_by(MarketObservation.date)).all()], src
    finally:
        if own:
            s.close()


def _at_or_before(pts: List[Point], target: date) -> Optional[Point]:
    best = None
    for d, v in pts:
        if _d(d) <= target:
            best = (d, v)
        else:
            break
    return best


def _minus_month(d: date) -> date:
    y, m = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    import calendar

    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def change(sr: Series, v: float, v0: float) -> Dict[str, Any]:
    if sr.change == "bp":
        x = (v - v0) * (1 if sr.unit == "bp" else 100)
        return {"value": round(x, 1), "unit": "bp", "display": f"{x:+.0f}bp"}
    if sr.change == "pp":
        x = v - v0
        return {"value": round(x, 2), "unit": "%p", "display": f"{x:+.{max(1, sr.decimals)}f}%p"}
    x = (v / v0 - 1) * 100 if v0 else 0.0
    return {"value": round(x, 2), "unit": "%", "display": f"{x:+.2f}%"}


def fmt(sr: Series, v: float) -> str:
    return f"{v:,.{sr.decimals}f}"


def series_card(sid: str, as_of: Optional[str] = None, spark: int = SPARK, session: Optional[Session] = None) -> Dict[str, Any]:
    sr = BY_ID[sid]
    own = session is None
    s = session or Session(engine)
    try:
        pts, src = points(sid, as_of, session=s)
        st = _status(s, sid) if not sr.calc else None
    finally:
        if own:
            s.close()
    card: Dict[str, Any] = {"id": sr.id, "name": sr.name, "group": sr.group, "unit": sr.unit, "decimals": sr.decimals, "freq": sr.freq,
                            "source": src, "sourceLabel": PROVIDER_KO.get(src or "", src or ""), "virtual": src == "demo",
                            "fallback": bool(st.fallback) if st else False, "value": None, "date": None, "changes": {}, "spark": []}
    if not pts:
        card["status"] = "empty"
        return card
    d, v = pts[-1]
    last = _d(d)
    card.update(value=v, display=fmt(sr, v), date=d, spark=[x for _d0, x in pts[-spark:]])
    refs = {
        "d1": pts[-2] if len(pts) > 1 else None,
        "w1": _at_or_before(pts, last - timedelta(days=7)),
        "m1": _at_or_before(pts, _minus_month(last)),
    }
    if sr.freq == "M":  # 월간 지표는 전월·3개월 전·1년 전
        refs = {"d1": pts[-2] if len(pts) > 1 else None, "w1": pts[-4] if len(pts) > 3 else None, "m1": pts[-13] if len(pts) > 12 else None}
    for k, ref in refs.items():
        if ref:
            card["changes"][k] = {**change(sr, v, ref[1]), "from": {"date": ref[0], "value": ref[1], "display": fmt(sr, ref[1])}}
    today = _d(as_of) if as_of else date.today()
    stale_days = 5 if sr.freq == "D" else 50
    card["status"] = "stale" if (today - last).days > stale_days else "ok"
    return card


def board(as_of: Optional[str] = None, ids: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    want = [s for s in SERIES if not ids or s.id in ids]
    with Session(engine) as s:
        cards = [series_card(sr.id, as_of, session=s) for sr in want]
    groups = [{"group": g, "series": [c for c in cards if c["group"] == g]} for g in GROUPS]
    return {"asOf": as_of or date.today().isoformat(), "groups": [g for g in groups if g["series"]]}


def series_view(sid: str, rng: str = "1Y", as_of: Optional[str] = None) -> Dict[str, Any]:
    if sid not in BY_ID:
        raise KeyError(sid)
    pts, src = points(sid, as_of)
    days = {"1M": 31, "3M": 92, "6M": 183, "1Y": 366}.get(rng, 366)
    if pts:
        cut = _d(pts[-1][0]) - timedelta(days=days)
        pts = [(d, v) for d, v in pts if _d(d) >= cut]
    sr = BY_ID[sid]
    return {"id": sid, "name": sr.name, "unit": sr.unit, "decimals": sr.decimals, "source": src, "sourceLabel": PROVIDER_KO.get(src or "", src or ""),
            "virtual": src == "demo", "range": rng, "points": [{"date": d, "value": v} for d, v in pts]}


def status_view() -> Dict[str, Any]:
    with Session(engine) as s:
        rows = {r.series_id: r for r in s.exec(select(MarketStatus)).all()}
    series = []
    prov_last: Dict[str, Dict[str, Any]] = {}
    for sr in SERIES:
        if sr.calc:
            continue
        st = rows.get(sr.id)
        series.append({"id": sr.id, "name": sr.name, "group": sr.group, "virtual": sr.virtual, "providerInUse": (st.provider_in_use if st else "") or None,
                       "providerLabel": PROVIDER_KO.get((st.provider_in_use if st else "") or "", ""), "fallback": bool(st and st.fallback),
                       "lastOkAt": iso(st.last_ok_at) if st else None, "lastDate": st.last_date if st else None, "lastError": st.last_error if st else None,
                       "providers": (st.providers if st else {}) or {}})
        for pname, info in ((st.providers if st else {}) or {}).items():
            cur = prov_last.setdefault(pname, {"provider": pname, "label": PROVIDER_KO.get(pname, pname), "ok": 0, "error": 0, "nokey": 0, "lastAt": None})
            cur[info.get("status", "error")] = cur.get(info.get("status", "error"), 0) + 1
            if info.get("at") and (not cur["lastAt"] or info["at"] > cur["lastAt"]):
                cur["lastAt"] = info["at"]
    return {"series": series, "providers": list(prov_last.values())}
