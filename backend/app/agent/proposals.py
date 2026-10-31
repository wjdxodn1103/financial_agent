"""대화로 등록하기 — "매일 7시에 해외주식 동향 브리핑 써서 팀에 올려 줘"·"엔비디아 공시 매일 모아 줘".
AI 는 바로 저장하지 않고 확인 카드(proposal)만 띄운다 → 사람이 카드에서 [등록](또는 고쳐서 등록)해야 저장된다.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from app.agent.session import Doc

SCHEDULE = {
    "type": "object",
    "description": "언제 — every: daily(매일)|weekdays(평일)|weekly(매주)|hourly(매시간)|manual(손으로만), time: 'HH:MM', weekday: 0(월)~6(일)",
    "properties": {"every": {"type": "string", "enum": ["daily", "weekdays", "weekly", "hourly", "manual"]}, "time": {"type": "string"}, "weekday": {"type": "integer"}},
}

PROPOSAL_TOOLS: List[Dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "propose_routine",
        "description": "반복 작성 업무(정기 보고서·브리핑)를 루틴으로 등록하자고 확인 카드를 띄운다. 바로 저장하지 않는다 — 사용자가 카드에서 등록한다. "
                       "사용자가 '매일/매주 …에 …를 써서 올려/보내 줘'처럼 반복을 말할 때만 부른다.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "루틴 이름(예: 해외주식 동향 브리핑)"},
            "format": {"type": "string", "description": "쓸 문서 양식 이름(사용자가 말했거나 '쓸 수 있는 양식' 목록에서 고른 것, 모르면 빈 문자열)"},
            "instruction": {"type": "string", "description": "매번 쓸 때의 지시(무엇을 어떤 관점으로 — 사용자가 말한 그대로 + 필요한 범위)"},
            "schedule": SCHEDULE,
            "folder": {"type": "string", "description": "올릴 드라이브 폴더 이름(예: 데일리 브리핑, 모르면 빈 문자열)"},
            "notify_all": {"type": "boolean", "description": "워크스페이스 전원에게 알릴지(사용자가 '팀에'·'전원에게'라고 하면 true)"},
        }, "required": ["name", "instruction", "schedule"]},
    }},
    {"type": "function", "function": {
        "name": "propose_source",
        "description": "데이터를 계속 모으는 수집 소스를 등록하자고 확인 카드를 띄운다(공시·시장 시계열·공식 보도자료 피드). 바로 저장하지 않는다. "
                       "사용자가 '…를 매일 모아 줘·수집해 줘·쌓아 줘'라고 할 때만 부른다.",
        "parameters": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["edgar", "series", "rss"], "description": "edgar=미국 상장사 공시, series=시장·거시 시계열, rss=공식 보도자료·성명 피드"},
            "name": {"type": "string"},
            "companies": {"type": "array", "items": {"type": "string"}, "description": "edgar — 회사 이름·티커"},
            "series": {"type": "array", "items": {"type": "string"}, "description": "series — 시리즈 이름(예: 원/달러, 미 국채 10년)"},
            "feeds": {"type": "array", "items": {"type": "string"}, "description": "rss — 피드 주소"},
            "schedule": SCHEDULE,
        }, "required": ["kind", "schedule"]},
    }},
    {"type": "function", "function": {
        "name": "propose_event_alert",
        "description": "경제 일정(지표 발표·중앙은행 회의·휴장·만기)이 발표되면 바로 알림이 가게 등록하자고 확인 카드를 띄운다. 바로 저장하지 않는다 — 사용자가 카드에서 등록한다. "
                       "사용자가 '…발표되면 알려 줘·일정 등록해 줘·알림 걸어 줘'라고 할 때 부른다. 알림 메시지는 코드가 정해진 양식으로 만든다(해설 없음).",
        "parameters": {"type": "object", "properties": {
            "targets": {"type": "array", "items": {"type": "string"}, "description": "지표·일정 이름 그대로(예: 미국 CPI, 고용보고서, FOMC, 금통위, 옵션 만기)"},
            "start": {"type": "string", "description": "찾을 기간 시작 YYYY-MM-DD(모르면 빈 문자열 = 오늘)"},
            "end": {"type": "string", "description": "찾을 기간 끝 YYYY-MM-DD(모르면 빈 문자열 = 60일 뒤)"},
            "repeat": {"type": "boolean", "description": "'매번·앞으로 계속'이면 true(그 지표의 다음 발표마다), 아니면 기간 안의 다음 한 번"},
            "notify_all": {"type": "boolean", "description": "워크스페이스 전원에게(사용자가 '팀에'·'전원에게'라고 하면 true)"},
            "workspace_message": {"type": "boolean", "description": "워크스페이스 메시지로도 보낼지"},
        }, "required": ["targets"]},
    }},
]
PROPOSAL_NAMES = tuple(t["function"]["name"] for t in PROPOSAL_TOOLS)


def _schedule(raw: Any) -> Dict[str, Any]:
    r = raw if isinstance(raw, dict) else {}
    every = r.get("every") if r.get("every") in ("daily", "weekdays", "weekly", "hourly", "manual") else "daily"
    t = str(r.get("time") or "07:00")[:5]
    return {"every": every, "times": [] if every in ("hourly", "manual") else [t if len(t) == 5 and t[2] == ":" else "07:00"], **({"weekday": int(r.get("weekday") or 0) % 7} if every == "weekly" else {})}


def _formats(doc: Doc) -> List[Dict[str, str]]:
    return [{"id": f.get("id"), "title": f.get("title")} for f in doc.get("_formats") or [] if isinstance(f, dict) and f.get("id")]


def _event_alert(args: Dict[str, Any], emit: Any) -> str:
    """'다음 주 미국 CPI랑 고용보고서, 금통위 알려 줘' → 기간 안의 다음 일정(또는 지표의 다음 발표마다) 확인 카드."""
    from datetime import date, datetime, timedelta

    from sqlmodel import Session, select

    from app.calendar import catalog
    from app.calendar.service import view
    from app.db import MarketEvent, engine, utcnow

    def _d(s: Any, default: date) -> date:
        try:
            return date.fromisoformat(str(s)[:10])
        except ValueError:
            return default

    today = date.today()
    start, end = _d(args.get("start"), today), _d(args.get("end"), today + timedelta(days=60))
    s_at, e_at = max(datetime.combine(start, datetime.min.time()) - timedelta(hours=9), utcnow()), datetime.combine(end, datetime.max.time())
    repeat = bool(args.get("repeat"))
    items, missing, seen = [], [], set()
    with Session(engine) as s:
        for t in [str(x) for x in args.get("targets") or []][:10]:
            inds = catalog.find(t)
            if inds:
                for ind in inds:
                    ev = s.exec(select(MarketEvent).where(MarketEvent.indicator_id == ind.id, MarketEvent.at >= s_at, MarketEvent.at <= e_at).order_by(MarketEvent.at)).first()
                    if ev is None and not repeat:
                        missing.append(f"{ind.short}(기간 안 일정 없음)")
                        continue
                    k = ind.id if repeat else (ev.id if ev else ind.id)
                    if k in seen:
                        continue
                    seen.add(k)
                    items.append({"eventId": ev.id if ev else None, "indicatorId": ind.id, "name": ind.name, **({"event": view(ev)} if ev else {})})
                continue
            words = [w for w in t.replace("한국", " ").replace("미국", " ").split() if w]
            evs = [e for e in s.exec(select(MarketEvent).where(MarketEvent.indicator_id == None, MarketEvent.at >= s_at, MarketEvent.at <= e_at).order_by(MarketEvent.at)).all()  # noqa: E711
                   if words and all(w in e.title for w in words) and (("한국" not in t) or e.country == "KR") and (("미국" not in t) or e.country == "US")]
            if not evs:
                missing.append(t)
            for e in evs[:3]:
                if e.id not in seen:
                    seen.add(e.id)
                    items.append({"eventId": e.id, "indicatorId": None, "name": e.title, "event": view(e)})
    card = {"kind": "event_alert", "items": items, "repeat": repeat, "notifyAll": bool(args.get("notify_all")), "workspace": bool(args.get("workspace_message")),
            "range": [start.isoformat(), end.isoformat()], "missing": missing}
    emit({"type": "proposal", "proposal": card})
    if not items:
        return "맞는 일정을 찾지 못했다(" + ", ".join(missing) + "). 일정 이름이나 기간을 다시 물어본다."
    return "확인 카드를 띄웠다. 사용자가 카드에서 [등록]해야 저장된다 — 저장했다고 말하지 말고 카드를 확인해 달라고 한 줄로만 안내한다." + (f" 찾지 못한 것: {', '.join(missing)}" if missing else "")


async def run(name: str, args: Dict[str, Any], doc: Doc, emit: Any) -> str:
    if name == "propose_routine":
        fmt_name = str(args.get("format") or "").strip()
        fmts = _formats(doc)
        hit = next((f for f in fmts if fmt_name and (fmt_name in (f["title"] or "") or (f["title"] or "") in fmt_name)), None)
        card = {"kind": "routine", "name": str(args.get("name") or "루틴")[:60], "formatId": hit["id"] if hit else None, "formatTitle": hit["title"] if hit else fmt_name,
                "instruction": str(args.get("instruction") or "")[:1000], "schedule": _schedule(args.get("schedule")), "folderName": str(args.get("folder") or "")[:60],
                "notifyAll": bool(args.get("notify_all")), "sessionId": doc.get("id")}
        emit({"type": "proposal", "proposal": card})
        return "확인 카드를 띄웠다. 사용자가 카드에서 [등록]해야 저장된다 — 저장했다고 말하지 말고, 카드를 확인해 달라고 한 줄로만 안내한다." + ("" if hit else " 양식을 정하지 못했으니 카드에서 양식을 골라 달라고 한다.")
    if name == "propose_source":
        kind = args.get("kind") if args.get("kind") in ("edgar", "series", "rss") else "edgar"
        card: Dict[str, Any] = {"kind": "source", "sourceKind": kind, "name": str(args.get("name") or "")[:60], "schedule": _schedule(args.get("schedule"))}
        if kind == "edgar":
            from app.pipeline.service import edgar_companies

            cos, missing = [], []
            for q in [str(x) for x in args.get("companies") or []][:10]:
                found = await asyncio.to_thread(edgar_companies, q)
                (cos.append(found[0]) if found else missing.append(q))
            card.update(companies=cos, missing=missing)
        elif kind == "series":
            from app.market.catalog import SERIES

            want = [str(x) for x in args.get("series") or []]
            card["seriesIds"] = [s.id for s in SERIES if any(w and (w in s.name or s.name in w) for w in want)] or [s.id for s in SERIES if not s.calc]
        else:
            card["feeds"] = [{"url": u, "issuer": ""} for u in (args.get("feeds") or []) if str(u).startswith(("http://", "https://"))]
        emit({"type": "proposal", "proposal": card})
        miss = card.get("missing") or []
        return "확인 카드를 띄웠다. 사용자가 카드에서 [등록]해야 저장된다." + (f" 찾지 못한 회사: {', '.join(miss)} — 이름이나 티커를 다시 물어본다." if miss else "")
    if name == "propose_event_alert":
        return await asyncio.to_thread(_event_alert, args, emit)
    return "모르는 도구"
