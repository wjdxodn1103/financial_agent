"""문장 속 숫자(주장) ↔ 원장 묶음·칸 맞추기 — 리포트 검토 준비(report/readiness)와 채널 숫자 대조(channel/numbers)가 같이 쓴다.
주장은 검수의 규칙 추출(review.claims.rule_claims) 결과 — 지표·기간·기준·값.
"""
from __future__ import annotations

from typing import Any, Dict

from app.ledger.figures import Figure
from app.ledger.numbers import same_value


def claim_matches_group(claim: Dict[str, Any], g: Dict[str, Any]) -> bool:
    """같은 지표·기간·(%/금액)·기준인가. 증감률·%p 는 원장 칸 값이 아니라 맞추지 않는다. 기준은 둘 다 있을 때만 가린다."""
    if claim["metricKey"] != g["metricKey"] or not claim["periodKey"] or claim["periodKey"] != g["periodKey"]:
        return False
    if claim.get("kind") == "change" or claim.get("pp"):
        return False
    if bool(claim["percent"]) != (g["key"].split("|")[2] == "%"):
        return False
    return not (claim.get("basis") and g.get("basis") and claim["basis"] != g["basis"])


def claim_same_figure(claim: Dict[str, Any], f: Figure) -> bool:
    """반올림까지 같은 값인가 — 단위를 둘 다 알면 배율 적용 값, 아니면 표기 숫자끼리."""
    if claim.get("unitKnown") and f.get("unitKnown", True):
        return same_value(claim["abs"], claim["step"], f["abs"], f["step"])
    return same_value(claim["value"], 10 ** -int(claim.get("decimals") or 0), f["value"], 10 ** -int(f.get("decimals") or 0))


__all__ = ["claim_matches_group", "claim_same_figure"]
