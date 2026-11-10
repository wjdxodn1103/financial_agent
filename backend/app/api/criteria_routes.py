"""판단 기준·검토 제안 API(2026-10-31)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.auth import UserDep
from app.criteria import proposals, service
from app.db import SessionDep

router = APIRouter(prefix="/api")


class _Body(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# ── 판단 기준 ──────────────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/criteria")
def list_criteria(workspace_id: str, user: UserDep, session: SessionDep):
    return service.listing(session, workspace_id, user)


class ExtractBody(_Body):
    doc_kind: str = Field("data", alias="docKind")
    doc_ref: str = Field(alias="docRef")
    scope: str = "workspace"


@router.post("/workspaces/{workspace_id}/criteria/extract")
async def extract_criteria(workspace_id: str, body: ExtractBody, user: UserDep):
    return await service.run_extract(workspace_id, user, body.doc_kind, body.doc_ref, body.scope)


@router.patch("/criteria/{criterion_id}")
def patch_criterion(criterion_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    return service.patch(session, criterion_id, user, body)


class DecideBody(_Body):
    approve: bool
    note: str = ""


@router.post("/criteria/{criterion_id}/decide")
async def decide_criterion(criterion_id: str, body: DecideBody, user: UserDep):
    return await service.decide(criterion_id, user, body.approve, body.note)


@router.get("/criteria/{criterion_id}/versions")
def criterion_versions(criterion_id: str, user: UserDep, session: SessionDep, workspaceId: Optional[str] = None):
    return {"versions": service.versions(session, criterion_id, user, workspaceId or "")}


class ScanBody(_Body):
    as_of: Optional[str] = Field(None, alias="asOf")


@router.post("/workspaces/{workspace_id}/criteria/scan")
async def scan_criteria(workspace_id: str, user: UserDep, body: Optional[ScanBody] = None):
    """수동 다시 확인 — 대상마다 기준 판정, 바뀐 것만 검토 제안(처음은 기준선)."""
    return await proposals.scan(workspace_id, user, (body.as_of if body else None) or None)


# ── 검토 제안 ──────────────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/proposals")
def list_proposals(workspace_id: str, user: UserDep, session: SessionDep, reportId: Optional[str] = None, status: Optional[str] = "open"):
    return {"proposals": proposals.listing(session, workspace_id, user, reportId, status)}


class ApplyBody(_Body):
    picks: Optional[List[int]] = None


@router.post("/proposals/{proposal_id}/apply")
def apply_proposal(proposal_id: str, user: UserDep, session: SessionDep, body: Optional[ApplyBody] = None):
    return proposals.apply(session, proposal_id, user, body.picks if body else None)


@router.post("/proposals/{proposal_id}/agenda")
def proposal_agenda(proposal_id: str, user: UserDep):
    """백그라운드로 시작만 — 다 쓰면 알림(result.agendaStatus = writing)."""
    return proposals.start_agenda(proposal_id, user)


class DismissBody(_Body):
    note: str = ""


@router.post("/proposals/{proposal_id}/dismiss")
def dismiss_proposal(proposal_id: str, user: UserDep, session: SessionDep, body: Optional[DismissBody] = None):
    return proposals.dismiss(session, proposal_id, user, body.note if body else "")
