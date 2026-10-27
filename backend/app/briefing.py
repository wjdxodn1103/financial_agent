"""접속 브리핑 — "지난 접속 이후" 바뀐 것을 결정적으로 모은다(LLM 0회). 홈 화면이 열 때 부른다.
방문 단위: 마지막 활동에서 VISIT_GAP 넘게 지나 다시 오면 새 방문 — 기준 시각(visit_since)을 직전 방문의 마지막 시각으로 바꾼다.
같은 방문 안에서 홈을 다시 열어도(새로고침·화면 이동) 기준은 그대로라 방금 본 소식이 사라지지 않는다.

 - 확인을 기다리는 기록 후보(내 발언이거나 내가 소유자) · 새로 확정된 팀 기록(원문 인용 그대로)
 - 나를 부른 채널 메시지(@이름) · 내 작업 항목(안 끝난 것) · 끝난 검수 · 새 자료 · 바뀐 리포트 · 마지막 기록 배치
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.auth import require_member
from app.db import BatchRun, ChannelMessage, IngestJob, ReportSession, Review, Task, TeamRecord, User, iso, utcnow
from app.docs.store import doc_label, load_meta
from app.records.digest import JOB, run_view
from app.records.service import RECORD_TYPES

VISIT_GAP = timedelta(minutes=30)


def briefing(session: Session, workspace_id: str, user: User) -> Dict[str, Any]:
    ws, m = require_member(session, workspace_id, user)
    now = utcnow()
    if m.last_seen_at is not None and now - m.last_seen_at > VISIT_GAP:
        m.visit_since = m.last_seen_at  # 새 방문
    since: Optional[datetime] = m.visit_since
    names = {u.id: f"{u.name} {u.title}".strip() for u in session.exec(select(User)).all()}

    def after(t: Optional[datetime]) -> bool:
        return t is not None and (since is None or t > since)

    recs = session.exec(select(TeamRecord).where(TeamRecord.workspace_id == workspace_id)).all()
    pending = [r for r in recs if r.status == "candidate" and (r.author_id == user.id or m.role == "owner")]
    confirmed = [r for r in recs if r.status == "confirmed" and after(r.confirmed_at) and r.confirmed_by != user.id]

    def rec(r: TeamRecord) -> Dict[str, Any]:
        q = (r.quotes or [{}])[0]
        return {"id": r.id, "type": r.type, "typeKo": RECORD_TYPES.get(r.type, r.type), "text": r.text, "author": names.get(r.author_id or "", ""), "quote": q.get("text") or "", "at": q.get("at") or iso(r.created_at)}

    mentions = [
        {"id": x.id, "author": names.get(x.user_id or "", ""), "text": x.text[:160], "at": iso(x.created_at)}
        for x in session.exec(select(ChannelMessage).where(ChannelMessage.workspace_id == workspace_id, ChannelMessage.kind == "user")).all()
        if user.id in ((x.meta or {}).get("mentions") or []) and after(x.created_at)
    ]
    my_tasks = [{"id": t.id, "title": t.title, "due": t.due, "status": t.status} for t in session.exec(select(Task).where(Task.workspace_id == workspace_id, Task.assignee_id == user.id)).all() if t.status != "done"]
    reviews = [
        {"id": r.id, "docLabel": doc_label(load_meta(r.doc_id), r.doc_id), "by": names.get(r.created_by, ""), "counts": (r.summary or {}).get("counts") or {}}
        for r in session.exec(select(Review).where(Review.workspace_id == workspace_id, Review.status == "done")).all()
        if after(r.finished_at) and r.created_by != user.id
    ]
    docs: List[Dict[str, Any]] = []
    for j in session.exec(select(IngestJob).where(IngestJob.workspace_id == workspace_id, IngestJob.status == "done")).all():
        if after(j.created_at) and j.uploaded_by != user.id and j.doc_id in (ws.document_ids or []):
            docs.append({"id": j.doc_id, "label": doc_label(load_meta(j.doc_id or ""), j.doc_id or ""), "by": names.get(j.uploaded_by, "")})
    reports = [
        {"id": r.id, "title": r.title or "제목 없는 리포트", "by": names.get(r.created_by, ""), "written": r.written}
        for r in session.exec(select(ReportSession).where(ReportSession.workspace_id == workspace_id)).all()
        if after(r.updated_at) and r.created_by != user.id
    ]
    last = session.exec(select(BatchRun).where(BatchRun.workspace_id == workspace_id, BatchRun.job == JOB).order_by(BatchRun.started_at.desc())).first()  # type: ignore[attr-defined]
    out = {
        "since": iso(since),
        "pendingRecords": [rec(r) for r in pending],
        "newRecords": [rec(r) for r in confirmed],
        "mentions": mentions[-10:],
        "myTasks": my_tasks,
        "reviews": reviews,
        "documents": docs,
        "reports": reports,
        "lastRun": run_view(last) if last else None,
    }
    m.last_seen_at = now
    session.add(m)
    session.commit()
    return out
