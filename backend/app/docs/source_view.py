"""원문 확인 — 가공한 값(원장 칸·표 칸·인용 문단)이 **원본 파일**의 어디인지, 원본을 다시 읽어 그대로 보여 준다(가공한 글이 아니라).

PDF  : 그 쪽을 그림으로(page_png) + 강조 상자(쪽 크기 비율 좌표). 청커 v4 청크는 추출 때 저장한 상자를 그대로 쓴다 —
       문단 = 쪽별 줄 상자(쪽을 넘으면 marks 에 쪽마다), 표 칸 = 그 칸 상자. 옛 청크(상자 없음)만 글을 다시 맞춰 찾는다:
       칸 = 원 행 이름과 같은 줄에 있는 그 값 글자, 문단 = 글이 가장 많이 겹치는 글 덩어리(들).
엑셀 : 원본 시트를 다시 읽어(보이는 값 — 추출과 같은 서식) 그 칸 주변을 격자로 + A1 주소. 칸 = 행 이름이 있는 줄에서 값이 같은 칸.
워드 : 원본 문단·표를 다시 읽어 그 문단(표면 그 칸) 주변.
글   : 원본 줄 주변(TXT·MD).
연결 스냅샷(DART·EDGAR·ECOS·FRED·주가 — API 로 받은 JSON): 원본 JSON 줄은 사람이 못 읽어서, 그 시트 표 + 그 칸(문장으로 열면 문장 속
       금액과 같은 칸) + 그 값이 나온 API 응답 항목(DART: 계정명·당기금액·접수번호) + 원문 링크(DART 공시 뷰어). 글 문단은 앞뒤 문단과 함께.
찾지 못하면 found=false — 화면은 그 쪽(시트·문단 주변)만 보이고 '찾지 못했습니다' 한 줄.
extracted = 가공한 값(원장 수치면 값·지표·기간, 문단이면 앞부분) — 화면이 원본 옆에 한 줄로 둔다.
origin = 연결 스냅샷의 출처(연결 이름·조회 시각·원문 주소) — 화면 위쪽 한 줄과 [DART 공시 원문] 버튼.
"""
from __future__ import annotations

import json
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


# ── 연결 스냅샷(API 로 받은 JSON) ─────────────────────────────────────────

_ORIGIN = {"dart": "DART OpenAPI(금융감독원)", "edgar": "SEC EDGAR", "ecos": "한국은행 ECOS", "fred": "FRED(St. Louis Fed)", "prices": "주가 일봉",
           "market": "시장·거시 데이터", "rss": "보도자료 RSS", "calendar": "경제 일정(기관 공식 발표 일정표)"}
# DART 재무제표 응답 항목 이름 — 화면은 한글 이름 옆에 원래 키를 작게
_DART_KEYS = {
    "rcept_no": "접수번호", "reprt_code": "보고서 코드", "bsns_year": "사업연도", "corp_code": "고유번호", "sj_div": "재무제표 구분", "sj_nm": "재무제표",
    "account_id": "계정 ID", "account_nm": "계정명", "account_detail": "계정 상세", "thstrm_nm": "당기", "thstrm_amount": "당기 금액",
    "thstrm_add_amount": "당기 누적 금액", "frmtrm_nm": "전기", "frmtrm_amount": "전기 금액", "frmtrm_q_nm": "전기 같은 분기", "frmtrm_q_amount": "전기 같은 분기 금액",
    "frmtrm_add_amount": "전기 누적 금액", "bfefrmtrm_nm": "전전기", "bfefrmtrm_amount": "전전기 금액", "ord": "순서", "currency": "통화",
}


def origin(meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """연결 스냅샷의 출처 — 연결 이름·스냅샷 제목·조회 시각·원문 주소(DART 는 공시 뷰어). 업로드 자료면 None."""
    sn = meta.get("snapshot") or {}
    if not sn:
        return None
    url = str(sn.get("url") or "")
    label = "DART 공시 원문" if "dsaf001" in url else "DART 공시 목록" if "dart.fss.or.kr" in url else "원문 페이지"
    return {"name": _ORIGIN.get(str(sn.get("connector") or ""), str(sn.get("connector") or "데이터 연결")), "title": str(sn.get("title") or ""),
            "fetchedAt": str(sn.get("fetchedAt") or ""), "url": url if url.startswith(("https://", "http://")) else "", "urlLabel": label}


def match_cells(chunk: Optional[Dict[str, Any]], quote: Optional[str]) -> List[Dict[str, Any]]:
    """인용 문장의 금액·비율이 표의 어느 칸인지 → [{r, c, as}](r = 머리글 포함 행 번호, as = 문장 속 표기). LLM 0회.
    단위를 원 단위로 맞추고(표 단위 '원' · 문장 '44.76억원' · '7,198,980천원') 반올림 차이까지 같은 값으로 본다. 부호는 보지 않는다
    ('영업손실 48.01억원' = -4,801,006,624). 행 이름에 %·률·율이 있으면 그 행 칸은 비율(문장의 % 와만 맞춘다).
    같은 값 칸이 여럿이면(당기순이익 = 법인세비용차감전순이익) 금액 바로 앞 글('당기순손실은')과 행 이름이 가장 많이 겹치는 칸만. 순서는 문장 순서."""
    from app.ledger.numbers import find_amounts, parse_number, parse_unit, same_value, step_of

    rows = (chunk or {}).get("rows") or []
    amounts = find_amounts(quote or "")
    if not rows or not amounts:
        return []
    scale = parse_unit(str((chunk or {}).get("unit") or "")).scale or 1.0
    cands: Dict[int, List[Tuple[int, int]]] = {}
    for r, row in enumerate(rows[1:], start=1):
        pct_row = bool(row) and bool(re.search(r"%|률|율", str(row[0])))
        for c, v in enumerate(row[1:], start=1):
            got = parse_number(v)
            if got is None:
                continue
            val, info = got
            pct = bool(info["percent"]) or pct_row
            cell_abs, cell_step = (val, step_of(info["decimals"], 1.0)) if pct else (val * scale, step_of(info["decimals"], scale))
            for i, a in enumerate(amounts):
                if bool(a["percent"]) == pct and same_value(abs(a["abs"]), a["step"], abs(cell_abs), cell_step):
                    cands.setdefault(i, []).append((r, c))

    def bigrams(t: str) -> set:
        t = re.sub(r"[\s\W\d]+", "", t)
        return {t[k:k + 2] for k in range(len(t) - 1)}

    out: List[Dict[str, Any]] = []
    for i in sorted(cands):
        cells = cands[i]
        if len(cells) > 1:
            near = bigrams((quote or "")[max(0, amounts[i]["start"] - 16):amounts[i]["start"]])
            scored = [(len(near & bigrams(str(rows[r][0]))), r, c) for r, c in cells]
            top = max(s for s, _r, _c in scored)
            if top > 0:
                cells = [(r, c) for s, r, c in scored if s == top]
        out += [{"r": r, "c": c, "as": amounts[i]["raw"]} for r, c in cells if not any(o["r"] == r and o["c"] == c for o in out)]
    return out[:12]


def _raw_record(raw: Any, label: str, value: str, sheet: str) -> Optional[Dict[str, Any]]:
    """API 응답에서 그 칸 값이 나온 항목 — 값(숫자만 견줌)과 행 이름이 같은 객체. 같은 항목이 여러 표에 있으면 시트 이름이 같은 것."""
    digits = re.sub(r"\D", "", str(value or ""))
    lab = _norm(label)
    if not digits:
        return None
    hits: List[Dict[str, Any]] = []
    stack, seen = [raw], 0
    while stack and seen < 50000 and len(hits) < 8:
        x = stack.pop()
        seen += 1
        if isinstance(x, dict):
            vals = [str(v) for v in x.values() if isinstance(v, (str, int, float))]
            if any(re.sub(r"\D", "", s) == digits for s in vals) and (not lab or any(_norm(s) == lab for s in vals)):
                hits.append(x)
            stack.extend(v for v in x.values() if isinstance(v, (dict, list)))
        elif isinstance(x, list):
            stack.extend(reversed(x))
    return next((h for h in hits if sheet and any(str(v) == sheet for v in h.values())), hits[0] if hits else None)


def _snapshot(doc_id: str, path: Path, chunk: Optional[Dict[str, Any]], cell: Optional[Tuple[int, int]], quote: Optional[str]) -> Dict[str, Any]:
    rows = (chunk or {}).get("rows") or []
    if chunk and rows:
        hits = [tuple(cell)] if cell else [(h["r"], h["c"]) for h in match_cells(chunk, quote)]
        hits = [(r, c) for r, c in hits if 1 <= r < len(rows) and 0 <= c < len(rows[r])]
        record = None
        if hits:
            r, c = hits[0]
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = None
            rec = _raw_record(raw, str(rows[r][0]), str(rows[r][c]), str(chunk.get("sheet") or "")) if raw is not None else None
            if rec:
                digits = re.sub(r"\D", "", str(rows[r][c]))
                record = [{"key": k, "name": _DART_KEYS.get(k, ""), "value": str(v), "on": bool(digits) and re.sub(r"\D", "", str(v)) == digits}
                          for k, v in rec.items() if isinstance(v, (str, int, float))][:24]
        first = hits[0][0] if hits else None
        where = " · ".join(x for x in (f"시트 {chunk['sheet']}" if chunk.get("sheet") else "", str(rows[first][0]) if first else "") if x)
        r0, c0 = hits[0] if hits else (0, 0)
        return {"kind": "snapshot", "table": {"title": str(chunk.get("heading") or chunk.get("sheet") or ""), "unit": str(chunk.get("unit") or ""), "header": rows[0], "rows": rows[1:]},
                "hl": [[r - 1, c] for r, c in hits], "record": record, "recordOf": f"{rows[r0][0]} · {rows[0][c0]}" if record else "", "found": True, "where": where}
    # 글 문단 — 원본 JSON 줄 대신 앞뒤 문단과 함께 읽을 수 있는 글로(원문은 원문 링크)
    paras = paragraphs(doc_id)
    i = next((k for k, p in enumerate(paras) if chunk and str(p.get("id")) == str(chunk.get("id"))), None)
    lo, hi = (max(0, i - 3), min(len(paras), i + 4)) if i is not None else (0, min(len(paras), 6))
    blocks = [{"type": "table", "rows": p["rows"]} if p.get("rows") else {"type": "p", "text": re.sub(r"\s+", " ", str(p.get("text") or "")).strip()} for p in paras[lo:hi]]
    return {"kind": "snapshot", "blocks": blocks, "at": (i - lo) if i is not None else None, "found": i is not None, "where": str((chunk or {}).get("heading") or "")}


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


def locate(doc_id: str, chunk_id: Optional[str] = None, cell: Optional[Tuple[int, int]] = None, quote: Optional[str] = None) -> Dict[str, Any]:
    """quote = 그 칸을 인용한 문장(근거 카드에서 열 때) — 연결 스냅샷 표에서 문장 속 금액과 같은 칸을 칠한다."""
    meta, path = _source(doc_id)
    chunk = _chunk(doc_id, chunk_id) if chunk_id else None
    ext = path.suffix.lower()
    snapshot = bool(meta.get("snapshot")) and ext == ".json"
    if snapshot:
        out = _snapshot(doc_id, path, chunk, cell, quote)
    elif ext == ".pdf":
        out = _pdf(path, chunk, cell)
    elif ext in (".xlsx", ".xlsm"):
        out = _xlsx(path, chunk, cell)
    elif ext == ".docx":
        out = _docx(path, chunk, cell)
    else:
        out = _text(path, chunk, cell)
    extracted = _extracted(doc_id, chunk, cell) if chunk else None
    if snapshot and chunk and chunk.get("rows") and not cell:
        # 표 문단을 문장으로 열었으면 위 한 줄은 표 글 덩어리 대신 그 문장(칠한 칸이 문장 속 어느 금액인지 견준다)
        extracted = {"text": re.sub(r"\s+", " ", quote)[:300], "quote": True} if quote else None
    return {"docId": doc_id, "label": doc_label(meta, doc_id), "fileName": meta.get("fileName") or path.name, "extracted": extracted, "origin": origin(meta), **out}


__all__ = ["locate", "match_cells", "origin", "page_png"]
