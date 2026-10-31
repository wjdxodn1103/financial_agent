"""경제 일정 — 일정 합치기(sync: FRED 발표일 + 공식 일정표 + 만기 규칙) · 목록 · 발표값 기록 · 알림 등록·보내기.
알림 메시지는 코드가 양식으로 만든다(AI 없음 — 속도). 날짜·시각은 한국 시각으로 보이고, 미국·유럽 일정은 현지 시각을 함께 둔다.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app import config
from app.auth import require_member
from app.calendar import rules, sources
from app.calendar.catalog import BY_ID, CATEGORY_KO, COUNTRY_KO, INDICATORS, Indicator
from app.calendar.schedule_data import FIXED
from app.db import ChannelMessage, EventAlert, MarketEvent, User, engine, iso, set_json, utcnow
from app.ids import id36
from app.notify import member_ids, notify

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")
TZ_SHORT = {"America/New_York": "ET", "Asia/Seoul": "KST", "Europe/Berlin": "CET"}
HORIZON_DAYS = 120
PAST_DAYS = 45
LAG = {"us_jolts": 28}  # 발표일과 대상 월 끝 사이 최소 시차(일) — 나머지 월간 지표는 1(앞 달)


def _utc(d: str, hhmm: str, tz: str) -> Tuple[datetime, bool]:
    """현지 날짜·시각 → UTC(naive). 시각을 모르면 현지 자정."""
    known = bool(hhmm)
    h, m = (int(hhmm[:2]), int(hhmm[3:5])) if known else (0, 0)
    local = datetime(int(d[:4]), int(d[5:7]), int(d[8:10]), h, m, tzinfo=ZoneInfo(tz or "Asia/Seoul"))
    return local.astimezone(timezone.utc).replace(tzinfo=None), known


def _period(ind: Indicator, d: str) -> Tuple[str, str]:
    """FRED 발표일 → 대상 기간(표시·감지 키)."""
    y, m = int(d[:4]), int(d[5:7])
    if ind.freq == "Q":
        mm, yy = m - ((m - 1) % 3 + 1), y
        if mm <= 0:
            mm, yy = mm + 12, yy - 1
        q = (mm - 1) // 3 + 1
        return f"{yy}년 {q}분기", f"{yy}Q{q}"
    if ind.freq == "W":
        we = date.fromisoformat(d) - timedelta(days=5)  # 목요일 발표 → 그 전 토요일로 끝나는 주
        return f"{we.month}월 {we.day}일까지 한 주", we.isoformat()
    if ind.freq == "meeting":
        return f"{y}년 {m}월 회의", d
    # 대상 월 = (발표일 − 최소 시차)가 든 달의 앞 달 — JOLTS 는 9/29 발표가 8월, 11/3 발표가 9월(시차 4~5주)
    base = date.fromisoformat(d) - timedelta(days=LAG.get(ind.id, 1))
    mm, yy = base.month - 1, base.year
    if mm <= 0:
        mm, yy = 12, yy - 1
    return f"{yy}년 {mm}월", f"{yy}-{mm:02d}"


# ── 일정 합치기 ──

def _items() -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    today = date.today()
    start, end = today - timedelta(days=PAST_DAYS), today + timedelta(days=HORIZON_DAYS)
    out: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    if config.FRED_API_KEY:
        for ind in INDICATORS:
            if not ind.fred or ind.category != "release":
                continue
            try:
                _rid, name, dates = sources.fred_release_dates(ind.fred, start, end)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{ind.short}: {str(e)[:100]}")
                continue
            for d in dates:
                label, pk = _period(ind, d)
                out[f"{ind.id}:{d}"] = {"indicator": ind.id, "date": d, "period": label, "periodKey": pk, "url": ind.url, "confirmed": True, "source": "fred", "note": f"FRED 발표일({name})"}
    # 공식 일정표가 FRED 뒤 — 같은 자리면 공식 표의 기간·링크가 이긴다
    for f in FIXED:
        key = f"{f['indicator']}:{f['date']}" if f.get("indicator") else f"fixed:{f['title']}:{f['date']}"
        out[key] = {**f, "source": "fixed"}
    for r in rules.expiries(today, months=4):
        out[r["key"]] = {**r, "source": "rule"}
    return out, errors


def _fields(it: Dict[str, Any]) -> Dict[str, Any]:
    ind = BY_ID.get(it.get("indicator") or "")
    if ind:
        at, known = _utc(it["date"], ind.time, ind.tz)
        return dict(country=ind.country, category=ind.category, importance=ind.importance, indicator_id=ind.id, title=ind.name, period=it["period"], period_key=it["periodKey"],
                    at=at, time_known=known, tz=ind.tz, unit=ind.unit, decimals=ind.decimals, source=it["source"], confirmed=bool(it.get("confirmed", True)), source_url=it.get("url") or ind.url)
    tz = it.get("tz") or ("Asia/Seoul" if it["country"] == "KR" else "America/New_York")
    at, known = _utc(it["date"], it.get("time") or "", tz)
    return dict(country=it["country"], category=it["category"], importance=int(it["importance"]), indicator_id=None, title=it["title"], period="", period_key=it["date"],
                at=at, time_known=known, tz=tz, unit="", decimals=0, source=it["source"], confirmed=bool(it.get("confirmed", True)), source_url=it.get("url") or "")


def sync() -> Dict[str, Any]:
    items, errors = _items()
    added = updated = 0
    with Session(engine) as s:
        have = {e.key: e for e in s.exec(select(MarketEvent)).all()}
        for key, it in items.items():
            fields = _fields(it)
            note = it.get("note") or ""
            ev = have.get(key)
            if ev is None:
                s.add(MarketEvent(id=id36("ev", 4), key=key, meta={"note": note} if note else {}, **fields))
                added += 1
                continue
            diff = {k: v for k, v in fields.items() if getattr(ev, k) != v}
            if diff or (ev.meta or {}).get("note", "") != note:
                for k, v in diff.items():
                    setattr(ev, k, v)
                set_json(ev, "meta", {**(ev.meta or {}), "note": note})
                ev.updated_at = utcnow()
                s.add(ev)
                updated += 1
        s.commit()
    filled = fill_values()
    return {"added": added, "updated": updated, "errors": errors + filled.pop("errors", []), **filled}


def fill_values() -> Dict[str, Any]:
    """이전치(앞으로의 일정)와 지난 일정의 실제치(하루 넘게 지난 것 — 알림은 보내지 않는다)를 소스에서 채운다."""
    now = utcnow()
    with Session(engine) as s:
        evs = s.exec(select(MarketEvent).where(MarketEvent.indicator_id != None, MarketEvent.status == "scheduled")).all()  # noqa: E711
        todo = [(e.id, e.indicator_id, e.period_key, e.at, e.previous) for e in evs]
    by_ind: Dict[str, List[Tuple[str, str, str, datetime, Optional[float]]]] = {}
    for t in todo:
        by_ind.setdefault(t[1], []).append(t)
    errors: List[str] = []
    bls_cache: Dict[str, sources.Points] = {}
    bls_ids = [BY_ID[i].bls for i in by_ind if BY_ID.get(i) and BY_ID[i].bls]
    if bls_ids:
        try:
            bls_cache = sources.bls_fetch([x for x in bls_ids if x])
        except Exception as e:  # noqa: BLE001
            errors.append(f"BLS: {str(e)[:100]}")
    prev_n = past_n = 0
    for ind_id, rows in by_ind.items():
        ind = BY_ID.get(ind_id)
        if ind is None:
            continue
        pts: sources.Points = []
        via = ""
        for v in sources.available(ind):
            if v == "bls" and not bls_cache:
                continue
            try:
                pts = sources.values(ind, v, bls_cache)
                via = v
                if pts:
                    break
            except Exception as e:  # noqa: BLE001
                errors.append(f"{ind.short}({v}): {str(e)[:80]}")
        if not pts:
            continue
        first_future = True
        for ev_id, _i, pk, at, prev in sorted(rows, key=lambda r: r[2]):
            before = [p for p in pts if p[0] < pk]
            if at > now:
                # 이전치는 바로 다음 발표에만(그다음 일정은 이번 발표의 실제치가 들어올 때 채운다)
                if first_future and prev is None and before:
                    _set(ev_id, previous=round(before[-1][1], 4))
                    prev_n += 1
                first_future = False
            elif now - at > timedelta(hours=24):
                hit = next((p for p in pts if p[0] == pk), None)
                if hit:
                    record_actual(ev_id, hit[1], via=via, obs=pk, previous=before[-1][1] if before else None, notify_alerts=False, backfill=True)
                    past_n += 1
    return {"previousFilled": prev_n, "pastFilled": past_n, "errors": errors}


def _set(ev_id: str, **kw: Any) -> None:
    with Session(engine) as s:
        ev = s.get(MarketEvent, ev_id)
        if ev is None:
            return
        for k, v in kw.items():
            setattr(ev, k, v)
        ev.updated_at = utcnow()
        s.add(ev)
        s.commit()


# ── 보기 ──

def view(ev: MarketEvent, alerted: bool = False) -> Dict[str, Any]:
    ind = BY_ID.get(ev.indicator_id or "")
    at = ev.at.replace(tzinfo=timezone.utc)
    kst = at.astimezone(KST)
    local = at.astimezone(ZoneInfo(ev.tz)) if ev.tz else kst
    det = ev.detect or {}
    return {"id": ev.id, "key": ev.key, "country": ev.country, "countryKo": COUNTRY_KO.get(ev.country, ev.country), "category": ev.category, "categoryKo": CATEGORY_KO.get(ev.category, ev.category),
            "importance": ev.importance, "indicatorId": ev.indicator_id, "title": ev.title, "short": ind.short if ind else ev.title, "agency": ind.agency if ind else "", "period": ev.period,
            "at": iso(ev.at), "date": kst.date().isoformat(), "kstTime": kst.strftime("%H:%M") if ev.time_known else "",
            "localTime": f"{local:%m/%d %H:%M} {TZ_SHORT.get(ev.tz, '')}" if ev.time_known and ev.tz and ev.tz != "Asia/Seoul" else "",
            "unit": ev.unit, "decimals": ev.decimals, "previous": ev.previous, "forecast": ev.forecast, "actual": ev.actual, "actualText": ev.actual_text, "status": ev.status,
            "releasedAt": iso(ev.released_at) if ev.released_at else None, "confirmed": ev.confirmed, "note": (ev.meta or {}).get("note") or "", "sourceUrl": ev.source_url, "source": ev.source,
            "detect": {k: det.get(k) for k in ("via", "url", "obs", "lagSec", "backfill") if det.get(k) is not None},
            "detectable": bool(ind and sources.available(ind)), "alerted": alerted}


def _my_targets(session: Session, workspace_id: str, user: User) -> Tuple[Set[str], Set[str]]:
    rows = session.exec(select(EventAlert).where(EventAlert.workspace_id == workspace_id, EventAlert.enabled == True)).all()  # noqa: E712
    mine = [a for a in rows if a.user_id == user.id or (a.recipients or {}).get("all") or user.id in ((a.recipients or {}).get("users") or [])]
    return {a.event_id for a in mine if a.event_id}, {a.indicator_id for a in mine if a.indicator_id and a.repeat}


def listing(session: Session, workspace_id: str, user: User, start: str, end: str, country: str = "", category: str = "", min_importance: int = 1) -> Dict[str, Any]:
    require_member(session, workspace_id, user)
    s_at = _utc(start, "", "Asia/Seoul")[0]
    e_at = _utc(end, "", "Asia/Seoul")[0] + timedelta(days=1)
    q = select(MarketEvent).where(MarketEvent.at >= s_at, MarketEvent.at < e_at, MarketEvent.importance >= min_importance)
    if country:
        q = q.where(MarketEvent.country.in_(country.split(",")))
    if category:
        q = q.where(MarketEvent.category.in_(category.split(",")))
    evs, inds = _my_targets(session, workspace_id, user)
    rows = session.exec(q.order_by(MarketEvent.at, MarketEvent.importance.desc())).all()
    return {"events": [view(e, e.id in evs or (e.indicator_id or "") in inds) for e in rows], "keys": key_status()}


def key_status() -> Dict[str, Any]:
    return {"fred": bool(config.FRED_API_KEY), "bls": bool(config.BLS_API_KEY), "ecos": bool(config.ECOS_API_KEY), "blsLeft": sources.bls_budget_left(), "webhook": bool(config.ALERT_WEBHOOK_URL)}


def set_forecast(session: Session, workspace_id: str, event_id: str, user: User, value: Optional[float]) -> Dict[str, Any]:
    require_member(session, workspace_id, user, "editor")
    ev = session.get(MarketEvent, event_id)
    if ev is None:
        raise HTTPException(404, "일정을 찾지 못했습니다.")
    ev.forecast, ev.forecast_by, ev.updated_at = value, (user.id if value is not None else None), utcnow()
    session.add(ev)
    session.commit()
    evs, inds = _my_targets(session, workspace_id, user)
    return view(ev, ev.id in evs or (ev.indicator_id or "") in inds)


# ── 발표값 기록 → 알림 ──

def record_actual(event_id: str, value: float, *, text: str = "", via: str = "manual", url: str = "", obs: str = "", previous: Optional[float] = None,
                  notify_alerts: bool = True, backfill: bool = False) -> Optional[Dict[str, Any]]:
    with Session(engine) as s:
        ev = s.get(MarketEvent, event_id)
        if ev is None:
            return None
        if ev.status == "released" and ev.actual is not None and abs(ev.actual - value) < 1e-9 and not backfill:
            return view(ev)
        now = utcnow()
        ev.actual, ev.actual_text, ev.status = round(float(value), 4), text, "released"
        if previous is not None:
            ev.previous = round(float(previous), 4)
        ev.released_at = ev.released_at or now
        set_json(ev, "detect", {**(ev.detect or {}), "via": via, "url": url, "obs": obs, "fetchedAt": iso(now), "lagSec": None if backfill else max(0, int((now - ev.at).total_seconds())),
                                "backfill": backfill or None})
        ev.updated_at = now
        s.add(ev)
        if ev.indicator_id:  # 같은 지표의 다음 일정 — 이전치 = 이번 실제치
            nxt = s.exec(select(MarketEvent).where(MarketEvent.indicator_id == ev.indicator_id, MarketEvent.status == "scheduled", MarketEvent.period_key > ev.period_key)
                         .order_by(MarketEvent.period_key)).first()
            if nxt is not None:
                nxt.previous, nxt.updated_at = ev.actual, now
                s.add(nxt)
        s.commit()
        out = view(ev)
    if notify_alerts:
        deliver(event_id)
    return out


def _num(v: Optional[float], ev: MarketEvent) -> str:
    if v is None:
        return "—"
    d = ev.decimals if ev.decimals is not None else 1
    return f"{v:,.{d}f}{ev.unit if ev.unit == '%' else (' ' + ev.unit if ev.unit else '')}"


def _diff(a: float, b: float, ev: MarketEvent) -> str:
    """보이는 값끼리의 차이(3.7% − 3.4% = ▲0.3%p — 반올림 전 값으로 빼면 0.4 가 나와 메시지가 어긋난다)."""
    dec = max(ev.decimals, 0)
    d = round(round(a, dec) - round(b, dec), dec)
    if abs(d) < 10 ** -(dec + 1):
        return "변화 없음"
    unit = "%p" if ev.unit == "%" else (" " + ev.unit if ev.unit else "")
    return f"{'▲' if d > 0 else '▼'}{abs(d):,.{dec}f}{unit}"


def format_message(ev: MarketEvent) -> Tuple[str, str]:
    """→ (한 줄, 덧붙임). 예: '[미국 CPI · 2026년 10월] 실제 3.1% · 예상 3.0% · 이전 2.9% · 이전 대비 ▲0.2%p'"""
    ind = BY_ID.get(ev.indicator_id or "")
    name = f"{COUNTRY_KO.get(ev.country, ev.country)} {ind.short if ind else ev.title}" if ev.country != "EU" or not ind else ind.short
    head = f"[{name} · {ev.period}]" if ev.period else f"[{name}]"
    if ev.category == "meeting":
        t = ev.actual_text or "결정"
        rng = "~" in t  # FOMC 는 결정 문구에 범위가 들어 있다('인하 3.50~3.75%')
        parts = [t] if rng else [t, _num(ev.actual, ev)]
        if ev.previous is not None:
            parts.append(f"이전 {'상단 ' if rng else ''}{_num(ev.previous, ev)}")
    else:
        parts = [f"실제 {_num(ev.actual, ev)}"]
        if ev.forecast is not None:
            parts.append(f"예상 {_num(ev.forecast, ev)}")
        if ev.previous is not None:
            parts.append(f"이전 {_num(ev.previous, ev)}")
        if ev.actual is not None and ev.forecast is not None:
            parts.append(f"예상 대비 {_diff(ev.actual, ev.forecast, ev)}")
        elif ev.actual is not None and ev.previous is not None:
            parts.append(f"이전 대비 {_diff(ev.actual, ev.previous, ev)}")
    at = ev.at.replace(tzinfo=timezone.utc)
    kst = at.astimezone(KST)
    local = at.astimezone(ZoneInfo(ev.tz)) if ev.tz else kst
    when = f"{local:%H:%M} {TZ_SHORT.get(ev.tz, '')}(한국 {kst:%m/%d %H:%M})" if ev.tz and ev.tz != "Asia/Seoul" else f"{kst:%H:%M} KST"
    det = ev.detect or {}
    extra = " · ".join(x for x in [f"{when} 발표", ind.agency if ind else "", f"감지 {det['lagSec']}초 뒤" if det.get("lagSec") is not None else "", det.get("url") or ev.source_url] if x)
    return f"{head} " + " · ".join(parts), extra


def deliver(event_id: str) -> int:
    """그 일정·지표에 걸린 알림마다 한 번씩 — 알림함(받는 사람) · 워크스페이스 메시지 · 웹훅."""
    with Session(engine) as s:
        ev = s.get(MarketEvent, event_id)
        if ev is None or ev.status != "released":
            return 0
        q = select(EventAlert).where(EventAlert.enabled == True)  # noqa: E712
        alerts = [a for a in s.exec(q).all() if a.event_id == ev.id or (a.repeat and ev.indicator_id and a.indicator_id == ev.indicator_id)]
        sent: List[str] = list((ev.meta or {}).get("sent") or [])
        line, extra = format_message(ev)
        n = 0
        for a in alerts:
            if a.id in sent:
                continue
            rec = a.recipients or {}
            users = member_ids(a.workspace_id, s) if rec.get("all") else list(dict.fromkeys([a.user_id, *(rec.get("users") or [])]))
            ch = a.channels or {}
            if ch.get("inbox", True):
                notify(users, workspace_id=a.workspace_id, kind="calendar", title=line, body=extra, link={"w": a.workspace_id, "v": "calendar", "s": ev.id},
                       ref={"kind": "event", "id": ev.id}, dedupe_key=f"event:{ev.id}:{a.id}", session=s)
            if ch.get("workspace"):
                s.add(ChannelMessage(id=id36("c", 4), workspace_id=a.workspace_id, user_id=None, kind="system", text=f"{line}\n{extra}", meta={"event": ev.id, "alert": a.id}))
            if ch.get("webhook") and config.ALERT_WEBHOOK_URL:
                try:
                    httpx.post(config.ALERT_WEBHOOK_URL, json={"text": f"{line}\n{extra}"}, timeout=5)
                except Exception:  # noqa: BLE001 — 밖으로 못 보내도 앱 알림은 간다
                    log.exception("webhook failed")
            a.last_sent_at = utcnow()
            if not a.repeat:
                a.enabled = False  # 한 번짜리는 보낸 뒤 끝
            s.add(a)
            sent.append(a.id)
            n += 1
        set_json(ev, "meta", {**(ev.meta or {}), "sent": sent})
        s.add(ev)
        s.commit()
    return n


# ── 알림 등록 ──

def alert_view(session: Session, a: EventAlert) -> Dict[str, Any]:
    ev = session.get(MarketEvent, a.event_id) if a.event_id else None
    ind = BY_ID.get(a.indicator_id or (ev.indicator_id if ev else "") or "")
    return {"id": a.id, "eventId": a.event_id, "indicatorId": a.indicator_id, "repeat": a.repeat, "title": (ev.title if ev else (ind.name if ind else "")),
            "event": view(ev) if ev else None, "all": bool((a.recipients or {}).get("all")), "channels": a.channels, "enabled": a.enabled, "userId": a.user_id,
            "lastSentAt": iso(a.last_sent_at) if a.last_sent_at else None, "createdAt": iso(a.created_at), "source": a.source}


def list_alerts(session: Session, workspace_id: str, user: User) -> List[Dict[str, Any]]:
    require_member(session, workspace_id, user)
    rows = session.exec(select(EventAlert).where(EventAlert.workspace_id == workspace_id).order_by(EventAlert.created_at.desc())).all()
    return [alert_view(session, a) for a in rows if a.user_id == user.id or (a.recipients or {}).get("all")]


def create_alerts(session: Session, workspace_id: str, user: User, *, event_ids: List[str], indicator_ids: List[str], repeat: bool, to_all: bool,
                  workspace_msg: bool = False, webhook: bool = False, source: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    require_member(session, workspace_id, user, "editor" if to_all else "viewer")
    have = session.exec(select(EventAlert).where(EventAlert.workspace_id == workspace_id, EventAlert.user_id == user.id, EventAlert.enabled == True)).all()  # noqa: E712
    made: List[EventAlert] = []
    targets: List[Tuple[Optional[str], Optional[str]]] = [(None, i) for i in indicator_ids if i in BY_ID] if repeat else []
    for e in event_ids:
        ev = session.get(MarketEvent, e)
        if ev is None:
            continue
        targets.append((None, ev.indicator_id) if repeat and ev.indicator_id else (ev.id, ev.indicator_id))
    for ev_id, ind_id in dict.fromkeys(targets):
        if any((a.event_id == ev_id and ev_id) or (not ev_id and a.repeat and a.indicator_id == ind_id) for a in have):
            continue
        a = EventAlert(id=id36("ea", 4), workspace_id=workspace_id, user_id=user.id, event_id=ev_id, indicator_id=ind_id, repeat=bool(repeat and not ev_id),
                       recipients={"all": to_all}, channels={"inbox": True, "workspace": workspace_msg, "webhook": webhook}, source=source or {"kind": "ui"})
        session.add(a)
        made.append(a)
    session.commit()
    return [alert_view(session, a) for a in made]


def delete_alert(session: Session, alert_id: str, user: User) -> None:
    a = session.get(EventAlert, alert_id)
    if a is None:
        raise HTTPException(404, "알림을 찾지 못했습니다.")
    require_member(session, a.workspace_id, user, "viewer" if a.user_id == user.id else "owner")
    session.delete(a)
    session.commit()


def upcoming(indicator_ids: List[str], start: datetime, end: datetime) -> List[MarketEvent]:
    with Session(engine) as s:
        return list(s.exec(select(MarketEvent).where(MarketEvent.indicator_id.in_(indicator_ids), MarketEvent.at >= start, MarketEvent.at <= end).order_by(MarketEvent.at)).all())
