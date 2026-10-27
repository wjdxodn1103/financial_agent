"""워크스페이스 자료 — 목록·올리기·빼기·문단 읽기(지연 로딩)·근거 문단·카드 정리·원본 내려받기.
자료는 워크스페이스에 붙는다(그 안의 리포트·검수·채널 에이전트가 같이 쓴다). 사내 공용 데이터(CompanyDocument)는 모든 워크스페이스가
기본으로 보고, 워크스페이스는 AI 참고를 끄기만 한다. 파일 복사·추출은 큐(app.docs.queue)가 스레드에서 한다.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import require_member
from app.config import MAX_UPLOAD_MB
from app.db import COMPANY_SCOPE, Membership, Repo, User, Workspace, company_rows, excluded_ids, iso, scope_ids, set_excluded
from app.docs import queue as docs_queue
from app.docs.extract import SUPPORTED_LABEL, file_type_of
from app.docs.store import chunk_with_context, doc_dir, doc_label, document_cards, load_meta, paragraphs, public_chunk
from app.docs.versions import archived_ids, chain, compare_figures, version_map
from app.services.report_service import _busy

PAGE_MAX = 100


def attach_document(session: Session, workspace_id: str, doc_id: str) -> None:
    """워크스페이스 자료 목록에 붙인다(이미 있으면 그대로). 새 list 를 대입해야 JSON 컬럼 변경이 잡힌다."""
    repo = Repo(session)
    ws = repo.workspace(workspace_id)
    if ws is None:
        return
    ids = list(ws.document_ids or [])
    if doc_id not in ids:
        ws.document_ids = [*ids, doc_id]
        repo.save(ws)


class DocumentService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = Repo(session)

    def _ws(self, workspace_id: str, user: User, min_role: str = "viewer") -> Workspace:
        ws, _m = require_member(self.session, workspace_id, user, min_role)
        return ws

    def _own(self, ws: Workspace, doc_id: str) -> None:
        if doc_id not in (ws.document_ids or []):
            raise HTTPException(404, "이 워크스페이스의 자료가 아닙니다.")

    def _readable(self, ws: Workspace, doc_id: str) -> None:
        """원문 보기·비교는 사내 공용 데이터와 보관된 이전 판도 된다(검색·원장·리포트는 활성 판만)."""
        if doc_id not in scope_ids(ws) and doc_id not in archived_ids(self.session, ws.id):
            raise HTTPException(404, "이 워크스페이스의 자료가 아닙니다.")

    def listing(self, workspace_id: str, user: User) -> Dict[str, Any]:
        """이 워크스페이스가 볼 수 있는 데이터 — 사내 공용(shared)과 이 워크스페이스에 올린 것.
        excluded = 이 워크스페이스에서 AI 가 쓰지 않음, uploadedAt = 이 워크스페이스(사내 것은 사내 목록)에 올라온 시각."""
        ws = self._ws(workspace_id, user)
        own = set(ws.document_ids or [])
        company = {r.doc_id: r for r in company_rows()}
        cards = document_cards(scope_ids(ws))
        names = {u.id: u.name for u in self.repo.users()}
        jobs = {j.doc_id: j for j in self.repo.jobs(ws.id) if j.doc_id}
        from app.library import library_map  # 순환 import 피하기(library 가 attach_document 를 쓴다)

        versions = version_map(self.session, ws.id)
        shelf = library_map(self.session)
        off = set(excluded_ids(ws))
        for c in cards:
            job = jobs.get(c["id"])
            c["shared"] = c["id"] in company and c["id"] not in own  # 사내 공용 — 같은 파일을 워크스페이스에도 올렸으면 워크스페이스 것으로 본다
            c["excluded"] = c["id"] in off
            c["uploadedAt"] = iso(company[c["id"]].created_at) if c["shared"] else (iso(job.created_at) if job else c.get("createdAt"))
            c.update(docs_queue.is_processing(c["id"]))
            c["uploadedBy"] = names.get(job.uploaded_by, "") if job else ""
            c["version"] = versions.get(c["id"])
            c["library"] = shelf.get(c["id"])
        return {"documents": cards, "jobs": [docs_queue.job_view(j) for j in self.repo.jobs(ws.id) if j.status != "done"]}

    def company_listing(self) -> Dict[str, Any]:
        """사내 공용 데이터 목록(관리용 — 데모 준비 스크립트가 처리 끝을 기다릴 때 쓴다)."""
        rows = {r.doc_id: r for r in company_rows()}
        cards = document_cards(list(rows))
        for c in cards:
            c["uploadedAt"] = iso(rows[c["id"]].created_at)
            c.update(docs_queue.is_processing(c["id"]))
        return {"documents": cards, "jobs": [docs_queue.job_view(j) for j in self.repo.jobs(COMPANY_SCOPE) if j.status != "done"]}

    def upload_company(self, user: User, files: List[Any]) -> Dict[str, Any]:
        """사내 공용 데이터 넣기(관리용 — 화면 없음). 회사가 미리 넣어 두는 데이터라 어느 워크스페이스든 소유자인 사람만."""
        if not any(m.role == "owner" for m in self.session.exec(select(Membership).where(Membership.user_id == user.id))):
            raise HTTPException(403, "사내 공용 데이터는 워크스페이스 소유자만 넣을 수 있습니다.")
        errors = self._enqueue_files(COMPANY_SCOPE, user.id, files)
        return {**self.company_listing(), "errors": errors}

    def set_evidence(self, workspace_id: str, user: User, doc_id: str, use: bool) -> Dict[str, Any]:
        """이 워크스페이스에서 AI 가 참고할지(편집자 이상, 사내 공용 데이터도) — 끄면 원장·리포트 작성·채팅 에이전트·검수 대조에서 빠진다.
        검수를 시작하면 대상 문서는 자동으로 꺼진다."""
        ws = self._ws(workspace_id, user, "editor")
        if doc_id not in scope_ids(ws):
            raise HTTPException(404, "이 워크스페이스의 자료가 아닙니다.")
        set_excluded(ws, doc_id, not use)
        self.repo.save(ws)
        return self.listing(workspace_id, user)

    def upload(self, workspace_id: str, user: User, files: List[Any], replaces: Optional[str] = None, folder_id: Optional[str] = None) -> Dict[str, Any]:
        """multipart UploadFile 목록 → 형식·크기 검사 → 임시 파일 → 큐 등록. 거절된 파일은 errors 로. 검토자 이상(검수 대상 문서를 올린다).
        replaces = 이 자료의 새 판(파일 하나, 편집자 이상) — 처리가 끝나면 이전 판 자리를 차지하고 이전 판은 보관된다.
        folder_id = 드라이브 폴더 — 처리가 끝나면 그 폴더에 놓인다(나에게 보이는 폴더만)."""
        ws = self._ws(workspace_id, user, "editor" if replaces else "reviewer")
        if replaces:
            self._own(ws, replaces)
            if len(files) != 1:
                raise HTTPException(400, "새 판은 파일 하나만 올립니다.")
        if folder_id:
            from app.drive import folders_of, visible_folders

            if folder_id not in visible_folders(folders_of(self.session, ws.id), user.id):
                raise HTTPException(404, "폴더가 없습니다.")
        errors = self._enqueue_files(ws.id, user.id, files, replaces, folder_id)
        return {**self.listing(ws.id, user), "errors": errors}

    def _enqueue_files(self, scope: str, user_id: str, files: List[Any], replaces: Optional[str] = None, folder_id: Optional[str] = None) -> List[str]:
        """형식·크기 검사 → 임시 파일 → 큐 등록(scope = 워크스페이스 id 또는 COMPANY_SCOPE). 거절된 파일 이름·이유를 돌려준다."""
        errors: List[str] = []
        accepted = []
        tmpdir = Path(tempfile.mkdtemp(prefix="upload_"))
        try:
            for f in files:
                name = Path(f.filename or "file").name
                if not file_type_of(name):
                    errors.append(f"{name}: 지원하지 않는 형식({SUPPORTED_LABEL} 만)")
                    continue
                dest = tmpdir / f"{len(accepted)}{Path(name).suffix.lower()}"
                with open(dest, "wb") as out:
                    shutil.copyfileobj(f.file, out)
                if dest.stat().st_size > MAX_UPLOAD_MB * 1024 * 1024:
                    errors.append(f"{name}: {MAX_UPLOAD_MB}MB 를 넘습니다")
                    continue
                accepted.append((dest, name))
            if accepted:
                docs_queue.enqueue(scope, user_id, accepted, replaces=replaces, folder_id=folder_id)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        return errors

    def remove(self, workspace_id: str, user: User, job_id: Optional[str] = None, doc_id: Optional[str] = None) -> Dict[str, Any]:
        """작업 행(오류·대기) 치우기 또는 문서를 이 워크스페이스에서 빼기(파일은 다른 워크스페이스가 쓸 수 있어 남긴다)."""
        ws = self._ws(workspace_id, user, "reviewer" if job_id and not doc_id else "editor")
        if job_id:
            job = self.repo.get_job(job_id)
            if job and job.workspace_id == ws.id:
                docs_queue.remove_inbox_file(job.src_path)
                self.repo.delete_job(job)
        if doc_id:
            busy = [r.id for r in self.repo.reports(ws.id) if r.id in _busy]
            if busy:
                raise HTTPException(409, "리포트 작성 중에는 자료를 뺄 수 없습니다. 끝난 뒤 다시 시도해 주세요.")
            ws.document_ids = [d for d in ws.document_ids or [] if d != doc_id]
            self.repo.save(ws)
        return self.listing(ws.id, user)

    def chunks(self, workspace_id: str, user: User, doc_id: str, offset: int, limit: int) -> Dict[str, Any]:
        """문단 페이지 — 뷰어가 스크롤하며 불러온다(지연 로딩)."""
        self._readable(self._ws(workspace_id, user), doc_id)
        paras = paragraphs(doc_id)
        limit = max(1, min(limit, PAGE_MAX))
        offset = max(0, offset)
        return {"docId": doc_id, "total": len(paras), "offset": offset, "chunks": [public_chunk(p, offset + i) for i, p in enumerate(paras[offset : offset + limit])]}

    def chunk(self, workspace_id: str, user: User, doc_id: str, chunk_id: str) -> Dict[str, Any]:
        """근거 문단 하나 + 앞뒤 문단(근거 보기)."""
        self._readable(self._ws(workspace_id, user), doc_id)
        got = chunk_with_context(doc_id, chunk_id)
        if got is None:
            raise HTTPException(404, "문단을 찾지 못했습니다(자료가 다시 처리됐을 수 있습니다).")
        meta = load_meta(doc_id) or {}
        return {"docId": doc_id, "label": doc_label(meta, doc_id), "fileName": meta.get("fileName") or "", "snapshot": meta.get("snapshot"), **got}

    def enrich(self, workspace_id: str, user: User, doc_id: str) -> Dict[str, Any]:
        ws = self._ws(workspace_id, user, "reviewer")
        self._own(ws, doc_id)
        docs_queue.enqueue_enrich(doc_id, force=True)
        return self.listing(ws.id, user)

    def compare(self, workspace_id: str, user: User, doc_id: str, other: Optional[str] = None) -> Dict[str, Any]:
        """같은 묶음의 두 판 숫자 비교 — other 가 없으면 바로 앞 판과."""
        ws = self._ws(workspace_id, user)
        self._readable(ws, doc_id)
        ids = chain(self.session, ws.id, doc_id)
        if len(ids) < 2:
            raise HTTPException(404, "비교할 이전 판이 없습니다.")
        if other is None:
            i = ids.index(doc_id)
            other = ids[i - 1] if i > 0 else ids[1]
        if other not in ids or other == doc_id:
            raise HTTPException(400, "같은 자료의 다른 판끼리만 비교합니다.")
        old, new = sorted((doc_id, other), key=ids.index)
        return compare_figures(old, new)

    def source_file(self, workspace_id: str, user: User, doc_id: str) -> Dict[str, Any]:
        self._readable(self._ws(workspace_id, user), doc_id)
        meta = load_meta(doc_id) or {}
        p = doc_dir(doc_id) / str(meta.get("source") or "")
        if not meta.get("source") or not p.is_file():
            raise HTTPException(404, "원본 파일이 없습니다.")
        return {"path": p, "fileName": meta.get("fileName") or p.name}
