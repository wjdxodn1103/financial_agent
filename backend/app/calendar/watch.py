"""발표 감지 — 1분마다: 예정 시각이 지났고 아직 값이 없는 일정을 공식 소스로 확인한다(AI 없음).
확인 간격: 처음 15분은 매분(BLS 키가 없으면 3분 — 하루 25회 한도), 2시간까지 5분, 24시간까지 30분. 그 뒤로는 보지 않는다(일정 합치기가 지난 값을 채운다).
값이 잡히면 실제치를 기록하고 바로 알림(service.record_actual → deliver).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app import config
from app.calendar import sources
from app.calendar.catalog import BY_ID
from app.calendar.service import record_actual
from app.db import MarketEvent, engine, iso, set_json, utcnow

log = logging.getLogger(__name__)
WINDOW = timedelta(hours=24)


def _interval(elapsed: timedelta, uses_bls: bool) -> int:
    if elapsed < timedelta(minutes=15):
        return 180 if uses_bls and not config.BLS_API_KEY else 60
    if elapsed < timedelta(hours=2):
        return 300
    return 1800


def due_events(now: datetime) -> List[MarketEvent]:
    with Session(engine) as s:
        rows = s.exec(select(MarketEvent).where(MarketEvent.status == "scheduled", MarketEvent.indicator_id != None, MarketEvent.at <= now, MarketEvent.at >= now - WINDOW)).all()  # noqa: E711
    out = []
    for ev in rows:
        ind = BY_ID.get(ev.indicator_id or "")
        avail = sources.available(ind) if ind else []
        if not avail:
            continue
        last = (ev.detect or {}).get("lastPollAt")
        if last:
            try:
                if (now - datetime.fromisoformat(last.replace("Z", ""))).total_seconds() < _interval(now - ev.at, "bls" in avail) - 5:
                    continue
            except ValueError:
                pass
        out.append(ev)
    return out


def _meeting_text(value: float, prev: Optional[float]) -> str:
    if prev is None:
        return "결정"
    d = round(value - prev, 4)
    return "동결" if abs(d) < 1e-9 else (f"인상 {abs(d):.2f}%p" if d > 0 else f"인하 {abs(d):.2f}%p")


async def run_watch() -> int:
    now = utcnow()
    due = due_events(now)
    if not due:
        return 0
    bls_ids = sorted({BY_ID[e.indicator_id].bls for e in due if BY_ID.get(e.indicator_id or "") and BY_ID[e.indicator_id].bls})  # type: ignore[index]
    bls_cache: Dict[str, sources.Points] = {}
    bls_err = ""
    if bls_ids:
        try:
            bls_cache = await asyncio.to_thread(sources.bls_fetch, list(bls_ids))
        except Exception as e:  # noqa: BLE001
            bls_err = str(e)[:120]
    fomc_cache: Optional[List[Dict[str, Any]]] = None
    found = 0
    for ev in due:
        ind = BY_ID[ev.indicator_id or ""]
        hit: Optional[Tuple[float, str, str, str, Optional[float]]] = None  # (값, 결정 문구, 원문 URL, 관측 키, 이전치)
        errs: List[str] = [bls_err] if bls_err and ind.bls else []
        for via in sources.available(ind):
            if via == "bls" and not bls_cache:
                continue
            try:
                if via == "fomc":
                    if fomc_cache is None:
                        fomc_cache = await asyncio.to_thread(sources.fomc_statements)
                    sts = [x for x in fomc_cache if x.get("upper") is not None]
                    new = next((x for x in sts if x["date"] >= ev.period_key), None)
                    if new:
                        older = next((x for x in sts if x["date"] < new["date"]), None)
                        prev = older["upper"] if older else ev.previous
                        hit = (new["upper"], f"{sources.DECISION_KO.get(new['decision'], '')} {new['lower']:.2f}~{new['upper']:.2f}%".strip(), new["url"], new["date"], prev)
                else:
                    pts = await asyncio.to_thread(sources.values, ind, via, bls_cache)
                    if ind.freq == "meeting":  # 회의(한은): 결정일 이후 첫 관측값
                        after = [p for p in pts if p[0] >= ev.period_key]
                        before = [p for p in pts if p[0] < ev.period_key]
                        if after:
                            prev = before[-1][1] if before else ev.previous
                            hit = (after[0][1], _meeting_text(after[0][1], prev), "", after[0][0], prev)
                    else:
                        cur = next((p for p in pts if p[0] == ev.period_key), None)
                        before = [p for p in pts if p[0] < ev.period_key]
                        if cur:
                            hit = (cur[1], "", "", cur[0], before[-1][1] if before else None)
                if hit:
                    record_actual(ev.id, hit[0], text=hit[1], via=via, url=hit[2] or ind.url, obs=hit[3], previous=hit[4])
                    found += 1
                    break
            except Exception as e:  # noqa: BLE001
                errs.append(f"{via}: {str(e)[:100]}")
        if not hit:
            with Session(engine) as s:
                row = s.get(MarketEvent, ev.id)
                if row is not None:
                    d = row.detect or {}
                    set_json(row, "detect", {**d, "lastPollAt": iso(now), "polls": int(d.get("polls") or 0) + 1, "errors": errs[-3:] or None})
                    s.add(row)
                    s.commit()
    return found
