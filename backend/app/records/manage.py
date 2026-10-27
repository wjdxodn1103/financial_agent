"""팀 기록 관리 — 후보 확인·버리기, 직접 남기기, 배치 지금 실행(소유자), 실행 기록.

확인 권한: 발언자 본인 또는 소유자(남의 말을 대신 확정하지 않는다). 할 일(todo) 기록을 확정하면 작업 항목도 만든다.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import require_member
from app.db import BatchRun, Repo, Task, TeamRecord, User, iso, utcnow
from app.ids import id36
from app.records.digest import JOB, run_digest, run_view
from app.records.service import RECORD_TYPES


def record_view(r: TeamRecord, names: Dict[str, str]) -> Dict[str, Any]:
    return {
        "id": r.id,
        "type": r.type,
        "typeKo": RECORD_TYPES.get(r.type, r.type),
        "text": r.text,
        "quotes": r.quotes or [],
        "authorId": r.author_id,
        "author": names.get(r.author_id or "", ""),
        "scope": r.scope,
        "status": r.status,
        "source": r.source or {},
        "batchId": r.batch_id,
        "confirmedBy": names.get(r.confirmed_by or "", ""),
        "confirmedAt": iso(r.confirmed_at),
        "createdAt": iso(r.created_at),
    }


class RecordService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = Repo(session)

    def _names(self) -> Dict[str, str]:
        return {u.id: f"{u.name} {u.title}".strip() for u in self.repo.users()}

    def listing(self, workspace_id: str, user: User, status: Optional[str] = None) -> Dict[str, Any]:
        from app.scheduler import next_run_at

        ws, m = require_member(self.session, workspace_id, user)
        q = select(TeamRecord).where(TeamRecord.workspace_id == workspace_id)
        if status:
            q = q.where(TeamRecord.status == status)
        rows = self.session.exec(q.order_by(TeamRecord.created_at.desc())).all()  # type: ignore[attr-defined]
        names = self._names()
        runs = self.session.exec(select(BatchRun).where(BatchRun.workspace_id == workspace_id, BatchRun.job == JOB).order_by(BatchRun.started_at.desc()).limit(5)).all()  # type: ignore[attr-defined]
        return {
            "records": [{**record_view(r, names), "canConfirm": r.status == "candidate" and (r.author_id == user.id or m.role == "owner")} for r in rows],
            "runs": [run_view(r) for r in runs],
            "nextRunAt": next_run_at(ws),
            "offHour": (ws.settings or {}).get("offHour"),
        }

    def _owned(self, workspace_id: str, user: User, record_id: str) -> TeamRecord:
        _ws, m = require_member(self.session, workspace_id, user, "reviewer")
        r = self.session.get(TeamRecord, record_id)
        if r is None or r.workspace_id != workspace_id:
            raise HTTPException(404, "기록이 없습니다.")
        if r.author_id != user.id and m.role != "owner":
            raise HTTPException(403, "기록 후보는 발언자 본인이나 소유자만 확인할 수 있습니다.")
        return r

    def confirm(self, workspace_id: str, user: User, record_id: str, text: Optional[str] = None) -> Dict[str, Any]:
        r = self._owned(workspace_id, user, record_id)
        if text and text.strip():
            r.text = text.strip()[:300]
        r.status, r.confirmed_by, r.confirmed_at = "confirmed", user.id, utcnow()
        self.repo.save(r)
        task = None
        if r.type == "todo":
            src = r.source or {}
            t = Task(id=id36("t", 4), workspace_id=workspace_id, title=r.text[:160], detail="\n".join(f"{q.get('author')}: {q.get('text')}" for q in r.quotes or [])[:1000], assignee_id=src.get("assigneeId"), due=src.get("due") or "", status="todo", source={"kind": "record", "recordId": r.id}, created_by=user.id)
            self.repo.save(t)
            task = t.id
        out = self.listing(workspace_id, user)
        out["taskId"] = task
        return out

    def dismiss(self, workspace_id: str, user: User, record_id: str) -> Dict[str, Any]:
        r = self._owned(workspace_id, user, record_id)
        r.status = "dismissed"
        self.repo.save(r)
        return self.listing(workspace_id, user)

    def add(self, workspace_id: str, user: User, type_: str, text: str, scope: str = "") -> Dict[str, Any]:
        """직접 남기는 기록 — 본인이 쓴 것이라 바로 확정(행동은 즉시 기록)."""
        require_member(self.session, workspace_id, user, "reviewer")
        if type_ not in RECORD_TYPES or not (text or "").strip():
            raise HTTPException(400, "기록 종류와 내용을 넣어 주세요.")
        now = utcnow()
        self.repo.save(
            TeamRecord(
                id=id36("k", 4),
                workspace_id=workspace_id,
                type=type_,
                text=text.strip()[:300],
                quotes=[{"messageId": None, "userId": user.id, "author": f"{user.name} {user.title}".strip(), "text": text.strip()[:300], "at": iso(now)}],
                author_id=user.id,
                scope=(scope or "").strip()[:80],
                status="confirmed",
                source={"kind": "manual"},
                confirmed_by=user.id,
                confirmed_at=now,
            )
        )
        return self.listing(workspace_id, user)

    async def run_now(self, workspace_id: str, user: User) -> Dict[str, Any]:
        """소유자 전용 — 퇴근 시각을 기다리지 않고 지금 배치를 돌린다(데모·테스트)."""
        require_member(self.session, workspace_id, user, "owner")
        run = await run_digest(workspace_id, trigger="manual")
        out = self.listing(workspace_id, user)
        out["run"] = run
        return out

