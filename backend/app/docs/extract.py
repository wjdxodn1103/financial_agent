"""문서 추출 — PDF·DOCX·XLSX·TXT·MD → 문단 목록 [{"page", "text", "heading"?, "kind": "prose"|"table", "rows"?, "unit"?, "sheet"?}].
**내용만** 뽑는다(서식은 버린다). 형식 → 추출 함수는 EXTRACTORS 등록표 한 곳(HWP 등은 여기에 하나 더한다).

OP 의 논문 청커에서 가져온 것은 PDF 조판 문단 인식(layout.py)뿐이다 — 논문 전용 규칙은 금융 문서에 맞지 않아 뺐다.
표는 칸 구조(rows: 첫 행 = 머리글)를 그대로 남긴다 — 근거 원장(figures)이 칸 좌표를 출처로 쓰고, 근거 보기가 표로 그린다.
 - PDF: PyMuPDF find_tables 로 칸 구조 표를 먼저 뽑고(그 영역의 줄은 문단에서 뺀다), 나머지는 조판 문단(layout.py).
        칸 구조를 못 잡은 숫자 줄은 예전처럼 kind="table"(rows 없음) 줄 묶음으로 남긴다.
 - DOCX: 본문 순서대로 문단·표. 제목 스타일(Heading/제목) 문단은 heading 메타.
 - XLSX: 시트마다 빈 행으로 나뉜 덩어리 = 표 하나. 위쪽 한 칸짜리 줄은 제목·단위로.
 - TXT/MD: 빈 줄로 문단, "#" 제목은 heading 메타, "|" 표는 칸 구조로.
표 단위 문구("(단위: 백만원)")는 표 위·첫 행에서 찾아 unit 에 둔다(원장이 배율로 쓴다).
쪽 번호는 PDF 만 있다(그 밖은 None — 화면은 "문단 n"·"시트 이름" 으로 보인다).
청커 v4: PDF 문단은 boxes(쪽별 줄 상자, layout.py), PDF 칸 구조 표는 cells(칸마다 [x0, y0, x1, y1] 0~1 — 칸이 없으면 None),
모든 형식에 heading_path(위 제목부터 — PDF 는 글자 크기, DOCX 는 제목 스타일 수준, MD 는 # 개수, 그 밖은 번호 깊이로 수준을 정한다).
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

Para = Dict[str, Any]

SUPPORTED: Dict[str, str] = {".pdf": "PDF", ".docx": "DOCX", ".xlsx": "XLSX", ".xlsm": "XLSX", ".txt": "TXT", ".md": "MD", ".markdown": "MD"}
SUPPORTED_LABEL = "PDF·DOCX·XLSX·TXT·MD"

_LETTERS = re.compile(r"[A-Za-z가-힣]")
_DIGIT = re.compile(r"[0-9]")
_NUMERIC_CELL = re.compile(r"^[\s(△▲▼\-–+]*[\d,]+(?:\.\d+)?\s*%?\)?\s*$")
_NUM_FMT = re.compile(r"[0#](?:\.(0+))?")  # 엑셀 숫자 서식의 소수 자리(0.00 → 2)
_END = re.compile(r"[.!?。]\s*$|다\.\s*$|[.!?][\"”’)\]]\s*$|(?:함|음|됨|임)\.?\s*$")
_HEADING_NUM = re.compile(r"^\s*(?:\d{1,2}(?:\.\d{1,2}){0,3}\.?|[IVX]{1,4}\.|[가-힣]\.|\(?[a-z0-9]\)|[①-⑳]|[■□●▶◆▪]|Ⅰ|Ⅱ|Ⅲ|Ⅳ|Ⅴ|Ⅵ)\s*\S")
UNIT_RX = re.compile(r"[(\[]?\s*(?:단위|unit|Unit|UNIT)\s*[:：]?\s*([^)\]\n]{1,24})[)\]]?")
TABLE_DIGIT_RATIO = 0.3  # 이보다 숫자가 많으면 표 줄로 본다(논문 청커는 0.35 를 넘으면 버렸다)
TABLE_MERGE_CHARS = 1200  # 칸 구조 없는 연속 표 줄을 이 길이까지 한 문단으로
XLSX_MAX_ROWS = 2000  # 시트 하나에서 읽는 행 상한(거대한 원시 데이터 시트 방지)


def file_type_of(file_name: str) -> Optional[str]:
    return SUPPORTED.get(Path(file_name).suffix.lower())


def _ends_sentence(s: str) -> bool:
    return bool(_END.search(s))


_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def _digit_ratio(text: str) -> float:
    """숫자 비율 — 연도(2024 등)는 세지 않는다("A사 2024 IR 자료" 같은 제목이 표 줄로 잡히지 않게)."""
    t = _YEAR.sub("", text)
    return len(_DIGIT.findall(t)) / max(1, len(t))


def _is_heading(text: str, bold: bool = False) -> bool:
    """제목 줄 — 글자 60 이하·문장 끝 아님·(번호/기호 제목 또는 굵게 또는 글자 30 이하)·숫자 30% 미만."""
    letters = len(_LETTERS.findall(text))
    if letters < 2 or _digit_ratio(text) > 0.3:
        return False
    return letters <= 60 and len(text) <= 80 and not _ends_sentence(text) and (bool(_HEADING_NUM.match(text)) or bold or letters <= 30)


_NUM_DEPTH = [(re.compile(r"^\s*\d{1,2}\.\d{1,2}\.\d{1,2}"), 3), (re.compile(r"^\s*\d{1,2}\.\d{1,2}"), 2), (re.compile(r"^\s*(?:\d{1,2}[.)]|[IVX]{1,4}\.|Ⅰ|Ⅱ|Ⅲ|Ⅳ|Ⅴ|Ⅵ)"), 1), (re.compile(r"^\s*[가-힣]\."), 3), (re.compile(r"^\s*(?:\(?\d{1,2}\)|[①-⑳]|\(?[a-z]\))"), 4)]


def num_depth(text: str, default: float = 5) -> float:
    """번호로 본 제목 깊이 — '1.' 1, '1.1' 2, '가.' 3, '(1)' 4, 번호 없음 = default."""
    return next((d for rx, d in _NUM_DEPTH if rx.match(text)), default)


class HeadingTrail:
    """제목 경로 — 새 제목은 같거나 아래 수준(level 이 같거나 큰)의 앞 제목을 밀어내고 들어간다. level 이 작을수록 위."""

    def __init__(self) -> None:
        self.stack: List[tuple] = []

    def push(self, text: str, level: float) -> None:
        while self.stack and self.stack[-1][0] >= level:
            self.stack.pop()
        self.stack.append((level, text.strip()[:120]))

    def path(self) -> List[str]:
        return [t for _, t in self.stack]


def unit_of(text: str) -> Optional[str]:
    m = UNIT_RX.search(text or "")
    return m.group(1).strip(" .,") if m else None


def _clean_cell(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()


def table_text(rows: List[List[str]]) -> str:
    return "\n".join(" | ".join(r).strip(" |") for r in rows if any(r))


def normalize_rows(rows: List[List[Any]]) -> List[List[str]]:
    """칸 문자열화 + 빈 행·빈 열 제거 + 행 길이 맞춤."""
    rs = [[_clean_cell(c) for c in r] for r in rows]
    rs = [r for r in rs if any(r)]
    if not rs:
        return []
    width = max(len(r) for r in rs)
    rs = [r + [""] * (width - len(r)) for r in rs]
    keep = [j for j in range(width) if any(r[j] for r in rs)]
    return [[r[j] for j in keep] for r in rs]


def is_data_table(rows: List[List[str]]) -> bool:
    """칸 구조로 둘 만한 표인가 — 2행·2열 이상이고 숫자 칸이 있다."""
    if len(rows) < 2 or max(len(r) for r in rows) < 2:
        return False
    return any(_NUMERIC_CELL.match(c) for r in rows[1:] for c in r[1:] if c)


def table_para(rows: List[List[str]], *, page: Optional[int] = None, heading: Optional[str] = None, unit: Optional[str] = None, sheet: Optional[str] = None, heading_path: Optional[List[str]] = None, cells: Optional[List[List[Any]]] = None) -> Para:
    p: Para = {"page": page, "text": table_text(rows), "kind": "table", "rows": rows}
    if heading:
        p["heading"] = heading
    if heading_path:
        p["heading_path"] = heading_path
    if cells and len(cells) == len(rows):
        p["cells"] = cells
    unit = unit or next((u for u in (unit_of(c) for c in rows[0]) if u), None)
    if unit:
        p["unit"] = unit
    if sheet:
        p["sheet"] = sheet
    return p


def _merge_tables(paras: List[Para]) -> List[Para]:
    """같은 쪽·같은 제목 아래 연속된 (칸 구조 없는) 표 줄을 한 문단으로 — 행 하나가 문단 하나로 흩어지지 않게."""
    out: List[Para] = []
    for p in paras:
        q = out[-1] if out else None
        if (
            q is not None
            and p["kind"] == "table"
            and q["kind"] == "table"
            and not p.get("rows")
            and not q.get("rows")
            and q.get("page") == p.get("page")
            and q.get("heading") == p.get("heading")
            and len(q["text"]) + len(p["text"]) <= TABLE_MERGE_CHARS
        ):
            q["text"] = f"{q['text']}\n{p['text']}"
            q["boxes"] = [*(q.get("boxes") or []), *(p.get("boxes") or [])]
            continue
        out.append(dict(p))
    return out


# ── PDF ─────────────────────────────────────────────────────────────────

def _pdf_tables(doc: Any) -> Dict[int, List[Dict[str, Any]]]:
    """쪽마다 칸 구조 표 [{bbox, rows, unit, caption}] — find_tables 가 못 잡거나 숫자 없는 표는 버린다(그 줄은 조판 문단으로 남는다)."""
    out: Dict[int, List[Dict[str, Any]]] = {}
    for pno, page in enumerate(doc, 1):
        try:
            found = page.find_tables()
        except Exception:  # noqa: BLE001 — 표 찾기 실패는 문단 추출로 넘어간다
            continue
        w, h = page.rect.width or 1.0, page.rect.height or 1.0
        for t in getattr(found, "tables", []) or []:
            raw = t.extract() or []
            rows = normalize_rows(raw)
            if not is_data_table(rows):
                continue
            x0, y0, x1, y1 = t.bbox
            above = page.get_textbox((x0 - 40, max(0, y0 - 60), x1 + 40, y0)) or ""
            out.setdefault(pno, []).append({"bbox": (x0, y0, x1, y1), "rows": rows, "unit": unit_of(above), "caption": _caption(above), "cells": _cell_boxes(raw, t, w, h, rows)})
    return out


def _cell_boxes(raw: List[List[Any]], t: Any, w: float, h: float, rows: List[List[str]]) -> Optional[List[List[Any]]]:
    """normalize_rows 와 같은 행·열 버리기를 칸 상자에도 — rows[r][c] ↔ cells[r][c]. 맞지 않으면 None(원문 창이 글로 찾는다)."""
    try:
        boxes = [list(t.rows[i].cells) for i in range(len(raw))]
    except Exception:  # noqa: BLE001
        return None
    rs = [[_clean_cell(c) for c in r] for r in raw]
    idx = [i for i, r in enumerate(rs) if any(r)]
    if not idx:
        return None
    width = max(len(rs[i]) for i in idx)
    rs2 = [rs[i] + [""] * (width - len(rs[i])) for i in idx]
    bx2 = [boxes[i] + [None] * (width - len(boxes[i])) for i in idx]
    keep = [j for j in range(width) if any(r[j] for r in rs2)]
    out = [[[round(b[0] / w, 4), round(b[1] / h, 4), round(b[2] / w, 4), round(b[3] / h, 4)] if b else None for b in (r[j] for j in keep)] for r in bx2]
    return out if [[r[j] for j in keep] for r in rs2] == rows else None


def _strip_unit(line: str) -> str:
    """'사업 부문별 매출 (2024, 단위: 억원)' → '사업 부문별 매출 (2024)' — 단위 문구만 빼고 나머지(연도 등)는 남긴다."""
    s = UNIT_RX.sub("", line)
    s = re.sub(r"[,\s]+$", "", s)
    if s.count("(") > s.count(")"):
        s += ")"
    s = re.sub(r"\(\s*\)", "", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def _caption(above: str) -> Optional[str]:
    """표 바로 위 줄 가운데 제목 같은 것 — 단위 문구는 떼고(단위는 unit 으로 따로 붙는다), 단위만 있는 줄은 건너뛴다."""
    for line in reversed([l.strip() for l in above.split("\n") if l.strip()]):
        cleaned = _strip_unit(line)
        if not cleaned:
            continue  # '(단위: 억원)' 만 있는 줄 — 그 위 줄을 본다
        return cleaned if _is_heading(cleaned, False) else None
    return None


def pdf_paragraphs(layout: List[Dict[str, Any]], tables: Optional[Dict[int, List[Dict[str, Any]]]] = None) -> List[Para]:
    out: List[Para] = []
    pending: Optional[str] = None
    used = False  # pending 제목을 표 줄이 이미 받았다 — 다음 제목은 잇지 않고 바꾼다
    trail = HeadingTrail()  # 제목 경로 — 글자가 클수록 위, 같은 크기면 번호 깊이로
    for p in layout:
        text = (p.get("text") or "").strip()
        if not text:
            continue
        if UNIT_RX.fullmatch(text) or p.get("caption"):
            continue  # 표 위 단위 줄·표 제목 줄 — 칸 구조 표의 unit·제목(caption)으로 이미 붙었다
        if _is_heading(text, bool(p.get("bold"))):
            pending = text if pending is None or used or len(pending) > 120 else f"{pending} / {text}"
            used = False
            trail.push(text, -float(p.get("size") or 10.0) + num_depth(text, 0) * 0.01)
            continue
        letters = len(_LETTERS.findall(text))
        table = _digit_ratio(text) > TABLE_DIGIT_RATIO
        if not table and letters < 8:
            continue  # 기호·쪽 번호 조각
        if table and len(text) < 6:
            continue
        para: Para = {"page": p.get("page"), "text": text, "kind": "table" if table else "prose", "y0": p.get("y0", 0.0)}
        if p.get("boxes"):
            para["boxes"] = p["boxes"]
        if trail.stack:
            para["heading_path"] = trail.path()
        if pending:
            para["heading"] = pending
        # 표 줄은 제목을 다음 줄들과 나눠 쓴다(같은 제목 아래 연속 표 줄이 합쳐지게) — 산문은 제목을 한 번만 받는다
        if table:
            used = True
        else:
            pending = None
        out.append(para)
    out = _merge_tables(out)
    if tables:
        out = _insert_tables(out, tables)
    for p in out:
        p.pop("y0", None)
    return out


def _insert_tables(paras: List[Para], tables: Dict[int, List[Dict[str, Any]]]) -> List[Para]:
    """칸 구조 표를 같은 쪽의 위치(y) 순서에 끼운다. 표 제목은 표 위 캡션, 없으면 바로 앞 문단의 제목(heading)."""
    result: List[Para] = []
    queue: Dict[int, List[Dict[str, Any]]] = {k: sorted(v, key=lambda t: t["bbox"][1]) for k, v in tables.items()}
    last_heading: Optional[str] = None
    last_path: List[str] = []

    def flush(page: int, before_y: Optional[float]) -> None:
        q = queue.get(page) or []
        while q and (before_y is None or q[0]["bbox"][1] <= before_y):
            t = q.pop(0)
            path = [*last_path, t["caption"]] if t.get("caption") else last_path
            result.append(table_para(t["rows"], page=page, heading=t.get("caption") or last_heading, unit=t.get("unit"), heading_path=path or None, cells=t.get("cells")))

    cur_page: Optional[int] = None
    for p in paras:
        page = p.get("page") or 0
        if cur_page is not None and page != cur_page:
            for k in sorted(k for k in queue if cur_page <= k < page):
                flush(k, None)
        cur_page = page
        flush(page, p.get("y0"))
        result.append(p)
        last_heading = p.get("heading") or last_heading
        last_path = p.get("heading_path") or last_path
    for k in sorted(queue):
        flush(k, None)
    return result


def extract_pdf(path: str | Path) -> Dict[str, Any]:
    import fitz  # PyMuPDF

    from app.docs.layout import layout_paragraphs

    doc = fitz.open(str(path))
    try:
        tables = _pdf_tables(doc)
        exclude = {pno: [t["bbox"] for t in ts] for pno, ts in tables.items()}
        paras = pdf_paragraphs(layout_paragraphs(doc, exclude), tables)
        meta = doc.metadata or {}
        first_page = doc[0].get_text("text") if len(doc) else ""
        return {
            "paras": paras,
            "meta": {"title": (meta.get("title") or "").strip(), "author": (meta.get("author") or "").strip(), "pageCount": len(doc)},
            "frontText": first_page[:3000],
        }
    finally:
        doc.close()


# ── DOCX ────────────────────────────────────────────────────────────────

def _docx_rows(table: Any) -> List[List[str]]:
    # 병합 칸은 같은 글이 되풀이된다 — 칸 좌표를 지키려고 그대로 둔다
    return normalize_rows([[c.text for c in row.cells] for row in table.rows])


def extract_docx(path: str | Path) -> Dict[str, Any]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = Document(str(path))
    paras: List[Para] = []
    pending: Optional[str] = None
    first_heading = ""
    last_text = ""
    trail = HeadingTrail()
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(child, d)
            text = re.sub(r"\s+", " ", p.text).strip()
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            bold = bool(p.runs) and all(r.bold for r in p.runs if r.text.strip())
            last_text = text
            if UNIT_RX.fullmatch(text.strip()):
                continue  # 표 위 단위 줄 — 다음 표의 unit 으로 쓴다
            if re.match(r"(Heading|Title|제목)", style, re.I) or _is_heading(text, bold):
                pending = text
                first_heading = first_heading or text
                lv = re.search(r"(\d+)", style) if re.match(r"(Heading|제목)", style, re.I) else None
                trail.push(text, 0 if re.match(r"Title", style, re.I) else float(lv.group(1)) if lv else num_depth(text) + 4)
                continue
            para: Para = {"page": None, "text": text, "kind": "table" if _digit_ratio(text) > TABLE_DIGIT_RATIO else "prose"}
            if pending:
                para["heading"] = pending
                pending = None
            if trail.stack:
                para["heading_path"] = trail.path()
            paras.append(para)
        elif tag == "tbl":
            rows = _docx_rows(Table(child, d))
            if not rows:
                continue
            heading = pending or (paras[-1].get("heading") if paras else None)
            if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                paras.append(table_para(rows, heading=heading, unit=unit_of(last_text), heading_path=trail.path() or None))
            else:
                paras.append({"page": None, "text": table_text(rows), "kind": "prose", **({"heading": heading} if heading else {}), **({"heading_path": trail.path()} if trail.stack else {})})
            pending = None
    title = (d.core_properties.title or "").strip() or first_heading
    front = "\n".join(p["text"] for p in paras[:30])[:3000]
    return {"paras": paras, "meta": {"title": title, "author": (d.core_properties.author or "").strip(), "pageCount": None}, "frontText": front}


# ── XLSX ────────────────────────────────────────────────────────────────

def _xlsx_value(cell: Any) -> str:
    """보이는 값에 가깝게 — 퍼센트 서식은 ×100 + %, 날짜는 YYYY-MM-DD, 숫자 서식(0.0·#,##0)이 있으면 그 소수 자리·천 단위대로
    (7.0 이 '7' 로 바뀌면 자릿수가 0 이 되어 1.4 와 1.0 을 같은 값으로 본다), 서식이 없으면 정수는 소수점 없이(수식 칸은 저장된 결과값)."""
    v = cell.value
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (int, float)):
        fmt = str(cell.number_format or "").split(";")[0]
        if "%" in fmt:
            decimals = len(fmt.split(".")[1].split("%")[0]) if "." in fmt else 0
            return f"{v * 100:.{decimals}f}%"
        m = _NUM_FMT.search(fmt) if fmt and fmt != "General" else None
        if m:
            return f"{v:{',' if ',' in fmt else ''}.{len(m.group(1) or '')}f}"
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        if isinstance(v, float):
            return f"{v:.6g}"
        return str(v)
    return _clean_cell(v)


def _xlsx_blocks(matrix: List[List[str]]) -> List[List[List[str]]]:
    blocks: List[List[List[str]]] = []
    cur: List[List[str]] = []
    for row in matrix:
        if any(row):
            cur.append(row)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def extract_xlsx(path: str | Path) -> Dict[str, Any]:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), data_only=True)
    paras: List[Para] = []
    try:
        props = wb.properties
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                continue
            matrix = [[_xlsx_value(c) for c in row] for r, row in enumerate(ws.iter_rows()) if r < XLSX_MAX_ROWS]
            heading: str = ws.title
            unit: Optional[str] = None
            for block in _xlsx_blocks(matrix):
                rows = normalize_rows(block)
                # 위쪽 한 칸짜리 줄 = 표 제목·단위
                while len(rows) > 1 and sum(1 for c in rows[0] if c) == 1:
                    only = next(c for c in rows[0] if c)
                    if unit_of(only):
                        unit = unit_of(only)
                    elif only != ws.title:
                        heading = f"{ws.title} / {only}"
                    rows = normalize_rows(rows[1:])
                if not rows:
                    continue
                if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                    paras.append(table_para(rows, heading=heading, unit=unit, sheet=ws.title, heading_path=[h.strip() for h in heading.split(" / ")]))
                    continue
                text = " ".join(c for r in rows for c in r if c)
                if unit_of(text) and len(text) <= 30:
                    unit = unit_of(text)
                elif text:
                    paras.append({"page": None, "text": text, "kind": "prose", "heading": heading, "sheet": ws.title})
    finally:
        wb.close()
    front = "\n".join(p["text"] for p in paras[:20])[:3000]
    return {"paras": paras, "meta": {"title": (props.title or "").strip(), "author": (props.creator or "").strip(), "pageCount": None}, "frontText": front}


# ── TXT / MD ────────────────────────────────────────────────────────────

def _read_text(path: str | Path) -> str:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp949", "euc-kr", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_text(path: str | Path, markdown: bool) -> Dict[str, Any]:
    text = _read_text(path).replace("\r\n", "\n")
    paras: List[Para] = []
    pending: Optional[str] = None
    pending_unit: Optional[str] = None
    first_heading = ""
    trail = HeadingTrail()

    def add(para: Para) -> None:
        if trail.stack:
            para["heading_path"] = trail.path()
        paras.append(para)

    for block in re.split(r"\n\s*\n", text):
        lines = [l.rstrip() for l in block.strip().split("\n") if l.strip()]
        if not lines:
            continue
        # 마크다운 제목 줄은 블록 안 어디에 있어도 떼어 heading 메타로
        body: List[str] = []
        for l in lines:
            m = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", l) if markdown else None
            if m:
                if body:
                    add(_text_para(body, pending))
                    pending, body = None, []
                pending = m.group(2).strip()
                first_heading = first_heading or pending
                trail.push(pending, len(m.group(1)))
            else:
                body.append(l)
        if body:
            if len(body) == 1 and UNIT_RX.fullmatch(body[0].strip()):
                pending_unit = unit_of(body[0])  # 다음 표의 단위
                continue
            if not markdown and len(body) == 1 and _is_heading(body[0]):
                pending = body[0].strip()
                first_heading = first_heading or pending
                trail.push(pending, num_depth(pending))
                continue
            add(_text_para(body, pending, pending_unit))
            pending = None
            pending_unit = None
    front = "\n".join(p["text"] for p in paras[:30])[:3000]
    return {"paras": paras, "meta": {"title": first_heading, "author": "", "pageCount": None}, "frontText": front}


def _md_rows(lines: List[str]) -> List[List[str]]:
    rows = []
    for l in lines:
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue  # 구분 줄 |---|---|
        rows.append(cells)
    return normalize_rows(rows)


def _text_para(lines: List[str], heading: Optional[str], unit: Optional[str] = None) -> Para:
    table = sum(1 for l in lines if l.lstrip().startswith("|")) >= max(1, len(lines) // 2)
    if table:
        rows = _md_rows([l for l in lines if l.lstrip().startswith("|")])
        if len(rows) >= 2:
            return table_para(rows, heading=heading, unit=unit)
    text = "\n".join(lines) if table else re.sub(r"\s+", " ", " ".join(lines)).strip()
    para: Para = {"page": None, "text": text, "kind": "table" if table or _digit_ratio(text) > TABLE_DIGIT_RATIO else "prose"}
    if heading:
        para["heading"] = heading
    return para


# ── 진입점(형식 등록표) ─────────────────────────────────────────────────

EXTRACTORS: Dict[str, Callable[[str | Path], Dict[str, Any]]] = {
    "PDF": extract_pdf,
    "DOCX": extract_docx,
    "XLSX": extract_xlsx,
    "TXT": lambda p: extract_text(p, markdown=False),
    "MD": lambda p: extract_text(p, markdown=True),
}


def extract(path: str | Path, file_name: str) -> Dict[str, Any]:
    """파일 → {"paras", "meta": {title, author, pageCount}, "frontText", "fileType"}. 지원하지 않는 형식이면 ValueError."""
    ftype = file_type_of(file_name)
    fn = EXTRACTORS.get(ftype or "")
    if fn is None:
        raise ValueError(f"지원하지 않는 형식입니다: {Path(file_name).suffix or file_name} ({SUPPORTED_LABEL} 만)")
    out = fn(path)
    if not out["paras"]:
        raise ValueError("본문 텍스트를 찾지 못했습니다(스캔 PDF·이미지 문서는 아직 지원하지 않습니다).")
    out["fileType"] = ftype
    return out
