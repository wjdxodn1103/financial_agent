"""SQLite + SQLModel. 워크스페이스·멤버·리포트 세션·인제스트 작업·채널·팀 기록·작업 항목·배치 실행·검수를 행으로 둔다.
리포트 세션은 문서(doc) JSON 통째로. 문서(업로드 자료)의 정본은 파일(DOCUMENTS_DIR/<id>/)이고 DB 에는 두지 않는다.

주의(OP 에서 겪은 것):
 - JSON 컬럼은 값 비교로 변경을 잡는다 — 커밋된 값을 제자리에서 고치지 말고 새 dict/list 를 대입한다.
 - 요청 세션(SessionDep)을 SSE 스트림에 끌고 가지 않는다(커넥션 풀 고갈로 앱 전체가 멈춘다).
 - 시각은 naive UTC 로 저장한다(SQLite 가 tz 를 버린다 — 읽은 값과 새 값을 비교할 수 있게).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Iterator, List, Optional

from fastapi import Depends
from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.config import DB_PATH

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False, "timeout": 30}, pool_size=5, max_overflow=10)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def _json(default: Any) -> Any:
    return Field(default_factory=lambda: type(default)(default), sa_column=Column(JSON))


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
