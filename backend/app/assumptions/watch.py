"""새 자료가 들어오면 감시 중인 가정을 다시 판정한다 — 수집 소스가 적재했을 때(pipeline.runner)와 드라이브에 직접 올린 자료의 처리가 끝났을 때(docs.queue).
숫자 가정은 코드라 모두 다시, 정성 가정(LLM)은 새 자료가 그 대상을 다룰 때만."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.assumptions.judge import entity_docs
from app.assumptions.service import check
from app.db import COMPANY_SCOPE, Assumption, SourceItem, engine, utcnow

log = logging.getLogger(__name__)


async def recheck_for_docs(new_docs: List[str], trigger: Dict[str, Any], workspace_id: Optional[str] = None, as_of: Optional[str] = None) -> int:
    """새 자료 → 감시 가정 다시 판정. workspace_id 가 있으면 그 워크스페이스 가정만(사내 공용 자료면 전부)."""
    if not new_docs:
        return 0
    with Session(engine) as s:
        q = select(Assumption).where(Assumption.watch == True)  # noqa: E712
        if workspace_id and workspace_id != COMPANY_SCOPE:
            q = q.where(Assumption.workspace_id == workspace_id)
        targets = [(a.id, a.kind, dict(a.target or {})) for a in s.exec(q).all()]
    n = 0
    for aid, kind, target in targets:
        if kind != "numeric" and not entity_docs(target, new_docs):
            continue
        try:
            await check(aid, as_of, trigger=trigger)
            n += 1
        except Exception:  # noqa: BLE001
            log.exception("recheck failed: %s", aid)
    try:  # 판단 기준 판정 → 걸린 문서에 검토 제안(가정 판정 뒤 — 같은 새 자료로)
        from app.criteria.proposals import on_new_docs

        n += await on_new_docs(new_docs, trigger, workspace_id, as_of)
    except Exception:  # noqa: BLE001
        log.exception("criteria proposals failed")
    return n


async def on_new_items(source_id: str, as_of: Optional[str] = None) -> int:
    with Session(engine) as s:
        new_docs = [x.doc_id for x in s.exec(select(SourceItem).where(SourceItem.source_id == source_id, SourceItem.status == "ok", SourceItem.fetched_at >= utcnow() - timedelta(minutes=15))).all() if x.doc_id]
    return await recheck_for_docs(new_docs, {"kind": "source", "sourceId": source_id}, as_of=as_of)


async def on_uploaded(doc_id: str, workspace_id: str, user_id: str = "") -> int:
    return await recheck_for_docs([doc_id], {"kind": "upload", "docId": doc_id, "by": user_id}, workspace_id=workspace_id)
