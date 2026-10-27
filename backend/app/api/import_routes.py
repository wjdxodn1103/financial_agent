"""양식 샘플 API — prefix /api.

  /sessions/{s}/imports                     샘플 올리기(multipart file — .docx·.pdf) → 그다음 /chat {import} 로 카드를 받는다
  /sessions/{s}/imports/{i}/items/{n}       표·차트 카드 등록·건너뛰기
  /sessions/{s}/imports/{i}/format          리포트 양식 한꺼번에 등록
  /workspaces/{w}/report-types              등록한 리포트 양식(새 문서·양식 고르기)
  /report-types/{id}                        등록 양식 지우기
  /workspaces/{w}/formats                   양식 메뉴 — 목록(기본+등록)·만들기(빈 것·복사)
  /workspaces/{w}/formats/{id}              양식 고치기(이름·설명·섹션·자리·범위)
  /workspaces/{w}/format-imports            새 양식 = 샘플 올리기 → 뒤에서 LLM 분석 → 끝나면 '등록 전' 양식(GET 으로 상태·formatId)
  /workspaces/{w}/formats/{id}/register     등록 전 양식을 등록(범위)
  /workspaces/{w}/formats/{id}/revise       말로 고치기(LLM 이 양식을 고쳐 저장)
  /workspaces/{w}/formats/{id}/sample       예시 문서(브라우저에서 바로 연다)
  /workspaces/{w}/formats/{id}/assets/{a}/image  표·차트 양식이 샘플에서 있던 부분만(PNG)
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.datastructures import UploadFile

from app.auth import UserDep
from app.db import SessionDep
from app.templates_import.registry import asset_image, create_format, delete_report_template, format_view, format_views, register_draft, report_type_views, sample_path, update_format
from app.templates_import.service import FileImport, ImportService

router = APIRouter(prefix="/api")
MAX_BYTES = 30 * 1024 * 1024


async def _with_sample(request: Request, run: Any) -> Any:
    """multipart file(.docx·.pdf, 30MB 이하)을 임시 파일로 받아 run(src, name) 에 넘긴다."""
    form = await request.form()
    f = form.get("file")
    name = Path(getattr(f, "filename", "") or "").name
    if not isinstance(f, UploadFile) or Path(name).suffix.lower() not in (".docx", ".pdf"):
        return JSONResponse(status_code=400, content={"code": "BAD_SAMPLE", "message": "Word(.docx)나 PDF 샘플을 올려 주세요."})
    tmp = Path(tempfile.mkdtemp(prefix="imp_"))
    try:
        src = tmp / "sample"
        with open(src, "wb") as out:
            shutil.copyfileobj(f.file, out)
        if src.stat().st_size > MAX_BYTES:
            return JSONResponse(status_code=400, content={"code": "TOO_BIG", "message": "30MB 이하 파일만 올릴 수 있습니다."})
        return await run(str(src), name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@router.post("/sessions/{session_id}/imports")
async def upload_sample(session_id: str, request: Request, user: UserDep, session: SessionDep):
    return await _with_sample(request, lambda src, name: run_in_threadpool(ImportService(session).upload, session_id, user, src, name))


@router.post("/sessions/{session_id}/imports/{import_id}/items/{n}")
def import_item(session_id: str, import_id: str, n: int, body: Dict[str, Any], user: UserDep, session: SessionDep):
    """{action: register|skip, name?, scope?: user|workspace|company, spec?}"""
    return ImportService(session).item(session_id, user, import_id, n, body)


@router.post("/sessions/{session_id}/imports/{import_id}/format")
def import_format(session_id: str, import_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    """{name?, scope?} — 아직 고르지 않은 표·차트도 같은 범위로 등록한다."""
    return ImportService(session).register_format(session_id, user, import_id, body)


@router.get("/workspaces/{workspace_id}/report-types")
def list_report_types(workspace_id: str, user: UserDep, session: SessionDep):
    return {"reportTypes": report_type_views(session, workspace_id, user)}


@router.delete("/report-types/{type_id}", status_code=204)
def remove_report_type(type_id: str, user: UserDep, session: SessionDep):
    delete_report_template(session, type_id, user)


@router.get("/workspaces/{workspace_id}/formats")
def list_formats(workspace_id: str, user: UserDep, session: SessionDep):
    return {"formats": format_views(session, workspace_id, user)}


@router.post("/workspaces/{workspace_id}/formats", status_code=201)
def new_format(workspace_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    """{name?, scope?, from?: 양식 id(복사)}"""
    return create_format(session, workspace_id, user, body)


@router.patch("/workspaces/{workspace_id}/formats/{type_id}")
def edit_format(workspace_id: str, type_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    """{name?, desc?, style?, sections?: [{id?, title, level, guide, slots}], assets?: [{id, name, desc}], scope?}"""
    return update_format(session, workspace_id, user, type_id, body)


@router.post("/workspaces/{workspace_id}/format-imports")
async def upload_format_sample(workspace_id: str, request: Request, user: UserDep, session: SessionDep):
    """샘플을 받아 두고 바로 돌려준다 — 분석(쪽마다 VL, 7쪽에 약 2분)은 뒤에서. 화면은 GET 으로 상태를 다시 묻는다."""
    return await _with_sample(request, lambda src, name: FileImport(session).start(workspace_id, user, src, name))


@router.get("/workspaces/{workspace_id}/format-imports/{import_id}")
def format_import_state(workspace_id: str, import_id: str, user: UserDep, session: SessionDep):
    """{status: analyzing|ready|error, progress: {done, total}, formatId?(등록 전 양식), error?}"""
    return FileImport(session).get(workspace_id, user, import_id)


@router.post("/workspaces/{workspace_id}/formats/{type_id}/register")
def format_register(workspace_id: str, type_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    """{scope: workspace|company} — 등록 전 양식을 등록."""
    return register_draft(session, workspace_id, user, type_id, str(body.get("scope") or "workspace"))


@router.post("/workspaces/{workspace_id}/formats/{type_id}/revise")
async def format_revise(workspace_id: str, type_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    """{instruction} — 말로 고치기. LLM 이 고친 양식을 저장하고 {format, summary} 를 돌려준다."""
    from app.llm.client import ReportLlm
    from app.templates_import.revise import revise

    view = format_view(session, workspace_id, user, type_id)
    patch, summary = await revise(view, str(body.get("instruction") or ""), ReportLlm())
    return {"format": update_format(session, workspace_id, user, type_id, patch), "summary": summary}


@router.get("/workspaces/{workspace_id}/formats/{type_id}/sample")
def format_sample(workspace_id: str, type_id: str, user: UserDep, session: SessionDep):
    p = sample_path(session, workspace_id, user, type_id)
    return FileResponse(p, filename=p.name, content_disposition_type="inline")


@router.get("/workspaces/{workspace_id}/formats/{type_id}/assets/{asset_id}/image")
def format_asset_image(workspace_id: str, type_id: str, asset_id: str, user: UserDep, session: SessionDep):
    png = asset_image(session, workspace_id, user, type_id, asset_id)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})
