"""예약 작업 실행기 — 1분마다 등록표(JOBS)를 보고 때가 된 작업을 돈다. 실행 결과는 batch_run 등에 남는다.

작업 = (때가 됐는가, 돌리기, 대상 워크스페이스 목록). 대상이 [None] 이면 전사 작업(사내 공용 수집·시장 갱신).
v1 은 기록 비서(매일 워크스페이스 퇴근 시각) 하나였고, 2026-10-29 부터 수집 소스·루틴 등이 `register()` 로 더한다(app/jobs.py).
돌리기는 띄워 두고 다음으로 넘어간다 — 긴 작업(루틴 작성) 하나가 다른 작업을 막지 않게, 같은 (작업, 대상)은 하나만 돈다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlmodel import Session, select

from app import config
from app.db import BatchRun, Workspace, engine
from app.records.digest import JOB as DIGEST_JOB
from app.records.digest import run_digest, workspaces_with_messages

log = logging.getLogger(__name__)
TICK_SEC = 60
_state: Dict[str, Any] = {"task": None, "loop": None}
GLOBAL = "_global"  # 전사 작업의 실행 기록 workspace_id
_running: Set[str] = set()
_tasks: Set["asyncio.Task[None]"] = set()


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


def register(name: str, *, due: Callable[[Optional[Workspace], datetime], bool], run: Callable[[Optional[Workspace]], Awaitable[Any]],
             workspaces: Optional[Callable[[], List[Optional[Workspace]]]] = None) -> None:
    """작업 더하기 — workspaces 가 없으면 전사 작업(대상 [None])."""
    JOBS[name] = {"due": due, "run": run, "workspaces": workspaces or (lambda: [None])}


def is_running(name: str, workspace_id: Optional[str] = None) -> bool:
    return f"{name}:{workspace_id or GLOBAL}" in _running


def spawn(name: str, coro: Awaitable[Any], workspace_id: Optional[str] = None) -> bool:
    """화면의 [지금 실행]도 같은 자리로 — 이미 돌고 있으면 띄우지 않는다(→ False)."""
    key = f"{name}:{workspace_id or GLOBAL}"
    if key in _running:
        if hasattr(coro, "close"):
            coro.close()  # type: ignore[union-attr]
        return False
    _running.add(key)

    async def _run() -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — 한 작업의 실패가 다른 작업을 막지 않게
            log.exception("[scheduler] %s failed", key)
        finally:
            _running.discard(key)

    def _start() -> None:
        t = asyncio.get_running_loop().create_task(_run(), name=f"job:{key}")
        _tasks.add(t)
        t.add_done_callback(_tasks.discard)

    try:
        asyncio.get_running_loop()
        _start()
    except RuntimeError:  # 동기 엔드포인트(스레드풀)에서 부른 경우 — 서버 이벤트 루프에 맡긴다
        loop = _state.get("loop")
        if loop is None:
            _running.discard(key)
            if hasattr(coro, "close"):
                coro.close()  # type: ignore[union-attr]
            return False
        loop.call_soon_threadsafe(_start)
    return True


async def tick() -> None:
    now = local_now()
    from app.templates_import.service import clean_imports

    await asyncio.to_thread(clean_imports)  # 14일 지난 양식 샘플 원본
    for name, job in list(JOBS.items()):
        try:
            targets = await asyncio.to_thread(job["workspaces"])
        except Exception:  # noqa: BLE001
            log.exception("[scheduler] %s targets failed", name)
            continue
        for ws in targets:
            wid = ws.id if ws is not None else None
            if is_running(name, wid):
                continue
            try:
                if not await asyncio.to_thread(job["due"], ws, now):
                    continue
            except Exception:  # noqa: BLE001
                log.exception("[scheduler] %s due check failed for %s", name, wid or GLOBAL)
                continue
            log.info("[scheduler] %s for %s", name, wid or GLOBAL)
            run: Callable[[Optional[Workspace]], Awaitable[Any]] = job["run"]
            spawn(name, run(ws), wid)


def recover_stale() -> None:
    """서버가 작업 도중 꺼졌으면 'running' 으로 남은 실행 기록을 오류로 닫는다(다음 예약이 막히지 않게)."""
    from app.db import utcnow

    with Session(engine) as s:
        for r in s.exec(select(BatchRun).where(BatchRun.status == "running")).all():
            r.status, r.error, r.finished_at = "error", "서버가 다시 시작되어 중단됨", utcnow()
            s.add(r)
        s.commit()
    try:
        from app import jobs

        jobs.recover_stale()
    except Exception:  # noqa: BLE001
        log.exception("[scheduler] recover_stale (jobs) failed")


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
        from app import jobs  # 수집 소스·루틴 등 작업 등록(순환 import 를 피해 여기서)

        jobs.register_all()
        recover_stale()
        _state["loop"] = asyncio.get_running_loop()
        _state["task"] = asyncio.get_running_loop().create_task(_loop(), name="scheduler")


def stop() -> None:
    t = _state["task"]
    if t is not None and not t.done():
        t.cancel()
    _state["task"] = None
