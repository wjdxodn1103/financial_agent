"""드라이브 — 워크스페이스의 문서(리포트)와 데이터(올린 파일)를 폴더로 정리·공유한다(구글 드라이브처럼).

 - 폴더 공유: access = all(멤버 전체, 기본) | private(만든 사람만) | members(고른 멤버 + 만든 사람). 조상 폴더가 안 보이면 안쪽도 안 보인다.
 - 안 보이는 폴더 속 문서·데이터는 그 사람의 드라이브·검색·작성 범위에서 빠진다. 채팅(모두가 보는 대화) 에이전트는 멤버 전체 공개 데이터만 쓴다.
 - 작업 채팅 데이터 범위(doc.dataScope = {groups, docIds, folderIds}): 묶음(워크스페이스·사내·개인)을 켜고 끄고 + 고른 데이터·폴더.
   개인 = 내가 만든 '나만' 폴더(하위 폴더 포함) 속 데이터, 워크스페이스 = 그 밖의 워크스페이스 데이터, 사내 = 사내 공용. 기본 = 워크스페이스·사내.
   옛 모양 {mode: default}(= 기본 묶음) · {mode: custom}(= 고른 것만)도 그대로 읽는다(새 문서 창).
 - 자리(DriveItem)가 없는 문서·데이터는 드라이브 맨 위에 있다.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth import require_member
from app.db import DriveFolder, DriveItem, Repo, ResearchTable, User, Workspace, company_ids, evidence_ids, iso, utcnow
from app.docs import queue as docs_queue
from app.docs.store import doc_label, document_cards, load_meta
from app.agent.modes import has_doc
from app.ids import id36

ACCESS = ("all", "private", "members")


# ── 보이기·범위 ─────────────────────────────────────────────────────────

def folders_of(session: Session, workspace_id: str) -> Dict[str, DriveFolder]:
    return {f.id: f for f in session.exec(select(DriveFolder).where(DriveFolder.workspace_id == workspace_id))}


def places_of(session: Session, workspace_id: str) -> Dict[str, DriveItem]:
    return {p.item_id: p for p in session.exec(select(DriveItem).where(DriveItem.workspace_id == workspace_id))}


def _open_to(f: DriveFolder, user_id: Optional[str]) -> bool:
    if f.access == "all":
        return True
    if user_id is None:
        return False  # 누구 것도 아닌 자리(채팅) — 전체 공개만
    return f.created_by == user_id or (f.access == "members" and user_id in (f.member_ids or []))


def visible_folders(folders: Dict[str, DriveFolder], user_id: Optional[str]) -> Set[str]:
    """보이는 폴더 — 자기와 모든 조상이 열려 있어야 한다(user_id=None 이면 멤버 전체 공개만)."""
    memo: Dict[str, bool] = {}

    def ok(fid: str, depth: int = 0) -> bool:
        if fid in memo:
            return memo[fid]
        f = folders.get(fid)
        memo[fid] = bool(f) and depth < 50 and _open_to(f, user_id) and (f.parent_id is None or ok(f.parent_id, depth + 1))  # type: ignore[union-attr]
        return memo[fid]

    return {fid for fid in folders if ok(fid)}


def hidden_items(session: Session, workspace_id: str, user_id: Optional[str]) -> Set[str]:
    """이 사람에게 안 보이는 폴더 속 문서·데이터 id(user_id=None 이면 전체 공개가 아닌 폴더 속 전부)."""
    folders = folders_of(session, workspace_id)
    seen = visible_folders(folders, user_id)
    return {p.item_id for p in places_of(session, workspace_id).values() if p.folder_id and p.folder_id not in seen}


def descendants(folders: Dict[str, DriveFolder], roots: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    todo = [r for r in roots if r in folders]
    while todo:
        fid = todo.pop()
        if fid in out:
            continue
        out.add(fid)
        todo += [f.id for f in folders.values() if f.parent_id == fid]
    return out


def items_in(session: Session, workspace_id: str, folder_ids: Iterable[str]) -> Set[str]:
    folders = folders_of(session, workspace_id)
    inside = descendants(folders, folder_ids)
    return {p.item_id for p in places_of(session, workspace_id).values() if p.folder_id in inside}


GROUPS = ("workspace", "company", "personal")
DEFAULT_GROUPS = {"workspace": True, "company": True, "personal": False}


def scope_groups(scope: Dict[str, Any]) -> Dict[str, bool]:
    """dataScope → 켠 묶음. 옛 모양: default = 기본 묶음, custom = 묶음 없이 고른 것만."""
    if isinstance(scope.get("groups"), dict):
        return {g: bool(scope["groups"].get(g)) for g in GROUPS}
    if scope.get("mode") == "custom":
        return {g: False for g in GROUPS}
    return dict(DEFAULT_GROUPS)


def private_ids(session: Session, workspace_id: str, owner_id: Optional[str]) -> Set[str]:
    """개인 데이터 — 이 사람이 만든 '나만'(private) 폴더 안(하위 폴더 포함)의 데이터."""
    if not owner_id:
        return set()
    folders = folders_of(session, workspace_id)
    return items_in(session, workspace_id, [f.id for f in folders.values() if f.access == "private" and f.created_by == owner_id])


def data_groups(session: Session, ws: Workspace, owner_id: Optional[str]) -> Dict[str, str]:
    """이 사람이 쓸 수 있는 데이터(AI 참고 대상, 안 보이는 폴더 제외) → 묶음 이름."""
    hidden = hidden_items(session, ws.id, owner_id)
    company = set(company_ids()) - set(ws.document_ids or [])
    personal = private_ids(session, ws.id, owner_id)
    return {d: ("company" if d in company else "personal" if d in personal else "workspace") for d in evidence_ids(ws) if d not in hidden}


def report_scope_ids(session: Session, ws: Optional[Workspace], doc: Optional[Dict[str, Any]], owner_id: Optional[str], apply_off: bool = True) -> List[str]:
    """작업 채팅(리포트)이 쓰는 데이터 — 워크스페이스에서 AI 가 참고하는 데이터 중 작성자에게 보이는 것 →
    켠 묶음(워크스페이스·사내·개인)의 것 + 고른 데이터·폴더 안의 것 → 이 작업에서 끈 것(doc.dataExcluded)을 뺀다(apply_off)."""
    if ws is None:
        return []
    scope = (doc or {}).get("dataScope") or {}
    groups = scope_groups(scope)
    picked = set(scope.get("docIds") or []) | items_in(session, ws.id, scope.get("folderIds") or [])
    base = [d for d, g in data_groups(session, ws, owner_id).items() if groups[g] or d in picked]
    if not apply_off:
        return base
    off = set((doc or {}).get("dataExcluded") or [])
    return [d for d in base if d not in off]


def place(session: Session, workspace_id: str, item_id: str, kind: str, folder_id: Optional[str]) -> None:
    """문서·데이터의 자리 — folder_id=None 이면 맨 위."""
    row = session.get(DriveItem, (workspace_id, item_id))
    if folder_id is None:
        if row is not None:
            session.delete(row)
            session.commit()
        return
    if row is None:
        row = DriveItem(workspace_id=workspace_id, item_id=item_id, kind=kind, folder_id=folder_id)
    else:
        row.folder_id, row.kind = folder_id, kind
    session.add(row)
    session.commit()


# ── 드라이브 화면 ─────────────────────────────────────────────────────────

class DriveService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = Repo(session)

    def _folder(self, workspace_id: str, user: User, folder_id: Optional[str]) -> Optional[DriveFolder]:
        if not folder_id:
            return None
        folders = folders_of(self.session, workspace_id)
        if folder_id not in folders or folder_id not in visible_folders(folders, user.id):
            raise HTTPException(404, "폴더가 없습니다.")
        return folders[folder_id]

    def listing(self, workspace_id: str, user: User, folder_id: Optional[str] = None) -> Dict[str, Any]:
        """한 폴더(없으면 맨 위)의 하위 폴더·문서·데이터 — 나에게 보이는 것만."""
        from app.services.document_service import DocumentService

        ws, m = require_member(self.session, workspace_id, user)
        current = self._folder(workspace_id, user, folder_id)
        folders = folders_of(self.session, workspace_id)
        seen = visible_folders(folders, user.id)
        places = places_of(self.session, workspace_id)
        here = current.id if current else None
        names = {u.id: f"{u.name} {u.title}".strip() for u in self.repo.users()}

        def where(item_id: str) -> Optional[str]:
            p = places.get(item_id)
            return p.folder_id if p and p.folder_id in folders else None

        path: List[Dict[str, str]] = []
        f = current
        while f is not None and len(path) < 50:
            path.insert(0, {"id": f.id, "name": f.name})
            f = folders.get(f.parent_id) if f.parent_id else None

        def count(fid: str) -> int:
            return sum(1 for p in places.values() if p.folder_id == fid) + sum(1 for x in folders.values() if x.parent_id == fid and x.id in seen)

        sub = [
            {"id": x.id, "name": x.name, "access": x.access, "items": count(x.id), "createdBy": names.get(x.created_by, ""), "updatedAt": iso(x.updated_at)}
            for x in sorted(folders.values(), key=lambda x: x.name)
            if x.parent_id == here and x.id in seen
        ]
        docs = [
            {"id": r.id, "title": r.title or "제목 없는 리포트", "reportType": r.report_type, "written": r.written, "sections": len((r.doc or {}).get("sections") or []), "createdBy": names.get(r.created_by, ""), "updatedAt": iso(r.updated_at)}
            for r in self.repo.reports(workspace_id)
            if where(r.id) == here and has_doc(r.doc or {})  # 문서가 붙은 작업만(대화만 한 AI 작업은 드라이브에 안 보인다)
        ]
        listing = DocumentService(self.session).listing(workspace_id, user)
        data = [c for c in listing["documents"] if not c.get("shared") and where(c["id"]) == here]
        # 자료 속 표·이미 만든 에셋·비슷한 문서에서 만든 같은 모양 표(에셋으로 꺼내기·같은 모양으로 만들기)
        from app.research.doc_tables import asset_hints

        hints = asset_hints(self.session, workspace_id, user, [c["id"] for c in data])
        data = [{**c, "assets": hints.get(c["id"])} for c in data]
        my_tasks = {r.id for r in self.repo.reports(workspace_id) if r.created_by == user.id}
        tables = [
            {
                "id": t.id,
                "kind": t.kind or "table",
                "title": t.title,
                "rows": len((t.data or {}).get("subjects") or []),
                "cols": len([i for i in (t.data or {}).get("items") or [] if not i.get("hidden")]),
                "createdBy": names.get(t.created_by, ""),
                "updatedAt": iso(t.updated_at),
                "chatId": t.chat_id if t.created_by == user.id and t.chat_id in my_tasks else None,
            }
            for t in self.session.exec(select(ResearchTable).where(ResearchTable.workspace_id == workspace_id, ResearchTable.saved == True).order_by(ResearchTable.updated_at.desc()))  # type: ignore[arg-type]  # noqa: E712
            if where(t.id) == here
        ]
        jobs = [docs_queue.job_view(j) for j in self.repo.jobs(workspace_id) if j.status != "done" and (j.folder_id or None) == here]
        return {
            "folder": {"id": current.id, "name": current.name, "access": current.access, "memberIds": current.member_ids or [], "createdBy": current.created_by, "canShare": current.created_by == user.id or m.role == "owner"} if current else None,
            "path": path,
            "folders": sub,
            "docs": docs,
            "data": data,
            "tables": tables,
            "jobs": jobs,
            "members": [{"id": mm.user_id, "name": names.get(mm.user_id, "")} for mm in self.repo.members(workspace_id)],
            "tree": [{"id": x.id, "name": x.name, "parentId": x.parent_id, "access": x.access} for x in sorted(folders.values(), key=lambda x: x.name) if x.id in seen],
        }

    def create_folder(self, workspace_id: str, user: User, name: str, parent_id: Optional[str] = None) -> Dict[str, Any]:
        require_member(self.session, workspace_id, user, "editor")
        parent = self._folder(workspace_id, user, parent_id)
        if not (name or "").strip():
            raise HTTPException(400, "폴더 이름을 넣어 주세요.")
        self.repo.save(DriveFolder(id=id36("f", 4), workspace_id=workspace_id, parent_id=parent.id if parent else None, name=name.strip()[:80], created_by=user.id))
        return self.listing(workspace_id, user, parent.id if parent else None)

    def update_folder(self, workspace_id: str, user: User, folder_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """이름 바꾸기·옮기기(편집자 이상), 공유 범위(만든 사람이나 소유자)."""
        _ws, m = require_member(self.session, workspace_id, user, "editor")
        f = self._folder(workspace_id, user, folder_id)
        assert f is not None
        if str(body.get("name") or "").strip():
            f.name = str(body["name"]).strip()[:80]
        if "parentId" in body:
            target = body.get("parentId") or None
            if target and target in descendants(folders_of(self.session, workspace_id), [f.id]):
                raise HTTPException(400, "폴더를 자기 안으로 옮길 수 없습니다.")
            self._folder(workspace_id, user, target)
            f.parent_id = target
        if "access" in body:
            if f.created_by != user.id and m.role != "owner":
                raise HTTPException(403, "공유 범위는 폴더를 만든 사람이나 소유자만 바꿉니다.")
            if body["access"] not in ACCESS:
                raise HTTPException(400, "모르는 공유 범위입니다.")
            f.access = body["access"]
            members = {mm.user_id for mm in self.repo.members(workspace_id)}
            f.member_ids = [u for u in (body.get("memberIds") or []) if u in members and u != f.created_by] if f.access == "members" else []
        f.updated_at = utcnow()
        self.repo.save(f)
        return self.listing(workspace_id, user, f.parent_id)

    def delete_folder(self, workspace_id: str, user: User, folder_id: str) -> Dict[str, Any]:
        """폴더 지우기 — 안의 문서·데이터·하위 폴더는 지우지 않고 한 칸 위로 옮긴다."""
        require_member(self.session, workspace_id, user, "editor")
        f = self._folder(workspace_id, user, folder_id)
        assert f is not None
        for x in folders_of(self.session, workspace_id).values():
            if x.parent_id == f.id:
                x.parent_id = f.parent_id
                self.session.add(x)
        for p in places_of(self.session, workspace_id).values():
            if p.folder_id == f.id:
                if f.parent_id:
                    p.folder_id = f.parent_id
                    self.session.add(p)
                else:
                    self.session.delete(p)
        self.session.delete(f)
        self.session.commit()
        return self.listing(workspace_id, user, f.parent_id)

    def move(self, workspace_id: str, user: User, items: List[Dict[str, str]], folder_id: Optional[str], current: Optional[str] = None) -> Dict[str, Any]:
        """문서·데이터·저장한 표 옮기기(편집자 이상) — items = [{id, kind: doc|data|table}]."""
        ws, _m = require_member(self.session, workspace_id, user, "editor")
        target = self._folder(workspace_id, user, folder_id)
        reports = {r.id for r in self.repo.reports(workspace_id)}
        own = set(ws.document_ids or [])
        tables = {t.id for t in self.session.exec(select(ResearchTable).where(ResearchTable.workspace_id == workspace_id, ResearchTable.saved == True))}  # noqa: E712
        for it in items:
            kind = it.get("kind")
            if (kind == "doc" and it.get("id") in reports) or (kind == "data" and it.get("id") in own) or (kind == "table" and it.get("id") in tables):
                place(self.session, workspace_id, it["id"], kind, target.id if target else None)
        return self.listing(workspace_id, user, current)

    def search(self, workspace_id: str, user: User, q: str) -> Dict[str, Any]:
        """새 문서의 참고 데이터 고르기 — 이름이 맞는 폴더·데이터(사내 공용 포함). 나에게 보이는 것만."""
        ws, _m = require_member(self.session, workspace_id, user)
        return name_hits(self.session, ws, user, q)


def name_hits(session: Session, ws: Workspace, user: User, q: str, folder_max: int = 20, data_max: int = 40) -> Dict[str, Any]:
    """이름이 맞는 폴더·데이터(사내 공용 포함, 나에게 보이는 것만) — 참고 데이터 고르기·통합 검색·AI 찾기가 같이 쓴다. 낱말이 모두 든 것."""
    words = [w for w in (q or "").lower().split() if w]
    folders = folders_of(session, ws.id)
    seen = visible_folders(folders, user.id)
    hidden = hidden_items(session, ws.id, user.id)
    shared = set(company_ids())

    def hit(text: str) -> bool:
        low = (text or "").lower()
        return all(w in low for w in words)

    def path_of(fid: Optional[str]) -> str:
        parts: List[str] = []
        while fid and fid in folders and len(parts) < 20:
            parts.insert(0, folders[fid].name)
            fid = folders[fid].parent_id
        return " / ".join(parts)

    places = places_of(session, ws.id)
    fs = [{"id": f.id, "name": f.name, "path": path_of(f.parent_id), "items": len(items_in(session, ws.id, [f.id]))} for f in folders.values() if f.id in seen and hit(f.name)]
    cards = document_cards([d for d in evidence_ids(ws) if d not in hidden])
    personal = private_ids(session, ws.id, user.id)
    data = [
        {
            "id": c["id"],
            "label": c["label"],
            "fileType": c["fileType"],
            "fileName": c.get("fileName") or "",
            "shared": c["id"] in shared,
            "personal": c["id"] in personal,
            "path": "사내 공용" if c["id"] in shared else path_of((places.get(c["id"]) or DriveItem(workspace_id="", item_id="")).folder_id),
        }
        for c in cards
        if hit(f"{c['label']} {c.get('fileName') or ''}")
    ]
    return {"folders": fs[:folder_max], "data": data[:data_max]}


def scope_view(session: Session, ws: Optional[Workspace], doc: Dict[str, Any], owner_id: Optional[str]) -> Dict[str, Any]:
    """작업 화면에 보일 데이터 설정 — 켠 묶음·묶음마다 데이터 수·고른 데이터(묶음 표시)·폴더 이름. mode 는 옛 화면(새 문서 창)용."""
    scope = doc.get("dataScope") or {}
    groups = scope_groups(scope)
    of = data_groups(session, ws, owner_id) if ws is not None else {}
    folders = folders_of(session, ws.id) if ws is not None else {}
    return {
        "mode": "custom" if scope.get("mode") == "custom" or "groups" in scope else "default",
        "groups": groups,
        "counts": {g: sum(1 for x in of.values() if x == g) for g in GROUPS},
        "docs": [{"id": d, "label": doc_label(load_meta(d), d), "group": of.get(d)} for d in scope.get("docIds") or [] if load_meta(d)],
        "folders": [{"id": f, "name": folders[f].name} for f in scope.get("folderIds") or [] if f in folders],
    }


def clean_scope(session: Session, ws: Workspace, raw: Any) -> Dict[str, Any]:
    """FE 가 보낸 dataScope 검사 — 워크스페이스에서 쓰는 데이터·있는 폴더만 남긴다. groups 가 오면 묶음 + 고른 것(데이터 설정)."""
    if isinstance(raw, dict) and isinstance(raw.get("groups"), dict):
        allowed = set(evidence_ids(ws))
        folders = folders_of(session, ws.id)
        return {
            "groups": {g: bool(raw["groups"].get(g)) for g in GROUPS},
            "docIds": [d for d in dict.fromkeys(raw.get("docIds") or []) if d in allowed],
            "folderIds": [f for f in dict.fromkeys(raw.get("folderIds") or []) if f in folders],
        }
    if not isinstance(raw, dict) or raw.get("mode") != "custom":
        return {"mode": "default"}
    allowed = set(evidence_ids(ws))
    folders = folders_of(session, ws.id)
    return {
        "mode": "custom",
        "docIds": [d for d in dict.fromkeys(raw.get("docIds") or []) if d in allowed],
        "folderIds": [f for f in dict.fromkeys(raw.get("folderIds") or []) if f in folders],
    }
