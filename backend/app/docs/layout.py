"""조판 문단 인식 — StatUpAI OP-BE `paper/refs/layout.py`(청커 v7) 그대로.
PyMuPDF 줄 좌표(`page.get_text("dict")`)로 2단을 풀고 행간·들여쓰기·글꼴·짧게 끝난 줄로 문단 경계를 찾는다:
 - 열 판정: 폭이 페이지의 60% 를 넘거나 페이지 중앙을 가로지르는 줄 = 전폭, 나머지는 중심 x 로 좌/우. 양쪽에 5줄 이상이면 2단.
 - 같은 기준선(세로 겹침 50% 이상) 줄은 한 줄로 합친다(위첨자·각주 번호·수식 조각).
 - 경계: gap(행간 > 중앙 행간 + 0.45 행높이) / jump(역행) / font(크기 0.8pt 차 또는 굵기 토글, 짧은 줄) / indent(0.8 글자 크기 이상 들여쓰기) / short-end(오른쪽 15% 이상 비고 문장 종결) / column·page.
 - 열·페이지에서 잘린 문단은 앞이 문장 끝이 아니고 뒤가 소문자·조사로 시작하면 잇는다(heal).
 - 3쪽 이상 반복되는 60자 이하 문단(러닝 헤더·쪽번호)은 버린다 — extract_pdf 의 블록 규칙과 같다.
제목·표 분류와 버리기는 extract.pdf_paragraphs 가 맡는다.
문단마다 boxes = [[쪽, x0, y0, x1, y1], …](쪽 크기로 나눈 0~1, 쪽·단마다 줄을 합친 사각형) — 원문 확인 창이 글을 다시 맞춰 찾지 않고 그대로 그린다.
잇기(heal)로 합친 문단은 두 쪽의 상자를 다 가진다.
"""
from __future__ import annotations

import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

Line = Dict[str, Any]
LayoutPara = Dict[str, Any]  # {"page", "text", "size", "bold", "reason", "healed"}

# 다운로드 도장: "IP 000.000.000.000 at Monday, September 01, 2025 12:00:00 AM", "[Provider:earticle] Download by …"(한국 학술 DB) — 본문 줄과 같은 기준선에 찍힌다
IP_STAMP = re.compile(r"\[Provider:[^\]]*\]\s*Download\s+by\s*|IP\s+[0-9X.]+\s+at\s+[A-Za-z]+,\s+[A-Za-z]+\s+[0-9]+,\s+[0-9]{4}\s+[0-9:]+\s*(AM|PM)")
_END = re.compile(r"[.!?。]\s*$|다\.\s*$|[.!?][\"”’)\]]\s*$")
_LOWER_START = re.compile(r"^[a-z(,;]|^[가-힣]{1,2}[은는이가을를에의로도]\s")  # 소문자·접속 조사로 시작 = 이어지는 문장
_CAP_START = re.compile(r"^[A-Z0-9\[(“\"■●▪◆∎【]|^[가-힣]")
_BULLET = re.compile(r"^\s*(?:[-•▪■●∙·]|\(?\d{1,2}[.)]|[가나다라마바사]\.|[①-⑳])\s*")
_PAGE_NO = re.compile(r"[\d\s\-–]+")


def _median(xs: List[float], default: float = 0.0) -> float:
    return statistics.median(xs) if xs else default


def ends_sentence(text: str) -> bool:
    return bool(_END.search(text))


def _inside(x0: float, y0: float, x1: float, y1: float, rects: List[Tuple[float, float, float, float]]) -> bool:
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return any(r[0] - 1 <= cx <= r[2] + 1 and r[1] - 1 <= cy <= r[3] + 1 for r in rects)


def page_lines(page: Any, exclude: Optional[List[Tuple[float, float, float, float]]] = None) -> List[Line]:
    """한 페이지의 줄 목록 [{text, x0, y0, x1, y1, size, bold, full, col}] — 열 판정 뒤 (열, y, x) 순, 같은 기준선 줄은 합쳐서.
    exclude: 표 영역(칸 구조로 따로 뽑은 표) — 그 안의 줄은 문단에서 뺀다(같은 숫자가 두 번 들어가지 않게)."""
    d = page.get_text("dict")
    width = page.rect.width
    lines: List[Line] = []
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        for l in b.get("lines", []):
            spans = [s for s in l.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s.get("text", "") for s in l["spans"])
            text = re.sub(r"\s+", " ", IP_STAMP.sub(" ", text)).strip()
            if not text:
                continue
            x0, y0, x1, y1 = l["bbox"]
            if exclude and _inside(x0, y0, x1, y1, exclude):
                continue
            main = max(spans, key=lambda s: len(s.get("text", "").strip()))  # 글자 크기·굵기는 가장 긴 스팬 기준(위첨자·도장 스팬에 끌리지 않게)
            lines.append({
                "text": text, "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                "size": float(main.get("size") or 10.0),
                "bold": bool(int(main.get("flags", 0)) & 16),
                "full": (x1 - x0) > width * 0.6 or (x0 < width * 0.5 < x1 and (x1 - x0) > width * 0.25),
            })
    if not lines:
        return []

    def col(l: Line) -> int:
        return 0 if l["full"] else (0 if (l["x0"] + l["x1"]) / 2 < width / 2 else 1)

    two = sum(1 for l in lines if not l["full"] and col(l) == 1) >= 5 and sum(1 for l in lines if not l["full"] and col(l) == 0) >= 5
    for l in lines:
        l["col"] = col(l) if two else 0
    lines.sort(key=lambda l: (l["col"], round(l["y0"], 1), l["x0"]))
    merged: List[Line] = []
    for l in lines:
        if merged and merged[-1]["col"] == l["col"]:
            q = merged[-1]
            h = min(q["y1"] - q["y0"], l["y1"] - l["y0"]) or 1.0
            overlap = min(q["y1"], l["y1"]) - max(q["y0"], l["y0"])
            if overlap > 0.5 * h:  # 같은 기준선 — 위첨자/각주 번호/수식 조각/다운로드 도장
                if len(l["text"]) > len(q["text"]):
                    q["size"], q["bold"] = l["size"], l["bold"]  # 긴 쪽이 본문
                q["text"] = f"{q['text']} {l['text']}".strip() if l["x0"] >= q["x0"] else f"{l['text']} {q['text']}".strip()
                q["x0"], q["x1"] = min(q["x0"], l["x0"]), max(q["x1"], l["x1"])
                q["y0"], q["y1"] = min(q["y0"], l["y0"]), max(q["y1"], l["y1"])
                continue
        merged.append(l)
    return merged


def split_paragraphs(lines: List[Line]) -> List[LayoutPara]:
    """한 페이지의 (열 순) 줄 → 문단 [{text, size, bold, reason}]. 경계 규칙: column / gap / jump / font / indent / short-end."""
    if not lines:
        return []
    stats: Dict[int, Dict[str, float]] = {}
    for c in {l["col"] for l in lines}:
        ls = [l for l in lines if l["col"] == c]
        hs = [l["y1"] - l["y0"] for l in ls]
        mh = _median(hs, 10.0)
        gaps = [ls[i + 1]["y0"] - ls[i]["y1"] for i in range(len(ls) - 1)]
        normal = [g for g in gaps if -0.2 * mh <= g <= 1.5 * mh]
        xs0 = sorted(l["x0"] for l in ls if not l["full"]) or sorted(l["x0"] for l in ls)
        xs1 = sorted(l["x1"] for l in ls if not l["full"]) or sorted(l["x1"] for l in ls)
        stats[c] = {"mh": mh, "mgap": _median(normal, 0.15 * mh), "x0": xs0[len(xs0) // 10], "x1": xs1[-1 - len(xs1) // 10], "size": _median([l["size"] for l in ls], 10.0)}
    groups: List[Dict[str, Any]] = []
    cur: List[Line] = []
    reason = "start"
    prev: Line | None = None
    for l in lines:
        st = stats[l["col"]]
        why = None
        if prev is not None:
            if prev["col"] != l["col"]:
                why = "column"
            else:
                gap = l["y0"] - prev["y1"]
                colw = max(1.0, st["x1"] - st["x0"])
                if gap > max(st["mgap"] + 0.45 * st["mh"], 1.6 * st["mgap"] + 0.1 * st["mh"]):
                    why = "gap"
                elif gap < -0.6 * st["mh"]:
                    why = "jump"
                elif abs(l["size"] - prev["size"]) > 0.8 or (l["bold"] != prev["bold"] and (len(l["text"]) < 60 or len(prev["text"]) < 60)):
                    why = "font"
                elif (l["x0"] - st["x0"]) > 0.8 * st["size"] and (prev["x0"] - st["x0"]) <= 0.4 * st["size"] and not l["full"]:
                    why = "indent"
                elif prev["x1"] < st["x1"] - 0.15 * colw and _END.search(prev["text"]) and not prev["full"]:
                    why = "short-end"
        if why and cur:
            groups.append({"lines": cur, "reason": reason})
            cur, reason = [], why
        cur.append(l)
        prev = l
    if cur:
        groups.append({"lines": cur, "reason": reason})
    out: List[LayoutPara] = []
    for g in groups:
        text = ""
        for l in g["lines"]:
            t = l["text"]
            if text.endswith("-") and re.match(r"[a-z]", t):  # 영문 하이픈 줄바꿈 잇기
                text = text[:-1] + t
            else:
                text = f"{text} {t}" if text else t
        first = g["lines"][0]
        ls = g["lines"]
        rect = [min(l["x0"] for l in ls), min(l["y0"] for l in ls), max(l["x1"] for l in ls), max(l["y1"] for l in ls)]
        out.append({"text": text.strip(), "reason": g["reason"], "size": _median([l["size"] for l in g["lines"]], 10.0), "bold": all(l["bold"] for l in g["lines"]), "y0": first["y0"], "col": first["col"], "rect": rect})
    return out


def _box(pno: int, rect: List[float], w: float, h: float) -> List[float]:
    return [pno, round(rect[0] / w, 4), round(rect[1] / h, 4), round(rect[2] / w, 4), round(rect[3] / h, 4)]


def heal(paras: List[LayoutPara], tables: Optional[Dict[int, List[Tuple[float, float, float, float]]]] = None) -> List[LayoutPara]:
    """열·페이지에서 잘린 문단 잇기: 앞 문단이 문장 끝이 아니고 뒤 문단이 이어지는 모양(소문자·조사·대문자 아님)이면 합친다. 글머리표·글꼴 크기가 다른 것은 잇지 않는다.
    표 제목 줄(caption)과는 잇지 않고, 같은 쪽에서 두 문단 사이에 표가 있으면(표 위 제목 + 표 아래 본문) 잇지 않는다."""
    out: List[LayoutPara] = []
    for p in paras:
        if out:
            q = out[-1]
            t = p["text"]
            between = q.get("page") == p.get("page") and any(q.get("y0", 0) < r[1] <= p.get("y0", 0) for r in (tables or {}).get(p.get("page") or 0, []))
            if q.get("caption") or p.get("caption") or between:
                out.append(dict(p))
                continue
            continues = _LOWER_START.match(t) or not _CAP_START.match(t) or (re.match(r"^[가-힣]", t) and not q["text"].rstrip().endswith((":", "다", ".")))
            if not _END.search(q["text"]) and continues and not _BULLET.match(t) and abs(p["size"] - q["size"]) <= 0.8:
                q["text"] = f"{q['text']} {t}"
                q["healed"] = q.get("healed", 0) + 1
                q["boxes"] = [*(q.get("boxes") or []), *(p.get("boxes") or [])]  # 다른 단·쪽의 상자도 같이
                continue
        out.append(dict(p))
    return out


def layout_paragraphs(doc: Any, exclude_by_page: Optional[Dict[int, List[Tuple[float, float, float, float]]]] = None) -> List[LayoutPara]:
    """열린 PyMuPDF 문서 → 조판 문단(페이지 순, 반복 머리글 제거, 열·페이지 잇기). 각 항목 {"page", "text", "size", "bold", "reason", "healed", "y0", "col"}."""
    all_pages: List[List[LayoutPara]] = []
    seen: Dict[str, int] = {}
    n = 0
    for pno, page in enumerate(doc, 1):
        n += 1
        ps = split_paragraphs(page_lines(page, (exclude_by_page or {}).get(pno)))
        w, h = page.rect.width or 1.0, page.rect.height or 1.0
        for p in ps:
            p["page"] = pno
            p["boxes"] = [_box(pno, p.pop("rect"), w, h)]
            if len(p["text"]) <= 60:
                seen[p["text"]] = seen.get(p["text"], 0) + 1
        all_pages.append(ps)
    repeated = {t for t, c in seen.items() if c >= 3 and n >= 3}
    flat = [p for ps in all_pages for p in ps if p["text"] not in repeated and not _PAGE_NO.fullmatch(p["text"])]
    # 칸 구조 표 바로 위(60pt 안)에서 가장 가까운 짧은 줄 = 표 제목 — 표가 caption 으로 가져가고 문단에서는 뺀다(그 위 쪽 제목은 남긴다)
    for pno, rects in (exclude_by_page or {}).items():
        for r in rects:
            above = [p for p in flat if p.get("page") == pno and len(p["text"]) <= 100 and r[1] - 60 <= p.get("y0", -1e9) < r[1]]
            if above:
                max(above, key=lambda p: p.get("y0", 0))["caption"] = True
    return heal(flat, exclude_by_page)


__all__ = ["IP_STAMP", "ends_sentence", "heal", "layout_paragraphs", "page_lines", "split_paragraphs"]
