"""AI 채팅 수명주기 — 대화(만든 사람만)·표(만든 사람, 드라이브에 저장하면 그 폴더를 볼 수 있는 멤버)·양식(사내·워크스페이스·개인).

한 턴 SSE 는 리포트 작성과 같은 틀(services/report_service 의 EventStream·stream_events·잠금)을 쓴다 — 잠금 키는 "rc:<대화 id>".
요청 세션을 스트림에 끌고 가지 않고, 커밋된 JSON 은 deepcopy 후 새 dict 를 대입한다.
"""
from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import ROLE_RANK, display_name, require_member
from app.db import DriveItem, Repo, ResearchChat, ResearchTable, ResearchTemplate, User, engine, iso
from app.drive import folders_of, hidden_items, place, report_scope_ids, visible_folders
from app.ids import id36
from app.llm.base import LlmError
from app.research.chart import ChartError, asset_block, derive_chart
from app.research.templates import SpecError, builtin_views, normalize_spec, spec_from_table
from app.services.report_service import EventStream, release_lock

logger = logging.getLogger(__name__)
_tasks: Dict[str, "asyncio.Task[None]"] = {}


def lock_key(chat_id: str) -> str:
    return f"rc:{chat_id}"


def new_chat_doc() -> Dict[str, Any]:
    return {"history": [], "transcript": [], "dataScope": {"mode": "default"}, "dataExcluded": [], "tableIds": [], "currentTableId": None}


# ── 양식 보이기 ─────────────────────────────────────────────────────────

def template_view(t: ResearchTemplate, names: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return {"id": t.id, "scope": t.scope, "builtin": False, "name": t.name, "spec": t.spec, "ownerId": t.owner_id, "owner": (names or {}).get(t.owner_id, ""), "updatedAt": iso(t.updated_at)}


def visible_templates(session: Session, workspace_id: str, user_id: str) -> List[Dict[str, Any]]:
    """사내 기본(코드) → 사내(DB) → 워크스페이스 → 내 것."""
    names = {u.id: display_name(u) for u in Repo(session).users()}
    rows = session.exec(select(ResearchTemplate).where((ResearchTemplate.scope == "company") | (ResearchTemplate.workspace_id == workspace_id)).order_by(ResearchTemplate.created_at)).all()  # type: ignore[arg-type]
    mine = [t for t in rows if t.scope == "company" or t.scope == "workspace" or (t.scope == "user" and t.owner_id == user_id)]
    order = {"company": 0, "workspace": 1, "user": 2}
    return [*builtin_views(), *[template_view(t, names) for t in sorted(mine, key=lambda t: order.get(t.scope, 3))]]


def match_template(templates: List[Dict[str, Any]], ref: str) -> Optional[Dict[str, Any]]:
    ref = (ref or "").strip()
    if not ref:
        return None
    low = ref.lower().replace(" ", "")
    return next((t for t in templates if t["id"] == ref), None) or next((t for t in templates if t["name"].lower().replace(" ", "") == low), None) or next((t for t in templates if low in t["name"].lower().replace(" ", "")), None)


def template_line(t: Dict[str, Any]) -> str:
    spec = t["spec"]
    scope = {"company": "사내", "workspace": "워크스페이스", "user": "개인"}.get(t["scope"], "")
    rows = "고정 " + ", ".join(r["label"] for r in spec.get("rows") or []) if spec.get("rows") else "매번 정함"
    cols = "매번 정함(질문)" if spec.get("itemsOpen") else ", ".join(it["label"] for it in spec.get("items") or [] if not it.get("hidden"))
    return f"- {t['name']} [{t['id']}] ({scope}) — 행: {(spec.get('subject') or {}).get('label', '')} {rows} / 열: {cols}"


# ── 서비스 ───────────────────────────────────────────────────────────────

class ResearchService:
    def __init__(self, session: Session):
        self.s = session
        self.repo = Repo(session)

    # 대화
    def chat_row(self, chat_id: str, user: User) -> ResearchChat:
        row = self.s.get(ResearchChat, chat_id)
        if row is None or row.created_by != user.id:
            raise HTTPException(404, "대화가 없습니다.")
        require_member(self.s, row.workspace_id, user)
        return row

    def chats(self, workspace_id: str, user: User) -> List[Dict[str, Any]]:
        require_member(self.s, workspace_id, user)
        rows = self.s.exec(select(ResearchChat).where(ResearchChat.workspace_id == workspace_id, ResearchChat.created_by == user.id).order_by(ResearchChat.updated_at.desc())).all()  # type: ignore[attr-defined]
        return [{"id": r.id, "title": r.title or "새 대화", "updatedAt": iso(r.updated_at)} for r in rows]

    def create_chat(self, workspace_id: str, user: User, title: str = "") -> Dict[str, Any]:
        require_member(self.s, workspace_id, user)
        row = self.repo.save(ResearchChat(id=id36("rc", 4), workspace_id=workspace_id, created_by=user.id, title=title.strip()[:80], doc=new_chat_doc()))
        return self.chat_payload(row.id, user)

    def chat_payload(self, chat_id: str, user: User) -> Dict[str, Any]:
        row = self.chat_row(chat_id, user)
        doc = row.doc or {}
        tables = [self.table_view(t, user) for t in self._tables(doc.get("tableIds") or [])]
        return {"chat": {"id": row.id, "title": row.title or "새 대화", "workspaceId": row.workspace_id, "currentTableId": doc.get("currentTableId")}, "messages": doc.get("transcript") or [], "tables": tables}

    def rename_chat(self, chat_id: str, user: User, title: str) -> Dict[str, Any]:
        row = self.chat_row(chat_id, user)
        row.title = (title or "").strip()[:80]
        self.repo.save(row)
        return {"id": row.id, "title": row.title}

    def delete_chat(self, chat_id: str, user: User) -> None:
        # 대화를 지워도 표·차트(에셋)는 남는다 — 드라이브 ▸ 에셋의 '내 에셋'
        self.s.delete(self.chat_row(chat_id, user))
        self.s.commit()

    def persist_chat(self, chat_id: str, doc: Dict[str, Any]) -> None:
        row = self.s.get(ResearchChat, chat_id)
        if row is None:
            return
        keep = {k: v for k, v in doc.items() if k in ("history", "transcript", "decisions", "dataScope", "dataExcluded", "tableIds", "currentTableId")}
        row.doc = copy.deepcopy(keep)
        if not row.title:
            first = next((m.get("text") for m in keep.get("transcript") or [] if m.get("role") == "user" and m.get("text")), "")
            row.title = (first or "")[:40]
        self.repo.save(row)

    def scope_ids(self, row: ResearchChat) -> List[str]:
        return report_scope_ids(self.s, self.repo.workspace(row.workspace_id), row.doc or {}, row.created_by)

    # 표
    def _tables(self, ids: List[str]) -> List[ResearchTable]:
        if not ids:
            return []
        rows = {t.id: t for t in self.s.exec(select(ResearchTable).where(ResearchTable.id.in_(ids))).all()}  # type: ignore[attr-defined]
        return [rows[i] for i in ids if i in rows]

    def table_row(self, table_id: str, user: User, *, write: bool = False) -> ResearchTable:
        row = self.s.get(ResearchTable, table_id)
        if row is None:
            raise HTTPException(404, "표가 없습니다.")
        require_member(self.s, row.workspace_id, user)
        mine = row.created_by == user.id
        if write and not mine:
            raise HTTPException(403, "표를 만든 사람만 바꿀 수 있습니다.")
        if not mine and (not row.saved or row.id in hidden_items(self.s, row.workspace_id, user.id)):
            raise HTTPException(404, "표가 없습니다.")
        return row

    def table_view(self, row: ResearchTable, user: Optional[User] = None) -> Dict[str, Any]:
        data = row.data or {}
        spec = data.get("spec") or {}
        author = self.repo.user(row.created_by)
        placed = self.s.get(DriveItem, (row.workspace_id, row.id))
        chart = data.get("chart") or {}
        source = self.s.get(ResearchTable, chart.get("source") or "") if row.kind == "chart" and chart.get("source") else None
        return {
            "id": row.id,
            "kind": row.kind or "table",
            "title": row.title,
            "status": row.status,
            "saved": row.saved,
            "chatId": row.chat_id,
            "mine": bool(user and user.id == row.created_by),
            "createdBy": display_name(author),
            "updatedAt": iso(row.updated_at),
            "templateId": data.get("templateId"),
            "spec": {"name": spec.get("name"), "subject": spec.get("subject"), "orientation": spec.get("orientation") or "subjects_as_rows", "itemsOpen": bool(spec.get("itemsOpen"))},
            "items": data.get("items") or [],
            "subjects": data.get("subjects") or [],
            "inputs": data.get("inputs") or {},
            "period": data.get("period"),
            "progress": data.get("progress") or {},
            "folderId": placed.folder_id if placed else None,
            "chart": {"type": chart.get("type") or "bar", "source": chart.get("source"), "sourceTitle": source.title if source else None, "dropped": data.get("dropped") or []} if row.kind == "chart" else None,
            "block": asset_block(row),
        }

    def get_table(self, table_id: str, user: User) -> Dict[str, Any]:
        return self.table_view(self.table_row(table_id, user), user)

    def patch_table(self, table_id: str, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        row = self.table_row(table_id, user, write=True)
        if str(body.get("title") or "").strip():
            row.title = str(body["title"]).strip()[:80]
        if body.get("orientation") in ("subjects_as_rows", "items_as_rows"):
            data = copy.deepcopy(row.data or {})
            data["spec"] = {**(data.get("spec") or {}), "orientation": body["orientation"]}
            row.data = data
        if "saved" in body:
            row.saved = bool(body["saved"])
            folder = body.get("folderId") or None
            if folder and folder not in visible_folders(folders_of(self.s, row.workspace_id), user.id):
                raise HTTPException(404, "폴더가 없습니다.")
            if row.saved:
                place(self.s, row.workspace_id, row.id, "table", folder)
            else:
                place(self.s, row.workspace_id, row.id, "table", None)
        self.repo.save(row)
        return self.table_view(row, user)

    def make_chart(self, table_id: str, user: User, body: Dict[str, Any], chat_id: str = "") -> ResearchTable:
        """표 → 차트 에셋. body = {type bar|line|area|pie|combo|band, series?:[열 이름], seriesTypes?·axes?(series 와 같은 순서 — 양식 차트), rows?:[행 이름], horizontal?, title?, form?}.
        내가 볼 수 있는 표면 남의 공유 표도 된다. form = 문서 양식의 차트 양식 정보(research/forms.form_meta — 겉모양)."""
        src = self.table_row(table_id, user)
        if src.kind == "chart":
            raise HTTPException(400, "차트는 표에서 만듭니다.")
        if src.status != "done":
            raise HTTPException(409, "표를 아직 만드는 중입니다.")
        spec = {
            "source": src.id,
            "type": body.get("type"),
            "horizontal": bool(body.get("horizontal")),
            "seriesLabels": [str(x) for x in body.get("series") or [] if str(x).strip()],
            "seriesTypes": [str(x) for x in body.get("seriesTypes") or []],
            "axes": [str(x) for x in body.get("axes") or []],
            "rows": [str(x) for x in body.get("rows") or [] if str(x).strip()] or None,
        }
        try:
            data = derive_chart(src.data or {}, spec)
        except ChartError as e:
            raise HTTPException(400, str(e)) from e
        if isinstance(body.get("form"), dict):
            data["form"] = body["form"]
        title = str(body.get("title") or "").strip()[:80] or src.title
        return self.repo.save(ResearchTable(id=id36("rt", 4), workspace_id=src.workspace_id, chat_id=chat_id or src.chat_id, created_by=user.id, title=title, status="done", kind="chart", data=data))

    def save_to_drive(self, table_id: str, user: User, folder_name: str = "") -> Tuple[Dict[str, Any], str]:
        row = self.table_row(table_id, user, write=True)
        folder_id, where = None, "드라이브 맨 위"
        if folder_name.strip():
            folders = folders_of(self.s, row.workspace_id)
            seen = visible_folders(folders, user.id)
            low = folder_name.strip().lower()
            hit = next((f for f in folders.values() if f.id in seen and f.name.lower() == low), None) or next((f for f in folders.values() if f.id in seen and low in f.name.lower()), None)
            if hit:
                folder_id, where = hit.id, f"'{hit.name}' 폴더"
        return self.patch_table(table_id, user, {"saved": True, "folderId": folder_id}), where

    def delete_table(self, table_id: str, user: User) -> None:
        row = self.table_row(table_id, user, write=True)
        place(self.s, row.workspace_id, row.id, "table", None)
        self.s.delete(row)
        self.s.commit()

    # 양식
    def templates(self, workspace_id: str, user: User) -> List[Dict[str, Any]]:
        require_member(self.s, workspace_id, user)
        return visible_templates(self.s, workspace_id, user.id)

    def create_template(self, workspace_id: str, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        _ws, m = require_member(self.s, workspace_id, user)
        scope = body.get("scope") if body.get("scope") in ("company", "workspace", "user") else "user"
        if scope == "workspace" and ROLE_RANK.get(m.role, 0) < ROLE_RANK["editor"]:
            raise HTTPException(403, "워크스페이스 양식은 편집자 이상만 저장합니다.")
        if scope == "company" and m.role != "owner":
            raise HTTPException(403, "사내 양식은 워크스페이스 소유자만 저장합니다.")
        name = str(body.get("name") or "").strip()[:60]
        try:
            if body.get("fromTableId"):
                table = self.table_row(str(body["fromTableId"]), user)
                spec = spec_from_table(table.data or {}, name or table.title, bool(body.get("keepRows")))
            else:
                spec = normalize_spec({**(body.get("spec") or {}), **({"name": name} if name else {})})
        except SpecError as e:
            raise HTTPException(400, str(e)) from e
        row = self.repo.save(ResearchTemplate(id=id36("tp", 4), scope=scope, workspace_id="" if scope == "company" else workspace_id, owner_id=user.id, name=spec["name"], spec=spec))
        return template_view(row, {user.id: display_name(user)})

    def _template_row(self, template_id: str, user: User) -> ResearchTemplate:
        row = self.s.get(ResearchTemplate, template_id)
        if row is None:
            raise HTTPException(404, "양식이 없습니다.")
        if row.scope == "user" and row.owner_id != user.id:
            raise HTTPException(404, "양식이 없습니다.")
        if row.scope == "workspace":
            _ws, m = require_member(self.s, row.workspace_id, user)
            if row.owner_id != user.id and ROLE_RANK.get(m.role, 0) < ROLE_RANK["editor"]:
                raise HTTPException(403, "워크스페이스 양식은 편집자 이상만 바꿉니다.")
        if row.scope == "company" and row.owner_id != user.id:
            raise HTTPException(403, "사내 양식은 만든 사람만 바꿉니다.")
        return row

    def patch_template(self, template_id: str, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
        row = self._template_row(template_id, user)
        try:
            spec = normalize_spec({**(row.spec or {}), **(body.get("spec") or {}), **({"name": body["name"]} if body.get("name") else {})})
        except SpecError as e:
            raise HTTPException(400, str(e)) from e
        row.spec, row.name = spec, spec["name"]
        self.repo.save(row)
        return template_view(row, {user.id: display_name(user)})

    def delete_template(self, template_id: str, user: User) -> None:
        self.s.delete(self._template_row(template_id, user))
        self.s.commit()


# ── 한 턴 ───────────────────────────────────────────────────────────────

def start_turn(chat_id: str, user_id: str, body: Dict[str, Any]) -> Tuple[EventStream, "asyncio.Task[None]"]:
    es = EventStream()
    task = asyncio.create_task(_produce(es, chat_id, user_id, body), name=f"research-turn-{chat_id}")
    _tasks[chat_id] = task
    return es, task


def cancel_turn(chat_id: str) -> bool:
    task = _tasks.get(chat_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


def _context(chat_id: str, user_id: str) -> Dict[str, Any]:
    from app.ledger.service import choices_of

    with Session(engine) as s:
        svc = ResearchService(s)
        row = s.get(ResearchChat, chat_id)
        if row is None:
            raise HTTPException(404, "대화가 없습니다.")
        doc = copy.deepcopy(row.doc or {})
        templates = visible_templates(s, row.workspace_id, user_id)
        current = s.get(ResearchTable, doc.get("currentTableId") or "") if doc.get("currentTableId") else None
        doc.update(
            {
                "id": row.id,
                "workspaceId": row.workspace_id,
                "ownerId": row.created_by,
                "documentIds": svc.scope_ids(row),
                "ledgerChoices": choices_of(s, row.workspace_id),
                "_templates": templates,
                "_current": {"id": current.id, "title": current.title, "data": current.data} if current is not None else None,
            }
        )
        return doc


async def _produce(es: EventStream, chat_id: str, user_id: str, body: Dict[str, Any]) -> None:
    from app.agent.loop import humanize_error
    from app.llm.client import ReportLlm
    from app.research.loop import run_research_turn

    try:
        if body.get("tableId"):
            await asyncio.to_thread(_set_current, chat_id, user_id, str(body["tableId"]))
        doc = await asyncio.to_thread(_context, chat_id, user_id)
        llm = ReportLlm()

        async def save() -> None:
            snapshot = copy.deepcopy({k: v for k, v in doc.items() if not k.startswith("_")})
            await asyncio.to_thread(_persist, chat_id, snapshot)

        await run_research_turn(doc, str(body.get("text") or ""), llm, es.emit, save)
    except asyncio.CancelledError:
        raise
    except LlmError as e:
        es.emit({"type": "error", "message": humanize_error(e), "code": e.code})
        es.emit({"type": "done"})
    except HTTPException as e:
        es.emit({"type": "error", "message": str(e.detail)})
        es.emit({"type": "done"})
    except Exception as e:  # noqa: BLE001
        logger.exception("research turn failed")
        es.emit({"type": "error", "message": f"처리 중 오류가 났습니다: {e}"})
        es.emit({"type": "done"})
    finally:
        es.close()
        release_lock(lock_key(chat_id))
        if _tasks.get(chat_id) is asyncio.current_task():
            _tasks.pop(chat_id, None)


def _set_current(chat_id: str, user_id: str, table_id: str) -> None:
    """오른쪽 패널에서 보던 표 — "이 표"가 가리키는 것. 내가 볼 수 있는 표면 이 대화의 표 목록에도 넣는다."""
    with Session(engine) as s:
        row = s.get(ResearchChat, chat_id)
        user = s.get(User, user_id)
        if row is None or user is None:
            return
        try:
            ResearchService(s).table_row(table_id, user)
        except HTTPException:
            return
        doc = copy.deepcopy(row.doc or {})
        doc["currentTableId"] = table_id
        if table_id not in (doc.get("tableIds") or []):
            doc["tableIds"] = [*(doc.get("tableIds") or []), table_id]
        row.doc = doc
        Repo(s).save(row)


def _persist(chat_id: str, doc: Dict[str, Any]) -> None:
    with Session(engine) as s:
        ResearchService(s).persist_chat(chat_id, doc)
