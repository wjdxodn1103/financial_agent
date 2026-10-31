"""작업 설명 — 확인 카드 대신, 섹션을 쓴 뒤 '왜 이렇게 썼는지'와 '무엇을 근거로 썼는지'를 풀어 보여 준다(전문가용 양식 리포트).

이유  = 작성 모델의 [작성 메모](writer.split_memo)
근거  = 코드가 본문에서 정리 — 인용 토큰이 달린 문장마다 그 문장의 숫자를 자료·시트/쪽 단위로 모은다(LLM 0회)
표·그림 = 섹션 뒤에 붙은 양식 블록 (숫자별 원본은 숫자 출처 탭 — 설명에 판정 요약을 싣지 않는다)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from app.docs.citations import strip_tokens, tokens
from app.docs.store import doc_label, load_chunks, load_meta
from app.formats.registry import doc_block_spec, label, section_blocks_of
from app.ledger.numbers import find_amounts

_SENT = re.compile(r"(?<=[.!?。])\s+|\n+")


def _where(doc_id: str, chunk_id: str, cache: Dict[str, Dict[str, Dict[str, Any]]]) -> str:
    if doc_id not in cache:
        cache[doc_id] = {c.get("id"): c for c in load_chunks(doc_id)}
    ch = cache[doc_id].get(chunk_id) or {}
    if ch.get("sheet"):
        return f"시트 {ch['sheet']}"
    if ch.get("page"):
        return f"p.{ch['page']}"
    return (ch.get("heading") or "").split(" / ")[-1][:40] or "본문"


def evidence_lines(content: str) -> List[str]:
    """자료별 '어디서 무엇을 가져왔는지' — 인용 순서대로."""
    used: Dict[str, Dict[str, Tuple[List[str], str]]] = {}
    order: List[str] = []
    cache: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for sent in _SENT.split(content or ""):
        toks = tokens(sent)
        if not toks:
            continue
        nums = [a["raw"] for a in find_amounts(strip_tokens(sent))]
        plain = re.sub(r"\s+", " ", strip_tokens(sent)).strip()
        for d, c in dict.fromkeys(toks):
            if d not in used:
                used[d] = {}
                order.append(d)
            where = _where(d, c, cache)
            prev_nums, prev_quote = used[d].get(where, ([], ""))
            used[d][where] = (list(dict.fromkeys(prev_nums + nums)), prev_quote or plain)
    lines = []
    for d in order:
        name = doc_label(load_meta(d), d)
        parts = []
        for where, (nums, quote) in used[d].items():
            if nums:
                parts.append(f"{where}: {', '.join(nums[:8])}{' 등' if len(nums) > 8 else ''}")
            else:
                parts.append(f"{where}: \"{quote[:70]}{'…' if len(quote) > 70 else ''}\"")
        lines.append(f"- **{name}** — " + " / ".join(parts))
    return lines


def explain_section(doc: Dict[str, Any], sec: Dict[str, Any], res: Dict[str, Any], action: str) -> str:
    content = sec.get("content") or ""
    out = [f"**{sec['title']}** 섹션을 {'고쳐 썼습니다' if action == 'revise' else '썼습니다'} ({len(strip_tokens(content)):,}자)."]
    if res.get("memo"):
        out.append(f"**이렇게 쓴 이유** — {res['memo']}")
    ev = evidence_lines(content)
    out.append("**사용한 근거**\n" + ("\n".join(ev) if ev else "- 출처를 단 문장이 없습니다."))
    blocks = [doc_block_spec(doc, b) for b in section_blocks_of(doc, sec)]
    labels = [label(b) for b in blocks if b]
    if labels:
        out.append("**붙인 표·그림** — " + ", ".join(labels))
    return "\n\n".join(out)


__all__ = ["explain_section", "evidence_lines"]
