"""워크스페이스 — 만들기·목록·상세·설정·멤버(초대·역할·빼기). 권한은 auth.require_member 로 확인한다."""
from __future__ import annotations

import re
from typing import Any, Dict, List

from fastapi import HTTPException
from sqlmodel import Session

from app.auth import ROLES, require_member, user_view
from app.config import DEFAULT_OFF_HOUR
from app.db import Membership, Repo, User, Workspace, iso, utcnow
from app.ids import id36

WORKSPACE_KINDS: List[Dict[str, str]] = [
    {"id": "deal", "title": "투자 검토", "desc": "한 기업·딜의 자료로 투자 검토 리포트를 쓰고 검수합니다.", "reportType": "equity"},
    {"id": "quarterly", "title": "정기 점검", "desc": "분기 실적·보고서를 모아 변화를 점검합니다.", "reportType": "equity"},
    {"id": "regulation", "title": "규정 검토", "desc": "사내 규정·지침에서 근거 조항을 찾아 검토 메모를 씁니다.", "reportType": "memo"},
    {"id": "free", "title": "자유", "desc": "유형 없이 자료·리포트·검수를 모읍니다.", "reportType": "equity"},
]
_KIND_IDS = {k["id"] for k in WORKSPACE_KINDS}


def default_report_type(kind: str) -> str:
    return next((k["reportType"] for k in WORKSPACE_KINDS if k["id"] == kind), "equity")


def workspace_view(ws: Workspace) -> Dict[str, Any]:
    return {
        "id": ws.id,
        "name": ws.name,
        "kind": ws.kind,
        "description": ws.description,
        "settings": {"offHour": DEFAULT_OFF_HOUR, **(ws.settings or {})},
        "documentCount": len(ws.document_ids or []),
        "createdBy": ws.created_by,
        "createdAt": iso(ws.created_at),
        "updatedAt": iso(ws.updated_at),
    }


class WorkspaceService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = Repo(session)

    def list(self, user: User) -> List[Dict[str, Any]]:
        out = []
        for ws in self.repo.my_workspaces(user.id):
            m = self.repo.membership(ws.id, user.id)
            out.append({**workspace_view(ws), "role": m.role if m else "viewer", "members": len(self.repo.members(ws.id))})
        return out

    def create(self, user: User, name: str, kind: str = "free", description: str = "") -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise HTTPException(400, "워크스페이스 이름을 넣어 주세요.")
        kind = kind if kind in _KIND_IDS else "free"
        ws = Workspace(id=id36("w", 4), name=name[:80], kind=kind, description=(description or "").strip()[:400], created_by=user.id, settings={"offHour": DEFAULT_OFF_HOUR})
        self.repo.save(ws)
        self.repo.save(Membership(workspace_id=ws.id, user_id=user.id, role="owner", last_seen_at=utcnow()))
        return self.detail(ws.id, user)

    def detail(self, workspace_id: str, user: User) -> Dict[str, Any]:
        ws, me = require_member(self.session, workspace_id, user)
        members = []
        for m in self.repo.members(ws.id):
            u = self.repo.user(m.user_id)
            if u:
                members.append({"user": user_view(u), "role": m.role, "lastSeenAt": iso(m.last_seen_at)})
        return {
            "workspace": workspace_view(ws),
            "me": {"role": me.role, "lastSeenAt": iso(me.last_seen_at)},
            "members": members,
            "users": [user_view(u) for u in self.repo.users()],
        }

    def patch(self, workspace_id: str, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        ws, _m = require_member(self.session, workspace_id, user, "owner")
        if "name" in body and str(body["name"]).strip():
            ws.name = str(body["name"]).strip()[:80]
        if "description" in body:
            ws.description = str(body["description"] or "").strip()[:400]
        if isinstance(body.get("settings"), dict):
            settings = dict(ws.settings or {})
            s = body["settings"]
            if "offHour" in s:
                hh = str(s["offHour"]).strip()
                if not _valid_hhmm(hh):
                    raise HTTPException(400, "퇴근 시각은 HH:MM(예: 19:00) 으로 넣어 주세요.")
                settings["offHour"] = hh
            if isinstance(s.get("connectors"), dict):
                settings["connectors"] = {**(settings.get("connectors") or {}), **{k: bool(v) for k, v in s["connectors"].items()}}
            ws.settings = settings
        self.repo.save(ws)
        return self.detail(ws.id, user)

    # ── 멤버 ──────────────────────────────────────────────────────────
    def invite(self, workspace_id: str, user: User, user_id: str, role: str) -> Dict[str, Any]:
        ws, _m = require_member(self.session, workspace_id, user, "owner")
        if role not in ROLES:
            raise HTTPException(400, "모르는 역할입니다.")
        target = self.repo.user(user_id)
        if target is None:
            raise HTTPException(404, "그런 사용자가 없습니다.")
        existing = self.repo.membership(ws.id, user_id)
        if existing:
            existing.role = role
            self.repo.save(existing)
        else:
            self.repo.save(Membership(workspace_id=ws.id, user_id=user_id, role=role))
        self.repo.save(ws)
        return self.detail(ws.id, user)

    def set_role(self, workspace_id: str, user: User, user_id: str, role: str) -> Dict[str, Any]:
        ws, _m = require_member(self.session, workspace_id, user, "owner")
        if role not in ROLES:
            raise HTTPException(400, "모르는 역할입니다.")
        m = self.repo.membership(ws.id, user_id)
        if m is None:
            raise HTTPException(404, "멤버가 아닙니다.")
        if m.role == "owner" and role != "owner" and self._owner_count(ws.id) <= 1:
            raise HTTPException(409, "소유자가 한 명은 있어야 합니다.")
        m.role = role
        self.repo.save(m)
        return self.detail(ws.id, user)

    def remove_member(self, workspace_id: str, user: User, user_id: str) -> Dict[str, Any]:
        ws, _m = require_member(self.session, workspace_id, user, "owner")
        m = self.repo.membership(ws.id, user_id)
        if m is None:
            raise HTTPException(404, "멤버가 아닙니다.")
        if m.role == "owner" and self._owner_count(ws.id) <= 1:
            raise HTTPException(409, "소유자가 한 명은 있어야 합니다.")
        self.repo.delete(m)
        return self.detail(ws.id, user)

    def _owner_count(self, workspace_id: str) -> int:
        return sum(1 for m in self.repo.members(workspace_id) if m.role == "owner")


def _valid_hhmm(s: str) -> bool:
    return bool(re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", s))
