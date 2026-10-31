"""샘플 표·차트 → 표 양식 spec(research/templates.normalize_spec 모양).

표: LLM 이 행 종류(기업·기간·문서·항목)·방향·열 종류(숫자·글·계산)·단위·고정 행을 고르고, 코드가 검증한다.
    계산식이 틀리면 계산 열을 숫자 열로 바꿔 한 번 더, 그래도 안 되거나 LLM 이 실패하면 규칙(rule_spec)으로.
차트: 범주 = 행, 계열 = 숫자 열 — 규칙으로 만들고 chart{type, horizontal, seriesLabels} 를 붙인다.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.llm.base import ChatParams
from app.research.templates import SUBJECT_KINDS, SpecError, normalize_spec

logger = logging.getLogger(__name__)
PERIOD = re.compile(
    r"^(?:FY\s*)?'?\d{2,4}\s*(?:년|Y|E|F|A|P)?(?:\s*[1-4]\s*(?:Q|분기))?$|^[1-4]\s*Q\s*'?\d{2,4}$|^\d{4}[./-]\d{1,2}$|^\d{2,4}\s*년?\s*(?:상|하)반기$|^\d{4}\s*년\s*\d{1,2}\s*월$",
    re.I,
)
_NUM = re.compile(r"^[-+(]?\s*[\d,]+(?:\.\d+)?\s*%?\)?$")
_UNIT_SUFFIX = re.compile(r"\s*[(\[]\s*([^()\[\]]{1,12})\s*[)\]]\s*$")
_PCT = re.compile(r"(률|율|비율|비중|%)$")

SYSTEM = """너는 보고서 표를 '다시 채울 수 있는 표 양식'으로 바꾸는 보조다. 주어진 표(캡션·머리 줄·앞 몇 행)를 보고 JSON 하나만 답한다.
- subject_kind: 행(채울 대상)이 무엇인가 — company(기업), period(연도·분기·월), document(문서), label(그 밖 늘 같은 항목)
- orientation: 대상(기업·기간)이 표의 열(가로)로 놓였으면 items_as_rows, 행(세로)으로 놓였으면 subjects_as_rows
- items: 지표 목록 [{"label","type","unit","formula"}] — type 은 number(자료의 수치)·text(짧은 글)·calc(다른 숫자 지표로 계산). calc 의 formula 는 ratio(a, b)·growth(새, 옛)·diff(a, b) 이고 a·b 는 앞쪽 지표 label. 이익률·증가율이 같은 표의 다른 지표로 계산되면 calc. label 에서 '(%)'·'(억원)' 같은 단위는 빼고 unit 에 둔다.
- fixed_rows: 행이 늘 같은 항목이면(체크리스트·고정 계정과목) 그 이름 목록, 기업·기간처럼 매번 바뀌면 null
- name: 짧은 양식 이름(캡션에서 연도·기업 이름은 뺀다)
JSON 만: {"name":"","subject_kind":"","subject_label":"","orientation":"","items":[],"fixed_rows":null}"""


def _split_unit(label: str) -> Tuple[str, Optional[str]]:
    m = _UNIT_SUFFIX.search(label or "")
    return (label[: m.start()].strip(), m.group(1).strip()) if m else ((label or "").strip(), None)


def _numeric(cells: List[str]) -> bool:
    vals = [c for c in cells if c.strip() and c.strip() not in ("-", "–", "—")]
    return bool(vals) and sum(1 for c in vals if _NUM.match(c.strip())) >= len(vals) * 0.6


def _mostly(cells: List[str], rx: re.Pattern) -> bool:
    vals = [c.strip() for c in cells if c.strip()]
    return bool(vals) and sum(1 for c in vals if rx.match(c)) >= max(1, len(vals) * 2 // 3)


def _item(label: str, values: List[str], unit: Optional[str]) -> Dict[str, Any]:
    name, own = _split_unit(label)
    numeric = _numeric(values)
    it: Dict[str, Any] = {"label": name or label, "type": "number" if numeric else "text"}
    u = own or ("%" if numeric and _PCT.search(name) else unit if numeric else None)
    if u:
        it["unit"] = u
    if numeric:
        it["metric"] = name or label
    return it


def rule_spec(rows: List[List[str]], caption: str, unit: Optional[str]) -> Dict[str, Any]:
    """LLM 없이 — 머리 줄이 기간이면 '기간 × 지표(지표가 행)', 첫 열이 기간이면 '기간이 행', 아니면 첫 열 = 기업(글자) 또는 항목."""
    header, body = rows[0], rows[1:]
    first_col = [r[0] for r in body]
    if _mostly(header[1:], PERIOD):
        items = [_item(r[0], r[1:], unit) for r in body if r and r[0].strip()]
        raw = {"subject": {"kind": "period", "label": "기간"}, "items": items, "orientation": "items_as_rows"}
    else:
        kind = "period" if _mostly(first_col, PERIOD) else "company" if not any(re.search(r"\d", c) for c in first_col) else "label"
        items = [_item(h, [r[j] if j < len(r) else "" for r in body], unit) for j, h in enumerate(header) if j > 0 and h.strip()]
        raw = {"subject": {"kind": kind, "label": header[0].strip()[:20] or SUBJECT_KINDS[kind]}, "items": items, "orientation": "subjects_as_rows"}
    raw["name"] = caption or "표"
    return normalize_spec(raw)


def _from_llm(ans: Dict[str, Any], caption: str, unit: Optional[str]) -> Dict[str, Any]:
    kind = ans.get("subject_kind") if ans.get("subject_kind") in SUBJECT_KINDS else "company"
    items = []
    for it in ans.get("items") or []:
        if not isinstance(it, dict) or not str(it.get("label") or "").strip():
            continue
        label, own = _split_unit(str(it["label"]))
        x: Dict[str, Any] = {"label": label, "type": it.get("type") if it.get("type") in ("number", "text", "calc") else "number"}
        u = str(it.get("unit") or own or "").strip() or None
        if x["type"] == "number":
            x["metric"] = label
            u = u or ("%" if _PCT.search(label) else unit)
        if u and x["type"] != "text":
            x["unit"] = u
        if x["type"] == "calc":
            x["formula"] = str(it.get("formula") or "")
            x["decimals"] = 1
        items.append(x)
    fixed = ans.get("fixed_rows")
    raw = {
        "name": str(ans.get("name") or caption or "표"),
        "subject": {"kind": kind, "label": str(ans.get("subject_label") or SUBJECT_KINDS[kind])},
        "orientation": ans.get("orientation"),
        "items": items,
        "rows": [str(r) for r in fixed if str(r).strip()] if isinstance(fixed, list) and fixed else None,
    }
    try:
        return normalize_spec(raw)
    except SpecError:
        # 계산식이 틀렸으면 계산 열을 숫자 열로(자료에서 그 값을 찾는다)
        raw["items"] = [{**x, "type": "number", "metric": x["label"], "formula": None} if x["type"] == "calc" else x for x in items]
        return normalize_spec(raw)


def _json(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", text or "")
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


async def table_to_spec(llm: Any, rows: List[List[str]], caption: str, unit: Optional[str]) -> Tuple[Dict[str, Any], str]:
    """→ (spec, via llm|rule)."""
    shown = "\n".join(" | ".join(r) for r in rows[:5])
    user = f"캡션: {caption or '(없음)'}\n단위: {unit or '(없음)'}\n표:\n{shown}"
    if llm is not None:
        try:
            # 추론 모델 — 출력 상한이 작으면 생각만 하다 빈 답을 낸다(fill.py 와 같은 2500). 빈 답이면 한 번 더
            params = ChatParams(messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], temperature=0.1, max_tokens=2500, timeout_s=60)
            for _try in range(2):
                out = await llm.complete("chat", params)
                ans = _json(getattr(out, "content", None) or "")
                if ans:
                    return _from_llm(ans, caption, unit), "llm"
        except SpecError as e:
            logger.info("import spec rejected (%s) — rule", e)
        except Exception:  # noqa: BLE001 — LLM 오류는 규칙으로
            logger.exception("import spec llm failed — rule")
    return rule_spec(rows, caption, unit), "rule"


def chart_rows(chart: Dict[str, Any]) -> List[List[str]]:
    """차트 → 표 칸(범주 = 행, 계열 = 열) — 규칙 spec 과 미리보기가 같이 쓴다."""
    def cell(v: Optional[float]) -> str:
        return "" if v is None else (f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}".rstrip("0").rstrip("."))

    return [["", *[s["name"] for s in chart["series"]]], *[[cat, *[cell(s["values"][i]) for s in chart["series"]]] for i, cat in enumerate(chart["categories"])]]


def chart_to_spec(chart: Dict[str, Any], caption: str, unit: Optional[str]) -> Dict[str, Any]:
    spec = rule_spec(chart_rows(chart), caption, unit)
    spec["chart"] = {"type": chart["type"], "horizontal": bool(chart.get("horizontal")), "seriesLabels": [it["label"] for it in spec["items"] if not it.get("hidden")]}
    return spec


__all__ = ["chart_rows", "chart_to_spec", "rule_spec", "table_to_spec"]
