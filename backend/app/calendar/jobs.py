"""경제 일정 예약 — 일정 합치기(서버 시작 때 한 번 + 매일 06:00·18:00) · 발표 감지(1분마다, 감지할 일정이 있을 때만)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

SYNC_HOURS = (6, 18)  # 하루 두 번(아침 브리핑 전 · 저녁) — 거시 시계열 수집(06:30·18:00)과 같은 박자
_state: Dict[str, Any] = {"synced": ""}  # 마지막으로 합친 몫('YYYY-MM-DD@HH', 한국 시각) — 서버 시작 때는 비어 있어 한 번 돈다


def _slot(now_local: datetime) -> str:
    """지금 시각이 속한 가장 최근 몫 — 그날 첫 시각 전이면 ''."""
    hours = [h for h in SYNC_HOURS if now_local.hour >= h]
    return f"{now_local.date().isoformat()}@{hours[-1]:02d}" if hours else ""


def register_jobs(scheduler: Any) -> None:
    from app.calendar.service import sync
    from app.calendar.watch import due_events, run_watch
    from app.db import utcnow

    def sync_due(_ws: Optional[Any], now_local: datetime) -> bool:
        slot = _slot(now_local)
        return not _state["synced"] or (bool(slot) and _state["synced"] != slot)

    async def sync_run(_ws: Optional[Any]) -> None:
        import asyncio

        from app.scheduler import local_now

        now = local_now()
        _state["synced"] = _slot(now) or f"{now.date().isoformat()}@start"
        await asyncio.to_thread(sync)

    def watch_due(_ws: Optional[Any], _now_local: datetime) -> bool:
        return bool(due_events(utcnow()))

    async def watch_run(_ws: Optional[Any]) -> None:
        await run_watch()

    scheduler.register("calendar_sync", due=sync_due, run=sync_run)
    scheduler.register("calendar_watch", due=watch_due, run=watch_run)
