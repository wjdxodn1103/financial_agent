"""공유·확인 — 드라이브의 결과(문서·데이터·정리한 데이터)를 멤버에게 보내고(메시지·검토 요청), 받은 사람이 근거를 확인한 뒤 승인한다.

문서 상태: doc.approval = {status: draft(AI 초안)|review(검토 중)|approved(승인), by, at, note, reviewerId}.
밖으로(메일·메신저) 보내지 않는다 — 앱 안 알림만.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import ROLE_RANK, require_member
from app.db import ReportSession, ResearchTable, Share, Task, User, iso, scope_ids, utcnow
from app.ids import id36
from app.notify import notify

STATUS_KO = {"draft": "AI 초안", "review": "검토 중", "approved": "승인"}


def _item(session: Session, ws_id: str, kind: str, item_id: str) -> Dict[str, Any]:
    if kind == "doc":
        r = session.get(ReportSession, item_id)
        if r is None or r.workspace_id != ws_id:
            raise HTTPException(404, "문서를 찾지 못했습니다.")
        return {"title": r.title or str(((r.doc or {}).get("setup") or {}).get("title") or "제목 없는 문서"), "link": {"w": ws_id, "v": "reports", "s": r.id}}
    if kind == "table":
        t = session.get(ResearchTable, item_id)
        if t is None or t.workspace_id != ws_id:
            raise HTTPException(404, "정리한 데이터를 찾지 못했습니다.")
        return {"title": t.title or "정리한 데이터", "link": {"w": ws_id, "v": "documents"}}
    if kind == "data":
        from app.db import Repo
        from app.docs.store import doc_label, load_meta

        ws = Repo(session).workspace(ws_id)
        if item_id not in scope_ids(ws):
            raise HTTPException(404, "데이터를 찾지 못했습니다.")
        return {"title": doc_label(load_meta(item_id), item_id), "link": {"w": ws_id, "v": "documents"}}
    raise HTTPException(400, "보낼 수 없는 항목입니다.")


def share(session: Session, ws_id: str, user: User, kind: str, item_id: str, to: List[str], message: str = "", review: bool = False) -> Dict[str, Any]:
    require_member(session, ws_id, user, "reviewer")
    to = [u for u in dict.fromkeys(to) if u and u != user.id]
    if not to:
        raise HTTPException(400, "받는 사람을 고르세요.")
    from app.db import Repo

    repo = Repo(session)
    for uid in to:
        if repo.membership(ws_id, uid) is None:
            raise HTTPException(400, "받는 사람은 이 워크스페이스 멤버여야 합니다.")
    it = _item(session, ws_id, kind, item_id)
    msg = (message or "").strip()[:500]
    row = Share(id=id36("sh", 5), workspace_id=ws_id, item_kind=kind, item_id=item_id, title=it["title"][:200], from_user=user.id, to_users=to, message=msg, review=review)
    session.add(row)
    session.commit()
    sender = f"{user.name} {user.title}".strip()
    if review and kind == "doc":
        if len(to) != 1:
            raise HTTPException(400, "검토 요청은 한 사람에게 보냅니다.")
        from app.services.report_service import ReportService

        ReportService(session).request_review(item_id, user, to[0], msg)  # 검토 작업·알림·doc.reviewRequest
        set_approval(session, item_id, "review", user, reviewer_id=to[0])
    else:
        if review:
            for uid in to:
                session.add(Task(id=id36("t", 4), workspace_id=ws_id, title=f"검토 — {it['title']}"[:160], detail=msg, assignee_id=uid, status="todo", source={"kind": "share", "shareId": row.id, "itemKind": kind, "itemId": item_id}, created_by=user.id))
            session.commit()
        notify(to, workspace_id=ws_id, kind="review" if review else "share", title=f"{sender}님이 '{it['title']}'{'의 검토를 요청했습니다' if review else '을(를) 보냈습니다'}"[:200],
               body=msg, link=it["link"], ref={"kind": kind, "id": item_id, "shareId": row.id}, session=session)
        session.commit()
    return view(session, row)


def view(session: Session, r: Share) -> Dict[str, Any]:
    u = session.get(User, r.from_user)
    return {"id": r.id, "itemKind": r.item_kind, "itemId": r.item_id, "title": r.title, "from": {"id": r.from_user, "name": f"{u.name} {u.title}".strip() if u else ""}, "to": r.to_users,
            "message": r.message, "review": r.review, "createdAt": iso(r.created_at)}


def received(session: Session, ws_id: str, user: User, limit: int = 20) -> List[Dict[str, Any]]:
    require_member(session, ws_id, user)
    rows = session.exec(select(Share).where(Share.workspace_id == ws_id).order_by(Share.created_at.desc()).limit(200)).all()
    return [view(session, r) for r in rows if user.id in (r.to_users or [])][:limit]


def set_approval(session: Session, session_id: str, status: str, user: Optional[User], note: str = "", reviewer_id: Optional[str] = None) -> Dict[str, Any]:
    r = session.get(ReportSession, session_id)
    if r is None:
        raise HTTPException(404, "문서를 찾지 못했습니다.")
    doc = copy.deepcopy(r.doc or {})
    cur = doc.get("approval") or {}
    doc["approval"] = {**cur, "status": status, "label": STATUS_KO.get(status, status), "by": user.id if user else cur.get("by"), "at": iso(utcnow()), "note": (note or "")[:300],
                       **({"reviewerId": reviewer_id} if reviewer_id else {})}
    r.doc = doc
    r.updated_at = utcnow()
    session.add(r)
    session.commit()
    return doc["approval"]


def approve(session: Session, session_id: str, user: User, note: str = "") -> Dict[str, Any]:
    """승인 — 검토를 요청받은 사람, 또는 편집자 이상(만든 사람 자신은 아님)."""
    r = session.get(ReportSession, session_id)
    if r is None:
        raise HTTPException(404, "문서를 찾지 못했습니다.")
    _ws, m = require_member(session, r.workspace_id, user, "reviewer")
    req = (r.doc or {}).get("reviewRequest") or {}
    if req.get("reviewerId") != user.id and (ROLE_RANK.get(m.role, 0) < ROLE_RANK["editor"] or r.created_by == user.id):
        raise HTTPException(403, "검토를 요청받은 사람이나 다른 편집자가 승인합니다.")
    out = set_approval(session, session_id, "approved", user, note)
    if req.get("taskId"):
        t = session.get(Task, req["taskId"])
        if t is not None and t.status != "done":
            t.status, t.updated_at = "done", utcnow()
            session.add(t)
            session.commit()
    title = r.title or "문서"
    notify([r.created_by], workspace_id=r.workspace_id, kind="review", title=f"'{title}' 승인 — {user.name} {user.title}".strip()[:200], body=note[:300], link={"w": r.workspace_id, "v": "reports", "s": r.id},
           ref={"kind": "doc", "id": r.id}, dedupe_key=f"approved:{r.id}:{out['at']}", exclude=[user.id])
    return out
