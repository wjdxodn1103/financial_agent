"""수집한 것 → 보통 문서(청크·문서 카드·벡터·원장 수치) — 업로드 파일과 같은 길(prepare_document)이라 AI 검색·작성·원문 창이 그대로 동작한다.
카드(제목·종류·날짜·발행처)는 수집할 때 이미 확실하므로 그대로 넣고(LLM 정리 생략), 원문 주소·발행일·접수번호는 meta.snapshot 에 둔다.
"""
from __future__ import annotations

import hashlib
import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Optional

from sqlmodel import Session

from app import config
from app.db import CompanyDocument, engine
from app.docs.ingest import prepare_document
from app.docs.store import load_meta, save_meta
from app.ids import now_iso

log = logging.getLogger(__name__)
PIPE_DIR = config.INBOX_DIR / "pipeline"


def attach(doc_id: str, scope: str, workspace_id: str = "", folder_id: Optional[str] = None, added_by: str = "") -> None:
    from app.services.document_service import attach_document

    with Session(engine) as s:
        if scope == "company":
            if s.get(CompanyDocument, doc_id) is None:
                s.add(CompanyDocument(doc_id=doc_id, added_by=added_by))
                s.commit()
        elif workspace_id:
            attach_document(s, workspace_id, doc_id)
            if folder_id:
                from app.drive import place

                place(s, workspace_id, doc_id, "data", folder_id)


def _after(doc_id: str, card: Optional[Dict[str, Any]], snapshot: Dict[str, Any]) -> None:
    meta = load_meta(doc_id) or {}
    if card:
        meta["card"] = {**(meta.get("card") or {}), **{k: v for k, v in card.items() if v}}
        meta["enriched"] = True
    meta["snapshot"] = {**(meta.get("snapshot") or {}), **snapshot, "fetchedAt": snapshot.get("fetchedAt") or now_iso()}
    save_meta(doc_id, meta)
    try:
        from app.docs.ingest import index_card

        index_card(doc_id)
    except Exception:  # noqa: BLE001 — 카드 벡터는 다음 임베딩 때 다시
        log.debug("index_card failed %s", doc_id)
    try:
        from app.docs.queue import schedule_embed

        schedule_embed(doc_id)
    except Exception:  # noqa: BLE001
        log.debug("schedule_embed failed %s", doc_id)


def add_file(path: Path, file_name: str, *, card: Optional[Dict[str, Any]], snapshot: Dict[str, Any], scope: str, workspace_id: str = "", folder_id: Optional[str] = None, added_by: str = "") -> str:
    prep = prepare_document(path, file_name)
    did = prep["id"]
    _after(did, card, snapshot)
    attach(did, scope, workspace_id, folder_id, added_by)
    return did


def add_text(text: str, file_name: str, **kw: Any) -> str:
    PIPE_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w.\-가-힣]+", "_", file_name)[:80] or "item"
    p = PIPE_DIR / f"{hashlib.sha1(text.encode('utf-8')).hexdigest()[:10]}_{safe}"
    if p.suffix.lower() not in (".md", ".txt"):
        p = p.with_suffix(".md")
    p.write_text(text, encoding="utf-8")
    try:
        return add_file(p, p.name if file_name.lower().endswith((".md", ".txt")) else f"{file_name}.md", **kw)
    finally:
        try:
            p.unlink()
        except OSError:
            pass


class _Text(HTMLParser):
    SKIP = {"script", "style", "nav", "header", "footer", "noscript", "svg", "form", "aside"}
    BLOCK = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "br", "section", "article", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.out.append(data)


def html_text(html: str) -> str:
    """보도자료 HTML → 본문 글(문단마다 빈 줄). 짧은 메뉴 줄은 뺀다."""
    p = _Text()
    try:
        p.feed(html or "")
    except Exception:  # noqa: BLE001
        pass
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in "".join(p.out).split("\n")]
    keep = [ln for ln in lines if len(ln) >= 40 or (ln and ln[-1:] in ".:%)")]
    return "\n\n".join(dict.fromkeys(keep))
