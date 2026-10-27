"""작성 브리프의 '이 섹션 뒤에 붙는 표·그림' 블록 — 표 칸을 근거 원장 figure 로 F#·[S#] 를 붙여 보인다.

작성 모델은 이 숫자를 표기 그대로 인용하고(숫자 확인이 원장 칸과 맞춘다), 표 자체는 시스템이 섹션 뒤에 붙인다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.agent.ledger_brief import LedgerBook, _register, approx_note
from app.docs.search_tool import SourceBook
from app.formats.blocks import section_format_blocks
from app.ledger.figures import load_figures


def block_brief_lines(doc: Dict[str, Any], sec: Dict[str, Any], book: SourceBook, lb: LedgerBook) -> List[str]:
    blocks = section_format_blocks(doc, sec)
    if not blocks:
        return []
    figs: Dict[str, Dict[str, Dict[str, Any]]] = {}
    lines: List[str] = []
    for b in blocks:
        if b.get("missing"):
            lines.append(f"{b['label']} — 데이터 없음(자료에 시트 '{b.get('sheet')}' 가 없다). 이 표·그림의 숫자는 쓰지 않는다.")
            continue
        if b["kind"] == "chart":
            lines.append(f"{b['label']} — 표 데이터로 그린 막대 그래프(범주: {', '.join(b['categories'][:12])}). 본문에서 경향을 말할 때 가리킨다.")
            continue
        did = b["docId"]
        if did not in figs:
            figs[did] = {f["id"]: f for f in load_figures(did)}
        header = b["header"]
        lines.append(f"{b['label']} (단위: {b['unit']}) — 자료: {b.get('docLabel')} · 시트 {b['sheet']}")
        for row in b["rows"]:
            if not row:
                continue
            parts = []
            for c, cell in enumerate(row[1:], start=1):
                col = header[c] if c < len(header) else ""
                fid = cell.get("fid")
                f = figs[did].get(fid.split(":", 1)[1]) if fid else None
                if f:
                    full = {**f, "fid": fid, "docLabel": b.get("docLabel")}
                    s_no = _register(book, full)
                    k = lb.add({**full, "_s": s_no})
                    parts.append(f"{col} {k} [S{s_no}] {cell['text']}{approx_note(f)}")
                elif cell.get("text"):
                    parts.append(f"{col} {cell['text']}")
            lines.append(f"- {row[0]['text']}: " + " · ".join(parts))
    return lines


__all__ = ["block_brief_lines"]
