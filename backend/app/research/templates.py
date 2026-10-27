"""표 양식 — 무엇을(열 = items) 누구에 대해(행 = subject) 채울지. 열만 고정하면 행은 매번 정하고, 행까지 고정하면 그대로 다시 채운다.

spec = {
  name, desc,
  subject: {kind: company | document | period | label, label: "기업"},
  rows: null | [{label, docId?}],      # null = 행은 매번 정함
  items: [{key, label, type: number | text | calc, metric?, unit?, decimals?, periodOffset?, instruction?, formula?, hidden?}],
  itemsOpen: bool,                     # true = 열도 매번 정함(질문 표 — 열 = 질문)
  orientation: subjects_as_rows | items_as_rows,
  inputs: [{key: period | basis, label, default}],
  chart?: {type: bar | line, horizontal, seriesLabels}   # 차트 양식(샘플의 차트에서 등록) — 표를 채운 뒤 차트를 만든다
}
number = 자료의 수치(원장 칸으로 연결), text = 자료 근거가 있는 짧은 답(인용), calc = 같은 행 칸으로 코드가 계산(ratio·growth·diff·cagr).
periodOffset = 전년 같은 기간(-1)처럼 기준 기간에서 몇 해 앞. hidden = 계산에만 쓰고 표에는 안 보이는 열.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional

from app.ledger.calc import FUNCS, refs_in

SUBJECT_KINDS = {"company": "기업", "document": "문서", "period": "기간", "label": "항목"}
ITEM_TYPES = ("number", "text", "calc")
ORIENTATIONS = ("subjects_as_rows", "items_as_rows")
INPUT_KEYS = {"period": "기준 기간", "basis": "기준"}
MAX_ROWS = 12
MAX_ITEMS = 10
_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,15}$")

BUILTIN: Dict[str, Dict[str, Any]] = {
    "builtin_peer": {
        "name": "Peer 비교표",
        "desc": "기업별 매출·이익·이익률·성장률",
        "subject": {"kind": "company", "label": "기업"},
        "rows": None,
        "items": [
            {"key": "rev", "label": "매출액", "type": "number", "metric": "매출액"},
            {"key": "rev_p", "label": "매출액(전년)", "type": "number", "metric": "매출액", "periodOffset": -1, "hidden": True},
            {"key": "rev_g", "label": "매출 증가율", "type": "calc", "formula": "growth(rev, rev_p)", "unit": "%", "decimals": 1},
            {"key": "op", "label": "영업이익", "type": "number", "metric": "영업이익"},
            {"key": "opm", "label": "영업이익률", "type": "calc", "formula": "ratio(op, rev)", "unit": "%", "decimals": 1},
            {"key": "ni", "label": "당기순이익", "type": "number", "metric": "당기순이익"},
        ],
        "itemsOpen": False,
        "orientation": "subjects_as_rows",
        "inputs": [{"key": "period", "label": "기준 기간", "default": ""}, {"key": "basis", "label": "기준", "default": ""}],
    },
    "builtin_qtable": {
        "name": "질문 표",
        "desc": "여러 문서를 같은 질문으로 — 칸마다 인용",
        "subject": {"kind": "document", "label": "문서"},
        "rows": None,
        "items": [],
        "itemsOpen": True,
        "orientation": "subjects_as_rows",
        "inputs": [],
    },
}


class SpecError(ValueError):
    pass


def builtin(template_id: str) -> Optional[Dict[str, Any]]:
    spec = BUILTIN.get(template_id)
    return copy.deepcopy(spec) if spec else None


def builtin_views() -> List[Dict[str, Any]]:
    return [{"id": k, "scope": "company", "builtin": True, "name": v["name"], "spec": copy.deepcopy(v)} for k, v in BUILTIN.items()]


def _int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _formula(raw: str, items: List[Dict[str, Any]]) -> str:
    """식 속 열 이름(영업이익 …)을 열 key 로 바꾼다 — 채팅에서 이름으로 써도 받는다."""
    out = str(raw or "").strip()
    for it in sorted(items, key=lambda x: len(x["label"]), reverse=True):
        if it["label"] and it["label"] != it["key"]:
            out = out.replace(it["label"], it["key"])
    return out


def normalize_items(raw_items: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen: set = set()
    for i, raw in enumerate(raw_items or []):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("name") or "").strip()[:40]
        if not label:
            continue
        typ = raw.get("type") if raw.get("type") in ITEM_TYPES else ("calc" if raw.get("formula") else "number" if raw.get("metric") else "text")
        key = str(raw.get("key") or "").strip()
        if not _KEY.match(key) or key in seen or key in FUNCS:
            key = f"c{i + 1}"
            while key in seen:
                key += "_"
        seen.add(key)
        it: Dict[str, Any] = {"key": key, "label": label, "type": typ}
        if typ == "number":
            it["metric"] = str(raw.get("metric") or label).strip()[:40]
            off = _int(raw.get("periodOffset"), -5, 0, 0)
            if off:
                it["periodOffset"] = off
        if raw.get("unit"):
            it["unit"] = str(raw["unit"]).strip()[:12]
        if raw.get("decimals") is not None:
            it["decimals"] = _int(raw.get("decimals"), 0, 4, 0)
        if raw.get("instruction"):
            it["instruction"] = str(raw["instruction"]).strip()[:300]
        if typ == "calc":
            it["formula"] = str(raw.get("formula") or "")
        if raw.get("hidden"):
            it["hidden"] = True
        items.append(it)
    for it in items:
        if it["type"] != "calc":
            continue
        it["formula"] = _formula(it["formula"], items)
        before = [x["key"] for x in items[: items.index(it)] if x["type"] in ("number", "calc")]
        refs = refs_in(it["formula"])
        if not refs or any(r not in before for r in refs):
            raise SpecError(f"'{it['label']}' 계산식은 앞쪽 숫자 열만 쓸 수 있습니다: {it['formula'] or '(비어 있음)'}")
    if len([x for x in items if not x.get("hidden")]) > MAX_ITEMS:
        raise SpecError(f"열은 {MAX_ITEMS}개까지입니다.")
    return items


def normalize_spec(raw: Dict[str, Any]) -> Dict[str, Any]:
    """채팅·화면이 보낸 양식 → 저장할 spec. 잘못된 것은 SpecError(사용자에게 그대로 보여 줄 문장)."""
    if not isinstance(raw, dict):
        raise SpecError("양식 형식이 아닙니다.")
    subj = raw.get("subject") or {}
    kind = subj.get("kind") if isinstance(subj, dict) and subj.get("kind") in SUBJECT_KINDS else "company"
    items_open = bool(raw.get("itemsOpen"))
    items = normalize_items(raw.get("items"))
    if not items and not items_open:
        raise SpecError("열을 하나 이상 정해 주세요.")
    rows = raw.get("rows")
    if isinstance(rows, list):
        rows = [{"label": str(r.get("label") if isinstance(r, dict) else r).strip()[:60], **({"docId": r["docId"]} if isinstance(r, dict) and r.get("docId") else {})} for r in rows]
        rows = [r for r in rows if r["label"]][:MAX_ROWS] or None
    else:
        rows = None
    inputs = []
    for inp in raw.get("inputs") or []:
        if isinstance(inp, dict) and inp.get("key") in INPUT_KEYS:
            inputs.append({"key": inp["key"], "label": INPUT_KEYS[inp["key"]], "default": str(inp.get("default") or "")[:20]})
    if any(it["type"] == "number" for it in items) and not any(i["key"] == "period" for i in inputs):
        inputs.insert(0, {"key": "period", "label": INPUT_KEYS["period"], "default": ""})
    chart = raw.get("chart")
    return {
        **(
            # 차트 양식 — 표를 채운 뒤 이 차트를 만든다(값은 표에 보인 숫자)
            {"chart": {"type": chart.get("type") if chart.get("type") in ("bar", "line") else "bar", "horizontal": bool(chart.get("horizontal")), "seriesLabels": [str(x).strip()[:40] for x in chart.get("seriesLabels") or [] if str(x).strip()][:MAX_ITEMS]}}
            if isinstance(chart, dict)
            else {}
        ),
        "name": str(raw.get("name") or "").strip()[:60] or "표",
        "desc": str(raw.get("desc") or "").strip()[:120],
        "subject": {"kind": kind, "label": str((subj or {}).get("label") or SUBJECT_KINDS[kind]).strip()[:20] if isinstance(subj, dict) else SUBJECT_KINDS[kind]},
        "rows": rows,
        "items": items,
        "itemsOpen": items_open,
        "orientation": raw.get("orientation") if raw.get("orientation") in ORIENTATIONS else "subjects_as_rows",
        "inputs": inputs,
    }


def spec_from_table(data: Dict[str, Any], name: str, keep_rows: bool) -> Dict[str, Any]:
    """만든 표 → 양식. 열은 지금 표의 열(질문 표면 질문까지 고정), 행은 keep_rows 일 때만."""
    spec = copy.deepcopy(data.get("spec") or {})
    spec["items"] = copy.deepcopy(data.get("items") or spec.get("items") or [])
    spec["itemsOpen"] = False
    spec["name"] = name or spec.get("name") or "표"
    spec["rows"] = [{k: v for k, v in s.items() if k in ("label", "docId")} for s in data.get("subjects") or []] if keep_rows else None
    return normalize_spec(spec)
