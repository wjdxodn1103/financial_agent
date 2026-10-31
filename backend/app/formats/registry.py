"""고정 양식 등록표 — 리포트 종류(REPORT_TYPES)와 같은 모양에 표·그림 블록이 더 붙는다.

새 양식 = 이 파일에 모듈 하나를 더한다(섹션 items·order + blocks). 양식을 LLM 과 사용자가 만드는 기능은 다음 단계.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.formats import nbim_half_year

FORMATS: Dict[str, Dict[str, Any]] = {
    "nbim_half_year": nbim_half_year.FORMAT,
}


def get_format(type_id: Optional[str]) -> Optional[Dict[str, Any]]:
    return FORMATS.get(type_id or "")


def is_format(type_id: Optional[str]) -> bool:
    return (type_id or "") in FORMATS


def block_spec(type_id: Optional[str], block_id: str) -> Optional[Dict[str, Any]]:
    f = get_format(type_id)
    return (f or {}).get("blocks", {}).get(block_id)


def catalog(type_id: Optional[str]) -> List[Dict[str, Any]]:
    """양식에 딸린 도구(블록) 목록 — 번호순(표 먼저)."""
    f = get_format(type_id)
    blocks = list((f or {}).get("blocks", {}).values())
    return sorted(blocks, key=lambda b: (b["kind"] != "table", b["no"]))


def default_blocks(type_id: Optional[str], item_id: Optional[str]) -> List[str]:
    f = get_format(type_id)
    it = next((i for i in (f or {}).get("items", []) if i["id"] == item_id), None)
    return list((it or {}).get("blocks") or [])


def has_blocks(doc: Dict[str, Any]) -> bool:
    """섹션에 묶인 표·그림 블록이 있는 문서 — 고정 양식(NBIM) 또는 양식 2.0 틀(doc['layout'])."""
    return is_format(doc.get("reportType")) or bool(doc.get("layout"))


def titled(doc: Dict[str, Any], spec: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """틀 양식 제목의 대상 자리 {subject} → 이 문서의 대상(샘플 회사 이름은 양식을 만들 때 이 자리로 바뀌어 있다)."""
    if not spec or "{subject}" not in (spec.get("title") or ""):
        return spec
    from app.formats.blocks import doc_subject

    return {**spec, "title": spec["title"].replace("{subject}", doc_subject(doc) or "대상 기업")}


def doc_block_spec(doc: Dict[str, Any], block_id: str) -> Optional[Dict[str, Any]]:
    """블록 사양 — 틀 문서는 틀의 표·그림 양식(layout.forms), 고정 양식은 BLOCKS."""
    if doc.get("layout"):
        return titled(doc, (doc["layout"].get("forms") or {}).get(block_id))
    return block_spec(doc.get("reportType"), block_id)


def doc_catalog(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """이 문서에 붙일 수 있는 표·그림 목록 — 틀 문서는 틀의 표 양식, 고정 양식은 BLOCKS."""
    if doc.get("layout"):
        return [titled(doc, f) for f in (doc["layout"].get("forms") or {}).values() if f.get("kind") == "table"]
    return catalog(doc.get("reportType"))


def section_blocks_of(doc: Dict[str, Any], sec: Dict[str, Any]) -> List[str]:
    """섹션에 붙는 블록 id — 대화로 바꾼 목록(sec['blocks'])이 있으면 그것, 없으면 양식 기본값. 틀 문서는 섹션에 깐 자리(sec['blocks'])."""
    if doc.get("layout"):
        forms = doc["layout"].get("forms") or {}
        return [b for b in sec.get("blocks") or [] if b in forms]
    if not is_format(doc.get("reportType")):
        return []
    if isinstance(sec.get("blocks"), list):
        return [b for b in sec["blocks"] if block_spec(doc.get("reportType"), b)]
    return default_blocks(doc.get("reportType"), (sec.get("covers") or [None])[0])


def label(spec: Dict[str, Any]) -> str:
    """'<표 4> 제목' — 번호 없는 양식(틀의 표·그림, KIRS 처럼 제목만)은 제목 그대로."""
    if spec.get("no") is None:
        return spec.get("title") or ""
    return f"<{'표' if spec['kind'] == 'table' else '그림'} {spec['no']}> {spec['title']}"


__all__ = ["FORMATS", "get_format", "is_format", "has_blocks", "titled", "doc_block_spec", "doc_catalog", "block_spec", "catalog", "default_blocks", "section_blocks_of", "label"]
