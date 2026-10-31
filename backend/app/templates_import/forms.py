"""문서 양식의 표·차트 양식(에셋) — 샘플에서 뽑은 '형식'만(구성 + 겉모양 + 샘플 속 위치). 숫자·행 이름 같은 내용은 두지 않는다.

에셋은 섹션에 묶지 않고 양식 전체의 모음이다(sectionId 는 샘플에서 어느 섹션에 있었는지 참고만). 저장 모양:
  {id, kind: table|chart, name, desc, sectionId, position: main|sidebar,
   source: {page, box: [x0, y0, x1, y1](0~1) | None, caption},   — 원본에서 잘라 보여 줄 자리(caption 은 샘플 제목 그대로, 참고용)
   caption: {label, numbered}, sourceLine, note,
   table: {stub, rowKind, rows, groups: [{label, unit, columns: [..]}]},
   chart: {type, x, series: [{name, type, axis}], unit, unit2, legend},
   look: {headerFill, headerText, rule, lines, numberAlign, colors: [..], grid, labels, captionBold, captionColor}}
analyze.py 가 VL 이 읽은 블록(block_to_asset)으로 만들고, 화면에서 고친 것은 clean_assets 로 받는다(이름·설명·빼기·순서와 차트 종류만 — VL 이 막대를 가로 막대로
읽는 일이 있어 종류는 고칠 수 있게. 나머지 구성은 샘플에서 온 것 그대로).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

ASSET_MAX = 60  # 기업분석 샘플(KIRS 27쪽)은 표·그림이 약 40개
CHART_TYPES = ("line", "bar", "barh", "area", "pie", "combo", "band", "other")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_AID = re.compile(r"^a\d{1,3}$")
_NUMBER = re.compile(r"^\s*(?:표|그림|차트|Table|Figure|Chart|Exhibit)\s*\d+[.:]?\s*", re.I)
_UNIT_SUFFIX = re.compile(r"\s*[(\[]\s*([^()\[\]]{1,16})\s*[)\]]\s*$")


def _s(v: Any, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _hex(v: Any) -> Optional[str]:
    t = str(v or "").strip()
    return t.lower() if _HEX.match(t) else None


def _int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def strip_number(caption: str) -> str:
    """'표 1. 인도 주요 지수 수익률' → '인도 주요 지수 수익률'"""
    return _NUMBER.sub("", caption or "").strip()


def split_unit(label: str, unit: str) -> tuple:
    """'투자수익률 (%)' → ('투자수익률', '%') — 묶음 머리에 붙은 단위를 단위 칸으로(화면이 두 번 붙이지 않게)."""
    m = _UNIT_SUFFIX.search(label or "")
    return (label[: m.start()].strip(), unit or m.group(1).strip()) if m and label[: m.start()].strip() else (label, unit)


def _box(v: Any) -> Optional[List[float]]:
    """VL 의 0~1000 비율 좌표 → 0~1. 이상하면 None(원본 쪽 전체를 보인다)."""
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(x) for x in v)
    except (TypeError, ValueError):
        return None
    scale = 1000.0 if max(x0, y0, x1, y1) > 1.5 else 1.0
    x0, y0, x1, y1 = (max(0.0, min(1.0, x / scale)) for x in (x0, y0, x1, y1))
    if x1 - x0 < 0.03 or y1 - y0 < 0.02:
        return None
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def _look(raw: Any, kind: str) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    out: Dict[str, Any] = {}
    if kind == "table":
        for src, key in (("header_fill", "headerFill"), ("header_text", "headerText"), ("rule", "rule")):
            if _hex(raw.get(src)):
                out[key] = _hex(raw.get(src))
        if raw.get("lines") in ("horizontal", "grid", "none"):
            out["lines"] = raw["lines"]
        if raw.get("number_align") in ("right", "center", "left"):
            out["numberAlign"] = raw["number_align"]
    else:
        colors = [c for c in (_hex(x) for x in (raw.get("colors") or [])[:8]) if c]
        if colors:
            out["colors"] = colors
        for key in ("grid", "labels"):
            if isinstance(raw.get(key), bool):
                out[key] = raw[key]
    return out


def _caption_look(style: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if isinstance(style.get("bold"), bool):
        out["captionBold"] = style["bold"]
    if _hex(style.get("color")):
        out["captionColor"] = _hex(style.get("color"))
    return out


def block_to_asset(block: Dict[str, Any], aid: str, page: Optional[int], caption_style: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """쪽 읽기(analyze.PAGE_PROMPT 모양)의 표·차트 블록 → 에셋(이름은 샘플 제목 — 묶기에서 일반 이름으로 바꾼다)."""
    kind = block.get("type")
    if kind not in ("table", "chart"):
        return None
    cs = caption_style if isinstance(caption_style, dict) else {}
    caption = _s(block.get("caption"), 120)
    label = _s(cs.get("table_label" if kind == "table" else "chart_label"), 6)
    asset: Dict[str, Any] = {
        "id": aid,
        "kind": kind,
        "name": strip_number(caption)[:80] or ("표" if kind == "table" else "차트"),
        "desc": "",
        "sectionId": None,
        "position": "sidebar" if block.get("position") == "sidebar" else "main",
        "source": {"page": page, "box": _box(block.get("box")), "caption": caption},
        "caption": {"label": label, "numbered": bool(cs.get("numbered")) and bool(label)},
        "sourceLine": bool(block.get("source_line", kind == "table")),
        "note": bool(block.get("note")),
        "look": {**_look(block.get("look") if kind == "table" else block, kind), **_caption_look(cs)},
    }
    if kind == "table":
        groups = []
        for g in (block.get("header") or [])[:12]:
            if not isinstance(g, dict):
                continue
            cols = [_s(c, 40) for c in (g.get("columns") or [])[:16] if _s(c, 40)]
            label, unit = split_unit(_s(g.get("group"), 40), _s(g.get("unit"), 20))
            if cols or label:
                groups.append({"label": label, "unit": unit, "columns": cols or [label]})
        asset["table"] = {"stub": _s(block.get("stub"), 40), "rowKind": _s(block.get("row_kind"), 20), "rows": _int(block.get("row_count"), 1, 200, 5), "groups": groups}
    else:
        series = []
        for x in (block.get("series") or [])[:10]:
            name = _s(x.get("name") if isinstance(x, dict) else x, 40)
            if not name:
                continue
            x = x if isinstance(x, dict) else {}
            series.append({"name": name, "type": x.get("type") if x.get("type") in ("line", "bar", "area") else "line", "axis": "right" if x.get("axis") == "right" else "left"})
        ctype = block.get("chart_type") if block.get("chart_type") in CHART_TYPES else "other"
        asset["chart"] = {
            "type": ctype,
            "x": block.get("x") if block.get("x") in ("date", "period", "category") else "category",
            "series": series,
            "unit": _s(block.get("unit"), 20),
            "unit2": _s(block.get("unit2"), 20),
            "legend": block.get("legend") if block.get("legend") in ("top", "bottom", "right", "none") else ("none" if len(series) <= 1 else "top"),
        }
    return asset


def apply_rename(asset: Dict[str, Any], rename: Any) -> None:
    """샘플 속 고유한 이름(지수·통화 등) → 역할 이름. 머리·계열·단위 글자에서 그대로 바꾼다."""
    if not isinstance(rename, dict):
        return
    pairs = sorted(((str(k), _s(v, 40)) for k, v in rename.items() if str(k).strip() and _s(v, 40)), key=lambda p: -len(p[0]))[:20]
    if not pairs:
        return

    def fix(text: str) -> str:
        for old, new in pairs:
            text = text.replace(old, new)
        return text

    t = asset.get("table")
    if t:
        t["stub"], t["rowKind"] = fix(t["stub"]), fix(t["rowKind"])
        for g in t["groups"]:
            g["label"], g["unit"], g["columns"] = fix(g["label"]), fix(g["unit"]), [fix(c) for c in g["columns"]]
    c = asset.get("chart")
    if c:
        c["unit"], c["unit2"] = fix(c["unit"]), fix(c["unit2"])
        for x in c["series"]:
            x["name"] = fix(x["name"])


def clean_assets(raw: Any, base: List[Dict[str, Any]], section_ids: List[str]) -> List[Dict[str, Any]]:
    """화면에서 고친 에셋 목록 → 저장 모양. 받은 것은 id·이름·설명(·순서)·차트 종류뿐 — 구성·겉모양·위치는 base(분석 결과·저장된 것)에서.
    목록에 없는 id 는 빠진 것, 모르는 id 는 버린다. sectionId 는 남은 섹션만."""
    if raw is None:
        raw = base
    if not isinstance(raw, list):
        return []
    by_id = {a["id"]: a for a in base if isinstance(a, dict) and a.get("id")}
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for x in raw[:ASSET_MAX]:
        if not isinstance(x, dict):
            continue
        aid = str(x.get("id") or "")
        a = by_id.get(aid)
        if a is None or aid in seen:
            continue
        seen.add(aid)
        a = {**a, "name": _s(x.get("name"), 80) or a["name"], "desc": _s(x.get("desc", a.get("desc")), 200)}
        if a.get("chart") and x.get("chartType") in CHART_TYPES:
            a["chart"] = {**a["chart"], "type": x["chartType"]}
        if a.get("sectionId") not in section_ids:
            a["sectionId"] = None
        out.append(a)
    return out


def is_asset_id(v: str) -> bool:
    return bool(_AID.match(v or ""))


__all__ = ["ASSET_MAX", "apply_rename", "block_to_asset", "clean_assets", "is_asset_id", "strip_number"]
