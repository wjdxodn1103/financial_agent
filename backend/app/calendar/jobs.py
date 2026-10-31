"""경제 일정 예약 — 일정 합치기(서버 시작 때 한 번 + 매일 06:00) · 발표 감지(1분마다, 감지할 일정이 있을 때만)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

SYNC_HOUR = 6
_state: Dict[str, Any] = {"synced": ""}  # 마지막으로 합친 날(한국 날짜) — 서버 시작 때는 비어 있어 한 번 돈다


def register_jobs(scheduler: Any) -> None:
    from app.calendar.service import sync
    from app.calendar.watch import due_events, run_watch
    from app.db import utcnow

    def sync_due(_ws: Optional[Any], now_local: datetime) -> bool:
        today = now_local.date().isoformat()
        return not _state["synced"] or (_state["synced"] != today and now_local.hour >= SYNC_HOUR)

    async def sync_run(_ws: Optional[Any]) -> None:
        import asyncio

        from app.scheduler import local_now

        _state["synced"] = local_now().date().isoformat()
        await asyncio.to_thread(sync)

    def watch_due(_ws: Optional[Any], _now_local: datetime) -> bool:
        return bool(due_events(utcnow()))

    async def watch_run(_ws: Optional[Any]) -> None:
        await run_watch()

    scheduler.register("calendar_sync", due=sync_due, run=sync_run)
    scheduler.register("calendar_watch", due=watch_due, run=watch_run)
