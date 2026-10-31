"""품질·이용 지표 — 전부 코드 계산(LLM 0회). 지표마다 {id, label, value(0~1 또는 값), display, detail, trace[원자료 줄]}.

- 질의응답 정확도: 평가 세트 채점 결과(app/quality/evals.py) + 답 👍 비율
- 출처 완전성: 최근 문서 본문 숫자 중 자료·계산·입력값으로 이어진 비율(report/number_check.number_report)
- 데이터 갱신율: 예약 수집 소스·시장 시계열 중 주기 안에 갱신된 비율
- 결과물 생성시간: 화면 없이 쓴 문서(루틴·안건) 중앙값 · 대화 턴 중앙값(ActivityEvent)
- 사용자 수정률: AI 가 쓴 섹션(aiDraft) 대 지금 본문 차이(difflib)
- 데이터 오류율: 열린 품질 문제(DataIssue) / 감시 대상(시리즈·소스·문서)
- 양식 유지율: 양식 문서의 쓴 섹션 / 전체 섹션
- 만족도: 👍 / (👍+👎)
이용: 활성 사용자·턴·문서·루틴·수집·LLM 호출·토큰(기능·워크스페이스별), 날짜별 추이.
"""
from __future__ import annotations

import difflib
import json
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app import config
from app.db import ActivityEvent, DataIssue, DataSource, Feedback, MarketStatus, ReportSession, Workspace, engine, scope_ids

EVAL_LAST = config.DATA_DIR / "quality" / "eval_last.json"
USAGE_LOG = config.DATA_DIR / "logs" / "llm_usage.jsonl"
FRESH_H = {"hourly": 2, "daily": 26, "weekdays": 74, "weekly": 8 * 24}
_cache: Dict[str, Any] = {}


def _pct(a: float, b: float) -> Optional[float]:
    return (a / b) if b else None


def _fmt(v: Optional[float]) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def _reports(s: Session, since: datetime) -> List[ReportSession]:
    return list(s.exec(select(ReportSession).where(ReportSession.updated_at >= since.replace(tzinfo=None)).order_by(ReportSession.updated_at.desc()).limit(60)).all())


def _source_complete(s: Session, reports: List[ReportSession]) -> Dict[str, Any]:
    from app.ledger.service import ledger_for
    from app.report.number_check import number_report

    ok = total = 0
    trace = []
    ledgers: Dict[str, Any] = {}
    for r in reports[:20]:
        doc = r.doc or {}
        if not any(sec.get("content") for sec in doc.get("sections") or []):
            continue
        if r.workspace_id not in ledgers:
            ledgers[r.workspace_id] = ledger_for(s, r.workspace_id)
        sm = number_report(doc, ledgers[r.workspace_id])["summary"]
        by = sm["byStatus"]
        good = by.get("source", 0) + by.get("calc", 0) + by.get("input", 0)
        ok, total = ok + good, total + sm["total"]
        if sm["total"]:
            trace.append({"kind": "report", "id": r.id, "ws": r.workspace_id, "label": r.title or "문서", "detail": f"{good}/{sm['total']} · 출처 없음 {by.get('unsourced', 0)} · 원장과 다름 {by.get('mismatch', 0)}", "v": good / sm["total"]})
    trace.sort(key=lambda x: x["v"])
    v = _pct(ok, total)
    return {"id": "source_complete", "label": "출처 완전성", "value": v, "display": _fmt(v), "detail": f"본문 숫자 {total}개 중 {ok}개가 자료·계산·입력값으로 이어짐 · 문서 {len(trace)}건", "trace": trace[:10]}


def _edit_rate(reports: List[ReportSession]) -> Dict[str, Any]:
    diffs, edited, trace = [], 0, []
    for r in reports:
        for sec in (r.doc or {}).get("sections") or []:
            ai = (sec.get("aiDraft") or {}).get("text")
            if not ai or not sec.get("content"):
                continue
            d = 1 - difflib.SequenceMatcher(None, ai, sec["content"], autojunk=False).ratio()
            diffs.append(d)
            if d > 0.02:
                edited += 1
                trace.append({"kind": "section", "id": r.id, "ws": r.workspace_id, "step": sec.get("step"), "label": f"{r.title or '문서'} · {sec.get('title')}", "detail": f"{d * 100:.0f}% 고침", "v": d})
    v = statistics.mean(diffs) if diffs else None
    trace.sort(key=lambda x: -x["v"])
    return {"id": "edit_rate", "label": "사용자 수정률", "value": v, "display": _fmt(v), "detail": f"AI 가 쓴 섹션 {len(diffs)}개 중 {edited}개를 사람이 고침(평균 글자 차이)", "trace": trace[:10]}


def _format_keep(reports: List[ReportSession]) -> Dict[str, Any]:
    w = t = 0
    trace = []
    for r in reports:
        if not str(r.report_type or "").startswith(("rt:", "fmt", "format")) and not (r.doc or {}).get("format"):
            continue
        secs = (r.doc or {}).get("sections") or []
        if not secs:
            continue
        done = sum(1 for x in secs if x.get("content"))
        w, t = w + done, t + len(secs)
        trace.append({"kind": "report", "id": r.id, "ws": r.workspace_id, "label": r.title or "문서", "detail": f"{done}/{len(secs)} 섹션", "v": done / len(secs)})
    v = _pct(w, t)
    trace.sort(key=lambda x: x["v"])
    return {"id": "format_keep", "label": "양식 유지율", "value": v, "display": _fmt(v), "detail": f"양식 문서 {len(trace)}건 · 섹션 {t}개 중 {w}개 작성", "trace": trace[:10]}


def _gen_time(s: Session, since: datetime) -> Dict[str, Any]:
    ev = s.exec(select(ActivityEvent).where(ActivityEvent.at >= since.replace(tzinfo=None), ActivityEvent.kind.in_(["doc_generated", "turn"]))).all()
    docs = [e for e in ev if e.kind == "doc_generated" and (e.meta or {}).get("sec")]
    turns = [float(e.meta["sec"]) for e in ev if e.kind == "turn" and (e.meta or {}).get("sec")]
    per_sec = [float(e.meta["sec"]) / max(1, int(e.meta.get("sections") or 1)) for e in docs if int(e.meta.get("sections") or 0) > 0]
    md = statistics.median(per_sec) if per_sec else None
    mt = statistics.median(turns) if turns else None
    trace = [{"kind": "report", "id": (e.ref or {}).get("sessionId"), "ws": e.workspace_id, "label": f"문서 생성 {e.meta.get('sections')}섹션", "detail": f"{float(e.meta['sec']):.0f}초", "v": float(e.meta["sec"])} for e in docs[-10:]]
    disp = f"섹션당 {md:.0f}초" if md is not None else (f"턴 {mt:.0f}초" if mt is not None else "—")
    turn = f" · 대화 턴 {len(turns)}건 중앙값 {mt:.0f}초" if mt is not None else ""
    return {"id": "gen_time", "label": "결과물 생성시간", "value": md, "display": disp, "detail": f"화면 없이 쓴 문서 {len(docs)}건(섹션당 중앙값){turn}", "trace": trace}


def _freshness(s: Session) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    trace, ok, total = [], 0, 0
    for src in s.exec(select(DataSource).where(DataSource.enabled == True)).all():  # noqa: E712
        every = (src.schedule or {}).get("every") or "daily"
        if every == "manual":
            continue
        total += 1
        last = _aware(src.last_run_at)
        fresh = bool(last and now - last <= timedelta(hours=FRESH_H.get(every, 26)))
        ok += fresh
        if not fresh:
            trace.append({"kind": "source", "id": src.id, "label": src.name, "detail": f"마지막 수집 {last.date() if last else '없음'} · {every}"})
    for st in s.exec(select(MarketStatus)).all():
        total += 1
        last = _aware(st.last_ok_at)
        fresh = bool(last and now - last <= timedelta(hours=26)) and not st.last_error
        ok += fresh
        if not fresh:
            trace.append({"kind": "series", "id": st.series_id, "label": st.series_id, "detail": f"마지막 갱신 {last.date() if last else '없음'}{' · 오류' if st.last_error else ''}"})
    v = _pct(ok, total)
    return {"id": "freshness", "label": "데이터 갱신율", "value": v, "display": _fmt(v), "detail": f"예약 소스·시장 시계열 {total}개 중 {ok}개가 주기 안에 갱신", "trace": trace[:12]}


def _data_error(s: Session) -> Dict[str, Any]:
    open_ = s.exec(select(DataIssue).where(DataIssue.resolved_at == None)).all()  # noqa: E711
    n_series = len(s.exec(select(MarketStatus)).all())
    n_src = len(s.exec(select(DataSource)).all())
    docs = set()
    for w in s.exec(select(Workspace)).all():
        docs.update(scope_ids(w))
    base = n_series + n_src + len(docs)
    by = Counter(i.kind for i in open_)
    v = _pct(len(open_), base)
    trace = [{"kind": "issue", "id": i.id, "label": i.kind, "detail": str((i.detail or {}).get("text") or (i.detail or {}).get("message") or i.series_id or i.doc_id or "")[:80]} for i in open_[:12]]
    return {"id": "data_error", "label": "데이터 오류율", "value": v, "display": _fmt(v), "detail": f"열린 문제 {len(open_)}건 / 감시 대상 {base}(시리즈 {n_series}·소스 {n_src}·문서 {len(docs)}) · " + ", ".join(f"{k} {n}" for k, n in by.most_common(4)), "trace": trace}


def _satisfaction(s: Session, since: datetime) -> Dict[str, Any]:
    fb = s.exec(select(Feedback).where(Feedback.updated_at >= since.replace(tzinfo=None), Feedback.thumbs != 0)).all()
    up = sum(1 for f in fb if f.thumbs > 0)
    v = _pct(up, len(fb))
    by = Counter((f.target_kind, f.thumbs > 0) for f in fb)
    trace = [{"kind": "feedback", "id": f.id, "label": f.target_kind, "detail": ("👍" if f.thumbs > 0 else "👎") + (f" {f.comment[:60]}" if f.comment else "")} for f in fb if f.thumbs < 0][:10]
    return {"id": "satisfaction", "label": "만족도", "value": v, "display": _fmt(v), "detail": f"👍 {up} · 👎 {len(fb) - up}" + "".join(f" · {k} {'👍' if g else '👎'}{n}" for (k, g), n in sorted(by.items())), "trace": trace}


def _qa(fb_answers: Dict[str, int]) -> Dict[str, Any]:
    last = None
    try:
        last = json.loads(EVAL_LAST.read_text(encoding="utf-8")) if EVAL_LAST.exists() else None
    except (OSError, ValueError):
        last = None
    parts, v = [], None
    if last:
        qa, asm = last.get("qa") or {}, last.get("assumption") or {}
        tot = (qa.get("total") or 0) + (asm.get("total") or 0)
        v = _pct((qa.get("correct") or 0) + (asm.get("correct") or 0), tot)
        parts.append(f"평가 세트 {last.get('at', '')[:10]} — 질의 {qa.get('correct', 0)}/{qa.get('total', 0)} · 가정 판정 {asm.get('correct', 0)}/{asm.get('total', 0)}")
    up, down = fb_answers.get("up", 0), fb_answers.get("down", 0)
    if up + down:
        parts.append(f"답 👍 {up}/{up + down}")
    trace = [{"kind": "eval", "id": c.get("id"), "label": c.get("q") or c.get("id"), "detail": f"{'맞음' if c.get('ok') else '틀림'} · 기대 {c.get('expect')} · 얻은 값 {c.get('got')}"} for c in ((last or {}).get("cases") or [])]
    return {"id": "qa_accuracy", "label": "질의응답 정확도", "value": v, "display": _fmt(v), "detail": " · ".join(parts) or "평가 세트를 아직 돌리지 않음", "trace": trace}


def _usage(s: Session, since: datetime) -> Dict[str, Any]:
    ev = s.exec(select(ActivityEvent).where(ActivityEvent.at >= since.replace(tzinfo=None))).all()
    users = {e.user_id for e in ev if e.user_id}
    kinds = Counter(e.kind for e in ev)
    by_day: Dict[str, Counter] = defaultdict(Counter)
    for e in ev:
        by_day[e.at.strftime("%Y-%m-%d")][e.kind] += 1
    calls = Counter()
    tokens = Counter()
    by_ws = Counter()
    llm_day: Counter = Counter()
    cutoff = since.strftime("%Y-%m-%dT%H:%M:%S")
    if USAGE_LOG.exists():
        with open(USAGE_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if (r.get("at") or "") < cutoff:
                    continue
                feat = r.get("feature") or "구분 없음"
                calls[feat] += 1
                tokens[feat] += int(r.get("prompt") or 0) + int(r.get("completion") or 0)
                by_ws[r.get("ws") or "—"] += 1
                llm_day[(r.get("at") or "")[:10]] += 1
                if r.get("user"):
                    users.add(r["user"])
    days = sorted(set(by_day) | set(llm_day))
    return {"activeUsers": len(users), "turns": kinds.get("turn", 0), "docs": kinds.get("doc_generated", 0), "routineRuns": kinds.get("routine_run", 0), "sourceRuns": kinds.get("source_run", 0),
            "llmCalls": sum(calls.values()), "tokens": sum(tokens.values()),
            "byFeature": [{"feature": k, "calls": n, "tokens": tokens[k]} for k, n in calls.most_common(12)],
            "byWorkspace": [{"workspaceId": k, "calls": n} for k, n in by_ws.most_common(8)],
            "trend": [{"date": d, "turns": by_day[d].get("turn", 0), "docs": by_day[d].get("doc_generated", 0), "llmCalls": llm_day.get(d, 0)} for d in days[-30:]]}


def compute(days: int = 7) -> Dict[str, Any]:
    key = f"q:{days}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))
    with Session(engine) as s:
        reports = _reports(s, since)
        fb = s.exec(select(Feedback).where(Feedback.target_kind == "answer", Feedback.thumbs != 0)).all()
        metrics = [
            _qa({"up": sum(1 for f in fb if f.thumbs > 0), "down": sum(1 for f in fb if f.thumbs < 0)}),
            _source_complete(s, reports),
            _freshness(s),
            _gen_time(s, since),
            _edit_rate(reports),
            _data_error(s),
            _format_keep(reports),
            _satisfaction(s, since),
        ]
        usage = _usage(s, since)
    out = {"days": days, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "metrics": metrics, "usage": usage}
    _cache[key] = (time.monotonic(), out)
    return out


def widget_metrics(ids: List[str]) -> List[Dict[str, Any]]:
    ms = compute(7)["metrics"]
    pick = [m for m in ms if not ids or m["id"] in ids]
    return [{"id": m["id"], "label": m["label"], "value": m["display"], "detail": m["detail"]} for m in pick]
