"""벡터 저장소(Qdrant) — 문단 조각 컬렉션 + 문서 카드 컬렉션.

 - 기본은 로컬 모드: `QDRANT_PATH` 폴더(기본 data/qdrant)에 백엔드 프로세스 안에서 저장한다(별도 서버 없음, 데모 규모 — 전체 비교 검색).
   `.env` 에 `QDRANT_URL`(+ `QDRANT_API_KEY`)을 넣으면 같은 코드로 Qdrant 서버를 쓴다(필터를 반영한 HNSW·압축은 서버에서).
 - 로컬 모드 폴더는 한 프로세스만 열 수 있다 — 백엔드가 떠 있는 동안 스크립트로 같은 폴더를 열지 않는다.
 - 컬렉션 이름에 벡터 차원을 붙인다(`paragraphs_d2048`) — 임베딩 모델을 바꾸면 새 컬렉션으로 다시 색인된다.

문단 점(point) = 청크 조각 하나(chunks.json 순서, id = uuid5(문서 id:조각 번호)). payload 는 검색 조건만:
  doc_id · chunk(문단 id) · part · kind(prose|table) · page · years(언급 연도) · disclaimer(면책·고지) · lang(문서 언어) · doc_type · as_of
본문·줄 좌표는 chunks.json 에 있다(근거 보기·원문 확인 창이 거기서 읽는다) — 같은 내용을 두 곳에 두지 않는다.
문서 카드 점 = 문서 하나(제목·종류·날짜·발행처·요약·앞부분 임베딩) — 이름이 아닌 뜻으로 문서를 고를 때.
"""
from __future__ import annotations

import logging
import threading
import uuid
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app import config

log = logging.getLogger(__name__)

_NS = uuid.UUID("6f1c3a52-6b2e-4c1e-9d0b-1f2a3b4c5d6e")
_lock = threading.RLock()
_client: Any = None
_ready: Dict[str, int] = {}  # 만든 컬렉션 → 차원


def _qc() -> Any:
    global _client
    if _client is None:
        from qdrant_client import QdrantClient

        if config.QDRANT_URL:
            _client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY or None, timeout=30)
        else:
            config.QDRANT_PATH.mkdir(parents=True, exist_ok=True)
            _client = QdrantClient(path=str(config.QDRANT_PATH))
    return _client


def mode() -> str:
    return "server" if config.QDRANT_URL else "local"


def _name(kind: str, dim: int) -> str:
    return f"{kind}_d{dim}"


def _ensure(kind: str, dim: int) -> str:
    from qdrant_client import models

    name = _name(kind, dim)
    if name in _ready:
        return name
    c = _qc()
    if not c.collection_exists(name):
        c.create_collection(name, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))
        if config.QDRANT_URL:  # 로컬 모드는 색인 없이 전체 비교라 payload 색인이 의미 없다
            for field, schema in (("doc_id", models.PayloadSchemaType.KEYWORD), ("kind", models.PayloadSchemaType.KEYWORD), ("years", models.PayloadSchemaType.INTEGER), ("disclaimer", models.PayloadSchemaType.BOOL)):
                c.create_payload_index(name, field_name=field, field_schema=schema)
    _ready[name] = dim
    return name


def _existing(kind: str) -> List[str]:
    """이 종류의 컬렉션들(차원별) — 지울 때는 전부에서."""
    return [c.name for c in _qc().get_collections().collections if c.name.startswith(f"{kind}_d")]


def point_id(doc_id: str, n: int) -> str:
    return str(uuid.uuid5(_NS, f"{doc_id}:{n}"))


def _doc_filter(doc_id: str) -> Any:
    from qdrant_client import models

    return models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])


# ── 쓰기 ────────────────────────────────────────────────────────────────

def delete_doc(doc_id: str) -> None:
    """이 문서의 문단 점·카드 점을 모두 지운다(다시 뽑을 때·모델을 바꿀 때)."""
    from qdrant_client import models

    with _lock:
        for name in _existing("paragraphs") + _existing("documents"):
            _qc().delete(name, points_selector=models.FilterSelector(filter=_doc_filter(doc_id)))


def upsert_paragraphs(doc_id: str, payloads: Sequence[Dict[str, Any]], vectors: Sequence[Sequence[float]]) -> int:
    """문서의 조각 전부를 바꿔 넣는다(먼저 지우고). payloads[i] ↔ vectors[i] ↔ chunks.json 의 i 번째 조각. → 차원."""
    from qdrant_client import models

    if not vectors:
        return 0
    dim = len(vectors[0])
    with _lock:
        name = _ensure("paragraphs", dim)
        _qc().delete(name, points_selector=models.FilterSelector(filter=_doc_filter(doc_id)))
        points = [models.PointStruct(id=point_id(doc_id, i), vector=list(v), payload={"doc_id": doc_id, **p}) for i, (p, v) in enumerate(zip(payloads, vectors))]
        for k in range(0, len(points), 256):
            _qc().upsert(name, points=points[k : k + 256], wait=True)
    return dim


def upsert_card(doc_id: str, payload: Dict[str, Any], vector: Sequence[float]) -> None:
    from qdrant_client import models

    with _lock:
        name = _ensure("documents", len(vector))
        _qc().upsert(name, points=[models.PointStruct(id=point_id(doc_id, -1), vector=list(vector), payload={"doc_id": doc_id, **payload})], wait=True)


def count_doc(doc_id: str, dim: int) -> int:
    with _lock:
        name = _name("paragraphs", dim)
        if not _qc().collection_exists(name):
            return 0
        return int(_qc().count(name, count_filter=_doc_filter(doc_id), exact=True).count)


# ── 읽기 ────────────────────────────────────────────────────────────────

def _filter(doc_ids: Sequence[str], kind: Optional[str] = None, years: Optional[Sequence[int]] = None, exclude_disclaimer: bool = False) -> Any:
    from qdrant_client import models

    must: List[Any] = [models.FieldCondition(key="doc_id", match=models.MatchAny(any=list(doc_ids)))]
    if kind:
        must.append(models.FieldCondition(key="kind", match=models.MatchValue(value=kind)))
    if years:
        must.append(models.FieldCondition(key="years", match=models.MatchAny(any=[int(y) for y in years])))
    must_not = [models.FieldCondition(key="disclaimer", match=models.MatchValue(value=True))] if exclude_disclaimer else []
    return models.Filter(must=must, must_not=must_not or None)


def search_paragraphs(qvecs: Sequence[Sequence[float]], doc_ids: Sequence[str], limit: int, **cond: Any) -> List[Tuple[str, str, float]]:
    """질의 벡터들로 조각을 찾아 문단 단위로 묶는다(문단 점수 = 모든 질의·조각의 코사인 최대). → [(doc_id, 문단 id, 점수)] 점수 순."""
    if not qvecs or not doc_ids:
        return []
    name = _name("paragraphs", len(qvecs[0]))
    best: Dict[Tuple[str, str], float] = {}
    with _lock:
        if name not in _ready and not _qc().collection_exists(name):
            return []
        flt = _filter(doc_ids, **cond)
        for v in qvecs:
            res = _qc().query_points(name, query=list(v), query_filter=flt, limit=limit, with_payload=["doc_id", "chunk"])
            for p in res.points:
                key = (str(p.payload.get("doc_id")), str(p.payload.get("chunk")))
                if p.score > best.get(key, -2.0):
                    best[key] = float(p.score)
    return [(d, c, s) for (d, c), s in sorted(best.items(), key=lambda kv: -kv[1])]


def search_cards(qvec: Sequence[float], doc_ids: Sequence[str], limit: int = 5) -> List[Tuple[str, float]]:
    """문서 카드로 문서를 뜻으로 고른다. → [(doc_id, 점수)]."""
    if not qvec or not doc_ids:
        return []
    name = _name("documents", len(qvec))
    with _lock:
        if not _qc().collection_exists(name):
            return []
        res = _qc().query_points(name, query=list(qvec), query_filter=_filter(doc_ids), limit=limit, with_payload=["doc_id"])
    return [(str(p.payload.get("doc_id")), float(p.score)) for p in res.points]


def close() -> None:
    global _client
    with _lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:  # noqa: BLE001
                pass
            _client = None
            _ready.clear()


__all__ = ["close", "count_doc", "delete_doc", "mode", "point_id", "search_cards", "search_paragraphs", "upsert_card", "upsert_paragraphs"]
