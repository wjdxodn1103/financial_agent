"""루틴 실행 — 만든 사람 이름으로 화면 없이 쓰고('AI 초안'), 받는 사람에게 알리고, 검토 담당에게 검토를 요청한다.
예약 실행은 하루 한 번, [지금 실행]·[날짜 지정 실행]은 하루 MANUAL_PER_DAY 번까지. LLM 루틴은 한 번에 하나만 돈다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app import usage
from app.auth import ROLE_RANK
from app.db import Membership, Routine, RoutineRun, User, engine, iso, utcnow
from app.ids import id36
from app.notify import member_ids, notify

log = logging.getLogger(__name__)
LEAD_MIN = 20  # 정한 시각보다 먼저 시작(그 시각에 올라와 있게)
MANUAL_PER_DAY = 5
_lock = asyncio.Lock()


def _local(dt: Optional[datetime], tz: Any) -> Optional[datetime]:
    return dt.replace(tzinfo=timezone.utc).astimezone(tz) if dt else None


def is_due(r: Routine, now_local: datetime) -> bool:
    sch = r.schedule or {}
    every = sch.get("every") or "daily"
    if not r.enabled or every == "manual":
        return False
    if every == "weekdays" and now_local.weekday() >= 5 or every == "weekly" and now_local.weekday() != int(sch.get("weekday", 0)):
        return False
    try:
        hh, mm = (int(x) for x in str(sch.get("time") or "07:00").split(":")[:2])
    except ValueError:
        return False
    start = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0) - timedelta(minutes=LEAD_MIN)
    if now_local < start:
        return False
    changed = _local(max(r.created_at, r.updated_at), now_local.tzinfo)
    if changed and changed > start:
        return False  # 오늘 시각이 지난 뒤에 만들거나 일정을 바꾼 루틴은 다음 회차부터(바로 한 번 더 돌지 않게)
    with Session(engine) as s:
        rows = s.exec(select(RoutineRun).where(RoutineRun.routine_id == r.id, RoutineRun.trigger == "schedule")).all()
    return not any(_local(x.started_at, now_local.tzinfo).date() == now_local.date() for x in rows)


def next_run(r: Routine, now_local: datetime) -> Optional[str]:
    sch = r.schedule or {}
    every = sch.get("every") or "daily"
    if not r.enabled or every == "manual":
        return None
    hh, mm = (int(x) for x in str(sch.get("time") or "07:00").split(":")[:2])
    for add in range(0, 8):
        day = now_local + timedelta(days=add)
        if every == "weekdays" and day.weekday() >= 5 or every == "weekly" and day.weekday() != int(sch.get("weekday", 0)):
            continue
        at = day.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if at > now_local:
            return at.isoformat(timespec="minutes")
    return None


def manual_left(routine_id: str) -> int:
    with Session(engine) as s:
        rows = s.exec(select(RoutineRun).where(RoutineRun.routine_id == routine_id, RoutineRun.trigger != "schedule", RoutineRun.started_at >= utcnow() - timedelta(hours=24))).all()
    return max(0, MANUAL_PER_DAY - len(rows))


def _title(r: Routine, as_of: Optional[str]) -> str:
    day = as_of or date.today().isoformat()
    try:
        return (r.title_pattern or "{name} {date}").format(name=r.name, date=day)[:120]
    except (KeyError, ValueError, IndexError):
        return f"{r.name} {day}"


async def run_routine(routine_id: str, trigger: str = "manual", as_of: Optional[str] = None) -> Dict[str, Any]:
    from app.headless import write_report

    with Session(engine) as s:
        r = s.get(Routine, routine_id)
        if r is None:
            raise KeyError(routine_id)
        snap = r.model_copy()
        run = RoutineRun(id=id36("rr", 5), routine_id=r.id, workspace_id=r.workspace_id, trigger=trigger, as_of=as_of)
        s.add(run)
        s.commit()
        run_id = run.id
        mm = s.get(Membership, (r.workspace_id, r.owner_id))
        owner = s.get(User, r.owner_id)
    status, note, report_id, written = "ok", "", None, 0
    token = usage.bind(user=snap.owner_id, ws=snap.workspace_id, feature="routine", run=run_id, fresh_count=True)
    try:
        if mm is None or owner is None or ROLE_RANK.get(mm.role, 0) < ROLE_RANK["editor"]:
            raise PermissionError("만든 사람이 이 워크스페이스의 편집자가 아니어서 실행하지 않았습니다.")
        if not snap.format_id:
            raise ValueError("루틴에 양식이 없습니다.")
        async with _lock:
            res = await write_report(workspace_id=snap.workspace_id, owner_id=snap.owner_id, format_id=snap.format_id, title=_title(snap, as_of), instruction=snap.instruction,
                                     data_scope=snap.data_scope or None, as_of=as_of, folder_id=snap.folder_id, origin={"routine": snap.id, "routineName": snap.name, "runId": run_id})
        report_id, written = res["sessionId"], res["written"]
        status = "ok" if written and not res.get("stopped") and not res["warnings"] else ("partial" if written else "error")
        note = " · ".join(x for x in [f"섹션 {written}/{res['sections']}", f"{res['sec']:.0f}초", f"멈춤: {res['stopped']}" if res.get("stopped") else "", *res["warnings"][:3]] if x)[:300]
    except Exception as e:  # noqa: BLE001
        log.exception("routine failed: %s", routine_id)
        status, note = "error", str(e)[:300]
    finally:
        calls = usage.calls()
        usage.reset(token)
    with Session(engine) as s:
        run = s.get(RoutineRun, run_id)
        r = s.get(Routine, routine_id)
        if run:
            run.status, run.report_id, run.written, run.llm_calls, run.note, run.finished_at = status, report_id, written, calls, note, utcnow()
            s.add(run)
        if r:
            r.last_run_at = utcnow()
            s.add(r)
        s.commit()
    link = {"w": snap.workspace_id, "v": "reports", "s": report_id} if report_id else {"w": snap.workspace_id, "v": "routines", "s": snap.id}
    if report_id and written:
        to: List[str] = member_ids(snap.workspace_id) if (snap.recipients or {}).get("all") else list((snap.recipients or {}).get("userIds") or [])
        notify([*to, snap.owner_id], workspace_id=snap.workspace_id, kind="routine", title=f"{_title(snap, as_of)} — AI 초안이 올라왔습니다"[:200], body=note, link=link,
               ref={"kind": "routine", "id": snap.id, "runId": run_id, "reportId": report_id}, dedupe_key=f"routine-run:{run_id}")
        if snap.reviewer_id and snap.reviewer_id != snap.owner_id:
            try:
                from app.services.report_service import ReportService

                with Session(engine) as s:
                    ReportService(s).request_review(report_id, s.get(User, snap.owner_id), snap.reviewer_id, f"루틴 '{snap.name}' AI 초안")
            except Exception:  # noqa: BLE001
                log.exception("routine review request failed")
    if status != "ok":
        notify([snap.owner_id], workspace_id=snap.workspace_id, kind="routine", title=f"루틴 '{snap.name}' {'일부만 썼습니다' if status == 'partial' else '실패'}", body=note, link=link,
               ref={"kind": "routine", "id": snap.id, "runId": run_id}, dedupe_key=f"routine-fail:{run_id}")
    await asyncio.to_thread(usage.activity, "routine_run", {"routineId": snap.id, "runId": run_id, "reportId": report_id}, {"status": status, "written": written, "calls": calls}, user=snap.owner_id, ws=snap.workspace_id)
    return {"runId": run_id, "status": status, "reportId": report_id, "note": note}


def due_routines(now_local: datetime) -> List[str]:
    with Session(engine) as s:
        rows = s.exec(select(Routine).where(Routine.enabled == True)).all()  # noqa: E712
    return [r.id for r in rows if is_due(r, now_local)]


async def run_due(now_local: datetime) -> None:
    for rid in due_routines(now_local):
        try:
            await run_routine(rid, trigger="schedule")
        except Exception:  # noqa: BLE001
            log.exception("scheduled routine failed: %s", rid)


def run_view(r: RoutineRun) -> Dict[str, Any]:
    return {"id": r.id, "trigger": r.trigger, "asOf": r.as_of, "status": r.status, "reportId": r.report_id, "written": r.written, "llmCalls": r.llm_calls, "note": r.note, "startedAt": iso(r.started_at), "finishedAt": iso(r.finished_at)}
