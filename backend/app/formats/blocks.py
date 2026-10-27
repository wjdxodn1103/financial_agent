"""양식 블록 만들기 — 표는 데이터 워크북의 시트를 그대로 옮기고(칸마다 근거 원장 figure 에 연결), 그림은 표 블록의 행·열로 그린다.

결정적(LLM 0회). 리포트 뷰가 그릴 때마다 지금 자료로 다시 만든다(저장된 스냅샷 없음 — 데이터를 고치면 표도 바뀌고, 본문 숫자는 숫자 확인이 다시 대조).

표 블록:  {kind:"table", step, blockId, no, label, title, unit, number, sheet, docId, docLabel, chunk, header, rows:[[cell]], missing}
          cell = {text, num: bool, fid?, chunk?, cell?: [r, c]}
그림 블록: {kind:"chart", step, blockId, no, label, title, unit, number, docId, chunk, categories, series:[{name, values}], horizontal, missing}
시트가 자료에 없으면 missing=True(무엇을 올리면 되는지 sheet 로 알려 준다).
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.docs.store import doc_label, load_chunks, load_meta
from app.formats.registry import block_spec, label, section_blocks_of
from app.ledger.figures import load_figures

Doc = Dict[str, Any]
_NUMERIC = re.compile(r"^\s*[-−△]?\s*[\d,]+(?:\.\d+)?\s*%?\s*$")


class SheetIndex:
    """리포트 자료에서 시트 찾기 — 같은 시트가 여러 자료에 있으면 나중에 올린 것(documentIds 뒤쪽)."""

    def __init__(self, doc_ids: Sequence[str]) -> None:
        self.doc_ids = list(doc_ids)
        self._chunks: Dict[str, List[Dict[str, Any]]] = {}
        self._figs: Dict[str, Dict[Tuple[str, int, int], str]] = {}

    def chunks(self, doc_id: str) -> List[Dict[str, Any]]:
        if doc_id not in self._chunks:
            self._chunks[doc_id] = [c for c in load_chunks(doc_id) if c.get("rows") and c.get("sheet")]
        return self._chunks[doc_id]

    def fids(self, doc_id: str) -> Dict[Tuple[str, int, int], str]:
        if doc_id not in self._figs:
            self._figs[doc_id] = {(f["chunk"], f["cell"][0], f["cell"][1]): f"{doc_id}:{f['id']}" for f in load_figures(doc_id) if f.get("cell")}
        return self._figs[doc_id]

    def find(self, sheet: str) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
        for did in reversed(self.doc_ids):
            hits = [c for c in self.chunks(did) if c.get("sheet") == sheet]
            if hits:
                return did, hits
        return None


def _table(spec: Dict[str, Any], sheets: SheetIndex) -> Dict[str, Any]:
    base = {"kind": "table", "blockId": spec["id"], "no": spec["no"], "label": label(spec), "title": spec["title"], "unit": spec.get("unit") or "", "number": spec.get("number") or "", "sheet": spec["sheet"]}
    found = sheets.find(spec["sheet"])
    if not found:
        return {**base, "missing": True, "header": [], "rows": []}
    did, chunks = found
    fids = sheets.fids(did)
    header: List[str] = []
    rows: List[List[Dict[str, Any]]] = []
    for k, ch in enumerate(chunks):
        crow = ch["rows"]
        if k == 0:
            header = [str(x) for x in crow[0]]
        # 긴 시트가 여러 청크로 나뉘면 뒤 청크는 머리 행을 되풀이한다
        for r, row in enumerate(crow[1:], start=1):
            cells = []
            for c, text in enumerate(row):
                t = str(text)
                num = bool(_NUMERIC.match(t)) and c > 0
                cell: Dict[str, Any] = {"text": t, "num": num}
                fid = fids.get((ch["id"], r, c))
                if fid:
                    cell.update({"fid": fid, "chunk": ch["id"], "cell": [r, c]})
                cells.append(cell)
            rows.append(cells)
    meta = load_meta(did)
    return {**base, "missing": False, "docId": did, "docLabel": doc_label(meta, did), "chunk": chunks[0]["id"], "header": header, "rows": rows}


def _num(text: str) -> Optional[float]:
    t = re.sub(r"[,%\s]", "", text or "").replace("−", "-").replace("△", "-")
    try:
        return float(t)
    except ValueError:
        return None


def _chart(spec: Dict[str, Any], table: Dict[str, Any]) -> Dict[str, Any]:
    base = {"kind": "chart", "blockId": spec["id"], "no": spec["no"], "label": label(spec), "title": spec["title"], "unit": spec.get("unit") or "", "number": spec.get("number") or "0.0",
            "horizontal": bool(spec.get("horizontal")), "from": spec.get("from")}
    if table.get("missing"):
        return {**base, "missing": True, "sheet": table.get("sheet"), "categories": [], "series": []}
    header = table["header"]
    cols = [header.index(c) for c in spec.get("cols") or header[1:] if c in header]
    wanted = spec.get("rows")
    picked = [r for r in table["rows"] if r and ((r[0]["text"] in wanted) if wanted else "합계" not in r[0]["text"])]
    if wanted:
        picked.sort(key=lambda r: wanted.index(r[0]["text"]))
    series = [{"name": header[c], "values": [_num(r[c]["text"]) if c < len(r) else None for r in picked]} for c in cols]
    return {**base, "missing": False, "docId": table["docId"], "chunk": table["chunk"], "sheet": table["sheet"], "categories": [r[0]["text"] for r in picked], "series": series}


def section_format_blocks(doc: Doc, sec: Dict[str, Any], number_of: Optional[Callable[[str], int]] = None, sheets: Optional[SheetIndex] = None) -> List[Dict[str, Any]]:
    """섹션 뒤에 붙는 표·그림 블록(양식 리포트만). number_of 를 주면 데이터 자료를 참고 자료 번호에 올린다."""
    ids = section_blocks_of(doc, sec)
    if not ids:
        return []
    sheets = sheets or SheetIndex(doc.get("documentIds") or [])
    type_id = doc.get("reportType")
    tables: Dict[str, Dict[str, Any]] = {}
    out: List[Dict[str, Any]] = []
    for bid in ids:
        spec = block_spec(type_id, bid)
        if not spec:
            continue
        if spec["kind"] == "table":
            b = tables.get(bid) or _table(spec, sheets)
            tables[bid] = b
        else:
            src = block_spec(type_id, spec.get("from") or "")
            t = tables.get(spec.get("from") or "") or (_table(src, sheets) if src else {"missing": True, "sheet": ""})
            b = _chart(spec, t)
        if number_of and not b.get("missing") and b.get("docId"):
            b["sourceNo"] = number_of(b["docId"])
        out.append({**b, "step": sec["step"]})
    return out


def report_blocks(doc: Doc) -> List[Dict[str, Any]]:
    """리포트 전체의 표·그림 블록(내보내기·엑셀용) — 섹션 순서대로."""
    sheets = SheetIndex(doc.get("documentIds") or [])
    out: List[Dict[str, Any]] = []
    for s in doc.get("sections") or []:
        out.extend(section_format_blocks(doc, s, sheets=sheets))
    return out


__all__ = ["SheetIndex", "section_format_blocks", "report_blocks"]
