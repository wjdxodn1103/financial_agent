"""대시보드 위젯 목록·검증·기본 구성. 위젯 = {id, type, title, params, size: s|m|l|full}.
AI 가 고친 구성도 여기서 검증한다(알려진 종류·매개변수·시리즈만, 12개 이하) — 모르는 것은 버린다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.ids import id36
from app.market.catalog import BY_ID, GROUPS, SERIES

WIDGETS: Dict[str, Dict[str, Any]] = {
    "series_cards": {"label": "시리즈 카드(값·전일·1주·1달·스파크라인)", "params": {"seriesIds": "시리즈 id 목록(1~12)"}},
    "change_table": {"label": "변화 표(전일·1주·1달)", "params": {"seriesIds": "시리즈 id 목록(1~24)"}},
    "series_chart": {"label": "시계열 차트", "params": {"seriesIds": "시리즈 id 목록(1~4)", "range": "1M|3M|6M|1Y"}},
    "ai_summary": {"label": "오늘의 시장 요약·AI 판단", "params": {}},
    "source_status": {"label": "수집·갱신 상태(마지막 갱신·대체 소스)", "params": {}},
    "data_issues": {"label": "데이터 품질 문제", "params": {"limit": "보일 수(기본 12)"}},
    "ingest_stats": {"label": "적재 현황(문서·청크·수치·시계열)", "params": {}},
    "assumptions": {"label": "감시 중인 가정(판정이 바뀐 것 먼저)", "params": {}},
    "houseview": {"label": "하우스뷰 흐름(분기별 자산군 입장·가정 판정)", "params": {}},
    "shared_docs": {"label": "받은 것", "params": {}},
    "routine_docs": {"label": "루틴이 쓴 문서", "params": {}},
    "tasks": {"label": "내 할 일", "params": {}},
    "note": {"label": "메모", "params": {"text": "글"}},
    "kpi": {"label": "AI 품질·이용 지표", "params": {"metrics": "지표 id 목록"}},
}
SIZES = ("s", "m", "l", "full")
RANGES = ("1M", "3M", "6M", "1Y")
MAX_WIDGETS = 12
# 화면마다 쓸 수 있는 위젯 — 전사 대시보드는 시장·데이터만, 워크스페이스는 전부
ALLOWED = {
    "market": {"series_cards", "change_table", "series_chart", "ai_summary", "note", "source_status", "data_issues"},
    "data": {"source_status", "data_issues", "ingest_stats", "series_cards", "change_table", "note"},
    "workspace": set(WIDGETS),
}


def clean(spec: Dict[str, Any], kind: str) -> Dict[str, Any]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for w in (spec or {}).get("widgets") or []:
        if not isinstance(w, dict):
            continue
        t = w.get("type")
        if t not in WIDGETS or t not in ALLOWED.get(kind, set()):
            continue
        p = w.get("params") if isinstance(w.get("params"), dict) else {}
        params: Dict[str, Any] = {}
        if "seriesIds" in WIDGETS[t]["params"]:
            ids = [i for i in p.get("seriesIds") or [] if i in BY_ID]
            cap = 4 if t == "series_chart" else 24 if t == "change_table" else 12
            if not ids:
                continue
            params["seriesIds"] = list(dict.fromkeys(ids))[:cap]
        if t == "series_chart":
            params["range"] = p.get("range") if p.get("range") in RANGES else "1Y"
        if t == "data_issues":
            params["limit"] = max(3, min(int(p.get("limit") or 12), 50)) if str(p.get("limit") or "12").isdigit() else 12
        if t == "note":
            params["text"] = str(p.get("text") or "")[:1000]
        if t == "kpi":
            params["metrics"] = [str(m) for m in p.get("metrics") or []][:8]
        wid = str(w.get("id") or "") or id36("w", 3)
        if wid in seen:
            wid = id36("w", 3)
        seen.add(wid)
        out.append({"id": wid, "type": t, "title": str(w.get("title") or WIDGETS[t]["label"])[:60], "params": params, "size": w.get("size") if w.get("size") in SIZES else "m"})
        if len(out) >= MAX_WIDGETS:
            break
    return {"widgets": out}


def _group(g: str) -> List[str]:
    return [s.id for s in SERIES if s.group == g]


def default(kind: str) -> Dict[str, Any]:
    if kind == "market":
        ws: List[Dict[str, Any]] = [{"type": "ai_summary", "title": "오늘의 시장 요약", "size": "full"}]
        ws += [{"type": "series_cards", "title": g, "params": {"seriesIds": _group(g)}, "size": "full"} for g in GROUPS]
        ws += [
            {"type": "series_chart", "title": "미 국채 금리(1년)", "params": {"seriesIds": ["us_2y", "us_10y"], "range": "1Y"}, "size": "l"},
            {"type": "series_chart", "title": "원/달러(1년)", "params": {"seriesIds": ["krw_usd"], "range": "1Y"}, "size": "l"},
        ]
        return clean({"widgets": ws}, kind)
    if kind == "data":
        return clean({"widgets": [
            {"type": "source_status", "title": "수집·갱신 상태", "size": "full"},
            {"type": "data_issues", "title": "데이터 품질 문제", "params": {"limit": 20}, "size": "l"},
            {"type": "ingest_stats", "title": "적재 현황", "size": "l"},
        ]}, kind)
    return clean({"widgets": [
        {"type": "assumptions", "title": "감시 중인 가정", "size": "l"},
        {"type": "shared_docs", "title": "받은 것", "size": "l"},
        {"type": "series_cards", "title": "관심 시리즈", "params": {"seriesIds": ["us_10y", "krw_usd", "spx", "wti"]}, "size": "full"},
        {"type": "routine_docs", "title": "루틴이 쓴 문서", "size": "l"},
        {"type": "tasks", "title": "내 할 일", "size": "l"},
    ]}, "workspace")


def catalog_text(kind: str) -> str:
    """AI 에게 보일 위젯·시리즈 목록."""
    lines = ["위젯 종류(type: 설명 · params):"]
    for t, w in WIDGETS.items():
        if t in ALLOWED.get(kind, set()):
            ps = ", ".join(f"{k}={v}" for k, v in w["params"].items()) or "없음"
            lines.append(f"- {t}: {w['label']} · {ps}")
    lines.append("크기(size): s | m | l | full")
    lines.append("시리즈(seriesIds 에 쓰는 id: 이름 · 묶음):")
    lines += [f"- {s.id}: {s.name} · {s.group}{' · 가상' if s.virtual else ''}" for s in SERIES]
    return "\n".join(lines)
