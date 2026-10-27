"""근거 원장 서비스 — 워크스페이스 문서들의 figures 를 모아 묶음·충돌·채택을 보여 주고, 채택은 결정 기록으로 남긴다."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import require_member
from app.db import LedgerChoice, Repo, TeamRecord, User, evidence_ids, iso, utcnow
from app.docs.store import doc_label, load_meta
from app.ids import id36
from app.ledger.figures import Figure, workspace_ledger


def doc_labels(doc_ids: List[str]) -> Dict[str, str]:
    return {d: doc_label(load_meta(d), d) for d in doc_ids}


def choices_of(session: Session, workspace_id: str) -> Dict[str, Dict[str, Any]]:
    rows = session.exec(select(LedgerChoice).where(LedgerChoice.workspace_id == workspace_id)).all()
    return {r.key: {"figureId": r.figure_id, "reason": r.reason, "chosenBy": r.chosen_by, "chosenAt": iso(r.chosen_at), "recordId": r.record_id} for r in rows}


def ledger_for(session: Session, workspace_id: str, doc_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    ws = Repo(session).workspace(workspace_id)
    ids = list(doc_ids if doc_ids is not None else evidence_ids(ws))
    return workspace_ledger(ids, doc_labels(ids), choices_of(session, workspace_id))


class LedgerService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = Repo(session)

    def view(self, workspace_id: str, user: User) -> Dict[str, Any]:
        require_member(self.session, workspace_id, user)
        led = ledger_for(self.session, workspace_id)
        groups = led["groups"]
        return {
            **led,
            "stats": {
                "figures": len(led["figures"]),
                "groups": len(groups),
                "conflicts": sum(1 for g in groups if g["conflict"] and not g["chosen"]),
                "resolved": sum(1 for g in groups if g["chosen"]),
                "documents": len({f["doc"] for f in led["figures"]}),
            },
        }

    def choose(self, workspace_id: str, user: User, key: str, figure_id: str, reason: str = "") -> Dict[str, Any]:
        """충돌 묶음에서 값을 채택 — 행동이라 결정 기록을 즉시(확정 상태로) 남긴다."""
        require_member(self.session, workspace_id, user, "editor")
        led = ledger_for(self.session, workspace_id)
        group = next((g for g in led["groups"] if g["key"] == key), None)
        if group is None or figure_id not in group["figureIds"]:
            raise HTTPException(404, "원장에서 그 값을 찾지 못했습니다(자료가 바뀌었을 수 있습니다).")
        fig: Figure = next(f for f in led["figures"] if f["fid"] == figure_id)
        basis = f", {fig['basis']}" if fig.get("basis") else ""
        others = [v["display"] for v in group["values"] if figure_id not in v["figureIds"]]
        text = f"{fig['metric']}({fig['period']}{basis})은 {fig['docLabel']}의 {fig.get('display') or fig['raw']}을 쓴다" + (f" — 다른 값: {', '.join(others)}" if others else "") + (f". 사유: {reason.strip()}" if reason.strip() else "")
        now = utcnow()
        old = self.session.get(LedgerChoice, (workspace_id, key))
        if old and old.record_id:
            prev = self.session.get(TeamRecord, old.record_id)
            if prev and prev.status == "confirmed":
                prev.status = "superseded"
                self.repo.save(prev)
        rec = TeamRecord(
            id=id36("k", 4),
            workspace_id=workspace_id,
            type="decision",
            text=text,
            author_id=user.id,
            scope=fig["metric"],
            status="confirmed",
            source={"kind": "card", "card": "ledger_choice", "key": key, "figureId": figure_id},
            confirmed_by=user.id,
            confirmed_at=now,
        )
        self.repo.save(rec)
        if old:
            old.figure_id, old.reason, old.chosen_by, old.chosen_at, old.record_id = figure_id, reason.strip(), user.id, now, rec.id
            self.repo.save(old)
        else:
            self.repo.save(LedgerChoice(workspace_id=workspace_id, key=key, figure_id=figure_id, reason=reason.strip(), record_id=rec.id, chosen_by=user.id, chosen_at=now))
        return self.view(workspace_id, user)
