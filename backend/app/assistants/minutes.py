"""IC 회의록 정리 — 올린 회의록(화자 줄 — 녹취 정리본·STT 대용)만 근거로 'IC 심의 요약(예시)' 양식 문서를 화면 없이 쓴다.
발언은 인용 토큰으로 달려 원문 창에서 그 줄이 열린다(작성기의 인용 검증 그대로). 다 쓰면 결정 문장을 가정 후보로 뽑고, 부른 사람에게 알린다.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session

from app.auth import require_member
from app.db import Repo, User, engine, scope_ids
from app.docs.store import doc_label, load_meta
from app.notify import notify

log = logging.getLogger(__name__)

BRIEF = """회의록 '{label}' 하나만 근거로 쓴다(다른 자료·일반 지식으로 채우지 않는다).
- 발언은 화자 이름(직책)과 함께 쓰고, 문장마다 그 발언 줄을 인용한다.
- 회의록에 없는 쟁점·숫자·결정은 만들지 않는다. 없는 항목은 '회의록에 없음'으로 둔다.
- 결정 문장(승인·보류·조건·재심의 기준)은 회의록 글자 그대로 옮긴다.
- 정리하는 사람의 평가·판단·총평 문장은 쓰지 않는다."""


def start(workspace_id: str, user: User, doc_id: str, only: Optional[List[str]] = None) -> Dict[str, Any]:
    from app import scheduler

    with Session(engine) as s:
        require_member(s, workspace_id, user, "editor")
        if doc_id not in scope_ids(Repo(s).workspace(workspace_id)):
            raise HTTPException(404, "회의록을 찾지 못했습니다.")
    label = doc_label(load_meta(doc_id), doc_id)
    if not scheduler.spawn("ic_minutes", _run(workspace_id, user.id, doc_id, label, only), workspace_id):
        raise HTTPException(409, "다른 회의록을 정리하는 중입니다. 끝나면 알림이 옵니다.")
    return {"started": True, "title": label}


async def _run(workspace_id: str, user_id: str, doc_id: str, label: str, only: Optional[List[str]] = None) -> None:
    from app.assumptions import service as asm
    from app.headless import write_report
    from app.seed_formats import type_id

    res = await write_report(workspace_id=workspace_id, owner_id=user_id, format_id=type_id("kicicminutes"), title=f"IC 심의 요약 — {label}"[:80],
                             data_scope={"groups": {"workspace": False, "company": False, "personal": False}, "docIds": [doc_id]},
                             extra_brief=BRIEF.format(label=label), origin={"minutes": doc_id}, steps=only or None)
    found = 0
    if res.get("written"):
        try:
            with Session(engine) as s:
                user = s.get(User, user_id)
            found = len(await asm.run_extract(workspace_id, user, "report", res["sessionId"]))
        except Exception:  # noqa: BLE001 — 가정 후보는 덤(실패해도 문서는 남는다)
            log.exception("minutes: assumption extract failed")
    notify([user_id], workspace_id=workspace_id, kind="routine", title=f"IC 심의 요약을 썼습니다 — {label}"[:120],
           body=f"섹션 {res.get('written')}/{res.get('sections')}" + (f" · 가정 후보 {found}개" if found else "") + (f" · {', '.join(res['warnings'])[:120]}" if res.get("warnings") else ""),
           link={"w": workspace_id, "v": "reports", "s": res["sessionId"]}, ref={"kind": "report", "id": res["sessionId"]})
