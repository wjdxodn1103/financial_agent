"""판단 기준 관리 — 목록(사용 중·승인 대기·보관)·뽑기(초안)·고치기(초안만)·승인/버리기·판 이력.
승인: 사내 공통 = 관리자(config.ADMIN_USER_IDS), 워크스페이스 기준 = 그 워크스페이스 소유자. 승인하면 같은 기준(key)의 사용 중 판은 보관으로 넘어간다.
충돌 = 같은 지표·대상인데 조건(부등호·기준값)이나 방향이 다른 사용 중 기준(코드가 본다). 수정안(revise)이 내는 충돌은 by=ai 로 따로 표시."""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app import config
from app.assumptions.judge import entity_docs, ledger_metrics, map_metric
from app.auth import ROLE_RANK, require_member
from app.criteria.extract import extract, kind_of
from app.criteria.match import DIRECTION_KO, SCOPE_KO, active, code_metric, condition_text, same_target
from app.db import Criterion, Membership, ReportSession, User, Workspace, engine, iso, scope_ids, utcnow
from app.ids import id36
from app.ledger.figures import metric_key
from app.notify import notify

log = logging.getLogger(__name__)
STATUS_KO = {"draft": "승인 대기", "active": "사용 중", "archived": "보관", "rejected": "버림"}
EDITABLE = ("title", "when_text", "direction", "condition", "applies", "limit", "note")


def is_admin(user: User) -> bool:
    return user.id in config.ADMIN_USER_IDS


def can_approve(session: Session, user: User, scope: str, workspace_id: str) -> bool:
    if scope == "company":
        return is_admin(user)
    m = session.get(Membership, (workspace_id, user.id))
    return m is not None and m.role == "owner"


def approvers(session: Session, scope: str, workspace_id: str) -> List[str]:
    if scope == "company":
        return list(config.ADMIN_USER_IDS)
    return [m.user_id for m in session.exec(select(Membership).where(Membership.workspace_id == workspace_id, Membership.role == "owner")).all()]


def _names(session: Session) -> Dict[str, str]:
    return {u.id: f"{u.name} {u.title}".strip() for u in session.exec(select(User)).all()}


def _same_metric(a: Criterion, b: Criterion) -> bool:
    ma, mb = (a.condition or {}).get("metric") or "", (b.condition or {}).get("metric") or ""
    return bool(ma and mb) and (metric_key(ma) == metric_key(mb) or ma.replace(" ", "") == mb.replace(" ", ""))


def _overlap(a: Criterion, b: Criterion) -> bool:
    pa, pb = a.applies or {}, b.applies or {}
    if (pa.get("name") or pa.get("ticker")) and (pb.get("name") or pb.get("ticker")):
        return same_target(pa, pb)
    return True


def code_conflicts(session: Session, c: Criterion) -> List[Dict[str, Any]]:
    """같은 지표·겹치는 대상의 사용 중 기준 중 부등호·기준값·방향이 다른 것(같은 key 의 이전 판은 고치는 대상이라 뺀다)."""
    if c.kind != "numeric":
        return []
    ws = c.workspace_id or ""
    out = []
    for o in active(session, ws) if ws else session.exec(select(Criterion).where(Criterion.status == "active")).all():
        if o.key == c.key or o.kind != "numeric" or not _same_metric(c, o) or not _overlap(c, o):
            continue
        a, b = c.condition or {}, o.condition or {}
        diff = [w for w, x, y in (("부등호", a.get("op"), b.get("op")), ("기준값", a.get("threshold"), b.get("threshold")), ("방향", c.direction, o.direction)) if x != y]
        if diff:
            out.append({"id": o.id, "key": o.key, "version": o.version, "title": o.title, "why": f"같은 지표 — {'·'.join(diff)} 다름", "by": "code"})
    return out


def diff(base: Optional[Criterion], c: Criterion) -> List[Dict[str, Any]]:
    """판 사이에 바뀐 것(조건·방향·대상·한도) — 사람 말로."""
    if base is None:
        return []
    out = []
    for label, before, after in (("조건", condition_text(base), condition_text(c)), ("방향", DIRECTION_KO.get(base.direction, base.direction), DIRECTION_KO.get(c.direction, c.direction)),
                                 ("대상", (base.applies or {}).get("name") or "전체", (c.applies or {}).get("name") or "전체"),
                                 ("한도", (base.limit or {}).get("threshold"), (c.limit or {}).get("threshold"))):
        if before != after:
            out.append({"field": label, "before": before, "after": after})
    return out


def view(session: Session, c: Criterion, names: Optional[Dict[str, str]] = None, user: Optional[User] = None) -> Dict[str, Any]:
    names = names if names is not None else _names(session)
    base = session.get(Criterion, c.base_id) if c.base_id else None
    ap = c.applies or {}
    return {"id": c.id, "key": c.key, "version": c.version, "scope": c.scope, "scopeKo": SCOPE_KO.get(c.scope, c.scope), "workspaceId": c.workspace_id,
            "status": c.status, "statusKo": STATUS_KO.get(c.status, c.status), "title": c.title, "when": c.when_text, "kind": c.kind, "conditionText": condition_text(c),
            "condition": c.condition, "direction": c.direction, "directionKo": f"입장 {ap['stance']}" if c.kind == "stance" and ap.get("stance") else DIRECTION_KO.get(c.direction, c.direction),
            "applies": ap, "limit": c.limit, "source": c.source, "origin": c.origin, "conflicts": c.conflicts, "note": c.note,
            "createdBy": names.get(c.created_by, c.created_by), "approvedBy": names.get(c.approved_by or "", c.approved_by), "approvedAt": iso(c.approved_at), "createdAt": iso(c.created_at),
            "base": {"id": base.id, "version": base.version, "title": base.title, "conditionText": condition_text(base), "directionKo": DIRECTION_KO.get(base.direction, base.direction)} if base else None,
            "diff": diff(base, c), "canApprove": bool(user) and c.status == "draft" and can_approve(session, user, c.scope, c.workspace_id)}  # type: ignore[arg-type]


def listing(session: Session, workspace_id: str, user: User) -> Dict[str, Any]:
    require_member(session, workspace_id, user)
    rows = session.exec(select(Criterion).where(Criterion.workspace_id.in_(["", workspace_id]), Criterion.status != "rejected")).all()  # type: ignore[attr-defined]
    rows = sorted(rows, key=lambda c: (c.scope != "workspace", c.kind == "stance", c.kind != "numeric", c.created_at, -c.version))  # 이 워크스페이스 기준 → 사내(숫자 → 정성 → 하우스뷰 입장)
    names = _names(session)
    m = session.get(Membership, (workspace_id, user.id))
    return {"criteria": [view(session, c, names, user) for c in rows],
            "canApprove": {"company": is_admin(user), "workspace": m is not None and m.role == "owner"},
            "canExtract": {"company": is_admin(user), "workspace": m is not None and ROLE_RANK.get(m.role, 0) >= ROLE_RANK["editor"]}}


def _new_row(workspace_id: str, scope: str, user_id: str, fields: Dict[str, Any], origin: Dict[str, Any], base: Optional[Criterion] = None) -> Criterion:
    keep = {k: v for k, v in fields.items() if k in ("title", "when_text", "kind", "condition", "direction", "applies", "limit", "source")}
    return Criterion(id=id36("cr", 4), key=base.key if base else id36("ck", 4), version=(base.version + 1) if base else 1, base_id=base.id if base else None,
                     scope=scope, workspace_id="" if scope == "company" else workspace_id, status="draft", created_by=user_id, origin=origin, **copy.deepcopy(keep))


def _dup(session: Session, workspace_id: str, scope: str, fields: Dict[str, Any]) -> bool:
    """같은 원문 인용의 기준이 이미 있으면(버린 것 빼고) 다시 내지 않는다."""
    q = (fields.get("source") or {}).get("quote") or ""
    ws = "" if scope == "company" else workspace_id
    rows = session.exec(select(Criterion).where(Criterion.workspace_id == ws, Criterion.status != "rejected")).all()
    return any(((r.source or {}).get("quote") or "") == q for r in rows) if q else False


def notify_drafts(session: Session, rows: List[Criterion], workspace_id: str, why: str) -> None:
    if not rows:
        return
    scope = rows[0].scope
    notify(approvers(session, scope, workspace_id), workspace_id=workspace_id, kind="criteria", title=f"판단 기준 승인 대기 {len(rows)}건 — {why}"[:200],
           body=" · ".join(r.title for r in rows)[:300], link={"w": workspace_id, "v": "criteria", "s": rows[0].id}, ref={"kind": "criteria", "id": rows[0].id},
           dedupe_key=f"criteria:{rows[0].id}")


async def run_extract(workspace_id: str, user: User, doc_kind: str, doc_ref: str, scope: str = "workspace") -> Dict[str, Any]:
    """자료·문서 → 기준 초안. 사내 공통 초안은 관리자만 낸다(워크스페이스는 편집자 이상)."""
    from app.llm.client import ReportLlm

    scope = "company" if scope == "company" else "workspace"
    with Session(engine) as s:
        _ws, m = require_member(s, workspace_id, user, "editor")
        if scope == "company" and not is_admin(user):
            raise HTTPException(403, "사내 공통 기준은 관리자가 등록합니다.")
        report_doc, title = None, ""
        if doc_kind == "report":
            r = s.get(ReportSession, doc_ref)
            if r is None or r.workspace_id != workspace_id:
                raise HTTPException(404, "문서를 찾지 못했습니다.")
            report_doc, title = copy.deepcopy(r.doc or {}), r.title or "문서"
        elif doc_ref not in scope_ids(_ws):
            raise HTTPException(404, "자료를 찾지 못했습니다.")
    found = await extract(ReportLlm(), doc_kind, doc_ref, report_doc, title)
    made: List[Criterion] = []
    with Session(engine) as s:
        for f in found:
            if _dup(s, workspace_id, scope, f):
                continue
            row = _new_row(workspace_id, scope, user.id, f, {"kind": "extract", "docKind": doc_kind, "docRef": doc_ref, "via": kind_of(doc_kind, doc_ref)})
            row.conflicts = code_conflicts(s, row)
            s.add(row)
            made.append(row)
        s.commit()
        for r in made:
            s.refresh(r)
        notify_drafts(s, made, workspace_id, f"'{(made[0].source or {}).get('docTitle') or '자료'}'에서 뽑음" if made else "")
        return {"made": len(made), "found": len(found), **listing(s, workspace_id, user)}


def _row(session: Session, criterion_id: str) -> Criterion:
    c = session.get(Criterion, criterion_id)
    if c is None:
        raise HTTPException(404, "판단 기준을 찾지 못했습니다.")
    return c


def _check_view(session: Session, c: Criterion, user: User, workspace_id: str) -> None:
    if c.scope == "company":
        require_member(session, workspace_id, user)
    else:
        require_member(session, c.workspace_id, user)


def patch(session: Session, criterion_id: str, user: User, body: Dict[str, Any], workspace_id: str = "") -> Dict[str, Any]:
    """승인 전 초안만 고친다 — 사내 초안은 관리자, 워크스페이스 초안은 편집자 이상."""
    c = _row(session, criterion_id)
    if c.status != "draft":
        raise HTTPException(409, "승인된 기준은 고칠 수 없습니다. 수정안으로 새 판을 냅니다.")
    if c.scope == "company":
        if not is_admin(user):
            raise HTTPException(403, "사내 공통 기준은 관리자가 고칩니다.")
    else:
        require_member(session, c.workspace_id, user, "editor")
    for k in EDITABLE:
        src = {"when_text": "when"}.get(k, k)
        if src not in body:
            continue
        v = body[src]
        if k == "direction" and v not in DIRECTION_KO:
            continue
        if k in ("condition", "applies", "limit"):
            if not isinstance(v, dict):
                continue
            v = copy.deepcopy(v)
        setattr(c, k, v if not isinstance(v, str) else v.strip()[:400])
    c.conflicts = code_conflicts(session, c)
    c.updated_at = utcnow()
    session.add(c)
    session.commit()
    return view(session, c, user=user)


async def decide(criterion_id: str, user: User, approve: bool, note: str = "") -> Dict[str, Any]:
    """승인 → 사용 중(같은 key 의 사용 중 판은 보관), 숫자 기준의 지표 이름을 원장 이름으로 맞춘다(코드 → 안 되면 LLM 1회). 버리기 → rejected."""
    with Session(engine) as s:
        c = _row(s, criterion_id)
        if c.status != "draft":
            raise HTTPException(409, "이미 처리한 기준입니다.")
        if not can_approve(s, user, c.scope, c.workspace_id):
            raise HTTPException(403, "사내 공통 기준은 관리자가, 워크스페이스 기준은 소유자가 승인합니다.")
        snap = c.model_copy()
        ws = c.workspace_id
    cond = dict(snap.condition or {})
    if approve and snap.kind == "numeric" and cond.get("metric") and not cond.get("ledgerMetric") and (snap.applies or {}).get("name"):
        with Session(engine) as s:
            w = s.get(Workspace, ws) if ws else None
            doc_ids = scope_ids(w) if w else []
        cands = ledger_metrics(entity_docs(snap.applies or {}, doc_ids))
        hit = code_metric(cond["metric"], cands)
        if not hit and cands:
            from app.llm.client import ReportLlm

            try:
                hit = await map_metric(ReportLlm(), cond["metric"], cands)
            except Exception:  # noqa: BLE001 — 지표 이름을 못 맞춰도 승인은 한다(판정 때 다시 맞춘다)
                log.exception("map_metric failed: %s", criterion_id)
        if hit:
            cond["ledgerMetric"] = hit
    with Session(engine) as s:
        c = _row(s, criterion_id)
        if approve:
            for o in s.exec(select(Criterion).where(Criterion.key == c.key, Criterion.status == "active")).all():
                o.status, o.updated_at = "archived", utcnow()
                s.add(o)
            c.status, c.approved_by, c.approved_at, c.condition = "active", user.id, utcnow(), cond
            c.conflicts = code_conflicts(s, c)
        else:
            c.status = "rejected"
        if note:
            c.note = note[:300]
        c.updated_at = utcnow()
        s.add(c)
        s.commit()
        return view(s, c, user=user)


def versions(session: Session, criterion_id: str, user: User, workspace_id: str = "") -> List[Dict[str, Any]]:
    c = _row(session, criterion_id)
    _check_view(session, c, user, workspace_id or c.workspace_id)
    names = _names(session)
    rows = session.exec(select(Criterion).where(Criterion.key == c.key).order_by(Criterion.version.desc())).all()  # type: ignore[attr-defined]
    return [view(session, r, names, user) for r in rows]


def pending_count(session: Session, workspace_id: str, user: User) -> int:
    """이 사람이 승인할 수 있는 초안 수(홈 '오늘 확인할 것')."""
    rows = session.exec(select(Criterion).where(Criterion.status == "draft", Criterion.workspace_id.in_(["", workspace_id]))).all()  # type: ignore[attr-defined]
    return sum(1 for c in rows if can_approve(session, user, c.scope, c.workspace_id))
