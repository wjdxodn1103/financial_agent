"""마이페이지(워크스페이스 홈) — 이 워크스페이스에서 '나'의 할 일·일정, 받은/보낸 검토 요청, 내가 만든 문서, 내가 한 일을 한 번에(LLM 없음).

 - 할 일 = 작업 항목(Task) 중 나에게 배정된 직접 등록 항목(source.kind=manual). 기간(start~due)이 일정이 된다.
 - 검토 요청 = 리포트 검토 요청이 만든 작업(source.kind=report) — 받은 것은 내가 담당, 보낸 것은 내가 만든 것.
 - 내가 한 일 = 내 리포트 수정·데이터 업로드·검수·검토 요청·끝낸 할 일을 시각순으로.
할 일 등록·완료·삭제는 역할과 상관없이 자기 것만(작업 항목 화면의 편집자 규칙과 따로 — 개인 할 일이라서).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import ROLE_RANK, require_member
from app.db import IngestJob, Repo, Review, Task, User, iso
from app.docs.store import doc_label, load_meta
from app.agent.modes import has_doc
from app.ids import id36
from app.tasks import norm_dates

ACTIVITY_MAX = 20


def _kind(t: Task) -> str:
    return (t.source or {}).get("kind") or "manual"


def _written_at(r: Any) -> Optional[str]:
    """실제로 쓰거나 고친 마지막 시각(섹션 기록) — 검토 요청·데이터 선택처럼 본문을 안 바꾼 저장은 치지 않는다."""
    stamps = [line[:16] for lines in ((r.doc or {}).get("sectionLog") or {}).values() for line in lines if line[:4].isdigit()]
    return f"{max(stamps)}:00Z" if stamps else None


def my_page(session: Session, workspace_id: str, user: User) -> Dict[str, Any]:
    _ws, m = require_member(session, workspace_id, user)
    repo = Repo(session)
    names = {u.id: f"{u.name} {u.title}".strip() for u in repo.users()}
    tasks = list(session.exec(select(Task).where(Task.workspace_id == workspace_id)))
    reports = {r.id: r for r in repo.reports(workspace_id)}

    def title_of(report_id: Optional[str]) -> str:
        r = reports.get(report_id or "")
        return (r.title if r else "") or "제목 없는 리포트"

    todos = [
        {"id": t.id, "title": t.title, "due": t.due, "start": t.start or "", "status": t.status, "done": t.status == "done", "createdAt": iso(t.created_at), "updatedAt": iso(t.updated_at)}
        for t in tasks
        if t.assignee_id == user.id and _kind(t) == "manual"
    ]

    def request(t: Task, person: Optional[str]) -> Dict[str, Any]:
        rid = (t.source or {}).get("reportId")
        r = reports.get(rid or "")
        req = ((r.doc if r else None) or {}).get("reviewRequest") or {}
        note = str(req.get("note") or "") if req.get("taskId") == t.id else ""  # 요청 메모(같은 검토 작업의 것만)
        return {"taskId": t.id, "reportId": rid, "title": title_of(rid), "person": names.get(person or "", ""), "done": t.status == "done", "at": iso(t.created_at), "updatedAt": iso(t.updated_at), "note": note}

    asked = [t for t in tasks if _kind(t) == "report"]
    received = [request(t, t.created_by) for t in asked if t.assignee_id == user.id]
    sent = [request(t, t.assignee_id) for t in asked if t.created_by == user.id]

    documents = []
    for r in reports.values():
        if r.created_by != user.id or not has_doc(r.doc or {}):
            continue
        req = (r.doc or {}).get("reviewRequest") or {}
        task = next((t for t in asked if t.id == req.get("taskId")), None)
        documents.append(
            {
                "id": r.id,
                "title": r.title or "제목 없는 리포트",
                "reportType": r.report_type,
                "written": r.written,
                "sections": len((r.doc or {}).get("sections") or []),
                "updatedAt": _written_at(r) or iso(r.created_at),
                "review": {"person": names.get(req.get("reviewerId") or "", ""), "done": task is not None and task.status == "done"} if req else None,
            }
        )

    activity: List[Dict[str, Any]] = []
    for r in reports.values():
        at = _written_at(r) if r.created_by == user.id else None
        if at:
            activity.append({"kind": "write", "title": r.title or "제목 없는 리포트", "at": at, "reportId": r.id})
    for j in repo.jobs(workspace_id):
        if j.uploaded_by == user.id and j.status == "done" and j.doc_id:
            activity.append({"kind": "upload", "title": doc_label(load_meta(j.doc_id), j.doc_id), "at": iso(j.created_at)})
    for rv in session.exec(select(Review).where(Review.workspace_id == workspace_id, Review.created_by == user.id)):
        activity.append({"kind": "review", "title": doc_label(load_meta(rv.doc_id), rv.doc_id), "at": iso(rv.created_at)})
    for t in asked:
        if t.created_by == user.id:
            activity.append({"kind": "request", "title": title_of((t.source or {}).get("reportId")), "person": names.get(t.assignee_id or "", ""), "at": iso(t.created_at), "reportId": (t.source or {}).get("reportId")})
    for t in tasks:
        if t.assignee_id == user.id and t.status == "done" and _kind(t) in ("manual", "report"):
            activity.append({"kind": "done", "title": t.title, "at": iso(t.updated_at)})
    activity.sort(key=lambda a: a["at"] or "", reverse=True)

    reviewers = [{"id": mm.user_id, "name": names.get(mm.user_id, "")} for mm in repo.members(workspace_id) if mm.user_id != user.id and ROLE_RANK.get(mm.role, 0) >= ROLE_RANK["reviewer"]]
    return {
        "me": {"id": user.id, "name": user.name, "title": user.title, "role": m.role},
        "todos": todos,
        "received": received,
        "sent": sent,
        "documents": sorted(documents, key=lambda d: d["updatedAt"] or "", reverse=True),
        "activity": activity[:ACTIVITY_MAX],
        "reviewers": reviewers,
    }


def add_todo(session: Session, workspace_id: str, user: User, title: str, due: str = "", start: str = "") -> Dict[str, Any]:
    require_member(session, workspace_id, user)
    if not (title or "").strip():
        raise HTTPException(400, "할 일을 넣어 주세요.")
    start, due = norm_dates(start, due)
    Repo(session).save(Task(id=id36("t", 4), workspace_id=workspace_id, title=title.strip()[:160], assignee_id=user.id, due=due, start=start, status="todo", source={"kind": "manual"}, created_by=user.id))
    return my_page(session, workspace_id, user)


def _mine(session: Session, workspace_id: str, user: User, task_id: str) -> Task:
    require_member(session, workspace_id, user)
    t = session.get(Task, task_id)
    if t is None or t.workspace_id != workspace_id or t.assignee_id != user.id:
        raise HTTPException(404, "내 할 일이 아닙니다.")
    return t


def update_mine(session: Session, workspace_id: str, user: User, task_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """내게 배정된 항목(할 일·받은 검토 요청) — 끝냄/되돌림, 할 일이면 제목·기한도."""
    t = _mine(session, workspace_id, user, task_id)
    if "done" in body:
        t.status = "done" if body["done"] else "todo"
    if _kind(t) == "manual":
        if "due" in body or "start" in body:
            t.start, t.due = norm_dates(str(body.get("start", t.start) or ""), str(body.get("due", t.due) or ""))
        if str(body.get("title") or "").strip():
            t.title = str(body["title"]).strip()[:160]
    Repo(session).save(t)
    return my_page(session, workspace_id, user)


def delete_todo(session: Session, workspace_id: str, user: User, task_id: str) -> Dict[str, Any]:
    t = _mine(session, workspace_id, user, task_id)
    if _kind(t) != "manual":
        raise HTTPException(400, "직접 등록한 할 일만 지울 수 있습니다.")
    Repo(session).delete(t)
    return my_page(session, workspace_id, user)
