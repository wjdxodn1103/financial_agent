"""백그라운드 인제스트 큐 — OP `paper/refs/queue.py` 의 구조 그대로(DB 표 `IngestJob` 위에서).

 A. 인제스트(직렬): 추출·청킹 + 임시 카드(LLM 없음, 편당 1~3초) → 작업 done, 문서가 워크스페이스에 붙어 **BM25 로 바로 검색된다**.
 A'. 게으른 임베딩: 벡터는 뒤에서 한 편씩(NVIDIA API) 벡터 저장소(Qdrant)에. meta 의 색인 기록이 생기는 즉시 검색에 쓰인다.
 A''. 서버 시작 때: 청커가 바뀐 옛 문서를 원본에서 다시 뽑고(rechunk) → 색인이 없는 문서를 색인한다.
 B. 카드 정리(LLM, 온디맨드): 리포트 본문에 인용된 문서(enqueue_cited)와 사용자가 지목한 문서만.

 - 원본은 inbox/<jobId><ext> 에 복사해 두므로 서버가 재시작돼도 큐를 이어 간다(processing → queued 로 되돌림).
 - 한 작업의 실패는 그 행만 error 로 남기고 워커는 계속 돈다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlmodel import Session

from app.config import DOCUMENTS_DIR, INBOX_DIR
from app.db import COMPANY_SCOPE, CompanyDocument, IngestJob, Repo, engine
from app.docs.citations import token_doc_ids
from app.docs.ingest import embed_document, index_card, needs_embedding, needs_rechunk, prepare_document, rechunk_document
from app.docs.store import load_meta, save_meta
from app.ids import id36

logger = logging.getLogger(__name__)

ENRICH_WORKERS = 2
_state: Dict[str, Any] = {"task": None, "event": None}
_enrich: Dict[str, Any] = {"items": [], "event": None, "tasks": [], "active": set(), "tried": set()}
_embed_lock: Optional[asyncio.Lock] = None
_bg: "set[asyncio.Task[Any]]" = set()


def _spawn(coro: Any, name: str) -> None:
    task = asyncio.get_running_loop().create_task(coro, name=name)
    _bg.add(task)
    task.add_done_callback(_bg.discard)


# ── 조회 뷰 ─────────────────────────────────────────────────────────────

def job_view(row: IngestJob) -> Dict[str, Any]:
    out: Dict[str, Any] = {"id": row.id, "fileName": row.file_name, "status": row.status}
    if row.error is not None:
        out["error"] = row.error
    if row.doc_id is not None:
        out["docId"] = row.doc_id
    if row.created_at is not None:
        out["createdAt"] = row.created_at.isoformat()
    return out


def is_processing(doc_id: str) -> Dict[str, bool]:
    """화면 표시용 — 임베딩·카드 정리가 진행 중인가."""
    return {"enriching": doc_id in _enrich["active"] or any(x[0] == doc_id for x in _enrich["items"])}


# ── 등록 ────────────────────────────────────────────────────────────────

def enqueue(workspace_id: str, user_id: str, files: Iterable[Tuple[str | Path, str]], replaces: Optional[str] = None, folder_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """(임시 경로, 표시 파일명) 들을 인박스로 옮기고 작업 행으로 등록한다(즉시 반환). 처리는 워커가 한다.
    replaces = 새 판으로 올린 경우 이전 판 doc_id(처리가 끝나면 그 자리를 새 판이 차지한다). folder_id = 드라이브 폴더에 올린 경우."""
    out: List[Dict[str, Any]] = []
    with Session(engine) as s:
        repo = Repo(s)
        for src, file_name in files:
            job_id = id36("j", 4)
            dest = INBOX_DIR / f"{job_id}{Path(file_name).suffix.lower()}"
            shutil.copyfile(src, dest)
            out.append(job_view(repo.save_job(IngestJob(id=job_id, workspace_id=workspace_id, uploaded_by=user_id, file_name=str(file_name), src_path=str(dest), status="queued", replaces=replaces, folder_id=folder_id))))
    kick()
    return out


def kick() -> None:
    ev = _state.get("event")
    if ev is not None:
        ev.set()


def remove_inbox_file(path: Optional[str]) -> None:
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


# ── 워커 ────────────────────────────────────────────────────────────────

def start_worker() -> None:
    """FastAPI startup 에서 한 번. 재시작 시 processing → queued, 벡터가 없는 문서는 임베딩을 다시 건다."""
    task = _state.get("task")
    if task is not None and not task.done():
        kick()
        return
    loop = asyncio.get_running_loop()
    _state["loop"] = loop  # 스레드(run_in_threadpool)에서 임베딩을 예약할 때 쓴다
    ev = asyncio.Event()
    _state["event"] = ev
    _state["task"] = loop.create_task(_run(ev), name="docs-ingest")
    eev = asyncio.Event()
    _enrich.update({"event": eev, "items": [], "active": set(), "tried": set()})
    _enrich["tasks"] = [loop.create_task(_enrich_loop(eev), name=f"docs-enrich-{i}") for i in range(ENRICH_WORKERS)]
    _spawn(_refresh_store(), "docs-refresh-store")


def stop_worker() -> None:
    for t in [*(_enrich.get("tasks") or []), _state.get("task"), *list(_bg)]:
        if t is not None and not t.done():
            t.cancel()
    _state.update({"task": None, "event": None})


def _resume() -> None:
    with Session(engine) as s:
        repo = Repo(s)
        for r in repo.pending_jobs():
            if r.status == "processing":
                r.status = "queued"
                repo.save_job(r)


def _pick_next() -> Optional[str]:
    with Session(engine) as s:
        repo = Repo(s)
        for r in repo.pending_jobs():
            if r.status != "queued":
                continue
            if not r.src_path or not os.path.exists(r.src_path):
                r.status, r.error = "error", "원본 파일이 없습니다(임시 폴더 정리됨). 다시 올려 주세요."
                repo.save_job(r)
                continue
            return r.id
    return None


async def _run(ev: asyncio.Event) -> None:
    await asyncio.to_thread(_resume)
    while True:
        try:
            job_id = await asyncio.to_thread(_pick_next)
        except Exception:  # noqa: BLE001 — DB 가 잠깐 잠겨도 워커는 죽지 않는다
            logger.exception("[docs.queue] pick failed")
            job_id = None
            await asyncio.sleep(1)
        if job_id is None:
            ev.clear()
            await ev.wait()
            continue
        try:
            await process_job(job_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[docs.queue] job %s failed", job_id)


def _set_status(job_id: str, status: str, error: Optional[str] = None) -> Optional[Tuple[str, str, str]]:
    with Session(engine) as s:
        repo = Repo(s)
        row = repo.get_job(job_id)
        if not row:
            return None
        row.status, row.error = status, error
        repo.save_job(row)
        return row.workspace_id, row.src_path, row.file_name


def _finish_job(job_id: str, workspace_id: str, doc_id: str) -> None:
    """워크스페이스 자료 목록에 붙이고 done. 새 판이면 이전 판 자리를 차지한다(app.docs.versions).
    사내 공용 데이터로 올린 파일(workspace_id = COMPANY_SCOPE)은 사내 목록에 붙는다."""
    from app.docs.versions import register_version
    from app.services.document_service import attach_document

    with Session(engine) as s:
        repo = Repo(s)
        job = repo.get_job(job_id)
        ws = repo.workspace(workspace_id)
        if workspace_id == COMPANY_SCOPE:
            if s.get(CompanyDocument, doc_id) is None:
                repo.save(CompanyDocument(doc_id=doc_id, added_by=job.uploaded_by if job else ""))
        elif job and job.replaces and ws is not None:
            register_version(s, ws, job.replaces, doc_id, job.uploaded_by)
        else:
            attach_document(s, workspace_id, doc_id)
        if job and job.folder_id and workspace_id != COMPANY_SCOPE:
            from app.drive import place

            place(s, workspace_id, doc_id, "data", job.folder_id)
        if job:
            job.status, job.error, job.doc_id = "done", None, doc_id
            repo.save_job(job)


async def process_job(job_id: str) -> Optional[str]:
    started = await asyncio.to_thread(_set_status, job_id, "processing")
    if started is None:
        return None
    workspace_id, src_path, file_name = started
    try:
        prep = await asyncio.to_thread(prepare_document, src_path, file_name)
        doc_id = prep["id"]
        await asyncio.to_thread(_finish_job, job_id, workspace_id, doc_id)
        remove_inbox_file(src_path)
        if await asyncio.to_thread(needs_embedding, doc_id):
            schedule_embed(doc_id)
        if not prep.get("existing"):
            from app.assumptions.watch import on_uploaded

            _spawn(on_uploaded(doc_id, workspace_id), f"assume-recheck:{doc_id}")  # 직접 올린 공시·보유 내역도 감시 가정을 다시 판정
        return doc_id
    except asyncio.CancelledError:
        await asyncio.to_thread(_set_status, job_id, "queued")
        raise
    except Exception as err:  # noqa: BLE001
        logger.exception("[docs.queue] ingest failed: %s", file_name)
        await asyncio.to_thread(_set_status, job_id, "error", str(err)[:200])
        return None


# ── A': 게으른 임베딩 ───────────────────────────────────────────────────

def schedule_embed(doc_id: str) -> None:
    """게으른 임베딩 예약 — 이벤트 루프 안이면 바로, 스레드(데이터 연결 등)에서 부르면 워커의 루프로 넘긴다.
    루프가 없으면(테스트) 다음 시작 때 _embed_missing 이 한다."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = _state.get("loop")
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(lambda: _spawn(_embed_later(doc_id), f"docs-embed-{doc_id[:8]}"))
        return
    _spawn(_embed_later(doc_id), f"docs-embed-{doc_id[:8]}")


async def _embed_later(doc_id: str) -> None:
    global _embed_lock
    if _embed_lock is None:
        _embed_lock = asyncio.Lock()
    async with _embed_lock:  # 한 번에 한 편 — API 호출 한도를 나눠 쓴다
        try:
            await asyncio.to_thread(embed_document, doc_id)
        except Exception as e:  # noqa: BLE001 — 벡터가 없어도 BM25 로 검색된다
            logger.warning("[docs.queue] embed failed for %s: %s", doc_id, e)


async def _embed_missing() -> None:
    if not DOCUMENTS_DIR.exists():
        return
    for d in sorted(DOCUMENTS_DIR.iterdir()):
        if d.is_dir() and await asyncio.to_thread(needs_embedding, d.name):
            await _embed_later(d.name)


async def _refresh_store() -> None:
    """시작 때 한 번 — 청커가 바뀐 문서 다시 뽑기(그동안은 옛 청크로 검색된다) → 색인 없는 문서 색인."""
    if DOCUMENTS_DIR.exists():
        for d in sorted(DOCUMENTS_DIR.iterdir()):
            if d.is_dir() and await asyncio.to_thread(needs_rechunk, d.name):
                try:
                    await asyncio.to_thread(rechunk_document, d.name)
                except Exception as e:  # noqa: BLE001 — 한 문서 실패는 그 문서만(옛 청크로 남는다)
                    logger.warning("[docs.queue] rechunk failed for %s: %s", d.name, e)
    await _embed_missing()


# ── B: 카드 정리(온디맨드) ──────────────────────────────────────────────

def enqueue_enrich(doc_id: str, force: bool = False) -> bool:
    items: List[Tuple[str, bool]] = _enrich["items"]
    if doc_id in _enrich["active"] or any(x[0] == doc_id for x in items) or (doc_id in _enrich["tried"] and not force):
        return False
    items.append((doc_id, force))
    ev = _enrich.get("event")
    if ev is not None:
        ev.set()
    return True


def enqueue_cited(content: str) -> int:
    """본문에 인용된 문서 가운데 카드 정리가 안 된 것만 정리 큐에 넣는다. 어떤 오류도 올리지 않는다(작성 흐름을 막지 않게)."""
    n = 0
    try:
        for did in token_doc_ids(content or ""):
            meta = load_meta(did)
            if meta and not meta.get("enriched") and enqueue_enrich(did):
                n += 1
    except Exception:  # noqa: BLE001
        logger.exception("[docs.queue] enqueue_cited failed")
    return n


async def _enrich_loop(ev: asyncio.Event) -> None:
    while True:
        items: List[Tuple[str, bool]] = _enrich["items"]
        if not items:
            ev.clear()
            await ev.wait()
            continue
        doc_id, _force = items.pop(0)
        _enrich["active"].add(doc_id)
        try:
            if not await enrich_document(doc_id):
                _enrich["tried"].add(doc_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[docs.queue] enrich failed: %s", doc_id)
            _enrich["tried"].add(doc_id)
        finally:
            _enrich["active"].discard(doc_id)


async def enrich_document(doc_id: str) -> bool:
    from app.docs.card import enrich_card
    from app.llm.client import ReportLlm, provider_ready

    if not provider_ready():
        return False
    meta = await asyncio.to_thread(load_meta, doc_id)
    if not meta:
        return False
    card = await enrich_card(ReportLlm(), meta.get("card") or {}, meta.get("fileName") or "", meta.get("frontText") or "")
    if card is None:
        return False
    latest = await asyncio.to_thread(load_meta, doc_id) or meta
    latest["card"] = card
    latest["enriched"] = True
    await asyncio.to_thread(save_meta, doc_id, latest)
    try:
        await asyncio.to_thread(index_card, doc_id)  # 정리한 카드로 문서 카드 벡터도
    except Exception as e:  # noqa: BLE001
        logger.warning("[docs.queue] card index failed for %s: %s", doc_id, e)
    logger.info("[docs.queue] enriched %s: %s", doc_id, card.get("title"))
    return True
