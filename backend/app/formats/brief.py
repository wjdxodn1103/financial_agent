"""작성 브리프의 '이 섹션 뒤에 붙는 표·그림' 블록 — 표 칸을 근거 원장 figure 로 F#·[S#] 를 붙여 보인다.

작성 모델은 이 숫자를 표기 그대로 인용하고(숫자 확인이 원장 칸과 맞춘다), 표 자체는 시스템이 섹션 뒤에 붙인다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.agent.ledger_brief import LedgerBook, _register, approx_note
from app.docs.search_tool import SourceBook
from app.docs.store import doc_label, load_meta
from app.formats.blocks import section_format_blocks
from app.ledger.figures import load_figures


def block_brief_lines(doc: Dict[str, Any], sec: Dict[str, Any], book: SourceBook, lb: LedgerBook) -> List[str]:
    blocks = section_format_blocks(doc, sec)
    if not blocks:
        return []
    figs: Dict[str, Dict[str, Dict[str, Any]]] = {}
    lines: List[str] = []
    for b in blocks:
        if b["kind"] == "figure":  # 틀의 그림 자리 — 값이 없다
            continue
        layout = bool(b.get("formId"))  # 틀(양식 2.0)의 표 — 칸마다 출처 자료가 다르다(cell.docId)
        if b.get("missing"):
            if layout:
                lines.append(f"표 '{b['label']}' — 자료에서 채운 칸이 없다. 이 표의 숫자는 쓰지 않는다.")
            else:
                lines.append(f"{b['label']} — 데이터 없음(자료에 시트 '{b.get('sheet')}' 가 없다). 이 표·그림의 숫자는 쓰지 않는다.")
            continue
        if b["kind"] == "chart" and layout:
            # 틀의 차트(research/form_charts) — 계열 값을 그대로 보여 준다. 분기 값·비중은 계산값이라 본문에 쓰면 숫자 확인이 계산값으로 본다
            vals = "; ".join(f"{s['name']}: " + " · ".join(f"{c} {v:,.1f}".rstrip("0").rstrip(".") for c, v in zip(b["categories"], s["values"]) if v is not None)
                             for s in b["series"] if len(b["categories"]) <= 24)
            lines.append(f"그림 '{b['label']}' (단위: {b.get('unit') or '-'}{', 오른쪽 ' + b['unit2'] if b.get('unit2') else ''}) — {b.get('sourceLine')}. {vals}")
            lb.calcs.extend({**c, "auto": True} for c in b.get("calcs") or [])
            continue
        if b["kind"] == "chart":
            lines.append(f"{b['label']} — 표 데이터로 그린 막대 그래프(범주: {', '.join(b['categories'][:12])}). 본문에서 경향을 말할 때 가리킨다.")
            continue
        header = b["header"]
        if layout:
            lines.append(f"표 '{b['label']}' (단위: {b['unit'] or '행 이름의 괄호'}) — {b.get('sourceLine')}. 빈 칸 = 자료에 없거나 예상 열")
            lb.calcs.extend({**c, "auto": True} for c in b.get("calcs") or [])  # 표의 계산 칸(비율·증가율) — 본문이 쓰면 계산값으로 본다
        else:
            lines.append(f"{b['label']} (단위: {b['unit']}) — 자료: {b.get('docLabel')} · 시트 {b['sheet']}")
        for row in b["rows"]:
            if not row:
                continue
            parts = []
            for c, cell in enumerate(row[1:], start=1):
                col = header[c] if c < len(header) else ""
                fid = cell.get("fid")
                did = (cell.get("docId") if layout else b["docId"]) or ""
                if fid and did not in figs:
                    figs[did] = {f["id"]: f for f in load_figures(did)}
                f = figs[did].get(fid.split(":", 1)[1]) if fid else None
                if f:
                    full = {**f, "fid": fid, "docLabel": b.get("docLabel") or doc_label(load_meta(did), did)}
                    s_no = _register(book, full)
                    k = lb.add({**full, "_s": s_no})
                    parts.append(f"{col} {k} [S{s_no}] {cell['text']}{approx_note(f)}")
                elif cell.get("text"):
                    parts.append(f"{col} {cell['text']}" + ("(계산)" if cell.get("kind") == "calc" else ""))
            if parts or not layout:
                lines.append(f"- {row[0]['text']}: " + " · ".join(parts))
    return lines


__all__ = ["block_brief_lines"]
