"""가정 감시 API(문서 속, 2026-10-29)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.assumptions import service as asm
from app.auth import UserDep
from app.db import SessionDep

router = APIRouter(prefix="/api")


@router.get("/workspaces/{workspace_id}/assumptions")
def list_assumptions(workspace_id: str, user: UserDep, session: SessionDep, docRef: Optional[str] = None):
    return {"assumptions": asm.listing(session, workspace_id, user, docRef)}


class ExtractBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    doc_kind: str = Field("report", alias="docKind")
    doc_ref: str = Field(alias="docRef")


@router.post("/workspaces/{workspace_id}/assumptions/extract")
async def extract_assumptions(workspace_id: str, body: ExtractBody, user: UserDep):
    return {"assumptions": await asm.run_extract(workspace_id, user, body.doc_kind, body.doc_ref)}


@router.patch("/assumptions/{assumption_id}")
def update_assumption(assumption_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    return asm.update(session, assumption_id, user, body)


class CheckBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    as_of: Optional[str] = Field(None, alias="asOf")


@router.post("/assumptions/{assumption_id}/check")
async def check_assumption(assumption_id: str, user: UserDep, session: SessionDep, body: Optional[CheckBody] = None):
    from fastapi import HTTPException

    from app.auth import require_member
    from app.db import Assumption

    a = session.get(Assumption, assumption_id)
    if a is None:
        raise HTTPException(404, "가정을 찾지 못했습니다.")
    require_member(session, a.workspace_id, user)
    return await asm.check(assumption_id, (body.as_of if body else None) or None, trigger={"kind": "manual", "by": user.id})


@router.post("/assumptions/{assumption_id}/agenda")
def assumption_agenda(assumption_id: str, user: UserDep):
    """백그라운드로 시작만 — 다 쓰면 알림(지금 가정 상태를 돌려준다: latest.agendaStatus = writing)."""
    return asm.start_agenda(assumption_id, user)


@router.get("/workspaces/{workspace_id}/today")
def today(workspace_id: str, user: UserDep, session: SessionDep):
    return asm.today(session, workspace_id, user)
