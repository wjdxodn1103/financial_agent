"""여러 화면이 같이 쓰는 API — 알림함·피드백(2026-10-29)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app import feedback, notify, sharing
from app.auth import UserDep
from app.db import SessionDep

router = APIRouter(prefix="/api")


class _Body(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


# ── 알림함 ─────────────────────────────────────────────────────────────

@router.get("/notifications")
def list_notifications(user: UserDep, session: SessionDep, unread: int = 0, limit: int = 30):
    return notify.listing(session, user.id, unread_only=bool(unread), limit=limit)


@router.get("/notifications/count")
def notification_count(user: UserDep, session: SessionDep):
    return {"unread": notify.count(session, user.id)}


class ReadBody(_Body):
    ids: Optional[List[str]] = None
    all: bool = False


@router.post("/notifications/read")
def read_notifications(body: ReadBody, user: UserDep, session: SessionDep):
    n = notify.mark_read(session, user.id, None if body.all else (body.ids or []))
    return {"read": n, "unread": notify.count(session, user.id)}


# ── 피드백 ─────────────────────────────────────────────────────────────

class FeedbackBody(_Body):
    workspace_id: str = Field("", alias="workspaceId")
    target_kind: str = Field(alias="targetKind")
    target_id: str = Field(alias="targetId")
    thumbs: int = 0
    score: Optional[int] = None
    comment: str = ""


@router.post("/feedback")
def give_feedback(body: FeedbackBody, user: UserDep, session: SessionDep):
    return feedback.give(session, user.id, body.workspace_id, body.target_kind, body.target_id, body.thumbs, body.score, body.comment)


@router.get("/feedback")
def my_feedback(user: UserDep, session: SessionDep, kind: str = "answer", ids: str = ""):
    return {"thumbs": feedback.mine(session, user.id, kind, [i for i in ids.split(",") if i][:200])}


# ── 보내기·승인 ────────────────────────────────────────────────────────

class ShareBody(_Body):
    item_kind: str = Field(alias="itemKind")
    item_id: str = Field(alias="itemId")
    to: List[str] = Field(default_factory=list)
    message: str = ""
    review: bool = False


@router.post("/workspaces/{workspace_id}/shares")
def send_item(workspace_id: str, body: ShareBody, user: UserDep, session: SessionDep):
    return sharing.share(session, workspace_id, user, body.item_kind, body.item_id, body.to, body.message, body.review)


@router.get("/workspaces/{workspace_id}/shares/received")
def received_items(workspace_id: str, user: UserDep, session: SessionDep):
    return {"shares": sharing.received(session, workspace_id, user)}


class ApproveBody(_Body):
    note: str = ""


@router.post("/sessions/{session_id}/approve")
def approve_doc(session_id: str, user: UserDep, session: SessionDep, body: Optional[ApproveBody] = None):
    return {"approval": sharing.approve(session, session_id, user, (body.note if body else "") or "")}
