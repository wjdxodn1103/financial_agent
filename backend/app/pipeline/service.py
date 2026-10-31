"""수집 소스 관리 — 사내 공용(관리자)·워크스페이스(편집자 이상) 소스의 등록·고치기·지우기·실행·재처리, 목록·실행 기록·항목 보기.
처음 시작할 때 사내 공용 기본 소스 넷을 심는다(시장·거시 시계열 · 공식 보도자료 · 미국 상장사 공시 · 사내 자료 수집 폴더).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app import config
from app.auth import require_member
from app.db import DataSource, SourceItem, SourceRun, User, engine, iso, utcnow
from app.ids import id36
from app.market.catalog import SERIES
from app.pipeline.kinds import COLLECTORS, KIND_KO, default_feeds, edgar_mode, fixture_companies, watch_dir
from app.pipeline.runner import kind_ko, next_run, run_view, source_dict

SCHEDULE_EVERY = ("daily", "weekdays", "hourly", "weekly", "manual")


def is_admin(user: User) -> bool:
    return user.id in config.ADMIN_USER_IDS


def _clean_schedule(sch: Dict[str, Any]) -> Dict[str, Any]:
    every = sch.get("every") if sch.get("every") in SCHEDULE_EVERY else "daily"
    times = [t for t in (sch.get("times") or ["06:30"]) if isinstance(t, str) and len(t) == 5 and t[2] == ":"][:6] or ["06:30"]
    out: Dict[str, Any] = {"every": every, "times": times}
    if every == "weekly":
        out["weekday"] = int(sch.get("weekday") or 0) % 7
    return out


def _clean_params(kind: str, p: Dict[str, Any]) -> Dict[str, Any]:
    if kind == "series":
        ids = [i for i in (p.get("seriesIds") or []) if i in {s.id for s in SERIES}]
        return {"seriesIds": ids} if ids else {}
    if kind == "rss":
        feeds = []
        for f in p.get("feeds") or []:
            url = (f.get("url") if isinstance(f, dict) else str(f)).strip()
            if url.startswith(("http://", "https://")):
                feeds.append({"url": url, "issuer": (f.get("issuer") if isinstance(f, dict) else "") or ""})
        return {"feeds": feeds[:20]} if feeds else {}
    if kind == "edgar":
        cos = [{"cik": int(c["cik"]), "ticker": str(c.get("ticker") or ""), "name": str(c.get("name") or "")} for c in p.get("companies") or [] if str(c.get("cik") or "").isdigit()]
        forms = [f for f in (p.get("forms") or ["10-Q", "10-K", "8-K"]) if f in ("10-Q", "10-K", "8-K", "20-F", "6-K")]
        return {"companies": cos[:30], "forms": forms or ["10-Q", "10-K", "8-K"]}
    if kind == "folder":
        return {}  # 서버 수집 폴더는 소스마다 정해진다(관리자가 서버 경로를 바꾸는 것은 .env·설정 몫)
    raise HTTPException(400, "모르는 소스 종류입니다.")


class SourceService:
    def __init__(self, session: Session):
        self.s = session

    # ── 권한 ──
    def _can_write(self, src: DataSource, user: User) -> bool:
        if src.scope == "company":
            return is_admin(user)
        try:
            _ws, m = require_member(self.s, src.workspace_id, user, "editor")
        except HTTPException:
            return False
        return src.created_by == user.id or m.role == "owner"

    def _row(self, source_id: str, user: User, write: bool = False) -> DataSource:
        src = self.s.get(DataSource, source_id)
        if src is None:
            raise HTTPException(404, "소스를 찾지 못했습니다.")
        if src.scope == "workspace":
            require_member(self.s, src.workspace_id, user)
        if write and not self._can_write(src, user):
            raise HTTPException(403, "사내 공용 소스는 관리자, 워크스페이스 소스는 만든 사람이나 관리자만 바꿉니다.")
        return src

    # ── 보기 ──
    def view(self, src: DataSource, user: User) -> Dict[str, Any]:
        from app.scheduler import local_now

        last = self.s.exec(select(SourceRun).where(SourceRun.source_id == src.id).order_by(SourceRun.started_at.desc())).first()
        items = self.s.exec(select(SourceItem.status).where(SourceItem.source_id == src.id)).all()
        out = {**source_dict(src), "kindKo": kind_ko(src.kind), "enabled": src.enabled, "status": src.status, "lastRunAt": iso(src.last_run_at),
               "nextRunAt": next_run(src, local_now()), "items": len(items), "failedItems": sum(1 for x in items if x == "error"),
               "lastRun": run_view(last) if last else None, "canEdit": self._can_write(src, user)}
        if src.kind == "folder":
            out["watchDir"] = str(watch_dir(source_dict(src)))
        if src.kind == "edgar":
            out["mode"] = edgar_mode()
        return out

    def listing(self, workspace_id: str, user: User) -> Dict[str, Any]:
        require_member(self.s, workspace_id, user)
        rows = self.s.exec(select(DataSource)).all()
        mine = [r for r in rows if r.scope == "company" or r.workspace_id == workspace_id]
        mine.sort(key=lambda r: (r.scope != "company", r.created_at))
        return {"sources": [self.view(r, user) for r in mine], "isAdmin": is_admin(user), "kinds": [{"id": k, "label": v} for k, v in KIND_KO.items()]}

    def runs(self, source_id: str, user: User) -> List[Dict[str, Any]]:
        self._row(source_id, user)
        rows = self.s.exec(select(SourceRun).where(SourceRun.source_id == source_id).order_by(SourceRun.started_at.desc()).limit(20)).all()
        return [run_view(r) for r in rows]

    def items(self, source_id: str, user: User, limit: int = 60) -> List[Dict[str, Any]]:
        self._row(source_id, user)
        rows = self.s.exec(select(SourceItem).where(SourceItem.source_id == source_id).order_by(SourceItem.fetched_at.desc()).limit(limit)).all()
        return [{"id": r.id, "key": r.key, "title": r.title, "url": r.url, "publishedAt": r.published_at, "docId": r.doc_id, "status": r.status, "error": r.error, "retries": r.retries,
                 "fetchedAt": iso(r.fetched_at), "meta": r.meta or {}} for r in rows]

    # ── 바꾸기 ──
    def create(self, workspace_id: str, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        scope = "company" if body.get("scope") == "company" else "workspace"
        if scope == "company" and not is_admin(user):
            raise HTTPException(403, "사내 공용 소스는 관리자만 등록합니다.")
        if scope == "workspace":
            require_member(self.s, workspace_id, user, "editor")
        kind = body.get("kind")
        if kind not in COLLECTORS:
            raise HTTPException(400, "모르는 소스 종류입니다.")
        src = DataSource(id=id36("src", 4), scope=scope, workspace_id="" if scope == "company" else workspace_id, kind=kind, name=(body.get("name") or KIND_KO[kind])[:80],
                         params=_clean_params(kind, body.get("params") or {}), schedule=_clean_schedule(body.get("schedule") or {}),
                         target={"folderId": (body.get("target") or {}).get("folderId")} if scope == "workspace" and (body.get("target") or {}).get("folderId") else {}, created_by=user.id)
        self.s.add(src)
        self.s.commit()
        if kind == "folder":
            watch_dir(source_dict(src)).mkdir(parents=True, exist_ok=True)
        return self.view(src, user)

    def update(self, source_id: str, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        src = self._row(source_id, user, write=True)
        if "name" in body:
            src.name = str(body["name"] or src.name)[:80]
        if "params" in body:
            src.params = _clean_params(src.kind, body["params"] or {})
        if "schedule" in body:
            src.schedule = _clean_schedule(body["schedule"] or {})
        if "enabled" in body:
            src.enabled = bool(body["enabled"])
        src.updated_at = utcnow()
        self.s.add(src)
        self.s.commit()
        return self.view(src, user)

    def delete(self, source_id: str, user: User) -> None:
        """소스만 지운다 — 이미 적재한 문서는 사내 공용·워크스페이스 데이터에 그대로 남는다."""
        src = self._row(source_id, user, write=True)
        self.s.delete(src)
        self.s.commit()

    def check_run(self, source_id: str, user: User) -> DataSource:
        return self._row(source_id, user, write=True)

    def retry_item(self, item_id: str, user: User) -> str:
        it = self.s.get(SourceItem, item_id)
        if it is None:
            raise HTTPException(404, "항목을 찾지 못했습니다.")
        self._row(it.source_id, user, write=True)
        it.retries = 0  # 다음 실행에서 다시(즉시 실행은 라우트가 띄운다)
        self.s.add(it)
        self.s.commit()
        return it.source_id


def catalog() -> Dict[str, Any]:
    from app.market.catalog import view

    return {"series": [view(s) for s in SERIES], "feeds": default_feeds(), "edgarMode": edgar_mode(), "fixtureCompanies": fixture_companies(), "forms": ["10-Q", "10-K", "8-K", "20-F", "6-K"]}


def edgar_companies(q: str) -> List[Dict[str, Any]]:
    """회사 찾기 — SEC_USER_AGENT 가 있으면 SEC 티커 목록(기존 커넥터 캐시), 없으면 고정 파일 회사."""
    q = (q or "").strip().lower()
    if edgar_mode() == "live":
        from app.connectors.edgar import search_companies

        try:
            return search_companies(q)[:20]
        except Exception:  # noqa: BLE001
            return []
    return [c for c in fixture_companies() if not q or q in c["name"].lower() or q in c["ticker"].lower()]


def seed_defaults() -> None:
    """사내 공용 기본 소스 넷 — 처음 한 번(사내 공용 소스가 하나도 없을 때)."""
    with Session(engine) as s:
        if s.exec(select(DataSource).where(DataSource.scope == "company")).first():
            return
        admin = (config.ADMIN_USER_IDS or [""])[0]
        rows = [
            DataSource(id=id36("src", 4), scope="company", kind="series", name="시장·거시 시계열", params={}, schedule={"every": "daily", "times": ["06:30", "18:00"]}, created_by=admin),
            DataSource(id=id36("src", 4), scope="company", kind="rss", name="공식 보도자료·성명", params={}, schedule={"every": "daily", "times": ["07:00", "12:00", "19:00"]}, created_by=admin),
            DataSource(id=id36("src", 4), scope="company", kind="edgar", name="미국 상장사 공시", params={"companies": fixture_companies() if edgar_mode() == "fixture" else [], "forms": ["10-Q", "10-K", "8-K"]},
                       schedule={"every": "weekdays", "times": ["06:00"]}, created_by=admin),
            DataSource(id=id36("src", 4), scope="company", kind="folder", name="사내 자료 수집 폴더", params={}, schedule={"every": "hourly", "times": []}, created_by=admin),
        ]
        for r in rows:
            s.add(r)
        s.commit()
        for r in rows:
            if r.kind == "folder":
                watch_dir(source_dict(r)).mkdir(parents=True, exist_ok=True)
