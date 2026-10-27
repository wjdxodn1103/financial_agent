"""워크스페이스 채널 — 멤버끼리 대화하고, "@에이전트"로 물으면 워크스페이스 자료를 근거로 답한다.

 - 스레드: 답글은 thread_id(첫 메시지 id)를 갖는다. 목록은 전부 보내고 화면이 묶는다(폴링 그대로). 스레드 안 질문의 답도 그 스레드에.
 - 숫자 대조: 사람 메시지의 (지표·기간·값) 을 원장과 맞춰 meta.numberChecks 에 둔다(channel/numbers, LLM 0회).

 - 실시간은 폴링(화면이 ?after= 로 3초마다) — 이벤트 스트림은 확장 자리.
 - 메시지는 공통 형식(ChannelMessage) — 사내 메신저를 연결할 때도 같은 표에 넣으면 기록 비서가 그대로 읽는다.
 - 채널 대화는 멤버 모두에게 공유된다(기록 비서의 재료). 개인 대화는 리포트의 에이전트 대화다.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import require_member
from app.db import ChannelMessage, Repo, User, engine, iso, utcnow
from app.docs.store import doc_label, load_meta
from app.channel.numbers import check_numbers
from app.ids import id36

log = logging.getLogger(__name__)
AGENT_MENTION = re.compile(r"@(에이전트|agent|AI)", re.I)
_tasks: "set[asyncio.Task[None]]" = set()


def message_view(m: ChannelMessage, names: Dict[str, str]) -> Dict[str, Any]:
    return {"id": m.id, "userId": m.user_id, "author": names.get(m.user_id or "", "에이전트" if m.kind == "agent" else ""), "kind": m.kind, "text": m.text, "meta": m.meta or {}, "threadId": m.thread_id, "createdAt": iso(m.created_at)}


def _names(session: Session) -> Dict[str, str]:
    return {u.id: f"{u.name} {u.title}".strip() for u in session.exec(select(User)).all()}


def _parse_after(after: Optional[str]) -> Optional[datetime]:
    if not after:
        return None
    try:
        return datetime.fromisoformat(after.rstrip("Z"))
    except ValueError:
        return None


class ChannelService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = Repo(session)

    def listing(self, workspace_id: str, user: User, after: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
        require_member(self.session, workspace_id, user)
        q = select(ChannelMessage).where(ChannelMessage.workspace_id == workspace_id)
        t = _parse_after(after)
        if t is not None:
            q = q.where(ChannelMessage.created_at > t)
        rows = list(self.session.exec(q.order_by(ChannelMessage.created_at.desc()).limit(limit)).all())  # type: ignore[attr-defined]
        rows.reverse()
        # 답을 기다리던 에이전트 메시지는 답이 끝날 때 바뀐다 — after 보다 먼저 만들어졌어도 그 뒤에 바뀌었으면 다시 보낸다
        changed: List[ChannelMessage] = []
        if t is not None:
            older = self.session.exec(select(ChannelMessage).where(ChannelMessage.workspace_id == workspace_id, ChannelMessage.kind == "agent", ChannelMessage.created_at <= t)).all()  # type: ignore[arg-type]
            for m in older:
                u = _parse_after((m.meta or {}).get("updatedAt"))
                if u is not None and u > t:
                    changed.append(m)
        names = _names(self.session)
        return {"messages": [message_view(m, names) for m in rows], "updated": [message_view(m, names) for m in changed]}

    def post(self, workspace_id: str, user: User, text: str, attachments: Optional[List[str]] = None, thread_id: Optional[str] = None) -> Dict[str, Any]:
        """검토자 이상. "@에이전트" 가 있으면 답을 뒤에서 만든다(이벤트 루프에서 불러야 한다). thread_id = 답글을 달 첫 메시지."""
        ws, _m = require_member(self.session, workspace_id, user, "reviewer")
        if thread_id:
            root = self.session.get(ChannelMessage, thread_id)
            if root is None or root.workspace_id != ws.id:
                raise HTTPException(404, "답글을 달 메시지가 없습니다.")
            thread_id = root.thread_id or root.id  # 답글에 단 답글은 같은 스레드로
        text = (text or "").strip()
        att = [d for d in (attachments or []) if d in (ws.document_ids or [])]
        if not text and not att:
            raise HTTPException(400, "보낼 내용이 없습니다.")
        members = {self.repo.user(m.user_id).name: m.user_id for m in self.repo.members(ws.id) if self.repo.user(m.user_id)}  # type: ignore[union-attr]
        mentions = [uid for name, uid in members.items() if f"@{name}" in text]
        meta: Dict[str, Any] = {}
        if mentions:
            meta["mentions"] = mentions
        if att:
            meta["attachments"] = [{"docId": d, "label": doc_label(load_meta(d), d)} for d in att]
        asks_agent = bool(AGENT_MENTION.search(text))
        if asks_agent:
            meta["askAgent"] = True
        msg_id = id36("c", 4)
        checks = check_numbers(self.session, ws.id, msg_id, text) if text else []
        if checks:
            meta["numberChecks"] = checks
        msg = ChannelMessage(id=msg_id, workspace_id=ws.id, user_id=user.id, kind="user", text=text[:4000], meta=meta, thread_id=thread_id)
        self.repo.save(msg)
        out = {"message": message_view(msg, _names(self.session))}
        if asks_agent:
            placeholder = ChannelMessage(id=id36("c", 4), workspace_id=ws.id, user_id=None, kind="agent", text="", meta={"pending": True, "replyTo": msg.id}, thread_id=thread_id)
            self.repo.save(placeholder)
            task = asyncio.get_running_loop().create_task(_answer(ws.id, msg.id, placeholder.id), name=f"channel-agent-{placeholder.id}")
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)
            out["agent"] = message_view(placeholder, {})
        return out


async def _answer(workspace_id: str, question_id: str, placeholder_id: str) -> None:
    from app.channel.agent import answer_question

    try:
        result = await answer_question(workspace_id, question_id)
    except Exception as e:  # noqa: BLE001
        log.exception("[channel] agent answer failed")
        result = {"text": f"답을 만들지 못했습니다: {e}", "cites": {}}
    with Session(engine) as s:
        m = s.get(ChannelMessage, placeholder_id)
        if m is None:
            return
        m.text = result["text"]
        m.meta = {"replyTo": question_id, "cites": result.get("cites") or {}, "updatedAt": iso(utcnow())}
        s.add(m)
        s.commit()

