"""리서치 메모 — 대화의 답(출처 링크째)을 에셋(kind=note)으로 남긴다. 보관·검색·다시 열기·문서에 넣기용이고 **근거 자료가 아니다**
(작업의 documentIds 에 들어가지 않는다 — AI 가 쓴 글이 다시 근거가 되면 초안의 틀린 숫자가 인용되던 문제가 되풀이된다).

data = {text: 마크다운(출처는 [문서, p.n](#cite=docId~청크) 링크), cites: [{docId, chunk, label}], question}
문서에 넣기: 링크를 본문 인용 토큰 [@docId#청크] 로 바꿔 섹션 끝에 잇는다(그 출처는 원문 문단 그대로).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

CITE_LINK = re.compile(r"\[([^\]]+)\]\(#cite=([0-9a-f]{16})~([A-Za-z0-9_-]+)\)")
_GROUP = re.compile(r"\s*\(((?:\s*\[[^\]]+\]\(#cite=[0-9a-f]{16}~[A-Za-z0-9_-]+\)\s*;?)+)\)")


def note_data(text: str, question: str = "") -> Dict[str, Any]:
    cites: List[Dict[str, str]] = []
    seen = set()
    for m in CITE_LINK.finditer(text or ""):
        key = (m.group(2), m.group(3))
        if key not in seen:
            seen.add(key)
            cites.append({"docId": m.group(2), "chunk": m.group(3), "label": m.group(1)})
    return {"text": (text or "").strip(), "cites": cites, "question": (question or "").strip()[:200]}


def note_title(text: str, question: str = "") -> str:
    base = (question or "").strip() or re.sub(r"[#*>\-\s]+", " ", (text or "").split("\n")[0]).strip()
    return (base[:40] + ("…" if len(base) > 40 else "")) or "메모"


def to_tokens(text: str) -> str:
    """' (문서, p.3; 문서2)' 링크 묶음 → '[@d#c][@d2#c2]' — 리포트 본문의 인용 꼴."""

    def group(m: re.Match) -> str:
        return "".join(f"[@{g.group(2)}#{g.group(3)}]" for g in CITE_LINK.finditer(m.group(1)))

    out = _GROUP.sub(group, text or "")
    return CITE_LINK.sub(lambda g: f"[@{g.group(2)}#{g.group(3)}]", out)


def plain(text: str) -> str:
    """내보내기용 — 링크는 '(문서, p.3)' 글로."""
    return CITE_LINK.sub(lambda g: g.group(1), text or "")


__all__ = ["CITE_LINK", "note_data", "note_title", "plain", "to_tokens"]
