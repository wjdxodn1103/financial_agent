"""SQLite + SQLModel. 워크스페이스·멤버·리포트 세션·인제스트 작업·채널·팀 기록·작업 항목·배치 실행·검수를 행으로 둔다.
리포트 세션은 문서(doc) JSON 통째로. 문서(업로드 자료)의 정본은 파일(DOCUMENTS_DIR/<id>/)이고 DB 에는 두지 않는다.

주의(OP 에서 겪은 것):
 - JSON 컬럼은 값 비교로 변경을 잡는다 — 커밋된 값을 제자리에서 고치지 말고 새 dict/list 를 대입한다.
 - 요청 세션(SessionDep)을 SSE 스트림에 끌고 가지 않는다(커넥션 풀 고갈로 앱 전체가 멈춘다).
 - 시각은 naive UTC 로 저장한다(SQLite 가 tz 를 버린다 — 읽은 값과 새 값을 비교할 수 있게).
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Iterator, List, Optional

from fastapi import Depends
from sqlalchemy import Column, event
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.types import JSON
from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.config import DB_PATH

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 30}, pool_size=5, max_overflow=10)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    # 예약 작업(수집·루틴)과 화면 요청이 같이 쓴다 — WAL 이면 읽기가 쓰기를 기다리지 않는다
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def _json(default: Any) -> Any:
    return Field(default_factory=lambda: type(default)(default), sa_column=Column(JSON))


def set_json(row: Any, field: str, value: Any) -> None:
    """JSON 열에 새 값을 넣는다 — 제자리에서 고친 dict 도 변경으로 잡히게 복사해 대입하고 표시한다."""
    setattr(row, field, copy.deepcopy(value))
    flag_modified(row, field)


# ── 사람·워크스페이스 ───────────────────────────────────────────────────

class User(SQLModel, table=True):
    __tablename__ = "user"

    id: str = Field(primary_key=True)
    name: str
    title: str = ""  # 직함
    created_at: datetime = Field(default_factory=utcnow)


class Workspace(SQLModel, table=True):
    __tablename__ = "workspace"

    id: str = Field(primary_key=True)
    name: str
    kind: str = "free"  # deal | quarterly | regulation | free
    description: str = ""
    document_ids: List[str] = _json([])
    settings: Dict[str, Any] = _json({})
    created_by: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


def excluded_ids(ws: Optional[Workspace]) -> List[str]:
    """이 워크스페이스에서 AI 가 쓰지 않기로 한 데이터 — 사내 공용·워크스페이스 데이터 모두(settings.evidenceExcluded).
    검수 대상 초안은 검수를 시작하면 자동으로 들어간다."""
    return list(((ws.settings if ws else None) or {}).get("evidenceExcluded") or [])


def scope_ids(ws: Optional[Workspace]) -> List[str]:
    """이 워크스페이스가 볼 수 있는 데이터 — 사내 공용 데이터(모든 워크스페이스 기본) + 이 워크스페이스에 올린 것.
    사내 것이 앞이다(같은 시트가 겹치면 뒤쪽 = 워크스페이스 것을 쓴다)."""
    return list(dict.fromkeys([*company_ids(), *((ws.document_ids if ws else None) or [])]))


def evidence_ids(ws: Optional[Workspace]) -> List[str]:
    """AI 가 참고하는 데이터 — 볼 수 있는 데이터에서 이 워크스페이스가 끈 것을 뺀다. 원장·리포트 작성·채팅 에이전트·검수 대조가 이것만 본다(검색·원문 보기는 전부)."""
    off = set(excluded_ids(ws))
    return [d for d in scope_ids(ws) if d not in off]


def set_excluded(ws: Workspace, doc_id: str, excluded: bool) -> None:
    ids = [d for d in excluded_ids(ws) if d != doc_id] + ([doc_id] if excluded else [])
    ws.settings = {**(ws.settings or {}), "evidenceExcluded": ids}  # 새 dict 대입(JSON 컬럼 변경)


class Membership(SQLModel, table=True):
    __tablename__ = "membership"

    workspace_id: str = Field(primary_key=True)
    user_id: str = Field(primary_key=True)
    role: str = "viewer"  # owner | editor | reviewer | viewer
    last_seen_at: Optional[datetime] = None
    visit_since: Optional[datetime] = None  # 이번 방문의 브리핑 기준(직전 방문의 마지막 시각) — 방문 안에서는 고정
    created_at: datetime = Field(default_factory=utcnow)


# ── 리포트·자료 ─────────────────────────────────────────────────────────

class ReportSession(SQLModel, table=True):
    __tablename__ = "report_session"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True, default="")
    created_by: str = ""
    title: str = ""
    report_type: str = "equity"
    written: int = 0
    doc: Dict[str, Any] = _json({})
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class IngestJob(SQLModel, table=True):
    __tablename__ = "ingest_job"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    uploaded_by: str = ""
    file_name: str = ""
    src_path: str = ""
    status: str = "queued"  # queued | processing | done | error
    error: Optional[str] = None
    doc_id: Optional[str] = None
    replaces: Optional[str] = None  # 새 판으로 올린 경우 이전 판 doc_id
    folder_id: Optional[str] = None  # 드라이브 폴더에 올린 경우 — 처리가 끝나면 그 폴더에 놓인다
    created_at: datetime = Field(default_factory=utcnow)


class LibraryItem(SQLModel, table=True):
    """공용 자료실 — 조직이 같이 쓰는 자료 선반(검색 범위가 아니다: 워크스페이스가 골라 붙여야 쓴다)."""

    __tablename__ = "library_item"

    id: str = Field(primary_key=True)
    doc_id: str = Field(index=True, unique=True)
    note: str = ""
    published_by: str = ""
    from_workspace_id: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class CompanyDocument(SQLModel, table=True):
    """사내 공용 데이터 — 회사가 미리 넣어 둔 데이터. 모든 워크스페이스의 기본 범위이고, 워크스페이스는 끄기만 한다."""

    __tablename__ = "company_document"

    doc_id: str = Field(primary_key=True)
    added_by: str = ""
    created_at: datetime = Field(default_factory=utcnow)


COMPANY_SCOPE = "__company__"  # 인제스트 작업의 workspace_id 자리 — 사내 공용 데이터로 올린 파일


def company_rows() -> List[CompanyDocument]:
    with Session(engine) as s:
        return list(s.exec(select(CompanyDocument).order_by(CompanyDocument.created_at)))  # type: ignore[arg-type]


def company_ids() -> List[str]:
    return [r.doc_id for r in company_rows()]


class DriveFolder(SQLModel, table=True):
    """워크스페이스 드라이브 폴더 — 문서(리포트)·데이터를 함께 담는다. access = all(멤버 전체) | private(만든 사람만) | members(고른 멤버 + 만든 사람)."""

    __tablename__ = "drive_folder"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    parent_id: Optional[str] = None
    name: str = ""
    access: str = "all"
    member_ids: List[str] = _json([])
    created_by: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DriveItem(SQLModel, table=True):
    """드라이브에서 문서·데이터의 자리 — 행이 없으면 맨 위(드라이브 루트)."""

    __tablename__ = "drive_item"

    workspace_id: str = Field(primary_key=True)
    item_id: str = Field(primary_key=True)  # 데이터 doc id · 리포트 id · 리서치 표 id
    kind: str = "data"  # data | doc | table
    folder_id: Optional[str] = None


class DocVersion(SQLModel, table=True):
    """워크스페이스 안 자료 판 묶음 — root_id 가 같으면 한 자료의 판들(version 1, 2, …)."""

    __tablename__ = "doc_version"

    workspace_id: str = Field(primary_key=True)
    doc_id: str = Field(primary_key=True)
    root_id: str = Field(index=True)
    version: int = 1
    prev_id: Optional[str] = None
    created_by: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# ── 협업 ────────────────────────────────────────────────────────────────

class ChannelMessage(SQLModel, table=True):
    __tablename__ = "channel_message"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    user_id: Optional[str] = None  # None = 에이전트·시스템
    kind: str = "user"  # user | agent | system
    text: str = ""
    meta: Dict[str, Any] = _json({})
    thread_id: Optional[str] = None  # 답글이면 스레드 첫 메시지 id(스레드 안의 스레드는 없다)
    created_at: datetime = Field(default_factory=utcnow, index=True)


class TeamRecord(SQLModel, table=True):
    __tablename__ = "team_record"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    type: str = "decision"  # decision | directive | convention | todo | question
    text: str = ""  # 한 문장 정리(에이전트) — 원문은 quotes
    quotes: List[Dict[str, Any]] = _json([])  # [{messageId, userId, text, at}]
    author_id: Optional[str] = None  # 발언자(원문 메시지의 작성자) 또는 카드에서 고른 사람
    scope: str = ""  # 적용 범위(섹션 이름 등, 비우면 워크스페이스 전체)
    status: str = "candidate"  # candidate | confirmed | dismissed | superseded
    source: Dict[str, Any] = _json({})  # {kind: batch|card|manual, ...}
    batch_id: Optional[str] = None
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


class Task(SQLModel, table=True):
    __tablename__ = "task"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    title: str
    detail: str = ""
    assignee_id: Optional[str] = None
    due: str = ""  # YYYY-MM-DD — 마감(기간의 끝)
    start: Optional[str] = None  # YYYY-MM-DD — 기간의 시작(없으면 마감 하루짜리)
    status: str = "todo"  # todo | doing | review | done
    source: Dict[str, Any] = _json({})  # {kind: review|record|manual, reviewId, findingId, recordId}
    created_by: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class BatchRun(SQLModel, table=True):
    __tablename__ = "batch_run"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    job: str  # record_digest …
    trigger: str = "schedule"  # schedule | manual
    status: str = "running"  # running | ok | error | skipped
    cursor_from: Optional[datetime] = None
    cursor_to: Optional[datetime] = None
    processed: int = 0
    candidates: int = 0
    error: Optional[str] = None
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None


class Review(SQLModel, table=True):
    __tablename__ = "review"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    doc_id: str
    status: str = "running"  # running | done | error
    findings: List[Dict[str, Any]] = _json([])
    summary: Dict[str, Any] = _json({})
    error: Optional[str] = None
    created_by: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None


class LedgerChoice(SQLModel, table=True):
    """원장 충돌(같은 지표·기간·기준에 값이 여럿)에서 사람이 채택한 값 — 결정 기록(team_record)과 함께 남긴다."""

    __tablename__ = "ledger_choice"

    workspace_id: str = Field(primary_key=True)
    key: str = Field(primary_key=True)
    figure_id: str
    reason: str = ""
    record_id: Optional[str] = None
    chosen_by: str = ""
    chosen_at: datetime = Field(default_factory=utcnow)


# ── AI 리서치 채팅(1:1) ─────────────────────────────────────────────────

class ResearchChat(SQLModel, table=True):
    """AI 채팅 대화 하나 — 만든 사람만 본다. doc = {history, transcript, dataScope, dataExcluded, currentTableId, tableIds}."""

    __tablename__ = "research_chat"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    created_by: str = ""
    title: str = ""
    doc: Dict[str, Any] = _json({})
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ResearchTable(SQLModel, table=True):
    """AI 채팅이 만든 출처 달린 표. 드라이브에 저장(saved)하면 워크스페이스 멤버가 본다.
    data = {spec, templateId, inputs, subjects, items, cells, period, progress}."""

    __tablename__ = "research_table"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    chat_id: str = Field(index=True, default="")
    created_by: str = ""
    title: str = ""
    status: str = "running"  # running | done | error
    saved: bool = False
    kind: Optional[str] = None  # None = 표 | chart(표에서 만든 차트, data.chart.source = 원 표)
    data: Dict[str, Any] = _json({})
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ResearchTemplate(SQLModel, table=True):
    """표 양식 — scope = company(사내, 모든 워크스페이스) | workspace(그 워크스페이스) | user(만든 사람, 그 워크스페이스).
    사내 기본 양식 몇 개는 코드(research/templates.py BUILTIN)에 있다."""

    __tablename__ = "research_template"

    id: str = Field(primary_key=True)
    scope: str = "user"
    workspace_id: str = Field(index=True, default="")  # company 는 ""
    owner_id: str = ""
    name: str = ""
    spec: Dict[str, Any] = _json({})
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ReportTemplate(SQLModel, table=True):
    """리포트 양식(Word·PDF 샘플에서 등록) — 리포트 종류 id 는 'rt:<id>'. scope 는 표 양식과 같다.
    spec = {desc, sections: [{title, level, guide, slots: [{templateId?, kind: table|chart|figure, title, rows?}]}]} — slots = 섹션 뒤 표·차트 자리."""

    __tablename__ = "report_template"

    id: str = Field(primary_key=True)
    scope: str = "user"
    workspace_id: str = Field(index=True, default="")
    owner_id: str = ""
    name: str = ""
    source_name: str = ""
    spec: Dict[str, Any] = _json({})
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ── 알림·활동·피드백(2026-10-29) ───────────────────────────────────────

class Notification(SQLModel, table=True):
    """알림함 — 받는 사람마다 한 줄. link = 화면 이동({v, s, t, w}), ref = 무엇에 대한 알림인지.
    dedupe_key 가 같은 알림은 같은 사람에게 다시 만들지 않는다(같은 판정·같은 실행이 여러 번 알리지 않게)."""

    __tablename__ = "notification"

    id: str = Field(primary_key=True)
    user_id: str = Field(index=True)
    workspace_id: str = Field(default="", index=True)
    kind: str = "system"  # routine | share | review | assumption | source | dashboard | system
    title: str = ""
    body: str = ""
    link: Dict[str, Any] = _json({})
    ref: Dict[str, Any] = _json({})
    dedupe_key: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    read_at: Optional[datetime] = None


class ActivityEvent(SQLModel, table=True):
    """이용 기록 — 품질·이용 지표(생성 시간·이용 현황)의 원자료. 본문은 남기지 않는다."""

    __tablename__ = "activity_event"

    id: str = Field(primary_key=True)
    at: datetime = Field(default_factory=utcnow, index=True)
    user_id: str = Field(default="", index=True)
    workspace_id: str = Field(default="", index=True)
    kind: str = Field(index=True)  # turn | section_written | doc_created | export | search | routine_run | source_run …
    ref: Dict[str, Any] = _json({})
    meta: Dict[str, Any] = _json({})  # {sec, chars, feature …}


class Feedback(SQLModel, table=True):
    """👍/👎 — 사람·대상마다 하나(다시 누르면 바뀐다). target_kind = answer | section | brief | doc."""

    __tablename__ = "feedback"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(default="", index=True)
    user_id: str = Field(index=True)
    target_kind: str
    target_id: str = Field(index=True)
    thumbs: int = 0  # +1 | -1 | 0(취소)
    score: Optional[int] = None
    comment: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ── 수집·적재 파이프라인·시장 데이터(2026-10-29) ─────────────────────────

class DataSource(SQLModel, table=True):
    """수집 소스 — 사내 공용(scope=company, 관리자)·워크스페이스(편집자 이상). 모은 것은 보통 문서가 되어 AI 검색·작성·원문 창에 그대로 쓰인다.
    kind = edgar(공시) | series(시장·거시 시계열) | rss(공식 보도자료·성명) | folder(서버 수집 폴더 — 사내 자료공유시스템 연계 자리).
    schedule = {every: daily|weekdays|hourly|weekly|manual, times: ["06:30"], weekday: 0~6}."""

    __tablename__ = "data_source"

    id: str = Field(primary_key=True)
    scope: str = "workspace"  # company | workspace
    workspace_id: str = Field(default="", index=True)  # company 는 ""
    kind: str
    name: str = ""
    params: Dict[str, Any] = _json({})
    schedule: Dict[str, Any] = _json({})
    target: Dict[str, Any] = _json({})  # {folderId}
    enabled: bool = True
    created_by: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    last_run_at: Optional[datetime] = None
    status: str = ""  # ok | error | partial | 빈 값(아직)


class SourceRun(SQLModel, table=True):
    __tablename__ = "source_run"

    id: str = Field(primary_key=True)
    source_id: str = Field(index=True)
    trigger: str = "schedule"  # schedule | manual | replay | retry
    as_of: Optional[str] = None
    status: str = "running"  # running | ok | partial | error | skipped
    new: int = 0
    skipped: int = 0
    failed: int = 0
    note: str = ""
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None


class SourceItem(SQLModel, table=True):
    """수집한 항목 하나(공시 한 건·보도자료 한 건·파일 하나·시리즈 갱신 하루). key 는 소스 안에서 유일 — 같은 것을 두 번 적재하지 않는다."""

    __tablename__ = "source_item"

    id: str = Field(primary_key=True)
    source_id: str = Field(index=True)
    key: str = Field(index=True)
    doc_id: Optional[str] = None
    title: str = ""
    url: str = ""
    published_at: Optional[str] = None
    fetched_at: datetime = Field(default_factory=utcnow)
    status: str = "ok"  # ok | error
    error: Optional[str] = None
    retries: int = 0
    meta: Dict[str, Any] = _json({})


class MarketObservation(SQLModel, table=True):
    """시계열 관측값 — (시리즈, 날짜, 공급자, 빈티지)마다 한 줄. 공급자를 섞지 않고 저장해 대조·대체 소스 표시에 쓴다."""

    __tablename__ = "market_observation"

    id: str = Field(primary_key=True)  # series|date|source|vintage
    series_id: str = Field(index=True)
    date: str = Field(index=True)  # YYYY-MM-DD
    source: str = Field(index=True)  # fred | treasury | ecb | nyfed | demo …
    vintage: str = ""  # ALFRED 빈티지(날짜 지정 재현) — 보통 ""
    value: float
    fetched_at: datetime = Field(default_factory=utcnow)


class MarketStatus(SQLModel, table=True):
    __tablename__ = "market_status"

    series_id: str = Field(primary_key=True)
    provider_in_use: str = ""
    fallback: bool = False
    last_ok_at: Optional[datetime] = None
    last_error: Optional[str] = None
    last_date: Optional[str] = None
    providers: Dict[str, Any] = _json({})  # {공급자: {status ok|error|nokey, error, at, rows}}


class PriceBar(SQLModel, table=True):
    """종목 일봉 — (종목, 날짜, 공급자)마다 한 줄. 사내 공용(app/market/prices.py)."""

    __tablename__ = "price_bar"

    id: str = Field(primary_key=True)  # ticker|date|source
    ticker: str = Field(index=True)  # Yahoo 표기(389500.KQ · 005930.KS · AAPL)
    date: str = Field(index=True)  # YYYY-MM-DD(거래소 현지 날짜)
    source: str = "yahoo"
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: float
    adj_close: Optional[float] = None
    volume: Optional[float] = None
    currency: str = ""
    fetched_at: datetime = Field(default_factory=utcnow)


class DataIssue(SQLModel, table=True):
    """데이터 품질 문제 — 결측·이상치·공급자 간 불일치·기준일 지남·단위/주기·문서 숫자 불일치·수집 실패. key 가 같으면 한 줄(해소되면 resolved_at)."""

    __tablename__ = "data_issue"

    id: str = Field(primary_key=True)
    key: str = Field(index=True)
    scope: str = "company"
    workspace_id: str = Field(default="", index=True)
    kind: str  # missing | outlier | disagree | stale | unit | doc_mismatch | ingest_failed
    series_id: Optional[str] = None
    doc_id: Optional[str] = None
    source_id: Optional[str] = None
    detail: Dict[str, Any] = _json({})
    detected_at: datetime = Field(default_factory=utcnow)
    resolved_at: Optional[datetime] = None


# ── 공유·확인(2026-10-29) ─────────────────────────────────────────────

class Share(SQLModel, table=True):
    """보내기 — 드라이브의 문서·데이터·정리한 데이터를 멤버에게(메시지·검토 요청과 함께). 받는 사람은 알림함·홈 '받은 것'에서 연다."""

    __tablename__ = "share"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    item_kind: str  # doc | data | table
    item_id: str
    title: str = ""
    from_user: str = ""
    to_users: List[str] = _json([])
    message: str = ""
    review: bool = False
    created_at: datetime = Field(default_factory=utcnow, index=True)


# ── 대시보드(2026-10-29) ───────────────────────────────────────────────

class DashboardSpec(SQLModel, table=True):
    """대시보드 위젯 구성 — kind = market(전사 시장)|data(전사 데이터 현황)|workspace(워크스페이스 맞춤).
    status = active(지금 쓰는 것)|draft(AI 가 낸 제안 — 제안한 사람이 미리보기 후 승인·버리기)|archived(예전 것)."""

    __tablename__ = "dashboard_spec"

    id: str = Field(primary_key=True)
    scope: str = "company"  # company | workspace
    workspace_id: str = Field(default="", index=True)
    kind: str = Field(index=True)
    status: str = Field(default="active", index=True)
    spec: Dict[str, Any] = _json({})
    prompt: str = ""
    summary: str = ""
    base_id: Optional[str] = None
    created_by: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class MarketBrief(SQLModel, table=True):
    """오늘의 시장 요약 — 사실표(코드가 계산)와 그것을 [F#]로 가리키는 요약·AI 판단 문장. 사실표에 없는 숫자가 든 문장은 뺀다(dropped)."""

    __tablename__ = "market_brief"

    date: str = Field(primary_key=True)
    summary: List[str] = _json([])
    judgement: List[str] = _json([])
    facts: List[Dict[str, Any]] = _json([])
    dropped: List[str] = _json([])
    model: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# ── 루틴(예약 작성, 2026-10-29) ────────────────────────────────────────

class Routine(SQLModel, table=True):
    """반복 작성 업무 — 양식·데이터 범위·지시·일정·올릴 폴더·받는 사람·검토 담당. 만든 사람 이름으로 화면 없이 쓰고(AI 초안) 알린다.
    schedule = {every: daily|weekdays|weekly|manual, time: "07:00", weekday}. call = 대화창 '/' 호출 문구."""

    __tablename__ = "routine"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    name: str = ""
    call: str = ""
    format_id: str = ""
    data_scope: Dict[str, Any] = _json({})
    instruction: str = ""
    schedule: Dict[str, Any] = _json({})
    folder_id: Optional[str] = None
    title_pattern: str = "{name} {date}"
    recipients: Dict[str, Any] = _json({})  # {all: bool, userIds: []}
    reviewer_id: Optional[str] = None
    owner_id: str = ""
    enabled: bool = True
    source: Dict[str, Any] = _json({})  # {kind: chat|task|manual, sessionId}
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    last_run_at: Optional[datetime] = None


class RoutineRun(SQLModel, table=True):
    __tablename__ = "routine_run"

    id: str = Field(primary_key=True)
    routine_id: str = Field(index=True)
    workspace_id: str = Field(default="", index=True)
    trigger: str = "schedule"  # schedule | manual | replay
    as_of: Optional[str] = None
    status: str = "running"  # running | ok | partial | error
    report_id: Optional[str] = None
    written: int = 0
    llm_calls: int = 0
    note: str = ""
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None


# ── 가정 감시(문서 속, 2026-10-29) ────────────────────────────────────

class Assumption(SQLModel, table=True):
    """문서 속 가정 문장 — 투자 결정이 기댄 가정('데이터센터 매출이 연 30% 넘게 성장'). 별도 메뉴 없이 그 문서·알림·홈에서 보인다.
    doc_kind = report(AI 작업 문서) | data(올린 자료). condition = 숫자 가정의 조건(코드 판정). anchor = 그 문장의 원문 위치, basis = 당시 근거."""

    __tablename__ = "assumption"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    doc_kind: str = "report"
    doc_ref: str = Field(index=True)
    step: Optional[str] = None
    quote: str = ""
    anchor: Dict[str, Any] = _json({})
    target: Dict[str, Any] = _json({})  # {name, ticker}
    kind: str = "numeric"  # numeric | qualitative
    condition: Dict[str, Any] = _json({})  # {metric, period: latest_q_yoy|latest_q|latest_fy|latest_fy_yoy, op, threshold, unit}
    basis: List[Dict[str, Any]] = _json([])
    watch: bool = False
    status: str = "candidate"  # candidate | watching | dismissed
    latest: Dict[str, Any] = _json({})  # {result, value, at, changed, acknowledged}
    created_by: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    role: Optional[str] = None  # None = 가정(맞아야 하는 전망) | trigger = 재심의 조건(그렇게 되면 다시 심의) — 판정 낱말이 도달·미도달
    watched_by: Optional[str] = None  # 감시를 켠 사람(알림 받는 사람 = 문서 만든 사람 + 이 사람)


class AssumptionCheck(SQLModel, table=True):
    """판정 이력(덧붙이기만) — 언제·어떤 자료로·어떤 결과·지금 값·근거 앵커."""

    __tablename__ = "assumption_check"

    id: str = Field(primary_key=True)
    assumption_id: str = Field(index=True)
    at: datetime = Field(default_factory=utcnow)
    as_of: Optional[str] = None
    trigger: Dict[str, Any] = _json({})
    result: str = ""  # met | not_met | no_data | support | refute | hold
    value: Dict[str, Any] = _json({})
    anchors: List[Dict[str, Any]] = _json([])
    quote: str = ""
    prev_result: Optional[str] = None
    changed: bool = False


class MarketEvent(SQLModel, table=True):
    """경제 일정 — 지표 발표·중앙은행 회의·휴장·만기. 출처: FRED 발표일·공식 일정표·규칙(만기). 전사 공용(워크스페이스 없음).
    발표되면 실제치를 코드가 기록한다(감지 출처·관측 기간·받은 시각을 detect 에 고정). 예상치는 사람이 넣는다(무료 공식 출처 없음)."""

    __tablename__ = "market_event"

    id: str = Field(primary_key=True)
    key: str = Field(index=True, unique=True)  # 지표id:날짜 · fixed:이름:날짜 · rule:이름:날짜
    country: str = "US"  # KR | US | EU | CN | JP
    category: str = "release"  # release(발표) | meeting(회의) | issue(이슈) | industry(산업) | earnings(실적) | holiday(휴장)
    importance: int = 2  # 1~3
    indicator_id: Optional[str] = Field(default=None, index=True)
    title: str = ""
    period: str = ""  # 대상 기간 '2026년 10월'
    period_key: str = ""  # 감지 기준 '2026-10' · '2026Q3' · 회의는 결정일
    at: datetime = Field(index=True)  # 예정 시각(UTC)
    time_known: bool = True
    tz: str = ""  # 현지 시간대(표시용)
    unit: str = ""
    decimals: int = 1
    previous: Optional[float] = None
    forecast: Optional[float] = None
    forecast_by: Optional[str] = None
    actual: Optional[float] = None
    actual_text: str = ""  # 회의 결정('동결' 등)
    released_at: Optional[datetime] = None
    status: str = "scheduled"  # scheduled | released
    source: str = ""  # fred | fixed | rule
    confirmed: bool = True  # 공식 일정으로 확인(아니면 '공식 확인 전')
    source_url: str = ""
    detect: Dict[str, Any] = _json({})  # 감지 기록 {via, url, obs, fetchedAt, polls, lastPollAt}
    meta: Dict[str, Any] = _json({})
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class EventAlert(SQLModel, table=True):
    """일정 알림 등록 — 일정 하나(event_id) 또는 지표의 다음 발표마다(indicator_id + repeat). 발표가 감지되면 코드가 양식대로 만든 메시지를 보낸다(AI 없음).
    recipients = {all: 워크스페이스 전원, users: [id]}, channels = {inbox, workspace(채널 메시지), webhook}."""

    __tablename__ = "event_alert"

    id: str = Field(primary_key=True)
    workspace_id: str = Field(index=True)
    user_id: str = ""
    event_id: Optional[str] = Field(default=None, index=True)
    indicator_id: Optional[str] = Field(default=None, index=True)
    repeat: bool = False
    recipients: Dict[str, Any] = _json({})
    channels: Dict[str, Any] = _json({})
    enabled: bool = True
    source: Dict[str, Any] = _json({})  # {kind: chat|ui, sessionId}
    last_sent_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """create_all 은 이미 있는 표에 새 열을 넣지 않는다 — DB 를 지우지 않고 빠진 열(전부 비어도 되는 열)만 더한다."""
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            have = {r[1] for r in conn.exec_driver_sql(f'PRAGMA table_info("{table.name}")')}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}')


def get_session() -> Iterator[Session]:
    with Session(engine) as s:
        yield s


SessionDep = Annotated[Session, Depends(get_session)]


class Repo:
    """행 접근 — 서비스·워커가 같이 쓴다."""

    def __init__(self, session: Session):
        self.s = session

    def save(self, row: Any) -> Any:
        if hasattr(row, "updated_at"):
            row.updated_at = utcnow()
        self.s.add(row)
        self.s.commit()
        self.s.refresh(row)
        return row

    def delete(self, row: Any) -> None:
        self.s.delete(row)
        self.s.commit()

    # 리포트 세션
    def get(self, session_id: str) -> Optional[ReportSession]:
        return self.s.get(ReportSession, session_id)

    def reports(self, workspace_id: str) -> List[ReportSession]:
        return list(self.s.exec(select(ReportSession).where(ReportSession.workspace_id == workspace_id).order_by(ReportSession.updated_at.desc())))  # type: ignore[attr-defined,arg-type]

    # 인제스트 작업
    def jobs(self, workspace_id: str) -> List[IngestJob]:
        return list(self.s.exec(select(IngestJob).where(IngestJob.workspace_id == workspace_id).order_by(IngestJob.created_at)))  # type: ignore[arg-type]

    def pending_jobs(self) -> List[IngestJob]:
        return list(self.s.exec(select(IngestJob).where(IngestJob.status.in_(("queued", "processing"))).order_by(IngestJob.created_at)))  # type: ignore[attr-defined,arg-type]

    def get_job(self, job_id: str) -> Optional[IngestJob]:
        return self.s.get(IngestJob, job_id)

    def save_job(self, row: IngestJob) -> IngestJob:
        return self.save(row)

    def delete_job(self, row: IngestJob) -> None:
        self.delete(row)

    # 워크스페이스
    def workspace(self, workspace_id: str) -> Optional[Workspace]:
        return self.s.get(Workspace, workspace_id)

    def membership(self, workspace_id: str, user_id: str) -> Optional[Membership]:
        return self.s.get(Membership, (workspace_id, user_id))

    def members(self, workspace_id: str) -> List[Membership]:
        return list(self.s.exec(select(Membership).where(Membership.workspace_id == workspace_id).order_by(Membership.created_at)))  # type: ignore[arg-type]

    def my_workspaces(self, user_id: str) -> List[Workspace]:
        ids = [m.workspace_id for m in self.s.exec(select(Membership).where(Membership.user_id == user_id))]
        if not ids:
            return []
        return list(self.s.exec(select(Workspace).where(Workspace.id.in_(ids)).order_by(Workspace.updated_at.desc())))  # type: ignore[attr-defined]

    def users(self) -> List[User]:
        return list(self.s.exec(select(User).order_by(User.created_at)))  # type: ignore[arg-type]

    def user(self, user_id: str) -> Optional[User]:
        return self.s.get(User, user_id)
