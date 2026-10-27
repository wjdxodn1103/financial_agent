"""AI 채팅 API — prefix /api.

  /workspaces/{w}/research/chats       내 대화 목록·새 대화
  /research/chats/{c}                  대화 하나(메시지·표) · 이름 바꾸기 · 지우기
  /research/chats/{c}/chat             한 턴(SSE) · /cancel
  /research/tables/{t}                 표 하나(보기·고치기·드라이브 저장·지우기) · /export.docx · /export.xlsx
  /sessions/{s}/tables                 표·차트를 문서(리포트) 섹션에 넣기
  /sessions/{s}/charts                 표 → 차트(결과에 둔다)
  /sessions/{s}/notes                  대화의 답 → 메모(근거 아님)
  /workspaces/{w}/documents/{d}/tables         올린 자료 속 표 목록 · /{chunk}/asset 에셋으로 꺼내기
  /workspaces/{w}/documents/{d}/similar-assets 이미 만든 에셋·같은 모양 표 · POST 같은 모양으로 만들기
  /workspaces/{w}/assets               드라이브 ▸ 에셋(검색)
  /workspaces/{w}/research/templates   표 양식 목록·저장
  /research/templates/{id}             양식 고치기·지우기
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth import UserDep
from app.db import SessionDep
from app.llm.base import LlmError
from app.llm.client import require_provider
from app.research import service as research
from app.research.service import ResearchService
from app.services.report_service import ReportService, release_lock, try_lock

router = APIRouter(prefix="/api")
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


class ChatCreate(BaseModel):
    title: str = ""


class ChatTurn(BaseModel):
    text: str = ""
    table_id: Optional[str] = Field(default=None, alias="tableId")
    model_config = ConfigDict(populate_by_name=True)


@router.get("/workspaces/{workspace_id}/research/chats")
def list_chats(workspace_id: str, user: UserDep, session: SessionDep):
    return {"chats": ResearchService(session).chats(workspace_id, user)}


@router.post("/workspaces/{workspace_id}/research/chats", status_code=201)
def create_chat(workspace_id: str, body: ChatCreate, user: UserDep, session: SessionDep):
    return ResearchService(session).create_chat(workspace_id, user, body.title)


@router.get("/research/chats/{chat_id}")
def get_chat(chat_id: str, user: UserDep, session: SessionDep):
    return ResearchService(session).chat_payload(chat_id, user)


@router.patch("/research/chats/{chat_id}")
def rename_chat(chat_id: str, body: ChatCreate, user: UserDep, session: SessionDep):
    return ResearchService(session).rename_chat(chat_id, user, body.title)


@router.delete("/research/chats/{chat_id}", status_code=204)
def delete_chat(chat_id: str, user: UserDep, session: SessionDep):
    ResearchService(session).delete_chat(chat_id, user)


@router.post("/research/chats/{chat_id}/chat")
async def chat_turn(chat_id: str, body: ChatTurn, request: Request, user: UserDep, session: SessionDep):
    """한 턴 — 권한·키·잠금만 요청 세션으로 확인하고 스트림 전에 세션을 닫는다."""
    if not (body.text or "").strip():
        return JSONResponse(status_code=400, content={"code": "EMPTY", "message": "보낼 내용이 없습니다."})
    ResearchService(session).chat_row(chat_id, user)
    try:
        require_provider()
    except LlmError as e:
        return JSONResponse(status_code=e.http_status, content=e.to_payload())
    session.close()
    key = research.lock_key(chat_id)
    if not try_lock(key):
        return JSONResponse(status_code=409, content={"code": "SESSION_BUSY", "message": "이 대화에서 아직 앞선 요청을 처리하고 있습니다."})
    try:
        es, task = research.start_turn(chat_id, user.id, {"text": body.text, "tableId": body.table_id})
    except Exception:
        release_lock(key)
        raise
    return StreamingResponse(ReportService.stream_events(es, task, request), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/research/chats/{chat_id}/cancel")
def cancel_chat_turn(chat_id: str, user: UserDep, session: SessionDep):
    ResearchService(session).chat_row(chat_id, user)
    return {"cancelled": research.cancel_turn(chat_id)}


@router.get("/research/tables/{table_id}")
def get_table(table_id: str, user: UserDep, session: SessionDep):
    return ResearchService(session).get_table(table_id, user)


@router.patch("/research/tables/{table_id}")
def patch_table(table_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    """{title?, orientation?, saved?, folderId?} — saved=true 면 드라이브(폴더)에 둔다."""
    return ResearchService(session).patch_table(table_id, user, body)


@router.get("/research/tables/{table_id}/export.{fmt}")
def export_table(table_id: str, fmt: str, user: UserDep, session: SessionDep):
    """표·차트 하나 — docx(네이티브 워드 표·차트) · xlsx(값, 차트는 엑셀 차트)."""
    from app.report.format_export import build_table_docx, build_table_xlsx

    view = ResearchService(session).get_table(table_id, user)
    if view["kind"] == "note":
        if fmt != "docx":
            return JSONResponse(status_code=400, content={"message": "메모는 docx 로만 내려받습니다."})
        from app.report.format_export import build_note_docx

        data, filename = build_note_docx(view["block"], view["title"])
        return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})
    if fmt == "docx":
        data, filename = build_table_docx(view["block"], view["title"])
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif fmt == "xlsx":
        data, filename = build_table_xlsx(view["block"], view["title"])
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        return JSONResponse(status_code=404, content={"message": "docx 나 xlsx 만 됩니다."})
    return Response(content=data, media_type=media, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


class InsertTable(BaseModel):
    table_id: str = Field(alias="tableId")
    step: str
    model_config = ConfigDict(populate_by_name=True)


@router.post("/sessions/{session_id}/tables")
def insert_table(session_id: str, body: InsertTable, user: UserDep, session: SessionDep):
    """표를 문서 섹션 뒤에 넣는다(지금 표의 복사본)."""
    return ReportService(session).insert_table(session_id, user, body.table_id, body.step)


class AddChart(BaseModel):
    table_id: str = Field(alias="tableId")
    type: str = "bar"
    series: Optional[list] = None
    rows: Optional[list] = None
    horizontal: bool = False
    title: str = ""
    model_config = ConfigDict(populate_by_name=True)


@router.post("/sessions/{session_id}/charts")
def add_chart(session_id: str, body: AddChart, user: UserDep, session: SessionDep):
    """표 → 차트 에셋(막대·꺾은선), 이 작업의 결과에 둔다."""
    return ReportService(session).add_chart(session_id, user, body.table_id, body.model_dump(exclude={"table_id"}))


class NoteBody(BaseModel):
    msg_id: str = Field(alias="msgId")
    model_config = ConfigDict(populate_by_name=True)


@router.post("/sessions/{session_id}/notes")
def add_note(session_id: str, body: NoteBody, user: UserDep, session: SessionDep):
    """대화의 답 하나 → 메모(에셋 kind=note, 출처 링크째). 근거 자료가 아니다."""
    return ReportService(session).add_note(session_id, user, body.msg_id)


def _doc_in_workspace(session: Any, workspace_id: str, user: Any, doc_id: str) -> None:
    """이 워크스페이스에서 나에게 보이는 자료인가(사내 공용 + 워크스페이스 업로드 − 숨은 폴더)."""
    from fastapi import HTTPException

    from app.auth import require_member
    from app.db import scope_ids
    from app.drive import hidden_items

    ws, _m = require_member(session, workspace_id, user)
    if doc_id not in scope_ids(ws) or doc_id in hidden_items(session, workspace_id, user.id):
        raise HTTPException(404, "자료가 없습니다.")


@router.get("/workspaces/{workspace_id}/documents/{doc_id}/tables")
def document_tables(workspace_id: str, doc_id: str, user: UserDep, session: SessionDep):
    """올린 자료 속 표 목록(에셋으로 꺼내기)."""
    from app.research.doc_tables import table_list

    _doc_in_workspace(session, workspace_id, user, doc_id)
    return {"tables": table_list(doc_id)}


@router.post("/workspaces/{workspace_id}/documents/{doc_id}/tables/{chunk}/asset", status_code=201)
def document_table_asset(workspace_id: str, doc_id: str, chunk: str, user: UserDep, session: SessionDep):
    """자료 속 표 하나 → 내 에셋(칸 = 원문 칸, LLM 없음)."""
    from fastapi import HTTPException

    from app.research.doc_tables import create_from_doc

    _doc_in_workspace(session, workspace_id, user, doc_id)
    try:
        row = create_from_doc(session, workspace_id, user, doc_id, chunk)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    svc = ResearchService(session)
    return svc.table_view(row, user)


@router.get("/workspaces/{workspace_id}/documents/{doc_id}/similar-assets")
def document_similar_assets(workspace_id: str, doc_id: str, user: UserDep, session: SessionDep):
    """이 자료로 이미 만든 에셋 · 비슷한 문서에서 만든 같은 모양 표(내 것 + 공유된 것만)."""
    from app.research.doc_tables import similar_for_doc

    _doc_in_workspace(session, workspace_id, user, doc_id)
    return similar_for_doc(session, workspace_id, user, doc_id)


class SimilarPicks(BaseModel):
    picks: list


@router.post("/workspaces/{workspace_id}/documents/{doc_id}/similar-assets", status_code=201)
def apply_similar_assets(workspace_id: str, doc_id: str, body: SimilarPicks, user: UserDep, session: SessionDep):
    """{picks: [{chunk, assetId}]} — 같은 모양으로 만들기(그 표로 만든 차트도)."""
    from app.research.doc_tables import apply_similar

    _doc_in_workspace(session, workspace_id, user, doc_id)
    made = apply_similar(session, workspace_id, user, doc_id, [p for p in body.picks if isinstance(p, dict)])
    svc = ResearchService(session)
    return {"tables": [svc.table_view(r, user) for r in made]}


@router.delete("/research/tables/{table_id}", status_code=204)
def delete_table(table_id: str, user: UserDep, session: SessionDep):
    ResearchService(session).delete_table(table_id, user)


@router.get("/workspaces/{workspace_id}/assets")
def list_assets(workspace_id: str, user: UserDep, session: SessionDep, q: str = "", kind: Optional[str] = None, scope: Optional[str] = None):
    """드라이브 ▸ 에셋 — 내 에셋 + 공유된 에셋. q 는 낱말·종류(표·차트)·범위(내 것·공유)·날짜(지난주 등)를 함께 읽는다."""
    from app.auth import display_name, require_member
    from app.db import Repo
    from app.research.assets import asset_item, search_assets

    require_member(session, workspace_id, user)
    rows, parsed = search_assets(session, workspace_id, user, q, kind if kind in ("table", "chart", "note") else None, scope if scope in ("mine", "shared") else None)
    names = {u.id: display_name(u) for u in Repo(session).users()}
    return {"assets": [asset_item(session, r, user, names) for r in rows], "query": {k: parsed.get(k) for k in ("terms", "kind", "scope", "dateLabel")}}


@router.get("/workspaces/{workspace_id}/research/templates")
def list_templates(workspace_id: str, user: UserDep, session: SessionDep):
    return {"templates": ResearchService(session).templates(workspace_id, user)}


@router.post("/workspaces/{workspace_id}/research/templates", status_code=201)
def create_template(workspace_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    """{name, scope: user|workspace|company, spec} 또는 {name, scope, fromTableId, keepRows}."""
    return ResearchService(session).create_template(workspace_id, user, body)


@router.patch("/research/templates/{template_id}")
def patch_template(template_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    return ResearchService(session).patch_template(template_id, user, body)


@router.delete("/research/templates/{template_id}", status_code=204)
def delete_template(template_id: str, user: UserDep, session: SessionDep):
    ResearchService(session).delete_template(template_id, user)
