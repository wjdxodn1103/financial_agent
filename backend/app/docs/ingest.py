"""인제스트 — 업로드 파일 하나를 문서 폴더로 만든다(CPU 작업, 스레드에서 부른다).
  prepare_document: 폴더·원본 복사 → 추출(extract) → 청크(chunk) → chunks.json → 임시 카드(LLM 없음) → meta.json
  embed_document:   chunks.json → NVIDIA 임베딩 → 벡터 저장소(Qdrant) 문단 조각 + 문서 카드 (게으른 임베딩: 워커가 뒤에서 한 편씩)
  rechunk_document: 청커가 바뀐 옛 문서를 원본에서 다시 뽑는다(서버 시작 때 — 문단 id 는 나누는 규칙이 같으면 그대로)
같은 파일(sha1)은 한 번만 처리하고 기존 id 를 돌려준다.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.docs.card import temp_card
from app.docs.chunk import CHUNKER_VERSION, chunk_paragraphs
from app.docs.extract import extract
from app.docs.store import doc_dir, doc_language, has_vectors, load_chunks, load_meta, save_meta, write_json_atomic
from app.llm.embeddings import Embedder, get_embedder

log = logging.getLogger(__name__)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha1_id(path: str | Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def prepare_document(path: str | Path, file_name: str) -> Dict[str, Any]:
    """→ {"id", "existing": bool}. 추출에 실패하면 폴더를 지우고 ValueError 를 올린다(작업 행이 오류로 남는다)."""
    did = sha1_id(path)
    d = doc_dir(did)
    old = load_meta(did) if (d / "meta.json").exists() else None
    if old is not None and (old.get("chunker") or 0) >= CHUNKER_VERSION:
        return {"id": did, "existing": True}
    if old is not None:
        # 청커가 바뀐 옛 문서 — 다시 뽑는다(벡터 저장소의 옛 점도 지운다). 카드 정리 결과는 살린다
        shutil.rmtree(d, ignore_errors=True)
        _drop_points(did)
    d.mkdir(parents=True, exist_ok=True)
    try:
        ext = Path(file_name).suffix.lower() or ".bin"
        shutil.copyfile(path, d / f"source{ext}")
        ex = extract(path, file_name)
        chunks = chunk_paragraphs(ex["paras"])
        write_json_atomic(d / "chunks.json", chunks)
        meta = {
            "id": did,
            "fileName": file_name,
            "fileType": ex["fileType"],
            "source": f"source{ext}",
            "pageCount": ex["meta"].get("pageCount"),
            "chunkCount": len(chunks),
            "paragraphCount": len(ex["paras"]),
            "chunker": CHUNKER_VERSION,
            "embedModel": None,
            "embedDim": None,
            "card": (old or {}).get("card") if (old or {}).get("enriched") else temp_card(ex, file_name),
            "frontText": (ex.get("frontText") or "")[:4000],
            "enriched": bool((old or {}).get("enriched")),
            "createdAt": (old or {}).get("createdAt") or now_iso(),  # 다시 뽑아도 올린 시각은 그대로
        }
        save_meta(did, meta)
        from app.ledger.figures import build_figures, save_figures

        save_figures(did, build_figures(did))  # 근거 원장(표 칸 → 수치) — 결정적, LLM 0회
        return {"id": did, "existing": False}
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise


def _drop_points(doc_id: str) -> None:
    from app.docs import vectorstore

    try:
        vectorstore.delete_doc(doc_id)
    except Exception as e:  # noqa: BLE001 — 지우지 못해도 다시 넣을 때 같은 id 로 덮는다
        log.warning("[ingest] could not drop vectors of %s: %s", doc_id, e)


def _card_text(meta: Dict[str, Any]) -> str:
    c = meta.get("card") or {}
    head = " · ".join(x for x in (c.get("title"), c.get("docType"), c.get("date"), c.get("issuer"), c.get("company")) if x)
    return "\n".join(x for x in (head, c.get("oneLine") or "", (meta.get("frontText") or "")[:1200]) if x)


def index_card(doc_id: str, embedder: Optional[Embedder] = None) -> bool:
    """문서 카드 점을 넣거나 바꾼다(카드 정리 뒤에도 부른다). 임베더가 없으면 False."""
    from app.docs import vectorstore

    emb = embedder or get_embedder()
    meta = load_meta(doc_id)
    if not emb.model or not meta:
        return False
    vec = emb.embed_passages([_card_text(meta)])
    if not vec:
        return False
    c = meta.get("card") or {}
    vectorstore.upsert_card(doc_id, {"title": c.get("title") or meta.get("fileName") or "", "doc_type": c.get("docType") or "", "as_of": c.get("date") or "", "issuer": c.get("issuer") or "", "lang": doc_language(doc_id)}, vec[0])
    return True


def embed_document(doc_id: str, embedder: Optional[Embedder] = None) -> bool:
    """저장된 청크를 임베딩해 벡터 저장소(Qdrant)에 넣는다(조각마다 점 하나 + 문서 카드 점 하나, 카드·청크 불변).
    임베딩 입력 = 제목 + 본문(벤치에서 잰 그대로). 임베더가 없으면 False. 실패는 예외로(워커가 로그만 남긴다)."""
    from app.docs import vectorstore

    emb = embedder or get_embedder()
    if not emb.model:
        return False
    meta = load_meta(doc_id)
    chunks = load_chunks(doc_id)
    if not meta or not chunks:
        return False
    t0 = time.perf_counter()
    vectors = emb.embed_passages([f"{c.get('heading') + chr(10) if c.get('heading') else ''}{c['text']}" for c in chunks])
    if not vectors:
        return False
    card = meta.get("card") or {}
    lang = doc_language(doc_id)
    payloads = [
        {"chunk": str(c.get("id")), "part": int(c.get("part") or 1), "kind": c.get("kind") or "prose", "page": c.get("page"), "years": c.get("years") or [], "disclaimer": bool(c.get("disclaimer")), "lang": lang, "doc_type": card.get("docType") or "", "as_of": card.get("date") or ""}
        for c in chunks
    ]
    dim = vectorstore.upsert_paragraphs(doc_id, payloads, vectors)
    index_card(doc_id, emb)
    (doc_dir(doc_id) / "vectors.bin").unlink(missing_ok=True)  # 예전 파일 벡터(Qdrant 이전)
    latest = load_meta(doc_id) or meta
    latest.update({"embedModel": emb.model, "embedDim": dim, "vectorStore": "qdrant", "indexedChunks": len(chunks)})
    save_meta(doc_id, latest)
    log.info("[ingest] indexed %s in qdrant (%d chunks, dim %d, %.1fs)", doc_id, len(chunks), dim, time.perf_counter() - t0)
    return True


def needs_embedding(doc_id: str, embedder: Optional[Embedder] = None) -> bool:
    emb = embedder or get_embedder()
    if not emb.model:
        return False
    meta = load_meta(doc_id)
    return bool(meta) and (meta.get("embedModel") != emb.model or not has_vectors(doc_id))


def needs_rechunk(doc_id: str) -> bool:
    """청커가 바뀐 옛 문서인가(원본 파일에서 다시 뽑을 수 있는 것만 — 데이터 연결 스냅샷은 제외)."""
    meta = load_meta(doc_id)
    if not meta or meta.get("snapshot") or (meta.get("chunker") or 0) >= CHUNKER_VERSION:
        return False
    src = doc_dir(doc_id) / str(meta.get("source") or "")
    return bool(meta.get("source")) and src.is_file()


def rechunk_document(doc_id: str) -> bool:
    """원본에서 다시 뽑는다(같은 내용이라 id 그대로). prepare_document 가 폴더를 비우므로 원본을 잠깐 옮겨 둔다."""
    import tempfile

    meta = load_meta(doc_id) or {}
    src = doc_dir(doc_id) / str(meta.get("source") or "")
    if not src.is_file():
        return False
    with tempfile.TemporaryDirectory(prefix="rechunk_") as tmp:
        copy = Path(tmp) / src.name
        shutil.copyfile(src, copy)
        out = prepare_document(copy, meta.get("fileName") or src.name)
    log.info("[ingest] rechunked %s (chunker %s → %s)", doc_id, meta.get("chunker"), CHUNKER_VERSION)
    return out.get("id") == doc_id
