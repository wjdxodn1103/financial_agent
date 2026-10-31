"""글자층 PDF 레이아웃 분석 — 쪽마다 글 줄·채움 칸·선·그림 영역을 읽어 역할을 붙인다(LLM 0회). 양식 2.0 틀(blueprint.py)의 재료.

역할(쪽 요소 kind)
  title · subtitle   표지·요약 쪽의 큰 글자(본문의 1.5배 이상)
  band               장 띠 — 채움 칸 위 흰 글자, 쪽에서 가장 큰 흰 글자(쪽당 하나)
  headline           소제목·요약 주장 — 강조색 굵게, 본문보다 조금 큼, 왼쪽 정렬
  minor              본문 칸의 굵은 본문 크기 줄('1. 베어링' 같은 작은 머리)
  keyline            핵심 문장 묶음 — 본문 칸보다 왼쪽의 굵은 본문 크기 줄(옆 문단과 y 로 짝)
  para               본문 문단
  table · figure     표(작은 글자 격자 → find_tables 로 칸) · 그림(이미지·벡터) — 바로 위 굵은 한 줄 = 제목, 아래 '자료:' 줄 = 출처
  note               '주:' 같은 작은 글자 줄(표·그림에 붙지 않은 것)
머리글·바닥글 = 여러 쪽 위·아래에서 되풀이되는 줄(쪽 번호 포함) — 요소에서 빼고 page.header/footer 로.
규칙은 상대값: 본문 크기 = 글자 수가 가장 많은 크기, 강조색 = 색 있는 굵은 소제목 크기 글자의 최빈색, 크기는 ±0.3 으로 묶는다.
글자층이 없거나(그림 PDF) 깨졌으면 has_text_layer() 가 거짓 → analyze.py 의 VL 경로를 쓴다.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PAGE_MAX = 40
_HANGUL_OR_WORD = re.compile(r"[가-힣A-Za-z0-9]")
_NUMERIC_CELL = re.compile(r"^[\s(]*[-−△+]?[\d,]+(?:\.\d+)?\s*[%)]?\s*(?:원|억원|배|p|만주|백만주|주|%)?\s*$|^(?:N/?A|적지|적전|흑전|흑지|-|–|n\.?m\.?)$", re.I)
_CAPTION = re.compile(r"^\s*[\[<(]?\s*(그림|표|도표|차트|Figure|Fig\.|Exhibit|Table|Chart)\s*[\dIVX]+[\]>)]?\s*[.:：]?", re.I)
_SOURCE = re.compile(r"^\s*(자료|출처|Source|Sources)\s*[:：]", re.I)
_NOTE = re.compile(r"^\s*(주|Note|Notes)\s*[:：)\d]", re.I)
_UNIT_NOTE = re.compile(r"\(\s*(?:단위|Unit)\s*[:：]\s*([^)]+)\)", re.I)
_PERIODISH = re.compile(r"^(?:FY)?\s*'?(?:19|20)?\d{2}(?:\s*[./-]?\s*(?:[1-4]Q|Q[1-4]|[1-4]분기|[12]H|H[12]))?\s*[AEFP]?$|^\d개월$|^\d{1,2}M$", re.I)
_PERIOD_HEAD = re.compile(r"^(?:FY)?\s*(?:19|20)\d{2}(?:\s*[./-]?\s*(?:[1-4]Q|Q[1-4]|[1-4]분기|[12]H|H[12]|상반기|하반기))?\s*\(?[AEFP]?\)?$|^[1-4]Q\s*'?\d{2}[AEFP]?$|^'\d{2}[AEFP]?$|^\d{1,2}\s*(?:개월|M|Y|년)$", re.I)
_DISCLAIMER = re.compile(r"Compliance|면책|고지|투자의견|시장경보|Disclaimer|Important\s+disclosure", re.I)


# ── 읽기 ────────────────────────────────────────────────────────────────────

def _hex(color: int) -> str:
    return f"#{color:06X}"


def _rgb_hex(rgb: Optional[Tuple[float, ...]]) -> Optional[str]:
    if not rgb or len(rgb) < 3:
        return None
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb[:3])


def _is_grey(h: str, tol: int = 18) -> bool:
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return max(r, g, b) - min(r, g, b) <= tol


def _near(a: str, b: str, tol: int = 24) -> bool:
    return all(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) <= tol for i in (1, 3, 5))


def _bold(span: Dict[str, Any]) -> bool:
    f = span.get("font") or ""
    return bool(span.get("flags", 0) & 16) or any(k in f for k in ("Bold", "ExtraBo", "Black", "Heavy", "SemiBo"))


def _read_page(page: Any, pno: int) -> Dict[str, Any]:
    lines: List[Dict[str, Any]] = []
    images: List[List[float]] = []
    for b in page.get_text("dict")["blocks"]:
        if b.get("type") == 1:
            images.append([round(v, 1) for v in b["bbox"]])
            continue
        for ln in b.get("lines") or []:
            spans = [s for s in ln.get("spans") or [] if (s.get("text") or "").strip()]
            if not spans:
                continue
            # 줄의 글꼴 = 글자 수가 가장 많은 조각
            main = max(spans, key=lambda s: len(s["text"].strip()))
            text = re.sub(r"\s+", " ", "".join(s["text"] for s in spans)).strip()
            lines.append({"page": pno, "bbox": [round(v, 1) for v in ln["bbox"]], "text": text, "size": round(main["size"] * 2) / 2,
                          "rawSize": round(main["size"], 2), "bold": _bold(main), "color": _hex(main.get("color", 0)), "font": main.get("font") or ""})
    fills: List[Dict[str, Any]] = []
    rules: List[Dict[str, Any]] = []
    marks: List[List[float]] = []  # 차트 조각 — 색 있는 채움(막대·조각)·두께 있는 선(꺾은선)
    paths: List[Dict[str, Any]] = []  # 꺾은선·띠선(점 여러 개인 선) — 차트 모양 읽기
    bars: List[Dict[str, Any]] = []
    keys: List[Dict[str, Any]] = []
    for dr in page.get_drawings():
        r = dr.get("rect")
        if r is None:
            continue
        bbox = [round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)]
        fill = _rgb_hex(dr.get("fill")) if dr.get("fill") is not None else None
        stroke = _rgb_hex(dr.get("color")) if dr.get("color") is not None else None
        if stroke and not fill and r.height <= 1.6 and 6 <= r.width <= 30 and len(dr.get("items") or []) == 1:
            keys.append({"bbox": bbox, "color": stroke})  # 꺾은선 범례 견본(짧은 가로 선 — 요약 쪽 주가 차트의 '에스비비테크·KOSDAQ')
        if r.height <= 1.6 and r.width >= 20:
            rules.append({"bbox": bbox, "color": stroke or fill or "#000000", "width": round(dr.get("width") or r.height or 0.5, 2)})
            continue
        if fill and r.width * r.height >= 30:
            fills.append({"bbox": bbox, "color": fill})
        # 막대 색 = 보이는 색 — 같은 색에 투명도만 달리 쓴 누적 막대('글로벌 로봇 시장 전망' 1.0·0.5·0.2)는 흰 바탕과 섞어야 계열이 갈린다
        op = dr.get("fill_opacity")
        bar_fill = _rgb_hex(tuple(c * op + (1 - op) for c in dr["fill"])) if fill and op is not None and op < 0.99 else fill
        if bar_fill and bar_fill != "#FFFFFF" and r.width >= 1.5:
            # 차트 모양 읽기 — 막대(0 근처 값의 납작한 막대 포함)·범례 견본. 막대 여러 개를 채움 하나(선 조각 여럿)로 그린 차트가 있어 조각 사각형으로 나눈다(KIRS 연간 매출액)
            # 사각형 여럿('re' 4개 — 경쟁사 실적 차트의 회색 막대)도 나눈다. 선 4개로 닫은 사각형 하나는 이어진 조각이라 그대로 하나
            for sb in (_subrects(dr["items"]) if len(dr.get("items") or []) > 1 else []) or [bbox]:
                if sb[2] - sb[0] >= 1.5:
                    bars.append({"bbox": sb, "color": bar_fill})
        if stroke and not fill and len(dr.get("items") or []) >= 2 and (r.width > 6 or r.height > 6):
            paths.append({"bbox": bbox, "color": stroke, "width": round(dr.get("width") or 0.5, 2), "points": len(dr["items"]) + 1})
        if (fill and not _is_grey(fill) and r.width * r.height >= 12) or (stroke and not _is_grey(stroke) and r.width > 1.6 and r.height > 1.6):
            marks.append(bbox)
    lines.sort(key=lambda x: (round(x["bbox"][1]), x["bbox"][0]))
    return {"page": pno, "width": round(page.rect.width, 1), "height": round(page.rect.height, 1), "lines": lines, "images": images, "fills": fills, "rules": rules, "marks": marks,
            "paths": paths, "bars": bars, "keys": keys}


def read_pdf(path: str | Path, page_max: int = PAGE_MAX) -> List[Dict[str, Any]]:
    import fitz  # PyMuPDF

    doc = fitz.open(str(path))
    try:
        return [_read_page(doc[i], i + 1) for i in range(min(len(doc), page_max))]
    finally:
        doc.close()


def has_text_layer(pages: List[Dict[str, Any]]) -> bool:
    """글자층이 쓸 만한가 — 글자가 있는 쪽이 절반 이상이고, 글자 가운데 한글·영문·숫자가 60% 이상(깨진 글꼴 거름)."""
    if not pages:
        return False
    texty = 0
    good = total = 0
    for p in pages:
        chars = "".join(ln["text"] for ln in p["lines"]).replace(" ", "")
        if len(chars) >= 120:
            texty += 1
        total += len(chars)
        good += len(_HANGUL_OR_WORD.findall(chars))
    return texty * 2 >= len(pages) and total > 0 and good / total >= 0.6


# ── 스타일 기준 ───────────────────────────────────────────────────────────────

def _theme_sizes(pages: List[Dict[str, Any]]) -> Dict[str, float]:
    by_size: Counter = Counter()
    for p in pages:
        for ln in p["lines"]:
            by_size[ln["size"]] += len(ln["text"])
    body = by_size.most_common(1)[0][0] if by_size else 10.0
    return {"body": body}


def _repeats(pages: List[Dict[str, Any]]) -> Tuple[set, Dict[str, Any]]:
    """머리글·바닥글 — 위 11%·아래 9% 줄 가운데 숫자를 지운 글이 여러 쪽(1/3 이상)에서 되풀이되는 것. 쪽 번호(숫자만)도."""
    seen: Counter = Counter()
    where: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    for p in pages:
        h = p["height"]
        for i, ln in enumerate(p["lines"]):
            y0, y1 = ln["bbox"][1], ln["bbox"][3]
            if y1 > h * 0.11 and y0 < h * 0.91:
                continue
            key = ("top:" if y1 <= h * 0.11 else "bottom:") + re.sub(r"\d+", "#", ln["text"])
            seen[key] += 1
            where.setdefault(key, []).append((p["page"], ln))
    need = max(2, len(pages) // 3)
    ids: set = set()
    info: Dict[str, Any] = {"header": [], "footer": []}
    for key, n in seen.items():
        is_num = re.fullmatch(r"(top:|bottom:)#?", key) is not None
        if n >= need or is_num:
            for pg, ln in where[key]:
                ids.add((pg, id(ln)))
            if n >= need:
                ln0 = where[key][0][1]
                side = "header" if key.startswith("top:") else "footer"
                info[side].append({"text": ln0["text"], "pattern": key.split(":", 1)[1], "x": ln0["bbox"][0], "size": ln0["size"], "color": ln0["color"], "bold": ln0["bold"],
                                   "align": "right" if ln0["bbox"][0] > 0.6 * pages[0]["width"] else "left"})
    return ids, info


# ── 표·그림 영역 ──────────────────────────────────────────────────────────────

def _rows(lines: List[Dict[str, Any]], tol: float = 2.5) -> List[List[Dict[str, Any]]]:
    """같은 y(가운데)에 놓인 줄끼리 한 행으로."""
    out: List[List[Dict[str, Any]]] = []
    for ln in sorted(lines, key=lambda x: (x["bbox"][1] + x["bbox"][3]) / 2):
        cy = (ln["bbox"][1] + ln["bbox"][3]) / 2
        if out and abs(((out[-1][0]["bbox"][1] + out[-1][0]["bbox"][3]) / 2) - cy) <= tol:
            out[-1].append(ln)
        else:
            out.append([ln])
    for r in out:
        r.sort(key=lambda x: x["bbox"][0])
    return out


def _union(boxes: List[List[float]]) -> List[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _inside(b: List[float], box: List[float], pad: float = 1.0) -> bool:
    return b[0] >= box[0] - pad and b[1] >= box[1] - pad and b[2] <= box[2] + pad and b[3] <= box[3] + pad


def _overlap_x(a: List[float], b: List[float]) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0]))


def _grid_rows(rows: List[List[Dict[str, Any]]], body: float) -> List[Tuple[int, str]]:
    """행마다 격자 판정 — 'grid'(작은 글자 칸 2개 이상, 값 칸이 숫자·N/A·기간), 'label'(작은 글자 한 칸), ''(아님)."""
    out = []
    for r in rows:
        small = [ln for ln in r if ln["size"] <= body * 0.93]
        if not small or len(small) < len(r):
            out.append(""); continue
        if len(small) >= 2:
            tail = [ln["text"] for ln in small[1:]]
            numeric = sum(1 for t in tail if _NUMERIC_CELL.match(t) or _PERIODISH.match(t.replace(" ", "")))
            out.append("grid" if numeric >= max(1, len(tail) // 2) else "label")
        else:
            out.append("label")
    return out


def _gutter(lines: List[Dict[str, Any]], x_lo: float, x_hi: float, body: float) -> Optional[float]:
    """나란히 놓인 두 표 사이 빈 세로 띠 — 작은 글자 줄이 가로지르지 않는 x 가 5pt 이상 이어지고,
    그 오른쪽에 글(숫자가 아닌) 행 이름 줄이 5개 이상 붙어 있으면(오른쪽에도 표 머리 칸이 있다) 그 가운데. 한 표의 열 사이 빈틈과 가른다."""
    small = [ln for ln in lines if ln["size"] <= body * 0.93]
    if len(small) < 20:
        return None
    best: Optional[float] = None
    run = 0
    for x in range(int(x_lo), int(x_hi)):
        crossing = any(ln["bbox"][0] < x < ln["bbox"][2] for ln in small)
        run = 0 if crossing else run + 1
        if run >= 5:
            g = x - 2
            right_labels = sum(1 for ln in small if g < ln["bbox"][0] <= g + 18 and not _NUMERIC_CELL.match(ln["text"]) and not _PERIODISH.match(ln["text"].replace(" ", "")))
            left_labels = sum(1 for ln in small if ln["bbox"][0] < g - 100 and not _NUMERIC_CELL.match(ln["text"]))
            if right_labels >= 5 and left_labels >= 5 and (best is None or abs(g - (x_lo + x_hi) / 2) < abs(best - (x_lo + x_hi) / 2)):
                best = float(g)
    return best


def _tables_and_figures(page: Dict[str, Any], lines: List[Dict[str, Any]], body: float, columns: List[Tuple[float, float]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], set]:
    """작은 글자 격자 행이 이어진 묶음 = 표 후보. 막대·선 같은 그림 조각이 많으면 그림(차트). 위의 굵은 한 줄 = 제목, 아래 '자료:' = 출처.
    본문 칸 안에 표 두 개가 나란히 있으면(부록 재무표) 빈 세로 띠로 단을 가른다."""
    used: set = set()
    tables: List[Dict[str, Any]] = []
    figures: List[Dict[str, Any]] = []
    split: List[Tuple[float, float]] = []
    for cx0, cx1 in columns:
        g = _gutter([ln for ln in lines if cx0 - 2 <= ln["bbox"][0] < cx1], cx0 + (cx1 - cx0) * 0.3, cx0 + (cx1 - cx0) * 0.7, body)
        split += [(cx0, g), (g, cx1)] if g else [(cx0, cx1)]
    for cx0, cx1 in split:
        col = [ln for ln in lines if ln["bbox"][0] >= cx0 - 2 and ln["bbox"][0] < cx1 - 10]
        rows = _rows(col)
        kinds = _grid_rows(rows, body)
        i = 0
        while i < len(rows):
            if kinds[i] != "grid":
                i += 1; continue
            j = i
            pitch = []
            while j + 1 < len(rows):
                gap = rows[j + 1][0]["bbox"][1] - rows[j][0]["bbox"][1]
                avg = sum(pitch) / len(pitch) if pitch else 14.0
                if kinds[j + 1] == "grid" and gap <= max(avg * 2.2, 16):
                    pitch.append(gap); j += 1; continue
                # 묶음 머리 행('수익성(%)') — 위·아래가 격자이고 간격이 고르면 표 안
                if kinds[j + 1] == "label" and j + 2 < len(rows) and kinds[j + 2] in ("grid", "label") and gap <= max(avg * 1.7, 14):
                    pitch.append(gap); j += 1; continue
                break
            # 위로 머리 행(굵은 작은 글자 행, 기간·'구분' 같은 머리) 하나 더
            k = i
            while k - 1 >= 0 and rows[k][0]["bbox"][1] - rows[k - 1][0]["bbox"][1] <= 16 and all(ln["bold"] for ln in rows[k - 1]) and (
                    (kinds[k - 1] in ("grid", "label") and len(rows[k - 1]) >= 2)
                    # 두 줄 머리 사이에 끼인 첫 칸 한 줄('기업명' — 위아래 머리 행에 걸친 칸)
                    or (len(rows[k - 1]) == 1 and k - 2 >= 0 and len(rows[k - 2]) >= 2 and all(ln["bold"] for ln in rows[k - 2]) and rows[k - 1][0]["bbox"][1] - rows[k - 2][0]["bbox"][1] <= 12)):
                k -= 1
            block_rows = rows[k:j + 1]
            if len(block_rows) >= 2:
                boxes = [ln["bbox"] for r in block_rows for ln in r]
                box = _union(boxes)
                colored = sum(1 for r in block_rows for ln in r if ln["color"] not in ("#000000",) and not _is_grey(ln["color"]))
                white = sum(1 for r in block_rows for ln in r if ln["color"] == "#FFFFFF")
                cells = sum(len(r) for r in block_rows)
                # 차트 — 영역 안 차트 조각(색 있는 막대·꺾은선·조각)이 많거나, 행 이름(맨 왼쪽 칸)이 대부분 숫자(축 눈금)
                marks = sum(1 for m in page.get("marks") or [] if _inside(m, [box[0] - 10, box[1] - 30, box[2] + 10, box[3] + 10], 2))
                body_rows = [r for r in block_rows if not (all(ln["bold"] for ln in r) and len(r) >= 2)]
                numeric_labels = sum(1 for r in body_rows if _NUMERIC_CELL.match(r[0]["text"]) or _PERIODISH.match(r[0]["text"].replace(" ", "")))
                is_chart = marks >= 4 or white * 3 > cells or (colored * 10 > cells * 6) or (body_rows and numeric_labels * 2 >= len(body_rows))
                obj = {"bbox": box, "rows": block_rows, "column": (cx0, cx1)}
                (figures if is_chart else tables).append(obj)
                for r in block_rows:
                    for ln in r:
                        used.add(id(ln))
            i = j + 1
    return tables, _split_twins(figures, lines, body), used


def _subrects(items: List[Any]) -> List[List[float]]:
    """채움 경로의 조각(이어지지 않는 선 묶음·사각형)마다 bbox — 막대 여러 개를 한 경로로 그린 차트."""
    out: List[List[float]] = []
    cur: List[Any] = []

    def close() -> None:
        if len(cur) >= 3:
            xs, ys = [p.x for p in cur], [p.y for p in cur]
            out.append([round(min(xs), 1), round(min(ys), 1), round(max(xs), 1), round(max(ys), 1)])
        cur.clear()

    for it in items:
        if it[0] == "re":
            close()
            rc = it[1]
            out.append([round(rc.x0, 1), round(rc.y0, 1), round(rc.x1, 1), round(rc.y1, 1)])
        elif it[0] == "qu":
            close()
            rc = it[1].rect
            out.append([round(rc.x0, 1), round(rc.y0, 1), round(rc.x1, 1), round(rc.y1, 1)])
        elif it[0] in ("l", "c"):
            p1, p2 = it[1], it[-1]
            if cur and (abs(cur[-1].x - p1.x) > 0.5 or abs(cur[-1].y - p1.y) > 0.5):
                close()
            if not cur:
                cur.append(p1)
            cur.append(p2)
    close()
    return out


_NUM_TEXT = re.compile(r"^[-+]?\(?[\d,]*\.?\d+\)?%?[xX배]?$")
_UNIT_TEXT = re.compile(r"^\((?:[^()]{1,8})\)$")


def chart_look(page: Dict[str, Any], fig: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """그림 영역의 벡터(막대 채움·꺾은선)와 글자로 차트 모양을 읽는다 — 종류(bar·line·combo, 가로 막대), 계열 색 순서, 막대 위 값 표시와 그 색,
    범례 이름, x 축 범주(샘플 연도·분기 — 내용이라 채울 때 우리 기간으로 바꾼다), 왼쪽·오른쪽 축, 단위 글자. 막대·선이 없으면 None(사진·그림)."""
    bx = fig["bbox"]
    region = [bx[0] - 2, bx[1] + (12 if fig.get("title") else 0), bx[2] + 2, bx[3] + 2]
    inr = lambda b: _inside(b, region, 2)  # noqa: E731
    width = region[2] - region[0]
    # 막대 — 세로 막대는 폭이 좁고, 가로 막대는 길어도 높이가 낮다(가로 막대를 폭으로 거르면 '국내 주요 베어링 기업 매출액'이 비었다)
    bars = [b for b in page.get("bars") or [] if inr(b["bbox"]) and (b["bbox"][2] - b["bbox"][0] < width * 0.25 or (b["bbox"][3] - b["bbox"][1] <= 16 and b["bbox"][2] - b["bbox"][0] < width * 0.95))]
    texts = [ln for ln in page["lines"] if inr(ln["bbox"]) and ln["text"] != fig.get("title") and not _SOURCE.match(ln["text"])]

    def right_text(sw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return min((ln for ln in texts if 0 <= ln["bbox"][0] - sw["bbox"][2] <= 14 and abs((ln["bbox"][1] + ln["bbox"][3]) / 2 - (sw["bbox"][1] + sw["bbox"][3]) / 2) <= 5),
                   key=lambda ln: ln["bbox"][0], default=None)

    # 범례 견본 — 작은 네모·납작한 띠 + 오른쪽 이름 글자. 이름이 없으면 막대(강조 색 막대 하나 — 로봇 업종 주가의 에스비비테크),
    # 오른쪽 글자가 숫자면 값이 작은 가로 막대('씨에스베어링 1,054'). 꺾은선 위 작은 네모는 점 표지(값 글자 읽기에만 쓴다)
    swatch = [b for b in bars if b["bbox"][2] - b["bbox"][0] <= 22 and b["bbox"][3] - b["bbox"][1] <= 10
              and (nx := right_text(b)) is not None and not _NUM_TEXT.match(nx["text"].replace(" ", ""))]
    color_paths = [x for x in page.get("paths") or [] if inr(x["bbox"]) and not _is_grey(x["color"])]
    markers = [b for b in bars if b not in swatch and b["bbox"][2] - b["bbox"][0] <= 8 and b["bbox"][3] - b["bbox"][1] <= 8
               and any(x["color"] == b["color"] and _inside(b["bbox"], x["bbox"], 4) for x in color_paths)]
    bars = [b for b in bars if b not in swatch and b not in markers and (not _is_grey(b["color"]) or b["color"] < "#F8F8F8")]
    # 꺾은선 — 눈금 달린 축(세로·가로로 납작한 경로)은 뺀다
    paths = [x for x in page.get("paths") or [] if inr(x["bbox"]) and x["points"] >= 3 and x["bbox"][2] - x["bbox"][0] >= 4 and x["bbox"][3] - x["bbox"][1] >= 4]
    if len(bars) < 2 and not paths:
        return None
    ws = [b["bbox"][2] - b["bbox"][0] for b in bars]
    hs = [b["bbox"][3] - b["bbox"][1] for b in bars]
    spread = lambda xs: (max(xs) - min(xs)) / (sum(xs) / len(xs)) if xs and sum(xs) else 0  # noqa: E731
    horizontal = bool(bars) and spread(ws) > spread(hs) * 1.5 and spread(hs) < 0.2
    # 계열 색 순서 — 한 범주 안 막대들의 x(가로 막대는 y) 순서
    groups: List[List[Dict[str, Any]]] = []
    key = (lambda b: (b["bbox"][1] + b["bbox"][3]) / 2) if horizontal else (lambda b: (b["bbox"][0] + b["bbox"][2]) / 2)
    gap = (min(hs) if horizontal else min(ws)) * 1.6 if bars else 0
    for b in sorted(bars, key=key):
        if groups and key(b) - key(groups[-1][-1]) <= gap:
            groups[-1].append(b)
        else:
            groups.append([b])
    best = max(groups, key=len) if groups else []
    colors = list(dict.fromkeys(b["color"] for b in best))
    # 누적 막대 — 한 범주의 막대들이 같은 x 에 위아래로 붙어 있다
    stacked = not horizontal and len(best) >= 2 and len(colors) >= 2 and all(abs(key(b) - key(best[0])) <= 1 for b in best)
    bar_colors = sorted({b["color"] for b in bars}, key=lambda c: colors.index(c) if c in colors else 99)  # 막대 계열 색(나머지는 꺾은선)
    # 꺾은선 계열 — 회색 가는 선은 점이 몇 개면 축·눈금, 점이 많으면 데이터 선(요약 쪽 주가 차트의 KOSDAQ 상대 지수)
    line_colors = [x["color"] for x in sorted(paths, key=lambda x: -x["points"]) if not (_is_grey(x["color"]) and x["width"] < 0.6 and x["points"] < 12)]
    grey_lines = [x for x in paths if _is_grey(x["color"]) and x["bbox"][2] - x["bbox"][0] >= width * 0.5]
    band = not bars and len(grey_lines) >= 3 and any(not _is_grey(c) for c in line_colors)
    if band:  # 밴드의 회색 띠선은 계열이 아니다(밴드 미리보기가 따로 그린다)
        line_colors = [c for c in line_colors if not _is_grey(c)]
    colors += list(dict.fromkeys(c for c in line_colors if c not in colors))
    nums = [ln for ln in texts if _NUM_TEXT.match(ln["text"].replace(" ", ""))]
    plot_x0 = min((b["bbox"][0] for b in bars), default=min((x["bbox"][0] for x in paths), default=region[0]))
    plot_x1 = max((b["bbox"][2] for b in bars), default=max((x["bbox"][2] for x in paths), default=region[2]))
    left_axis = [ln for ln in nums if ln["bbox"][2] <= plot_x0 + 1]
    right_axis = [ln for ln in nums if ln["bbox"][0] >= plot_x1 - 1]
    inner = [ln for ln in nums if ln not in left_axis and ln not in right_axis]
    on_bar = [ln for ln in inner if any(b["bbox"][0] - 4 <= (ln["bbox"][0] + ln["bbox"][2]) / 2 <= b["bbox"][2] + 4 for b in bars)] if bars and not horizontal else inner
    base = max((b["bbox"][3] for b in bars), default=max((x["bbox"][3] for x in paths), default=region[3]))
    # 범주 글자 — 막대 아래 맨 아랫줄. 한 줄 이름은 두 줄 이름 사이 높이에 놓여(로봇 업종 주가의 '클로봇') 줄 높이의 0.6 까지 같은 줄로 본다.
    # 3pt 아래 글자(흰 숨은 글자)는 뺀다
    cats = [ln for ln in texts if ln["bbox"][1] >= base - 2 and ln not in left_axis and ln not in right_axis and not _UNIT_TEXT.match(ln["text"].strip()) and ln["size"] >= 4]
    below = list(cats)
    lh = sorted(c["bbox"][3] - c["bbox"][1] for c in cats)[len(cats) // 2] if cats else 0
    cats = [c for c in cats if abs(c["bbox"][1] - max(x["bbox"][1] for x in cats)) <= max(4.0, lh * 0.6)] if cats else []
    # 두 줄 범주 글자('레인보우 / 로보틱스') — 바로 위 줄(같은 x 가운데)을 앞에 붙인다(아랫줄만 읽으면 '로보틱스'가 겹친다)
    cats = [{**c, "text": f"{up['text']}{c['text']}"} if (up := next((t for t in below if t not in cats and not _NUM_TEXT.match(t["text"].replace(" ", ""))  # 음수 막대 값 글자는 범주가 아니다
                                                                 and abs((t["bbox"][0] + t["bbox"][2]) / 2 - (c["bbox"][0] + c["bbox"][2]) / 2) <= 8
                                                                 and 0 <= c["bbox"][1] - t["bbox"][3] <= 6), None)) else c for c in cats]
    legend = []
    for sw in swatch:
        nxt = right_text(sw)
        if nxt is not None:
            legend.append({"name": nxt["text"], "color": sw["color"]})
    for kl in [k for k in page.get("keys") or [] if inr(k["bbox"]) and k["color"] in line_colors and all(x["color"] != k["color"] for x in legend)]:
        nxt = right_text(kl)
        if nxt is not None and not _NUM_TEXT.match(nxt["text"].replace(" ", "")):
            legend.append({"name": nxt["text"], "color": kl["color"]})
    units =[ln["text"].strip() for ln in texts if _UNIT_TEXT.match(ln["text"].strip())]
    if legend and len(legend) >= len(colors):  # 범례가 있으면 그 색 순서가 계열 순서(막대 묶음 읽기보다 확실)
        colors = list(dict.fromkeys([x["color"] for x in legend] + colors))
    # '1Q23 2Q23 …' 처럼 한 줄로 붙은 기간 범주만 나눈다('3Q25 누적'은 한 범주)
    cat_texts = [t for c in sorted(cats, key=lambda c: c["bbox"][0])
                 for t in (c["text"].split() if len(c["text"].split()) > 1 and all(_PERIODISH.match(x) or re.fullmatch(r"\d+Q\d+F?", x) for x in c["text"].split()) else [c["text"]])]
    kind = "combo" if bars and line_colors else "bar" if bars else "line"
    if band:
        kind = "band"  # 밴드(PSR·PER) — 회색 띠선 여러 개 + 색 있는 주가 선
    # 차트라는 근거(값 축 눈금·막대 위 값·x 축 범주) — 없으면 그림(고객사 로고판의 빨간 원을 막대로 읽던 것)
    if not (len(left_axis) >= 3 or len(on_bar) >= 2 or len(cats) >= 2 or (horizontal and len(nums) >= 2)):
        return None
    if horizontal:
        sample = _hbar_sample(bars, texts)
        cat_texts = (sample or {}).get("categories") or cat_texts
    else:
        sample = _bar_sample(bars, colors, cats, cat_texts, left_axis, [ln for ln in on_bar if ln not in cats], markers, [ln for ln in inner if ln not in cats]) if bars else None
    return {"type": kind, "horizontal": horizontal, "colors": colors[:6], "labels": len(on_bar) >= 2,
            "labelColor": Counter(ln["color"] for ln in on_bar).most_common(1)[0][0] if on_bar else None,
            "legend": legend, "categories": cat_texts[:24],
            "axisLeft": len(left_axis) >= 3, "axisRight": len(right_axis) >= 3, "units": units[:2], "series": max(1, len(colors)), "barColors": bar_colors[:6],
            **({"stacked": True} if stacked else {}),
            **({"sample": sample} if sample else {})}


def _num_of(text: str) -> Optional[float]:
    t = text.replace(",", "").replace("%", "").replace("(", "-").replace(")", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _hbar_sample(bars: List[Dict[str, Any]], texts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """가로 막대의 샘플 값 — 막대 시작선 왼쪽 글자 = 범주(위→아래), 그 줄 막대 끝(막대가 안 보일 만큼 작으면 시작선) 오른쪽 숫자 = 값. 계열 하나."""
    if not bars:
        return None
    x0 = min(b["bbox"][0] for b in bars)
    mid = lambda o: (o["bbox"][1] + o["bbox"][3]) / 2  # noqa: E731
    names = [t for t in texts if x0 - 90 <= t["bbox"][2] <= x0 + 3 and not _NUM_TEXT.match(t["text"].replace(" ", "")) and not _UNIT_TEXT.match(t["text"].strip())]
    cats: List[str] = []
    vals: List[Optional[float]] = []
    for nm in sorted(names, key=mid):
        bar = next((b for b in bars if abs(mid(b) - mid(nm)) <= 6), None)
        end = bar["bbox"][2] if bar else x0
        num = min((t for t in texts if abs(mid(t) - mid(nm)) <= 6 and t["bbox"][0] >= end - 2 and t["bbox"][0] - end <= 24 and _num_of(t["text"]) is not None),
                  key=lambda t: t["bbox"][0], default=None)
        if bar is None and num is None:
            continue
        cats.append(nm["text"])
        vals.append(_num_of(num["text"]) if num is not None else None)
    if len(cats) < 2 or not any(v is not None for v in vals):
        return None
    return {"categories": cats, "series": [vals]}


def _bar_sample(bars: List[Dict[str, Any]], colors: List[str], cats: List[Dict[str, Any]], cat_texts: List[str],
                axis: List[Dict[str, Any]], labels: List[Dict[str, Any]], markers: Optional[List[Dict[str, Any]]] = None,
                point_labels: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """막대 차트의 샘플 값(양식 화면 미리보기만) — 막대 위 값 글자가 있으면 그 값, 없으면 왼쪽 축 눈금(글자 값 ↔ 높이)으로 막대 끝 높이를 값으로 바꾼다.
    범주 = x 축 글자(한 줄에 붙은 '1Q23 2Q23 …'는 그 줄 폭에 고르게), 계열 = 막대 색 순서(colors)."""
    centers: List[float] = []
    for c in sorted(cats, key=lambda c: c["bbox"][0]):
        toks = c["text"].split() if len(c["text"].split()) > 1 and len(cat_texts) > len(cats) else [c["text"]]
        w = (c["bbox"][2] - c["bbox"][0]) / len(toks)
        centers += [c["bbox"][0] + w * (k + 0.5) for k in range(len(toks))]
    if not centers or len(centers) != len(cat_texts):
        return None
    ticks = [(((ln["bbox"][1] + ln["bbox"][3]) / 2), v) for ln in axis if (v := _num_of(ln["text"])) is not None]
    fit = None
    if len(ticks) >= 2:  # 값 = a·y + b (최소제곱)
        n = len(ticks)
        my, mv = sum(t[0] for t in ticks) / n, sum(t[1] for t in ticks) / n
        den = sum((t[0] - my) ** 2 for t in ticks)
        if den:
            a = sum((t[0] - my) * (t[1] - mv) for t in ticks) / den
            fit = (a, mv - a * my)
    series = [[None] * len(centers) for _ in colors]
    one_per_cat = len(bars) <= len(centers)  # 범주마다 막대 하나(강조 색 막대 하나가 섞인 한 계열 차트 — 로봇 업종 주가)
    for b in bars:
        if b["color"] not in colors and not one_per_cat:
            continue
        cx = (b["bbox"][0] + b["bbox"][2]) / 2
        k = min(range(len(centers)), key=lambda i: abs(centers[i] - cx))
        # 값 글자 — 막대와 같은 색이거나 검정·회색(꺾은선의 빨간 % 글자가 회색 막대 위에 있어도 그 막대 값이 아니다).
        # 막대 안 글자(누적 막대 조각의 값)를 먼저, 없으면 막대 위·아래 글자
        near = [ln for ln in labels if (ln["color"] == b["color"] or _is_grey(ln["color"])) and abs((ln["bbox"][0] + ln["bbox"][2]) / 2 - cx) <= max(6.0, (b["bbox"][2] - b["bbox"][0]))]
        inside = [ln for ln in near if b["bbox"][1] <= (ln["bbox"][1] + ln["bbox"][3]) / 2 <= b["bbox"][3] and b["bbox"][0] <= (ln["bbox"][0] + ln["bbox"][2]) / 2 <= b["bbox"][2]
                  and b["bbox"][3] - b["bbox"][1] >= ln["bbox"][3] - ln["bbox"][1]]
        lab = next(iter(inside), None) or next((ln for ln in near if 0 <= b["bbox"][1] - ln["bbox"][3] <= 14 or 0 <= ln["bbox"][1] - b["bbox"][3] <= 14), None)
        v = _num_of(lab["text"]) if lab is not None else None
        if v is None and fit:
            zero = -fit[1] / fit[0] if fit[0] else None
            edge = b["bbox"][1] if zero is None or abs(b["bbox"][3] - zero) <= abs(b["bbox"][1] - zero) else b["bbox"][3]
            v = round(fit[0] * edge + fit[1], 1)
        j = colors.index(b["color"]) if b["color"] in colors else next((i for i, c in enumerate(colors) if any(x["color"] == c for x in bars)), 0)
        if v is not None and series[j][k] is None:
            series[j][k] = v
    # 꺾은선 계열(콤보) — 점 표지 바로 위·아래의 같은 색 값 글자('23.3%')
    for m in markers or []:
        if m["color"] not in colors:
            continue
        cx = (m["bbox"][0] + m["bbox"][2]) / 2
        k = min(range(len(centers)), key=lambda i: abs(centers[i] - cx))
        lab = next((ln for ln in point_labels or [] if ln["color"] == m["color"] and abs((ln["bbox"][0] + ln["bbox"][2]) / 2 - cx) <= 14
                    and (0 <= m["bbox"][1] - ln["bbox"][3] <= 14 or 0 <= ln["bbox"][1] - m["bbox"][3] <= 14)), None)
        v = _num_of(lab["text"]) if lab is not None else None
        if v is not None and series[colors.index(m["color"])][k] is None:
            series[colors.index(m["color"])][k] = v
    if not any(v is not None for s in series for v in s):
        return None
    return {"categories": cat_texts, "series": series}


def _split_twins(figures: List[Dict[str, Any]], lines: List[Dict[str, Any]], body: float) -> List[Dict[str, Any]]:
    """나란한 두 그림(같은 높이의 제목 줄 둘, 각자 아래 '자료:' 줄 — KIRS 분기별 매출액·영업이익) — 축 글자 줄이 이어져 한 그림으로 잡히면
    오른쪽 제목의 x 에서 가른다(단 가르기 _gutter 는 가운데 빈 띠가 없어 못 가른다)."""
    caps = [ln for ln in lines if ln["bold"] and body * 0.7 <= ln["size"] < body * 0.99 and not _NUMERIC_CELL.match(ln["text"])]
    srcs = [ln for ln in lines if _SOURCE.match(ln["text"])]
    cuts = []
    for a in caps:
        for b in caps:
            if b["bbox"][0] - a["bbox"][0] > 120 and abs(a["bbox"][1] - b["bbox"][1]) <= 2:
                below = lambda c: [s["bbox"][1] for s in srcs if abs(s["bbox"][0] - c["bbox"][0]) <= 30 and s["bbox"][1] > c["bbox"][3]]  # noqa: E731
                if below(a) and below(b):
                    cuts.append((b["bbox"][0] - 4, a["bbox"][1], min(below(b))))
    if not cuts:
        return figures
    out: List[Dict[str, Any]] = []
    for f in figures:
        cut = next((c for c in cuts if f["bbox"][0] < c[0] - 10 and c[0] + 10 < f["bbox"][2] and c[1] - 5 <= f["bbox"][1] and f["bbox"][3] <= c[2] + 5), None)
        if cut is None:
            out.append(f)
            continue
        for left in (True, False):
            rows = [[ln for ln in r if (ln["bbox"][0] < cut[0]) == left] for r in f["rows"]]
            rows = [r for r in rows if r]
            if rows:
                out.append({"bbox": _union([ln["bbox"] for r in rows for ln in r]), "rows": rows, "column": f["column"]})
    return out


def _is_head_row(r: List[Dict[str, Any]]) -> bool:
    """머리 행 — 칸 2개 이상이고 (모두 굵고 값 칸이 숫자가 아니다) 또는 (값 칸이 모두 기간 — '(억원) 2022 … 2026F' 처럼 첫 칸이 굵지 않은 단위여도)."""
    if len(r) < 2:
        return False
    tail = [ln["text"].replace(" ", "") for ln in r[1:]]
    if all(_PERIOD_HEAD.match(t) for t in tail):
        return True
    return all(ln["bold"] for ln in r) and sum(1 for ln in r[1:] if _NUMERIC_CELL.match(ln["text"]) and not _PERIODISH.match(ln["text"].replace(" ", ""))) == 0


def _merge_rules(rules: List[Dict[str, Any]], gap: float = 3.0) -> List[Dict[str, Any]]:
    """같은 높이(±0.8)·같은 색의 가로선 조각을 x 로 이어 붙인다(틈 gap 안)."""
    out: List[Dict[str, Any]] = []
    for r in sorted(rules, key=lambda r: (r["color"], round(r["bbox"][1]), r["bbox"][0])):
        last = out[-1] if out else None
        if last and last["color"] == r["color"] and abs(last["bbox"][1] - r["bbox"][1]) <= 0.8 and r["bbox"][0] <= last["bbox"][2] + gap:
            last["bbox"] = [last["bbox"][0], last["bbox"][1], max(last["bbox"][2], r["bbox"][2]), last["bbox"][3]]
            last["width"] = max(last["width"], r["width"])
        else:
            out.append({**r, "bbox": list(r["bbox"])})
    return out


def _merge_fills(fills: List[Dict[str, Any]], gap: float = 2.0) -> List[Dict[str, Any]]:
    """같은 색 바탕 조각을 잇는다 — 같은 열(x 양끝 ±1.5)이면 세로로, 같은 행(y 양끝 ±1.5)이면 가로로(행마다·칸마다 잘린 바탕)."""
    def join(items: List[Dict[str, Any]], axis: int) -> List[Dict[str, Any]]:
        a0, a1 = (0, 2) if axis == 1 else (1, 3)  # 맞춰야 할 쪽(세로로 이을 때는 x 양끝)
        b0, b1 = (1, 3) if axis == 1 else (0, 2)  # 이어 붙일 쪽
        out: List[Dict[str, Any]] = []
        for f in sorted(items, key=lambda f: (f["color"], round(f["bbox"][a0]), round(f["bbox"][a1]), f["bbox"][b0])):
            last = out[-1] if out else None
            if (last and last["color"] == f["color"] and abs(last["bbox"][a0] - f["bbox"][a0]) <= 1.5 and abs(last["bbox"][a1] - f["bbox"][a1]) <= 1.5
                    and f["bbox"][b0] <= last["bbox"][b1] + gap):
                bb = list(last["bbox"])
                bb[b1] = max(bb[b1], f["bbox"][b1])
                last["bbox"] = bb
            else:
                out.append({**f, "bbox": list(f["bbox"])})
        return out
    return join(join(fills, 1), 0)


def _table_cells(t: Dict[str, Any], page: Dict[str, Any]) -> Dict[str, Any]:
    """표 칸 — 줄 좌표로 직접 만든다. 열 기준 = 머리 행 칸의 오른쪽 끝(숫자는 오른쪽 정렬), 머리가 없으면 값 칸 오른쪽 끝 묶음.
    위 머리 행에서 여러 열에 걸친 칸은 묶음 머리(headGroups), 한 열 위에 쌓인 칸은 열 이름에 붙인다('종가 (원)').
    행 이름 = 첫 열 기준보다 왼쪽 줄들, 들여쓰기 = 행 이름 x 가 가장 왼쪽보다 4pt 넘게 들어간 것."""
    rows_ln = t["rows"]
    heads: List[List[Dict[str, Any]]] = []
    for idx, r in enumerate(rows_ln):
        # 두 줄 머리 사이에 끼인 첫 칸 한 줄('기업명')도 머리 — 위에 머리 행이 있고 바로 아래도 머리 행일 때
        between = heads and len(r) == 1 and r[0]["bold"] and idx + 1 < len(rows_ln) and _is_head_row(rows_ln[idx + 1])
        if not (_is_head_row(r) or between):
            break
        heads.append(r)
    body_rows = rows_ln[len(heads):]
    # 열 기준(오른쪽 끝)
    def cluster(xs: List[float], tol: float = 6.0) -> List[float]:
        out: List[List[float]] = []
        for x in sorted(xs):
            if out and x - out[-1][-1] <= tol:
                out[-1].append(x)
            else:
                out.append([x])
        return [sum(c) / len(c) for c in out]
    if heads:
        last = heads[-1]
        stub_last = last[0] if (not _PERIODISH.match(last[0]["text"].replace(" ", "")) and last[0]["bbox"][0] <= min(ln["bbox"][0] for r in body_rows for ln in r[:1] or [last[0]]) + 6) else None
        anchors = cluster([ln["bbox"][2] for ln in last if ln is not stub_last])
    else:
        stub_last = None
        anchors = cluster([ln["bbox"][2] for r in body_rows for ln in r[1:] if _NUMERIC_CELL.match(ln["text"])])
        anchors = [a for a in anchors if sum(1 for r in body_rows for ln in r[1:] if abs(ln["bbox"][2] - a) <= 6) >= max(2, len(body_rows) // 3)] or anchors[-1:]
    if not anchors:
        anchors = [max(ln["bbox"][2] for r in rows_ln for ln in r)]
    widths = [anchors[k] - anchors[k - 1] for k in range(1, len(anchors))]
    colw = min(widths) if widths else 40.0
    first_left = anchors[0] - max(colw * 0.9, 24)

    def col_of(ln: Dict[str, Any]) -> Optional[int]:
        k = min(range(len(anchors)), key=lambda c: abs(ln["bbox"][2] - anchors[c]))
        if abs(ln["bbox"][2] - anchors[k]) <= max(6.0, colw * 0.35):
            return k
        cx = (ln["bbox"][0] + ln["bbox"][2]) / 2
        k2 = min(range(len(anchors)), key=lambda c: abs(cx - (anchors[c] - colw / 2)))
        return k2 if abs(cx - (anchors[k2] - colw / 2)) <= colw * 0.6 else None

    # 머리 — 마지막 머리 행은 열 이름, 그 위 행은 한 열이면 이름 앞에 붙이고 여러 열에 걸치면 묶음 머리
    names = [""] * len(anchors)
    groups: List[Dict[str, Any]] = []
    stub = stub_last["text"] if stub_last is not None else ""
    # 마지막 머리 행의 기간 열이 '2024 2025F 2026F | 2024 2025F 2026F …'처럼 되풀이되면 그 묶음마다 위 행의 글자가 묶음 머리(동종 업종 밸류에이션 —
    # '매출액(십억원)' 글자가 세 열보다 좁아 가운데 열에만 붙던 것)
    last_names = [""] * len(anchors)
    for ln in heads[-1] if heads else []:
        c = col_of(ln) if ln is not stub_last else None
        if c is not None:
            last_names[c] = ln["text"]
    runs: List[List[int]] = []
    prev = None
    for c, head_text in enumerate(last_names):
        y = re.match(r"(\d{4})", head_text.replace(" ", ""))
        v = (int(y.group(1)), head_text) if y else None
        if v is None:
            prev = None
            continue
        if prev is None or v[0] < prev[0] or (v[0] == prev[0] and v[1] == prev[1]):
            runs.append([c])
        else:
            runs[-1].append(c)
        prev = v
    runs = [r for r in runs if len(r) >= 2]
    run_of = {c: r for r in runs for c in r}
    for hi, hr in enumerate(heads):
        for ln in hr:
            if ln is stub_last or (hi < len(heads) - 1 and ln["bbox"][2] < first_left + 4):
                stub = (ln["text"] + " " + stub).strip() if hi < len(heads) - 1 else stub
                continue
            span = [c for c in range(len(anchors)) if ln["bbox"][0] - 4 <= anchors[c] - colw * 0.5 <= ln["bbox"][2] + 4]
            if hi < len(heads) - 1 and len(span) >= 2:
                groups.append({"label": ln["text"], "from": span[0], "to": span[-1]})
                continue
            c = col_of(ln)
            if hi < len(heads) - 1 and c is not None and c in run_of and len(heads) >= 2:
                run = run_of[c]
                groups.append({"label": ln["text"], "from": run[0], "to": run[-1]})
                continue
            if c is not None:
                names[c] = (names[c] + " " + ln["text"]).strip()
    # 몸통 행
    label_x = []
    rows: List[Dict[str, Any]] = []
    for r in body_rows:
        labels = [ln for ln in r if ln["bbox"][2] < first_left + 2 or (ln is r[0] and col_of(ln) is None)]
        values = [""] * len(anchors)
        extra: List[str] = []
        for ln in r:
            if ln in labels:
                continue
            c = col_of(ln)
            if c is None or values[c]:
                extra.append(ln["text"])
            else:
                values[c] = ln["text"]
        lab = labels[0] if labels else None
        label = " ".join(ln["text"] for ln in labels[:1])
        extra = [ln["text"] for ln in labels[1:]] + extra
        if lab is not None:
            label_x.append(lab["bbox"][0])
        rows.append({"label": label, "values": values, "extra": extra, "x": lab["bbox"][0] if lab is not None else None, "bold": bool(lab and lab["bold"]),
                     "color": lab["color"] if lab is not None and lab["color"] != "#000000" else None,
                     "valueColor": next((ln["color"] for ln in r if ln not in labels and ln["color"] != "#000000"), None)})
    # 표 아래 '주:' 줄이 마지막 행으로 잡힌 것(동종 업종 밸류에이션) — 행이 아니라 주석
    foot: List[str] = []
    while rows and _NOTE.match(txt := " ".join([rows[-1]["label"]] + [v for v in rows[-1]["values"] if v] + rows[-1]["extra"]).strip()):
        foot.insert(0, txt)
        rows.pop()
    min_x = min(label_x) if label_x else 0
    for row in rows:
        row["indent"] = 1 if row["x"] is not None and row["x"] - min_x > 4 else 0
        row["group"] = bool(row["label"]) and not any(row["values"]) and not row["extra"]
        row.pop("x", None)
    # 열 강조색(F 열 빨강) — 머리 칸 색
    col_colors: List[Optional[str]] = [None] * len(anchors)
    if heads:
        for ln in heads[-1]:
            c = col_of(ln) if ln is not stub_last else None
            if c is not None and ln["color"] != "#000000" and not _is_grey(ln["color"]):
                col_colors[c] = ln["color"]
    # 규칙선·줄무늬 열·머리 바탕 — Word 로 만든 PDF 는 표 테두리·칸 바탕을 칸마다 잘린 조각으로 그린다(KIRS 실측: 선 x57-139·140-171…, 바탕 행마다 한 칸).
    # 같은 높이·색의 선 조각, 같은 열·색의 바탕 조각을 이어 붙인 뒤에 판정한다(잇기 전에는 '표 폭 절반 이상 선'·'표 높이 60% 바탕'이 하나도 안 걸렸다)
    bx = t["bbox"]
    rules = [r for r in _merge_rules([r for r in page["rules"] if r["bbox"][0] >= bx[0] - 4 and r["bbox"][2] <= bx[2] + 4 and bx[1] - 22 <= r["bbox"][1] <= bx[3] + 4])
             if _overlap_x(r["bbox"], bx) > (bx[2] - bx[0]) * 0.5]
    rule_colors = Counter(r["color"] for r in rules)
    head_top = min((ln["bbox"][1] for r in heads for ln in r), default=bx[1])
    head_bot = max((ln["bbox"][3] for r in heads for ln in r), default=bx[1])
    spans = [(min(ln["bbox"][1] for ln in r), max(ln["bbox"][3] for ln in r)) for r in body_rows][:len(rows)]  # 주석으로 뺀 끝 줄 제외
    top = next((r for r in sorted(rules, key=lambda r: r["bbox"][1]) if r["bbox"][1] <= head_top + 1), None) if heads else None
    head_rule = next((r for r in rules if heads and head_bot - 1 <= r["bbox"][1] <= (spans[0][0] + 1 if spans else head_bot + 6)), None)
    bottom = next((r for r in rules if spans and r["bbox"][1] >= spans[-1][1] - 1), None)
    row_rules = [i for i in range(len(spans) - 1) if any(spans[i][1] - 1.5 <= r["bbox"][1] <= spans[i + 1][0] + 1.5 for r in rules)]
    fills = _merge_fills([f for f in page["fills"] if f["color"] != "#FFFFFF" and _overlap_x(f["bbox"], bx) > 0 and bx[1] - 4 <= f["bbox"][1] and f["bbox"][3] <= bx[3] + 4])
    # 줄무늬 열 — 표 높이의 60% 이상인 좁은(표 폭의 절반 아래) 옅은 회색 칸(사이드바 바탕 같은 넓은 칸은 아님)
    stripes = [f for f in fills if _is_grey(f["color"]) and f["bbox"][3] - f["bbox"][1] > (bx[3] - bx[1]) * 0.6 and f["bbox"][2] - f["bbox"][0] < (bx[2] - bx[0]) * 0.5]
    stripe_cols = [min(range(len(anchors)), key=lambda c: abs((f["bbox"][0] + f["bbox"][2]) / 2 - (anchors[c] - colw / 2))) for f in stripes]
    # 머리 바탕 — 머리 행 높이 안에서 표 폭 대부분을 덮는 바탕(Forecast 의 연분홍)
    head_fill = next((f["color"] for f in fills if heads and f["bbox"][1] >= head_top - 4 and f["bbox"][3] <= head_bot + 4
                      and _overlap_x(f["bbox"], bx) > (bx[2] - bx[0]) * 0.6), None)
    cell_size = Counter(ln["size"] for r in rows_ln for ln in r).most_common(1)[0][0]
    look = {
        "headerBold": True,
        "rule": rule_colors.most_common(1)[0][0] if rule_colors else None,
        "topRule": top["color"] if top else None,
        "topRuleWidth": top["width"] if top else None,
        # 머리 아래 선·표 아래 선·몸통 안 묶음 선(행 번호 i = i 행 아래) — 행마다 긋지 않고 원본 자리에만
        "headRule": head_rule["color"] if head_rule else None,
        "headRuleWidth": head_rule["width"] if head_rule else None,
        "bottomRule": bottom["color"] if bottom else None,
        "rowRules": row_rules,
        "lines": ("horizontal" if len(row_rules) >= max(1, len(spans) - 2) else "groups") if row_rules else ("none" if not rules else "frame"),
        "numberAlign": "right",
        "fontSize": cell_size,
        "columnColors": col_colors,
        "stripeColumns": sorted(set(stripe_cols)),
        "stripeColor": stripes[0]["color"] if stripes else None,
        # 열마다 바탕색(실적 열 회색·예상(F) 열 연분홍처럼 열마다 다를 수 있다 — KIRS 실적 추이 표)
        "columnFills": [next((f["color"] for f, c in zip(stripes, stripe_cols) if c == k), None) for k in range(len(anchors))],
        **({"headerFill": head_fill} if head_fill else {}),
    }
    out = {"columns": names, "stub": stub, "rows": rows, "look": look, **({"notes": foot} if foot else {})}
    if groups:
        out["headGroups"] = groups
    return out


def _tidy_figures(page_list: List[Dict[str, Any]], figures: List[Dict[str, Any]], tables: List[Dict[str, Any]]) -> None:
    """그림 조각 정리 — 문서의 그림 제목 모양(자료 줄이 붙은 제목들의 최빈 색·크기)과 다른 '제목'은 차트 안 글자('조선')로 보고 지운다.
    제목 없는 조각은 같은 쪽·칸에서 바로 위(120pt 안)의 제목 있는 그림에 합친다(자료 줄도 넘긴다). 쪽 요소의 ref 도 맞춘다."""
    styles = Counter((o["captionStyle"]["color"], o["captionStyle"]["size"]) for o in figures + tables if o.get("captionStyle") and o.get("source") and o["column"] == "main")
    if not styles:
        return
    dom = styles.most_common(1)[0][0]
    for f in figures:
        cs = f.get("captionStyle")
        if f["column"] == "main" and f.get("title") and cs and (cs["color"] != dom[0] or abs(cs["size"] - dom[1]) > 0.3):
            f["title"] = ""
    gone: set = set()
    for f in figures:
        if f.get("title") or f["column"] != "main":
            continue
        hosts = [h for h in figures if h is not f and h["id"] not in gone and h.get("title") and h["page"] == f["page"] and h["column"] == "main"
                 and _overlap_x(h["bbox"], f["bbox"]) > 0 and -10 <= f["bbox"][1] - h["bbox"][1] and f["bbox"][1] - h["bbox"][3] <= 120]
        if not hosts:
            continue
        h = max(hosts, key=lambda x: x["bbox"][1])
        h["bbox"] = _union([h["bbox"], f["bbox"]])
        if f.get("source") and not h.get("source"):
            h["source"], h["sourceStyle"] = f["source"], f.get("sourceStyle")
        gone.add(f["id"])
    figures[:] = [f for f in figures if f["id"] not in gone]
    for pg in page_list:
        pg["elements"] = [e for e in pg["elements"] if e.get("ref") not in gone]
        for e in pg["elements"]:
            if e.get("ref"):
                o = next((x for x in figures + tables if x["id"] == e["ref"]), None)
                if o is not None:
                    e["title"], e["bbox"] = o.get("title", ""), o["bbox"]


def _heading_ladder(pages: List[Dict[str, Any]], hf_ids: set, body: float, accent: Optional[str]) -> Dict[Tuple[float, bool, str], str]:
    """제목 모양 사다리 — 본문보다 큰(1.08배~2.2배) 굵은 줄·색 있는 줄 모양 가운데 두 쪽 이상에 나오는 것을 크기순으로 장(chapter)·소제목(headline)·작은 머리(minor).
    강조색 소제목(KIRS)이 있으면 그 모양이 소제목이고, 그보다 큰 반복 모양만 장이 된다(장 띠가 따로 있으면 띠가 장)."""
    seen: Dict[Tuple[float, bool, str], set] = {}
    for p in pages:
        for ln in p["lines"]:
            if (p["page"], id(ln)) in hf_ids or len(ln["text"].strip()) < 3 or len(ln["text"]) > 90 or ln["color"] == "#FFFFFF":
                continue
            colored = ln["color"] not in ("#000000",) and not _is_grey(ln["color"])
            if body * 1.08 <= ln["size"] <= body * 2.2 and (ln["bold"] or colored):
                seen.setdefault((ln["size"], ln["bold"], ln["color"]), set()).add(p["page"])
    styles = sorted([st for st, pg in seen.items() if len(pg) >= 2], key=lambda st: -st[0])
    out: Dict[Tuple[float, bool, str], str] = {}
    acc = [st for st in styles if accent and st[2] == accent and st[1] and len(seen[st]) >= 3]
    if acc:
        # 강조색 소제목이 세 쪽 이상에 되풀이되면(KIRS) 그 모양이 소제목 — 그보다 큰 다른 반복 모양만 장
        head = acc[0]
        for st in styles:
            if st[0] > head[0] + 0.3 and st[2] != accent:
                out[st] = "chapter"
        return out
    kinds = ["chapter", "headline", "minor"]
    for k, st in enumerate(styles[:3]):
        out[st] = kinds[k] if len(styles) >= 2 else "headline"
    return out


# ── 쪽 분석 ──────────────────────────────────────────────────────────────────

def analyze_layout(path: str | Path) -> Dict[str, Any]:
    """PDF → {ok, pages, size, theme, header, footer, page_list:[{page, role, band, sidebar, elements}], tables, figures}."""
    pages = read_pdf(path)
    if not has_text_layer(pages):
        return {"ok": False, "pages": len(pages), "reason": "글자층이 없거나 깨졌습니다(그림 PDF)."}
    body = _theme_sizes(pages)["body"]
    hf_ids, hf = _repeats(pages)
    W = pages[0]["width"]

    # 강조색 — 굵게·본문보다 조금 큰(1.05~1.5배) 색 있는 줄의 최빈색
    accent_votes: Counter = Counter()
    for p in pages:
        for ln in p["lines"]:
            if (p["page"], id(ln)) in hf_ids:
                continue
            if ln["bold"] and body * 1.04 <= ln["size"] <= body * 1.55 and ln["color"] not in ("#000000", "#FFFFFF") and not _is_grey(ln["color"]):
                accent_votes[ln["color"]] += len(ln["text"])
    accent = accent_votes.most_common(1)[0][0] if accent_votes else None
    headline_size = Counter(ln["size"] for p in pages for ln in p["lines"] if accent and ln["color"] == accent and ln["bold"] and body * 1.04 <= ln["size"] <= body * 1.55).most_common(1)
    headline_size = headline_size[0][0] if headline_size else None
    ladder = _heading_ladder(pages, hf_ids, body, accent)
    if not headline_size:
        headline_size = next((st[0] for st, k in ladder.items() if k == "headline"), None)

    page_list: List[Dict[str, Any]] = []
    all_tables: List[Dict[str, Any]] = []
    all_figures: List[Dict[str, Any]] = []
    band_fill = sidebar_fill = None
    band_size = None
    caption_votes: Counter = Counter()
    caption_sizes: Counter = Counter()
    for p in pages:
        pno = p["page"]
        lines = [ln for ln in p["lines"] if (pno, id(ln)) not in hf_ids]
        H = p["height"]
        # 사이드바 — 세로로 긴(쪽 높이 60% 이상) 채움 칸, 폭 20~45%
        side = None
        for f in p["fills"]:
            x0, y0, x1, y1 = f["bbox"]
            if (y1 - y0) >= H * 0.6 and 0.18 * W <= (x1 - x0) <= 0.45 * W and f["color"] != "#FFFFFF":
                side = f
                sidebar_fill = sidebar_fill or f["color"]
                break
        # 본문 칸 x — 본문 크기 보통 줄의 최빈 x(사이드바 밖)
        body_lines = [ln for ln in lines if abs(ln["size"] - body) <= 0.3 and not ln["bold"] and len(ln["text"]) >= 12 and (side is None or ln["bbox"][0] < side["bbox"][0])]
        body_x = Counter(round(ln["bbox"][0]) for ln in body_lines).most_common(1)[0][0] if body_lines else 57
        right = side["bbox"][0] if side else W
        columns = [(0.0, right)] + ([(side["bbox"][0], side["bbox"][2])] if side else [])
        # 장 띠 — 가장 큰 흰 글자(본문 1.3배 이상)가 채움 칸 위에
        band = None
        whites = [ln for ln in lines if ln["color"] == "#FFFFFF" and ln["size"] >= body * 1.3]
        if whites:
            w = max(whites, key=lambda x: x["size"])
            under = [f for f in p["fills"] if _inside(w["bbox"], f["bbox"], 3) and f["color"] != "#FFFFFF"]
            if under and (under[0]["bbox"][2] - under[0]["bbox"][0]) < W * 0.7:
                band = {"text": w["text"], "bbox": under[0]["bbox"], "fill": under[0]["color"], "size": w["size"], "color": w["color"]}
                band_fill = band_fill or under[0]["color"]
                band_size = band_size or w["size"]
        tables, figures, used = _tables_and_figures(p, [ln for ln in lines if not (band and ln["text"] == band["text"])], body, columns)
        for t in tables:
            t.update(_table_cells(t, p))
        elements: List[Dict[str, Any]] = []
        consumed: set = set(used)

        # 제목(굵은 한 줄, 영역 바로 위)·출처('자료:' 줄, 영역 바로 아래) 붙이기
        def attach(obj: Dict[str, Any], kind: str) -> None:
            bx = obj["bbox"]
            above = [ln for ln in lines if id(ln) not in consumed and ((ln["bold"] and body * 0.7 <= ln["size"] < body * 0.99) or _CAPTION.match(ln["text"])) and not _NUMERIC_CELL.match(ln["text"])
                     and ln["bbox"][3] <= bx[1] + 1 and bx[1] - ln["bbox"][3] <= (60 if kind == "figure" else 40) and _overlap_x(ln["bbox"], [bx[0] - 5, 0, max(bx[2], bx[0] + 60), 0]) > 0
                     and abs(ln["bbox"][0] - bx[0]) <= 30]
            if above:
                cap = max(above, key=lambda x: x["bbox"][3])
                obj["title"] = cap["text"]
                obj["captionStyle"] = {"size": cap["size"], "color": cap["color"], "bold": cap["bold"]}
                caption_votes[cap["color"]] += 1
                caption_sizes[cap["size"]] += 1
                consumed.add(id(cap))
                obj["bbox"] = _union([obj["bbox"], cap["bbox"]])
                # 제목 줄 오른쪽 끝의 '(단위: 억원, %)' — 같은 높이의 다른 줄
                for ln in lines:
                    if id(ln) not in consumed and _UNIT_NOTE.search(ln["text"]) and abs(ln["bbox"][1] - cap["bbox"][1]) <= 3 and ln["bbox"][0] > cap["bbox"][2]:
                        obj["unitNote"] = _UNIT_NOTE.search(ln["text"]).group(1).strip()
                        consumed.add(id(ln))
                        break
            below = [ln for ln in lines if id(ln) not in consumed and (_SOURCE.match(ln["text"]) or _NOTE.match(ln["text"])) and ln["bbox"][1] >= bx[3] - 2 and ln["bbox"][1] - bx[3] <= 60
                     and abs(ln["bbox"][0] - bx[0]) <= 30]
            for ln in sorted(below, key=lambda x: x["bbox"][1])[:3]:
                obj.setdefault("notes", []).append(ln["text"])
                if _SOURCE.match(ln["text"]):
                    obj["source"] = ln["text"]
                    obj["sourceStyle"] = {"size": ln["size"], "color": ln["color"]}
                    if kind == "figure":  # 그림 영역은 자료 줄 바로 위까지(축 글자만 묶인 영역이 막대 아랫부분을 못 덮었다 — 경쟁사 실적 차트)
                        obj["bbox"] = _union([obj["bbox"], [obj["bbox"][0], obj["bbox"][1], obj["bbox"][2], ln["bbox"][1] - 1]])
                consumed.add(id(ln))
            obj["kind"] = kind

        for t in tables:
            attach(t, "table")
        for f in figures:
            attach(f, "figure")
        # 그림(이미지·벡터): '자료:' 줄 위의 굵은 제목 줄 — 아직 표·그림에 붙지 않은 짝
        for src in [ln for ln in lines if id(ln) not in consumed and _SOURCE.match(ln["text"])]:
            caps = [ln for ln in lines if id(ln) not in consumed and ((ln["bold"] and body * 0.7 <= ln["size"] < body * 0.99) or _CAPTION.match(ln["text"])) and ln["bbox"][3] <= src["bbox"][1]
                    and abs(ln["bbox"][0] - src["bbox"][0]) <= 30 and not _NUMERIC_CELL.match(ln["text"])]
            cap = max(caps, key=lambda x: x["bbox"][3]) if caps else None
            top = cap["bbox"][3] if cap else src["bbox"][1] - 120
            # 같은 높이 오른쪽에 다른 '자료:' 줄이 있으면 나란한 그림 — 그 앞에서 끊는다(왼쪽 그림이 오른쪽 그림까지 덮던 것)
            twin = [o["bbox"][0] for o in lines if o is not src and _SOURCE.match(o["text"]) and abs(o["bbox"][1] - src["bbox"][1]) <= 3 and o["bbox"][0] > src["bbox"][0] + 100]
            box = [src["bbox"][0], top, (min(twin) - 6) if twin else max(src["bbox"][2], right - 10), src["bbox"][1]]
            inner = [ln for ln in lines if id(ln) not in consumed and _inside(ln["bbox"], box, 2) and ln is not cap]
            for ln in inner:
                consumed.add(id(ln))
            fig = {"bbox": _union([box] + ([cap["bbox"]] if cap else [])), "column": (0.0, right), "title": cap["text"] if cap else "", "source": src["text"],
                   "sourceStyle": {"size": src["size"], "color": src["color"]}, "kind": "figure", "texts": [ln["text"] for ln in inner][:40]}
            if cap:
                fig["captionStyle"] = {"size": cap["size"], "color": cap["color"], "bold": cap["bold"]}
                caption_votes[cap["color"]] += 1
                caption_sizes[cap["size"]] += 1
                consumed.add(id(cap))
            consumed.add(id(src))
            # 그림 안의 작은 글자(연혁 그림의 연도·설명)를 격자로 잘못 잡은 표·그림은 버린다
            tables[:] = [t for t in tables if not _inside(t["bbox"], fig["bbox"], 3)]
            figures[:] = [f for f in figures if not _inside(f["bbox"], fig["bbox"], 3)]
            figures.append(fig)
        # 표로 잡힌 막대 차트(이름·값이 줄마다 있어 글자 격자처럼 보인다 — '글로벌 주요 베어링 기업 매출액') — 영역 안에 길이가 제각각인 막대 3개 이상과
        # 축 선(눈금 달린 경로 — 표 괘선은 rules 라 여기 없다)이 있으면 그림. 오른쪽에 나란한 그림이 있으면 그 앞에서 자른다
        for t in list(tables):
            nb = [f["bbox"][0] for f in figures if t["bbox"][0] + 100 < f["bbox"][0] < t["bbox"][2] and f["bbox"][1] < t["bbox"][3] and f["bbox"][3] > t["bbox"][1]]
            box = [t["bbox"][0], t["bbox"][1], min(nb) - 6, t["bbox"][3]] if nb else list(t["bbox"])
            in_bars = [b for b in p["bars"] if _inside(b["bbox"], box, 2)]
            lens = [max(b["bbox"][2] - b["bbox"][0], b["bbox"][3] - b["bbox"][1]) for b in in_bars]
            if len(in_bars) < 3 or max(lens) < min(lens) * 1.3 or not any(_inside(x["bbox"], box, 3) for x in p["paths"]):
                continue
            tables.remove(t)
            figures.append({"bbox": box, "column": t.get("column"), "title": t.get("title", ""), "kind": "figure", "source": t.get("source"), "sourceStyle": t.get("sourceStyle"),
                            "captionStyle": t.get("captionStyle"), "texts": [ln["text"] for ln in lines if _inside(ln["bbox"], box, 2)][:40], **({"notes": t["notes"]} if t.get("notes") else {})})
        # 제목 없는 차트 조각(범례·축 묶음)이 제목 있는 그림 바로 옆·아래(같은 칸, 세로 40pt 안)에 있으면 그 그림에 합친다
        titled = [f for f in figures if f.get("title") and not _NUMERIC_CELL.match(f["title"])]
        keep_f = []
        for f in figures:
            if f.get("title") and not _NUMERIC_CELL.match(f["title"]) and len(f["title"]) > 2:
                keep_f.append(f); continue
            host = next((h for h in titled if h is not f and _overlap_x(h["bbox"], f["bbox"]) > 0 and f["bbox"][1] <= h["bbox"][3] + 40 and f["bbox"][3] >= h["bbox"][1] - 10), None)
            if host is not None:
                host["bbox"] = _union([host["bbox"], f["bbox"]])
                continue
            keep_f.append(f)
        figures[:] = keep_f
        # 사이드바의 남은 굵은 한 줄 제목 아래 영역(차트 등)
        if side:
            for cap in [ln for ln in lines if id(ln) not in consumed and ln["bold"] and ln["bbox"][0] >= side["bbox"][0] and body * 0.7 <= ln["size"] < body * 0.99]:
                nxt = [o["bbox"][1] for o in tables + figures if o["bbox"][1] > cap["bbox"][3] and o["bbox"][0] >= side["bbox"][0] - 2]
                nxt += [ln["bbox"][1] for ln in lines if ln["bbox"][1] > cap["bbox"][3] + 2 and ln["bold"] and ln["bbox"][0] >= side["bbox"][0] and id(ln) not in consumed and ln is not cap]
                bottom = min(nxt) if nxt else H * 0.9
                box = [side["bbox"][0], cap["bbox"][1], side["bbox"][2], bottom - 2]
                inner = [ln for ln in lines if id(ln) not in consumed and _inside(ln["bbox"], box, 1) and ln is not cap]
                for ln in inner:
                    consumed.add(id(ln))
                consumed.add(id(cap))
                kind = "note" if not inner or all(len(x["text"]) > 30 for x in inner) and len(inner) <= 6 else "figure"
                figures.append({"bbox": box, "column": (side["bbox"][0], side["bbox"][2]), "title": cap["text"], "kind": kind, "texts": [x["text"] for x in inner][:40],
                                "captionStyle": {"size": cap["size"], "color": cap["color"], "bold": cap["bold"]}})

        # 글 요소
        key_lines: List[Dict[str, Any]] = []
        for ln in lines:
            if id(ln) in consumed:
                continue
            if band and ln["text"] == band["text"] and ln["color"] == "#FFFFFF":
                continue
            x0 = ln["bbox"][0]
            in_side = side is not None and x0 >= side["bbox"][0] - 2
            st = (ln["size"], ln["bold"], ln["color"])
            if st in ladder and len(ln["text"]) >= 3 and x0 < W * 0.6:
                kind = ladder[st]
            elif ln["size"] >= body * 1.5:
                kind = "title"
            elif accent and ln["color"] == accent and ln["bold"] and body * 1.04 <= ln["size"] <= body * 1.55 and x0 < W * 0.45:
                kind = "headline"
            elif ln["bold"] and abs(ln["size"] - body) <= 0.6 and x0 < body_x - 40:
                kind = "keyline"
            elif ln["bold"] and abs(ln["size"] - body) <= 0.6 and abs(x0 - body_x) <= 4 and len(ln["text"]) <= 30:
                kind = "minor"
            elif ln["size"] < body * 0.85 and (_SOURCE.match(ln["text"]) or _NOTE.match(ln["text"])):
                kind = "note"
            elif abs(ln["size"] - body) <= 0.6 and not ln["bold"]:
                kind = "para"
            else:
                kind = "text"
            el = {"kind": kind, "text": ln["text"], "bbox": ln["bbox"], "size": ln["size"], "color": ln["color"], "bold": ln["bold"], "column": "side" if in_side else ("key" if kind == "keyline" else "main")}
            if kind == "keyline":
                key_lines.append(el)
            elements.append(el)
        # 문단·핵심 묶기 — 이어진 같은 kind 줄(간격 1.9줄 이하)을 하나로
        merged: List[Dict[str, Any]] = []
        for el in sorted(elements, key=lambda e: (e["column"] != "key", e["bbox"][1], e["bbox"][0])):
            prev = next((m for m in reversed(merged) if m["kind"] == el["kind"] and m["column"] == el["column"]), None)
            if prev is not None and el["kind"] in ("para", "keyline", "title", "note") and 0 <= el["bbox"][1] - prev["bbox"][3] <= el["size"] * 1.05 and abs(el["bbox"][0] - prev["lines"][-1]["bbox"][0]) <= 12:
                prev["lines"].append(el)
                prev["text"] = (prev["text"] + ("" if prev["text"].endswith(("-",)) else " ") + el["text"]).strip() if el["kind"] != "keyline" else prev["text"] + "\n" + el["text"]
                prev["bbox"] = _union([prev["bbox"], el["bbox"]])
                continue
            merged.append({**el, "lines": [el]})
        for m in merged:
            m.pop("lines", None)
        # 핵심 묶음 ↔ 옆 문단(y 가 겹치는 첫 문단)
        for k in [m for m in merged if m["kind"] == "keyline"]:
            para = next((m for m in sorted(merged, key=lambda e: e["bbox"][1]) if m["kind"] == "para" and m["column"] == "main" and m["bbox"][3] >= k["bbox"][1] - 4 and m["bbox"][1] <= k["bbox"][3] + 4), None)
            k["pairY"] = para["bbox"][1] if para else k["bbox"][1]
        objs = [{**{k: v for k, v in o.items() if k not in ("rows", "column")}, "column": "side" if side and o["bbox"][0] >= side["bbox"][0] - 2 else "main"} for o in tables + figures]
        items = merged + objs
        items.sort(key=lambda e: (e["column"] == "side", e.get("pairY", e["bbox"][1]), e["kind"] != "keyline", e["bbox"][0]))
        for n, t in enumerate(tables):
            t["id"] = f"t{pno}_{n + 1}"
            all_tables.append({"id": t["id"], "page": pno, "title": t.get("title", ""), "bbox": t["bbox"], "column": "side" if side and t["bbox"][0] >= side["bbox"][0] - 2 else "main",
                               "stub": t.get("stub", ""), "columns": t.get("columns", []), "rows": t.get("rows", []), "look": t.get("look", {}), "source": t.get("source"),
                               "notes": t.get("notes", []), "captionStyle": t.get("captionStyle"), "sourceStyle": t.get("sourceStyle"), "unitNote": t.get("unitNote"),
                               **({"headGroups": t["headGroups"]} if t.get("headGroups") else {})})
        for n, f in enumerate(figures):
            f["id"] = f"f{pno}_{n + 1}"
            all_figures.append({"id": f["id"], "page": pno, "title": f.get("title", ""), "bbox": f["bbox"], "kind": f.get("kind", "figure"),
                                "column": "side" if side and f["bbox"][0] >= side["bbox"][0] - 2 else "main", "source": f.get("source"), "texts": f.get("texts", [])[:40],
                                "captionStyle": f.get("captionStyle"), "sourceStyle": f.get("sourceStyle")})
        ref = {id(t): t["id"] for t in tables + figures}
        out_items = []
        for it in items:
            if it["kind"] in ("table", "figure", "note") and it.get("id") is None:
                match = next((o for o in tables + figures if o["bbox"] == it["bbox"]), None)
                if match is not None:
                    it = {"kind": it["kind"], "ref": ref[id(match)], "title": match.get("title", ""), "bbox": match["bbox"], "column": it["column"]}
            out_items.append(it)
        page_list.append({"page": pno, "band": band, "sidebar": side["bbox"] if side else None, "sidebarFill": side["color"] if side else None, "bodyX": body_x,
                          "elements": out_items, "images": len(p["images"])})

    _tidy_figures(page_list, all_figures, all_tables)
    # 차트 모양은 조각을 합친 뒤의 영역으로 읽는다(제목 조각만 읽으면 아래 막대 조각을 놓친다 — 경쟁사 실적 차트)
    by_no = {p["page"]: p for p in pages}
    for f in all_figures:
        if f.get("kind", "figure") == "figure" and (look := chart_look(by_no[f["page"]], f)):
            f["chart"] = look

    # 쪽 역할
    n = len(page_list)
    for pg in page_list:
        els = pg["elements"]
        paras = sum(1 for e in els if e["kind"] == "para")
        titles = [e for e in els if e["kind"] == "title"]
        heads = [e for e in els if e["kind"] == "headline"]
        tabs = sum(1 for e in els if e["kind"] == "table")
        text = " ".join(e.get("text", "") for e in els)
        if pg["page"] == 1 and (titles or paras <= 3):
            role = "cover"
        elif pg["page"] == n and (_DISCLAIMER.search(text) or paras == 0):
            role = "disclaimer"
        elif pg["sidebar"] and heads:
            role = "summary"
        elif pg["band"] or any(e["kind"] == "chapter" for e in els):
            role = "chapter"
        elif tabs >= 2 and paras == 0 and not heads:
            role = "appendix"
        else:
            role = "body"
        pg["role"] = role
    theme = {
        "bodySize": body,
        "headlineSize": headline_size,
        "bandSize": band_size,
        "accent": accent,
        "bandFill": band_fill,
        "bandText": "#FFFFFF" if band_fill else None,
        "sidebarFill": sidebar_fill,
        "captionColor": caption_votes.most_common(1)[0][0] if caption_votes else None,
        "captionSize": caption_sizes.most_common(1)[0][0] if caption_sizes else None,
        "fonts": [f for f, _ in Counter(ln["font"] for p in pages for ln in p["lines"]).most_common(4)],
    }
    return {"ok": True, "pages": len(pages), "size": [W, pages[0]["height"]], "theme": theme, "header": hf["header"], "footer": hf["footer"],
            "page_list": page_list, "tables": all_tables, "figures": all_figures}


__all__ = ["PAGE_MAX", "analyze_layout", "has_text_layer", "read_pdf"]
