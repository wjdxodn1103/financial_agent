"""위젯 값 — 서버가 계산하고 화면은 그리기만 한다(숫자는 관측값·원장·기록에서 코드로)."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional

from sqlmodel import Session, func, select

from app.db import (DataSource, MarketObservation, ReportSession, SourceItem, Task, User, company_ids, engine, iso, scope_ids, utcnow)

log = logging.getLogger(__name__)


def _ingest_stats(workspace_id: str) -> Dict[str, Any]:
    from app.docs.store import load_meta
    from app.ledger.figures import load_figures

    with Session(engine) as s:
        from app.db import Repo

        ws = Repo(s).workspace(workspace_id) if workspace_id else None
        comp = company_ids()
        mine = [d for d in scope_ids(ws) if d not in set(comp)] if ws else []
        obs = s.exec(select(func.count()).select_from(MarketObservation)).one()
        series = s.exec(select(func.count(func.distinct(MarketObservation.series_id)))).one()
        items = s.exec(select(func.count()).select_from(SourceItem)).one()
        week = s.exec(select(func.count()).select_from(SourceItem).where(SourceItem.fetched_at >= utcnow() - timedelta(days=7), SourceItem.status == "ok")).one()
        sources = s.exec(select(func.count()).select_from(DataSource)).one()
    chunks = figures = 0
    for d in [*comp, *mine]:
        m = load_meta(d) or {}
        chunks += int(m.get("chunkCount") or 0)
        try:
            figures += len(load_figures(d))
        except Exception:  # noqa: BLE001
            pass
    return {"companyDocs": len(comp), "workspaceDocs": len(mine), "chunks": chunks, "figures": figures, "observations": obs, "series": series, "sources": sources, "items": items, "itemsWeek": week}


def _tasks(workspace_id: str, user: User) -> List[Dict[str, Any]]:
    with Session(engine) as s:
        rows = s.exec(select(Task).where(Task.workspace_id == workspace_id, Task.assignee_id == user.id, Task.status != "done").order_by(Task.due).limit(8)).all()
    return [{"id": t.id, "title": t.title, "due": t.due, "status": t.status} for t in rows]


def _routine_docs(workspace_id: str) -> List[Dict[str, Any]]:
    with Session(engine) as s:
        rows = s.exec(select(ReportSession).where(ReportSession.workspace_id == workspace_id).order_by(ReportSession.updated_at.desc()).limit(80)).all()
    out = []
    for r in rows:
        o = (r.doc or {}).get("origin") or {}
        if o.get("routine"):
            out.append({"id": r.id, "title": r.title, "routine": o.get("routineName") or "", "asOf": o.get("asOf"), "status": ((r.doc or {}).get("approval") or {}).get("status"), "updatedAt": iso(r.updated_at)})
        if len(out) >= 6:
            break
    return out


def _optional(mod: str, fn: str, *args: Any) -> Any:
    """뒤 단계 위젯(가정·품질 지표) — 모듈이 아직 없으면 빈 값."""
    import importlib

    try:
        return getattr(importlib.import_module(mod), fn)(*args)
    except ModuleNotFoundError:
        return []
    except Exception:  # noqa: BLE001
        log.exception("widget %s.%s failed", mod, fn)
        return []


def widget_data(w: Dict[str, Any], workspace_id: str, user: User, as_of: Optional[str] = None) -> Dict[str, Any]:
    from app.market import service as market

    t, p = w["type"], w.get("params") or {}
    try:
        if t == "series_cards":
            return {"cards": [market.series_card(i, as_of) for i in p.get("seriesIds") or []]}
        if t == "change_table":
            return {"rows": [market.series_card(i, as_of, spark=0) for i in p.get("seriesIds") or []]}
        if t == "series_chart":
            return {"series": [market.series_view(i, p.get("range") or "1Y", as_of) for i in p.get("seriesIds") or []]}
        if t == "ai_summary":
            from app.market.summary import brief_view

            return brief_view(as_of)
        if t == "source_status":
            from app.pipeline.service import SourceService

            with Session(engine) as s:
                src = SourceService(s).listing(workspace_id, user)["sources"] if workspace_id else []
            st = market.status_view()
            return {"sources": src, "providers": st["providers"], "series": st["series"]}
        if t == "data_issues":
            from app.pipeline.quality import issues

            return {"issues": issues(workspace_id or None)[: int(p.get("limit") or 12)]}
        if t == "ingest_stats":
            return _ingest_stats(workspace_id)
        if t == "tasks":
            return {"tasks": _tasks(workspace_id, user)}
        if t == "routine_docs":
            return {"docs": _routine_docs(workspace_id)}
        if t == "shared_docs":
            from app.sharing import received

            with Session(engine) as s:
                return {"shares": received(s, workspace_id, user, limit=6)}
        if t == "assumptions":
            return {"items": _optional("app.assumptions.service", "widget_items", workspace_id, user)}
        if t == "houseview":
            from app.assistants.houseview import widget as houseview

            return {"houseview": houseview(workspace_id, user)}
        if t == "kpi":
            return {"metrics": _optional("app.quality.kpi", "widget_metrics", p.get("metrics") or [])}
        if t == "note":
            return {"text": p.get("text") or ""}
        if t == "peer_board":
            from app.dashboards.peer import board

            return {"peer": board(workspace_id, p, as_of)}
    except Exception as e:  # noqa: BLE001
        log.exception("widget %s failed", t)
        return {"error": str(e)[:200]}
    return {}
