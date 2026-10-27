"""문단 구조 태그(규칙, LLM 0회) — 검색 조건으로 쓴다(벡터 저장소 payload).

 - years: 문단·제목에 나온 연도(1980~2049, FY27·FY2027 도) — '2024년 자료만' 같은 조건.
 - disclaimer: 면책·법적 고지·투자 권유 아님 문단 — AI 근거 검색에서 기본으로 뺀다(검색창은 그대로 찾는다).
지표·시황 같은 내용 태그는 아직 없다(제목 경로·임베딩 원형으로 더할 자리).
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence

_YEAR = re.compile(r"(?<![\d.,])(19[89]\d|20[0-4]\d)(?![\d])")
_FY = re.compile(r"\bFY\s?'?(\d{4}|\d{2})\b", re.I)
_DISCLAIMER = re.compile(
    r"disclaimer|not (?:be )?(?:intended|construed) (?:as|in any)|personali[sz]ed advice|(?:not|no) investment advice|for (?:general )?information(?:al)? purposes only"
    r"|solicitation (?:of )?an offer|this communication is being distributed|past performance is not|forward-looking statements"
    r"|면책|투자\s*권유|법적\s*(?:책임|효력)을?\s*(?:지지|갖지|부담하지)|투자\s*판단의\s*(?:최종\s*)?책임|정확성(?:이나|과|\s*및)\s*완전성을?\s*보장",
    re.I,
)
_DISCLAIMER_HEADING = re.compile(r"disclaimer|important (?:information|notice)|legal notice|면책|법적\s*고지|유의\s*사항", re.I)


def years_of(text: str, heading_path: Optional[Sequence[str]] = None) -> List[int]:
    src = " ".join([*(heading_path or []), text or ""])
    ys = {int(y) for y in _YEAR.findall(src)}
    for fy in _FY.findall(src):
        y = int(fy) if len(fy) == 4 else 2000 + int(fy)
        if 1980 <= y <= 2049:
            ys.add(y)
    return sorted(ys)


def is_disclaimer(text: str, heading_path: Optional[Sequence[str]] = None) -> bool:
    if any(_DISCLAIMER_HEADING.search(h or "") for h in heading_path or []):
        return True
    return len(text or "") >= 60 and bool(_DISCLAIMER.search(text or ""))


__all__ = ["is_disclaimer", "years_of"]
