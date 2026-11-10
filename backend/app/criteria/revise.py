"""승인 → 기준 수정안 — 보고서가 승인되면(sharing.approve) 그 문서가 지금 기준에 없던 판단 규칙이나 기준을 바꾸는 결정을 담았는지 본다(LLM 1회, 백그라운드).
있으면 초안(draft)으로 낸다: 같은 기준을 고치면 같은 key 의 다음 판(base_id), 새 규칙이면 새 key. 인용·방향 낱말·대상은 뽑기와 같은 코드 검증,
충돌은 코드가 다시 본다(같은 지표·대상인데 조건·방향이 다르면 by=code, LLM 만 그렇게 말하면 by=ai). 승인은 사람(사내 = 관리자, 워크스페이스 = 소유자)."""
from __future__ import annotations

import copy
import logging
import re
from typing import Any, Dict, List

from sqlmodel import Session

from app.assumptions.extract import _sentences_report
from app.criteria.extract import _json, verify
from app.criteria.match import DIRECTION_KO, active, condition_text
from app.criteria.service import _dup, _new_row, code_conflicts, notify_drafts
from app.db import Criterion, ReportSession, engine
from app.llm.base import ChatParams

log = logging.getLogger(__name__)
MAX_DRAFTS = 3

PROMPT = """승인된 투자 문서의 문장들(번호)과 지금 쓰는 판단 기준(K 번호)이 있다. 이 문서가 기존 기준에 없던 새 판단 규칙을 담았거나, 기존 기준을 바꾸는 결정(기준값·방향을 바꿈)을 담았으면
그것만 골라 JSON 하나로만 답한다(설명 없이). 없으면 "rules": [].
{"rules": [{"n": 문장 번호, "quote": "그 문장에서 규칙 부분을 글자 그대로", "title": "짧은 이름(20자 안)", "when": "조건 한 줄", "direction": "expand|hold|reduce|review",
  "kind": "numeric|qualitative", "applies": {"name": "특정 회사·자산에만 해당하면 그 이름", "ticker": "", "assetClass": ""},
  "condition": {"metric": "지표 이름", "period": "latest_q_yoy|latest_q|latest_fy|latest_fy_yoy", "op": ">=|>|<=|<", "threshold": 숫자, "unit": "%"},
  "relation": "new|refine|conflict", "k": 고치는 기준 번호(new 면 0), "why": "왜 새 규칙·수정인지 한 줄"}]}
규칙:
- 사실 서술이나 이번 결정의 내용 자체(예: '비중 30bp 축소')는 규칙이 아니다. '~이면 ~ 검토한다' 처럼 다음에도 쓸 조건 → 방향만.
- refine = 같은 기준의 기준값·방향을 고침, conflict = 기존 기준과 반대. 그 기준 번호를 k 에. 이미 같은 규칙이면 내지 않는다.
- condition 은 '조건이 참이면 그 방향을 검토한다'가 되게(예: '25% 아래로 내려가면 축소 검토' → op "<", threshold 25). quote 는 글자 그대로."""


def on_approved(report_id: str, approver_id: str) -> bool:
    """승인 직후 — 백그라운드로 띄우기만(승인 응답을 늦추지 않는다). 실패해도 승인은 그대로."""
    from app import scheduler

    with Session(engine) as s:
        r = s.get(ReportSession, report_id)
        if r is None:
            return False
        ws_id = r.workspace_id
    return scheduler.spawn(f"criteria_revise:{report_id}", _run(report_id, approver_id), ws_id)


def _crit_line(i: int, c: Criterion) -> str:
    who = (c.applies or {}).get("name") or "전체"
    return f"[K{i}] {c.title} — {condition_text(c)} → {DIRECTION_KO.get(c.direction, c.direction)} · 대상 {who} · 원문 “{((c.source or {}).get('quote') or '')[:120]}”"


async def _run(report_id: str, approver_id: str) -> int:
    from app.llm.client import ReportLlm

    with Session(engine) as s:
        r = s.get(ReportSession, report_id)
        if r is None:
            return 0
        doc, title, ws_id = copy.deepcopy(r.doc or {}), r.title or "문서", r.workspace_id
        crits = [c.model_copy() for c in active(s, ws_id) if c.kind != "stance"][:20]
    sents = _sentences_report(doc)
    if not sents:
        return 0
    body = "\n".join(f"[{i + 1}] {plain}" for i, (_s, _r, plain) in enumerate(sents))[:14000]
    kb = "\n".join(_crit_line(i + 1, c) for i, c in enumerate(crits)) or "(없음)"
    res = await ReportLlm().complete("chat", ChatParams(messages=[{"role": "user", "content": f"{PROMPT}\n\n## 지금 판단 기준\n{kb}\n\n## 승인된 문서 '{title}' 문장\n{body}"}],
                                                        temperature=0, max_tokens=3000, reasoning_effort="low", timeout_s=180))
    got = _json(getattr(res, "content", "") or "")
    made: List[Criterion] = []
    with Session(engine) as s:
        for it in got.get("rules") or []:
            if len(made) >= MAX_DRAFTS:
                break
            fields = verify([it], sents, "report", report_id, title)
            if not fields:
                continue
            f = fields[0]
            rel = it.get("relation") if it.get("relation") in ("new", "refine", "conflict") else "new"
            try:
                k = int(it.get("k") or 0)
            except (TypeError, ValueError):
                k = 0
            base = s.get(Criterion, crits[k - 1].id) if rel != "new" and 1 <= k <= len(crits) else None
            scope = base.scope if base else "workspace"
            if _dup(s, ws_id, scope, f):
                continue
            why = re.sub(r"(기존\s*)?K\d+", "기존 기준", str(it.get("why") or ""))[:200]  # 프롬프트 안 번호(K9)는 화면에 내지 않는다
            origin: Dict[str, Any] = {"kind": "revision", "reportId": report_id, "reportTitle": title, "relation": rel if base else "new", "why": why, "approvedBy": approver_id}
            row = _new_row(ws_id, scope, "", f, origin, base)
            conf = code_conflicts(s, row)
            if base and rel == "conflict" and not any(x["key"] == base.key for x in conf):
                conf.append({"id": base.id, "key": base.key, "version": base.version, "title": base.title, "why": origin["why"] or "AI 판단 — 기존 기준과 반대", "by": "ai"})
            row.conflicts = conf
            s.add(row)
            made.append(row)
        s.commit()
        for row in made:
            s.refresh(row)
        for scope in ("company", "workspace"):
            notify_drafts(s, [x for x in made if x.scope == scope], ws_id, f"승인된 '{title}'에서 수정안")
    return len(made)
