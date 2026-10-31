"""경제 일정 API(2026-10-29) — 일정 목록·예상치 입력·알림 등록, 관리자: 일정 다시 받기·실제치 넣기."""
from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import UserDep
from app.calendar import service as cal
from app.calendar.catalog import CATEGORY_KO, COUNTRY_KO, INDICATORS
from app.db import SessionDep
from app.pipeline.service import is_admin

router = APIRouter(prefix="/api")


@router.get("/workspaces/{workspace_id}/calendar")
def calendar(workspace_id: str, user: UserDep, session: SessionDep, start: Optional[str] = None, end: Optional[str] = None, country: str = "", category: str = "", minImportance: int = 1):
    s = start or (date.today() - timedelta(days=7)).isoformat()
    e = end or (date.today() + timedelta(days=60)).isoformat()
    return cal.listing(session, workspace_id, user, s, e, country, category, minImportance)


@router.get("/calendar/meta")
def calendar_meta(user: UserDep):
    return {"countries": COUNTRY_KO, "categories": CATEGORY_KO, "indicators": [{"id": i.id, "name": i.name, "short": i.short, "country": i.country, "importance": i.importance} for i in INDICATORS],
            "keys": cal.key_status(), "isAdmin": is_admin(user)}


class ForecastBody(BaseModel):
    forecast: Optional[float] = None


@router.patch("/workspaces/{workspace_id}/calendar/events/{event_id}")
def set_forecast(workspace_id: str, event_id: str, body: ForecastBody, user: UserDep, session: SessionDep):
    return cal.set_forecast(session, workspace_id, event_id, user, body.forecast)


class AlertBody(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    event_ids: List[str] = Field(default_factory=list, alias="eventIds")
    indicator_ids: List[str] = Field(default_factory=list, alias="indicatorIds")
    repeat: bool = False
    all: bool = False
    workspace: bool = False
    webhook: bool = False
    source: Optional[dict] = None


@router.get("/workspaces/{workspace_id}/calendar/alerts")
def list_alerts(workspace_id: str, user: UserDep, session: SessionDep):
    return {"alerts": cal.list_alerts(session, workspace_id, user)}


@router.post("/workspaces/{workspace_id}/calendar/alerts")
def create_alerts(workspace_id: str, body: AlertBody, user: UserDep, session: SessionDep):
    if not body.event_ids and not body.indicator_ids:
        raise HTTPException(400, "알림을 걸 일정을 골라 주세요.")
    made = cal.create_alerts(session, workspace_id, user, event_ids=body.event_ids, indicator_ids=body.indicator_ids, repeat=body.repeat, to_all=body.all,
                             workspace_msg=body.workspace, webhook=body.webhook, source=body.source)
    return {"alerts": made}


@router.delete("/calendar/alerts/{alert_id}")
def delete_alert(alert_id: str, user: UserDep, session: SessionDep):
    cal.delete_alert(session, alert_id, user)
    return {"ok": True}


def _admin(user) -> None:
    if not is_admin(user):
        raise HTTPException(403, "관리자만 할 수 있습니다.")


@router.post("/admin/calendar/sync")
async def admin_sync(user: UserDep):
    _admin(user)
    return await asyncio.to_thread(cal.sync)


class ActualBody(BaseModel):
    value: float
    text: str = ""


@router.post("/admin/calendar/events/{event_id}/actual")
def admin_actual(event_id: str, body: ActualBody, user: UserDep):
    """실제치 직접 넣기(감지 소스가 없는 지표·정정) — 넣으면 걸린 알림이 바로 간다."""
    _admin(user)
    out = cal.record_actual(event_id, body.value, text=body.text, via="manual", url="")
    if out is None:
        raise HTTPException(404, "일정을 찾지 못했습니다.")
    return out
