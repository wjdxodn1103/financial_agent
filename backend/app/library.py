"""공용 자료실 — 조직이 같이 쓰는 자료 선반. 워크스페이스 자료를 올려 두면 다른 워크스페이스가 **골라 붙여야** 쓴다.

원칙 유지: 검색·원장·리포트는 언제나 워크스페이스에 붙은 자료만 본다. 자료실은 검색 범위가 아니라 고르는 곳이다.
(데모에서는 로그인한 사람 모두가 자료실을 본다 — 기관 맞춤 때 부서·보안 등급별 열람 범위를 여기서 건다.)
올림·붙임 = 편집자 이상(그 워크스페이스에서). 내리기 = 올린 사람.
자료는 판(버전)과 무관하게 올린 그 파일 그대로다 — 원래 워크스페이스에서 새 판이 나와도 자료실 것은 바뀌지 않는다.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import require_member
from app.db import LibraryItem, Repo, User, iso
from app.docs.store import document_cards
from app.ids import id36
from app.services.document_service import attach_document


def library_map(session: Session) -> Dict[str, Dict[str, Any]]:
    """doc_id → 자료실 항목(자료 카드에 '공용' 표시용)."""
    names = {u.id: u.name for u in session.exec(select(User)).all()}
    return {r.doc_id: {"id": r.id, "publishedBy": names.get(r.published_by, "")} for r in session.exec(select(LibraryItem)).all()}


class LibraryService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = Repo(session)

    def listing(self, user: User, q: str = "", workspace_id: Optional[str] = None) -> Dict[str, Any]:
        active = set()
        if workspace_id:
            ws, _m = require_member(self.session, workspace_id, user)
            active = set(ws.document_ids or [])
        names = {u.id: f"{u.name} {u.title}".strip() for u in self.repo.users()}
        rows = list(self.session.exec(select(LibraryItem).order_by(LibraryItem.created_at.desc())).all())  # type: ignore[attr-defined]
        cards = {c["id"]: c for c in document_cards([r.doc_id for r in rows])}
        words = [w.lower() for w in (q or "").split() if w]
        out: List[Dict[str, Any]] = []
        for r in rows:
            c = cards.get(r.doc_id)
            if c is None:
                continue
            hay = f"{c['label']} {c['fileName']} {c['docType']} {c['issuer']} {c['company']} {r.note}".lower()
            if words and not all(w in hay for w in words):
                continue
            src = self.repo.workspace(r.from_workspace_id)
            out.append({"id": r.id, "docId": r.doc_id, "card": c, "note": r.note, "publishedBy": names.get(r.published_by, ""), "publishedById": r.published_by, "from": src.name if src else "", "at": iso(r.created_at), "attached": r.doc_id in active})
        return {"items": out}

    def publish(self, workspace_id: str, user: User, doc_id: str, note: str = "") -> Dict[str, Any]:
        ws, _m = require_member(self.session, workspace_id, user, "editor")
        if doc_id not in (ws.document_ids or []):
            raise HTTPException(404, "이 워크스페이스의 자료가 아닙니다.")
        row = self.session.exec(select(LibraryItem).where(LibraryItem.doc_id == doc_id)).first()
        if row is None:
            row = LibraryItem(id=id36("l", 4), doc_id=doc_id, note=note.strip()[:300], published_by=user.id, from_workspace_id=ws.id)
        else:
            row.note = note.strip()[:300] or row.note
        self.repo.save(row)
        return self.listing(user, workspace_id=workspace_id)

    def unpublish(self, user: User, item_id: str, workspace_id: Optional[str] = None) -> Dict[str, Any]:
        row = self.session.get(LibraryItem, item_id)
        if row is None:
            raise HTTPException(404, "자료실 항목이 없습니다.")
        if row.published_by != user.id:
            raise HTTPException(403, "올린 사람만 자료실에서 내릴 수 있습니다(이미 붙인 워크스페이스의 자료는 그대로 남습니다).")
        self.repo.delete(row)
        return self.listing(user, workspace_id=workspace_id)

    def attach(self, workspace_id: str, user: User, item_id: str) -> Dict[str, Any]:
        ws, _m = require_member(self.session, workspace_id, user, "editor")
        row = self.session.get(LibraryItem, item_id)
        if row is None:
            raise HTTPException(404, "자료실 항목이 없습니다.")
        if row.doc_id in (ws.document_ids or []):
            raise HTTPException(409, "이미 이 워크스페이스에 붙어 있습니다.")
        attach_document(self.session, ws.id, row.doc_id)
        return self.listing(user, workspace_id=workspace_id)


__all__ = ["LibraryService", "library_map"]
