"""수집 예약 — 전사 작업 하나가 1분마다 때가 된 소스(사내 공용·워크스페이스)를 차례로 돌린다(한 번에 하나)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select

from app.db import SourceRun, engine, utcnow

JOB = "sources"


def register_jobs(scheduler: Any) -> None:
    from app.pipeline.runner import due_sources, run_due
    from app.pipeline.service import seed_defaults

    seed_defaults()

    def due(_ws: Optional[Any], now_local: datetime) -> bool:
        return bool(due_sources(now_local))

    async def run(_ws: Optional[Any]) -> None:
        from app.scheduler import local_now

        await run_due(local_now())

    scheduler.register(JOB, due=due, run=run)


def recover_stale() -> None:
    with Session(engine) as s:
        for r in s.exec(select(SourceRun).where(SourceRun.status == "running")).all():
            r.status, r.note, r.finished_at = "error", "서버가 다시 시작되어 중단됨", utcnow()
            s.add(r)
        s.commit()
