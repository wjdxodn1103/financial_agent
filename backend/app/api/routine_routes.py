"""루틴(예약 작성) API(2026-10-29)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import scheduler
from app.auth import UserDep
from app.db import SessionDep
from app.routines.runner import run_routine
from app.routines.service import RoutineService

router = APIRouter(prefix="/api")


@router.get("/workspaces/{workspace_id}/routines")
def list_routines(workspace_id: str, user: UserDep, session: SessionDep):
    return {"routines": RoutineService(session).listing(workspace_id, user)}


@router.post("/workspaces/{workspace_id}/routines")
def create_routine(workspace_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    return RoutineService(session).create(workspace_id, user, body)


@router.patch("/routines/{routine_id}")
def update_routine(routine_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    return RoutineService(session).update(routine_id, user, body)


@router.delete("/routines/{routine_id}", status_code=204)
def delete_routine(routine_id: str, user: UserDep, session: SessionDep):
    RoutineService(session).delete(routine_id, user)


class RunBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    as_of: Optional[str] = Field(None, alias="asOf")


@router.post("/routines/{routine_id}/run")
async def run_routine_now(routine_id: str, user: UserDep, session: SessionDep, body: Optional[RunBody] = None):
    """[지금 실행]·[날짜 지정 실행] — 뒤에서 돈다(끝나면 알림)."""
    RoutineService(session).check_run(routine_id, user)
    as_of = (body.as_of if body else None) or None
    if as_of and not (len(as_of) == 10 and as_of[4] == "-" and as_of[7] == "-"):
        raise HTTPException(400, "날짜는 YYYY-MM-DD 로 적어 주세요.")
    if not scheduler.spawn(f"routine:{routine_id}", run_routine(routine_id, trigger="replay" if as_of else "manual", as_of=as_of)):
        raise HTTPException(409, "이 루틴을 이미 돌리고 있습니다.")
    return {"started": True}


@router.get("/routines/{routine_id}/runs")
def routine_runs(routine_id: str, user: UserDep, session: SessionDep):
    return {"runs": RoutineService(session).runs(routine_id, user)}
