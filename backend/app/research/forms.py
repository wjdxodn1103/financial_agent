"""문서 양식의 표·차트 양식(templates_import/forms.py 의 에셋)으로 AI 작업의 표·차트를 만든다 — 형식은 양식, 값은 자료에서.

 - 표 양식 → 채울 표(form_table_spec): 행 = 대상(사용자·AI 가 정함), 열 = 양식의 열. 묶음 머리 아래 열은 지표 이름에 묶음을 붙여
   찾는다('투자수익률 1주'). 이름·설명 열(운용사·티커·투자의견…)은 글 열. 값은 fill.fill_table 이 원장·문단에서(못 찾으면 빈 칸).
 - 자료 속 표 → 양식 모양(map_columns + doc_tables.build_from_doc(col_map)): 양식 열을 원 표 열에 잇는다 — 이름이 같으면 코드로,
   남은 것은 LLM 한 번(열 번호만 고른다). 칸은 원문 칸 그대로(원장 수치로 이어짐), 못 잇는 열은 빈 칸.
 - 열이 전부 기간인 표 양식(재무표 — 행 = 계정, 열 = 2022·2023·2025F)(period_columns·form_period_table): 행 = 기간·열 = 계정으로
   채우고(대상 기업으로 찾는다) 보일 때만 뒤집는다(items_as_rows). 샘플의 연도는 내용이라 실적 열의 마지막을 자료의 최근 연도로 옮긴다(shift_years).
 - 차트 양식(chart_body): 원 표(채운 표·꺼낸 표)의 숫자 열을 양식 계열에 잇고(이름, 안 되면 순서) 종류·축은 양식대로.
   표 없이 차트 양식만 쓰면 계열을 열로 한 표를 먼저 채운다(form_chart_table_spec — 가로축이 날짜·기간이면 행 = 기간).
data["form"] = form_meta(...) — 화면·Word 가 양식 모양(2단 머리·색·선·차트 색·범례)으로 그린다(block.to_block·chart.chart_block).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.ledger.figures import period_key
from app.llm.base import ChatParams
from app.research.entities import norm
from app.research.templates import MAX_ITEMS, SUBJECT_KINDS, normalize_items, normalize_spec
from app.templates_import.forms import split_unit

logger = logging.getLogger(__name__)

CHART_LABEL = {"line": "선", "bar": "막대", "barh": "가로 막대", "area": "영역", "pie": "원", "combo": "막대+선", "band": "밴드", "other": "차트"}
_TEXT_COL = re.compile(r"운용사|이름|명$|종목|티커|ticker|의견|설명|비고|업종|섹터|sector|국가|등급|코드", re.I)
_PERIOD_ROW = re.compile(r"기간|연도|년도|월|분기|일자|날짜|date|period|year|month", re.I)
_COMPANY_ROW = re.compile(r"기업|회사|company|firm", re.I)


def format_assets(session: Any, type_id: Optional[str]) -> List[Dict[str, Any]]:
    """작업 문서의 양식(rt:…)에 든 표·차트 양식. 기본 양식·양식 없는 작업은 빈 목록."""
    from app.agent.template import REGISTERED
    from app.db import ReportTemplate

    if not type_id or not type_id.startswith(REGISTERED):
        return []
    row = session.get(ReportTemplate, type_id[len(REGISTERED):])
    return list((row.spec or {}).get("assets") or []) if row is not None else []


def _grouped(g: Dict[str, Any]) -> bool:
    return bool(g.get("label")) and g.get("columns") != [g.get("label")]


def _cols_text(t: Dict[str, Any]) -> str:
    parts = []
    for g in t.get("groups") or []:
        unit = f"({g['unit']})" if g.get("unit") else ""
        parts.append(f"{g['label']}{unit}: {'·'.join(g['columns'])}" if _grouped(g) else f"{g['columns'][0]}{unit}")
    return " / ".join(parts)


def form_line(i: int, a: Dict[str, Any]) -> str:
    """프롬프트 한 줄 — 별칭 F번호 · 이름 · 모양."""
    if a["kind"] == "table":
        t = a.get("table") or {}
        return f"- F{i + 1} {a['name']} — 표 · 행: {t.get('stub') or t.get('rowKind') or '항목'} · 열: {_cols_text(t)}"
    c = a.get("chart") or {}
    x = {"date": "날짜", "period": "기간"}.get(c.get("x"), "항목")
    series = ", ".join(f"{s['name']}{'(오른쪽 축)' if s.get('axis') == 'right' else ''}" for s in c.get("series") or []) or a["name"]
    units = " / ".join(u for u in (c.get("unit"), c.get("unit2")) if u)
    return f"- F{i + 1} {a['name']} — {CHART_LABEL.get(c.get('type'), '차트')} 차트 · 가로축: {x} · 계열: {series}" + (f" · 단위 {units}" if units else "")


def match_form(assets: List[Dict[str, Any]], ref: str) -> Optional[Dict[str, Any]]:
    """'F2'·에셋 id(a5)·이름(같음 → 담김)으로 양식 하나."""
    ref = (ref or "").strip()
    if not ref:
        return None
    m = re.fullmatch(r"[Ff]\s*(\d+)", ref)
    if m and 0 < int(m.group(1)) <= len(assets):
        return assets[int(m.group(1)) - 1]
    key = norm(ref)
    return next((a for a in assets if a["id"] == ref), None) or next((a for a in assets if norm(a["name"]) == key), None) or next((a for a in assets if key and (key in norm(a["name"]) or norm(a["name"]) in key)), None)


def form_table_spec(asset: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """표 양식 → (채울 표 spec, 머리 묶음 [{label, unit, keys}]). 열은 MAX_ITEMS 까지."""
    t = asset.get("table") or {}
    row_text = f"{t.get('rowKind') or ''} {t.get('stub') or ''}"
    kind = "period" if _PERIOD_ROW.search(row_text) else "company" if _COMPANY_ROW.search(row_text) else "label"
    raw: List[Dict[str, Any]] = []
    sizes: List[Tuple[Dict[str, Any], int]] = []
    for g in t.get("groups") or []:
        n = 0
        for col in g.get("columns") or []:
            if len(raw) >= MAX_ITEMS:
                break
            label, unit = (col, g.get("unit") or "") if _grouped(g) else split_unit(col, g.get("unit") or "")  # '자사 비중(%)' → 이름·단위
            if _TEXT_COL.search(label):
                raw.append({"label": label, "type": "text"})
            else:
                raw.append({"label": label, "type": "number", "metric": f"{g['label']} {label}" if _grouped(g) else label, **({"unit": unit} if unit else {})})
            n += 1
        sizes.append((g, n))
    spec = normalize_spec({"name": asset["name"], "subject": {"kind": kind, "label": (t.get("stub") or t.get("rowKind") or SUBJECT_KINDS[kind])[:20]}, "items": raw})
    keys = [it["key"] for it in spec["items"]]
    groups, k = [], 0
    for g, n in sizes:
        if n:
            groups.append({"label": g["label"] if _grouped(g) else "", "unit": g.get("unit") or "", "keys": keys[k : k + n]})
            k += n
    return spec, groups


_PERIOD_KEY = re.compile(r"^\d{4}(?:E|Q[1-4]|H[12]|M9)?$")
_YEAR_COL = re.compile(r"^((?:19|20)\d{2})(\s*\(?[AEFP]\)?)?$", re.I)


def period_columns(asset: Dict[str, Any]) -> List[str]:
    """표 양식의 열이 전부 기간(2022·2025F·1Q26·2024H1)이면 그 열 — 행 = 계정·지표인 재무표 양식. 아니면 빈 목록."""
    if asset.get("kind") != "table":
        return []
    cols = [str(c).strip() for g in (asset.get("table") or {}).get("groups") or [] for c in g.get("columns") or []]
    if len(cols) < 2 or not all(_PERIOD_KEY.match(period_key(c)) for c in cols):
        return []
    return cols


def shift_years(cols: List[str], last_actual: Optional[int]) -> List[str]:
    """샘플 연도는 그 호의 내용 — 실적 열(F·E 없는 연도)의 마지막이 last_actual 이 되게 연도만 옮긴다
    (2022·2023·2024·2025F·2026F, 2025 → 2023·2024·2025·2026F·2027F). 연도 열이 아니거나 실적 열이 없으면 그대로."""
    ms = [_YEAR_COL.match(c) for c in cols]
    if not last_actual or not all(ms):
        return cols
    actual = [int(m.group(1)) for m in ms if m and not (m.group(2) or "").strip()]
    if not actual:
        return cols
    d = last_actual - max(actual)
    return [f"{int(m.group(1)) + d}{(m.group(2) or '').strip()}" for m in ms if m]


def form_period_table(asset: Dict[str, Any], rows: List[str], cols: List[str]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """열이 기간인 표 양식 + 행(계정) → (spec, subjects = 기간, items = 계정). 저장은 '행 = 기간'(채우기가 기간마다 대상 기업으로 찾는다),
    보일 때는 items_as_rows 로 뒤집어 양식처럼 행 = 계정·열 = 기간. 단위는 양식 머리의 '(억원)'."""
    t = asset.get("table") or {}
    unit = re.sub(r"^\s*[(\[]?\s*(?:단위\s*[:：]\s*)?|\s*[)\]]?\s*$", "", str(((t.get("groups") or [{}])[0]).get("unit") or ""))
    items = normalize_items([{"label": r, "type": "number", "metric": r, **({"unit": unit} if unit else {})} for r in rows][: MAX_ITEMS * 2])
    spec = normalize_spec({"name": asset["name"], "subject": {"kind": "period", "label": "기간"}, "items": items[:MAX_ITEMS], "orientation": "items_as_rows"})
    return spec, [{"label": c} for c in cols], items


def form_chart_table_spec(asset: Dict[str, Any]) -> Dict[str, Any]:
    """차트 양식만 쓸 때 먼저 채울 표 — 열 = 계열(이름·단위), 행 = 기간(가로축이 날짜·기간) 또는 항목."""
    c = asset.get("chart") or {}
    kind = "period" if c.get("x") in ("date", "period") else "label"
    raw = []
    for s in (c.get("series") or [])[:MAX_ITEMS]:
        unit = c.get("unit2") if s.get("axis") == "right" else c.get("unit")
        raw.append({"label": s["name"], "type": "number", "metric": s["name"], **({"unit": unit} if unit else {})})
    if not raw:
        raw = [{"label": asset["name"], "type": "number", **({"unit": c["unit"]} if c.get("unit") else {})}]
    return normalize_spec({"name": asset["name"], "subject": {"kind": kind, "label": "기간" if kind == "period" else "항목"}, "items": raw})


def form_meta(asset: Dict[str, Any], format_id: str, groups: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """표·차트 data 에 붙이는 양식 정보 — 화면·Word 가 이 모양으로 그린다."""
    return {
        "formatId": format_id or "",
        "assetId": asset["id"],
        "name": asset["name"],
        "kind": asset["kind"],
        "groups": groups or [],
        "look": dict(asset.get("look") or {}),
        "caption": dict(asset.get("caption") or {}),
        "chart": dict(asset.get("chart") or {}) if asset.get("chart") else None,
    }


def header_names(rows: List[List[str]]) -> List[str]:
    """원 표 머리 — 둘째 줄이 머리의 이어짐(첫 칸이 비었다)이면 위아래를 붙인다('투자수익률 (%) 1주')."""
    head = list(rows[0]) if rows else []
    if len(rows) > 1 and rows[1] and not rows[1][0].strip():
        last = ""
        for j in range(len(head)):
            top = head[j].strip() or (last if j > 0 else "")
            last = top or last
            low = rows[1][j].strip() if j < len(rows[1]) else ""
            head[j] = f"{top} {low}".strip() if low and low != top else top
    return head


async def map_columns(items: List[Dict[str, Any]], rows: List[List[str]], llm: Any) -> Dict[str, int]:
    """양식 열(key) → 원 표 열 번호. 이름이 같으면 코드로, 남은 것은 LLM 한 번(못 고르면 비운다)."""
    from app.research.doc_tables import label_key

    head = header_names(rows)
    by_name = {label_key(h): j for j, h in enumerate(head) if j > 0 and h.strip()}
    out: Dict[str, int] = {}
    for it in items:
        for name in (it["label"], it.get("metric") or ""):
            j = by_name.get(label_key(name))
            if j is not None and j not in out.values():
                out[it["key"]] = j
                break
    rest = [it for it in items if it["key"] not in out and not it.get("hidden")]
    if not rest or llm is None:
        return out
    body = next((r for r in rows[1:] if r and r[0].strip()), [])
    lines = [f"{j}: {h}" + (f" — 예: {body[j]}" if j < len(body) and body[j].strip() else "") for j, h in enumerate(head) if j > 0 and h.strip() and j not in out.values()]
    want = [f"{it['key']}: {it['label']}" + (f" (지표: {it['metric']})" if it.get("metric") and it["metric"] != it["label"] else "") + (f" [{it['unit']}]" if it.get("unit") else "") for it in rest]
    prompt = (
        "보고서 양식 표의 열을 원 표(자료 속 표)의 열에 잇는다. 같은 뜻(같은 기간·같은 지표)인 원 표 열 번호만 고르고, 없으면 null.\n"
        "JSON 하나로만 답한다(설명 없이): {\"양식 열 key\": 원 표 열 번호 또는 null}\n\n"
        "양식 열:\n" + "\n".join(want) + "\n\n원 표 열(번호: 머리 — 첫 행 값):\n" + "\n".join(lines)
    )
    try:
        res = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": prompt}], temperature=0, max_tokens=2000, timeout_s=90, reasoning_effort="low"))
        m = re.search(r"\{[\s\S]*\}", getattr(res, "content", "") or "")
        got = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001 — 이름으로 이은 것만 쓴다
        logger.exception("form column mapping failed")
        got = {}
    free = {j for j in range(1, len(head)) if j not in out.values()}
    for it in rest:
        v = got.get(it["key"]) if isinstance(got, dict) else None
        if isinstance(v, int) and v in free:
            out[it["key"]] = v
            free.discard(v)
    return out


def chart_body(asset: Dict[str, Any], source: Dict[str, Any], title: str) -> Dict[str, Any]:
    """차트 양식 + 원 표 data → ResearchService.make_chart 의 body. 계열은 양식 계열 이름으로 원 표 숫자 열을 찾고, 하나도 안 맞으면 숫자 열을 순서대로."""
    from app.research.chart import _pick

    c = asset.get("chart") or {}
    nums = [it for it in source.get("items") or [] if not it.get("hidden") and it.get("type") in ("number", "calc")]
    want = list(c.get("series") or [])
    labels, types, axes = [], [], []
    used: set = set()
    for s in want:
        hit = _pick([s["name"]], [(it["key"], it["label"]) for it in nums if it["key"] not in used])
        if hit:
            used.add(hit[0])
            labels.append(next(it["label"] for it in nums if it["key"] == hit[0]))
            types.append(s.get("type") or "line")
            axes.append(s.get("axis") or "left")
    if not labels:  # 이름이 안 맞으면 순서대로(계열이 없던 양식이면 숫자 열 전부)
        for i, it in enumerate(nums[: max(1, len(want)) if want else len(nums)]):
            s = want[i] if i < len(want) else {}
            labels.append(it["label"])
            types.append(s.get("type") or ("bar" if c.get("type") in ("bar", "barh") else "line"))
            axes.append(s.get("axis") or "left")
    ctype = c.get("type") or "bar"
    return {
        "type": "bar" if ctype in ("barh", "other") else ctype,
        "horizontal": ctype == "barh",
        "series": labels,
        "seriesTypes": types,
        "axes": axes,
        "title": title,
    }


__all__ = ["CHART_LABEL", "chart_body", "form_chart_table_spec", "form_line", "form_meta", "form_period_table", "form_table_spec", "format_assets", "header_names", "map_columns", "match_form", "period_columns", "shift_years"]
