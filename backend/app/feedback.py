"""👍/👎 — AI 답·섹션·시장 요약·문서에 사람마다 하나. 품질·이용 지표의 '만족도' 원자료."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db import Feedback, utcnow
from app.ids import id36

TARGETS = ("answer", "section", "brief", "doc")


def give(session: Session, user_id: str, workspace_id: str, target_kind: str, target_id: str, thumbs: int, score: Optional[int] = None, comment: str = "") -> Dict[str, Any]:
    if target_kind not in TARGETS or not target_id:
        raise HTTPException(400, "피드백 대상이 올바르지 않습니다.")
    thumbs = 1 if thumbs > 0 else -1 if thumbs < 0 else 0
    row = session.exec(select(Feedback).where(Feedback.user_id == user_id, Feedback.target_kind == target_kind, Feedback.target_id == target_id)).first()
    if row is None:
        row = Feedback(id=id36("f", 5), workspace_id=workspace_id, user_id=user_id, target_kind=target_kind, target_id=target_id)
    row.thumbs, row.score, row.comment, row.updated_at = thumbs, score, (comment or "")[:500], utcnow()
    session.add(row)
    session.commit()
    return {"targetId": target_id, "thumbs": thumbs}


def mine(session: Session, user_id: str, target_kind: str, ids: List[str]) -> Dict[str, int]:
    if not ids:
        return {}
    rows = session.exec(select(Feedback).where(Feedback.user_id == user_id, Feedback.target_kind == target_kind, Feedback.target_id.in_(ids))).all()  # type: ignore[attr-defined]
    return {r.target_id: r.thumbs for r in rows if r.thumbs}
