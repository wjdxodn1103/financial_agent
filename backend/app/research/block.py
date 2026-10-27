"""리서치 표 → 화면·문서·내보내기가 쓰는 표 블록(formats/blocks.py 의 표 블록과 같은 모양 + 칸별 docId·인용).

블록 = {kind: "table", blockId, title, caption, unit, header, rows: [[cell]], sourceLine, sourceDocIds, missing, headGroups?, look?}
문서 양식의 표 양식으로 만든 표(data.form — research/forms.py)는 머리 묶음 줄(headGroups = 첫 열 뒤 [{label, span}])과 겉모양(look)을 싣는다 —
묶음 아래 열 머리는 단위 없이(단위는 묶음 머리에).
칸 = {text, num, fid?, docId?, chunk?, cell?, cites?, title?(툴팁), kind}
행·열 뒤집기(orientation = items_as_rows)는 여기서만 한다 — 저장한 data 는 늘 '행 = subject'.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.docs.store import doc_label, load_meta
from app.ids import id36, now_iso
from app.research.fill import used_doc_ids


def _header(item: Dict[str, Any], cols: Dict[str, Dict[str, Any]]) -> str:
    unit = (cols.get(item["key"]) or {}).get("unit") or ""
    return f"{item['label']} ({unit})" if unit else item["label"]


def _form_header(item: Dict[str, Any], cols: Dict[str, Dict[str, Any]], under: Dict[str, Any]) -> str:
    """양식 표의 열 머리 — 묶음 아래 열은 이름만(단위는 묶음 머리에), 칸이 단위를 몰라도 양식의 단위를 붙인다."""
    if item["key"] in under:
        return item["label"]
    if not (cols.get(item["key"]) or {}).get("unit") and item.get("unit"):
        return f"{item['label']} ({item['unit']})"
    return _header(item, cols)


def _tip(c: Dict[str, Any]) -> str:
    t = c.get("type")
    if t == "empty":
        return c.get("reason") or ""
    if t == "calc":
        return c.get("readable") or ""
    if t == "number":
        where = f"p.{c['page']}" if c.get("page") else ""
        parts = [c.get("docLabel") or "", where, f"{c.get('metric') or ''} {c.get('period') or ''}".strip(), c.get("display") or ""]
        tip = " · ".join(p for p in parts if p)
        alts = c.get("alts") or []
        if alts:
            tip += " / 다른 자료: " + ", ".join(f"{a.get('display')} ({a.get('docLabel')})" for a in alts)
        return tip
    return ""


def cell_view(c: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    c = c or {"type": "empty"}
    t = c.get("type")
    out: Dict[str, Any] = {"kind": t, "text": c.get("text") or ("" if t == "empty" else c.get("display") or ""), "num": t in ("number", "calc"), "title": _tip(c)}
    if t == "number":
        out.update({"fid": c.get("fid"), "docId": c.get("docId"), "chunk": c.get("chunk"), "cell": c.get("cell")})
    elif t == "text":
        out["cites"] = c.get("cites") or []
        first = (c.get("cites") or [{}])[0]
        out.update({"docId": first.get("docId"), "chunk": first.get("chunk")})
    elif t == "calc":
        out["inputs"] = c.get("inputs") or []
    return out


def to_block(title: str, data: Dict[str, Any], block_id: str = "") -> Dict[str, Any]:
    spec = data.get("spec") or {}
    subj_label = (spec.get("subject") or {}).get("label") or "항목"
    items = [it for it in data.get("items") or [] if not it.get("hidden")]
    cols = data.get("columns") or {}
    subjects = data.get("subjects") or []
    cells = data.get("cells") or []
    period = (data.get("period") or {}).get("label") or ""
    form = data.get("form") or {}
    under = {k: g for g in form.get("groups") or [] if g.get("label") for k in g.get("keys") or []}
    if spec.get("orientation") == "items_as_rows":
        header = ["", *[s["label"] for s in subjects]]
        rows = [[{"kind": "head", "text": _header(it, cols), "num": False}, *[cell_view((cells[j] if j < len(cells) else {}).get(it["key"])) for j in range(len(subjects))]] for it in items]
    else:
        header = [subj_label, *[_form_header(it, cols, under) if form else _header(it, cols) for it in items]]
        rows = [[{"kind": "head", "text": s["label"], "num": False}, *[cell_view((cells[i] if i < len(cells) else {}).get(it["key"])) for it in items]] for i, s in enumerate(subjects)]
    docs = used_doc_ids(data)
    labels = [doc_label(load_meta(d), d) for d in docs]
    extra: Dict[str, Any] = {}
    if form:
        extra["look"] = form.get("look") or {}
        extra["formName"] = form.get("name") or ""
        if under and spec.get("orientation") != "items_as_rows":
            spans: List[Dict[str, Any]] = []
            for it in items:
                g = under.get(it["key"])
                label = (f"{g['label']} ({g['unit']})" if g.get("unit") else g["label"]) if g else ""
                if g and spans and spans[-1]["label"] == label and spans[-1].get("group"):
                    spans[-1]["span"] += 1
                else:
                    spans.append({"label": label, "span": 1, **({"group": True} if g else {})})
            extra["headGroups"] = spans
    return {
        **extra,
        "kind": "table",
        "blockId": block_id,
        "title": title,
        "caption": f"{title} ({period} 기준)" if period and period.split("년")[0] not in title else title,
        "unit": "",
        "number": "",
        "header": header,
        "rows": rows,
        "sourceLine": ("자료: " + ", ".join(labels)) if labels else "",
        "sourceDocIds": docs,
        "missing": False,
    }


def table_entry(row: Any) -> Dict[str, Any]:
    """섹션에 넣을 자리 — 지금 표·차트의 복사본(이후 표를 고쳐도 문서는 그대로). 계산 칸은 숫자 확인의 계산값 출처로 같이 둔다."""
    from app.research.chart import asset_block

    data = row.data or {}
    if getattr(row, "kind", None) == "chart":
        return {"id": id36("it", 4), "tableId": row.id, "block": asset_block(row), "calcs": [], "insertedAt": now_iso()}
    items = {it["key"]: it for it in data.get("items") or []}
    calcs = []
    for s, cells in zip(data.get("subjects") or [], data.get("cells") or []):
        for key, c in (cells or {}).items():
            if c.get("type") == "calc" and c.get("value") is not None:
                label = f"{s['label']} {items.get(key, {}).get('label', '')}".strip()
                calcs.append({"label": label, "expression": c.get("formula"), "readable": c.get("readable"), "value": c["value"], "display": c.get("text") or "", "percent": bool(c.get("percent")), "inputs": c.get("inputs") or []})
    return {"id": id36("it", 4), "tableId": row.id, "block": to_block(row.title, data, row.id), "calcs": calcs, "insertedAt": now_iso()}
