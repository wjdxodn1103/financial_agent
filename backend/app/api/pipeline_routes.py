"""수집 소스·시장 데이터·데이터 품질 API(2026-10-29)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app import scheduler
from app.auth import UserDep, require_member
from app.db import SessionDep
from app.market import prices
from app.market import service as market
from app.pipeline import quality
from app.pipeline.runner import run_source
from app.pipeline.service import SourceService, catalog, edgar_companies, is_admin

router = APIRouter(prefix="/api")


class _Body(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")


# ── 수집 소스 ──────────────────────────────────────────────────────────

@router.get("/sources/catalog")
def sources_catalog(user: UserDep):
    return catalog()


@router.get("/sources/edgar/companies")
def sources_edgar_companies(user: UserDep, q: str = ""):
    return {"companies": edgar_companies(q)}


@router.get("/workspaces/{workspace_id}/sources")
def list_sources(workspace_id: str, user: UserDep, session: SessionDep):
    return SourceService(session).listing(workspace_id, user)


class SourceBody(_Body):
    scope: str = "workspace"
    kind: str
    name: str = ""
    params: Dict[str, Any] = Field(default_factory=dict)
    schedule: Dict[str, Any] = Field(default_factory=dict)
    target: Dict[str, Any] = Field(default_factory=dict)


@router.post("/workspaces/{workspace_id}/sources")
def create_source(workspace_id: str, body: SourceBody, user: UserDep, session: SessionDep):
    return SourceService(session).create(workspace_id, user, body.model_dump())


@router.patch("/sources/{source_id}")
def update_source(source_id: str, body: Dict[str, Any], user: UserDep, session: SessionDep):
    return SourceService(session).update(source_id, user, body)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str, user: UserDep, session: SessionDep):
    SourceService(session).delete(source_id, user)


class RunBody(_Body):
    as_of: Optional[str] = Field(None, alias="asOf")


@router.post("/sources/{source_id}/run")
async def run_source_now(source_id: str, user: UserDep, session: SessionDep, body: Optional[RunBody] = None):
    """[지금 수집]·[날짜 지정 수집] — 뒤에서 돈다(화면은 실행 기록을 다시 묻는다)."""
    SourceService(session).check_run(source_id, user)
    as_of = (body.as_of if body else None) or None
    if as_of and not (len(as_of) == 10 and as_of[4] == "-" and as_of[7] == "-"):
        raise HTTPException(400, "날짜는 YYYY-MM-DD 로 적어 주세요.")
    started = scheduler.spawn(f"source:{source_id}", run_source(source_id, trigger="replay" if as_of else "manual", as_of=as_of))
    if not started:
        raise HTTPException(409, "이 소스를 이미 수집하고 있습니다.")
    return {"started": True}


@router.get("/sources/{source_id}/runs")
def source_runs(source_id: str, user: UserDep, session: SessionDep):
    return {"runs": SourceService(session).runs(source_id, user)}


@router.get("/sources/{source_id}/items")
def source_items(source_id: str, user: UserDep, session: SessionDep):
    return {"items": SourceService(session).items(source_id, user)}


@router.post("/sources/items/{item_id}/retry")
async def retry_item(item_id: str, user: UserDep, session: SessionDep):
    sid = SourceService(session).retry_item(item_id, user)
    scheduler.spawn(f"source:{sid}", run_source(sid, trigger="retry"))
    return {"started": True}


# ── 시장 데이터 ────────────────────────────────────────────────────────

@router.get("/market/board")
def market_board(user: UserDep, asOf: Optional[str] = None):
    return market.board(asOf)


@router.get("/market/series/{series_id}")
def market_series(series_id: str, user: UserDep, range: str = "1Y", asOf: Optional[str] = None):
    try:
        return market.series_view(series_id, range, asOf)
    except KeyError:
        raise HTTPException(404, "모르는 시리즈입니다.")


@router.get("/market/status")
def market_status(user: UserDep):
    return market.status_view()


class PriceLoadBody(BaseModel):
    tickers: List[str]
    days: int = Field(365, ge=5, le=3650)


@router.post("/market/prices/load")
def prices_load(body: PriceLoadBody, user: UserDep):
    """관리자 — 종목 일봉을 Yahoo 에서 받아 쌓는다(사내 공용, 종목 표기 389500.KQ · AAPL)."""
    if not is_admin(user):
        raise HTTPException(403, "관리자만 적재합니다.")
    return {"results": prices.load(body.tickers, body.days)}


@router.get("/market/prices/{ticker}")
def prices_get(ticker: str, user: UserDep, days: int = 365):
    return prices.view(ticker, days)


@router.get("/data/issues")
def data_issues(user: UserDep, session: SessionDep, workspaceId: Optional[str] = None, resolved: int = 0):
    if workspaceId:
        require_member(session, workspaceId, user)
    return {"issues": quality.issues(workspaceId, include_resolved=bool(resolved))}


@router.post("/market/refresh")
async def market_refresh(user: UserDep):
    """관리자 [지금 갱신] — 사내 공용 '시장·거시 시계열' 소스를 지금 돈다."""
    if not is_admin(user):
        raise HTTPException(403, "관리자만 갱신합니다.")
    from sqlmodel import Session, select

    from app.db import DataSource, engine

    with Session(engine) as s:
        src = s.exec(select(DataSource).where(DataSource.scope == "company", DataSource.kind == "series")).first()
    if src is None:
        raise HTTPException(404, "시장 시계열 소스가 없습니다.")
    scheduler.spawn(f"source:{src.id}", run_source(src.id, trigger="manual"))
    return {"started": True, "sourceId": src.id}
