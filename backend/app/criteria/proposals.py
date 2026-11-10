"""검토 제안 — 새 자료가 들어오면 판단 기준을 다시 판정하고(코드), 도달한 기준에 걸린 문서(승인·검토 중·작성 중)에 '○○ 검토 제안'을 낸다.

방향 = 그 기준의 방향(코드). 근거 셋 = 새 자료의 칸(판정 앵커) · 기준 원문과 판 · 과거 결정 문장. 여유 = 한도 기준의 남은 폭(코드).
LLM 은 1회 — 설명 2~3문장과 고칠 문장만. 코드가 확인한다: 숫자는 원문·판정 값·여유·기준 인용에 있는 숫자만, 결정·권고 낱말(매수·매도·추천…)은 버린다.
제안을 내는 때: 도달이면서 ① 판정 근거가 이번에 들어온 자료이거나 ② 지난 판정에서 바뀌었을 때(처음 판정은 기준선 — 제안 없음). 같은 문서·기준·대상·기간은 한 번만.
사람이 [문서에 반영](고친 문장 바꾸기 — 반영 전 판을 남긴다) · [재심의 안건 초안](백그라운드) · [닫기]를 한다. 투자 결정은 IWC·IC 가 한다.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select

from app.anchors import pin, pin_section
from app.assumptions.extract import _sentences_report
from app.auth import require_member
from app.criteria.extract import _json
from app.criteria.match import DIRECTION_KO, SCOPE_KO, active, applies_to, condition_text, evaluate, headroom, same_target, target_key
from app.db import COMPANY_SCOPE, Assumption, Criterion, ReportSession, ReviewProposal, User, Workspace, engine, iso, scope_ids, utcnow
from app.docs.citations import normalize, tokens
from app.docs.store import doc_label, load_meta, search_docs
from app.ids import id36, now_iso
from app.llm.base import ChatParams
from app.notify import notify

log = logging.getLogger(__name__)
MAX_REPORTS = 10
MAX_SENTENCES = 6
FORBID = re.compile(r"매수|매도|추천한다|추천합니다|권고한다|권고합니다|결정했다|결정한다|결정합니다|해야 한다")
METRIC_WORDS = re.compile(r"매출|성장|증가율|비중|이익|한도|확대|축소|유지|논거|전망|실적|bp|%")
DECISION = re.compile(r"승인|의결|결정")
ACTION = re.compile(r"\d+\s*bp|비중을|늘린다|줄인다|늘리기로|줄이기로|확대한다|축소한다|맞춘다|편입한다|매각한다|승인")  # 결정·행동 문장 — 고치지 않는다
HOLDS = re.compile(r"유지되고 있|유지된다|유지하고 있|충족|변함없|여전히 유효|문제없")  # 도달(전제 깨짐)인데 그대로라는 말
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
STATUS_KO = {"open": "열림", "applied": "반영함", "agenda": "재심의 안건", "dismissed": "닫음"}

PROMPT = """판단 기준에 걸린 문서 문장들이 있다. 방향은 이미 정해져 있다 — '{direction} 검토 제안'. 방향을 바꾸지 말고, 결정·권고(매수·매도·추천·'해야 한다')로 쓰지 않는다.
JSON 하나로만 답한다(설명 없이):
{{"explanation": "이 검토가 왜 필요한지 2~3문장 — 숫자는 아래 '지금 값'·'기준'·'여유'에 있는 것만", "edits": [{{"n": 문장 번호, "revised": "지금 값을 반영해 고친 그 문장 하나", "why": "한 줄"}}]}}
규칙: 지금 값과 어긋나 고칠 필요가 있는 사실 문장만 edits 에 넣는다. 비중·bp·승인 같은 결정 문장은 고치지 않는다(결정은 사람이 한다).
고친 문장은 사실(값·기간)과 기준 대비 결과를 사실대로 담는 데까지만 — 예: '30% 이상 성장' 논거에 기댄 문장은 '2026년 3분기 24.0%로 기준 30%에 못 미쳤다'처럼.
값이 바뀌어 '논거가 유지되고 있다' 같은 판단이 더는 맞지 않으면 그 판단을 사실로 바꾼다. '검토 제안'·'재심의' 같은 제안 문구는 넣지 않는다(제안은 따로 보인다).
숫자는 아래에 있는 값만 쓴다. 기간은 '2026Q3' 대신 '2026년 3분기'처럼 쓴다."""


def _norm(s: Any) -> str:
    return re.sub(r"[\s·\-_()]+", "", str(s or "")).lower()


def _nums(text: str) -> List[float]:
    out = []
    for m in NUM.findall(text or ""):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            continue
    return out


def numbers_ok(text: str, allowed: Sequence[str]) -> bool:
    """글의 숫자가 모두 허용 글들에 나오는가(소수 반올림 차이는 0.05 안)."""
    pool = [n for t in allowed for n in _nums(t)]
    return all(any(abs(n - p) < 0.051 for p in pool) for n in _nums(text))


# ── 걸린 문서 찾기 ──────────────────────────────────────────────────────

def _mentions(text: str, target: Dict[str, Any]) -> bool:
    t = _norm(text)
    name, ticker = _norm(target.get("name"))[:10], _norm(target.get("ticker"))
    return bool((name and name in t) or (ticker and len(ticker) >= 3 and ticker in t))


def affected_reports(session: Session, workspace_id: str, target: Dict[str, Any], metric: str = "") -> List[Dict[str, Any]]:
    """그 대상을 다룬 문서(승인·검토 중·작성 중) → 걸린 문장들. 그 대상의 문서 가정이 있는 문장 + 대상을 다룬 섹션의 지표·비중 문장. 재심의 안건 초안 자신은 뺀다."""
    asm = [a for a in session.exec(select(Assumption).where(Assumption.workspace_id == workspace_id, Assumption.doc_kind == "report", Assumption.status != "dismissed")).all()
           if same_target(a.target or {}, target)]
    asm_quotes: Dict[str, List[str]] = {}
    for a in asm:
        asm_quotes.setdefault(a.doc_ref, []).append(_norm(a.quote))
    mtoks = [w for w in re.findall(r"[가-힣]{2,}|[A-Za-z]{3,}", metric or "") if w not in ("비중", "증가율")]
    out = []
    for r in session.exec(select(ReportSession).where(ReportSession.workspace_id == workspace_id).order_by(ReportSession.updated_at.desc())).all():  # type: ignore[attr-defined]
        doc = r.doc or {}
        org = doc.get("origin") or {}
        if org.get("proposal") or org.get("assumption"):
            continue
        by_title = _mentions(f"{r.title} {json.dumps(doc.get('setup') or {}, ensure_ascii=False)}", target)
        sec_hit = {s["step"] for s in doc.get("sections") or [] if _mentions(f"{s.get('title') or ''} {s.get('content') or ''}", target)}
        if not (by_title or sec_hit or r.id in asm_quotes):
            continue
        cands: List[Tuple[int, str, str, str]] = []
        for step, raw, plain in _sentences_report(doc):
            via_asm = any(q and q in _norm(plain) for q in asm_quotes.get(r.id, []))
            if not via_asm and not (METRIC_WORDS.search(plain) and (by_title or step in sec_hit or _mentions(plain, target))):
                continue
            score = (3 if via_asm else 0) + (2 if any(w.lower() in plain.lower() for w in mtoks) else 0) + (1 if _mentions(plain, target) else 0)
            cands.append((score, step, raw, plain))
        cands.sort(key=lambda x: -x[0])
        if cands:
            out.append({"row": r, "via": "assumption" if r.id in asm_quotes else "mention", "sentences": [(st, raw, pl) for _s, st, raw, pl in cands[:MAX_SENTENCES]]})
        if len(out) >= MAX_REPORTS:
            break
    return out


def _decision_in(doc: Dict[str, Any], title: str, session_id: str) -> Optional[Dict[str, Any]]:
    for step, _raw, plain in _sentences_report(doc):
        if DECISION.search(plain):
            return {"title": title, "quote": plain[:240], "anchor": {"kind": "report", "sessionId": session_id, "step": step, "quote": plain[:240]}}
    return None


def decision_evidence(doc: Dict[str, Any], title: str, doc_ids: List[str], target: Dict[str, Any], workspace_id: str = "") -> Optional[Dict[str, Any]]:
    """과거 결정 문장(LLM 0회, 원문 고정) — 그 문서 안의 '승인·결정' 문장 → 같은 워크스페이스에서 그 대상을 다룬 승인 문서(IWC 안건 등)
    → 자료(회의록 등)에서 '대상 + 승인' 문장(문단이나 그 제목 줄·문서 이름에 대상이 나올 때)."""
    got = _decision_in(doc, title, doc.get("id") or "")
    if got:
        return got
    if workspace_id:
        with Session(engine) as s:
            rows = s.exec(select(ReportSession).where(ReportSession.workspace_id == workspace_id, ReportSession.id != (doc.get("id") or ""))).all()
            rows = sorted(rows, key=lambda r: ((r.doc or {}).get("approval") or {}).get("status") != "approved")
            for r in rows:
                if (r.doc or {}).get("origin") or not _mentions(f"{r.title} {json.dumps((r.doc or {}).get('setup') or {}, ensure_ascii=False)}", target):
                    continue
                got = _decision_in(r.doc or {}, r.title or "문서", r.id)
                if got:
                    return got
    name = target.get("name") or target.get("ticker") or ""
    if not name:
        return None
    for h in search_docs(doc_ids, f"{name} 비중 승인 결정", k=8, per_doc=3):
        text = h["chunk"].get("text") or ""
        if not (_mentions(f"{text} {h['chunk'].get('heading') or ''}", target) or _mentions(doc_label(load_meta(h["docId"]), h["docId"]), target)):
            continue
        for sent in re.split(r"(?<=[.!?。])\s+|\n+", text):
            if DECISION.search(sent) and len(sent.strip()) >= 10:
                a = pin(h["docId"], h["chunk"]["id"], quote=sent.strip())
                return {"title": doc_label(load_meta(h["docId"]), h["docId"]), "quote": sent.strip()[:240], "anchor": a}
    return None


# ── 제안 만들기 ─────────────────────────────────────────────────────────

def _code_text(c: Optional[Criterion], target: Dict[str, Any], res: Dict[str, Any], hr: List[Dict[str, Any]], direction: str) -> Tuple[str, str]:
    """(바뀐 것 한 줄, 코드 설명) — LLM 이 실패해도 제안은 이 글로 낸다."""
    disp = (res.get("value") or {}).get("display") or ""
    name = target.get("name") or target.get("ticker") or "대상"
    changed = f"{name} {disp}" + (f" — 기준 '{c.title}' v{c.version} 조건({condition_text(c)}) 도달" if c else "")
    parts = [f"{name}의 지금 값({disp})이 " + (f"'{c.title}' 기준 조건에 도달해" if c else "문서 가정과 어긋나"), f"{DIRECTION_KO.get(direction, direction)} 검토가 필요합니다."]
    if any(not h["within"] for h in hr):
        parts.append(" ".join(h["display"] for h in hr if not h["within"]) + ".")
    return changed, " ".join(parts)


async def _llm_text(llm: Any, c: Optional[Criterion], target: Dict[str, Any], res: Dict[str, Any], hr: List[Dict[str, Any]], direction: str, title: str,
                    sentences: List[Tuple[str, str, str]]) -> Tuple[str, Dict[int, Dict[str, str]]]:
    disp = (res.get("value") or {}).get("display") or ""
    crit = f"## 기준 ({SCOPE_KO.get(c.scope, c.scope)} v{c.version}) {c.title}: {condition_text(c)} → {DIRECTION_KO.get(c.direction, c.direction)} — 원문 “{(c.source or {}).get('quote', '')}”" if c else "## 기준 — 문서 가정"
    lines = [PROMPT.format(direction=DIRECTION_KO.get(direction, direction)), crit, f"## 지금 값(코드 판정) {target.get('name') or ''} {disp} — 도달",
             "## 여유 " + (" / ".join(h["display"] for h in hr) or "없음"), f"## 문서 '{title}' 문장"]
    lines += [f"[{i + 1}] {plain}" for i, (_s, _r, plain) in enumerate(sentences)]
    res2 = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": "\n".join(lines)}], temperature=0, max_tokens=2500, reasoning_effort="low", timeout_s=180))
    got = _json(getattr(res2, "content", "") or "")
    allowed = [disp, *(h["display"] for h in hr), condition_text(c) if c else "", (c.source or {}).get("quote", "") if c else ""]
    expl = str(got.get("explanation") or "").strip()
    if not expl or FORBID.search(expl) or not numbers_ok(expl, allowed):
        expl = ""
    edits: Dict[int, Dict[str, str]] = {}
    for e in got.get("edits") or []:
        try:
            n = int(e.get("n"))
        except (TypeError, ValueError):
            continue
        if not (1 <= n <= len(sentences)):
            continue
        rev = str(e.get("revised") or "").strip()
        if not revision_ok(sentences[n - 1][2], rev, allowed):
            rev = ""
        edits[n] = {"revised": rev, "why": str(e.get("why") or "").strip()[:160]}
    return expl, edits


def revision_ok(original: str, revised: str, allowed: Sequence[str]) -> bool:
    """고친 문장을 받아도 되는가 — 숫자는 허용 값만, 단정·권고 낱말 없음, 결정 문장(비중·bp·늘린다…)은 고치지 않음(결정은 사람),
    새 행동을 더하지 않음, 기준에 도달했는데(전제가 깨짐) '유지되고 있다'처럼 전제가 그대로라고 쓰지 않음."""
    if not revised or FORBID.search(revised) or not numbers_ok(revised, [*allowed, original]):
        return False
    if ACTION.search(original) or (ACTION.search(revised) and not ACTION.search(original)):
        return False
    return not HOLDS.search(revised)


def _revised_raw(raw: str, revised: str, res: Dict[str, Any]) -> str:
    """고친 문장 + 원래 인용 토큰 + 새 판정 근거 토큰(문장 끝 마침표 앞)."""
    toks = list(dict.fromkeys([*tokens(raw), *((a["docId"], a["chunk"]) for a in res.get("anchors") or [] if a and a.get("docId") and a.get("chunk"))]))
    text = re.sub(r"\[@[^\]]+\]", "", revised).strip()
    end = "." if not re.search(r"[.!?。]$", text) else ""
    return normalize(text + end + "".join(f"[@{d}#{c}]" for d, c in toks))


async def make_for_target(workspace_id: str, target: Dict[str, Any], doc_ids: List[str], as_of: Optional[str], trigger: Dict[str, Any],
                          new_docs: Optional[List[str]] = None) -> int:
    """대상 하나 — 기준 판정 → 도달·새 근거·바뀜이면 걸린 문서마다 제안. → 만든 수"""
    from app.llm.client import ReportLlm

    tk = target_key(target)
    hits: List[Tuple[Criterion, Dict[str, Any]]] = []
    with Session(engine) as s:
        crits = [c for c in active(s, workspace_id) if c.kind == "numeric" and applies_to(c, target)]
        for c in crits:
            res = evaluate(c, target, doc_ids, as_of)
            prev = ((c.latest or {}).get(tk) or {}).get("result")
            c.latest = {**(c.latest or {}), tk: {"result": res["result"], "display": (res.get("value") or {}).get("display"), "asOf": as_of, "at": iso(utcnow())}}
            s.add(c)
            if res["result"] != "reached":
                continue
            new_basis = bool(new_docs) and any((a or {}).get("docId") in set(new_docs or []) for a in res.get("anchors") or [])
            if new_basis or (prev is not None and prev != "reached"):
                hits.append((c.model_copy(), res))
        s.commit()
        if not hits:
            return 0
        hr = headroom(crits, target, doc_ids, as_of)
        groups = {c.key: affected_reports(s, workspace_id, target, (c.condition or {}).get("metric") or "") for c, _r in hits}
    llm = ReportLlm()
    made = 0
    for c, res in hits:
        period = (res.get("value") or {}).get("period") or as_of or ""
        for g in groups.get(c.key) or []:
            r: ReportSession = g["row"]
            dedupe = f"{r.id}|{c.key}|{tk}|{period}"
            with Session(engine) as s:
                if s.exec(select(ReviewProposal.id).where(ReviewProposal.dedupe == dedupe)).first():
                    continue
            changed, code_expl = _code_text(c, target, res, hr, c.direction)
            try:
                expl, edits = await _llm_text(llm, c, target, res, hr, c.direction, r.title or "문서", g["sentences"])
            except Exception:  # noqa: BLE001 — 설명을 못 받아도 제안은 낸다(코드 문구로)
                log.exception("proposal text failed: %s", r.id)
                expl, edits = "", {}
            sents = []
            for i, (step, raw, plain) in enumerate(g["sentences"]):
                e = edits.get(i + 1)
                if e is None:
                    continue
                sents.append({"step": step, "original": raw, "plain": plain, "revised": _revised_raw(raw, e["revised"], res) if e["revised"] else None, "why": e["why"]})
            if not sents:  # 고칠 문장을 못 받았으면 가장 걸린 문장 하나만 '걸림'으로
                step, raw, plain = g["sentences"][0]
                sents = [{"step": step, "original": raw, "plain": plain, "revised": None, "why": ""}]
            with Session(engine) as s:
                ws_ids = scope_ids(s.get(Workspace, workspace_id))
            dec = decision_evidence({**(r.doc or {}), "id": r.id}, r.title or "문서", ws_ids, target, workspace_id)
            p = ReviewProposal(id=id36("rp", 4), workspace_id=workspace_id, report_id=r.id, criterion_id=c.id, dedupe=dedupe, target=dict(target), direction=c.direction,
                               check={"result": res["result"], "value": res.get("value") or {}, "anchors": res.get("anchors") or [], "asOf": as_of},
                               headroom=hr, changed=changed, explanation=expl or code_expl, sentences=sents,
                               evidence={"data": res.get("anchors") or [], "criterion": {"id": c.id, "key": c.key, "version": c.version, "title": c.title, "scope": c.scope,
                                                                                       "quote": (c.source or {}).get("quote"), "anchor": (c.source or {}).get("anchor"), "docTitle": (c.source or {}).get("docTitle")},
                                         "decision": dec},
                               trigger={**trigger, "at": now_iso()})
            with Session(engine) as s:
                s.add(p)
                s.commit()
                _notify(s, p, r)
            made += 1
    return made


def _notify(session: Session, p: ReviewProposal, r: ReportSession) -> None:
    to = [r.created_by]
    for a in session.exec(select(Assumption).where(Assumption.doc_ref == r.id, Assumption.status != "dismissed")).all():
        to += [a.watched_by or "", a.created_by]
    crit = (p.evidence or {}).get("criterion") or {}
    notify(to, workspace_id=p.workspace_id, kind="proposal", title=f"{DIRECTION_KO.get(p.direction, p.direction)} 검토 제안 — {r.title or '문서'}"[:200],
           body=f"{p.changed[:200]} · 기준 {crit.get('title', '')} v{crit.get('version', '')}", link={"w": p.workspace_id, "v": "reports", "s": r.id},
           ref={"kind": "proposal", "id": p.id, "reportId": r.id}, dedupe_key=f"proposal:{p.id}")


def targets_of(session: Session, workspace_id: str) -> List[Dict[str, Any]]:
    """이 워크스페이스가 보는 대상 — 사용 중 기준의 대상 + 문서 가정의 대상(중복 없이)."""
    seen: Dict[str, Dict[str, Any]] = {}
    for c in active(session, workspace_id):
        ap = c.applies or {}
        if ap.get("name") or ap.get("ticker"):
            seen.setdefault(target_key(ap), {"name": ap.get("name") or "", "ticker": ap.get("ticker") or ""})
    for a in session.exec(select(Assumption).where(Assumption.workspace_id == workspace_id, Assumption.status != "dismissed")).all():
        t = a.target or {}
        if t.get("name") or t.get("ticker"):
            seen.setdefault(target_key(t), {"name": t.get("name") or "", "ticker": t.get("ticker") or ""})
    return [t for k, t in seen.items() if k]


async def on_new_docs(new_docs: List[str], trigger: Dict[str, Any], workspace_id: Optional[str] = None, as_of: Optional[str] = None) -> int:
    """새 자료(수집·업로드) → 그 자료가 범위에 든 워크스페이스마다 대상별 판정·제안. 가정 다시 판정 뒤(assumptions.watch)에 부른다."""
    from app.assistants.guideline import portfolio_doc
    from app.assumptions.judge import entity_docs

    if not new_docs:
        return 0
    with Session(engine) as s:
        q = select(Workspace)
        if workspace_id and workspace_id != COMPANY_SCOPE:
            q = q.where(Workspace.id == workspace_id)
        plan = []
        for w in s.exec(q).all():
            ids = scope_ids(w)
            fresh = [d for d in new_docs if d in set(ids)]
            if not fresh:
                continue
            port = bool(portfolio_doc(fresh))
            plan += [(w.id, t, ids) for t in targets_of(s, w.id) if port or entity_docs(t, fresh)]
    n = 0
    for ws_id, t, ids in plan:
        try:
            n += await make_for_target(ws_id, t, ids, as_of, trigger, new_docs)
        except Exception:  # noqa: BLE001
            log.exception("proposal scan failed: %s %s", ws_id, t)
    return n


async def scan(workspace_id: str, user: User, as_of: Optional[str] = None) -> Dict[str, Any]:
    """수동 다시 확인(시연·점검) — 이 워크스페이스의 대상 모두. 처음 판정은 기준선이라 제안을 내지 않는다(바뀌었을 때만)."""
    with Session(engine) as s:
        ws, _m = require_member(s, workspace_id, user, "editor")
        ids, targets = scope_ids(ws), targets_of(s, workspace_id)
    n = 0
    for t in targets:
        n += await make_for_target(workspace_id, t, ids, as_of, {"kind": "manual", "by": user.id, "asOf": as_of})
    return {"proposals": n, "targets": len(targets)}


# ── 보기·반영·안건·닫기 ─────────────────────────────────────────────────

def view(session: Session, p: ReviewProposal, user: Optional[User] = None, report: Optional[ReportSession] = None) -> Dict[str, Any]:
    r = report or session.get(ReportSession, p.report_id)
    owner = bool(user) and r is not None and r.created_by == user.id  # type: ignore[union-attr]
    approved = r is not None and ((r.doc or {}).get("approval") or {}).get("status") == "approved"  # 승인된 기록은 고치지 않고 재심의 안건으로
    crit = (p.evidence or {}).get("criterion") or {}
    return {"id": p.id, "workspaceId": p.workspace_id, "reportId": p.report_id, "reportTitle": (r.title if r else "") or "문서", "target": p.target,
            "direction": p.direction, "directionKo": DIRECTION_KO.get(p.direction, p.direction), "criterion": crit, "check": p.check, "headroom": p.headroom,
            "changed": p.changed, "explanation": p.explanation, "sentences": p.sentences, "evidence": p.evidence, "status": p.status, "statusKo": STATUS_KO.get(p.status, p.status),
            "result": p.result, "createdAt": iso(p.created_at), "decidedAt": iso(p.decided_at),
            "approved": approved, "canApply": owner and not approved and p.status == "open" and any(x.get("revised") for x in p.sentences or []), "canAct": p.status in ("open", "applied")}


def listing(session: Session, workspace_id: str, user: User, report_id: Optional[str] = None, status: Optional[str] = "open") -> List[Dict[str, Any]]:
    require_member(session, workspace_id, user)
    q = select(ReviewProposal).where(ReviewProposal.workspace_id == workspace_id)
    if report_id:
        q = q.where(ReviewProposal.report_id == report_id)
    if status and status != "all":
        q = q.where(ReviewProposal.status.in_(status.split(",")))  # type: ignore[attr-defined]
    return [view(session, p, user) for p in session.exec(q.order_by(ReviewProposal.created_at.desc())).all()]  # type: ignore[attr-defined]


def today_items(session: Session, workspace_id: str, user: User) -> List[Dict[str, Any]]:
    """홈 '오늘 확인할 것' — 내가 쓴 문서에 열린 제안."""
    rows = session.exec(select(ReviewProposal).where(ReviewProposal.workspace_id == workspace_id, ReviewProposal.status == "open").order_by(ReviewProposal.created_at.desc())).all()  # type: ignore[attr-defined]
    out = []
    for p in rows:
        r = session.get(ReportSession, p.report_id)
        if r is None or r.created_by != user.id:
            continue
        out.append({"id": p.id, "reportId": p.report_id, "reportTitle": r.title or "문서", "directionKo": DIRECTION_KO.get(p.direction, p.direction), "changed": p.changed,
                    "criterion": ((p.evidence or {}).get("criterion") or {}).get("title"), "createdAt": iso(p.created_at)})
    return out[:8]


def _row(session: Session, proposal_id: str) -> ReviewProposal:
    p = session.get(ReviewProposal, proposal_id)
    if p is None:
        raise HTTPException(404, "검토 제안을 찾지 못했습니다.")
    return p


def apply(session: Session, proposal_id: str, user: User, picks: Optional[List[int]] = None) -> Dict[str, Any]:
    """고친 문장을 문서에 넣는다(작성자만) — 반영 전 판을 남기고, 섹션 근거에 쓴 기준(판)을 적는다. 원문이 바뀐 문장은 건너뛴다."""
    from app.agent.session import find_section, log_section, save_version, set_section
    from app.services.report_service import ReportService, _busy

    p = _row(session, proposal_id)
    if p.status != "open":
        raise HTTPException(409, "이미 처리한 제안입니다.")
    svc = ReportService(session)
    row = svc.access(p.report_id, user, write=True)
    if ((row.doc or {}).get("approval") or {}).get("status") == "approved":
        raise HTTPException(409, "승인된 문서는 고치지 않습니다. 재심의 안건으로 다뤄 주세요.")
    if p.report_id in _busy:
        raise HTTPException(409, "이 문서에서 아직 앞선 요청을 처리하고 있습니다.")
    doc = copy.deepcopy(row.doc or {})
    crit = (p.evidence or {}).get("criterion") or {}
    v = save_version(doc, "검토 제안 반영 전")
    done = 0
    for i, sx in enumerate(p.sentences or []):
        if picks is not None and i not in picks or not sx.get("revised"):
            continue
        sec = find_section(doc, sx.get("step"))
        if sec is None or sx["original"] not in (sec.get("content") or ""):
            continue  # 그 사이 사람이 고친 문장
        ev = copy.deepcopy((doc.get("evidence") or {}).get(sec["step"]) or {})
        ev["criteria"] = [*(ev.get("criteria") or []), {"id": crit.get("id"), "key": crit.get("key"), "version": crit.get("version"), "via": "proposal", "proposalId": p.id}]
        set_section(doc, sec["step"], (sec.get("content") or "").replace(sx["original"], sx["revised"], 1), ev)
        pin_section(doc, sec)
        log_section(doc, sec["step"], f"검토 제안 반영 — {crit.get('title', '')} v{crit.get('version', '')}")
        done += 1
    if not done:
        raise HTTPException(409, "문장이 바뀌어 반영할 수 없습니다. 문서에서 직접 고쳐 주세요.")
    svc.persist(row, doc)
    p = _row(session, proposal_id)
    p.status, p.decided_by, p.decided_at, p.result = "applied", user.id, utcnow(), {**(p.result or {}), "versionId": v["id"], "applied": done}
    session.add(p)
    session.commit()
    return view(session, p, user)


def dismiss(session: Session, proposal_id: str, user: User, note: str = "") -> Dict[str, Any]:
    p = _row(session, proposal_id)
    require_member(session, p.workspace_id, user, "editor")
    p.status, p.decided_by, p.decided_at = "dismissed", user.id, utcnow()
    p.result = {**(p.result or {}), "note": note[:300]}
    session.add(p)
    session.commit()
    return view(session, p, user)


def start_agenda(proposal_id: str, user: User) -> Dict[str, Any]:
    """재심의 안건 초안 — 백그라운드에서 쓰고, 다 쓰면 부른 사람에게 알린다."""
    from app import scheduler

    with Session(engine) as s:
        p = _row(s, proposal_id)
        _ws, m = require_member(s, p.workspace_id, user, "editor")
        ws_id = p.workspace_id
    if not scheduler.spawn("proposal_agenda", _agenda_run(proposal_id, user.id), ws_id):
        raise HTTPException(409, "다른 재심의 안건을 쓰는 중입니다. 끝나면 알림이 옵니다.")
    with Session(engine) as s:
        p = _row(s, proposal_id)
        p.result = {**(p.result or {}), "agendaStatus": "writing"}
        s.add(p)
        s.commit()
        return view(s, p, user)


async def _agenda_run(proposal_id: str, user_id: str) -> None:
    from app.headless import write_report
    from app.seed_formats import type_id

    with Session(engine) as s:
        p = _row(s, proposal_id).model_copy()
        r = s.get(ReportSession, p.report_id)
        rtitle = (r.title if r else "") or "문서"
    crit = (p.evidence or {}).get("criterion") or {}
    dec = (p.evidence or {}).get("decision") or {}
    name = (p.target or {}).get("name") or rtitle
    brief = "\n".join([
        f"[재심의 대상] 원 문서 '{rtitle}' — {name}",
        f"[판단 기준] {SCOPE_KO.get(crit.get('scope') or '', '')} '{crit.get('title', '')}' v{crit.get('version', '')}: “{crit.get('quote') or ''}” → {DIRECTION_KO.get(p.direction, p.direction)} 검토",
        f"[지금 값] {p.changed}",
        "[여유] " + (" / ".join(h.get("display", "") for h in p.headroom or []) or "없음"),
        f"[과거 결정] {dec.get('quote') or '원 문서의 결정 문장'}",
        "[걸린 문장] " + " / ".join((x.get("plain") or "")[:120] for x in p.sentences or []),
        "숫자는 자료(공시 원문 표 칸·보유 내역 칸)를 인용해 쓴다. 투자 결정은 쓰지 말고 선택지와 확인할 점만.",
    ])
    res: Dict[str, Any] = {}
    try:
        res = await write_report(workspace_id=p.workspace_id, owner_id=user_id, format_id=type_id("kicrereview"), title=f"재심의 안건 — {name}"[:80],
                                 instruction="", extra_brief=brief, origin={"proposal": p.id, "criterion": crit.get("key")})
    except Exception as e:  # noqa: BLE001
        log.exception("proposal agenda failed: %s", proposal_id)
        res = {"error": str(e)[:200]}
    with Session(engine) as s:
        q = _row(s, proposal_id)
        out = {k: v for k, v in (q.result or {}).items() if k != "agendaStatus"}
        if res.get("sessionId"):
            out["agendaId"] = res["sessionId"]
            q.status = "agenda" if q.status == "open" else q.status
            q.decided_by, q.decided_at = q.decided_by or user_id, q.decided_at or utcnow()
        else:
            out["agendaStatus"] = "error"
        q.result = out
        s.add(q)
        s.commit()
    link = {"w": p.workspace_id, "v": "reports", "s": res["sessionId"]} if res.get("sessionId") else {"w": p.workspace_id, "v": "reports", "s": p.report_id}
    notify([user_id], workspace_id=p.workspace_id, kind="proposal", title=(f"재심의 안건 초안을 썼습니다 — {name}" if res.get("sessionId") else "재심의 안건을 쓰지 못했습니다")[:120],
           body=(f"섹션 {res.get('written')}/{res.get('sections')} · 기준 {crit.get('title', '')}" if res.get("sessionId") else str(res.get("error") or ""))[:200], link=link,
           ref={"kind": "report", "id": res["sessionId"]} if res.get("sessionId") else {"kind": "proposal", "id": p.id, "reportId": p.report_id})
