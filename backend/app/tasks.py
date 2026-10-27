"""작업 항목 — 담당·기한·상태(할 일 → 진행 → 검토 → 완료). 검수 지적·할 일 기록에서 만들어지고, 직접도 만든다.

권한: 만들기·지우기 = 편집자 이상(검수 지적에서 만드는 것은 검토자 이상 — review/service.py), 상태 바꾸기 = 담당자 본인 또는 편집자 이상.
사내 업무관리 툴(Jira 등)과 연동할 때는 이 모듈이 바꿔 끼우는 자리다.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import ROLE_RANK, require_member
from app.db import Repo, Task, User, iso
from app.ids import id36

STATUSES = ("todo", "doing", "review", "done")


def norm_dates(start: str, due: str) -> tuple[str, str]:
    """기간(시작~마감) 정리 — 시작만 있으면 마감도 그날, 뒤바뀌면 바로잡는다. 시작이 마감과 같으면 시작은 비운다(하루짜리)."""
    start, due = (start or "")[:10], (due or "")[:10]
    if start and not due:
        due = start
    if start and start > due:
        start, due = due, start
    return ("" if start == due else start), due


def task_view(t: Task) -> Dict[str, Any]:
    return {
        "id": t.id,
        "title": t.title,
        "detail": t.detail,
        "assigneeId": t.assignee_id,
        "due": t.due,
        "start": t.start or "",
        "status": t.status,
        "source": t.source or {},
        "createdBy": t.created_by,
        "createdAt": iso(t.created_at),
        "updatedAt": iso(t.updated_at),
    }


class TaskService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = Repo(session)

    def listing(self, workspace_id: str, user: User) -> Dict[str, Any]:
        require_member(self.session, workspace_id, user)
        rows = self.session.exec(select(Task).where(Task.workspace_id == workspace_id).order_by(Task.created_at.desc())).all()  # type: ignore[attr-defined]
        return {"tasks": [task_view(t) for t in rows]}

    def create(self, workspace_id: str, user: User, title: str, detail: str = "", assignee_id: Optional[str] = None, due: str = "", start: str = "") -> Dict[str, Any]:
        require_member(self.session, workspace_id, user, "editor")
        if not (title or "").strip():
            raise HTTPException(400, "작업 제목을 넣어 주세요.")
        if assignee_id and self.repo.membership(workspace_id, assignee_id) is None:
            raise HTTPException(400, "담당자는 워크스페이스 멤버여야 합니다.")
        start, due = norm_dates(start, due)
        self.repo.save(Task(id=id36("t", 4), workspace_id=workspace_id, title=title.strip()[:160], detail=(detail or "")[:1000], assignee_id=assignee_id or None, due=due, start=start, status="todo", source={"kind": "manual"}, created_by=user.id))
        return self.listing(workspace_id, user)

    def update(self, workspace_id: str, user: User, task_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        _ws, m = require_member(self.session, workspace_id, user, "reviewer")
        t = self.session.get(Task, task_id)
        if t is None or t.workspace_id != workspace_id:
            raise HTTPException(404, "작업 항목이 없습니다.")
        editor = ROLE_RANK.get(m.role, 0) >= ROLE_RANK["editor"]
        if not editor and t.assignee_id != user.id:
            raise HTTPException(403, "담당자 본인이나 편집자 이상만 바꿀 수 있습니다.")
        if "status" in body:
            if body["status"] not in STATUSES:
                raise HTTPException(400, "모르는 상태입니다.")
            t.status = body["status"]
        if editor:
            if "assigneeId" in body:
                a = body["assigneeId"] or None
                if a and self.repo.membership(workspace_id, a) is None:
                    raise HTTPException(400, "담당자는 워크스페이스 멤버여야 합니다.")
                t.assignee_id = a
            if "due" in body or "start" in body:
                t.start, t.due = norm_dates(str(body.get("start", t.start) or ""), str(body.get("due", t.due) or ""))
            if "title" in body and str(body["title"]).strip():
                t.title = str(body["title"]).strip()[:160]
            if "detail" in body:
                t.detail = str(body["detail"] or "")[:1000]
        self.repo.save(t)
        return self.listing(workspace_id, user)

    def delete(self, workspace_id: str, user: User, task_id: str) -> Dict[str, Any]:
        require_member(self.session, workspace_id, user, "editor")
        t = self.session.get(Task, task_id)
        if t is None or t.workspace_id != workspace_id:
            raise HTTPException(404, "작업 항목이 없습니다.")
        self.repo.delete(t)
        return self.listing(workspace_id, user)
