"""행(기업·문서) → 그 행의 수치를 찾을 자료 고르기. LLM 없음.

기업: 자료 카드의 회사(card.company)·연결 스냅샷의 회사(snapshot.params.corpName)·자료 이름·파일 이름에 기업 이름이 들어 있으면 그 자료.
      사내 DB 처럼 한 자료에 여러 기업이 행 이름("가온전자 매출액")으로 들어 있는 경우는 fill 이 원장 지표 이름으로 따로 찾는다.
문서: 그 문서 하나. 기간·항목: 범위 안 자료 전부.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from app.docs.store import doc_label, load_meta, search_docs


def norm(s: Optional[str]) -> str:
    return re.sub(r"\s|\(주\)|㈜|주식회사|\(株\)|,|\.", "", s or "").lower()


def _names(doc_id: str) -> List[str]:
    m = load_meta(doc_id) or {}
    card = m.get("card") or {}
    params = (m.get("snapshot") or {}).get("params") or {}
    return [norm(x) for x in (card.get("company"), params.get("corpName"), params.get("entityName"), doc_label(m, doc_id), m.get("fileName")) if x]


def company_docs(doc_ids: Sequence[str], name: str) -> List[str]:
    """기업 이름이 자료 자체를 가리키는 자료(그 회사의 공시·IR·스냅샷)."""
    key = norm(name)
    if len(key) < 2:
        return []
    return [d for d in doc_ids if any(key in n for n in _names(d))]


def candidate_docs(subject: Dict[str, Any], kind: str, doc_ids: Sequence[str]) -> List[str]:
    if subject.get("docId") and subject["docId"] in doc_ids:
        return [subject["docId"]]
    if kind == "document":
        hit = [d for d in doc_ids if norm(subject.get("label")) and norm(subject.get("label")) in " ".join(_names(d))]
        return hit[:1]
    if kind == "company":
        hit = company_docs(doc_ids, subject.get("label") or "")
        if hit:
            return hit
        # 이름이 자료 이름에 없으면 이름이 나오는 문단이 있는 자료
        key = norm(subject.get("label"))
        found = [h["docId"] for h in search_docs(doc_ids, subject.get("label") or "", k=8, per_doc=1, lexical=True) if key and key in norm(h["chunk"].get("text"))]
        return list(dict.fromkeys(found))
    return list(doc_ids)


def mentions(text: Optional[str], name: str) -> bool:
    key = norm(name)
    return bool(key) and key in norm(text)
