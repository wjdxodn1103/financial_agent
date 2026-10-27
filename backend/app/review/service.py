"""문서 검수 — 대상 문서를 고르면 뒤에서 돈다(숫자 주장 뽑기 → 원장 대조 규칙). 지적은 작업 항목으로 만들 수 있다.

수명: running → done | error. 요청 세션을 백그라운드에 끌고 가지 않는다(짧은 세션으로 읽고 쓴다).
재검수: 같은 자료(또는 그 이전 판)의 앞선 검수가 있으면 지적을 (규칙·지표·기간·표/문장) 으로 맞춰 본다 —
사라진 지적의 작업 항목은 자동 완료(사유를 작업에 남김), 남은 지적은 같은 작업 항목을 이어 받는다.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import require_member
from app.db import Repo, Review, Task, User, engine, evidence_ids, iso, set_excluded, utcnow
from app.drive import hidden_items
from app.docs.store import doc_label, load_meta
from app.ids import id36
from app.ledger.service import choices_of, doc_labels
from app.docs.versions import chain
from app.ledger.figures import metric_key, period_key, workspace_ledger
from app.review.claims import extract_claims
from app.review.rules import RULE_KO, align_metrics, run_rules
from app.review.word_memo import review_memo
from app.tasks import task_view

log = logging.getLogger(__name__)
_running: Dict[str, "asyncio.Task[None]"] = {}


def review_view(r: Review, detail: bool = False) -> Dict[str, Any]:
    meta = load_meta(r.doc_id) or {}
    out: Dict[str, Any] = {
        "id": r.id,
        "docId": r.doc_id,
        "docLabel": doc_label(meta, r.doc_id),
        "fileName": meta.get("fileName") or "",
        "status": r.status,
        "summary": r.summary or {},
        "error": r.error,
        "createdBy": r.created_by,
        "createdAt": iso(r.created_at),
        "finishedAt": iso(r.finished_at),
    }
    if detail:
        out["findings"] = r.findings or []
    return out


async def _run(review_id: str) -> None:
    from app.llm.client import ReportLlm, provider_ready

    try:
        with Session(engine) as s:
            r = s.get(Review, review_id)
            if r is None:
                return
            ws = Repo(s).workspace(r.workspace_id)
            doc_id = r.doc_id
            hidden = hidden_items(s, r.workspace_id, r.created_by)  # 검수한 사람에게 안 보이는 폴더 속 데이터는 근거로 쓰지 않는다
            ref_ids = [d for d in evidence_ids(ws) if d != doc_id and d not in hidden]
            choices = choices_of(s, r.workspace_id)
        llm = ReportLlm() if provider_ready() else None
        led = await asyncio.to_thread(workspace_ledger, ref_ids, doc_labels(ref_ids), choices)
        got = await extract_claims(doc_id, llm, list(dict.fromkeys(f["metric"] for f in led["figures"])))
        claims = align_metrics(got["claims"], led["figures"])
        findings, summary = run_rules(claims, led["figures"], choices, led["groups"])
        claims_by_id = {c["id"]: c for c in claims}
        for f in findings:
            c = claims_by_id.get(f["claimId"]) or {}
            f["claim"] = {k: c.get(k) for k in ("metric", "period", "basis", "raw", "quote", "chunk", "cell", "kind", "source")}
        summary.update({"mode": got["mode"], "proposed": got["proposed"], "rejected": got["rejected"], "referenceDocs": len(ref_ids), "swept": got["swept"], "missed": got["missed"][:30]})
        with Session(engine) as s:
            r = s.get(Review, review_id)
            if r is None:
                return
            carry = carry_over(s, r, findings)
            if carry:
                summary["carry"] = carry
            r.findings = findings
            r.summary = summary
            r.status = "done"
            r.finished_at = utcnow()
            s.add(r)
            s.commit()
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("[review] %s failed", review_id)
        with Session(engine) as s:
            r = s.get(Review, review_id)
            if r is not None:
                r.status, r.error, r.finished_at = "error", str(e)[:300], utcnow()
                s.add(r)
                s.commit()
    finally:
        _running.pop(review_id, None)


def _finding_key(f: Dict[str, Any]) -> tuple:
    c = f.get("claim") or {}
    return (f["rule"], metric_key(c.get("metric") or ""), period_key(c.get("period") or ""), c.get("source") == "table")


def carry_over(s: Session, r: Review, findings: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """앞선 검수(같은 묶음의 판들) 대비 — 해소된 지적의 작업 항목 자동 완료, 남은 지적은 작업 항목을 이어 받는다."""
    ids = chain(s, r.workspace_id, r.doc_id)
    prev = s.exec(
        select(Review).where(Review.workspace_id == r.workspace_id, Review.status == "done", Review.id != r.id).order_by(Review.finished_at.desc())  # type: ignore[attr-defined]
    ).all()
    prev = next((x for x in prev if x.doc_id in ids), None)
    if prev is None:
        return None
    now = utcnow().strftime("%Y-%m-%d")
    meta = load_meta(r.doc_id) or {}
    label = doc_label(meta, r.doc_id)
    version = ids.index(r.doc_id) + 1 if r.doc_id in ids else None
    tag = f"재검수({now}{f', v{version}' if version and len(ids) > 1 else ''})"
    new_by_key: Dict[tuple, Dict[str, Any]] = {}
    for f in findings:
        if f["rule"] != "ok":
            new_by_key.setdefault(_finding_key(f), f)
    resolved, carried = [], []
    for of in prev.findings or []:
        if of.get("rule") == "ok":
            continue
        k = _finding_key(of)
        c = of.get("claim") or {}
        item = {"rule": of["rule"], "metric": c.get("metric"), "period": c.get("period"), "before": c.get("raw"), "taskId": of.get("taskId")}
        t = s.get(Task, of["taskId"]) if of.get("taskId") else None
        nf = new_by_key.get(k)
        if nf is not None:
            item["after"] = (nf.get("claim") or {}).get("raw")
            carried.append(item)
            if t is not None and not nf.get("taskId"):
                nf["taskId"] = t.id  # 같은 지적은 같은 작업으로 — 새로 만들지 않는다
                t.detail = f"{t.detail}\n{tag}: 아직 남음 — {nf['message']}"[-1000:]
                t.source = {**(t.source or {}), "reviewId": r.id, "findingId": nf["id"], "docId": r.doc_id}
                t.updated_at = utcnow()
                s.add(t)
        else:
            resolved.append(item)
            if t is not None and t.status != "done":
                t.status = "done"
                t.detail = f"{t.detail}\n{tag}에서 해소 — 자동 완료({label})"[-1000:]
                t.updated_at = utcnow()
                s.add(t)
    fresh = [k for k in new_by_key if k not in {_finding_key(of) for of in prev.findings or [] if of.get("rule") != "ok"}]
    return {"previousReviewId": prev.id, "previousDocId": prev.doc_id, "previousLabel": doc_label(load_meta(prev.doc_id), prev.doc_id), "resolved": resolved, "carried": carried, "new": len(fresh), "autoDone": sum(1 for x in resolved if x.get("taskId"))}


class ReviewService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = Repo(session)

    def start(self, workspace_id: str, user: User, doc_id: str) -> Dict[str, Any]:
        """검토자 이상. 대상 문서는 워크스페이스 자료여야 한다(먼저 올린다). 이벤트 루프에서 불러야 한다(백그라운드 태스크)."""
        ws, _m = require_member(self.session, workspace_id, user, "reviewer")
        if doc_id not in (ws.document_ids or []):
            raise HTTPException(404, "이 워크스페이스의 자료가 아닙니다. 검수할 문서를 먼저 올려 주세요.")
        r = Review(id=id36("v", 4), workspace_id=ws.id, doc_id=doc_id, status="running", created_by=user.id)
        self.repo.save(r)
        # 검수 대상(초안)은 근거에서 뺀다 — 틀린 숫자가 원장·리포트·대화 답의 근거로 들어가지 않게(자료 목록에서 다시 켤 수 있다)
        set_excluded(ws, doc_id, True)
        self.repo.save(ws)
        _running[r.id] = asyncio.get_running_loop().create_task(_run(r.id), name=f"review-{r.id}")
        return review_view(r, detail=True)

    def listing(self, workspace_id: str, user: User) -> Dict[str, Any]:
        require_member(self.session, workspace_id, user)
        rows = self.session.exec(select(Review).where(Review.workspace_id == workspace_id).order_by(Review.created_at.desc())).all()  # type: ignore[attr-defined]
        return {"reviews": [review_view(r) for r in rows]}

    def get(self, workspace_id: str, user: User, review_id: str) -> Dict[str, Any]:
        require_member(self.session, workspace_id, user)
        r = self.session.get(Review, review_id)
        if r is None or r.workspace_id != workspace_id:
            raise HTTPException(404, "검수 결과가 없습니다.")
        out = review_view(r, detail=True)
        out["tasks"] = [task_view(t) for t in self.session.exec(select(Task).where(Task.workspace_id == workspace_id)).all() if (t.source or {}).get("reviewId") == review_id]
        return out

    def memo(self, workspace_id: str, user: User, review_id: str) -> Tuple[bytes, str]:
        """검수 결과 → Word(대상이 DOCX 면 원본에 메모, 아니면 검수 의견서). 멤버 누구나 받는다."""
        out = self.get(workspace_id, user, review_id)
        if out["status"] != "done":
            raise HTTPException(409, "검수가 끝난 뒤에 받을 수 있습니다.")
        by = self.repo.user(out["createdBy"])
        data, name, _stats = review_memo(out, f"{by.name} {by.title}".strip() if by else "")
        return data, name

    def make_tasks(self, workspace_id: str, user: User, review_id: str, finding_ids: List[str], assignee_id: Optional[str], due: str = "") -> Dict[str, Any]:
        """지적 → 작업 항목(검토자 이상). 담당자는 워크스페이스 멤버만."""
        require_member(self.session, workspace_id, user, "reviewer")
        r = self.session.get(Review, review_id)
        if r is None or r.workspace_id != workspace_id:
            raise HTTPException(404, "검수 결과가 없습니다.")
        if assignee_id and self.repo.membership(workspace_id, assignee_id) is None:
            raise HTTPException(400, "담당자는 워크스페이스 멤버여야 합니다.")
        findings = [dict(f) for f in r.findings or []]
        existing = {(t.source or {}).get("findingId") for t in self.session.exec(select(Task).where(Task.workspace_id == workspace_id)).all() if (t.source or {}).get("reviewId") == review_id}
        doc = doc_label(load_meta(r.doc_id), r.doc_id)
        made = 0
        for f in findings:
            if f["id"] not in finding_ids or f["id"] in existing or f["rule"] == "ok":
                continue
            c = f.get("claim") or {}
            title = f"[검수·{RULE_KO.get(f['rule'], f['rule'])}] {c.get('metric') or ''} {c.get('period') or ''} — {doc}".strip()
            detail = f"{f['message']}\n문장: {c.get('quote') or ''}" + (f"\n계산식: {f['formula']}" if f.get("formula") else "")
            t = Task(id=id36("t", 4), workspace_id=workspace_id, title=title[:160], detail=detail[:1000], assignee_id=assignee_id or None, due=due, status="todo", source={"kind": "review", "reviewId": review_id, "findingId": f["id"], "docId": r.doc_id}, created_by=user.id)
            self.repo.save(t)
            f["taskId"] = t.id
            made += 1
        r.findings = findings
        self.repo.save(r)
        out = self.get(workspace_id, user, review_id)
        out["made"] = made
        return out


