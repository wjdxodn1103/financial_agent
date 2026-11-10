"""대시보드 API — 전사(시장·데이터 현황)·워크스페이스 맞춤, AI 제안 → 미리보기 → 승인(2026-10-29)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import UserDep
from app.dashboards import service as dash

router = APIRouter(prefix="/api")


class ProposeBody(BaseModel):
    instruction: str


@router.get("/dashboards/{kind}")
def company_dashboard(kind: str, user: UserDep, workspaceId: str = "", preview: int = 0, asOf: Optional[str] = None):
    """전사 대시보드(market·data) — workspaceId 는 수집 소스 목록(워크스페이스 소스 포함)을 보일 때만 쓴다."""
    if kind not in ("market", "data"):
        raise HTTPException(404, "모르는 대시보드입니다.")
    return dash.view(kind, workspaceId, user, asOf, bool(preview))


@router.post("/dashboards/{kind}/propose")
async def propose_company(kind: str, body: ProposeBody, user: UserDep, workspaceId: str = ""):
    if kind not in ("market", "data"):
        raise HTTPException(404, "모르는 대시보드입니다.")
    return await dash.propose(kind, workspaceId, user, body.instruction)


@router.get("/workspaces/{workspace_id}/dashboard")
def workspace_dashboard(workspace_id: str, user: UserDep, preview: int = 0, asOf: Optional[str] = None):
    return dash.view("workspace", workspace_id, user, asOf, bool(preview))


@router.post("/workspaces/{workspace_id}/dashboard/propose")
async def propose_workspace(workspace_id: str, body: ProposeBody, user: UserDep):
    return await dash.propose("workspace", workspace_id, user, body.instruction)


@router.post("/dashboard/drafts/{draft_id}/approve")
def approve_draft(draft_id: str, user: UserDep):
    kind, ws = dash.decide(draft_id, user, approve=True)
    return dash.view(kind, ws, user)


@router.post("/dashboard/drafts/{draft_id}/discard")
def discard_draft(draft_id: str, user: UserDep):
    kind, ws = dash.decide(draft_id, user, approve=False)
    return dash.view(kind, ws, user)


@router.get("/market/home")
def market_home(user: UserDep):
    """시장 홈(금융 데이터 AI 에이전트 기본 화면) — 주요 지수·환율·원자재·금리. 오래됐으면 뒤에서 다시 받는다."""
    from app.market import home

    return home.view()


@router.get("/market/home/chart")
def market_home_chart(user: UserDep, ticker: str, range: str = "1Y"):
    from app.market import home

    try:
        return home.chart(ticker, range)
    except KeyError:
        raise HTTPException(404, "시장 홈에 없는 종목입니다.")


@router.post("/market/home/refresh")
def market_home_refresh(user: UserDep):
    from app.market import home

    return {"started": home.ensure_refresh()}


@router.get("/market/brief")
def market_brief(user: UserDep, date: Optional[str] = None):
    from app.market.summary import brief_view

    return brief_view(date)


@router.post("/market/brief/regenerate")
async def regenerate_brief(user: UserDep):
    from app import config
    from app.market.summary import make_brief

    if user.id not in config.ADMIN_USER_IDS:
        raise HTTPException(403, "관리자만 다시 만듭니다.")
    return await make_brief()
