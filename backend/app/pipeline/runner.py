"""수집 실행 — 소스 하나를 돌려 항목을 적재하고(같은 key 는 한 번), 실패 항목은 다음 실행에 3번까지 다시 한다.
실행 기록(SourceRun)·항목(SourceItem)·소스 상태를 남기고, 실패하면 만든 사람에게 알린다. 끝나면 품질 점검을 다시 한다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from sqlmodel import Session, select

from app import usage
from app.db import DataSource, SourceItem, SourceRun, engine, iso, utcnow
from app.ids import id36
from app.notify import notify
from app.pipeline.kinds import COLLECTORS, KIND_KO

log = logging.getLogger(__name__)
RETRY_MAX = 3
_lock = asyncio.Lock()  # 수집은 한 번에 하나(공급자 호출 상한·SQLite 쓰기)


def source_dict(s: DataSource) -> Dict[str, Any]:
    return {"id": s.id, "scope": s.scope, "workspaceId": s.workspace_id, "kind": s.kind, "name": s.name, "params": s.params or {}, "schedule": s.schedule or {}, "target": s.target or {}, "createdBy": s.created_by}


def _seen(source_id: str) -> Set[str]:
    """이미 잘 모은 key(재처리 대상 = 실패했고 아직 3번 안 된 것은 빼서 다시 모은다)."""
    with Session(engine) as s:
        rows = s.exec(select(SourceItem.key, SourceItem.status, SourceItem.retries).where(SourceItem.source_id == source_id)).all()
    return {k for k, st, r in rows if st == "ok" or r >= RETRY_MAX}


def _save_items(source_id: str, items: List[Dict[str, Any]]) -> Dict[str, int]:
    new = failed = 0
    with Session(engine) as s:
        for it in items:
            row = s.exec(select(SourceItem).where(SourceItem.source_id == source_id, SourceItem.key == it["key"])).first()
            if row is None:
                row = SourceItem(id=id36("si", 5), source_id=source_id, key=it["key"])
                new += it.get("status") == "ok"
            elif row.status == "error" and it.get("status") == "ok":
                new += 1
            if it.get("status") == "error":
                failed += 1
                row.retries = (row.retries or 0) + 1  # 실패한 시도 수 — RETRY_MAX 까지 다음 실행에 다시
            elif it.get("replace") and row.doc_id and row.doc_id != it.get("docId"):
                new += 1
            row.doc_id = it.get("docId") or row.doc_id
            row.title, row.url, row.published_at = (it.get("title") or row.title)[:300], it.get("url") or row.url, it.get("publishedAt") or row.published_at
            row.status, row.error, row.fetched_at = it.get("status", "ok"), it.get("error"), utcnow()
            row.meta = {**(row.meta or {}), **(it.get("meta") or {})}
            s.add(row)
        s.commit()
    return {"new": new, "failed": failed}


async def run_source(source_id: str, trigger: str = "manual", as_of: Optional[str] = None) -> Dict[str, Any]:
    with Session(engine) as s:
        src = s.get(DataSource, source_id)
        if src is None:
            raise KeyError(source_id)
        sd = source_dict(src)
        run = SourceRun(id=id36("sr", 5), source_id=source_id, trigger=trigger, as_of=as_of)
        s.add(run)
        s.commit()
        run_id = run.id
    token = usage.bind(user=sd["createdBy"], ws=sd["workspaceId"] or "", feature=f"source:{sd['kind']}", run=run_id, fresh_count=True)
    started = asyncio.get_running_loop().time()
    status, note, counts = "ok", "", {"new": 0, "failed": 0}
    try:
        async with _lock:
            items = await asyncio.to_thread(COLLECTORS[sd["kind"]], sd, as_of, _seen(source_id))
        counts = await asyncio.to_thread(_save_items, source_id, items)
        notes = [str((it.get("meta") or {}).get("note")) for it in items if (it.get("meta") or {}).get("note")]
        note = " · ".join(notes)[:300]
        ok = sum(1 for it in items if it.get("status") == "ok")
        status = "ok" if counts["failed"] == 0 else ("partial" if ok else "error")
    except Exception as e:  # noqa: BLE001
        log.exception("source run failed: %s", source_id)
        status, note = "error", str(e)[:300]
    finally:
        usage.reset(token)
    with Session(engine) as s:
        run = s.get(SourceRun, run_id)
        src = s.get(DataSource, source_id)
        if run:
            run.status, run.new, run.failed, run.note, run.finished_at = status, counts["new"], counts["failed"], note, utcnow()
            s.add(run)
        if src:
            src.last_run_at, src.status = utcnow(), status
            s.add(src)
        s.commit()
    if status in ("error", "partial") and sd["createdBy"]:
        notify([sd["createdBy"]], workspace_id=sd["workspaceId"] or "", kind="source", title=f"수집 {'실패' if status == 'error' else '일부 실패'} — {sd['name']}",
               body=note or f"실패 {counts['failed']}건", link={"w": sd["workspaceId"] or None, "v": "sources", "s": source_id} if sd["workspaceId"] else {"v": "sources", "s": source_id},
               ref={"kind": "source", "id": source_id}, dedupe_key=f"source-run:{run_id}")
    await asyncio.to_thread(usage.activity, "source_run", {"sourceId": source_id, "runId": run_id}, {"sec": round(asyncio.get_running_loop().time() - started, 2), "new": counts["new"], "failed": counts["failed"], "kind": sd["kind"]}, user=sd["createdBy"], ws=sd["workspaceId"] or "")
    try:
        from app.pipeline.quality import refresh_issues

        await asyncio.to_thread(refresh_issues)
    except Exception:  # noqa: BLE001
        log.exception("quality refresh failed")
    try:  # 새로 적재한 자료로 감시 중인 가정을 다시 판정(7단계 — 없으면 건너뜀)
        from app.assumptions.watch import on_new_items

        await on_new_items(source_id, as_of)
    except ModuleNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        log.exception("assumption recheck failed")
    return {"runId": run_id, "status": status, **counts, "note": note}


# ── 예약 ──

def _local(dt: Optional[datetime], tz: Any) -> Optional[datetime]:
    return dt.replace(tzinfo=timezone.utc).astimezone(tz) if dt else None


def is_due(src: DataSource, now_local: datetime) -> bool:
    sch = src.schedule or {}
    every = sch.get("every") or "daily"
    if not src.enabled or every == "manual":
        return False
    with Session(engine) as s:
        last_row = s.exec(select(SourceRun).where(SourceRun.source_id == src.id, SourceRun.trigger == "schedule").order_by(SourceRun.started_at.desc())).first()
    last = _local(last_row.started_at, now_local.tzinfo) if last_row else None
    if every == "hourly":
        return last is None or now_local - last >= timedelta(minutes=55)
    if every == "weekdays" and now_local.weekday() >= 5:
        return False
    if every == "weekly" and now_local.weekday() != int(sch.get("weekday", 0)):
        return False
    slots = []
    for t in sch.get("times") or ["06:30"]:
        try:
            hh, mm = (int(x) for x in str(t).split(":")[:2])
        except ValueError:
            continue
        at = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if at <= now_local:
            slots.append(at)
    if not slots:
        return False
    return last is None or last < max(slots)


def due_sources(now_local: datetime) -> List[str]:
    with Session(engine) as s:
        rows = s.exec(select(DataSource).where(DataSource.enabled == True)).all()  # noqa: E712
    return [r.id for r in rows if is_due(r, now_local)]


async def run_due(now_local: datetime) -> None:
    for sid in due_sources(now_local):
        try:
            await run_source(sid, trigger="schedule")
        except Exception:  # noqa: BLE001
            log.exception("scheduled source failed: %s", sid)


def next_run(src: DataSource, now_local: datetime) -> Optional[str]:
    sch = src.schedule or {}
    every = sch.get("every") or "daily"
    if not src.enabled or every == "manual":
        return None
    if every == "hourly":
        return (now_local + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0).isoformat(timespec="minutes")
    for add in range(0, 8):
        day = now_local + timedelta(days=add)
        if every == "weekdays" and day.weekday() >= 5 or every == "weekly" and day.weekday() != int(sch.get("weekday", 0)):
            continue
        for t in sorted(sch.get("times") or ["06:30"]):
            hh, mm = (int(x) for x in str(t).split(":")[:2])
            at = day.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if at > now_local:
                return at.isoformat(timespec="minutes")
    return None


def kind_ko(kind: str) -> str:
    return KIND_KO.get(kind, kind)


def run_view(r: SourceRun) -> Dict[str, Any]:
    return {"id": r.id, "trigger": r.trigger, "asOf": r.as_of, "status": r.status, "new": r.new, "failed": r.failed, "note": r.note, "startedAt": iso(r.started_at), "finishedAt": iso(r.finished_at)}
