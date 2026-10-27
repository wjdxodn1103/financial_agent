"""리서치 표 → 차트(에셋). 값은 표에 보인 그 숫자를 그대로 옮긴다(새로 계산하지 않는다).

차트 = ResearchTable(kind="chart"), data = {
  chart: {source, type bar|line|area|pie|combo|band, horizontal, series:[열 key], rows:[행 이름]|None, typeOf:{key: bar|line|area}, axisOf:{key: left|right}},
  sourceTitle, categories, series:[{key, name, values, type?, axis?, computed?}], points:[[점]], unit, unit2, number, period, docIds, dropped, form?
}
점 = {kind, text, fid?, docId?, chunk?, cell?} — 누르면 원 칸(원문)이 열린다.
계열은 같은 단위의 숫자·계산 열만(왼쪽 축은 첫 왼쪽 계열의 단위, 오른쪽 축(combo)은 첫 오른쪽 계열의 단위). 원 표를 다시 채우면 refresh_dependents 가 다시 만든다.
문서 양식의 차트 양식(research/forms.py)으로 만들면 종류·계열별 막대/선·축이 양식대로이고 data.form 에 겉모양(색·범례)을 둔다.
band = 첫 계열 + 그 값의 평균·±1·±2 표준편차 선(코드가 계산 — computed, 점 없음, 이름에 '계산값'). pie = 첫 계열만, 음수 없음.
"""
from __future__ import annotations

import copy
import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.db import Repo, ResearchTable
from app.docs.store import doc_label, load_meta
from app.research import entities
from app.research.block import cell_view

CHART_TYPES = ("bar", "line", "area", "pie", "combo", "band")
BAND_LINES = (("평균", 0), ("+1SD", 1), ("-1SD", -1), ("+2SD", 2), ("-2SD", -2))
_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


class ChartError(ValueError):
    pass


def _value(text: str) -> Tuple[Optional[float], int]:
    """표 칸 글자 → (숫자, 소수 자리). '10,250'·'8.5'·'8.5%' 만 — 그 밖('1조 2,000억원' 등)은 None."""
    s = (text or "").replace(",", "").strip().rstrip("%").strip()
    if not _NUM.match(s):
        return None, 0
    return float(s), len(s.split(".")[1]) if "." in s else 0


def _pick(labels: List[str], options: List[Tuple[str, str]]) -> List[str]:
    """이름(부분 일치 허용, 뒤의 '(%)'·'(억원)' 단위는 뗀다) → key. options = [(key, label)]."""
    out: List[str] = []
    for want in labels:
        w = entities.norm(re.sub(r"\s*[(\[][^()\[\]]*[)\]]\s*$", "", want))
        hit = (
            next((k for k, lab in options if entities.norm(lab) == w), None)
            or next((k for k, lab in options if w and w in entities.norm(lab)), None)
            or next((k for k, lab in options if w and entities.norm(lab) in w), None)
        )
        if hit and hit not in out:
            out.append(hit)
    return out


def derive_chart(source: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    """원 표 data + 차트 spec → 차트 data. 쓸 수 있는 열이 없으면 ChartError.
    spec.seriesLabels(+ seriesTypes·axes — 같은 순서)로 계열을 고르거나, 다시 만들 때는 저장한 series·typeOf·axisOf 를 쓴다."""
    items = [it for it in source.get("items") or [] if not it.get("hidden") and it.get("type") in ("number", "calc")]
    cols = source.get("columns") or {}
    subjects = source.get("subjects") or []
    cells = source.get("cells") or []
    ctype = spec.get("type") if spec.get("type") in CHART_TYPES else "bar"
    if not items:
        raise ChartError("숫자 열이 없는 표라 차트로 그릴 수 없습니다.")
    type_of: Dict[str, str] = dict(spec.get("typeOf") or {})
    axis_of: Dict[str, str] = dict(spec.get("axisOf") or {})
    if spec.get("seriesLabels"):
        keys: List[str] = []
        types, axes = list(spec.get("seriesTypes") or []), list(spec.get("axes") or [])
        for i, want in enumerate(spec["seriesLabels"]):
            hit = _pick([want], [(it["key"], it["label"]) for it in items if it["key"] not in keys])
            if hit:
                keys.append(hit[0])
                if i < len(types) and types[i] in ("bar", "line", "area"):
                    type_of[hit[0]] = types[i]
                if i < len(axes) and axes[i] == "right":
                    axis_of[hit[0]] = "right"
        if not keys:
            raise ChartError(f"그런 숫자 열이 없습니다({', '.join(spec['seriesLabels'])}). 이 표의 숫자 열: {', '.join(it['label'] for it in items)}")
    else:
        keys = list(spec.get("series") or [])
    keys = [k for k in keys if any(it["key"] == k for it in items)] or [it["key"] for it in items]
    if ctype != "combo":
        axis_of = {}
    left = [k for k in keys if axis_of.get(k) != "right"]
    right = [k for k in keys if axis_of.get(k) == "right"]

    def unit_of(k: str) -> str:
        return (cols.get(k) or {}).get("unit") or ""

    unit = unit_of((left or right)[0])
    unit2 = unit_of(right[0]) if left and right else ""
    kept = [k for k in left if unit_of(k) == unit] + ([k for k in right if unit_of(k) == unit2] if left else [k for k in right if unit_of(k) == unit])
    if ctype in ("pie", "band"):
        kept = kept[:1]
    dropped = [next(it["label"] for it in items if it["key"] == k) for k in keys if k not in kept]
    wanted = spec.get("rows") or None
    rows = [i for i, s in enumerate(subjects) if not wanted or any(entities.norm(w) == entities.norm(s["label"]) for w in wanted)]
    if not rows:
        raise ChartError("그릴 행이 없습니다.")
    decimals = 0
    series, points = [], []
    for k in kept:
        it = next(x for x in items if x["key"] == k)
        vals: List[Optional[float]] = []
        pts: List[Optional[Dict[str, Any]]] = []
        for i in rows:
            c = (cells[i] if i < len(cells) else {}).get(k) or {}
            v, d = _value(c.get("text") or "") if c.get("type") in ("number", "calc") else (None, 0)
            decimals = max(decimals, d)
            vals.append(v)
            pts.append({k2: v2 for k2, v2 in cell_view(c).items() if k2 in ("kind", "text", "fid", "docId", "chunk", "cell", "title") and v2 not in (None, "")} if v is not None else None)
        entry: Dict[str, Any] = {"key": k, "name": it["label"], "values": vals}
        if ctype == "combo":
            entry["type"] = type_of.get(k) or ("line" if axis_of.get(k) == "right" else "bar")
        if axis_of.get(k) == "right":
            entry["axis"] = "right"
        series.append(entry)
        points.append(pts)
    if not any(v is not None for s in series for v in s["values"]):
        raise ChartError("그릴 수 있는 숫자가 없습니다(빈 칸이거나 숫자가 아닌 칸).")
    if ctype == "pie" and any(v is not None and v < 0 for v in series[0]["values"]):
        raise ChartError("원 차트는 음수 값을 그릴 수 없습니다 — 막대 차트로 만드세요.")
    if ctype == "band":
        vals = [v for v in series[0]["values"] if v is not None]
        if len(vals) < 3:
            raise ChartError("밴드 차트는 값이 셋 이상 있어야 평균·표준편차를 계산합니다.")
        mean, sd = statistics.fmean(vals), statistics.stdev(vals)
        for name, z in BAND_LINES:
            series.append({"key": f"band{z}", "name": f"{name}(계산값)", "values": [round(mean + z * sd, max(decimals, 2))] * len(rows), "computed": True})
            points.append([None] * len(rows))
    doc_ids = list(dict.fromkeys(p["docId"] for ps in points for p in ps if p and p.get("docId")))
    for i in rows:  # 계산 칸의 근거 자료도 출처에
        for k in kept:
            doc_ids += [d for d in ((cells[i] if i < len(cells) else {}).get(k) or {}).get("docIds") or [] if d not in doc_ids]
    return {
        "chart": {
            "source": spec.get("source") or "",
            "type": ctype,
            "horizontal": bool(spec.get("horizontal")) and ctype == "bar",
            "series": kept,
            "rows": wanted,
            "typeOf": {k: v for k, v in type_of.items() if k in kept},
            "axisOf": {k: v for k, v in axis_of.items() if k in kept},
        },
        "categories": [subjects[i]["label"] for i in rows],
        "series": series,
        "points": points,
        "unit": unit,
        "unit2": unit2,
        "number": "#,##0" + ("." + "0" * min(decimals, 3) if decimals else ""),
        "period": copy.deepcopy(source.get("period")),
        "docIds": doc_ids,
        "dropped": dropped,
    }


def chart_block(title: str, data: Dict[str, Any], block_id: str = "") -> Dict[str, Any]:
    """화면·문서·내보내기의 차트 블록(formats/blocks.py 의 그림 블록과 같은 모양 + chartType·points·출처 줄)."""
    ch = data.get("chart") or {}
    period = (data.get("period") or {}).get("label") or ""
    labels = [doc_label(load_meta(d), d) for d in data.get("docIds") or []]
    return {
        "kind": "chart",
        "blockId": block_id,
        "title": title,
        "caption": f"{title} ({period} 기준)" if period and period.split("년")[0] not in title else title,
        "unit": data.get("unit") or "",
        "number": data.get("number") or "#,##0",
        "chartType": ch.get("type") or "bar",
        "horizontal": bool(ch.get("horizontal")),
        "categories": data.get("categories") or [],
        "series": [{"name": s["name"], "values": s["values"], **{k: s[k] for k in ("type", "axis", "computed") if s.get(k)}} for s in data.get("series") or []],
        "unit2": data.get("unit2") or "",
        **_form_look(data),
        "points": data.get("points") or [],
        "sourceLine": ("자료: " + ", ".join(labels)) if labels else "",
        "sourceDocIds": data.get("docIds") or [],
        "missing": False,
    }


def _form_look(data: Dict[str, Any]) -> Dict[str, Any]:
    """문서 양식의 차트 양식으로 만든 차트 — 색·눈금선·값 글자·범례 위치를 블록에(화면·Word 가 따른다)."""
    form = data.get("form") or {}
    if not form:
        return {}
    return {"look": form.get("look") or {}, "legend": (form.get("chart") or {}).get("legend") or "", "formName": form.get("name") or ""}


def asset_block(row: ResearchTable) -> Dict[str, Any]:
    """에셋 하나 → 블록(표면 표 블록, 차트면 차트 블록)."""
    from app.research.block import to_block

    if row.kind == "chart":
        return chart_block(row.title, row.data or {}, row.id)
    if row.kind == "note":
        data = row.data or {}
        return {"kind": "note", "blockId": row.id, "title": row.title, "text": data.get("text") or "", "cites": data.get("cites") or [], "missing": False}
    return to_block(row.title, row.data or {}, row.id)


def dependents(session: Session, source: ResearchTable) -> List[ResearchTable]:
    rows = session.exec(select(ResearchTable).where(ResearchTable.workspace_id == source.workspace_id, ResearchTable.kind == "chart")).all()
    return [r for r in rows if ((r.data or {}).get("chart") or {}).get("source") == source.id]


def refresh_dependents(session: Session, source: ResearchTable) -> List[str]:
    """원 표를 다시 채운 뒤 — 딸린 차트를 같은 spec 으로 다시 만든다. 그릴 수 없게 되면(열을 뺐다 등) 그대로 둔다."""
    out = []
    for r in dependents(session, source):
        try:
            new = derive_chart(source.data or {}, {**((r.data or {}).get("chart") or {})})
        except ChartError:
            continue
        if (r.data or {}).get("form"):
            new["form"] = r.data["form"]
        r.data = new
        Repo(session).save(r)
        out.append(r.id)
    return out


__all__ = ["CHART_TYPES", "ChartError", "asset_block", "chart_block", "derive_chart", "dependents", "refresh_dependents"]
