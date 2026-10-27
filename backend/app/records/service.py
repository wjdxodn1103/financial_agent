"""팀 기록 — 확정된 기록을 에이전트 맥락으로 꺼낸다(작성 브리프·채팅 시스템 프롬프트·확인 카드).
기록을 만드는 쪽(기록 비서 배치)은 records/digest.py.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Set

from sqlmodel import Session, select

from app.db import TeamRecord, User, iso

RECORD_TYPES: Dict[str, str] = {"decision": "결정", "directive": "지시", "convention": "방침", "todo": "할 일", "question": "미결 질문"}
NOTES_MAX = 20


def confirmed_notes(session: Session, workspace_id: str) -> List[Dict[str, Any]]:
    """확정된 기록(최근 순, 상한) → [{id, type, typeKo, text, author, scope, quote, at}]. 원문(quote)은 고치지 않고 그대로 싣는다."""
    rows = session.exec(
        select(TeamRecord).where(TeamRecord.workspace_id == workspace_id, TeamRecord.status == "confirmed").order_by(TeamRecord.created_at.desc())  # type: ignore[attr-defined]
    ).all()
    names = {u.id: f"{u.name} {u.title}".strip() for u in session.exec(select(User)).all()}
    out: List[Dict[str, Any]] = []
    for r in rows[:NOTES_MAX]:
        quote = (r.quotes or [{}])[0].get("text") if r.quotes else ""
        out.append(
            {
                "id": r.id,
                "type": r.type,
                "typeKo": RECORD_TYPES.get(r.type, r.type),
                "text": r.text,
                "author": names.get(r.author_id or "", ""),
                "scope": r.scope,
                "quote": quote or "",
                "at": iso(r.confirmed_at or r.created_at),
            }
        )
    return out


# 범위·섹션 제목에서 어느 섹션인지 가리지 못하는 낱말
_SCOPE_STOP = {"섹션", "부분", "파트", "항목", "보고서", "리포트", "내용", "관련", "분석", "요인", "투자", "전체", "공통", "모든"}


def _scope_words(s: str) -> Set[str]:
    s = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", s or "")
    return set(re.findall(r"[가-힣A-Za-z]{2,}", s)) - _SCOPE_STOP


def scope_matches(scope: str, title: str) -> bool:
    """기록의 범위(예: '리스크 섹션')가 이 섹션('4. 리스크 요인')에 해당하는가. 범위가 없거나 특정 섹션을 가리키지 않으면('리포트 전체') 모든 섹션.
    기록 비서가 쓴 범위는 섹션 제목과 글자가 같지 않으니 — 한쪽이 다른 쪽을 품거나, 섹션을 가리는 낱말(리스크·실적·밸류에이션…)이 겹치면 해당."""
    sc, ti = (scope or "").strip(), (title or "").strip()
    if not sc or not ti or sc in ti or ti in sc:
        return True
    words = _scope_words(sc)
    return not words or bool(words & _scope_words(ti))


def notes_lines(notes: List[Dict[str, Any]], scope_hint: str = "") -> List[str]:
    """프롬프트용 — 범위가 이 섹션이거나 전체인 기록만(scope_matches), 원문 인용 그대로."""
    out = []
    for n in notes:
        if not scope_matches(n.get("scope") or "", scope_hint):
            continue
        who = f"{n['author']}" if n.get("author") else "팀"
        quote = f' — 원문: "{n["quote"]}"' if n.get("quote") else ""
        out.append(f"- [{n['typeKo']}] {n['text']} ({who}, {str(n.get('at') or '')[:10]}){quote}")
    return out
