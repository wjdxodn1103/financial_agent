"""가정 감시 — 문서 속 가정 문장(별도 메뉴 없음): 뽑기 → 사람이 [감시] 켜기 → 새 자료가 오면 다시 판정 → 결과가 바뀌면 문서·알림·홈에.
가정(role 없음) = 맞아야 하는 전망 → 충족·미충족 / 재심의 조건(role=trigger) = 그렇게 되면 다시 심의 → 도달·미도달. 어느 쪽이든 '살펴볼 결과'(alert)는
가정의 미충족·반박, 재심의 조건의 도달이다. [재심의 안건] 은 깨진 가정·당시 근거·지금 값을 넣어 '재심의 안건(예시)' 양식으로 백그라운드에서 쓰고 알린다.
알림은 문서 만든 사람 + 감시를 켠 사람에게 간다. 상태 바꾸기(감시·버리기·넘기기)는 사람이 한다.
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.assumptions import judge
from app.assumptions.extract import doc_title, extract
from app.auth import require_member
from app.db import Assumption, AssumptionCheck, CompanyDocument, IngestJob, Repo, ReportSession, User, engine, iso, scope_ids, utcnow
from app.ids import id36
from app.notify import notify

log = logging.getLogger(__name__)
RESULT_KO = {"met": "충족", "not_met": "미충족", "no_data": "자료 없음", "support": "지지", "refute": "반박", "hold": "보류", "unrelated": "관련 없음"}
TRIGGER_KO = {**RESULT_KO, "met": "도달", "not_met": "미도달", "support": "도달", "refute": "미도달"}
OP_KO = {">=": "이상", ">": "초과", "<=": "이하", "<": "미만", "==": "같음"}
PERIOD_KO = {"latest_q_yoy": "최근 분기 전년 대비", "latest_q": "최근 분기", "latest_fy": "최근 연도", "latest_fy_yoy": "최근 연도 전년 대비"}
USED_KO = {"latest_q_yoy": "분기 자료로 판정", "latest_q": "분기 자료로 판정", "latest_fy": "연간 자료로 판정", "latest_fy_yoy": "연간 자료로 판정"}


def role_ko(a: Assumption) -> str:
    return "재심의 조건" if a.role == "trigger" else "가정"


def result_ko(a: Assumption, result: Optional[str]) -> str:
    return (TRIGGER_KO if a.role == "trigger" else RESULT_KO).get(result or "", result or "")


def is_alert(a: Assumption, result: Optional[str]) -> bool:
    """살펴볼 결과 — 가정이 깨졌거나(미충족·반박) 재심의 조건에 도달했거나"""
    return result in (("met", "support") if a.role == "trigger" else ("not_met", "refute"))


def needs_look(a: Assumption) -> bool:
    lt = a.latest or {}
    return bool(lt) and not lt.get("acknowledged") and bool(lt.get("changed") or is_alert(a, lt.get("result")))


def condition_text(a: Assumption) -> str:
    c = a.condition or {}
    if a.kind != "numeric" or not c:
        return "정성(새 자료 문단으로 판정)"
    parts = [str(c.get("ledgerMetric") or c.get("metric") or "")]
    if c.get("period") in PERIOD_KO:
        parts.append(PERIOD_KO[c["period"]])
    th = c.get("threshold")
    parts.append(f"{th:g}{c.get('unit') or ''} {OP_KO.get(c.get('op') or '>=', '')}" if isinstance(th, (int, float)) else f"{th}{c.get('unit') or ''} {OP_KO.get(c.get('op') or '>=', '')}")
    text = " · ".join(p for p in parts[:-1] if p) + " " + parts[-1]
    used = c.get("periodUsed")
    return f"{text} · {USED_KO.get(used, used)}" if used and used != c.get("period") else text


def _doc_ids(session: Session, workspace_id: str) -> List[str]:
    return scope_ids(Repo(session).workspace(workspace_id))


def doc_owner(session: Session, a: Assumption) -> str:
    """문서를 만든 사람 — AI 작업 문서는 만든 사람, 올린 자료는 올린 사람(사내 공용은 넣은 사람)."""
    if a.doc_kind == "report":
        r = session.get(ReportSession, a.doc_ref)
        return (r.created_by if r else "") or ""
    job = session.exec(select(IngestJob).where(IngestJob.doc_id == a.doc_ref).order_by(IngestJob.created_at.desc())).first()
    if job and job.uploaded_by:
        return job.uploaded_by
    cd = session.get(CompanyDocument, a.doc_ref)
    return (cd.added_by if cd else "") or ""


def recipients(session: Session, a: Assumption) -> List[str]:
    return [u for u in dict.fromkeys([doc_owner(session, a), a.watched_by or "", a.created_by]) if u][:3]


def view(session: Session, a: Assumption, title: str = "") -> Dict[str, Any]:
    checks = session.exec(select(AssumptionCheck).where(AssumptionCheck.assumption_id == a.id).order_by(AssumptionCheck.at.desc()).limit(10)).all()
    lt = a.latest or {}
    return {"id": a.id, "docKind": a.doc_kind, "docRef": a.doc_ref, "docTitle": title, "step": a.step, "quote": a.quote, "anchor": a.anchor, "target": a.target, "kind": a.kind, "condition": a.condition,
            "role": a.role or "assumption", "roleKo": role_ko(a), "conditionText": condition_text(a), "basis": a.basis, "watch": a.watch, "status": a.status,
            "latest": {**lt, "resultKo": result_ko(a, lt.get("result")), "prevKo": result_ko(a, lt.get("prev")) if lt.get("prev") else None, "alert": is_alert(a, lt.get("result"))} if lt else None,
            "history": [{"id": c.id, "at": iso(c.at), "asOf": c.as_of, "result": c.result, "resultKo": result_ko(a, c.result), "value": c.value, "anchors": c.anchors, "changed": c.changed, "trigger": c.trigger} for c in checks]}


def _title_of(session: Session, a: Assumption) -> str:
    if a.doc_kind == "report":
        r = session.get(ReportSession, a.doc_ref)
        return (r.title if r else "") or "문서"
    return doc_title("data", a.doc_ref)


def listing(session: Session, workspace_id: str, user: User, doc_ref: Optional[str] = None) -> List[Dict[str, Any]]:
    require_member(session, workspace_id, user)
    q = select(Assumption).where(Assumption.workspace_id == workspace_id, Assumption.status != "dismissed")
    if doc_ref:
        q = q.where(Assumption.doc_ref == doc_ref)
    rows = session.exec(q.order_by(Assumption.created_at)).all()
    titles: Dict[str, str] = {}
    out = []
    for a in rows:
        if a.doc_ref not in titles:
            titles[a.doc_ref] = _title_of(session, a)
        out.append(view(session, a, titles[a.doc_ref]))
    return out


async def run_extract(workspace_id: str, user: User, doc_kind: str, doc_ref: str) -> List[Dict[str, Any]]:
    from app.llm.client import ReportLlm

    with Session(engine) as s:
        require_member(s, workspace_id, user, "editor")
        report_doc = None
        if doc_kind == "report":
            r = s.get(ReportSession, doc_ref)
            if r is None or r.workspace_id != workspace_id:
                raise HTTPException(404, "문서를 찾지 못했습니다.")
            report_doc = copy.deepcopy(r.doc or {})
        elif doc_ref not in _doc_ids(s, workspace_id):
            raise HTTPException(404, "자료를 찾지 못했습니다.")
    found = await extract(ReportLlm(), doc_kind, doc_ref, report_doc)
    with Session(engine) as s:
        have = {x.quote for x in s.exec(select(Assumption).where(Assumption.doc_ref == doc_ref)).all()}
        for f in found:
            if f["quote"] in have:
                continue
            s.add(Assumption(id=id36("as", 4), workspace_id=workspace_id, doc_kind=doc_kind, doc_ref=doc_ref, created_by=user.id, **f))
        s.commit()
        return listing(s, workspace_id, user, doc_ref)


def update(session: Session, assumption_id: str, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
    a = session.get(Assumption, assumption_id)
    if a is None:
        raise HTTPException(404, "가정을 찾지 못했습니다.")
    require_member(session, a.workspace_id, user, "editor")
    if "watch" in body:
        a.watch = bool(body["watch"])
        a.status = "watching" if a.watch else "candidate"
        if a.watch:
            a.watched_by = user.id
    if "role" in body:
        a.role = "trigger" if body["role"] == "trigger" else None
    if body.get("dismiss"):
        a.status, a.watch = "dismissed", False
    if isinstance(body.get("condition"), dict) and a.kind == "numeric":
        c = {**(a.condition or {}), **{k: v for k, v in body["condition"].items() if k in ("metric", "ledgerMetric", "period", "op", "threshold", "unit")}}
        a.condition = c
    if body.get("acknowledge"):
        a.latest = {**(a.latest or {}), "acknowledged": True, "ackBy": user.id, "ackNote": str(body.get("note") or "")[:300], "ackAt": iso(utcnow())}
    a.updated_at = utcnow()
    session.add(a)
    session.commit()
    return view(session, a, _title_of(session, a))


async def check(assumption_id: str, as_of: Optional[str] = None, trigger: Optional[Dict[str, Any]] = None, notify_change: bool = True) -> Dict[str, Any]:
    from app.llm.client import ReportLlm

    with Session(engine) as s:
        a = s.get(Assumption, assumption_id)
        if a is None:
            raise HTTPException(404, "가정을 찾지 못했습니다.")
        snap = a.model_copy()
        doc_ids = _doc_ids(s, a.workspace_id)
    llm = ReportLlm()
    cond = dict(snap.condition or {})
    if snap.kind == "numeric":
        # 포트폴리오 비중 조건(단일 발행자·비상장·자산군)은 보유 내역 표로, 아니면 원장(공시·재무) 수치로
        res = judge.judge_portfolio(cond, snap.target or {}, doc_ids, as_of)
        if res is None:
            if not cond.get("ledgerMetric"):
                cands = judge.ledger_metrics(judge.entity_docs(snap.target or {}, doc_ids))
                hit = await judge.map_metric(llm, cond.get("metric") or "", cands)
                if hit:
                    cond["ledgerMetric"] = hit
            res = judge.judge_numeric(cond, snap.target or {}, doc_ids, as_of)
    else:
        res = await judge.judge_qualitative(snap.quote, snap.target or {}, doc_ids, llm, as_of, exclude=[snap.doc_ref])
    used = (res.get("value") or {}).get("rule")
    if snap.kind == "numeric" and used in PERIOD_KO and used != cond.get("period"):
        cond["periodUsed"] = used  # 적힌 기간은 그대로 두고, 자료에 맞춰 바꾼 기간을 따로(조건 문구에 '분기 자료로 판정')
    else:
        cond.pop("periodUsed", None)
    if used == "portfolio":
        cond.pop("period", None)  # 보유 내역은 기준일 하나 — 분기·연도 규칙이 없다
    prev = (snap.latest or {}).get("result")
    changed = bool(prev) and prev != res["result"]
    with Session(engine) as s:
        a = s.get(Assumption, assumption_id)
        s.add(AssumptionCheck(id=id36("ac", 5), assumption_id=assumption_id, as_of=as_of, trigger=trigger or {"kind": "manual"}, result=res["result"], value=res.get("value") or {},
                              anchors=[x for x in res.get("anchors") or [] if x], quote=res.get("quote") or "", prev_result=prev, changed=changed))
        a.condition = cond
        old = a.latest or {}
        pending = not changed and bool(old.get("changed") and not old.get("acknowledged")) and prev == res["result"]  # 아직 넘기지 않은 바뀜은 그대로(이전 판정도)
        a.latest = {**{k: old[k] for k in ("agendaId", "agendaStatus") if old.get(k)},
                    "result": res["result"], "value": res.get("value") or {}, "at": iso(utcnow()), "asOf": as_of, "changed": changed or pending,
                    "acknowledged": False if changed else bool(old.get("acknowledged")), "anchors": [x for x in res.get("anchors") or [] if x], "prev": old.get("prev") if pending else prev}
        a.updated_at = utcnow()
        s.add(a)
        s.commit()
        title = _title_of(s, a)
        out = view(s, a, title)
        to = recipients(s, a)
    if changed and notify_change and snap.watch:
        _notify_change(snap, to, prev, res, as_of, title)
    return out


def _link(a: Assumption) -> Dict[str, Any]:
    return {"w": a.workspace_id, "v": "reports", "s": a.doc_ref} if a.doc_kind == "report" else {"w": a.workspace_id, "v": "documents"}


def _notify_change(snap: Assumption, to: List[str], prev: Optional[str], res: Dict[str, Any], as_of: Optional[str], title: str) -> None:
    now = res["result"]
    head = f"재심의 조건 {result_ko(snap, now)}" if snap.role == "trigger" and is_alert(snap, now) else f"{role_ko(snap)} 판정 바뀜 — {result_ko(snap, prev)} → {result_ko(snap, now)}"
    notify(to, workspace_id=snap.workspace_id, kind="assumption", title=head,
           body=f"“{snap.quote[:120]}” · 지금 {(res.get('value') or {}).get('display', '')} · {title}", link=_link(snap),
           ref={"kind": "assumption", "id": snap.id, "docRef": snap.doc_ref, "docKind": snap.doc_kind, "title": title}, dedupe_key=f"assume:{snap.id}:{now}:{as_of or ''}")


def start_agenda(assumption_id: str, user: User) -> Dict[str, Any]:
    """재심의 안건 초안 — 백그라운드에서 쓰고, 다 쓰면 부른 사람에게 알린다(몇 분 걸린다)."""
    from app import scheduler

    with Session(engine) as s:
        a = s.get(Assumption, assumption_id)
        if a is None:
            raise HTTPException(404, "가정을 찾지 못했습니다.")
        require_member(s, a.workspace_id, user, "editor")
        ws_id = a.workspace_id
    if not scheduler.spawn("assumption_agenda", _agenda_run(assumption_id, user.id), ws_id):
        raise HTTPException(409, "다른 재심의 안건을 쓰는 중입니다. 끝나면 알림이 옵니다.")
    with Session(engine) as s:
        a = s.get(Assumption, assumption_id)
        a.latest = {**(a.latest or {}), "agendaStatus": "writing"}
        s.add(a)
        s.commit()
        return view(s, a, _title_of(s, a))


async def _agenda_run(assumption_id: str, user_id: str) -> None:
    from app.headless import write_report
    from app.seed_formats import type_id

    with Session(engine) as s:
        a = s.get(Assumption, assumption_id)
        snap = a.model_copy()
        title = _title_of(s, a)
    lt = snap.latest or {}
    basis = "; ".join(f"{b.get('quote', '')[:100]}" for b in (snap.basis or [])[:3])
    brief = "\n".join([
        f"[재심의 대상] 원 문서 '{title}' 의 {role_ko(snap)}: “{snap.quote}”",
        f"[조건] {condition_text(snap)}",
        f"[당시 근거] {basis or '원 문서의 인용'}",
        f"[지금 판정] {result_ko(snap, lt.get('result'))} — {(lt.get('value') or {}).get('display', '')}",
        "숫자는 자료(공시 원문 표 칸·보유 내역 칸)를 인용해 쓴다. 투자 결정은 쓰지 말고 선택지와 확인할 점만.",
    ])
    res: Dict[str, Any] = {}
    try:
        res = await write_report(workspace_id=snap.workspace_id, owner_id=user_id, format_id=type_id("kicrereview"), title=f"재심의 안건 — {(snap.target or {}).get('name') or title}"[:80],
                                 instruction="", extra_brief=brief, origin={"assumption": snap.id})
    except Exception as e:  # noqa: BLE001
        log.exception("agenda failed: %s", assumption_id)
        res = {"error": str(e)[:200]}
    with Session(engine) as s:
        a = s.get(Assumption, assumption_id)
        lt2 = {k: v for k, v in (a.latest or {}).items() if k != "agendaStatus"}
        if res.get("sessionId"):
            lt2["agendaId"] = res["sessionId"]
        else:
            lt2["agendaStatus"] = "error"
        a.latest = lt2
        s.add(a)
        s.commit()
    if res.get("sessionId"):
        notify([user_id], workspace_id=snap.workspace_id, kind="assumption", title=f"재심의 안건 초안을 썼습니다 — {(snap.target or {}).get('name') or title}"[:120],
               body=f"섹션 {res.get('written')}/{res.get('sections')} · “{snap.quote[:80]}”", link={"w": snap.workspace_id, "v": "reports", "s": res["sessionId"]},
               ref={"kind": "report", "id": res["sessionId"]})
    else:
        notify([user_id], workspace_id=snap.workspace_id, kind="assumption", title="재심의 안건을 쓰지 못했습니다", body=str(res.get("error") or "")[:200],
               link=_link(snap), ref={"kind": "assumption", "id": snap.id, "docRef": snap.doc_ref, "docKind": snap.doc_kind, "title": title})


def today(session: Session, workspace_id: str, user: User) -> Dict[str, Any]:
    """홈 '오늘 확인할 것' — 판정이 바뀌었거나 살펴볼 결과(가정 미충족·재심의 조건 도달)인데 아직 넘기지 않은 감시 가정 + 루틴이 쓴 문서."""
    from app.dashboards.resolve import _routine_docs

    from app.criteria.proposals import today_items
    from app.criteria.service import pending_count

    require_member(session, workspace_id, user)
    rows = session.exec(select(Assumption).where(Assumption.workspace_id == workspace_id, Assumption.watch == True)).all()  # noqa: E712
    changed = [a for a in rows if needs_look(a)]
    return {"assumptions": [view(session, a, _title_of(session, a)) for a in changed], "watching": len(rows), "routineDocs": _routine_docs(workspace_id),
            "proposals": today_items(session, workspace_id, user), "criteriaPending": pending_count(session, workspace_id, user)}


def widget_items(workspace_id: str, user: User) -> List[Dict[str, Any]]:
    with Session(engine) as s:
        rows = s.exec(select(Assumption).where(Assumption.workspace_id == workspace_id, Assumption.watch == True)).all()  # noqa: E712
        rows.sort(key=lambda a: (not needs_look(a), a.updated_at), reverse=False)
        out = []
        for a in rows[:8]:
            lt = a.latest or {}
            out.append({"id": a.id, "quote": a.quote[:140], "docTitle": _title_of(s, a), "docRef": a.doc_ref, "docKind": a.doc_kind, "role": a.role or "assumption", "roleKo": role_ko(a),
                        "result": result_ko(a, lt.get("result")) or None, "condition": condition_text(a),
                        "value": (lt.get("value") or {}).get("display"), "changed": needs_look(a), "at": lt.get("at")})
        return out
