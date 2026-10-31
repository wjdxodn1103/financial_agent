"""검색·자료 가공 탭 API(2026-10-29)."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app import search_studio
from app.auth import UserDep
from app.db import SessionDep

router = APIRouter(prefix="/api")


@router.get("/workspaces/{workspace_id}/search/studio")
def studio_search(workspace_id: str, user: UserDep, session: SessionDep, q: str = "", kinds: str = "", docType: str = "", issuer: str = "", since: str = "", until: str = ""):
    return search_studio.search(session, workspace_id, user, q, [k for k in kinds.split(",") if k], docType, issuer, since[:10], until[:10])


class QueryBody(BaseModel):
    q: str


@router.post("/workspaces/{workspace_id}/search/query")
async def studio_query(workspace_id: str, body: QueryBody, user: UserDep):
    return await search_studio.query(workspace_id, user, body.q)


class ComposeBody(BaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)
    op: str = "table"
    title: str = ""


@router.post("/workspaces/{workspace_id}/search/compose")
def studio_compose(workspace_id: str, body: ComposeBody, user: UserDep, session: SessionDep):
    return search_studio.compose(session, workspace_id, user, body.items, body.op, body.title)
