"""검수 결과 → Word. 다른 부서 문서에 의견을 돌려줄 때 쓰는 모양 그대로.

 - 대상이 DOCX: **원본 파일에 Word 메모**(python-docx add_comment)를 단다 — 지적한 숫자 글자에 정확히(런을 쪼개 앵커),
   못 찾으면 그 문단 전체, 문단도 못 찾으면 첫 문단의 요약 메모에 모은다. 본문은 한 글자도 고치지 않는다.
   표 칸 지적은 청크에 남은 행(rows)의 첫 칸(지표 이름)과 값으로 Word 표의 칸을 찾는다.
 - 대상이 PDF·XLSX 등: 같은 내용을 **검수 의견서 DOCX**(요약 + 지적 표)로 만든다.
메모 문구는 검수 규칙의 메시지·근거(자료·쪽·칸·값)·계산식 그대로 — LLM 이 새로 쓰지 않는다.
"""
from __future__ import annotations

import copy
import io
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from app.docs.store import doc_dir, doc_label, load_chunks, load_meta
from app.review.rules import RULE_KO

AUTHOR = "AssociateLM"
INITIALS = "AL"
_SIMPLE = {qn("w:rPr"), qn("w:t")}


def _ns(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


# ── 메모 문구 ───────────────────────────────────────────────────────────

def _where(e: Dict[str, Any]) -> str:
    loc = f"p.{e['page']}" if e.get("page") else (f"시트 {e['sheet']}" if e.get("sheet") else "")
    cell = f"표 {e['cell'][0] + 1}행 {e['cell'][1] + 1}열" if e.get("cell") else ""
    return " ".join(x for x in (loc, cell) if x)


def memo_text(f: Dict[str, Any]) -> str:
    lines = [f"[{RULE_KO.get(f['rule'], f['rule'])}] {f['message']}"]
    if f.get("formula"):
        lines.append(f"계산식: {f['formula']}")
    ev = f.get("evidence") or []
    if ev:
        lines.append("근거: " + " / ".join(f"{e['docLabel']}{(' ' + _where(e)) if _where(e) else ''} = {e['display']}" for e in ev[:3]))
    return "\n".join(lines)


def summary_text(review: Dict[str, Any], unplaced: Sequence[Dict[str, Any]]) -> str:
    s = review.get("summary") or {}
    c = s.get("counts") or {}
    head = f"{AUTHOR} 검수 — 숫자 주장 {s.get('claims', 0)}건 · " + " · ".join(f"{RULE_KO[k]} {c.get(k, 0)}" for k in ("mismatch", "calc", "unsourced", "internal", "ok"))
    lines = [head, f"근거: 워크스페이스 자료 {s.get('referenceDocs', 0)}개의 표 칸 원장(코드 대조). 메모는 지적 위치에 달았습니다."]
    if unplaced:
        lines.append("본문에서 위치를 찾지 못한 지적:")
        lines += [f"- {memo_text(f).splitlines()[0]}" for f in unplaced]
    return "\n".join(lines)


# ── DOCX 안에서 위치 찾기 ───────────────────────────────────────────────

def _paragraphs(doc: DocxDocument) -> Iterator[Paragraph]:
    yield from doc.paragraphs
    for t in doc.tables:
        yield from _table_paragraphs(t)


def _table_paragraphs(t: Table) -> Iterator[Paragraph]:
    for row in t.rows:
        for cell in row.cells:
            yield from cell.paragraphs
            for inner in cell.tables:
                yield from _table_paragraphs(inner)


def _simple(r: Run) -> bool:
    return all(ch.tag in _SIMPLE for ch in r._r)


def _split_at(p: Paragraph, pos: int) -> None:
    """pos 가 런 한가운데면 그 런을 둘로(서식 그대로). 글자 말고 다른 것이 든 런은 쪼개지 않는다."""
    start = 0
    for r in p.runs:
        end = start + len(r.text)
        if start < pos < end and _simple(r):
            text = r.text
            twin = copy.deepcopy(r._r)
            r._r.addnext(twin)
            r.text = text[: pos - start]
            Run(twin, p).text = text[pos - start :]
            return
        start = end


def _anchor(p: Paragraph, needle: str) -> Optional[List[Run]]:
    """문단 안 needle 글자를 덮는 런들. 정확히 못 찾으면(띄어쓰기 차이) 문단 전체 런."""
    full = "".join(r.text for r in p.runs)
    i = full.find(needle) if needle else -1
    if i < 0:
        runs = [r for r in p.runs if r.text]
        return runs or None
    j = i + len(needle)
    _split_at(p, j)
    _split_at(p, i)
    out, start = [], 0
    for r in p.runs:
        end = start + len(r.text)
        if start < j and end > i and r.text:
            out.append(r)
        start = end
    return out or None


def _find_prose(doc: DocxDocument, quote: str, raw: str) -> Optional[Paragraph]:
    q = _ns(quote)
    if not q:
        return None
    for p in _paragraphs(doc):
        t = _ns(p.text)
        if t and (q in t or (len(q) > 24 and q[:24] in t)) and (not raw or _ns(raw) in t):
            return p
    return None


def _find_cell(doc: DocxDocument, row_cells: Sequence[str], col: int, raw: str) -> Optional[Paragraph]:
    """청크 행의 첫 칸(지표 이름)이 같은 Word 표 행에서 값이 든 칸 — 같은 열을 먼저, 없으면 그 행에서 값이 든 칸."""
    label = _ns(row_cells[0]) if row_cells else ""
    for t in doc.tables:
        for row in t.rows:
            cells = row.cells
            if not cells or _ns(cells[0].text) != label:
                continue
            order = ([cells[col]] if col < len(cells) else []) + list(cells)
            for c in order:
                if _ns(raw) and _ns(raw) in _ns(c.text):
                    for p in c.paragraphs:
                        if _ns(raw) in _ns(p.text):
                            return p
    return None


def _locate(doc: DocxDocument, f: Dict[str, Any], chunks: Dict[str, Dict[str, Any]]) -> Optional[Tuple[Paragraph, str]]:
    c = f.get("claim") or {}
    raw = str(c.get("raw") or "")
    if c.get("source") == "table" and c.get("cell"):
        rows = (chunks.get(c.get("chunk") or "") or {}).get("rows") or []
        ri, ci = c["cell"][:2]
        if 0 <= ri < len(rows):
            p = _find_cell(doc, rows[ri], ci, raw)
            if p is not None:
                return p, raw
    p = _find_prose(doc, str(c.get("quote") or ""), raw)
    return (p, raw) if p is not None else None


def _first_paragraph(doc: DocxDocument) -> Optional[Paragraph]:
    return next((p for p in doc.paragraphs if p.text.strip()), None)


# ── 만들기 ─────────────────────────────────────────────────────────────

def annotate_docx(src: Path, review: Dict[str, Any]) -> Tuple[bytes, Dict[str, int]]:
    """원본 DOCX + Word 메모. → (파일 바이트, {placed, unplaced})."""
    doc = Document(str(src))
    chunks = {c.get("id"): c for c in load_chunks(review["docId"])}
    findings = [f for f in review.get("findings") or [] if f.get("rule") != "ok"]
    unplaced: List[Dict[str, Any]] = []
    placed = 0
    for f in findings:
        hit = _locate(doc, f, chunks)
        runs = _anchor(*hit) if hit else None
        if not runs:
            unplaced.append(f)
            continue
        doc.add_comment(runs, text=memo_text(f), author=AUTHOR, initials=INITIALS)
        placed += 1
    first = _first_paragraph(doc)
    if first is not None and first.runs:
        doc.add_comment([r for r in first.runs if r.text] or first.runs, text=summary_text(review, unplaced), author=AUTHOR, initials=INITIALS)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), {"placed": placed, "unplaced": len(unplaced)}


def opinion_docx(review: Dict[str, Any], label: str, reviewer: str) -> bytes:
    """원본이 DOCX 가 아닐 때 — 검수 의견서(요약 + 지적 표)."""
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "맑은 고딕"  # rFonts 를 만든 뒤에 동아시아 글꼴을 건다(report/export.py 와 같게)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), "맑은 고딕")
    style.font.size = Pt(10)
    doc.add_heading(f"검수 의견서 — {label}", level=1)
    s = review.get("summary") or {}
    c = s.get("counts") or {}
    doc.add_paragraph(f"대상: {label} ({review.get('fileName') or ''}) · 검수: {reviewer} · {str(review.get('finishedAt') or '')[:16].replace('T', ' ')} (UTC)")
    doc.add_paragraph(f"숫자 주장 {s.get('claims', 0)}건 — " + " · ".join(f"{RULE_KO[k]} {c.get(k, 0)}" for k in ("mismatch", "calc", "unsourced", "internal", "ok")) + f". 근거: 워크스페이스 자료 {s.get('referenceDocs', 0)}개의 표 칸 원장(코드 대조).")
    findings = [f for f in review.get("findings") or [] if f.get("rule") != "ok"]
    if not findings:
        doc.add_paragraph("지적할 것이 없습니다.")
    else:
        t = doc.add_table(rows=1, cols=5)
        t.style = "Table Grid"
        for i, h in enumerate(("번호", "종류", "문서 표기·위치", "지적", "근거")):
            t.rows[0].cells[i].text = h
        for n, f in enumerate(findings, 1):
            cl = f.get("claim") or {}
            where = f"표 {cl['cell'][0] + 1}행 {cl['cell'][1] + 1}열" if cl.get("cell") else ""
            ev = f.get("evidence") or []
            cells = t.add_row().cells
            cells[0].text = str(n)
            cells[1].text = RULE_KO.get(f["rule"], f["rule"])
            cells[2].text = f"{cl.get('raw') or ''} {where}\n“{cl.get('quote') or ''}”".strip()
            cells[3].text = f["message"] + (f"\n계산식: {f['formula']}" if f.get("formula") else "")
            cells[4].text = "\n".join(f"{e['docLabel']} {_where(e)} = {e['display']}".strip() for e in ev[:3])
    doc.add_paragraph("")
    doc.add_paragraph(f"이 의견서는 {AUTHOR}가 자료의 표 칸 원장과 코드로 대조해 만든 것입니다. 최종 판단은 담당자가 합니다.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def review_memo(review: Dict[str, Any], reviewer: str) -> Tuple[bytes, str, Dict[str, int]]:
    """→ (DOCX 바이트, 파일 이름, {placed, unplaced})."""
    meta = load_meta(review["docId"]) or {}
    label = doc_label(meta, review["docId"])
    src = doc_dir(review["docId"]) / str(meta.get("source") or "")
    stem = Path(meta.get("fileName") or label).stem
    if meta.get("source") and src.is_file() and src.suffix.lower() == ".docx":
        data, stats = annotate_docx(src, review)
        return data, f"{stem}_검수메모.docx", stats
    findings = [f for f in review.get("findings") or [] if f.get("rule") != "ok"]
    return opinion_docx(review, label, reviewer), f"{stem}_검수의견서.docx", {"placed": 0, "unplaced": len(findings)}


__all__ = ["annotate_docx", "memo_text", "opinion_docx", "review_memo"]
