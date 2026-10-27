"""채널 메시지 속 숫자 대조 — "매출 3,200억원이던데요" 같은 말을 원장과 바로 맞춰 본다(LLM 0회).

메시지에서 검수와 같은 규칙으로 (지표·기간·값) 을 뽑고 워크스페이스 원장 묶음과 맞춘다.
  match     채택값(있으면) 또는 자료들이 같은 값과 같다
  mismatch  원장 값과 다르다(원장 값·출처를 붙인다)
  conflict  원장 안에서도 자료마다 값이 다르다(어느 자료와 같은지 붙인다)
원장에 없는 지표·기간은 말하지 않는다(채팅을 시끄럽게 하지 않는다).
"""
from __future__ import annotations

from typing import Any, Dict, List

from sqlmodel import Session

from app.ledger.match import claim_matches_group, claim_same_figure
from app.ledger.service import ledger_for
from app.review.claims import rule_claims

MAX_CHECKS = 4


def _ref(f: Dict[str, Any]) -> Dict[str, Any]:
    return {"docId": f["doc"], "label": f.get("docLabel") or f["doc"][:8], "chunk": f["chunk"], "cell": f.get("cell"), "page": f.get("page"), "display": f.get("display") or f["raw"]}


def check_numbers(session: Session, workspace_id: str, message_id: str, text: str) -> List[Dict[str, Any]]:
    claims = rule_claims([{"id": message_id, "text": text or "", "heading": ""}])
    claims = [c for c in claims if c["periodKey"] and not c.get("periodInferred")]
    if not claims:
        return []
    led = ledger_for(session, workspace_id)
    by_fid = {f["fid"]: f for f in led["figures"]}
    out: List[Dict[str, Any]] = []
    seen = set()
    for c in claims:
        g = next((g for g in led["groups"] if claim_matches_group(c, g)), None)
        if g is None or (g["key"], c["raw"]) in seen:
            continue
        seen.add((g["key"], c["raw"]))
        base = {"raw": c["raw"], "metric": g["metric"], "period": g["period"], "basis": g.get("basis")}
        chosen = by_fid.get((g.get("chosen") or {}).get("figureId") or "")
        if chosen is not None:
            out.append({**base, "status": "match" if claim_same_figure(c, chosen) else "mismatch", "chosen": True, "ref": _ref(chosen)})
        elif g["conflict"]:
            hits = [by_fid[v["figureIds"][0]] for v in g["values"] if v["figureIds"][0] in by_fid and claim_same_figure(c, by_fid[v["figureIds"][0]])]
            out.append({**base, "status": "conflict", "values": [v["display"] for v in g["values"]], "ref": _ref(hits[0]) if hits else _ref(by_fid[g["values"][0]["figureIds"][0]]), "sameAs": hits[0].get("docLabel") if hits else None})
        else:
            rep = by_fid.get((g.get("value") or {}).get("figureId") or "")
            if rep is None:
                continue
            out.append({**base, "status": "match" if claim_same_figure(c, rep) else "mismatch", "chosen": False, "documents": g["documents"], "ref": _ref(rep)})
        if len(out) >= MAX_CHECKS:
            break
    return out


__all__ = ["check_numbers"]
