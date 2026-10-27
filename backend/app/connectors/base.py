"""데이터 연결 공통 규격 — 조회 → **스냅샷 문서** → figures.

외부에서 가져온 데이터도 업로드 자료와 똑같은 문서 폴더가 된다(chunks.json·meta.json·figures.json·source.json).
meta.snapshot 에 연결 이름·조회 조건·조회 시각·원본 주소를 남겨 "언제 기준 값인지"가 보이게 한다.
새 연결(EDGAR·ECOS·FRED·사내 DB)은 CONNECTORS 등록표에 하나 더하고 같은 make_snapshot 을 쓴다.
"""
from __future__ import annotations

import hashlib
import shutil
import time
from typing import Any, Callable, Dict, List, Optional

from app.docs.chunk import CHUNKER_VERSION, chunk_paragraphs
from app.docs.store import doc_dir, save_meta, write_json_atomic
from app.ledger.figures import build_figures, save_figures


class ConnectorError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def snapshot_id(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def make_snapshot(
    doc_id: str,
    *,
    file_name: str,
    file_type: str,
    paras: List[Dict[str, Any]],
    raw: Any,
    card: Dict[str, Any],
    snapshot: Dict[str, Any],
    figure_source: str,
    period_map: Optional[Dict[str, str]] = None,
    basis: Optional[str] = None,
) -> Dict[str, Any]:
    """스냅샷 문서 폴더를 만든다(같은 id 면 덮어쓴다 — 같은 날 같은 조건은 같은 스냅샷). → {"id", "figures": n}"""
    d = doc_dir(doc_id)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    try:
        write_json_atomic(d / "source.json", raw)
        chunks = chunk_paragraphs(paras)
        write_json_atomic(d / "chunks.json", chunks)
        front = "\n".join(p["text"] for p in paras[:10])[:3000]
        save_meta(
            doc_id,
            {
                "id": doc_id,
                "fileName": file_name,
                "fileType": file_type,
                "source": "source.json",
                "pageCount": None,
                "chunkCount": len(chunks),
                "paragraphCount": len(paras),
                "chunker": CHUNKER_VERSION,
                "embedModel": None,
                "embedDim": None,
                "card": card,
                "frontText": front,
                "enriched": True,  # 카드는 연결이 정확히 채운다(LLM 정리 불필요)
                "snapshot": snapshot,
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
        )
        figures = []
        for f in build_figures(doc_id):
            f = {**f, "source": figure_source}
            if period_map and f.get("period") in period_map:
                f["periodKey"] = period_map[f["period"]]  # 연결이 기간을 정확히 안다(누적·분기말 구분)
            if basis:
                f["basis"] = basis
            figures.append(f)
        save_figures(doc_id, figures, source=figure_source)
        return {"id": doc_id, "figures": len(figures)}
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise


# 연결 등록표 — {id: {title, desc, enabled() -> bool}}. 화면의 "데이터 연결" 목록이 여기서 나온다.
CONNECTORS: Dict[str, Dict[str, Any]] = {}


def register(cid: str, title: str, desc: str, enabled: Callable[[], bool], hint: Optional[str] = None) -> None:
    CONNECTORS[cid] = {"id": cid, "title": title, "desc": desc, "enabled": enabled, "hint": hint or ""}


def public_connectors() -> List[Dict[str, Any]]:
    return [{"id": c["id"], "title": c["title"], "desc": c["desc"], "ready": bool(c["enabled"]()), "hint": c["hint"]} for c in CONNECTORS.values()]
