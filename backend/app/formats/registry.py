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


def section_blocks_of(doc: Dict[str, Any], sec: Dict[str, Any]) -> List[str]:
    """섹션에 붙는 블록 id — 대화로 바꾼 목록(sec['blocks'])이 있으면 그것, 없으면 양식 기본값."""
    if not is_format(doc.get("reportType")):
        return []
    if isinstance(sec.get("blocks"), list):
        return [b for b in sec["blocks"] if block_spec(doc.get("reportType"), b)]
    return default_blocks(doc.get("reportType"), (sec.get("covers") or [None])[0])


def label(spec: Dict[str, Any]) -> str:
    return f"<{'표' if spec['kind'] == 'table' else '그림'} {spec['no']}> {spec['title']}"


__all__ = ["FORMATS", "get_format", "is_format", "block_spec", "catalog", "default_blocks", "section_blocks_of", "label"]
