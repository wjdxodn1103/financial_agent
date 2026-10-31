"""데이터 품질 점검 — 시계열(결측·이상치·공급자 간 불일치·기준일 지남), 문서(원장 값 충돌), 수집(실패 항목).
코드만으로 판단하고(LLM 0회), 같은 문제는 key 하나로 한 줄. 이번 점검에 없으면 해소(resolved_at)로 닫는다.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.db import DataIssue, DataSource, MarketObservation, MarketStatus, SourceItem, company_ids, engine, iso, utcnow
from app.ids import id36
from app.market.catalog import BY_ID, PROVIDER_KO, SERIES

KIND_KO = {"missing": "결측", "outlier": "이상치", "disagree": "공급자 간 불일치", "stale": "기준일 지남", "unit": "단위·주기", "doc_mismatch": "자료 간 숫자 불일치", "ingest_failed": "수집 실패"}


def _series_issues(s: Session) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    today = date.today()
    for sr in SERIES:
        if sr.calc:
            continue
        st = s.get(MarketStatus, sr.id)
        if not st or not st.provider_in_use:
            continue
        pts = [(o.date, o.value) for o in s.exec(select(MarketObservation).where(MarketObservation.series_id == sr.id, MarketObservation.source == st.provider_in_use, MarketObservation.vintage == "").order_by(MarketObservation.date)).all()]
        if not pts:
            continue
        last = date.fromisoformat(pts[-1][0])
        # 월간 지표는 관측일(그달 1일) 뒤 6주쯤 발표 — 80일. FRED 환율(H.10)은 일별 값을 매주 한 번 올린다 — 10일
        limit = 80 if sr.freq != "D" else (10 if st.provider_in_use == "fred" and sr.group == "환율" else 5)
        if (today - last).days > limit:
            out.append({"key": f"stale:{sr.id}", "kind": "stale", "series_id": sr.id, "detail": {"name": sr.name, "lastDate": pts[-1][0], "provider": PROVIDER_KO.get(st.provider_in_use, st.provider_in_use)}})
        if sr.freq == "D":
            recent = [p for p in pts if date.fromisoformat(p[0]) >= today - timedelta(days=90)]
            for (d0, _v0), (d1, _v1) in zip(recent, recent[1:]):
                a, b = date.fromisoformat(d0), date.fromisoformat(d1)
                bdays = sum(1 for k in range(1, (b - a).days) if (a + timedelta(days=k)).weekday() < 5)
                if bdays >= 4:  # 영업일 4일 넘게 빈 구간(휴일 하루·이틀은 넘어간다)
                    out.append({"key": f"missing:{sr.id}:{d0}", "kind": "missing", "series_id": sr.id, "detail": {"name": sr.name, "from": d0, "to": d1, "businessDays": bdays}})
            vals = [v for _d, v in pts[-61:]]
            if len(vals) >= 30:
                ch = [b - a if sr.change == "bp" else (b / a - 1 if a else 0) for a, b in zip(vals, vals[1:])]
                hist, lastc = ch[:-1], ch[-1]
                sd = statistics.pstdev(hist) if len(hist) > 5 else 0
                if sd > 0 and abs(lastc - statistics.mean(hist)) > 5 * sd:
                    out.append({"key": f"outlier:{sr.id}:{pts[-1][0]}", "kind": "outlier", "series_id": sr.id, "detail": {"name": sr.name, "date": pts[-1][0], "value": pts[-1][1], "prev": pts[-2][1], "sigma": round(abs(lastc - statistics.mean(hist)) / sd, 1)}})
        for pname, _code in sr.check:
            if pname == st.provider_in_use:
                continue
            other = {o.date: o.value for o in s.exec(select(MarketObservation).where(MarketObservation.series_id == sr.id, MarketObservation.source == pname, MarketObservation.vintage == "")).all()}
            common = [(d, v) for d, v in pts if d in other][-5:]
            for d, v in common[-1:]:
                o = other[d]
                diff = abs(v - o) if sr.change == "bp" else (abs(v - o) / abs(o) if o else 0)
                if diff > sr.tol:
                    out.append({"key": f"disagree:{sr.id}:{pname}", "kind": "disagree", "series_id": sr.id,
                                "detail": {"name": sr.name, "date": d, "a": {"provider": PROVIDER_KO.get(st.provider_in_use, st.provider_in_use), "value": v}, "b": {"provider": PROVIDER_KO.get(pname, pname), "value": o}, "tol": sr.tol}})
    return out


def _doc_issues() -> List[Dict[str, Any]]:
    """사내 공용 데이터의 원장 값 충돌(같은 지표·기간·기준에 자료마다 다른 값)."""
    from app.docs.store import doc_label, load_meta
    from app.ledger.figures import workspace_ledger

    ids = company_ids()
    if not ids:
        return []
    labels = {d: doc_label(load_meta(d), d) for d in ids}
    try:
        led = workspace_ledger(ids, labels, {})
    except Exception:  # noqa: BLE001
        return []
    out = []
    for g in led.get("groups") or []:
        if g.get("conflict"):
            out.append({"key": f"conflict:{g['key']}", "kind": "doc_mismatch", "detail": {"metric": g.get("metric"), "period": g.get("period"), "values": [v.get("display") for v in g.get("values") or []][:5], "documents": g.get("documents")}})
    return out[:50]


def _ingest_issues(s: Session) -> List[Dict[str, Any]]:
    names = {x.id: (x.name, x.scope, x.workspace_id) for x in s.exec(select(DataSource)).all()}
    out = []
    for it in s.exec(select(SourceItem).where(SourceItem.status == "error")).all():
        nm, scope, ws = names.get(it.source_id, ("", "company", ""))
        out.append({"key": f"ingest:{it.id}", "kind": "ingest_failed", "source_id": it.source_id, "scope": scope, "workspace_id": ws, "detail": {"source": nm, "title": it.title, "error": it.error, "retries": it.retries}})
    return out


def refresh_issues() -> Dict[str, int]:
    with Session(engine) as s:
        found = [*_series_issues(s), *_ingest_issues(s)]
    found += _doc_issues()
    keys = {f["key"] for f in found}
    now = utcnow()
    with Session(engine) as s:
        open_rows = {r.key: r for r in s.exec(select(DataIssue).where(DataIssue.resolved_at == None)).all()}  # noqa: E711
        made = 0
        for f in found:
            if f["key"] in open_rows:
                r = open_rows[f["key"]]
                r.detail = f.get("detail") or {}
                s.add(r)
                continue
            s.add(DataIssue(id=id36("di", 5), key=f["key"], kind=f["kind"], scope=f.get("scope", "company"), workspace_id=f.get("workspace_id", ""), series_id=f.get("series_id"), doc_id=f.get("doc_id"), source_id=f.get("source_id"), detail=f.get("detail") or {}))
            made += 1
        closed = 0
        for k, r in open_rows.items():
            if k not in keys:
                r.resolved_at = now
                s.add(r)
                closed += 1
        s.commit()
    return {"open": len(keys), "new": made, "resolved": closed}


def issue_view(r: DataIssue) -> Dict[str, Any]:
    return {"id": r.id, "kind": r.kind, "kindKo": KIND_KO.get(r.kind, r.kind), "seriesId": r.series_id, "sourceId": r.source_id, "detail": r.detail or {}, "detectedAt": iso(r.detected_at), "resolvedAt": iso(r.resolved_at)}


def issues(workspace_id: Optional[str] = None, include_resolved: bool = False, limit: int = 100) -> List[Dict[str, Any]]:
    with Session(engine) as s:
        q = select(DataIssue)
        if not include_resolved:
            q = q.where(DataIssue.resolved_at == None)  # noqa: E711
        rows = s.exec(q.order_by(DataIssue.detected_at.desc()).limit(limit * 2)).all()
    return [issue_view(r) for r in rows if r.scope == "company" or (workspace_id and r.workspace_id == workspace_id)][:limit]
