"""미리보기 — 우리 엔진(research/block.to_block·chart.chart_block)으로 샘플 값을 그대로 다시 그린다.

표: spec 의 열(이름·단위·방향)대로 샘플 칸을 옮긴다 — 등록하면 이런 모양으로 채워진다는 것을 보인다. 값은 미리보기에만 쓰고 저장하지 않는다.
차트: 샘플 차트의 범주·계열·값 그대로.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.research.block import to_block
from app.research.chart import chart_block
from app.research.entities import norm

_NUM = re.compile(r"^[-+(]?\s*[\d,]+(?:\.\d+)?\s*%?\)?$")


def _key(label: str) -> str:
    return norm(re.sub(r"\s*[(\[][^()\[\]]{1,12}[)\]]\s*$", "", label or ""))


def _cell(text: str) -> Dict[str, Any]:
    t = (text or "").strip()
    if not t or t in ("-", "–", "—"):
        return {"type": "empty"}
    return {"type": "number", "text": t} if _NUM.match(t) else {"type": "text", "text": t, "cites": []}


def table_preview(rows: List[List[str]], spec: Dict[str, Any], caption: str, source: str) -> Dict[str, Any]:
    header, body = rows[0], rows[1:]
    items = [it for it in spec["items"] if not it.get("hidden")]
    by_col = {_key(h): j for j, h in enumerate(header)}
    by_row = {_key(r[0]): r for r in body if r}
    if spec.get("orientation") == "items_as_rows" and any(_key(it["label"]) in by_row for it in items):
        # 샘플이 '지표가 행' — 행 = 지표, 열 = 대상(기간·기업)
        subjects = [{"label": h} for h in header[1:] if h.strip()]
        cells = [{it["key"]: _cell((by_row.get(_key(it["label"])) or [""] * len(header))[j + 1] if j + 1 < len(header) else "") for it in items} for j in range(len(subjects))]
    else:
        subjects = [{"label": r[0]} for r in body if r and r[0].strip()]
        cells = [{it["key"]: _cell(r[by_col[_key(it["label"])]] if _key(it["label"]) in by_col and by_col[_key(it["label"])] < len(r) else "") for it in items} for r in body if r and r[0].strip()]
    data = {"spec": spec, "subjects": subjects, "items": items, "cells": cells, "columns": {it["key"]: {"unit": it.get("unit") or ""} for it in items}, "period": None}
    block = to_block(caption or spec["name"], data)
    block["sourceLine"] = f"샘플: {source}"
    return block


def chart_preview(chart: Dict[str, Any], caption: str, unit: Optional[str], source: str) -> Dict[str, Any]:
    values = [v for s in chart["series"] for v in s["values"] if v is not None]
    decimals = max((len(f"{v}".split(".")[1].rstrip("0")) if "." in f"{v}" else 0 for v in values), default=0)
    data = {
        "chart": {"type": chart["type"], "horizontal": chart.get("horizontal")},
        "categories": chart["categories"],
        "series": chart["series"],
        "points": [],
        "unit": unit or "",
        "number": "#,##0" + ("." + "0" * min(decimals, 2) if decimals else ""),
        "docIds": [],
    }
    block = chart_block(caption or chart.get("title") or "차트", data)
    block["sourceLine"] = f"샘플: {source}"
    return block


__all__ = ["chart_preview", "table_preview"]
