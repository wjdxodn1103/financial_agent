"""문단 → 청크. OP 청커 v7 의 규칙 그대로: **문단 하나 = 청크 하나**(id p<n>), 너무 긴 문단만 문장(표는 줄) 경계에서
조각으로 나누고 조각은 같은 id 에 part 1..parts. 임베딩·vectors.bin 은 조각 순서, 검색·근거 보기는 문단 통째(store.merge_fragments).
칸 구조 표(rows)는 조각을 만들지 않는다 — 길면 머리글 행을 되풀이한 표 여러 개(id p<n>, p<n>r1 …)로 나눈다(칸 좌표가 청크 안에서 닫히게).

청커 v4: 문단의 boxes(쪽별 줄 상자)·headingPath(제목 경로)·years·disclaimer(구조 태그, tags.py)를 청크에 둔다(조각은 문단 것을 그대로).
칸 구조 표는 cells(칸 상자)를 행 묶음대로 나눠 갖고, boxes 는 머리글 행과 데이터 행 묶음의 사각형이다.

토큰 수는 어림(한글·한자 글자당 0.8, 그 밖 0.23 — OP 가 Gemma 토크나이저로 실측한 계수)으로 잰다. 임베딩 API 가
입력 끝을 자르므로(truncate=END) 정확할 필요는 없고, 근거 문단이 너무 길어지지 않게 하는 것이 목적이다.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

import regex

from app.docs.tags import is_disclaimer, years_of

Chunk = Dict[str, Any]

CHUNKER_VERSION = 4  # 2: 칸 구조 표(rows·unit·sheet) · 3: PDF 표 제목(단위 문구 뗀 caption)·표 위아래 문단 안 잇기 · 4: 줄·칸 상자, 제목 경로, 연도·면책 태그
MAX_TOKENS = 480
FRAGMENT_TOKENS = 400
TABLE_ROWS_MAX = 40  # 칸 구조 표 한 청크의 데이터 행 상한
_CJK = regex.compile(r"[\p{Hangul}\p{Han}\p{Hiragana}\p{Katakana}]")
_SENT_SPLIT = regex.compile(r"(?<=[.!?。]|다\.)\s+")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    return int(cjk * 0.805 + (len(text) - cjk) * 0.227)


def _units(text: str, table: bool) -> List[str]:
    parts = [l for l in text.split("\n") if l.strip()] if table else [s for s in (x.strip() for x in _SENT_SPLIT.split(text)) if s]
    out: List[str] = []
    for s in parts:
        # 한 문장(줄)이 상한보다 길면 글자 위치로 자른다
        while count_tokens(s) > MAX_TOKENS:
            cut = max(1, int(len(s) * MAX_TOKENS / count_tokens(s) * 0.9))
            sp = s.rfind(" ", cut // 2, cut)
            cut = sp if sp > 0 else cut
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            out.append(s)
    return out


def _group(units: List[str], limit: int) -> List[List[str]]:
    groups: List[List[str]] = []
    cur: List[str] = []
    tok = 0
    for u in units:
        t = count_tokens(u)
        if cur and tok + t > limit:
            groups.append(cur)
            cur, tok = [], 0
        cur.append(u)
        tok += t
    if cur:
        groups.append(cur)
    return groups


def _row_groups(rows: List[List[str]]) -> List[List[int]]:
    """머리글 행 + 데이터 행 묶음들(토큰·행 상한) — 행 번호 목록으로(칸 상자를 같은 행으로 나누려고). 0 = 머리글."""
    head_tok = count_tokens(" | ".join(rows[0]))
    groups: List[List[int]] = []
    cur: List[int] = []
    tok = head_tok
    for i in range(1, len(rows)):
        t = count_tokens(" | ".join(rows[i]))
        if cur and (tok + t > FRAGMENT_TOKENS or len(cur) >= TABLE_ROWS_MAX):
            groups.append([0, *cur])
            cur, tok = [], head_tok
        cur.append(i)
        tok += t
    if cur or not groups:
        groups.append([0, *cur])
    return groups


def _union(boxes: List[Any]) -> Any:
    bs = [b for b in boxes if b]
    if not bs:
        return None
    return [min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs)]


def _table_boxes(page: Any, cells: List[List[Any]]) -> List[List[Any]]:
    """표 청크의 상자 — 머리글 행 사각형 + 데이터 행들 사각형(칸 상자에서)."""
    out = []
    for part in (cells[:1], cells[1:]):
        u = _union([b for row in part for b in row])
        if u and page:
            out.append([page, *u])
    return out


def _rows_text(rows: List[List[str]]) -> str:
    return "\n".join(" | ".join(r).strip(" |") for r in rows if any(r))


def chunk_paragraphs(paras: List[Dict[str, Any]]) -> List[Chunk]:
    chunks: List[Chunk] = []
    for n, p in enumerate(paras):
        base: Chunk = {"id": f"p{n}", "part": 1, "parts": 1, "text": p["text"], "page": p.get("page"), "kind": p.get("kind", "prose")}
        for k in ("heading", "unit", "sheet", "boxes"):
            if p.get(k):
                base[k] = p[k]
        if p.get("heading_path"):
            base["headingPath"] = p["heading_path"]
        rows = p.get("rows")
        if rows:
            cells = p.get("cells")
            for k, idx in enumerate(_row_groups(rows)):
                g = [rows[i] for i in idx]
                c: Chunk = {**base, "id": base["id"] if k == 0 else f"{base['id']}r{k}", "rows": g, "text": _rows_text(g)}
                if cells:
                    c["cells"] = [cells[i] for i in idx]
                    c["boxes"] = _table_boxes(p.get("page"), c["cells"])
                _tag(c, c["text"])
                chunks.append(c)
            continue
        _tag(base, p["text"])
        if count_tokens(p["text"]) <= MAX_TOKENS:
            chunks.append(base)
            continue
        table = base["kind"] == "table"
        groups = _group(_units(p["text"], table), FRAGMENT_TOKENS)
        for k, g in enumerate(groups, 1):
            chunks.append({**base, "part": k, "parts": len(groups), "text": ("\n" if table else " ").join(g)})
    return chunks


def _tag(c: Chunk, text: str) -> None:
    """구조 태그 — 언급 연도(years), 면책·고지(disclaimer). 비었으면 두지 않는다."""
    ys = years_of(text, c.get("headingPath"))
    if ys:
        c["years"] = ys
    if is_disclaimer(text, c.get("headingPath")):
        c["disclaimer"] = True


def preview(text: str, limit: int = 160) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"
