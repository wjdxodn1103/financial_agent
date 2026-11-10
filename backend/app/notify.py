"""알림함 — 루틴 결과·받은 문서·검토 요청·가정 판정 변화·수집 실패를 받는 사람에게 한 줄씩.

밖(메일·메신저)으로는 보내지 않는다 — 앱 안 알림만. 사내 메신저 연동은 `deliver` 자리에 붙인다.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from sqlmodel import Session, select

from app.db import Membership, Notification, engine, iso, utcnow
from app.ids import id36

KINDS = ("routine", "share", "review", "assumption", "source", "dashboard", "calendar", "proposal", "criteria", "system")


def notify(user_ids: Iterable[str], *, title: str, workspace_id: str = "", kind: str = "system", body: str = "", link: Optional[Dict[str, Any]] = None,
           ref: Optional[Dict[str, Any]] = None, dedupe_key: Optional[str] = None, exclude: Iterable[str] = (), session: Optional[Session] = None) -> int:
    """받는 사람마다 한 줄. dedupe_key 가 같은 알림이 이미 있으면 그 사람에게는 건너뛴다. → 만든 수."""
    skip = set(exclude)
    targets = [u for u in dict.fromkeys(user_ids) if u and u not in skip]
    if not targets:
        return 0
    own = session is None
    s = session or Session(engine)
    try:
        made = 0
        for uid in targets:
            if dedupe_key and s.exec(select(Notification.id).where(Notification.user_id == uid, Notification.dedupe_key == dedupe_key)).first():
                continue
            s.add(Notification(id=id36("n", 5), user_id=uid, workspace_id=workspace_id, kind=kind if kind in KINDS else "system", title=title[:200], body=body[:600], link=link or {}, ref=ref or {}, dedupe_key=dedupe_key))
            made += 1
        if own:
            s.commit()
        return made
    finally:
        if own:
            s.close()


def member_ids(workspace_id: str, session: Optional[Session] = None) -> List[str]:
    own = session is None
    s = session or Session(engine)
    try:
        return [m.user_id for m in s.exec(select(Membership).where(Membership.workspace_id == workspace_id)).all()]
    finally:
        if own:
            s.close()


def notify_members(workspace_id: str, **kw: Any) -> int:
    return notify(member_ids(workspace_id), workspace_id=workspace_id, **kw)


def view(n: Notification) -> Dict[str, Any]:
    return {"id": n.id, "workspaceId": n.workspace_id, "kind": n.kind, "title": n.title, "body": n.body, "link": n.link or {}, "ref": n.ref or {}, "createdAt": iso(n.created_at), "read": n.read_at is not None}


def listing(session: Session, user_id: str, unread_only: bool = False, limit: int = 30) -> Dict[str, Any]:
    q = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        q = q.where(Notification.read_at == None)  # noqa: E711
    rows = session.exec(q.order_by(Notification.created_at.desc()).limit(max(1, min(limit, 100)))).all()
    return {"items": [view(n) for n in rows], "unread": count(session, user_id)}


def count(session: Session, user_id: str) -> int:
    return len(session.exec(select(Notification.id).where(Notification.user_id == user_id, Notification.read_at == None)).all())  # noqa: E711


def mark_read(session: Session, user_id: str, ids: Optional[List[str]] = None) -> int:
    q = select(Notification).where(Notification.user_id == user_id, Notification.read_at == None)  # noqa: E711
    if ids:
        q = q.where(Notification.id.in_(ids))  # type: ignore[attr-defined]
    now = utcnow()
    rows = session.exec(q).all()
    for n in rows:
        n.read_at = now
        session.add(n)
    session.commit()
    return len(rows)
