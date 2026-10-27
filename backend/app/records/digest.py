"""기록 비서 — 채널 대화에서 결정·지시·방침·할 일·미결 질문을 뽑아 **기록 후보**로 올린다. 사람이 확인해야 팀 기록이 된다.

네 부분으로 나눴다(확장 자리) — 새 기능은 조합만 바꾼다:
  언제(trigger)  v1: 매일 퇴근 시각 배치(scheduler) + 소유자의 "지금 실행"(데모·테스트)   → 향후: 즉시 기록, 회의 종료, 주간
  범위(scope)    v1: 지난 실행이 끝난 지점(처리 커서) ~ 지금의 채널 메시지                 → 향후: 지정한 시간대, 스레드
  뽑을 것        v1: DIGEST_SYSTEM(5종)                                                      → 향후: 사용자 정의 기록 종류
  보낼 곳        v1: 후보함(team_record status=candidate)                                     → 향후: 경과 문서, 사내 메신저
원문 보존: 기록마다 근거 메시지의 원문·발언자·시각을 quotes 로(LLM 요약 text 와 따로). 발언자는 LLM 이 아니라 메시지 작성자에서.
실패하면 실행 기록(batch_run)에 남기고 커서를 넘기지 않는다(다음 실행이 같은 범위를 다시 본다). 이미 기록에 쓰인 메시지는 다시 후보로 만들지 않는다.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlmodel import Session, select

from app.db import BatchRun, ChannelMessage, Repo, TeamRecord, User, Workspace, engine, iso, utcnow
from app.ids import id36
from app.llm.base import ChatParams

log = logging.getLogger(__name__)

JOB = "record_digest"
BUNDLE_GAP = timedelta(minutes=30)
BUNDLE_MAX = 40
RECORD_TYPES = ("decision", "directive", "convention", "todo", "question")

DIGEST_SYSTEM = """너는 투자 실무 팀의 기록 비서다. 팀 채널 대화 묶음을 읽고, 나중에 다시 찾아야 할 것만 기록 후보로 뽑는다. JSON 하나만 출력한다(설명·코드블록 없이).
{"records": [{"type": "decision|directive|convention|todo|question", "text": "한 문장 정리(대화 표현을 살려서)", "messages": ["m3"], "scope": "적용 범위(섹션·주제, 없으면 빈 문자열)", "assignee": "할 일 담당자 이름(todo 일 때, 없으면 빈 문자열)", "due": "YYYY-MM-DD 또는 빈 문자열"}]}
종류
- decision: 정한 것(어떤 값·기준·방향을 쓰기로 함) / directive: 누가 해 달라고 지시·요청한 작업 방식 / convention: 앞으로 지킬 표기·단위·기준
- todo: 담당자와 할 일이 분명한 것(누구에게 무엇을 언제까지 — 이름을 부른 요청) / question: 아직 답이 없는 질문
규칙
- 근거 메시지 번호(messages)는 대화 묶음에 실제로 있는 m번호만. 지어내지 않는다.
- 한 메시지에 서로 다른 결정·지시·방침이 여럿이면 각각 따로 뽑는다(예: "시나리오를 넣자. 단위는 억원으로" → directive 하나 + convention 하나).
- 인사·잡담·확인 응답("네", "감사합니다")은 뽑지 않는다. 같은 내용은 하나로.
- "@에이전트"에게 묻는 질문은 에이전트가 답하므로 question 으로 뽑지 않는다.
- 날짜는 대화 시각과 '오늘' 기준으로 YYYY-MM-DD 로 바꾼다(연도를 지어내지 않는다).
- 기록할 것이 없으면 {"records": []}."""


# ── 범위 ────────────────────────────────────────────────────────────────

@dataclass
class Scope:
    start: Optional[datetime]  # 이 시각 다음부터(None = 처음부터)
    end: datetime


def cursor_scope(session: Session, workspace_id: str, now: Optional[datetime] = None) -> Scope:
    """v1 범위 — 마지막으로 성공한 실행의 cursor_to 다음부터 지금까지."""
    last = session.exec(
        select(BatchRun).where(BatchRun.workspace_id == workspace_id, BatchRun.job == JOB, BatchRun.status == "ok").order_by(BatchRun.cursor_to.desc())  # type: ignore[attr-defined]
    ).first()
    return Scope(start=last.cursor_to if last else None, end=now or utcnow())


def scope_messages(session: Session, workspace_id: str, scope: Scope) -> List[ChannelMessage]:
    q = select(ChannelMessage).where(ChannelMessage.workspace_id == workspace_id, ChannelMessage.kind == "user", ChannelMessage.created_at <= scope.end)
    if scope.start is not None:
        q = q.where(ChannelMessage.created_at > scope.start)
    return list(session.exec(q.order_by(ChannelMessage.created_at)).all())  # type: ignore[attr-defined]


def bundles(msgs: Sequence[ChannelMessage]) -> List[List[ChannelMessage]]:
    out: List[List[ChannelMessage]] = []
    cur: List[ChannelMessage] = []
    for m in msgs:
        if cur and (m.created_at - cur[-1].created_at > BUNDLE_GAP or len(cur) >= BUNDLE_MAX):
            out.append(cur)
            cur = []
        cur.append(m)
    if cur:
        out.append(cur)
    return out


# ── 뽑을 것 ─────────────────────────────────────────────────────────────

def _parse(raw: str) -> List[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return []
    try:
        v = json.loads(m.group(0))
    except ValueError:
        return []
    return [x for x in (v.get("records") if isinstance(v, dict) else None) or [] if isinstance(x, dict)]


def _local(dt: datetime) -> datetime:
    from app.scheduler import local_tz

    return dt.replace(tzinfo=timezone.utc).astimezone(local_tz())


async def extract_records(llm: Any, bundle: Sequence[ChannelMessage], names: Dict[str, str]) -> List[Dict[str, Any]]:
    from app.scheduler import local_now

    numbered = {f"m{i}": m for i, m in enumerate(bundle, 1)}
    convo = "\n".join(f"[{k}] {names.get(m.user_id or '', '?')} ({_local(m.created_at).strftime('%Y-%m-%d %H:%M')}): {m.text}" for k, m in numbered.items())
    today = local_now().strftime("%Y-%m-%d (%a)")
    system = f"{DIGEST_SYSTEM}\n오늘: {today}"
    res = await llm.complete("chat", ChatParams(messages=[{"role": "system", "content": system}, {"role": "user", "content": convo}], temperature=0.0, max_tokens=3000, reasoning_effort="low", timeout_s=180))
    out = []
    for x in _parse(res.content):
        refs = [str(r) for r in (x.get("messages") or []) if str(r) in numbered]
        typ = str(x.get("type") or "")
        text = str(x.get("text") or "").strip()
        if not refs or typ not in RECORD_TYPES or not text:
            continue  # 근거 메시지가 없는 후보는 버린다(지어낸 기록 방지)
        if typ == "question" and all((numbered[r].meta or {}).get("askAgent") for r in refs):
            continue  # 에이전트에게 물은 질문은 에이전트가 답했다
        if typ == "directive" and str(x.get("assignee") or "").strip():
            typ = "todo"  # 담당자가 정해진 요청은 할 일(확정하면 작업 항목이 된다)
        out.append({"type": typ, "text": text[:300], "messages": [numbered[r] for r in refs], "scope": str(x.get("scope") or "").strip()[:80], "assignee": str(x.get("assignee") or "").strip(), "due": str(x.get("due") or "").strip()[:10]})
    return out


# ── 실행 ────────────────────────────────────────────────────────────────

async def run_digest(workspace_id: str, trigger: str = "schedule", scope: Optional[Scope] = None) -> Dict[str, Any]:
    """언제(trigger)·범위(scope) → 뽑기 → 후보함. → 실행 기록 뷰."""
    from app.llm.client import ReportLlm, provider_ready

    with Session(engine) as s:
        sc = scope or cursor_scope(s, workspace_id)
        run = BatchRun(id=id36("b", 4), workspace_id=workspace_id, job=JOB, trigger=trigger, status="running", cursor_from=sc.start, cursor_to=None)
        Repo(s).save(run)
        msgs = scope_messages(s, workspace_id, sc)
        used = {q.get("messageId") for r in s.exec(select(TeamRecord).where(TeamRecord.workspace_id == workspace_id)).all() for q in (r.quotes or [])}
        names = {u.id: f"{u.name} {u.title}".strip() for u in s.exec(select(User)).all()}
        members = {u.name: u.id for u in s.exec(select(User)).all() if Repo(s).membership(workspace_id, u.id)}
        run_id = run.id
    made = 0
    try:
        if msgs and not provider_ready():
            return _finish(run_id, "skipped", sc, len(msgs), 0, "모델 키가 없어 기록을 뽑지 못했습니다(backend/.env 의 NVIDIA_API_KEY).", advance=False)
        llm = ReportLlm() if msgs else None
        for b in bundles(msgs):
            for rec in await extract_records(llm, b, names):
                ids = [m.id for m in rec["messages"]]
                if any(i in used for i in ids):
                    continue
                first = rec["messages"][0]
                with Session(engine) as s:
                    Repo(s).save(
                        TeamRecord(
                            id=id36("k", 4),
                            workspace_id=workspace_id,
                            type=rec["type"],
                            text=rec["text"],
                            quotes=[{"messageId": m.id, "userId": m.user_id, "author": names.get(m.user_id or "", ""), "text": m.text, "at": iso(m.created_at)} for m in rec["messages"]],
                            author_id=first.user_id,
                            scope=rec["scope"],
                            status="candidate",
                            source={"kind": "batch", "trigger": trigger, "assigneeId": members.get(rec["assignee"].split(" ")[0]) if rec["assignee"] else None, "due": rec["due"]},
                            batch_id=run_id,
                        )
                    )
                used.update(ids)
                made += 1
        return _finish(run_id, "ok", sc, len(msgs), made, None, advance=True)
    except Exception as e:  # noqa: BLE001
        log.exception("[records] digest failed for %s", workspace_id)
        return _finish(run_id, "error", sc, len(msgs), made, str(e)[:300], advance=False)


def _finish(run_id: str, status: str, sc: Scope, processed: int, candidates: int, error: Optional[str], advance: bool) -> Dict[str, Any]:
    with Session(engine) as s:
        run = s.get(BatchRun, run_id)
        if run is None:
            return {}
        run.status, run.processed, run.candidates, run.error, run.finished_at = status, processed, candidates, error, utcnow()
        run.cursor_to = sc.end if advance else None  # 실패·건너뜀이면 커서를 넘기지 않는다
        s.add(run)
        s.commit()
        s.refresh(run)
        return run_view(run)


def run_view(r: BatchRun) -> Dict[str, Any]:
    return {
        "id": r.id,
        "job": r.job,
        "trigger": r.trigger,
        "status": r.status,
        "processed": r.processed,
        "candidates": r.candidates,
        "error": r.error,
        "cursorFrom": iso(r.cursor_from),
        "cursorTo": iso(r.cursor_to),
        "startedAt": iso(r.started_at),
        "finishedAt": iso(r.finished_at),
    }


def workspaces_with_messages() -> List[Workspace]:
    with Session(engine) as s:
        ids = {m.workspace_id for m in s.exec(select(ChannelMessage).where(ChannelMessage.kind == "user")).all()}
        return [w for w in (s.get(Workspace, i) for i in ids) if w is not None]
