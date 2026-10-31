"""예약 작업 등록 — 기록 비서 밖의 작업(수집 소스·시장 갱신·루틴·가정 감시)을 scheduler 에 더한다.
기능마다 `JOB_MODULES` 의 모듈이 `register_jobs(scheduler)` 와 (있으면) `recover_stale()` 을 둔다."""
from __future__ import annotations

import importlib
import logging
from typing import List

log = logging.getLogger(__name__)

# 단계마다 더한다 — 모듈이 아직 없으면 건너뛴다
JOB_MODULES: List[str] = [
    "app.pipeline.jobs",
    "app.routines.jobs",
    "app.calendar.jobs",
]


def _modules() -> List[object]:
    out = []
    for name in JOB_MODULES:
        try:
            out.append(importlib.import_module(name))
        except ModuleNotFoundError as e:
            if e.name and name.startswith(e.name):
                continue  # 아직 없는 단계
            raise
    return out


def register_all() -> None:
    from app import scheduler

    for m in _modules():
        try:
            m.register_jobs(scheduler)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            log.exception("job registration failed: %s", m)


def recover_stale() -> None:
    for m in _modules():
        fn = getattr(m, "recover_stale", None)
        if fn:
            fn()
