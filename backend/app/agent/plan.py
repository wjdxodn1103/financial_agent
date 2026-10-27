"""작성 계획 — OP `paper/agent/plan.py` 이식. 계획은 세션(plan)에 남고, 이어 쓰기는 남은 섹션을 하나씩 카드 없이 바로 쓴다(전문가용)."""
from __future__ import annotations

from typing import Any, Dict, List

from app.agent.session import Doc, find_section

PlanItem = Dict[str, Any]  # {"title", "covers", "sectionId"?, "instruction"?}


def remaining_plan(doc: Doc) -> List[PlanItem]:
    """아직 안 쓴 계획 항목 — 대상 섹션이 이미 쓰였으면 건너뛴다."""
    plan = doc.get("plan")
    if not plan:
        return []
    items: List[PlanItem] = plan.get("items") or []
    while plan.get("done", 0) < len(items):
        it = items[plan["done"]]
        sec = find_section(doc, it.get("sectionId")) if it.get("sectionId") else None
        if not (sec and sec.get("status") == "written"):
            break
        plan["done"] += 1
    return items[plan["done"]:]


def queue_plan_item(doc: Doc) -> List[PlanItem]:
    """남은 계획의 첫 섹션을 바로 쓰도록 걸어 둔다(loop.run_chat 이 이 턴에서 쓴다). 남은 것이 없으면 []."""
    rest = remaining_plan(doc)
    if not rest:
        return []
    first = rest[0]
    doc["pendingApproval"] = {"action": "plan", "steps": [first["title"]], "question": f'"{first["title"]}" 섹션 작성', "plan": [first], "fromPlan": True, "direct": True}
    return rest
