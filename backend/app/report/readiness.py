"""리포트 검토 준비 — 코드로만 점검한다(LLM 0회). 리포트 화면이 섹션을 쓴 뒤·값을 채택한 뒤 다시 부른다.

섹션별
  conflicts  본문 숫자가 가리키는 원장 묶음(지표·기간·기준) 중 **미해결 충돌** — 충돌 카드(자료별 값·출처 → 채택)
  stale      채택값이 있는데 본문 숫자가 채택값과 다름(채택 뒤 다시 쓰지 않은 섹션)
리포트 전체 점검표(items): 미작성 섹션 · 미해결 충돌 · 채택값과 다른 숫자 · 원장과 다른 숫자 · 근거 없는 숫자 · 인용 안 한 자료의 값 · 잘린 본문
숫자 판정은 숫자별 확인(number_check.number_report)과 같은 것 — 지금 본문·지금 원장으로 다시 재고, 사람이 확인 표시한 숫자는 빠진다.
state: empty(아무것도 안 씀) | writing(안 쓴 섹션 있음) | attention(확인할 것 있음) | ready(검토 준비됨)
본문 숫자 → 지표·기간은 검수(review)와 같은 규칙 추출(rule_claims)을 쓴다 — 기준이 하나라 화면마다 판정이 갈리지 않는다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.docs.citations import strip_tokens
from app.ledger.match import claim_matches_group, claim_same_figure
from app.report.number_check import number_report, open_review_items
from app.review.claims import rule_claims

KIND_KO = {"unwritten": "미작성", "conflict": "미해결 충돌", "stale": "채택값과 다름", "mismatch": "원장과 다른 숫자", "unsourced": "근거 없는 숫자", "wrongcite": "인용 안 한 자료의 값", "truncated": "잘린 본문"}


def _card(g: Dict[str, Any], by_fid: Dict[str, Dict[str, Any]], quotes: List[str]) -> Dict[str, Any]:
    values = []
    for v in g["values"]:
        docs = []
        for fid in v["figureIds"]:
            f = by_fid.get(fid)
            if f:
                docs.append({"figureId": fid, "docId": f["doc"], "label": f.get("docLabel") or f["doc"][:8], "chunk": f["chunk"], "page": f.get("page"), "sheet": f.get("sheet"), "cell": f.get("cell")})
        values.append({"figureId": v["figureIds"][0], "display": v["display"], "docs": docs})
    return {"key": g["key"], "metric": g["metric"], "period": g["period"], "basis": g.get("basis"), "values": values, "quotes": quotes[:3]}


def section_flags(doc: Dict[str, Any], ledger: Dict[str, Any]) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """→ {step: {"conflicts": [카드], "stale": [{metric, period, written, chosen, quote}]}}"""
    by_fid = {f["fid"]: f for f in ledger["figures"]}
    groups = ledger["groups"]
    out: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for s in doc.get("sections") or []:
        if s.get("status") != "written" or not s.get("content"):
            continue
        claims = rule_claims([{"id": s["step"], "text": strip_tokens(s["content"]), "heading": s.get("title") or ""}])
        hits: Dict[str, List[str]] = {}
        stale: List[Dict[str, Any]] = []
        for c in claims:
            for g in groups:
                if not claim_matches_group(c, g):
                    continue
                chosen = by_fid.get((g.get("chosen") or {}).get("figureId") or "")
                if chosen is not None:
                    if not claim_same_figure(c, chosen):
                        stale.append({"key": g["key"], "metric": g["metric"], "period": g["period"], "written": c["raw"], "chosen": chosen.get("display") or chosen["raw"], "quote": c["quote"]})
                elif g["conflict"]:
                    hits.setdefault(g["key"], []).append(c["quote"])
        flags = {"conflicts": [_card(g, by_fid, hits[g["key"]]) for g in groups if g["key"] in hits], "stale": stale}
        if flags["conflicts"] or flags["stale"]:
            out[s["step"]] = flags
    return out


def readiness(doc: Dict[str, Any], ledger: Dict[str, Any]) -> Dict[str, Any]:
    flags = section_flags(doc, ledger)
    evidence = doc.get("evidence") or {}
    numbers = number_report(doc, ledger)
    open_numbers: Dict[str, List[Dict[str, Any]]] = {}
    for it in open_review_items(numbers):
        open_numbers.setdefault(it["step"], []).append(it)
    items: List[Dict[str, Any]] = []
    sections = doc.get("sections") or []
    written = 0
    for s in sections:
        step, title = s["step"], s.get("title") or s["step"]
        if s.get("status") != "written" or not s.get("content"):
            items.append({"kind": "unwritten", "step": step, "title": title, "text": "아직 쓰지 않은 섹션"})
            continue
        written += 1
        f = flags.get(step) or {}
        for card in f.get("conflicts") or []:
            vals = " / ".join(v["display"] for v in card["values"])
            items.append({"kind": "conflict", "step": step, "title": title, "text": f"{card['metric']} {card['period']}: 자료마다 다름({vals})"})
        for x in f.get("stale") or []:
            items.append({"kind": "stale", "step": step, "title": title, "text": f"{x['metric']} {x['period']}: 본문 {x['written']} ↔ 채택값 {x['chosen']}"})
        items.extend(open_numbers.get(step) or [])
        checks = (evidence.get(step) or {}).get("checks") or {}
        if checks.get("truncated"):
            items.append({"kind": "truncated", "step": step, "title": title, "text": "출력 길이 상한에 걸려 끝이 잘렸을 수 있음"})
    counts = {k: sum(1 for i in items if i["kind"] == k) for k in KIND_KO}
    issues = sum(v for k, v in counts.items() if k != "unwritten")
    if not written:
        state = "empty"
    elif counts["unwritten"]:
        state = "writing"
    elif issues:
        state = "attention"
    else:
        state = "ready"
    return {"state": state, "counts": counts, "issues": issues, "sections": len(sections), "written": written, "items": items, "flags": flags, "kindKo": KIND_KO, "numbers": numbers["summary"]}


def summary_line(r: Dict[str, Any]) -> str:
    """검토 요청 작업 항목·채널 알림에 넣는 한 줄."""
    parts = [f"섹션 {r['written']}/{r['sections']}"]
    parts += [f"{KIND_KO[k]} {n}" for k, n in r["counts"].items() if n and k != "unwritten"]
    return " · ".join(parts) if len(parts) > 1 else parts[0] + " · 확인할 것 없음"


__all__ = ["readiness", "section_flags", "summary_line"]
