"""판단 기준을 프롬프트에 — 이 문서와 관련된 사용 중 기준만 싣는다(대상이 맞는 기준 + 대상 없는 한도·원칙, 하우스뷰 입장은 자산군이 문서에 나올 때).
숫자 조건은 코드 판정 결과를 같이 싣는다 — 모델이 도달 여부를 스스로 판정하지 않게. 줄 끝의 원문 인용으로 사용자가 출처를 물으면 답한다."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from sqlmodel import Session, select

from app.criteria.match import DIRECTION_KO, RESULT_KO, SCOPE_KO, active, condition_text, evaluate, same_target
from app.db import Assumption

LIMIT = 8


def _norm(s: Any) -> str:
    return re.sub(r"[\s·\-_()]+", "", str(s or "")).lower()


def doc_targets(session: Session, doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """문서의 대상 — 설정의 '대상' + 이 문서 가정의 대상."""
    out: List[Dict[str, Any]] = []
    subj = str((doc.get("setup") or {}).get("subject") or "").strip()
    if subj:
        out.append({"name": subj})
    if doc.get("id"):
        for a in session.exec(select(Assumption).where(Assumption.doc_ref == doc["id"], Assumption.status != "dismissed")).all():
            t = a.target or {}
            if (t.get("name") or t.get("ticker")) and not any(same_target(t, o) for o in out):
                out.append({"name": t.get("name") or "", "ticker": t.get("ticker") or ""})
    return out


def _text(doc: Dict[str, Any]) -> str:
    secs = " ".join(f"{s.get('title') or ''} {(s.get('content') or '')[:600]}" for s in doc.get("sections") or [])
    return _norm(f"{json.dumps(doc.get('setup') or {}, ensure_ascii=False)} {secs}")[:20000]


def relevant_criteria(session: Session, workspace_id: str, doc: Dict[str, Any], doc_ids: List[str], limit: int = LIMIT) -> List[Dict[str, Any]]:
    """→ [{id, key, version, scopeKo, title, conditionText, directionKo, quote, docTitle, status{result, resultKo, display}}] — 대상이 맞는 기준 먼저."""
    targets = doc_targets(session, doc)
    text = _text(doc)
    picked: List[tuple] = []
    for c in active(session, workspace_id):
        ap = c.applies or {}
        if ap.get("name") or ap.get("ticker"):
            hit = next((t for t in targets if same_target(ap, t)), None)
            if hit is None and _norm(ap.get("name"))[:10] and _norm(ap.get("name"))[:10] in text:
                hit = {"name": ap.get("name") or "", "ticker": ap.get("ticker") or ""}
            if hit is None:
                continue
            picked.append((0, c, hit))
        elif c.kind == "stance":
            if _norm(ap.get("assetClass")) and _norm(ap.get("assetClass")) in text:
                picked.append((2, c, None))
        else:
            picked.append((1, c, targets[0] if targets else None))
    picked.sort(key=lambda x: x[0])
    out = []
    for _rank, c, t in picked[:limit]:
        st: Dict[str, Any] = {}
        if c.kind == "numeric" and t:
            res = evaluate(c, t, doc_ids)
            st = {"result": res["result"], "resultKo": RESULT_KO.get(res["result"], res["result"]), "display": (res.get("value") or {}).get("display") or "", "target": t.get("name") or t.get("ticker")}
        ap = c.applies or {}
        out.append({"id": c.id, "key": c.key, "version": c.version, "scopeKo": SCOPE_KO.get(c.scope, c.scope), "title": c.title, "conditionText": condition_text(c),
                    "directionKo": f"입장 {ap['stance']}" if c.kind == "stance" and ap.get("stance") else DIRECTION_KO.get(c.direction, c.direction),
                    "quote": ((c.source or {}).get("quote") or "")[:160], "docTitle": (c.source or {}).get("docTitle") or "", "status": st})
    return out


def criteria_lines(items: List[Dict[str, Any]]) -> List[str]:
    """한 줄 = [사내 v1] 이름: 조건 → 방향 · 지금 값 — 도달(코드 판정) · 근거 “인용”(문서)"""
    out = []
    for it in items:
        st = it.get("status") or {}
        now = f" · 지금 {st.get('target', '')} {st['display']} — {st['resultKo']}(코드 판정)" if st.get("display") else ""
        out.append(f"- [{it['scopeKo']} v{it['version']}] {it['title']}: {it['conditionText']} → {it['directionKo']}{now} · 근거 “{it['quote']}”({it['docTitle']})")
    return out
