"""대시보드 위젯 목록·검증·기본 구성. 위젯 = {id, type, title, params, size: s|m|l|full}.
AI 가 고친 구성도 여기서 검증한다(알려진 종류·매개변수·시리즈만, 12개 이하) — 모르는 것은 버린다.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.ids import id36
from app.market.catalog import BY_ID, SERIES

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
    # 양식(templates.py)이 만드는 위젯 — AI 가 직접 넣지 않는다(회사 고유번호·종목 표기는 코드가 찾는다). 지표만 고칠 수 있다.
    "peer_board": {"label": "피어 비교(양식)", "params": {"companies": "양식이 채움 — 그대로 둔다", "metrics": "보일 지표 id 목록(revenue|op|opm|ni|roe|per|pbr|ret12)", "outlook": "양식이 채움 — 그대로 둔다"}, "template": True},
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
        if t == "peer_board":
            params = _peer_params(p)
            if params is None:
                continue
        wid = str(w.get("id") or "") or id36("w", 3)
        if wid in seen:
            wid = id36("w", 3)
        seen.add(wid)
        out.append({"id": wid, "type": t, "title": str(w.get("title") or WIDGETS[t]["label"])[:60], "params": params, "size": w.get("size") if w.get("size") in SIZES else "m"})
        if len(out) >= MAX_WIDGETS:
            break
    from app.dashboards.templates import TEMPLATES

    tpl = (spec or {}).get("template")
    keep = tpl in TEMPLATES and kind in TEMPLATES[tpl]["kinds"] and any(w["type"] == "peer_board" for w in out)
    return {"widgets": out, **({"template": tpl} if keep else {})}


def _peer_params(p: Dict[str, Any]) -> Any:
    """피어 비교 위젯 인자 — 회사는 고유번호·종목 표기가 있는 것만(2~3곳), 전망 문장은 근거가 달린 것만."""
    from app.dashboards.peer import METRICS

    cos = []
    for c in p.get("companies") or []:
        if isinstance(c, dict) and c.get("name") and c.get("corpCode") and c.get("ticker"):
            cos.append({"name": str(c["name"])[:40], "corpCode": str(c["corpCode"])[:12], "stockCode": str(c.get("stockCode") or "")[:12], "ticker": str(c["ticker"])[:20]})
    if len(cos) < 2:
        return None
    outlook = []
    for it in p.get("outlook") or []:
        cites = [{"docId": str(x.get("docId")), "chunk": str(x.get("chunk") or ""), "label": str(x.get("label") or "")[:80]} for x in (it.get("cites") or []) if isinstance(x, dict) and x.get("docId")] if isinstance(it, dict) else []
        if cites and it.get("text"):
            outlook.append({"title": str(it.get("title") or "")[:14], "text": str(it["text"])[:160], "cites": cites[:2]})
    metrics = [m for m in p.get("metrics") or [] if m in METRICS]
    return {"companies": cos[:3], "outlook": outlook[:4], **({"metrics": metrics} if metrics else {})}


def _group(g: str) -> List[str]:
    return [s.id for s in SERIES if s.group == g]


def default(kind: str) -> Dict[str, Any]:
    if kind == "market":
        # 금리·환율·원자재·주가지수 카드와 원/달러 차트는 위쪽 시장 홈(app/market/home.py)이 보여 준다(2026-11-03) — 겹치지 않는 것만
        ws: List[Dict[str, Any]] = [{"type": "ai_summary", "title": "오늘의 시장 요약", "size": "full"}]
        ws += [{"type": "series_chart", "title": "미 국채 금리(1년)", "params": {"seriesIds": ["us_2y", "us_10y"], "range": "1Y"}, "size": "full"}]
        ws += [{"type": "series_cards", "title": g, "params": {"seriesIds": _group(g)}, "size": "l"} for g in ("신용", "거시")]
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
    from app.dashboards.templates import catalog_text as template_text

    extra = template_text(kind)
    return "\n".join(lines) + (f"\n\n{extra}" if extra else "")
