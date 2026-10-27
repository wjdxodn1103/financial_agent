"""임베딩 — NVIDIA build `/v1/embeddings`(OpenAI 호환 + input_type).

OP 는 로컬 ONNX(EmbeddingGemma)였지만 여기서는 API 로 부른다(모델 파일·onnxruntime 없음, 데모 배포가 쉽다).
기본 모델 `nvidia/nemotron-3-embed-1b`(2048차원, 한·영 교차 검색 실측 OK — 2026-10-08 프로브).
 - 문단은 input_type="passage", 질의는 "query". 입력이 길면 서버가 끝을 자른다(truncate=END).
 - 벡터는 L2 정규화해서 돌려준다(검색은 내적 = 코사인).
 - 모델 이름이 비었거나 키가 없으면 NullEmbedder — 검색은 BM25 만으로 동작한다.
동기 함수다(인제스트 워커·검색이 스레드에서 부른다).
"""
from __future__ import annotations

import logging
import math
import threading
from collections import OrderedDict
from typing import List, Optional, Protocol, Sequence

import httpx

from app import config

log = logging.getLogger(__name__)

BATCH = 32
_QUERY_CACHE_MAX = 256


class Embedder(Protocol):
    model: Optional[str]

    def embed_passages(self, texts: Sequence[str]) -> Optional[List[List[float]]]: ...

    def embed_query(self, text: str) -> Optional[List[float]]: ...


class NullEmbedder:
    model: Optional[str] = None

    def embed_passages(self, texts: Sequence[str]) -> Optional[List[List[float]]]:
        return None

    def embed_query(self, text: str) -> Optional[List[float]]:
        return None


def _normalize(v: List[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class NvidiaEmbedder:
    def __init__(self, model: str):
        self.model: Optional[str] = model
        self._client = httpx.Client(timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0))
        self._lock = threading.Lock()
        self._qcache: "OrderedDict[str, List[float]]" = OrderedDict()

    def _post(self, texts: Sequence[str], input_type: str) -> List[List[float]]:
        body = {"input": list(texts), "model": self.model, "input_type": input_type, "encoding_format": "float", "truncate": "END"}
        r = self._client.post(
            config.NVIDIA_BASE_URL.rstrip("/") + "/embeddings",
            json=body,
            headers={"Authorization": f"Bearer {config.NVIDIA_API_KEY}", "Content-Type": "application/json"},
        )
        if r.status_code != 200:
            raise RuntimeError(f"embeddings {r.status_code}: {r.text[:200]}")
        data = sorted(r.json().get("data") or [], key=lambda d: d.get("index", 0))
        return [_normalize([float(x) for x in d["embedding"]]) for d in data]

    def embed_passages(self, texts: Sequence[str]) -> Optional[List[List[float]]]:
        out: List[List[float]] = []
        for i in range(0, len(texts), BATCH):
            out.extend(self._post(texts[i : i + BATCH], "passage"))
        return out

    def embed_query(self, text: str) -> Optional[List[float]]:
        with self._lock:
            hit = self._qcache.get(text)
            if hit is not None:
                self._qcache.move_to_end(text)
                return hit
        try:
            v = self._post([text], "query")[0]
        except Exception as e:  # noqa: BLE001 — 질의 임베딩이 실패해도 BM25 로 계속
            log.warning("[embed] query embedding failed — BM25 only: %s", e)
            return None
        with self._lock:
            self._qcache[text] = v
            while len(self._qcache) > _QUERY_CACHE_MAX:
                self._qcache.popitem(last=False)
        return v


_default: Optional[Embedder] = None
_default_lock = threading.Lock()


def get_embedder() -> Embedder:
    global _default
    if _default is not None:
        return _default
    with _default_lock:
        if _default is None:
            if config.EMBED_MODEL and config.NVIDIA_API_KEY:
                _default = NvidiaEmbedder(config.EMBED_MODEL)
            else:
                log.info("[embed] EMBED_MODEL 또는 NVIDIA_API_KEY 없음 — 검색은 BM25 만")
                _default = NullEmbedder()
    return _default
