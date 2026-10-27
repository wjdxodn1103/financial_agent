"""문서 저장소 — OP `paper/refs/store.py` 이식. 문서 한 편 = `DOCUMENTS_DIR/<sha1 16자>/` 폴더 하나(세션과 무관하게 공유, 같은 파일은 한 번만).
  source.<ext>  원본
  meta.json     카드(제목·문서 종류·날짜·발행처·한 줄 요약) + 파일 정보 + 임베딩 모델·차원
  chunks.json   청크(조각 단위 — 본문·쪽·줄/칸 상자·제목 경로·연도·면책 태그). 벡터 저장소(Qdrant)의 점 순서와 같다.
벡터는 Qdrant(app/docs/vectorstore.py — 문단 조각 컬렉션 + 문서 카드 컬렉션). 아직 색인 전이면 그 문서는 BM25 로 찾는다 — 게으른 임베딩.

검색(search_docs)은 벡터(코사인)로 순위를 매기고, 벡터가 아직 없는 문단(올린 직후)만 BM25(영문 소문자 단어 + 한글 2-gram)로 찾는다.
금융 공개 보고서 6종·질의 55개 실측(2026-10-27): 벡터만 상위5 1.00 · 상위1 0.80, BM25 를 가중 0.25 로 섞으면 국문 질의→영문 자료에서 상위5 0.85 로 떨어졌다.
검색창·기업 이름 찾기처럼 낱말 일치가 목적인 곳은 lexical=True(BM25 + 벡터 RRF). 문서당 상한으로 다양성을 지킨다.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from app.config import DOCUMENTS_DIR
from app.llm.embeddings import Embedder, get_embedder

log = logging.getLogger(__name__)

Chunk = Dict[str, Any]
Meta = Dict[str, Any]
Hit = Dict[str, Any]  # {"docId", "chunk", "score", "via"}


def doc_dir(doc_id: str) -> Path:
    return DOCUMENTS_DIR / doc_id


def write_json_atomic(path: Path, data: Any) -> None:
    """`<path>.tmp` 에 다 쓰고 os.replace — 쓰다 죽어도 잘린 JSON 이 남지 않는다."""
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_json(p: Path) -> Any:
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        log.warning("문서 파일을 읽지 못해 없는 것으로 봅니다 (%s): %s", p, e)
        return None


def load_meta(doc_id: str) -> Optional[Meta]:
    m = _read_json(doc_dir(doc_id) / "meta.json")
    return m if isinstance(m, dict) else None


def save_meta(doc_id: str, meta: Meta) -> None:
    write_json_atomic(doc_dir(doc_id) / "meta.json", meta)


def load_chunks(doc_id: str) -> List[Chunk]:
    c = _read_json(doc_dir(doc_id) / "chunks.json")
    return c if isinstance(c, list) else []


def merge_fragments(chunks: Sequence[Chunk]) -> List[Chunk]:
    """조각(같은 id, part 1..parts)을 문단 하나로 잇는다. 항목마다 "fragments": [원 청크 인덱스…] 를 붙여 벡터(조각 순서)를 되찾게 한다."""
    out: List[Chunk] = []
    at: Dict[str, int] = {}
    for i, c in enumerate(chunks):
        pid = c.get("id")
        if isinstance(pid, str) and (c.get("parts") or 1) > 1 and pid in at:
            m = out[at[pid]]
            sep = "\n" if c.get("kind") == "table" else " "
            m["text"] = f"{m['text']}{sep}{c.get('text') or ''}".strip()
            m["fragments"].append(i)
            continue
        m = {k: v for k, v in c.items() if k != "part"}
        m["fragments"] = [i]
        if isinstance(pid, str):
            at[pid] = len(out)
        out.append(m)
    return out


def public_chunk(chunk: Chunk, index: Optional[int] = None) -> Chunk:
    out = {k: v for k, v in chunk.items() if k not in ("fragments", "parts")}
    if index is not None:
        out["index"] = index
    return out


def paragraphs(doc_id: str) -> List[Chunk]:
    """문서의 문단(조각을 합친 것) 목록 — 뷰어 페이징·근거 보기용."""
    return merge_fragments(load_chunks(doc_id))


def chunk_with_context(doc_id: str, chunk_id: str) -> Optional[Dict[str, Any]]:
    paras = paragraphs(doc_id)
    i = next((k for k, p in enumerate(paras) if p.get("id") == chunk_id), None)
    if i is None:
        return None
    return {
        "chunk": public_chunk(paras[i], i),
        "prev": public_chunk(paras[i - 1], i - 1) if i > 0 else None,
        "next": public_chunk(paras[i + 1], i + 1) if i + 1 < len(paras) else None,
        "total": len(paras),
    }


# ── 색인 상태 ────────────────────────────────────────────────────────────

def has_vectors(doc_id: str) -> bool:
    """벡터 저장소(Qdrant)에 이 문서의 조각이 다 들어갔나 — meta 의 색인 기록으로(저장소에 묻지 않는다)."""
    m = load_meta(doc_id) or {}
    return m.get("vectorStore") == "qdrant" and bool(m.get("embedModel")) and m.get("indexedChunks") == m.get("chunkCount")


# ── BM25(OP store.py 그대로) ─────────────────────────────────────────────
_TOKEN = re.compile(r"[a-z0-9][a-z0-9\-'.%]*|[가-힣]+")
_HANGUL_ONLY = re.compile(r"^[가-힣]+$")
_HAS_DIGIT = re.compile(r"[0-9]")


def tokenize(text: str) -> List[str]:
    """영문·숫자 단어(소문자) + 한글 연속 구간의 2-gram — 형태소 분석 없이도 한국어 검색이 되게."""
    out: List[str] = []
    for m in _TOKEN.finditer(text.lower()):
        t = m.group(0).rstrip(".")
        if _HANGUL_ONLY.match(t):
            if len(t) == 1:
                out.append(t)
            for i in range(len(t) - 1):
                out.append(t[i : i + 2])
        elif len(t) > 1 or _HAS_DIGIT.search(t):
            out.append(t)
    return out


class Bm25Index:
    __slots__ = ("df", "docs", "avgdl")

    def __init__(self, df: Dict[str, int], docs: List[Tuple[str, Dict[str, int], int]], avgdl: float):
        self.df = df
        self.docs = docs
        self.avgdl = avgdl


def build_bm25(items: Sequence[Dict[str, Any]]) -> Bm25Index:
    df: Dict[str, int] = {}
    docs: List[Tuple[str, Dict[str, int], int]] = []
    for c in items:
        toks = tokenize(c["text"])
        tf: Dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        for t in tf:
            df[t] = df.get(t, 0) + 1
        docs.append((c["id"], tf, len(toks)))
    avgdl = sum(d[2] for d in docs) / max(1, len(docs))
    return Bm25Index(df, docs, avgdl)


def bm25_scores(index: Bm25Index, query: str, k1: float = 1.5, b: float = 0.75) -> Dict[str, float]:
    N = len(index.docs)
    q = list(dict.fromkeys(tokenize(query)))
    out: Dict[str, float] = {}
    for did, tf, dlen in index.docs:
        s = 0.0
        for t in q:
            f = tf.get(t)
            if not f:
                continue
            n = index.df.get(t, 0)
            idf = math.log(1 + (N - n + 0.5) / (n + 0.5))
            s += idf * ((f * (k1 + 1)) / (f + k1 * (1 - b + (b * dlen) / max(index.avgdl, 1e-9))))
        if s > 0:
            out[did] = s
    return out


# ── 검색 ────────────────────────────────────────────────────────────────
# 벡터가 아직 없는 문단의 BM25 순위는 이만큼 뒤에서 시작한다 — 임베딩을 기다리는 동안 다른 질의의 1~3위를 그 문서의 낱말 일치가 차지하지 않게(실측: 0 이면 상위1 0.87 → 0.35)
PENDING_RANK_OFFSET = 3
# lexical 검색(검색창·기업 이름 찾기)에서 RRF 의 BM25 항 가중(벡터가 있을 때) — OP 50질의 벤치(2026-09-28)에서 0.25 가 가장 좋았다. 벡터가 없으면 BM25 단독 = 1.0
BM25_WEIGHT = 0.25


class _Corpus:
    """BM25 코퍼스 — 검색창(lexical)·벡터가 아직 없는 문서·벡터를 못 쓸 때만 만든다."""

    __slots__ = ("docs", "index")

    def __init__(self, docs: List[Dict[str, Any]], index: Bm25Index):
        self.docs = docs
        self.index = index


_CORPUS_MAX = 8
_corpus_cache: "OrderedDict[Tuple[str, ...], Tuple[Tuple[Any, ...], _Corpus]]" = OrderedDict()
_corpus_lock = threading.Lock()


def _stamp(doc_ids: Sequence[str]) -> Tuple[Any, ...]:
    """무효화 서명 — 문서마다 chunks.json 의 mtime."""
    out: List[Any] = []
    for d in doc_ids:
        try:
            out.append(doc_dir(d).joinpath("chunks.json").stat().st_mtime_ns)
        except OSError:
            out.append(None)
    return tuple(out)


def _build_corpus(doc_ids: Sequence[str]) -> _Corpus:
    docs: List[Dict[str, Any]] = []
    for did in doc_ids:
        for c in merge_fragments(load_chunks(did)):
            docs.append({"gid": f"{did}::{c['id']}", "docId": did, "chunk": public_chunk(c)})
    return _Corpus(docs, build_bm25([{"id": d["gid"], "text": f"{d['chunk'].get('heading') or ''} {d['chunk']['text']}"} for d in docs]))


def _corpus_for(doc_ids: Sequence[str]) -> _Corpus:
    key = tuple(doc_ids)
    stamp = _stamp(doc_ids)
    with _corpus_lock:
        hit = _corpus_cache.get(key)
        if hit is not None and hit[0] == stamp:
            _corpus_cache.move_to_end(key)
            return hit[1]
    corpus = _build_corpus(doc_ids)
    with _corpus_lock:
        _corpus_cache[key] = (stamp, corpus)
        _corpus_cache.move_to_end(key)
        while len(_corpus_cache) > _CORPUS_MAX:
            _corpus_cache.popitem(last=False)
    return corpus


_para_cache: "OrderedDict[str, Tuple[Any, Dict[str, Chunk]]]" = OrderedDict()


def _para(doc_id: str, chunk_id: str) -> Optional[Chunk]:
    """문단 하나(조각을 합친 것) — 벡터 검색 결과를 화면·프롬프트 모양으로. 문서별 캐시(chunks.json mtime)."""
    stamp = _stamp([doc_id])
    with _corpus_lock:
        hit = _para_cache.get(doc_id)
        if hit is None or hit[0] != stamp:
            hit = (stamp, {str(c["id"]): public_chunk(c) for c in merge_fragments(load_chunks(doc_id))})
            _para_cache[doc_id] = hit
            while len(_para_cache) > 64:
                _para_cache.popitem(last=False)
        _para_cache.move_to_end(doc_id)
    return hit[1].get(chunk_id)


# 연도는 빼는 조건이 아니라 앞으로 올리는 가산점 — 보고서 본문은 "상반기"·"the first half of the year" 처럼 연도를 안 쓰는 문단이 많다
# (실측: year=2025 로 거르자 정답 문단 "relative return of -10 billion kroner" 가 빠져 '자료에 없음' 으로 답했다)
YEAR_BOOST = 0.5


def _passes(c: Chunk, kind: Optional[str], exclude_disclaimer: bool) -> bool:
    """BM25 쪽에도 벡터 저장소와 같은 조건(표/본문·면책)."""
    if kind and c.get("kind") != kind:
        return False
    return not (exclude_disclaimer and c.get("disclaimer"))


def search_docs(
    doc_ids: Sequence[str],
    query: Union[str, Sequence[str]],
    k: int = 6,
    per_doc: int = 2,
    embedder: Optional[Embedder] = None,
    lexical: bool = False,
    kind: Optional[str] = None,
    years: Optional[Sequence[int]] = None,
    exclude_disclaimer: bool = False,
) -> List[Hit]:
    """여러 문서에 걸쳐 검색. 질의는 여러 개(국문·영문)를 받는다 — 벡터는 문단마다 모든 질의·조각의 코사인 최대(벡터 저장소 Qdrant).
    기본(AI 근거 검색) = 벡터 순위. 벡터가 아직 없는 문서(게으른 임베딩 대기)만 BM25 순위로 끼우고(RRF w/(60+rank)), 벡터를 못 쓰면(질의 임베딩 실패·임베더 없음) BM25 만.
    lexical=True(검색창·기업 이름 찾기) = BM25 전체 + 벡터를 RRF 로(BM25 가중 BM25_WEIGHT).
    조건(벡터·BM25 둘 다): kind(table|prose) · exclude_disclaimer(면책·고지 문단 빼기). years 는 가산점(그 연도가 나오는 문단을 앞으로, 빼지는 않는다)."""
    from app.docs import vectorstore

    qs = [query] if isinstance(query, str) else list(query)
    queries = [q.strip() for q in qs if q and q.strip()]
    if not queries or not doc_ids:
        return []
    depth = max(20, k * 5)
    fused: Dict[str, Dict[str, Any]] = {}

    def add(gid: str, r: int, via: str, w: float = 1.0) -> None:
        cur = fused.get(gid)
        fused[gid] = {"s": (cur["s"] if cur else 0.0) + w / (60 + r), "via": [*(cur["via"] if cur else []), via]}

    indexed = [d for d in doc_ids if has_vectors(d)]
    scored: List[Tuple[str, float]] = []
    year_hits: List[str] = []
    if indexed:
        emb = embedder or get_embedder()
        qvs = [v for v in (emb.embed_query(q) for q in queries) if v] if emb.model else []
        if qvs:
            try:
                scored = [(f"{d}::{c}", s) for d, c, s in vectorstore.search_paragraphs(qvs, indexed, depth * 2, kind=kind, exclude_disclaimer=exclude_disclaimer)]
                if years:
                    year_hits = [f"{d}::{c}" for d, c, _s in vectorstore.search_paragraphs(qvs, indexed, depth, kind=kind, years=years, exclude_disclaimer=exclude_disclaimer)]
            except Exception as e:  # noqa: BLE001 — 벡터 저장소가 안 되면 BM25 로 계속
                log.warning("[store] vector search failed — BM25 only: %s", e)
    pending = [d for d in doc_ids if d not in set(indexed)]
    bm_ids = list(doc_ids) if (lexical or not scored) else pending
    by_gid: Dict[str, Dict[str, Any]] = {}
    if bm_ids:
        corpus = _corpus_for(bm_ids)
        by_gid = {d["gid"]: d for d in corpus.docs}
        bm = [x for x in sorted(bm25_scores(corpus.index, " ".join(queries)).items(), key=lambda kv: -kv[1]) if _passes(by_gid[x[0]]["chunk"], kind, exclude_disclaimer)]
        offset = PENDING_RANK_OFFSET if (scored and not lexical) else 0  # 벡터 결과 사이에 끼울 때만 뒤로
        for r, (gid, _s) in enumerate(bm[:depth]):
            add(gid, r + offset, "bm25", BM25_WEIGHT if lexical and scored else 1.0)
    for r, (gid, _s) in enumerate(scored[:depth]):
        add(gid, r, "vector")
    for r, gid in enumerate(year_hits):
        add(gid, r, "year", YEAR_BOOST)
    count: Dict[str, int] = {}
    out: List[Hit] = []
    for gid, rec in sorted(fused.items(), key=lambda kv: -kv[1]["s"]):
        did, cid = gid.split("::", 1)
        chunk = by_gid[gid]["chunk"] if gid in by_gid else _para(did, cid)
        if chunk is None or count.get(did, 0) >= per_doc:
            continue  # 색인과 chunks.json 이 어긋난 조각(다시 뽑는 중) — 건너뛴다
        count[did] = count.get(did, 0) + 1
        out.append({"docId": did, "chunk": chunk, "score": rec["s"], "via": rec["via"]})
        if len(out) >= k:
            break
    return out


def search_cards(doc_ids: Sequence[str], query: str, k: int = 3, embedder: Optional[Embedder] = None) -> List[Tuple[str, float]]:
    """문서 카드(제목·종류·날짜·요약·앞부분)로 문서를 뜻으로 고른다 — 이름이 안 맞을 때. 벡터가 없으면 []."""
    from app.docs import vectorstore

    emb = embedder or get_embedder()
    if not emb.model or not query.strip():
        return []
    v = emb.embed_query(query.strip())
    if not v:
        return []
    try:
        return vectorstore.search_cards(v, [d for d in doc_ids if has_vectors(d)], k)
    except Exception as e:  # noqa: BLE001
        log.warning("[store] card search failed: %s", e)
        return []


# ── 카드(화면·프롬프트용) ───────────────────────────────────────────────

_HANGUL = re.compile(r"[가-힣]")
_LATIN = re.compile(r"[A-Za-z]")
_lang_cache: Dict[Tuple[str, Optional[int]], str] = {}


def doc_language(doc_id: str) -> str:
    """'en' | 'ko' — 앞쪽 문단 글자로 어림(라틴 글자가 한글의 5배를 넘으면 영문). 검색 도구가 영문 자료에 영문 질의를 같이 쓰게 하려는 표시."""
    try:
        stamp: Optional[int] = doc_dir(doc_id).joinpath("chunks.json").stat().st_mtime_ns
    except OSError:
        stamp = None
    key = (doc_id, stamp)
    if key not in _lang_cache:
        text = " ".join((c.get("text") or "") for c in load_chunks(doc_id)[:40])
        ko, en = len(_HANGUL.findall(text)), len(_LATIN.findall(text))
        _lang_cache[key] = "en" if en > 5 * ko and en > 200 else "ko"
    return _lang_cache[key]


def doc_label(meta: Optional[Meta], doc_id: str = "") -> str:
    """사람이 읽는 짧은 이름 — 카드 제목(없으면 파일명). 출처 표기·검색 결과·참고 자료 목록이 같이 쓴다."""
    if not meta:
        return doc_id[:8]
    card = meta.get("card") or {}
    title = (card.get("title") or "").strip() or re.sub(r"\.[A-Za-z0-9]+$", "", meta.get("fileName") or doc_id)
    return title if len(title) <= 40 else title[:39] + "…"


def source_size(doc_id: str, meta: Meta) -> int:
    """올린 원본 파일 크기(바이트) — 데이터 목록에 보인다. 원본이 없으면 0."""
    src = meta.get("source")
    try:
        return (doc_dir(doc_id) / src).stat().st_size if src else 0
    except OSError:
        return 0


def document_cards(doc_ids: Sequence[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for did in doc_ids:
        m = load_meta(did)
        if not m:
            continue
        c = m.get("card") or {}
        out.append(
            {
                "id": did,
                "label": doc_label(m, did),
                "title": c.get("title") or "",
                "docType": c.get("docType") or "",
                "date": c.get("date") or "",
                "issuer": c.get("issuer") or "",
                "company": c.get("company") or "",
                "oneLine": c.get("oneLine") or "",
                "fileName": m.get("fileName") or "",
                "fileType": m.get("fileType") or "",
                "pageCount": m.get("pageCount"),
                "chunkCount": m.get("chunkCount") or 0,
                "paragraphCount": m.get("paragraphCount") or 0,
                "embedded": bool(m.get("embedModel")) and has_vectors(did),
                "enriched": bool(m.get("enriched")),
                "createdAt": m.get("createdAt"),
                "size": source_size(did, m),
                "snapshot": {k: (m.get("snapshot") or {}).get(k) for k in ("connector", "title", "fetchedAt", "url")} if m.get("snapshot") else None,
            }
        )
    return out
