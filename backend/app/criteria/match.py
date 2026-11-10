"""판단 기준 판정(LLM 0회) — 기준의 조건을 가정 판정과 같은 코드(원장 수치·보유 내역)로 계산하고, 한도 기준이면 여유(한도까지 남은 폭)를 낸다.
조건이 참이면 '도달'(그 기준의 방향을 검토할 때). 대상(회사·자산)이 정해진 기준은 그 대상에만, 대상이 없는 기준(한도·일반 원칙)은 어느 대상에나 건다."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from sqlmodel import Session, select

from app.assumptions.judge import KO_EN, entity_docs, judge_numeric, judge_portfolio, ledger_metrics
from app.db import Criterion
from app.ledger.figures import metric_key

DIRECTION_KO = {"expand": "확대 검토", "hold": "유지", "reduce": "축소 검토", "review": "재심의"}
RESULT_KO = {"reached": "도달", "not_reached": "미도달", "no_data": "자료 없음", "qualitative": "정성(사람 판단)"}
SCOPE_KO = {"company": "사내", "workspace": "워크스페이스"}
OP_KO = {">=": "이상", ">": "초과", "<=": "이하", "<": "미만", "==": "같음"}
PERIOD_KO = {"latest_q_yoy": "최근 분기 전년 대비", "latest_q": "최근 분기", "latest_fy": "최근 연도", "latest_fy_yoy": "최근 연도 전년 대비"}


def _norm(s: Any) -> str:
    return re.sub(r"[\s·\-_()]+", "", str(s or "")).lower()


def same_target(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """이름 앞 10자나 티커가 같으면 같은 대상(심의 준비의 과거 가정 찾기와 같은 규칙)."""
    na, nb = _norm(a.get("name")), _norm(b.get("name"))
    ta, tb = _norm(a.get("ticker")), _norm(b.get("ticker"))
    return bool((ta and ta == tb) or (na and nb and (na[:10] in nb or nb[:10] in na)))


def target_key(t: Dict[str, Any]) -> str:
    return _norm(t.get("ticker")) or _norm(t.get("name"))[:20]


def active(session: Session, workspace_id: str) -> List[Criterion]:
    """사내 공통 + 이 워크스페이스의 사용 중인 기준(사내 먼저)."""
    rows = session.exec(select(Criterion).where(Criterion.status == "active", Criterion.workspace_id.in_(["", workspace_id]))).all()  # type: ignore[attr-defined]
    return sorted(rows, key=lambda c: (c.scope != "company", c.created_at))


def applies_to(c: Criterion, target: Dict[str, Any]) -> bool:
    """대상이 정해진 기준은 그 대상에만, 대상이 없는 기준은 어디에나."""
    ap = c.applies or {}
    if ap.get("name") or ap.get("ticker"):
        return same_target(ap, target)
    return True


def code_metric(wanted: str, candidates: Sequence[str]) -> Optional[str]:
    """지표 이름 → 원장 지표 이름(LLM 없이 — 같은 이름 또는 한국어 낱말의 영문 대응이 모두 든 가장 짧은 후보). 못 찾으면 None."""
    for c in candidates:
        if metric_key(c) == metric_key(wanted) or _norm(c) == _norm(wanted):
            return c
    w, hints = _norm(wanted), []
    for ko, en in KO_EN:
        if ko in w:
            hints.append(en)
            w = w.replace(ko, "")
    if hints:
        hit = sorted((c for c in candidates if all(h in c.lower() for h in hints)), key=len)
        if hit:
            return hit[0]
    return None


def condition_text(c: Criterion) -> str:
    cond = c.condition or {}
    if c.kind != "numeric" or not cond:
        return c.when_text or "정성(사람 판단)"
    parts = [str(cond.get("metric") or cond.get("ledgerMetric") or "")]  # 화면·프롬프트는 사람이 쓴 지표 이름(원장 이름은 판정에만)
    if cond.get("period") in PERIOD_KO:
        parts.append(PERIOD_KO[cond["period"]])
    th = cond.get("threshold")
    head = " · ".join(p for p in parts if p)
    return f"{head} {th:g}{cond.get('unit') or ''} {OP_KO.get(cond.get('op') or '>=', '')}" if isinstance(th, (int, float)) else f"{head} {th}{cond.get('unit') or ''} {OP_KO.get(cond.get('op') or '>=', '')}"


def evaluate(c: Criterion, target: Dict[str, Any], doc_ids: List[str], as_of: Optional[str] = None) -> Dict[str, Any]:
    """→ {result: reached|not_reached|no_data|qualitative, value{display…}, anchors}. 숫자 조건만 판정한다(정성·입장 기준은 사람 판단)."""
    if c.kind != "numeric" or not c.condition:
        return {"result": "qualitative", "value": {}, "anchors": []}
    cond = dict(c.condition)
    res = judge_portfolio(cond, target, doc_ids, as_of)
    if res is None:
        if not cond.get("ledgerMetric"):
            hit = code_metric(cond.get("metric") or "", ledger_metrics(entity_docs(target, doc_ids)))
            if hit:
                cond["ledgerMetric"] = hit
        res = judge_numeric(cond, target, doc_ids, as_of)
    return {**res, "result": {"met": "reached", "not_met": "not_reached"}.get(res.get("result") or "", "no_data")}


def headroom(criteria: Sequence[Criterion], target: Dict[str, Any], doc_ids: List[str], as_of: Optional[str] = None) -> List[Dict[str, Any]]:
    """한도 기준(limit 있음)마다 지금 값과 한도까지 남은 폭 — 보유 내역 표로 코드가 계산(가이드라인 점검과 같은 계산). 음수면 이미 넘음.
    그 대상에 걸리는 한도(단일 발행자)는 늘, 포트폴리오 전체 한도(자산군·비상장)는 넘었을 때만 싣는다 — 비중을 바꾸는 검토에 실제로 걸리는 것만."""
    out: List[Dict[str, Any]] = []
    for c in criteria:
        lim = c.limit or {}
        try:
            th = float(lim.get("threshold"))
        except (TypeError, ValueError):
            continue
        op = str(lim.get("op") or "<=")
        metric = (c.condition or {}).get("metric") or ""
        res = judge_portfolio({"metric": metric, "op": op, "threshold": th}, target, doc_ids, as_of)
        if not res or res.get("result") == "no_data":
            continue
        v = float((res.get("value") or {}).get("value"))
        gap = round(th - v if op in ("<=", "<") else v - th, 2)
        if "발행" not in metric and gap >= 0:
            continue
        label = c.title or metric or "한도"
        limit = "" if f"{th:g}%" in label else f" {th:g}% {OP_KO.get(op, '')}"
        out.append({"criterionId": c.id, "key": c.key, "version": c.version, "title": label, "limit": th, "current": v, "gap": gap,
                    "display": f"{label}{limit} · 지금 {v:g}% · 여유 {gap:+.1f}%p", "anchors": res.get("anchors") or [], "within": gap >= 0})
    return out


__all__ = ["DIRECTION_KO", "RESULT_KO", "SCOPE_KO", "active", "applies_to", "code_metric", "condition_text", "evaluate", "headroom", "same_target", "target_key"]
