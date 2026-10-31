"""루틴 예약 — 전사 작업 하나가 1분마다 때가 된 루틴을 차례로(한 번에 하나) 돌린다."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.db import RoutineRun, engine, utcnow

JOB = "routines"


def register_jobs(scheduler: Any) -> None:
    from app.routines.runner import due_routines, run_due

    def due(_ws: Optional[Any], now_local: datetime) -> bool:
        return bool(due_routines(now_local))

    async def run(_ws: Optional[Any]) -> None:
        from app.scheduler import local_now

        await run_due(local_now())

    scheduler.register(JOB, due=due, run=run)


def recover_stale() -> None:
    with Session(engine) as s:
        for r in s.exec(select(RoutineRun).where(RoutineRun.status == "running")).all():
            r.status, r.note, r.finished_at = "error", "서버가 다시 시작되어 중단됨", utcnow()
            s.add(r)
        s.commit()
