"""양식 샘플 API 의 일 — 올리기, 표·차트 카드 등록·건너뛰기, 리포트 양식 한꺼번에 등록.

카드 상태는 doc.imports[id] 와 대화 기록의 그 카드(transcript 의 imports)에 같이 쓴다(새로고침해도 그대로).
진행 중인 턴이 있으면 409(턴이 doc 을 통째로 저장해 이 변경을 덮는다).
"""
from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any, Dict, List

import logging

from fastapi import HTTPException
from sqlmodel import Session

from app.agent.template import REGISTERED
from app.config import TEMPLATE_DIR
from app.db import ReportTemplate, User
from app.ids import id36, now_iso
from app.research.service import ResearchService
from app.services.report_service import ReportService, _busy
from app.templates_import.registry import check_scope

logger = logging.getLogger(__name__)
IMPORT_DIR = TEMPLATE_DIR / "imports"
IMPORT_TTL_DAYS = 14


def clean_imports() -> int:
    """올린 샘플 원본은 읽고 나면 쓰지 않는다(카드에 spec·미리보기가 있다) — 14일 지난 폴더를 지운다. 지운 수."""
    import time

    if not IMPORT_DIR.exists():
        return 0
    cut = time.time() - IMPORT_TTL_DAYS * 86400
    n = 0
    for d in IMPORT_DIR.iterdir():
        if d.is_dir() and d.stat().st_mtime < cut:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def register_card(session: Session, workspace_id: str, user: User, card: Dict[str, Any], scope: str, name: str = "", spec: Any = None) -> None:
    """표·차트 카드 하나 → 표 양식(ResearchTemplate). 차트 카드는 chart 키를 지킨다."""
    body = {"name": (name or card["title"]).strip()[:60], "scope": scope, "spec": {**(spec if isinstance(spec, dict) else card["spec"]), "name": (name or card["title"]).strip()[:60]}}
    if card["kind"] == "chart" and "chart" not in body["spec"]:
        body["spec"]["chart"] = card["spec"].get("chart")
    t = ResearchService(session).create_template(workspace_id, user, body)
    card.update({"state": "registered", "templateId": t["id"], "scope": scope, "spec": t["spec"], "title": t["name"]})


def apply_item(session: Session, workspace_id: str, user: User, imp: Dict[str, Any], n: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """{action: register|skip, name?, scope?, spec?} — imp 를 제자리에서 고친다."""
    card = next((c for c in imp.get("items") or [] if c["n"] == n), None)
    if card is None:
        raise HTTPException(404, "카드가 없습니다.")
    if body.get("action") == "skip":
        card["state"] = "skipped"
    else:
        scope = check_scope(session, workspace_id, user, str(body.get("scope") or "user"))
        register_card(session, workspace_id, user, card, scope, str(body.get("name") or ""), body.get("spec"))
    return card


def apply_format(session: Session, workspace_id: str, user: User, imp: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    """리포트 양식 한꺼번에 — 아직 고르지 않은 표·차트도 같은 범위로 등록하고 섹션마다 자리(slots)를 단다. imp 를 제자리에서 고친다."""
    fmt = imp.get("format")
    if not fmt:
        raise HTTPException(400, "섹션이 없는 샘플이라 리포트 양식으로 등록할 수 없습니다.")
    scope = check_scope(session, workspace_id, user, str(body.get("scope") or "user"))
    cards: List[Dict[str, Any]] = imp.get("items") or []
    for c in cards:
        if c["state"] == "pending":
            register_card(session, workspace_id, user, c, scope)
    by_n = {c["n"]: c for c in cards}
    sections = []
    for s in fmt["sections"]:
        slots = []
        for n in s.get("assets") or []:
            c = by_n.get(n)
            if c and c["state"] == "registered":
                period = (c["spec"].get("subject") or {}).get("kind") == "period"
                slots.append({"templateId": c["templateId"], "kind": c["kind"], "title": c["title"], **({"rows": c.get("sampleRows")} if period and c.get("sampleRows") else {})})
        slots += [{"kind": "figure", "title": f} for f in s.get("figures") or []]
        sections.append({"title": s["title"], "level": s["level"], "guide": s.get("guide") or "", "slots": slots})
    name = str(body.get("name") or fmt["name"]).strip()[:60] or "등록 양식"
    rt = ReportTemplate(id=id36("rp", 4), scope=scope, workspace_id="" if scope == "company" else workspace_id, owner_id=user.id, name=name, source_name=imp["name"], spec={"desc": "", "sections": sections})
    session.add(rt)
    session.commit()
    fmt.update({"state": "registered", "name": name, "scope": scope, "reportType": f"{REGISTERED}{rt.id}"})
    return fmt


class ImportService:
    def __init__(self, session: Session):
        self.s = session
        self.reports = ReportService(session)

    def _open(self, session_id: str, user: User) -> Any:
        row = self.reports.access(session_id, user, write=True)
        if session_id in _busy:
            raise HTTPException(409, "이 작업에서 아직 앞선 요청을 처리하고 있습니다.")
        return row

    def upload(self, session_id: str, user: User, src: str, name: str) -> Dict[str, Any]:
        row = self._open(session_id, user)
        iid = id36("im", 4)
        folder = IMPORT_DIR / iid
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / Path(name).name
        shutil.copyfile(src, dest)
        doc = copy.deepcopy(row.doc or {})
        doc.setdefault("imports", {})[iid] = {"name": Path(name).name, "path": str(dest), "status": "new", "createdAt": now_iso()}
        self.reports.persist(row, doc)
        return {"importId": iid, "name": Path(name).name}

    @staticmethod
    def _imp(doc: Dict[str, Any], iid: str) -> Dict[str, Any]:
        imp = (doc.get("imports") or {}).get(iid)
        if not imp or imp.get("status") != "ready":
            raise HTTPException(404, "양식 샘플이 없습니다.")
        return imp

    @staticmethod
    def _sync(doc: Dict[str, Any], iid: str) -> None:
        """대화 기록의 카드도 같은 상태로."""
        imp = doc["imports"][iid]
        for m in doc.get("transcript") or []:
            box = m.get("imports")
            if isinstance(box, dict) and box.get("id") == iid:
                box["items"] = copy.deepcopy(imp.get("items") or [])
                box["format"] = copy.deepcopy(imp.get("format"))

    def item(self, session_id: str, user: User, iid: str, n: int, body: Dict[str, Any]) -> Dict[str, Any]:
        """{action: register|skip, name?, scope?, spec?} — spec 은 화면에서 고친 양식(없으면 카드의 것)."""
        row = self._open(session_id, user)
        doc = copy.deepcopy(row.doc or {})
        imp = self._imp(doc, iid)
        card = apply_item(self.s, row.workspace_id, user, imp, n, body)
        self._sync(doc, iid)
        self.reports.persist(row, doc)
        return {"item": card}

    def register_format(self, session_id: str, user: User, iid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """리포트 양식 한꺼번에 — 아직 고르지 않은 표·차트도 같은 범위로 등록하고, 섹션마다 자리(slots)를 단다."""
        row = self._open(session_id, user)
        doc = copy.deepcopy(row.doc or {})
        imp = self._imp(doc, iid)
        fmt = apply_format(self.s, row.workspace_id, user, imp, body)
        self._sync(doc, iid)
        self.reports.persist(row, doc)
        return {"format": fmt, "items": imp.get("items") or []}


_running: Dict[str, "asyncio.Task[None]"] = {}


class FileImport:
    """문서 양식 메뉴의 '새 양식' — 샘플(PDF·DOCX)을 올리면 뒤에서 LLM 이 양식을 분석하고(analyze.py — PDF 는 쪽 그림을 VL 로),
    끝나면 바로 '등록 전' 양식(registry.create_from_proposal draft)을 만든다(formatId). 화면은 상태를 다시 묻다가 그 양식을 양식 화면으로 열고,
    사용자가 보며 고치고(직접·말로) 등록 버튼으로 등록한다. 창을 닫아도 분석은 이어지고 목록에 '등록 전'으로 남는다. 등록하면 샘플은 양식 폴더로 옮겨 '예시 문서'가 된다.
    상태는 올린 파일 옆 state.json(14일 뒤 스케줄러가 폴더째 지운다). 서버가 다시 시작되면 분석 중이던 것은 오류로 보인다."""

    def __init__(self, session: Session):
        self.s = session

    @staticmethod
    def _state(iid: str) -> Path:
        return IMPORT_DIR / iid / "state.json"

    def load(self, workspace_id: str, user: User, iid: str) -> Dict[str, Any]:
        import json

        p = self._state(iid)
        if not p.is_file():
            raise HTTPException(404, "양식 샘플이 없습니다.")
        imp = json.loads(p.read_text(encoding="utf-8"))
        if imp.get("workspaceId") != workspace_id or imp.get("ownerId") != user.id:
            raise HTTPException(404, "양식 샘플이 없습니다.")
        return imp

    @classmethod
    def save(cls, iid: str, imp: Dict[str, Any]) -> None:
        from app.docs.store import write_json_atomic

        write_json_atomic(cls._state(iid), imp)

    @staticmethod
    def public(imp: Dict[str, Any]) -> Dict[str, Any]:
        return {k: imp.get(k) for k in ("id", "name", "status", "progress", "formatId", "error")}

    async def start(self, workspace_id: str, user: User, src: str, name: str) -> Dict[str, Any]:
        import asyncio

        from app.auth import require_member

        require_member(self.s, workspace_id, user, "editor")
        iid = id36("im", 4)
        folder = IMPORT_DIR / iid
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / Path(name).name
        shutil.copyfile(src, dest)
        imp = {"id": iid, "name": dest.name, "path": str(dest), "status": "analyzing", "progress": {"done": 0, "total": 0}, "workspaceId": workspace_id, "ownerId": user.id, "createdAt": now_iso()}
        self.save(iid, imp)
        _running[iid] = asyncio.get_running_loop().create_task(self._analyze(iid), name=f"format-import-{iid}")
        _running[iid].add_done_callback(lambda _t: _running.pop(iid, None))
        return self.public(imp)

    @classmethod
    async def _analyze(cls, iid: str) -> None:
        import asyncio
        import json

        from app.llm.client import ReportLlm
        from app.templates_import.analyze import analyze_sample

        imp = json.loads(cls._state(iid).read_text(encoding="utf-8"))

        async def progress(done: int, total: int) -> None:
            imp["progress"] = {"done": done, "total": total}
            cls.save(iid, imp)

        try:
            proposal = await analyze_sample(imp["path"], imp["name"], ReportLlm(), progress)
            fmt = await asyncio.to_thread(cls._draft, imp, proposal)
            imp.update({"status": "ready", "proposal": proposal, "formatId": fmt["id"]})
        except Exception as e:  # noqa: BLE001 — 화면에 한 줄로
            logger.exception("format analysis failed: %s", imp.get("name"))
            imp.update({"status": "error", "error": str(e)[:200] if isinstance(e, ValueError) else "샘플을 분석하지 못했습니다. 잠시 뒤 다시 올려 주세요."})
        cls.save(iid, imp)

    @staticmethod
    def _draft(imp: Dict[str, Any], proposal: Dict[str, Any]) -> Dict[str, Any]:
        """분석 제안 → 등록 전 양식(올린 사람 것, 범위는 등록할 때 정한다)."""
        from app.db import engine
        from app.templates_import.registry import create_from_proposal

        with Session(engine) as s:
            user = s.get(User, imp["ownerId"])
            body = {k: proposal.get(k) for k in ("name", "desc", "style", "sections", "blueprint")}
            return create_from_proposal(s, imp["workspaceId"], user, {**body, "scope": "workspace"}, Path(imp["path"]), imp["name"], proposal.get("assets") or [], draft=True)

    def get(self, workspace_id: str, user: User, iid: str) -> Dict[str, Any]:
        imp = self.load(workspace_id, user, iid)
        if imp.get("status") == "analyzing" and iid not in _running:
            imp.update({"status": "error", "error": "서버가 다시 시작되어 분석이 멈췄습니다. 다시 올려 주세요."})
            self.save(iid, imp)
        return self.public(imp)


__all__ = ["IMPORT_DIR", "FileImport", "ImportService", "apply_format", "apply_item", "clean_imports", "register_card"]
