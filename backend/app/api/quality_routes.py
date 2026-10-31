"""품질·이용 API(관리자 전용, 2026-10-29) — 지표·이용 현황·평가 세트 채점."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.auth import UserDep
from app.pipeline.service import is_admin
from app.quality import evals, kpi

router = APIRouter(prefix="/api/admin/quality")


def _admin(user) -> None:
    if not is_admin(user):
        raise HTTPException(403, "관리자만 볼 수 있습니다.")


@router.get("")
def quality(user: UserDep, days: int = 7):
    _admin(user)
    return {**kpi.compute(days), "evals": evals.history()}


@router.post("/eval")
async def run_eval(user: UserDep):
    _admin(user)
    return await evals.run(user)
