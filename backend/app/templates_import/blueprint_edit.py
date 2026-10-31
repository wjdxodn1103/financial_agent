"""양식 2.0 틀 — 양식 화면의 표·차트 미리보기와 틀(장·소주제) 고치기.

미리보기 = 샘플 값으로 채운 블록(문서 화면과 같은 모양 — FE TableBlockView·ChartBlockView 가 그대로 그린다).
  표: 행 이름·열·모양은 양식 그대로, 칸은 샘플 값(form.rows[].sample). 차트: 샘플 값(chart.sample — 막대 위 값 글자 또는 축 눈금으로 읽은 막대 높이),
  값을 못 읽은 계열(꺾은선·주가)은 모양만 보이는 예시 값. 미리보기 값은 문서에 들어가지 않는다(문서는 원장·자료로 채운다).
틀 고치기 = 장(큰 제목) 추가·이름·안내·순서·빼기, 장 안 소주제(하위 카테고리) 추가·이름·안내·순서·빼기·표·차트 자리. 표지·요약·부록·고지는 그대로.
(옛 표 양식 가져오기의 미리보기는 templates_import/preview.py)
"""
from __future__ import annotations

import copy
import math
import re
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

CHAPTER_MAX = 12
SUBTOPIC_MAX = 12
BLOCK_MAX = 12
_NUMERIC = re.compile(r"^[-+]?\(?[\d,]*\.?\d+\)?%?$|^[-–]$|^N/?A$|^적[지전자]$|^흑전$", re.I)
SAMPLE_LINE = "자료: 샘플 값(미리보기 — 문서에서는 자료로 채웁니다)"
EXAMPLE_LINE = "예시 값 — 모양만 보입니다(문서에서는 자료로 채웁니다)"


def _title(f: Dict[str, Any]) -> str:
    return (f.get("title") or "").replace("{subject}", "(대상 기업)")


def _table(f: Dict[str, Any]) -> Dict[str, Any]:
    look = {"headerFill": "#FFFFFF", "headerText": "#000000", **dict(f.get("look") or {})}
    if f.get("captionStyle"):
        look.update({"captionColor": f["captionStyle"].get("color"), "captionSize": f["captionStyle"].get("size")})
    cols = list(f.get("columns") or [])
    rows = []
    for r in f.get("rows") or []:
        head = {"kind": "head", "text": r.get("label") or "", "num": False, "indent": int(r.get("indent") or 0), "bold": bool(r.get("bold")), "group": bool(r.get("group")),
                **({"color": r["color"]} if r.get("color") else {})}
        vals = list(r.get("sample") or [])
        cells = [{"kind": "text", "text": vals[j] if j < len(vals) else "", "num": bool(_NUMERIC.match((vals[j] if j < len(vals) else "").replace(" ", ""))), "title": "샘플 값"}
                 for j in range(len(cols))]
        rows.append([head] + cells)
    filled = any(c["text"] for r in rows for c in r[1:])
    return {"kind": "table", "formId": f["id"], "blockId": f["id"], "title": _title(f), "caption": _title(f), "unit": f.get("unit") or "",
            **({"unitNote": f["unitNote"]} if f.get("unitNote") else {}),
            **({"noteLines": list(f["noteSample"])} if f.get("noteSample") else {}),
            "header": [f.get("stub") or (f"({f['unit']})" if f.get("unit") else "")] + cols, "rows": rows, "look": look,
            "sourceLine": SAMPLE_LINE if filled else EXAMPLE_LINE, "position": f.get("position") or "main", "missing": False, "calcs": [], "headGroups": f.get("headGroups") or None}


def _wave(j: int, n: int, lo: float = 20.0, hi: float = 80.0) -> List[float]:
    """모양만 보이는 예시 값 — 계열마다 다른 결의 완만한 선."""
    return [round(lo + (hi - lo) * (0.5 + 0.3 * math.sin((i + 1) * (0.6 + 0.25 * j) + j * 1.7) + 0.1 * math.sin(i * 1.9 + j)), 1) for i in range(n)]


def _chart(f: Dict[str, Any]) -> Dict[str, Any]:
    ch = f.get("chart") or {}
    sample = ch.get("sample") or {}
    cats = list(sample.get("categories") or ch.get("categories") or [])
    kind = ch.get("type") or "bar"
    if kind in ("line", "band") and len(cats) < 6:  # 날짜 축(주가) — 범주 글자가 몇 개뿐이면 그 사이를 채운 예시 범주
        cats = [f"{i + 1}" for i in range(24)]
    if ch.get("horizontal") and not sample:  # 가로 막대 — 아래 글자는 값 축이라 범주가 아니다
        cats = [f"항목 {i + 1}" for i in range(6)]
    cats = cats or [str(i + 1) for i in range(6)]
    seen: Dict[str, int] = {}
    for i, c in enumerate(cats):  # 범주 이름이 겹치면(두 줄 글자의 아랫줄만 읽은 샘플 등) 번호를 붙여 구별
        seen[c] = seen.get(c, 0) + 1
        if seen[c] > 1:
            cats[i] = f"{c} {seen[c]}"
    n = len(cats)
    colors = list(ch.get("colors") or []) or ["#1F3A5F"]
    bar_colors = set(ch.get("barColors") or [])
    names = {x.get("color"): x.get("name") for x in ch.get("legend") or [] if x.get("name")}  # 범례 이름은 색으로 짝짓는다
    got = sample.get("series") or []
    series: List[Dict[str, Any]] = []
    used_sample = False
    if kind == "band":
        series = [{"name": "주가", "values": _wave(0, n, 30, 70), "type": "line"}] + [
            {"name": f"밴드 {k + 1}", "values": [round(50.0 * m, 1)] * n, "type": "line", "computed": True} for k, m in enumerate((0.5, 0.8, 1.1, 1.4))]
    else:
        for j, color in enumerate(colors):
            vals = got[j] if j < len(got) and any(v is not None for v in got[j]) else None
            is_bar = kind == "bar" or (kind == "combo" and color in bar_colors)
            if vals is not None:
                used_sample = True
            else:
                vals = _wave(j, n, 10 if is_bar else 15, 90 if is_bar else 45)
            series.append({"name": names.get(color) or f"계열 {j + 1}", "values": list(vals),
                           "type": "bar" if is_bar else "line", **({"axis": "right"} if kind == "combo" and not is_bar and ch.get("axisRight") else {})})
    chart_type = "band" if kind == "band" else "combo" if kind == "combo" else "line" if kind == "line" else "bar"
    unit = next((u.strip("() ") for u in ch.get("units") or []), "")
    # 자릿수 — 샘플 값이 모두 정수면 원본처럼 소수점 없이(34,900)
    whole = used_sample and all(float(v).is_integer() for s in series for v in s["values"] if v is not None)
    return {"kind": "chart", "formId": f["id"], "blockId": f["id"], "title": _title(f), "caption": _title(f), "categories": cats, "series": series,
            "chartType": chart_type, "horizontal": bool(ch.get("horizontal")), "unit": unit, "legend": "top" if len(series) > 1 else "none",
            "number": "#,##0" if whole else "#,##0.0",
            "look": {"colors": colors, "labels": bool(ch.get("labels")) and n <= 12, "grid": False, **({"stacked": True} if ch.get("stacked") else {})},
            "sourceLine": SAMPLE_LINE if used_sample else EXAMPLE_LINE, "position": f.get("position") or "main", "missing": False}


def preview_blocks(bp: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """틀의 표·그림 양식마다 미리보기 블록 — 표는 샘플 값 표, 차트는 샘플 값(또는 예시 값) 차트, 사진·그림은 자리."""
    out: Dict[str, Dict[str, Any]] = {}
    for fid, f in ((bp or {}).get("forms") or {}).items():
        if f.get("kind") == "table":
            out[fid] = _table(f)
        elif f.get("chart"):
            out[fid] = _chart(f)
        else:
            out[fid] = {"kind": "figure", "formId": fid, "blockId": fid, "title": _title(f), "placeholder": True, "note": f.get("kind") == "note", "position": f.get("position") or "main"}
    return out


def _str(v: Any, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def apply_outline(bp: Dict[str, Any], raw: Any) -> Dict[str, Any]:
    """화면에서 고친 장·소주제 → 새 틀(복사본). raw = [{id?, title, guide, subtopics: [{title, guide, blocks: [formId], pattern?, example?}]}].
    장 id 는 받은 것(틀에 있던 것)을 지키고 새 장은 쓴 적 없는 번호. 표지·요약은 앞, 부록·고지는 뒤 그대로. 소주제의 표·차트 자리는 틀에 있는 양식만."""
    if not isinstance(raw, list) or not raw:
        raise HTTPException(400, "장을 하나 이상 두세요.")
    if len(raw) > CHAPTER_MAX:
        raise HTTPException(400, f"장은 {CHAPTER_MAX}개까지 둘 수 있습니다.")
    new = copy.deepcopy(bp)
    forms = new.get("forms") or {}
    old = {p["id"]: p for p in new.get("parts") or [] if p.get("role") == "chapter"}
    proto = next(iter(old.values()), {"role": "chapter", "band": True, "keyline": True})
    nums = [int(m.group(1)) for k in old for m in [re.fullmatch(r"c(\d+)", k)] if m]
    next_n = max(nums, default=0) + 1
    seen: set = set()
    chapters: List[Dict[str, Any]] = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        title = _str(c.get("title"), 40)
        if not title:
            raise HTTPException(400, "장 이름을 적어 주세요.")
        pid = str(c.get("id") or "")
        if pid not in old or pid in seen:
            pid, next_n = f"c{next_n}", next_n + 1
        seen.add(pid)
        subs_in = c.get("subtopics") if isinstance(c.get("subtopics"), list) else []
        if not subs_in:
            raise HTTPException(400, f"'{title}' 장에 소주제를 하나 이상 두세요.")
        if len(subs_in) > SUBTOPIC_MAX:
            raise HTTPException(400, f"소주제는 장마다 {SUBTOPIC_MAX}개까지 둘 수 있습니다.")
        subs = []
        for s in subs_in:
            if not isinstance(s, dict):
                continue
            st = _str(s.get("title"), 40)
            if not st:
                raise HTTPException(400, f"'{title}' 장의 소주제 이름을 적어 주세요.")
            blocks = [str(b) for b in s.get("blocks") or [] if str(b) in forms][:BLOCK_MAX]
            pattern = [str(x) for x in s.get("pattern") or [] if str(x) in ("K", "P", "M") or str(x) in forms][:80]
            subs.append({"title": st, "guide": _str(s.get("guide"), 300), "example": _str(s.get("example"), 120), "blocks": list(dict.fromkeys(blocks)), "pattern": pattern})
        base = old.get(pid) or {k: proto.get(k) for k in ("role", "band", "keyline")}
        chapters.append({**base, "id": pid, "role": "chapter", "title": title, "guide": _str(c.get("guide"), 300), "subtopics": subs})
    parts = new.get("parts") or []
    new["parts"] = [p for p in parts if p.get("role") in ("cover", "summary")] + chapters + [p for p in parts if p.get("role") in ("appendix", "disclaimer")]
    return new


__all__ = ["preview_blocks", "apply_outline"]
