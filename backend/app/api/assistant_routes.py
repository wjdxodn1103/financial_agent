"""어시스턴트 API(2026-10-29) — 가이드라인 점검·IC 회의록 정리·심의 준비·하우스뷰 흐름."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.assistants import committee, guideline, houseview, minutes
from app.auth import UserDep, require_member
from app.db import SessionDep

router = APIRouter(prefix="/api")


@router.get("/workspaces/{workspace_id}/guideline")
def guideline_last(workspace_id: str, user: UserDep, session: SessionDep):
    return {"result": guideline.last(session, workspace_id, user)}


@router.post("/workspaces/{workspace_id}/guideline/check")
async def guideline_check(workspace_id: str, user: UserDep):
    return {"result": await guideline.check(workspace_id, user)}


class MinutesBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    doc_id: str = Field(alias="docId")
    only: Optional[List[str]] = None  # 쓸 섹션 제목(없으면 전부)


@router.post("/workspaces/{workspace_id}/minutes")
def minutes_start(workspace_id: str, body: MinutesBody, user: UserDep):
    return minutes.start(workspace_id, user, body.doc_id, body.only)


class CommitteeBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    doc_kind: str = Field("report", alias="docKind")
    doc_ref: str = Field(alias="docRef")


@router.post("/workspaces/{workspace_id}/committee")
async def committee_prepare(workspace_id: str, body: CommitteeBody, user: UserDep):
    return {"result": await committee.prepare(workspace_id, user, body.doc_kind, body.doc_ref)}


@router.get("/workspaces/{workspace_id}/committee")
def committee_last(workspace_id: str, docRef: str, user: UserDep, session: SessionDep):
    return {"result": committee.last(session, workspace_id, user, docRef)}


@router.get("/workspaces/{workspace_id}/houseview")
def houseview_flow(workspace_id: str, user: UserDep, session: SessionDep):
    require_member(session, workspace_id, user)
    return houseview.widget(workspace_id, user)
