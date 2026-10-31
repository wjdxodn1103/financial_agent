"""근거 고정 — 산출물(문서 문장·본문 숫자·표 칸·차트 점·AI 답 출처·시장 값)이 기댄 원문 위치를 **저장할 때**
'주소 + 글자 + 당시 값'으로 얼려 둔다. 별도 화면이 아니라 모든 기능 밑에 깔린 층이다(2026-10-29 사용자 방향).

 - 주소: 문서 id(파일 내용 해시 — 파일이 바뀌면 다른 문서), 문단 id, 쪽·상자, 시트, 표 칸(행·열)
 - 글자: 그 문단의 원문 글자(앞부분), 표 칸이면 행 이름·열 이름·칸 원문
 - 당시 값: 칸 값(raw·값·단위·배율·통화), 외부 데이터면 접수번호·관측일·빈티지(ext)

청커가 바뀌어 문단 id 가 다른 문단을 가리키게 돼도 저장해 둔 글자로 다시 찾는다(`resolve`). 못 찾으면 'missing' — 얼려 둔 글자·값을 보인다.
문서마다 핀 색인 `DATA_DIR/anchors/<docId>.json`({문단[@행,열]: 앵커})에도 남긴다 — 화면의 모든 원문 열기(본문 인용·표 칸·숫자 출처·답 출처)가
같은 길(`/documents/{d}/locate`)로 와서, 앵커를 따로 실어 나르지 않아도 다시 찾기가 동작한다. 문서 폴더는 다시 만들 때 지워지므로 색인은 밖에 둔다.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app import config
from app.docs.chunk import CHUNKER_VERSION
from app.docs.citations import tokens
from app.docs.store import paragraphs
from app.ids import now_iso
from app.ledger.numbers import find_amounts, parse_number, same_value

Anchor = Dict[str, Any]
PIN_DIR = config.DATA_DIR / "anchors"
QUOTE_MAX = 400
_lock = threading.Lock()
_WS = re.compile(r"[\s   ​]+")
_CITE_LINK = re.compile(r"#cite=([0-9a-f]{16})~([A-Za-z0-9_.\-]+)")


def _norm(s: Any) -> str:
    return _WS.sub("", str(s or ""))


# ── 문단 읽기(같은 요청 안에서 여러 번 부르니 문서별로 잠깐 들고 있는다) ──

_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}


def _paras(doc_id: str) -> List[Dict[str, Any]]:
    from app.docs.store import doc_dir

    p = doc_dir(doc_id) / "chunks.json"
    try:
        mt = p.stat().st_mtime
    except OSError:
        return []
    hit = _cache.get(doc_id)
    if hit and hit[0] == mt:
        return hit[1]
    paras = paragraphs(doc_id)
    if len(_cache) > 64:
        _cache.clear()
    _cache[doc_id] = (mt, paras)
    return paras


def _para(doc_id: str, chunk_id: str) -> Optional[Dict[str, Any]]:
    return next((p for p in _paras(doc_id) if p.get("id") == chunk_id), None)


def _header(rows: List[List[Any]], c: int) -> str:
    return str(rows[0][c]) if rows and 0 <= c < len(rows[0]) else ""


# ── 핀 색인 ──

def _key(chunk: str, cell: Optional[Sequence[int]] = None) -> str:
    return f"{chunk}@{cell[0]},{cell[1]}" if cell else chunk


def _load(doc_id: str) -> Dict[str, Anchor]:
    try:
        d = json.loads((PIN_DIR / f"{doc_id}.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_many(doc_id: str, pins: Dict[str, Anchor]) -> None:
    """같은 열쇠의 핀은 처음 것을 둔다(같은 청커 판이고 글자가 같으면) — '언제부터 이 근거였나'가 남게."""
    if not pins:
        return
    with _lock:
        cur = _load(doc_id)
        changed = False
        for k, a in pins.items():
            old = cur.get(k)
            if old and old.get("chunker") == a.get("chunker") and _norm(old.get("quote"))[:200] == _norm(a.get("quote"))[:200]:
                continue
            cur[k] = a
            changed = True
        if changed:
            PIN_DIR.mkdir(parents=True, exist_ok=True)
            tmp = PIN_DIR / f"{doc_id}.json.tmp"
            tmp.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
            tmp.replace(PIN_DIR / f"{doc_id}.json")


# ── 얼리기 ──

def make(doc_id: str, chunk_id: str, *, cell: Optional[Sequence[int]] = None, quote: Optional[str] = None,
         figure: Optional[Dict[str, Any]] = None, ext: Optional[Dict[str, Any]] = None) -> Optional[Anchor]:
    """지금 원문으로 앵커 하나(색인에는 넣지 않는다). 문단이 없으면 None."""
    p = _para(doc_id, chunk_id)
    if p is None:
        return None
    text = str(p.get("text") or "")
    q = quote if quote and _norm(quote) and _norm(quote) in _norm(text) else text
    a: Anchor = {
        "docId": doc_id,
        "chunk": chunk_id,
        "page": p.get("page"),
        "boxes": (p.get("boxes") or [])[:8],
        "sheet": p.get("sheet"),
        "quote": q[:QUOTE_MAX],
        "chunker": CHUNKER_VERSION,
        "pinnedAt": now_iso(),
    }
    rows = p.get("rows") or []
    if cell and rows:
        r, c = int(cell[0]), int(cell[1])
        if 0 <= r < len(rows) and 0 <= c < len(rows[r]):
            raw = str(rows[r][c])
            a.update({"cell": [r, c], "rowLabel": str(rows[r][0]) if rows[r] else "", "colLabel": _header(rows, c), "quote": " | ".join(str(x) for x in rows[r])[:QUOTE_MAX]})
            val: Dict[str, Any] = {"raw": raw}
            if figure:
                val.update({k: figure.get(k) for k in ("value", "unit", "scale", "currency", "abs") if figure.get(k) is not None})
                a["figureId"] = figure.get("fid") or figure.get("id")
            else:
                pn = parse_number(raw)
                if pn:
                    val["value"] = pn[0]
            a["value"] = val
    if ext:
        a["ext"] = ext
    return a


def pin(doc_id: str, chunk_id: str, **kw: Any) -> Optional[Anchor]:
    a = make(doc_id, chunk_id, **kw)
    if a:
        _save_many(doc_id, {_key(chunk_id, a.get("cell")): a})
    return a


def pin_many(items: Iterable[Tuple[str, str, Optional[Sequence[int]], Optional[Dict[str, Any]]]]) -> Dict[str, Anchor]:
    """[(docId, chunk, cell, figure)] → {docId#chunk[@r,c]: 앵커}. 문서마다 색인을 한 번만 쓴다."""
    out: Dict[str, Anchor] = {}
    by_doc: Dict[str, Dict[str, Anchor]] = {}
    for doc_id, chunk_id, cell, fig in items:
        k = _key(chunk_id, cell)
        if f"{doc_id}#{k}" in out:
            continue
        a = make(doc_id, chunk_id, cell=cell, figure=fig)
        if a:
            out[f"{doc_id}#{k}"] = a
            by_doc.setdefault(doc_id, {})[k] = a
    for d, pins in by_doc.items():
        _save_many(d, pins)
    return out


def pin_text(text: str) -> Dict[str, Anchor]:
    """본문·답의 인용(토큰 [@doc#chunk] · 링크 #cite=doc~chunk) → 그 문단들의 앵커."""
    refs = list(dict.fromkeys([*tokens(text or ""), *_CITE_LINK.findall(text or "")]))
    return pin_many((d, c, None, None) for d, c in refs)


def pin_section(doc: Dict[str, Any], sec: Dict[str, Any]) -> None:
    """섹션 저장 때 — 인용 문단(sec.anchors)과 본문 숫자가 기댄 칸·문단(sec.numberAnchors, 열쇠 = '표기|n번째')."""
    content = str(sec.get("content") or "")
    sec["anchors"] = pin_text(content)
    nums: Dict[str, Anchor] = {}
    seen: Dict[str, int] = {}
    cell_items: List[Tuple[str, str, Optional[Sequence[int]], Optional[Dict[str, Any]]]] = []
    for sent in re.split(r"(?<=[.!?。])\s+|\n+", content):
        cites = tokens(sent)
        if not cites:
            continue
        plain = re.sub(r"\[@[^\]]+\]", "", sent)
        for amt in find_amounts(plain):
            n = seen.get(amt["raw"], 0)
            seen[amt["raw"]] = n + 1
            key = f"{amt['raw']}|{n}"
            for d, c in cites:
                p = _para(d, c)
                if not p:
                    continue
                rows = p.get("rows") or []
                hit_cell = None
                for ri, row in enumerate(rows[1:], start=1):
                    for ci, v in enumerate(row[1:], start=1):
                        pn = parse_number(v)
                        if pn and same_value(abs(amt["value"]), 10 ** -amt["decimals"], abs(pn[0]), 10 ** -pn[1]["decimals"]):
                            hit_cell = (ri, ci)
                            break
                    if hit_cell:
                        break
                if hit_cell:
                    a = make(d, c, cell=hit_cell)
                    if a:
                        nums[key] = a
                        cell_items.append((d, c, hit_cell, None))
                        break
                text = str(p.get("text") or "")
                m = next((b for b in find_amounts(text) if bool(b["percent"]) == bool(amt["percent"]) and same_value(amt["abs"], amt["step"], b["abs"], b["step"])), None)
                if m:
                    s0, s1 = max(0, m["start"] - 60), min(len(text), m["end"] + 60)
                    a = make(d, c, quote=text[s0:s1])
                    if a:
                        a["value"] = {"raw": m["raw"], "value": m["value"], "abs": m["abs"], "unit": m.get("unit"), "currency": m.get("currency")}
                        nums[key] = a
                        break
    if cell_items:
        pin_many(cell_items)
    sec["numberAnchors"] = nums


def pin_table_cells(data: Dict[str, Any]) -> None:
    """리서치 표(정리한 데이터)의 숫자·글 칸 → 색인(표 칸을 누르면 원문이 바뀌었어도 다시 찾게). 칸 자체에 'pinnedAt' 만 남긴다."""
    items: List[Tuple[str, str, Optional[Sequence[int]], Optional[Dict[str, Any]]]] = []
    for row in data.get("cells") or []:
        for cell in (row or {}).values():
            if not isinstance(cell, dict):
                continue
            if cell.get("docId") and cell.get("chunk"):
                items.append((cell["docId"], cell["chunk"], cell.get("cell"), None))
            for ct in cell.get("cites") or []:
                if ct.get("docId") and ct.get("chunk"):
                    items.append((ct["docId"], ct["chunk"], None, None))
    if items:
        pin_many(items)


# ── 다시 찾기 ──

def resolve(doc_id: str, chunk_id: Optional[str], cell: Optional[Sequence[int]] = None, anchor: Optional[Anchor] = None) -> Dict[str, Any]:
    """→ {chunk, cell, status: exact|relocated|missing|unpinned, pinned: 얼려 둔 앵커}. 앵커가 없으면 색인에서 꺼낸다."""
    if not chunk_id:
        return {"chunk": None, "cell": None, "status": "unpinned", "pinned": None}
    a = anchor or _load(doc_id).get(_key(chunk_id, cell))
    if not a:
        return {"chunk": chunk_id, "cell": list(cell) if cell else None, "status": "unpinned", "pinned": None}
    paras = _paras(doc_id)
    cur = next((p for p in paras if p.get("id") == chunk_id), None)
    pinned = {k: a.get(k) for k in ("quote", "value", "rowLabel", "colLabel", "page", "pinnedAt", "ext")}
    if a.get("cell"):
        want = _norm((a.get("value") or {}).get("raw"))
        r, c = a["cell"]
        rows = (cur or {}).get("rows") or []
        if 0 <= r < len(rows) and 0 <= c < len(rows[r]) and _norm(rows[r][c]) == want and _norm(rows[r][0]) == _norm(a.get("rowLabel")):
            return {"chunk": chunk_id, "cell": [r, c], "status": "exact", "pinned": pinned}
        for p in paras:
            prows = p.get("rows") or []
            for ri, row in enumerate(prows):
                if not row or _norm(row[0]) != _norm(a.get("rowLabel")):
                    continue
                for ci, v in enumerate(row):
                    if _norm(v) == want and (not a.get("colLabel") or _norm(_header(prows, ci)) == _norm(a.get("colLabel"))):
                        return {"chunk": p.get("id"), "cell": [ri, ci], "status": "relocated", "pinned": pinned}
        return {"chunk": chunk_id, "cell": list(cell) if cell else None, "status": "missing", "pinned": pinned}
    q = _norm(a.get("quote"))[:160]
    if cur is not None and (not q or q in _norm(cur.get("text"))):
        return {"chunk": chunk_id, "cell": list(cell) if cell else None, "status": "exact", "pinned": pinned}
    if q:
        for p in paras:
            if q in _norm(p.get("text")):
                return {"chunk": p.get("id"), "cell": None, "status": "relocated", "pinned": pinned}
        # 앞 160자 그대로는 없지만 앞 60자가 든 문단(줄 바꿈·잇기 규칙만 바뀐 경우)
        q60 = q[:60]
        for p in paras:
            if q60 and q60 in _norm(p.get("text")):
                return {"chunk": p.get("id"), "cell": None, "status": "relocated", "pinned": pinned}
    return {"chunk": chunk_id, "cell": list(cell) if cell else None, "status": "missing", "pinned": pinned}
