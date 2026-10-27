"""HTTP API — prefix /api. 응답은 camelCase JSON 또는 text/event-stream(리포트 채팅 한 턴).
로그인은 요청 헤더 `X-User-Id`(데모 계정 — app/auth.py). 첫 바이트 전에 알 수 있는 오류는 HTTP, 그 뒤는 SSE error 이벤트.

  /meta · /me
  /workspaces …                    워크스페이스·멤버
  /workspaces/{w}/reports          리포트 목록·만들기
  /workspaces/{w}/documents …      자료(워크스페이스 공유)
  /sessions/{s} …                  리포트 하나(편집·채팅 턴·내보내기)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app import config
from app.auth import ROLE_KO, ROLES, UserDep, user_view
from app.db import Repo, SessionDep
from app.connectors.service import ConnectorService
from app.ledger.export import ledger_xlsx
from app.library import LibraryService
from app.records.progress_doc import progress_docx
from app.search import search_workspace
from app.ledger.service import LedgerService
from app.briefing import briefing
from app.drive import DriveService
from app.mypage import add_todo, delete_todo, my_page, update_mine
from app.channel.service import ChannelService
from app.records.manage import RecordService
from app.review.service import ReviewService
from app.tasks import TaskService
from app.llm.base import LlmError
from app.llm.client import require_provider
from app.services.document_service import DocumentService
from app.services.report_service import ReportService, release_lock, try_lock
from app.services.workspace_service import WORKSPACE_KINDS, WorkspaceService

router = APIRouter(prefix="/api")
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


class SessionCreate(BaseModel):
    title: str = ""
    report_type: str = Field(default="free", alias="reportType")
    folder_id: Optional[str] = Field(default=None, alias="folderId")
    data_scope: Optional[Dict[str, Any]] = Field(default=None, alias="dataScope")
    model_config = ConfigDict(populate_by_name=True)


class WorkspaceCreate(BaseModel):
    name: str
    kind: str = "free"
    description: str = ""


class MemberBody(BaseModel):
    user_id: str = Field(alias="userId")
    role: str = "viewer"
    model_config = ConfigDict(populate_by_name=True)


class RoleBody(BaseModel):
    role: str


class EdgarFetchBody(BaseModel):
    cik: int
    name: str
    year: int


class EcosSeriesBody(BaseModel):
    stat_code: str = Field(alias="statCode")
    stat_name: str = Field(default="", alias="statName")
    item_code: str = Field(alias="itemCode")
    item_name: str = Field(default="", alias="itemName")
    cycle: str
    start: str
    end: str
    model_config = ConfigDict(populate_by_name=True)


class DartFetchBody(BaseModel):
    corp_code: str = Field(alias="corpCode")
    corp_name: str = Field(alias="corpName")
    year: int
    report: str = "annual"
    fs: str = "CFS"
    model_config = ConfigDict(populate_by_name=True)


class ReviewBody(BaseModel):
    doc_id: str = Field(alias="docId")
    model_config = ConfigDict(populate_by_name=True)


class ReviewTasksBody(BaseModel):
    finding_ids: List[str] = Field(alias="findingIds")
    assignee_id: Optional[str] = Field(default=None, alias="assigneeId")
    due: str = ""
    model_config = ConfigDict(populate_by_name=True)


class MessageBody(BaseModel):
    text: str = ""
    attachments: List[str] = []
    thread_id: Optional[str] = Field(default=None, alias="threadId")
    model_config = ConfigDict(populate_by_name=True)


class RecordBody(BaseModel):
    type: str
    text: str
    scope: str = ""


class ConfirmBody(BaseModel):
    text: Optional[str] = None


class TaskBody(BaseModel):
    title: str
    detail: str = ""
    assignee_id: Optional[str] = Field(default=None, alias="assigneeId")
    due: str = ""
    start: str = ""
    model_config = ConfigDict(populate_by_name=True)


class ChooseBody(BaseModel):
    key: str
    figure_id: str = Field(alias="figureId")
    reason: str = ""
    model_config = ConfigDict(populate_by_name=True)


class ApprovalBody(BaseModel):
    approved: bool
    action: str = "plan"
    message_id: Optional[str] = Field(default=None, alias="messageId")
    steps: List[str] = []
    covers: Optional[List[str]] = None
    documents: Optional[List[str]] = None
    instruction: Optional[str] = None
    inputs: Optional[Dict[str, str]] = None
    label: Optional[str] = None
    model_config = ConfigDict(populate_by_name=True)


class NumberConfirmBody(BaseModel):
    confirmed: bool = True
    note: str = ""
    raw: str = ""


class ReviewRequestBody(BaseModel):
    reviewer_id: str = Field(alias="reviewerId")
    note: str = ""
    model_config = ConfigDict(populate_by_name=True)


class PublishBody(BaseModel):
    note: str = ""


class ChatBody(BaseModel):
    text: Optional[str] = None
    approval: Optional[ApprovalBody] = None
    # AI 작업 모드 {research, writing} · 오른쪽 패널에서 보던 표
    modes: Optional[Dict[str, bool]] = None
    table_id: Optional[str] = Field(default=None, alias="tableId")
    # 올린 양식 샘플을 읽는 턴(/imports 로 올린 뒤)
    import_id: Optional[str] = Field(default=None, alias="import")
    model_config = ConfigDict(populate_by_name=True)


# ── 메타·나 ────────────────────────────────────────────────────────────

@router.get("/meta")
def meta(session: SessionDep):
    """로그인 전에도 부른다 — 계정 목록(데모 로그인 화면)·리포트 유형·워크스페이스 유형·역할."""
    return {
        **ReportService.meta(),
        "workspaceKinds": WORKSPACE_KINDS,
        "roles": [{"id": r, "label": ROLE_KO[r]} for r in ROLES],
        "users": [user_view(u) for u in Repo(session).users()],
        "connectors": {"dart": bool(config.DART_API_KEY), "edgar": bool(config.SEC_USER_AGENT), "ecos": bool(config.ECOS_API_KEY)},
    }


@router.get("/me")
def me(user: UserDep):
    return user_view(user)


# ── 워크스페이스 ──────────────────────────────────────────────────────

@router.get("/workspaces")
def list_workspaces(user: UserDep, session: SessionDep):
    return {"workspaces": WorkspaceService(session).list(user)}


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceCreate, user: UserDep, session: SessionDep):
    return WorkspaceService(session).create(user, body.name, body.kind, body.description)


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: str, user: UserDep, session: SessionDep):
    return WorkspaceService(session).detail(workspace_id, user)


@router.patch("/workspaces/{workspace_id}")
def patch_workspace(workspace_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    return WorkspaceService(session).patch(workspace_id, user, body)


@router.post("/workspaces/{workspace_id}/members")
def invite_member(workspace_id: str, body: MemberBody, user: UserDep, session: SessionDep):
    return WorkspaceService(session).invite(workspace_id, user, body.user_id, body.role)


@router.patch("/workspaces/{workspace_id}/members/{member_id}")
def set_member_role(workspace_id: str, member_id: str, body: RoleBody, user: UserDep, session: SessionDep):
    return WorkspaceService(session).set_role(workspace_id, user, member_id, body.role)


@router.delete("/workspaces/{workspace_id}/members/{member_id}")
def remove_member(workspace_id: str, member_id: str, user: UserDep, session: SessionDep):
    return WorkspaceService(session).remove_member(workspace_id, user, member_id)


# ── 리포트 ─────────────────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/reports")
def list_reports(workspace_id: str, user: UserDep, session: SessionDep):
    return {"reports": ReportService(session).list(workspace_id, user)}


@router.post("/workspaces/{workspace_id}/reports", status_code=201)
def create_report(workspace_id: str, body: SessionCreate, user: UserDep, session: SessionDep):
    return ReportService(session).create(workspace_id, user, body.title, body.report_type, body.folder_id, body.data_scope)


@router.get("/sessions/{session_id}")
def get_session(session_id: str, user: UserDep, session: SessionDep):
    return ReportService(session).get_payload(session_id, user)


@router.patch("/sessions/{session_id}")
def patch_session(session_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    return ReportService(session).patch(session_id, user, body)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: str, user: UserDep, session: SessionDep):
    ReportService(session).delete(session_id, user)
    return None


@router.post("/sessions/{session_id}/chat")
async def chat(session_id: str, body: ChatBody, request: Request, user: UserDep, session: SessionDep):
    """한 턴. 사전 확인(권한·키·잠금)만 요청 세션으로 하고 스트림 전에 그 세션을 닫는다 — 분 단위 스트림이 DB 커넥션을 붙잡지 않게."""
    if not (body.text or "").strip() and body.approval is None and not body.import_id:
        return JSONResponse(status_code=400, content={"code": "EMPTY", "message": "보낼 내용이 없습니다."})
    ReportService(session).access(session_id, user, write=True)
    try:
        require_provider()
    except LlmError as e:
        return JSONResponse(status_code=e.http_status, content=e.to_payload())
    session.close()
    if not try_lock(session_id):
        return JSONResponse(status_code=409, content={"code": "SESSION_BUSY", "message": "이 리포트에서 아직 앞선 요청을 처리하고 있습니다."})
    if body.import_id:
        turn: Dict[str, Any] = {"import": body.import_id}
    elif body.approval is None:
        turn = {"text": body.text, "modes": body.modes, "tableId": body.table_id}
    else:
        turn = {"approval": body.approval.model_dump(by_alias=True, exclude_none=True)}
    try:
        es, task = ReportService.start_turn(session_id, turn)
    except Exception:
        release_lock(session_id)
        raise
    return StreamingResponse(ReportService.stream_events(es, task, request), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.get("/sessions/{session_id}/start-cards")
def start_cards(session_id: str, user: UserDep, session: SessionDep):
    """시작 화면 추천 카드 4개 — 내 기록(할 일·검토 요청·쓰다 만 문서·되풀이한 질문·새 자료·자주 쓴 양식)으로 코드가 고른다."""
    from app.start_cards import start_cards as pick

    row = ReportService(session).access(session_id, user, write=True)
    return {"cards": pick(session, row, user)}


@router.post("/sessions/{session_id}/cancel")
def cancel_turn(session_id: str, user: UserDep, session: SessionDep):
    """진행 중인 턴을 바로 끊는다(FE 중단 버튼이 스트림 abort 와 함께 부른다 — 잠금이 즉시 풀려 곧바로 다시 보낼 수 있다)."""
    ReportService(session).access(session_id, user, write=True)
    return {"cancelled": ReportService.cancel_turn(session_id)}


@router.get("/sessions/{session_id}/readiness")
def get_readiness(session_id: str, user: UserDep, session: SessionDep):
    return ReportService(session).readiness(session_id, user)


@router.get("/sessions/{session_id}/numbers")
def get_numbers(session_id: str, user: UserDep, session: SessionDep):
    """본문 숫자마다 출처 판정(자료와 일치·계산값·입력값·원장과 다름·출처 없음) + 사람 확인 표시."""
    return ReportService(session).numbers(session_id, user)


@router.post("/sessions/{session_id}/numbers/{key}")
def confirm_number(session_id: str, key: str, body: NumberConfirmBody, user: UserDep, session: SessionDep):
    return ReportService(session).confirm_number(session_id, user, key, body.confirmed, body.note, body.raw)


@router.post("/sessions/{session_id}/review-request")
def request_review(session_id: str, body: ReviewRequestBody, user: UserDep, session: SessionDep):
    return ReportService(session).request_review(session_id, user, body.reviewer_id, body.note)


@router.post("/sessions/{session_id}/template")
async def upload_template(session_id: str, request: Request, user: UserDep, session: SessionDep):
    """DOCX 양식 등록(multipart `file`) — 제목 문단이 섹션이 되고, 내보내기가 원본 양식에 채운다."""
    import shutil
    import tempfile
    from pathlib import Path

    form = await request.form()
    f = form.get("file")
    if not isinstance(f, UploadFile) or not (f.filename or "").lower().endswith(".docx"):
        return JSONResponse(status_code=400, content={"code": "BAD_TEMPLATE", "message": "DOCX 양식 파일을 올려 주세요."})
    tmp = Path(tempfile.mkdtemp(prefix="tpl_"))
    try:
        src = tmp / "template.docx"
        with open(src, "wb") as out:
            shutil.copyfileobj(f.file, out)
        return await run_in_threadpool(ReportService(session).set_template, session_id, user, str(src), Path(f.filename or "template.docx").name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@router.delete("/sessions/{session_id}/template")
def remove_template(session_id: str, user: UserDep, session: SessionDep):
    return ReportService(session).remove_template(session_id, user)


@router.get("/sessions/{session_id}/export")
def export_docx(session_id: str, user: UserDep, session: SessionDep):
    data, filename = ReportService(session).export(session_id, user)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/sessions/{session_id}/export.xlsx")
def export_blocks_xlsx(session_id: str, user: UserDep, session: SessionDep):
    """고정 양식 리포트의 표·그림 데이터 — 블록마다 시트, 그림은 엑셀 막대 그래프."""
    data, filename = ReportService(session).export_xlsx(session_id, user)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


# ── 자료(워크스페이스) ─────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/documents")
def list_documents(workspace_id: str, user: UserDep, session: SessionDep):
    return DocumentService(session).listing(workspace_id, user)


@router.post("/workspaces/{workspace_id}/documents")
async def upload_documents(workspace_id: str, request: Request, user: UserDep, session: SessionDep):
    """multipart `files` 여러 개. 파일 복사·등록은 스레드풀에서(이벤트 루프를 막지 않게)."""
    form = await request.form()
    files = [f for f in form.getlist("files") if isinstance(f, UploadFile)]
    if not files:
        return JSONResponse(status_code=400, content={"code": "EMPTY", "message": "올린 파일이 없습니다."})
    replaces = form.get("replaces")
    folder = form.get("folder")
    return await run_in_threadpool(
        DocumentService(session).upload, workspace_id, user, files, replaces if isinstance(replaces, str) and replaces else None, folder if isinstance(folder, str) and folder else None
    )


@router.delete("/workspaces/{workspace_id}/documents")
def remove_document(workspace_id: str, user: UserDep, session: SessionDep, job: Optional[str] = Query(default=None), doc: Optional[str] = Query(default=None)):
    return DocumentService(session).remove(workspace_id, user, job_id=job, doc_id=doc)


@router.get("/workspaces/{workspace_id}/documents/{doc_id}/compare")
def compare_versions(workspace_id: str, doc_id: str, user: UserDep, session: SessionDep, other: Optional[str] = Query(default=None, alias="with")):
    """같은 자료의 두 판 숫자 비교(바뀜·새로 생김·없어짐). with 가 없으면 바로 앞 판과."""
    return DocumentService(session).compare(workspace_id, user, doc_id, other)


@router.get("/workspaces/{workspace_id}/documents/{doc_id}/chunks")
def document_chunks(workspace_id: str, doc_id: str, user: UserDep, session: SessionDep, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100)):
    return DocumentService(session).chunks(workspace_id, user, doc_id, offset, limit)


@router.get("/workspaces/{workspace_id}/documents/{doc_id}/chunk")
def document_chunk(workspace_id: str, doc_id: str, user: UserDep, session: SessionDep, id: str = Query(...)):
    return DocumentService(session).chunk(workspace_id, user, doc_id, id)


class EvidenceBody(BaseModel):
    use: bool


@router.post("/workspaces/{workspace_id}/documents/{doc_id}/evidence")
def set_document_evidence(workspace_id: str, doc_id: str, body: EvidenceBody, user: UserDep, session: SessionDep):
    """근거로 쓸지 켜고 끈다(검수 대상 초안은 검수 시작 때 자동으로 꺼진다)."""
    return DocumentService(session).set_evidence(workspace_id, user, doc_id, body.use)


@router.post("/workspaces/{workspace_id}/documents/{doc_id}/enrich")
def enrich_document(workspace_id: str, doc_id: str, user: UserDep, session: SessionDep):
    return DocumentService(session).enrich(workspace_id, user, doc_id)


@router.get("/workspaces/{workspace_id}/documents/{doc_id}/locate")
def document_locate(workspace_id: str, doc_id: str, user: UserDep, session: SessionDep, chunk: Optional[str] = Query(default=None), cell: Optional[str] = Query(default=None)):
    """원문 확인 — 가공한 값(chunk·cell=행,열)이 원본 파일의 어디인지 원본을 다시 읽어서(PDF 쪽·엑셀 칸·워드 문단·글 줄)."""
    from app.docs.source_view import locate

    DocumentService(session).source_file(workspace_id, user, doc_id)  # 읽을 수 있는 자료인가
    rc = tuple(int(x) for x in cell.split(",")[:2]) if cell and re.fullmatch(r"\d+,\d+", cell) else None
    try:
        return locate(doc_id, chunk, rc)  # type: ignore[arg-type]
    except FileNotFoundError as e:
        return JSONResponse(status_code=404, content={"message": str(e)})


@router.get("/workspaces/{workspace_id}/documents/{doc_id}/page/{page_no}.png")
def document_page(workspace_id: str, doc_id: str, page_no: int, user: UserDep, session: SessionDep):
    """원본 PDF 한 쪽 그림(원문 확인 창)."""
    from fastapi.responses import Response as _Response

    from app.docs.source_view import page_png

    DocumentService(session).source_file(workspace_id, user, doc_id)
    try:
        return _Response(content=page_png(doc_id, page_no), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})
    except (FileNotFoundError, ValueError) as e:
        return JSONResponse(status_code=404, content={"message": str(e)})


@router.get("/workspaces/{workspace_id}/documents/{doc_id}/file")
def document_file(workspace_id: str, doc_id: str, user: UserDep, session: SessionDep):
    f = DocumentService(session).source_file(workspace_id, user, doc_id)
    # 내려받지 않고 브라우저에서 바로 연다(PDF 는 #page=n 으로 그 쪽) — 원문 확인 창의 '원본 파일'
    return FileResponse(f["path"], filename=f["fileName"], content_disposition_type="inline")


# ── 사내 공용 데이터(관리용 — 화면 없음, 데모 준비 스크립트가 넣는다) ─────────

@router.get("/company/documents")
def list_company_documents(user: UserDep, session: SessionDep):
    return DocumentService(session).company_listing()


@router.post("/company/documents")
async def upload_company_documents(request: Request, user: UserDep, session: SessionDep):
    """multipart `files` 여러 개 — 모든 워크스페이스가 기본으로 쓰는 사내 공용 데이터로 넣는다."""
    form = await request.form()
    files = [f for f in form.getlist("files") if isinstance(f, UploadFile)]
    if not files:
        return JSONResponse(status_code=400, content={"code": "EMPTY", "message": "올린 파일이 없습니다."})
    return await run_in_threadpool(DocumentService(session).upload_company, user, files)


# ── 공용 자료실 ────────────────────────────────────────────────────────

@router.get("/library")
def library(user: UserDep, session: SessionDep, q: str = Query(default=""), workspace: Optional[str] = Query(default=None)):
    """조직 공용 자료실(데모: 모두가 본다). workspace 를 주면 그 워크스페이스에 이미 붙었는지 표시."""
    return LibraryService(session).listing(user, q, workspace)


@router.post("/workspaces/{workspace_id}/documents/{doc_id}/publish")
def publish_document(workspace_id: str, doc_id: str, body: PublishBody, user: UserDep, session: SessionDep):
    return LibraryService(session).publish(workspace_id, user, doc_id, body.note)


@router.delete("/library/{item_id}")
def unpublish_document(item_id: str, user: UserDep, session: SessionDep, workspace: Optional[str] = Query(default=None)):
    return LibraryService(session).unpublish(user, item_id, workspace)


@router.post("/workspaces/{workspace_id}/library/{item_id}/attach")
def attach_from_library(workspace_id: str, item_id: str, user: UserDep, session: SessionDep):
    """자료실 자료를 이 워크스페이스에 붙인다 — 붙여야 이 워크스페이스의 검색·원장·리포트가 쓴다."""
    return LibraryService(session).attach(workspace_id, user, item_id)


# ── 통합 검색 · 경과 문서 ──────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/search")
def search(workspace_id: str, user: UserDep, session: SessionDep, q: str = Query(default="")):
    """워크스페이스 안 자료 문단·원장·팀 기록·리포트·채널·작업 항목 한 번에."""
    return search_workspace(session, workspace_id, user, q)


@router.get("/workspaces/{workspace_id}/progress-doc")
def progress_doc(workspace_id: str, user: UserDep, session: SessionDep):
    """작업 경과 DOCX — 팀 기록·충돌 채택·검수·자료·작업에서 코드로 묶는다(LLM 없음)."""
    data, filename = progress_docx(session, workspace_id, user)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


# ── 근거 원장 ──────────────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/ledger")
def get_ledger(workspace_id: str, user: UserDep, session: SessionDep):
    return LedgerService(session).view(workspace_id, user)


@router.post("/workspaces/{workspace_id}/ledger/choose")
def choose_ledger_value(workspace_id: str, body: ChooseBody, user: UserDep, session: SessionDep):
    return LedgerService(session).choose(workspace_id, user, body.key, body.figure_id, body.reason)


@router.get("/workspaces/{workspace_id}/ledger/export")
def export_ledger(workspace_id: str, user: UserDep, session: SessionDep):
    data, filename = ledger_xlsx(session, workspace_id, user)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


# ── 데이터 연결 ────────────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/connectors")
def list_connectors(workspace_id: str, user: UserDep, session: SessionDep):
    return ConnectorService(session).listing(workspace_id, user)


@router.get("/workspaces/{workspace_id}/connectors/dart/companies")
async def dart_companies(workspace_id: str, user: UserDep, session: SessionDep, q: str = Query(..., min_length=1)):
    return await run_in_threadpool(ConnectorService(session).dart_companies, workspace_id, user, q)


@router.post("/workspaces/{workspace_id}/connectors/dart/financials")
async def dart_financials(workspace_id: str, body: DartFetchBody, user: UserDep, session: SessionDep):
    return await run_in_threadpool(ConnectorService(session).dart_financials, workspace_id, user, body.corp_code, body.corp_name, body.year, body.report, body.fs)


@router.get("/workspaces/{workspace_id}/connectors/edgar/companies")
async def edgar_companies(workspace_id: str, user: UserDep, session: SessionDep, q: str = Query(..., min_length=1)):
    return await run_in_threadpool(ConnectorService(session).edgar_companies, workspace_id, user, q)


@router.post("/workspaces/{workspace_id}/connectors/edgar/financials")
async def edgar_financials(workspace_id: str, body: EdgarFetchBody, user: UserDep, session: SessionDep):
    return await run_in_threadpool(ConnectorService(session).edgar_financials, workspace_id, user, body.cik, body.name, body.year)


@router.get("/workspaces/{workspace_id}/connectors/ecos/tables")
async def ecos_tables(workspace_id: str, user: UserDep, session: SessionDep, q: str = Query(..., min_length=1)):
    return await run_in_threadpool(ConnectorService(session).ecos_tables, workspace_id, user, q)


@router.get("/workspaces/{workspace_id}/connectors/ecos/items")
async def ecos_items(workspace_id: str, user: UserDep, session: SessionDep, stat: str = Query(..., min_length=3)):
    return await run_in_threadpool(ConnectorService(session).ecos_items, workspace_id, user, stat)


@router.post("/workspaces/{workspace_id}/connectors/ecos/series")
async def ecos_series(workspace_id: str, body: EcosSeriesBody, user: UserDep, session: SessionDep):
    data = {"statCode": body.stat_code, "statName": body.stat_name, "itemCode": body.item_code, "itemName": body.item_name, "cycle": body.cycle, "start": body.start, "end": body.end}
    return await run_in_threadpool(ConnectorService(session).ecos_series, workspace_id, user, data)


# ── 문서 검수 ──────────────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/reviews")
def list_reviews(workspace_id: str, user: UserDep, session: SessionDep):
    return ReviewService(session).listing(workspace_id, user)


@router.post("/workspaces/{workspace_id}/reviews", status_code=201)
async def start_review(workspace_id: str, body: ReviewBody, user: UserDep, session: SessionDep):
    """검수 시작 — 뒤에서 돈다(이벤트 루프에서 태스크를 띄우려고 async). 화면은 GET 으로 상태를 본다."""
    return ReviewService(session).start(workspace_id, user, body.doc_id)


@router.get("/workspaces/{workspace_id}/reviews/{review_id}")
def get_review(workspace_id: str, review_id: str, user: UserDep, session: SessionDep):
    return ReviewService(session).get(workspace_id, user, review_id)


@router.get("/workspaces/{workspace_id}/reviews/{review_id}/memo")
def review_memo_docx(workspace_id: str, review_id: str, user: UserDep, session: SessionDep):
    """검수 지적을 Word 메모로 — 대상이 DOCX 면 원본 파일에 메모를 단 사본, 아니면 검수 의견서 DOCX."""
    data, filename = ReviewService(session).memo(workspace_id, user, review_id)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.post("/workspaces/{workspace_id}/reviews/{review_id}/tasks")
def review_tasks(workspace_id: str, review_id: str, body: ReviewTasksBody, user: UserDep, session: SessionDep):
    return ReviewService(session).make_tasks(workspace_id, user, review_id, body.finding_ids, body.assignee_id, body.due)


# ── 채널 ──────────────────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/channel")
def list_messages(workspace_id: str, user: UserDep, session: SessionDep, after: Optional[str] = Query(default=None)):
    return ChannelService(session).listing(workspace_id, user, after)


@router.post("/workspaces/{workspace_id}/channel", status_code=201)
async def post_message(workspace_id: str, body: MessageBody, user: UserDep, session: SessionDep):
    """"@에이전트" 가 있으면 답을 뒤에서 만든다(이벤트 루프에서 태스크를 띄우려고 async)."""
    return ChannelService(session).post(workspace_id, user, body.text, body.attachments, body.thread_id)


# ── 팀 기록·기록 비서 ──────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/records")
def list_records(workspace_id: str, user: UserDep, session: SessionDep, status: Optional[str] = Query(default=None)):
    return RecordService(session).listing(workspace_id, user, status)


@router.post("/workspaces/{workspace_id}/records", status_code=201)
def add_record(workspace_id: str, body: RecordBody, user: UserDep, session: SessionDep):
    return RecordService(session).add(workspace_id, user, body.type, body.text, body.scope)


@router.post("/workspaces/{workspace_id}/records/run")
async def run_records(workspace_id: str, user: UserDep, session: SessionDep):
    """소유자 전용 — 퇴근 시각 배치를 지금 돌린다(데모·테스트)."""
    return await RecordService(session).run_now(workspace_id, user)


@router.post("/workspaces/{workspace_id}/records/{record_id}/confirm")
def confirm_record(workspace_id: str, record_id: str, body: ConfirmBody, user: UserDep, session: SessionDep):
    return RecordService(session).confirm(workspace_id, user, record_id, body.text)


@router.post("/workspaces/{workspace_id}/records/{record_id}/dismiss")
def dismiss_record(workspace_id: str, record_id: str, user: UserDep, session: SessionDep):
    return RecordService(session).dismiss(workspace_id, user, record_id)


@router.get("/workspaces/{workspace_id}/briefing")
def get_briefing(workspace_id: str, user: UserDep, session: SessionDep):
    """지난 접속 이후 — 부르면 접속 시각이 지금으로 바뀐다."""
    return briefing(session, workspace_id, user)


# ── 드라이브(문서·데이터 폴더) ─────────────────────────────────────────────

class FolderBody(BaseModel):
    name: str
    parent_id: Optional[str] = Field(default=None, alias="parentId")
    model_config = ConfigDict(populate_by_name=True)


class MoveBody(BaseModel):
    items: List[Dict[str, str]]
    folder_id: Optional[str] = Field(default=None, alias="folderId")
    current: Optional[str] = None
    model_config = ConfigDict(populate_by_name=True)


@router.get("/workspaces/{workspace_id}/drive")
def get_drive(workspace_id: str, user: UserDep, session: SessionDep, folder: Optional[str] = Query(default=None)):
    return DriveService(session).listing(workspace_id, user, folder)


@router.get("/workspaces/{workspace_id}/drive/search")
def search_drive(workspace_id: str, user: UserDep, session: SessionDep, q: str = Query(default="")):
    return DriveService(session).search(workspace_id, user, q)


@router.post("/workspaces/{workspace_id}/drive/folders")
def create_folder(workspace_id: str, body: FolderBody, user: UserDep, session: SessionDep):
    return DriveService(session).create_folder(workspace_id, user, body.name, body.parent_id)


@router.patch("/workspaces/{workspace_id}/drive/folders/{folder_id}")
def update_folder(workspace_id: str, folder_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    return DriveService(session).update_folder(workspace_id, user, folder_id, body)


@router.delete("/workspaces/{workspace_id}/drive/folders/{folder_id}")
def delete_folder(workspace_id: str, folder_id: str, user: UserDep, session: SessionDep):
    return DriveService(session).delete_folder(workspace_id, user, folder_id)


@router.post("/workspaces/{workspace_id}/drive/move")
def move_drive_items(workspace_id: str, body: MoveBody, user: UserDep, session: SessionDep):
    return DriveService(session).move(workspace_id, user, body.items, body.folder_id, body.current)


# ── 검토 요청(여러 문서를 한 번에) ─────────────────────────────────────────

class ReviewRequestsBody(BaseModel):
    report_ids: List[str] = Field(alias="reportIds")
    reviewer_id: str = Field(alias="reviewerId")
    note: str = ""
    model_config = ConfigDict(populate_by_name=True)


@router.post("/workspaces/{workspace_id}/review-requests")
def send_review_requests(workspace_id: str, body: ReviewRequestsBody, user: UserDep, session: SessionDep):
    """작성한 문서 여러 편을 한 검토자에게 — 문서마다 검토 작업 + 채팅 알림(리포트 검토 요청과 같다)."""
    return ReportService(session).request_reviews(workspace_id, user, body.report_ids, body.reviewer_id, body.note)


# ── 마이페이지(워크스페이스 홈) ──────────────────────────────────────────

class TodoBody(BaseModel):
    title: str
    due: str = ""
    start: str = ""


@router.get("/workspaces/{workspace_id}/me")
def get_my_page(workspace_id: str, user: UserDep, session: SessionDep):
    return my_page(session, workspace_id, user)


@router.post("/workspaces/{workspace_id}/me/todos")
def post_my_todo(workspace_id: str, body: TodoBody, user: UserDep, session: SessionDep):
    return add_todo(session, workspace_id, user, body.title, body.due, body.start)


@router.patch("/workspaces/{workspace_id}/me/tasks/{task_id}")
def patch_my_task(workspace_id: str, task_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    return update_mine(session, workspace_id, user, task_id, body)


@router.delete("/workspaces/{workspace_id}/me/todos/{task_id}")
def delete_my_todo(workspace_id: str, task_id: str, user: UserDep, session: SessionDep):
    return delete_todo(session, workspace_id, user, task_id)


# ── 작업 항목 ──────────────────────────────────────────────────────────

@router.get("/workspaces/{workspace_id}/tasks")
def list_tasks(workspace_id: str, user: UserDep, session: SessionDep):
    return TaskService(session).listing(workspace_id, user)


@router.post("/workspaces/{workspace_id}/tasks", status_code=201)
def create_task(workspace_id: str, body: TaskBody, user: UserDep, session: SessionDep):
    return TaskService(session).create(workspace_id, user, body.title, body.detail, body.assignee_id, body.due, body.start)


@router.patch("/workspaces/{workspace_id}/tasks/{task_id}")
def update_task(workspace_id: str, task_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    return TaskService(session).update(workspace_id, user, task_id, body)


@router.delete("/workspaces/{workspace_id}/tasks/{task_id}")
def delete_task(workspace_id: str, task_id: str, user: UserDep, session: SessionDep):
    return TaskService(session).delete(workspace_id, user, task_id)
