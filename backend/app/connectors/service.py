"""데이터 연결 서비스 — 워크스페이스 화면의 "데이터 연결"(목록·회사 찾기·가져오기). 가져온 스냅샷은 워크스페이스 자료로 붙는다."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session

from app.auth import require_member
from app.connectors import dart, ecos, edgar
from app.connectors.base import ConnectorError, public_connectors
from app.db import User
from app.docs import queue as docs_queue
from app.docs.store import document_cards
from app.services.document_service import attach_document


def _http(e: ConnectorError) -> HTTPException:
    return HTTPException(e.http_status, {"code": e.code, "message": e.message})


class ConnectorService:
    def __init__(self, session: Session):
        self.session = session

    def listing(self, workspace_id: str, user: User) -> Dict[str, Any]:
        require_member(self.session, workspace_id, user)
        return {"connectors": public_connectors()}

    def dart_companies(self, workspace_id: str, user: User, q: str) -> Dict[str, List[Dict[str, Any]]]:
        require_member(self.session, workspace_id, user, "reviewer")
        try:
            return {"companies": dart.search_companies(q)}
        except ConnectorError as e:
            raise _http(e) from e

    def dart_financials(self, workspace_id: str, user: User, corp_code: str, corp_name: str, year: int, report: str, fs: str) -> Dict[str, Any]:
        require_member(self.session, workspace_id, user, "reviewer")
        try:
            snap = dart.fetch_financials(corp_code, corp_name, year, report, fs)
        except ConnectorError as e:
            raise _http(e) from e
        return self._attach(workspace_id, snap)

    def dart_overview(self, workspace_id: str, user: User, corp_code: str, corp_name: str, days: int = 365) -> Dict[str, Any]:
        require_member(self.session, workspace_id, user, "reviewer")
        try:
            snap = dart.fetch_overview(corp_code, corp_name, days)
        except ConnectorError as e:
            raise _http(e) from e
        return self._attach(workspace_id, snap)

    def dart_business(self, workspace_id: str, user: User, corp_code: str, corp_name: str, year: Optional[int] = None, report: str = "annual") -> Dict[str, Any]:
        """정기보고서 본문(회사 개요·사업의 내용·경영진단·주주·임직원) 스냅샷."""
        require_member(self.session, workspace_id, user, "reviewer")
        try:
            snap = dart.fetch_business(corp_code, corp_name, year, report)
        except ConnectorError as e:
            raise _http(e) from e
        return self._attach(workspace_id, snap)

    def prices_snapshot(self, workspace_id: str, user: User, ticker: str, name: str, days: int = 365) -> Dict[str, Any]:
        """사내 공용 일봉(price_bar) → 주가 요약·월말 종가 스냅샷 문서를 워크스페이스 자료로."""
        from app.market.prices import snapshot

        require_member(self.session, workspace_id, user, "reviewer")
        try:
            snap = snapshot(ticker, name, days)
        except ConnectorError as e:
            raise _http(e) from e
        return self._attach(workspace_id, snap)

    # ── SEC EDGAR ──
    def edgar_companies(self, workspace_id: str, user: User, q: str) -> Dict[str, List[Dict[str, Any]]]:
        require_member(self.session, workspace_id, user, "reviewer")
        try:
            return {"companies": edgar.search_companies(q)}
        except ConnectorError as e:
            raise _http(e) from e

    def edgar_financials(self, workspace_id: str, user: User, cik: int, name: str, year: int) -> Dict[str, Any]:
        require_member(self.session, workspace_id, user, "reviewer")
        try:
            snap = edgar.fetch_financials(cik, name, year)
        except ConnectorError as e:
            raise _http(e) from e
        return self._attach(workspace_id, snap)

    # ── 한국은행 ECOS ──
    def ecos_tables(self, workspace_id: str, user: User, q: str) -> Dict[str, List[Dict[str, Any]]]:
        require_member(self.session, workspace_id, user, "reviewer")
        try:
            return {"tables": ecos.search_tables(q)}
        except ConnectorError as e:
            raise _http(e) from e

    def ecos_items(self, workspace_id: str, user: User, stat_code: str) -> Dict[str, List[Dict[str, Any]]]:
        require_member(self.session, workspace_id, user, "reviewer")
        try:
            return {"items": ecos.list_items(stat_code)}
        except ConnectorError as e:
            raise _http(e) from e

    def ecos_series(self, workspace_id: str, user: User, body: Dict[str, str]) -> Dict[str, Any]:
        require_member(self.session, workspace_id, user, "reviewer")
        try:
            snap = ecos.fetch_series(body["statCode"], body.get("statName") or "", body["itemCode"], body.get("itemName") or "", body["cycle"], body["start"], body["end"])
        except ConnectorError as e:
            raise _http(e) from e
        return self._attach(workspace_id, snap)

    def _attach(self, workspace_id: str, snap: Dict[str, Any]) -> Dict[str, Any]:
        """스냅샷 문서를 워크스페이스 자료로 붙인다(연결마다 같다)."""
        attach_document(self.session, workspace_id, snap["id"])
        docs_queue.schedule_embed(snap["id"])  # 벡터는 뒤에서 — 그동안은 키워드 검색
        cards = document_cards([snap["id"]])
        return {"document": cards[0] if cards else None, "figures": snap["figures"], "title": snap["title"]}
