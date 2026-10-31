"""경제 일정 스냅샷 — 그날 아침의 '시간대 규칙 · 시간대가 바뀌는 지표 · 이번 주 발표 일정(한국 시각)'을 표 문서로 남긴다
(시장·거시 데이터 문서처럼 시계열 수집 때 — pipeline/kinds.collect_series). 작성기·대화는 발표 시각·서머타임을 기억이 아니라
이 문서로 말하고 인용한다 — 서머타임 전환 주에 "반영됐나"를 근거로 답하는 바탕. 시각 계산은 전부 코드(IANA 시간대 DB, LLM 0회).

문서 = 문단 넷
  ① 작성 방법 — 한국 시각을 어떻게 구했는지(공식 일정표의 현지 시각 → 발표일의 시간대 규칙)
  ② 시간대 규칙 — 미국 동부·유럽 중부의 전환일(앞 14일 ~ 뒤 21일)과 전후 약칭·UTC 차이·한국과 시차
  ③ 시간대 변경 표 — 그 기간에 전환이 있으면 현지 발표 시각마다 바뀌기 전·뒤 한국 시각
  ④ 이번 주 발표 일정 표 — 오늘부터 7일(한국 날짜), 현지 시각에 그날의 약칭(EDT·EST)을 붙인다
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.calendar.catalog import BY_ID, COUNTRY_KO, INDICATORS
from app.db import MarketEvent, engine

KST = ZoneInfo("Asia/Seoul")
ZONES: List[Tuple[str, str]] = [("America/New_York", "미국 동부"), ("Europe/Berlin", "유럽 중부")]
BACK, AHEAD = 14, 21  # 시간대 규칙을 보는 기간(오늘 기준 앞·뒤 일)
DAYS = 7  # 일정 표 기간
_WD = "월화수목금토일"


def _utc_label(off: timedelta) -> str:
    h = off.total_seconds() / 3600
    return f"UTC{'+' if h >= 0 else '-'}{abs(h):g}"


def _at(d: date, hhmm: str, tz: str) -> datetime:
    return datetime.combine(d, time(int(hhmm[:2]), int(hhmm[3:5])), tzinfo=ZoneInfo(tz))


def _kst_label(local: datetime) -> str:
    """현지 시각 → '22:30 (EST)' · '04:00 (EDT, 다음 날)' — 괄호 안은 현지 약칭(그날의 서머타임 여부)."""
    k = local.astimezone(KST)
    shift = ", 다음 날" if k.date() > local.date() else ", 전날" if k.date() < local.date() else ""
    return f"{k:%H:%M} ({local.tzname()}{shift})"


def transitions(tz: str, day: date) -> List[Dict[str, Any]]:
    """day 앞 BACK 일 ~ 뒤 AHEAD 일 사이의 시간대 전환 — [{date, end(서머타임 종료?), before, after}]. 그날 정오 현지 오프셋이 전날과 다르면 전환."""
    z = ZoneInfo(tz)
    out: List[Dict[str, Any]] = []
    prev = datetime.combine(day - timedelta(days=BACK + 1), time(12), tzinfo=z)
    for k in range(-BACK, AHEAD + 1):
        cur = datetime.combine(day + timedelta(days=k), time(12), tzinfo=z)
        if cur.utcoffset() != prev.utcoffset():
            out.append({"date": cur.date(), "end": cur.utcoffset() < prev.utcoffset(),  # type: ignore[operator]
                        "before": (prev.tzname(), prev.utcoffset()), "after": (cur.tzname(), cur.utcoffset())})
        prev = cur
    return out


def _kst_gap(off: timedelta) -> int:
    return int((timedelta(hours=9) - off).total_seconds() // 3600)


def rule_text(day: date) -> str:
    lines: List[str] = []
    for tz, label in ZONES:
        z = ZoneInfo(tz)
        trs = transitions(tz, day)
        if not trs:
            now = datetime.combine(day, time(12), tzinfo=z)
            lines.append(f"{label}({tz}): {day - timedelta(days=BACK):%m/%d}~{day + timedelta(days=AHEAD):%m/%d} 사이 시간대 변동 없음 — "
                         f"{now.tzname()}({_utc_label(now.utcoffset())}), 한국과 시차 {_kst_gap(now.utcoffset())}시간.")  # type: ignore[arg-type]
            continue
        for t in trs:
            (a0, o0), (a1, o1) = t["before"], t["after"]
            later = "늦어진다" if _kst_gap(o1) > _kst_gap(o0) else "빨라진다"
            lines.append(f"{label}({tz}): {t['date']:%Y-%m-%d}({_WD[t['date'].weekday()]}) 서머타임 {'종료' if t['end'] else '시작'} — "
                         f"그 전 {a0}({_utc_label(o0)}), 그 뒤 {a1}({_utc_label(o1)}). 한국과 시차 {_kst_gap(o0)}시간 → {_kst_gap(o1)}시간이라 "
                         f"같은 현지 시각의 발표가 한국 시각으로 1시간 {later}.")
    return "시간대 규칙(서머타임) — " + " ".join(lines)


def change_rows(day: date) -> List[List[str]]:
    """전환이 있는 시간대의 지표를 현지 발표 시각별로 묶어 바뀌기 전·뒤 한국 시각."""
    rows = [["현지 발표 시각", "지표", "바뀌기 전 한국 시각", "바뀐 뒤 한국 시각", "바뀌는 날(현지)"]]
    for tz, label in ZONES:
        for t in transitions(tz, day):
            groups: Dict[str, List[str]] = {}
            for ind in INDICATORS:
                if ind.tz == tz and ind.time:
                    groups.setdefault(ind.time, []).append(ind.short)
            for hhmm, names in sorted(groups.items()):
                before = _at(t["date"] - timedelta(days=2), hhmm, tz)
                after = _at(t["date"] + timedelta(days=2), hhmm, tz)
                rows.append([f"{hhmm} {label}", "·".join(names), _kst_label(before), _kst_label(after), f"{t['date']:%Y-%m-%d}"])
    return rows


def _num(v: Optional[float], ev: MarketEvent) -> str:
    if v is None:
        return ""
    d = ev.decimals if ev.decimals is not None else 1
    return f"{v:,.{d}f}{ev.unit if ev.unit == '%' else (' ' + ev.unit if ev.unit else '')}"


def schedule_rows(day: date, as_of: Optional[str] = None) -> Tuple[List[List[str]], List[Dict[str, Any]]]:
    """오늘(한국 날짜)부터 DAYS 일의 발표 일정 표 + 원본 항목. as_of 면 그 뒤에 나온 발표값은 비운다(날짜 지정 재현)."""
    start = datetime.combine(day, time(0), tzinfo=KST).astimezone(timezone.utc).replace(tzinfo=None)
    end = start + timedelta(days=DAYS)
    cut = datetime.combine(date.fromisoformat(as_of), time(23, 59), tzinfo=KST).astimezone(timezone.utc).replace(tzinfo=None) if as_of else None
    rows = [["날짜(한국)", "한국 시각", "현지 시각", "국가", "지표", "대상 기간", "이전", "예상", "발표", "발표 기관"]]
    raw: List[Dict[str, Any]] = []
    with Session(engine) as s:
        evs = s.exec(select(MarketEvent).where(MarketEvent.at >= start, MarketEvent.at < end).order_by(MarketEvent.at)).all()
    for ev in evs:
        ind = BY_ID.get(ev.indicator_id or "")
        at = ev.at.replace(tzinfo=timezone.utc)
        k = at.astimezone(KST)
        local = at.astimezone(ZoneInfo(ev.tz)) if ev.tz else k
        shown = ev.actual if ev.actual is not None and not (cut and ev.released_at and ev.released_at > cut) else None
        rows.append([f"{k:%m/%d}({_WD[k.weekday()]})", f"{k:%H:%M}" if ev.time_known else "미정",
                     f"{local:%m/%d %H:%M} {local.tzname()}" if ev.time_known and ev.tz and ev.tz != "Asia/Seoul" else "",
                     COUNTRY_KO.get(ev.country, ev.country), ind.short if ind else ev.title, ev.period or "", _num(ev.previous, ev), _num(ev.forecast, ev), _num(shown, ev),
                     ind.agency if ind else ""])
        raw.append({"id": ev.id, "title": ev.title, "at": ev.at.isoformat(), "tz": ev.tz, "timeKnown": ev.time_known, "period": ev.period, "previous": ev.previous,
                    "forecast": ev.forecast, "actual": shown, "source": ev.source, "sourceUrl": ev.source_url})
    return rows, raw


def build(as_of: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """→ make_snapshot 에 넘길 {day, paras, raw} (일정이 하나도 없으면 None)."""
    day = date.fromisoformat(as_of) if as_of else datetime.now(KST).date()
    rows, raw = schedule_rows(day, as_of)
    changes = change_rows(day)
    method = ("작성 방법 — 이 문서의 한국 시각은 각 기관 공식 발표 일정표(BLS·BEA·Census·노동부·연준·ECB·국가데이터처·한국은행)와 FRED 발표일의 "
              "현지 발표 시각을 발표일 당일의 시간대 규칙(IANA 시간대 DB)으로 한국 시각(KST, UTC+9)으로 바꾼 값이다. 서머타임이 바뀌는 주에도 "
              "발표일마다 따로 계산하므로, 같은 현지 시각이라도 전환일 앞뒤의 한국 시각이 다르다.")
    paras: List[Dict[str, Any]] = [{"kind": "prose", "heading": f"경제 일정 {day}", "text": method}, {"kind": "prose", "heading": "시간대 규칙", "text": rule_text(day)}]
    if len(changes) > 1:
        paras.append({"kind": "table", "heading": "시간대 변경 — 같은 현지 시각, 바뀌는 한국 시각", "rows": changes, "text": "\n".join(" | ".join(r) for r in changes)})
    if len(rows) > 1:
        paras.append({"kind": "table", "heading": f"이번 주 발표 일정 ({day:%m/%d}부터 {DAYS}일, 한국 시각)", "rows": rows, "text": "\n".join(" | ".join(r) for r in rows)})
    if len(rows) <= 1 and len(changes) <= 1:
        return None
    zones = [{"tz": tz, "label": label, "transitions": [{"date": t["date"].isoformat(), "end": t["end"], "before": [t["before"][0], _utc_label(t["before"][1])],
                                                         "after": [t["after"][0], _utc_label(t["after"][1])]} for t in transitions(tz, day)]} for tz, label in ZONES]
    return {"day": day.isoformat(), "paras": paras, "raw": {"day": day.isoformat(), "zones": zones, "events": raw}}


__all__ = ["build", "transitions", "rule_text", "change_rows", "schedule_rows"]
