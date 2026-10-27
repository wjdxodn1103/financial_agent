"""진행 상황 — 유형의 항목 × 쓰인 섹션(OP coverage.progress/suggest_next 의 축소판)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.session import Doc, written_sections
from app.agent.template import items_of, report_type, write_order


def progress(doc: Doc) -> Dict[str, Any]:
    written = written_sections(doc)
    entries: List[Dict[str, Any]] = []
    for it in items_of(doc.get("reportType")):
        by = [{"step": s["step"], "title": s["title"]} for s in written if it["id"] in (s.get("covers") or [])]
        entries.append({"item": {k: it[k] for k in ("id", "title", "phase", "level", "desc")}, "covered": bool(by), "by": by})
    required = [e for e in entries if e["item"]["level"] == "required"]
    return {
        "entries": entries,
        "required": len(required),
        "requiredCovered": sum(1 for e in required if e["covered"]),
        "done": all(e["covered"] for e in required),
        "remaining": [e["item"] for e in entries if not e["covered"]],
    }


def suggest_next(doc: Doc) -> Optional[Dict[str, Any]]:
    """권장 작성 순서에서 아직 안 쓴 첫 항목과 그 자리(깔린 빈 섹션)."""
    p = progress(doc)
    left = {e["item"]["id"]: e["item"] for e in p["entries"] if not e["covered"]}
    for item_id in write_order(doc.get("reportType")):
        if item_id in left:
            sec = next((s for s in doc.get("sections") or [] if item_id in (s.get("covers") or []) and s.get("status") != "written"), None)
            return {"item": left[item_id], "section": sec, "title": sec["title"] if sec else left[item_id]["title"]}
    return None


def status_text(doc: Doc) -> str:
    """채팅 모델용 상태 블록 — 섹션 목록(id·작성 여부), 진행, 다음 추천."""
    t = report_type(doc.get("reportType"))
    lines = [f"리포트 유형: {t['title']}"]
    sections = doc.get("sections") or []
    if sections:
        lines.append("원고 섹션(순서대로, [id] 제목 — 상태):")
        for s in sections:
            state = f"작성됨 {len(s.get('content') or '')}자" if s.get("status") == "written" else "비어 있음"
            lines.append(f"- [{s['step']}] {s['title']} — {state}")
    p = progress(doc)
    lines.append(f"필수 항목 {p['requiredCovered']}/{p['required']} 작성")
    nxt = suggest_next(doc)
    if nxt:
        lines.append(f"다음 추천: {nxt['title']}")
    elif p["done"]:
        lines.append("필수 섹션을 모두 썼다 — 전체 검토·보완을 제안할 수 있다.")
    plan = doc.get("plan")
    if plan and plan.get("items"):
        left = [x["title"] for x in plan["items"][plan.get("done", 0):]]
        if left:
            lines.append(f"확정된 작성 순서의 남은 섹션: {' → '.join(left)}")
    return "\n".join(lines)
