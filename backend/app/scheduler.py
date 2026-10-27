"""예약 작업 실행기 — 1분마다 등록표(JOBS)를 보고 때가 된 작업을 돈다. 실행 결과는 batch_run 에 남는다.

v1 작업은 기록 비서(매일 워크스페이스 퇴근 시각) 하나. 새 공시 감시·정기 리포트 갱신·주간 요약 같은 작업은
JOBS 에 (때가 됐는가, 돌리기) 한 쌍을 더하면 같은 실행기·같은 실행 기록을 쓴다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlmodel import Session, select

from app import config
from app.db import BatchRun, Workspace, engine
from app.records.digest import JOB as DIGEST_JOB
from app.records.digest import run_digest, workspaces_with_messages

log = logging.getLogger(__name__)
TICK_SEC = 60
_state: Dict[str, Optional["asyncio.Task[None]"]] = {"task": None}


def local_tz() -> Any:
    try:
        return ZoneInfo(config.TIMEZONE)
    except ZoneInfoNotFoundError:
        log.warning("시간대 %s 를 찾지 못해 UTC 로 봅니다(tzdata 를 설치하세요).", config.TIMEZONE)
        return timezone.utc


def local_now() -> datetime:
    return datetime.now(local_tz())


def off_hour(ws: Workspace) -> tuple[int, int]:
    hh, mm = ((ws.settings or {}).get("offHour") or config.DEFAULT_OFF_HOUR).split(":")
    return int(hh), int(mm)


def ran_today(workspace_id: str, job: str, now_local: datetime) -> bool:
    with Session(engine) as s:
        rows = s.exec(select(BatchRun).where(BatchRun.workspace_id == workspace_id, BatchRun.job == job, BatchRun.trigger == "schedule")).all()
    tz = now_local.tzinfo
    return any(r.started_at.replace(tzinfo=timezone.utc).astimezone(tz).date() == now_local.date() for r in rows)


def digest_due(ws: Workspace, now_local: datetime) -> bool:
    hh, mm = off_hour(ws)
    return (now_local.hour, now_local.minute) >= (hh, mm) and not ran_today(ws.id, DIGEST_JOB, now_local)


def next_run_at(ws: Workspace) -> str:
    """화면 표시용 — 다음 퇴근 시각 배치(오늘 이미 돌았거나 지났으면 내일)."""
    now = local_now()
    hh, mm = off_hour(ws)
    at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if (now.hour, now.minute) >= (hh, mm) and ran_today(ws.id, DIGEST_JOB, now):
        at = at + timedelta(days=1)
    return at.isoformat(timespec="minutes")


JOBS: Dict[str, Dict[str, Callable[..., Any]]] = {
    DIGEST_JOB: {"due": digest_due, "run": lambda ws: run_digest(ws.id, trigger="schedule"), "workspaces": workspaces_with_messages},
}


async def tick() -> None:
    now = local_now()
    from app.templates_import.service import clean_imports

    await asyncio.to_thread(clean_imports)  # 14일 지난 양식 샘플 원본
    for name, job in JOBS.items():
        for ws in await asyncio.to_thread(job["workspaces"]):
            try:
                if await asyncio.to_thread(job["due"], ws, now):
                    log.info("[scheduler] %s for %s", name, ws.id)
                    run: Callable[[Workspace], Awaitable[Any]] = job["run"]
                    await run(ws)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — 한 워크스페이스의 실패가 다른 작업을 막지 않게
                log.exception("[scheduler] %s failed for %s", name, ws.id)


async def _loop() -> None:
    while True:
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("[scheduler] tick failed")
        await asyncio.sleep(TICK_SEC)


def start() -> None:
    if _state["task"] is None or _state["task"].done():
        _state["task"] = asyncio.get_running_loop().create_task(_loop(), name="scheduler")


def stop() -> None:
    t = _state["task"]
    if t is not None and not t.done():
        t.cancel()
    _state["task"] = None
