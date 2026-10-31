"""루틴 관리 — 목록(워크스페이스 멤버 모두 보기)·등록(편집자 이상)·고치기·지우기(만든 사람이나 관리자)·실행 기록."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import require_member
from app.db import ReportSession, Routine, RoutineRun, User, iso, utcnow
from app.ids import id36
from app.routines.runner import manual_left, next_run, run_view

EVERY = ("daily", "weekdays", "weekly", "manual")


def _schedule(raw: Dict[str, Any]) -> Dict[str, Any]:
    every = raw.get("every") if raw.get("every") in EVERY else "daily"
    t = str(raw.get("time") or (raw.get("times") or ["07:00"])[0] or "07:00")[:5]
    out = {"every": every, "time": t if len(t) == 5 and t[2] == ":" else "07:00"}
    if every == "weekly":
        out["weekday"] = int(raw.get("weekday") or 0) % 7
    return out


class RoutineService:
    def __init__(self, session: Session):
        self.s = session

    def _row(self, routine_id: str, user: User, write: bool = False) -> Routine:
        r = self.s.get(Routine, routine_id)
        if r is None:
            raise HTTPException(404, "루틴을 찾지 못했습니다.")
        _ws, m = require_member(self.s, r.workspace_id, user, "editor" if write else "viewer")
        if write and r.owner_id != user.id and m.role != "owner":
            raise HTTPException(403, "루틴은 만든 사람이나 관리자가 바꿉니다.")
        return r

    def view(self, r: Routine, user: User) -> Dict[str, Any]:
        from app.agent.template import report_type
        from app.scheduler import local_now

        last = self.s.exec(select(RoutineRun).where(RoutineRun.routine_id == r.id).order_by(RoutineRun.started_at.desc())).first()
        owner = self.s.get(User, r.owner_id)
        try:
            fmt_title = report_type(r.format_id)["title"] if r.format_id else ""
        except Exception:  # noqa: BLE001
            fmt_title = ""
        return {"id": r.id, "name": r.name, "call": r.call, "formatId": r.format_id, "formatTitle": fmt_title, "dataScope": r.data_scope or {}, "instruction": r.instruction,
                "schedule": r.schedule or {}, "folderId": r.folder_id, "titlePattern": r.title_pattern, "recipients": r.recipients or {}, "reviewerId": r.reviewer_id,
                "owner": {"id": r.owner_id, "name": f"{owner.name} {owner.title}".strip() if owner else ""}, "enabled": r.enabled, "source": r.source or {},
                "lastRunAt": iso(r.last_run_at), "nextRunAt": next_run(r, local_now()), "lastRun": run_view(last) if last else None, "manualLeft": manual_left(r.id),
                "canEdit": r.owner_id == user.id or require_member(self.s, r.workspace_id, user)[1].role == "owner"}

    def listing(self, workspace_id: str, user: User) -> List[Dict[str, Any]]:
        require_member(self.s, workspace_id, user)
        rows = self.s.exec(select(Routine).where(Routine.workspace_id == workspace_id).order_by(Routine.created_at)).all()
        return [self.view(r, user) for r in rows]

    def _apply(self, r: Routine, b: Dict[str, Any]) -> None:
        if "name" in b:
            r.name = str(b.get("name") or "루틴").strip()[:60] or "루틴"
        if "call" in b or not r.call:
            c = str(b.get("call") or "").strip() or f"/{r.name}"
            r.call = (c if c.startswith("/") else f"/{c}")[:40]
        if "formatId" in b:
            r.format_id = str(b.get("formatId") or "")
        if "dataScope" in b:
            r.data_scope = b.get("dataScope") or {}
        if "instruction" in b:
            r.instruction = str(b.get("instruction") or "")[:2000]
        if "schedule" in b:
            r.schedule = _schedule(b.get("schedule") or {})
        if "folderId" in b:
            r.folder_id = b.get("folderId") or None
        if "titlePattern" in b:
            r.title_pattern = str(b.get("titlePattern") or "{name} {date}")[:80]
        if "recipients" in b:
            rc = b.get("recipients") or {}
            r.recipients = {"all": bool(rc.get("all")), "userIds": [str(x) for x in rc.get("userIds") or []][:30]}
        if "reviewerId" in b:
            r.reviewer_id = b.get("reviewerId") or None
        if "enabled" in b:
            r.enabled = bool(b.get("enabled"))

    def create(self, workspace_id: str, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        require_member(self.s, workspace_id, user, "editor")
        r = Routine(id=id36("rt", 4), workspace_id=workspace_id, owner_id=user.id, source=body.get("source") or {"kind": "manual"})
        if not body.get("formatId") and (body.get("source") or {}).get("sessionId"):
            row = self.s.get(ReportSession, body["source"]["sessionId"])  # 끝낸 작업에서 '루틴으로 저장' — 그 작업의 양식·범위
            if row and row.workspace_id == workspace_id:
                body = {**body, "formatId": row.report_type, "dataScope": body.get("dataScope") or (row.doc or {}).get("dataScope") or {}}
        self._apply(r, {"schedule": {}, **body})
        if not r.format_id:
            raise HTTPException(400, "루틴에 쓸 문서 양식을 고르세요.")
        self.s.add(r)
        self.s.commit()
        return self.view(r, user)

    def update(self, routine_id: str, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        r = self._row(routine_id, user, write=True)
        self._apply(r, body)
        r.updated_at = utcnow()
        self.s.add(r)
        self.s.commit()
        return self.view(r, user)

    def delete(self, routine_id: str, user: User) -> None:
        """루틴만 지운다 — 이미 쓴 문서는 드라이브에 그대로."""
        r = self._row(routine_id, user, write=True)
        self.s.delete(r)
        self.s.commit()

    def runs(self, routine_id: str, user: User) -> List[Dict[str, Any]]:
        self._row(routine_id, user)
        rows = self.s.exec(select(RoutineRun).where(RoutineRun.routine_id == routine_id).order_by(RoutineRun.started_at.desc()).limit(20)).all()
        return [run_view(x) for x in rows]

    def check_run(self, routine_id: str, user: User) -> Routine:
        r = self._row(routine_id, user, write=True)
        if manual_left(r.id) <= 0:
            raise HTTPException(429, "오늘은 이 루틴을 더 돌릴 수 없습니다(하루 상한).")
        return r
