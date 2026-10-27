"""원문 확인 — 가공한 값(원장 칸·표 칸·인용 문단)이 **원본 파일**의 어디인지, 원본을 다시 읽어 그대로 보여 준다(가공한 글이 아니라).

PDF  : 그 쪽을 그림으로(page_png) + 강조 상자(쪽 크기 비율 좌표). 청커 v4 청크는 추출 때 저장한 상자를 그대로 쓴다 —
       문단 = 쪽별 줄 상자(쪽을 넘으면 marks 에 쪽마다), 표 칸 = 그 칸 상자. 옛 청크(상자 없음)만 글을 다시 맞춰 찾는다:
       칸 = 원 행 이름과 같은 줄에 있는 그 값 글자, 문단 = 글이 가장 많이 겹치는 글 덩어리(들).
엑셀 : 원본 시트를 다시 읽어(보이는 값 — 추출과 같은 서식) 그 칸 주변을 격자로 + A1 주소. 칸 = 행 이름이 있는 줄에서 값이 같은 칸.
워드 : 원본 문단·표를 다시 읽어 그 문단(표면 그 칸) 주변.
글   : 원본 줄 주변(TXT·MD).
찾지 못하면 found=false — 화면은 그 쪽(시트·문단 주변)만 보이고 '찾지 못했습니다' 한 줄.
extracted = 가공한 값(원장 수치면 값·지표·기간, 문단이면 앞부분) — 화면이 원본 옆에 한 줄로 둔다.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.docs.store import doc_dir, doc_label, load_meta, paragraphs

_WORD = re.compile(r"[가-힣A-Za-z]{2,}|\d[\d,.]*")


def _words(text: str) -> List[str]:
    return _WORD.findall(text or "")


def _overlap(a: str, b: str) -> float:
    """b 의 낱말 중 a 에도 있는 비율."""
    wa, wb = set(_words(a)), _words(b)
    return sum(1 for w in wb if w in wa) / len(wb) if wb else 0.0


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).replace(",", "")


def _source(doc_id: str) -> Tuple[Dict[str, Any], Path]:
    meta = load_meta(doc_id) or {}
    p = doc_dir(doc_id) / str(meta.get("source") or "")
    if not meta.get("source") or not p.is_file():
        raise FileNotFoundError("원본 파일이 없습니다.")
    return meta, p


def _chunk(doc_id: str, chunk_id: str) -> Optional[Dict[str, Any]]:
    return next((c for c in paragraphs(doc_id) if str(c.get("id")) == str(chunk_id)), None)


def _extracted(doc_id: str, chunk: Optional[Dict[str, Any]], cell: Optional[Tuple[int, int]]) -> Dict[str, Any]:
    from app.ledger.figures import load_figures

    if chunk and cell:
        f = next((x for x in load_figures(doc_id) if str(x.get("chunk")) == str(chunk.get("id")) and list(x.get("cell") or []) == list(cell)), None)
        rows = chunk.get("rows") or []
        raw = rows[cell[0]][cell[1]] if cell[0] < len(rows) and cell[1] < len(rows[cell[0]]) else ""
        if f:
            return {"display": f.get("display") or f.get("raw"), "metric": f.get("metric"), "period": f.get("period"), "raw": raw}
        return {"display": raw, "raw": raw}
    return {"text": re.sub(r"\s+", " ", (chunk or {}).get("text") or "")[:220]}


# ── PDF ─────────────────────────────────────────────────────────────────

def _cells(row: List[Any]) -> set:
    return {re.sub(r"\s+", " ", str(c)).strip() for c in row if c is not None and str(c).strip()}


def _table_rows(page: Any, rows: List[List[str]]) -> List[Any]:
    """표 문단 → 그 쪽에서 같은 표를 찾아 맞는 행의 상자들(같은 숫자가 차트 눈금·본문에 또 있어도 표 밖은 칠하지 않는다). 표를 못 찾으면 []."""
    want = [w for w in (_cells(r) for r in rows) if w]
    try:
        tables = page.find_tables().tables
    except Exception:  # noqa: BLE001 — 표 찾기가 안 되는 쪽은 문단 방식으로
        return []
    best: List[Any] = []
    best_score = 0.0
    for t in tables:
        hit = [i for i, r in enumerate(t.extract()) if (got := _cells(r)) and any(len(w & got) / len(w) >= 0.6 for w in want)]
        score = len(hit) / max(len(want), 1)
        if hit and score > best_score:
            best, best_score = [t.rows[i].bbox for i in hit], score
    return best if best_score >= 0.5 else []


def _stored_marks(chunk: Optional[Dict[str, Any]], cell: Optional[Tuple[int, int]]) -> Optional[Dict[int, List[List[float]]]]:
    """청커 v4 가 저장한 상자 → {쪽: [[x0, y0, x1, y1], …]}. 칸이면 그 칸 상자 하나. 없으면 None(글로 찾는다)."""
    if not chunk:
        return None
    if cell:
        cells = chunk.get("cells") or []
        r, c = cell
        b = cells[r][c] if r < len(cells) and c < len(cells[r]) else None
        return {int(chunk["page"]): [list(b)]} if b and chunk.get("page") else None
    out: Dict[int, List[List[float]]] = {}
    for b in chunk.get("boxes") or []:
        if len(b) == 5:
            out.setdefault(int(b[0]), []).append([float(x) for x in b[1:]])
    return out or None


def _pdf(path: Path, chunk: Optional[Dict[str, Any]], cell: Optional[Tuple[int, int]]) -> Dict[str, Any]:
    import fitz  # PyMuPDF

    doc = fitz.open(str(path))
    try:
        stored = _stored_marks(chunk, cell)
        if stored:
            pages = sorted(p for p in stored if 1 <= p <= len(doc))
        if stored and pages:
            first = doc[pages[0] - 1]
            w, h = first.rect.width, first.rect.height
            return {
                "kind": "pdf",
                "page": pages[0],
                "pages": len(doc),
                "ratio": round(h / w, 4) if w else 1.414,
                "rects": stored[pages[0]],
                "marks": {str(p): stored[p] for p in pages},
                "found": True,
                "where": f"p.{pages[0]}" + (f"~{pages[-1]}" if len(pages) > 1 else ""),
            }
        page_no = int((chunk or {}).get("page") or 1)
        page_no = min(max(page_no, 1), len(doc))
        page = doc[page_no - 1]
        w, h = page.rect.width, page.rect.height
        rects: List[Any] = []
        if chunk and cell and chunk.get("rows"):
            rows = chunk["rows"]
            raw = rows[cell[0]][cell[1]].strip() if cell[0] < len(rows) and cell[1] < len(rows[cell[0]]) else ""
            label = (rows[cell[0]][0] if rows[cell[0]] else "").strip()
            hits = page.search_for(raw) if raw else []
            if label and hits:
                lab = page.search_for(label[:24])
                same = [r for r in hits if any(abs((r.y0 + r.y1) / 2 - (l.y0 + l.y1) / 2) < max(3.0, (l.y1 - l.y0) * 0.6) for l in lab)]
                hits = same or (hits if len(hits) == 1 else [])
            rects = hits[:1]
        elif chunk and chunk.get("rows") and (rows := [fitz.Rect(b) for b in _table_rows(page, chunk["rows"])]):
            rects = rows
        elif chunk:
            text = chunk.get("text") or ""
            blocks = [b for b in page.get_text("blocks") if len(b) >= 5 and str(b[4]).strip()]
            scored = [(fitz.Rect(b[:4]), _overlap(text, str(b[4]))) for b in blocks]
            rects = [r for r, s in scored if s >= 0.6]
            if not rects and scored:
                best = max(scored, key=lambda x: x[1])
                rects = [best[0]] if best[1] >= 0.3 else []
        return {
            "kind": "pdf",
            "page": page_no,
            "pages": len(doc),
            "ratio": round(h / w, 4) if w else 1.414,
            "rects": [[round(r.x0 / w, 4), round(r.y0 / h, 4), round(r.x1 / w, 4), round(r.y1 / h, 4)] for r in rects],
            "found": bool(rects),
            "where": f"p.{page_no}",
        }
    finally:
        doc.close()


@lru_cache(maxsize=48)
def page_png(doc_id: str, page_no: int, zoom: float = 2.0) -> bytes:
    import fitz

    _meta, path = _source(doc_id)
    doc = fitz.open(str(path))
    try:
        if not 1 <= page_no <= len(doc):
            raise ValueError("그런 쪽이 없습니다.")
        return doc[page_no - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")
    finally:
        doc.close()


# ── 엑셀 ────────────────────────────────────────────────────────────────

def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _xlsx(path: Path, chunk: Optional[Dict[str, Any]], cell: Optional[Tuple[int, int]]) -> Dict[str, Any]:
    from openpyxl import load_workbook

    from app.docs.extract import _xlsx_value

    wb = load_workbook(str(path), data_only=True)
    try:
        sheet = (chunk or {}).get("sheet") or wb.worksheets[0].title
        ws = wb[sheet] if sheet in wb.sheetnames else wb.worksheets[0]
        grid = [[_xlsx_value(c) for c in row] for row in ws.iter_rows(max_row=2000)]
        width = max((len(r) for r in grid), default=0)
        grid = [r + [""] * (width - len(r)) for r in grid]
        hit: Optional[Tuple[int, int]] = None
        span: List[int] = []
        rows = (chunk or {}).get("rows") or []
        if cell and rows:
            raw = rows[cell[0]][cell[1]] if cell[0] < len(rows) and cell[1] < len(rows[cell[0]]) else ""
            label = rows[cell[0]][0] if rows[cell[0]] else ""
            for r, row in enumerate(grid):
                if label and _norm(label) not in {_norm(x) for x in row if x}:
                    continue
                c = next((j for j, x in enumerate(row) if x and _norm(x) == _norm(raw)), None)
                if c is not None:
                    hit = (r, c)
                    break
        elif rows:
            head = [_norm(x) for x in rows[0] if x]
            r0 = next((r for r, row in enumerate(grid) if head and [_norm(x) for x in row if x][: len(head)] == head), None)
            if r0 is not None:
                span = list(range(r0, min(len(grid), r0 + len(rows))))
        center = hit[0] if hit else (span[0] if span else 0)
        top = max(0, center - 6)
        bottom = min(len(grid), max(center + 12, (span[-1] + 2) if span else 0))
        used = [j for j in range(width) if any(grid[r][j] for r in range(top, bottom))] or list(range(min(width, 8)))
        cols = list(range(used[0], min(used[-1] + 1, used[0] + 14)))
        return {
            "kind": "sheet",
            "sheet": ws.title,
            "cols": [_col(j) for j in cols],
            "rowNums": [r + 1 for r in range(top, bottom)],
            "grid": [[grid[r][j] for j in cols] for r in range(top, bottom)],
            "hl": [[hit[0] - top, hit[1] - cols[0]]] if hit and cols[0] <= hit[1] <= cols[-1] else [[r - top, -1] for r in span],
            "found": bool(hit or span),
            "where": f"시트 {ws.title}" + (f" · {_col(hit[1])}{hit[0] + 1}" if hit else ""),
        }
    finally:
        wb.close()


# ── 워드 ────────────────────────────────────────────────────────────────

def _docx(path: Path, chunk: Optional[Dict[str, Any]], cell: Optional[Tuple[int, int]]) -> Dict[str, Any]:
    from docx import Document
    from docx.table import Table

    from app.docs.extract import _docx_rows
    from app.report.template_docx import _body_items

    d = Document(str(path))
    blocks: List[Dict[str, Any]] = []
    for kind, it in _body_items(d):
        if kind == "p":
            t = re.sub(r"\s+", " ", it.text).strip()
            if t:
                blocks.append({"type": "p", "text": t})
        else:
            rows = _docx_rows(Table(it, d))
            if rows:
                blocks.append({"type": "table", "rows": rows})
    at, hl = None, None
    rows = (chunk or {}).get("rows") or []
    if cell and rows:
        raw = rows[cell[0]][cell[1]] if cell[0] < len(rows) and cell[1] < len(rows[cell[0]]) else ""
        label = rows[cell[0]][0] if rows[cell[0]] else ""
        for i, b in enumerate(blocks):
            if b["type"] != "table":
                continue
            for r, row in enumerate(b["rows"]):
                if label and (not row or _norm(row[0]) != _norm(label)):
                    continue
                c = next((j for j, x in enumerate(row) if _norm(x) == _norm(raw)), None)
                if c is not None:
                    at, hl = i, [r, c]
                    break
            if at is not None:
                break
    elif chunk:
        text = chunk.get("text") or ""
        scored = [(i, _overlap(text, b["text"] if b["type"] == "p" else " ".join(" ".join(r) for r in b["rows"]))) for i, b in enumerate(blocks)]
        best = max(scored, key=lambda x: x[1], default=(None, 0.0))
        if best[0] is not None and best[1] >= 0.5:
            at = best[0]
    center = at if at is not None else 0
    lo, hi = max(0, center - 3), min(len(blocks), center + 4)
    return {"kind": "docx", "blocks": blocks[lo:hi], "at": (at - lo) if at is not None else None, "cell": hl, "found": at is not None, "where": f"문단 {at + 1}" if at is not None else ""}


# ── 글 ──────────────────────────────────────────────────────────────────

def _text(path: Path, chunk: Optional[Dict[str, Any]], cell: Optional[Tuple[int, int]]) -> Dict[str, Any]:
    raw = path.read_bytes()
    text = next((raw.decode(enc) for enc in ("utf-8-sig", "cp949") if _decodes(raw, enc)), raw.decode("utf-8", "replace"))
    lines = text.splitlines()
    target = ""
    if chunk and cell and chunk.get("rows"):
        rows = chunk["rows"]
        target = rows[cell[0]][cell[1]] if cell[0] < len(rows) and cell[1] < len(rows[cell[0]]) else ""
        label = rows[cell[0]][0] if rows[cell[0]] else ""
        idx = [i for i, l in enumerate(lines) if _norm(target) and _norm(target) in _norm(l) and (not label or _norm(label) in _norm(l))]
    elif chunk:
        body = chunk.get("text") or ""
        scored = [(i, _overlap(body, l)) for i, l in enumerate(lines) if len(l.strip()) > 3]
        top = max((s for _i, s in scored), default=0.0)
        idx = [i for i, s in scored if s >= max(0.6, top * 0.9)] if top >= 0.5 else []
    else:
        idx = []
    center = idx[0] if idx else 0
    lo, hi = max(0, center - 6), min(len(lines), (idx[-1] if idx else center) + 8)
    return {"kind": "text", "lines": lines[lo:hi], "lineNums": list(range(lo + 1, hi + 1)), "hl": [i - lo for i in idx if lo <= i < hi], "mark": target, "found": bool(idx), "where": f"{idx[0] + 1}줄" if idx else ""}


def _decodes(raw: bytes, enc: str) -> bool:
    try:
        raw.decode(enc)
        return True
    except UnicodeDecodeError:
        return False


def locate(doc_id: str, chunk_id: Optional[str] = None, cell: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
    meta, path = _source(doc_id)
    chunk = _chunk(doc_id, chunk_id) if chunk_id else None
    ext = path.suffix.lower()
    if ext == ".pdf":
        out = _pdf(path, chunk, cell)
    elif ext in (".xlsx", ".xlsm"):
        out = _xlsx(path, chunk, cell)
    elif ext == ".docx":
        out = _docx(path, chunk, cell)
    else:
        out = _text(path, chunk, cell)
    return {"docId": doc_id, "label": doc_label(meta, doc_id), "fileName": meta.get("fileName") or path.name, "extracted": _extracted(doc_id, chunk, cell) if chunk else None, **out}


__all__ = ["locate", "page_png"]
