"""대시보드 — 전사(시장·데이터 현황)와 워크스페이스 맞춤. 고치기 = AI 에게 말하기 → 제안(draft) → 미리보기 → 제안한 사람이 승인·버리기.
전사 대시보드는 관리자, 워크스페이스는 편집자 이상이 제안·승인한다. 다른 사람에게는 지금 구성과 '제안 대기'만 보인다.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select

from app import config
from app.auth import require_member
from app.dashboards.resolve import widget_data
from app.dashboards.templates import label_of
from app.dashboards.widgets import ALLOWED, catalog_text, clean, default
from app.db import DashboardSpec, User, engine, iso
from app.ids import id36
from app.llm.base import ChatParams

log = logging.getLogger(__name__)
KINDS = ("market", "data", "workspace")

PROMPT = """아래는 대시보드 구성(JSON)이다. 사용자 요청대로 고친 구성을 JSON 하나로만 답한다(설명·코드 블록 없이).
{"summary": "무엇을 고쳤는지 한 문장", "spec": {"widgets": [{"id": "있던 위젯이면 그 id", "type": "", "title": "", "params": {}, "size": "s|m|l|full"}]}}
규칙:
- 요청과 상관없는 위젯은 그대로 둔다(순서·id·params 그대로).
- 아래 목록에 있는 위젯 종류·시리즈 id 만 쓴다. 없는 것을 요청하면 spec 은 그대로 두고 summary 에 이유를 적는다.
- 위젯은 12개 이하.
- 맨 아래 '양식'에 맞는 요청(예: 회사 두 곳을 비교해 달라)이면 spec 을 쓰지 말고 그 양식의 답 꼴로만 답한다.
- type 이 peer_board 인 위젯은 양식이 만든 것이다 — params 의 companies·outlook 은 그대로 두고, 지표를 빼거나 더해 달라는 요청만 metrics 로 고친다."""


def _scope(kind: str) -> str:
    return "workspace" if kind == "workspace" else "company"


def _check(kind: str, workspace_id: str, user: User, write: bool) -> None:
    if kind not in KINDS:
        raise HTTPException(404, "모르는 대시보드입니다.")
    if kind == "workspace":
        with Session(engine) as s:
            require_member(s, workspace_id, user, "editor" if write else "viewer")
    elif write and user.id not in config.ADMIN_USER_IDS:
        raise HTTPException(403, "전사 대시보드는 관리자만 고칩니다.")


def _active(s: Session, kind: str, workspace_id: str, user_id: str = "") -> DashboardSpec:
    ws = workspace_id if kind == "workspace" else ""
    row = s.exec(select(DashboardSpec).where(DashboardSpec.kind == kind, DashboardSpec.workspace_id == ws, DashboardSpec.status == "active")).first()
    if row is None:
        row = DashboardSpec(id=id36("db", 4), scope=_scope(kind), workspace_id=ws, kind=kind, status="active", spec=default(kind), created_by=user_id)
        s.add(row)
        s.commit()
    return row


def _draft(s: Session, kind: str, workspace_id: str) -> Optional[DashboardSpec]:
    ws = workspace_id if kind == "workspace" else ""
    return s.exec(select(DashboardSpec).where(DashboardSpec.kind == kind, DashboardSpec.workspace_id == ws, DashboardSpec.status == "draft").order_by(DashboardSpec.created_at.desc())).first()


def _render(spec: Dict[str, Any], workspace_id: str, user: User, as_of: Optional[str]) -> list:
    return [{**w, "data": widget_data(w, workspace_id, user, as_of)} for w in spec.get("widgets") or []]


def view(kind: str, workspace_id: str, user: User, as_of: Optional[str] = None, preview: bool = False) -> Dict[str, Any]:
    _check(kind, workspace_id, user, write=False)
    with Session(engine) as s:  # 세션 안에서 값을 꺼내 둔다(커밋 뒤 만료된 행을 밖에서 읽지 않게)
        act = _active(s, kind, workspace_id, user.id)
        act_id, act_spec, act_prompt = act.id, dict(act.spec or {}), act.prompt or ""
        dr = _draft(s, kind, workspace_id)
        draft = None
        if dr:
            u = s.get(User, dr.created_by)
            draft = {"id": dr.id, "summary": dr.summary, "prompt": dr.prompt, "by": f"{u.name} {u.title}".strip() if u else "", "mine": dr.created_by == user.id, "at": iso(dr.created_at), "spec": dict(dr.spec or {})}
    mine = bool(draft and draft["mine"])
    show = draft["spec"] if (preview and mine and draft) else act_spec
    if draft:
        draft.pop("spec")
    return {
        "kind": kind,
        "id": act_id,
        "widgets": _render(show, workspace_id, user, as_of),
        "preview": bool(preview and mine),
        "template": label_of(show),
        "prompt": draft["prompt"] if (preview and mine and draft) else act_prompt,  # 지금 보이는 구성을 만든 요청(대화창에 남긴다)
        "draft": draft,
        "canEdit": _can_edit(kind, workspace_id, user),
        "asOf": as_of,
    }


def _can_edit(kind: str, workspace_id: str, user: User) -> bool:
    try:
        _check(kind, workspace_id, user, write=True)
        return True
    except HTTPException:
        return False


def _json(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M))
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


async def propose(kind: str, workspace_id: str, user: User, instruction: str, llm: Any = None) -> Dict[str, Any]:
    from app.llm.client import ReportLlm

    _check(kind, workspace_id, user, write=True)
    text = (instruction or "").strip()[:800]
    if not text:
        raise HTTPException(400, "어떻게 바꿀지 적어 주세요.")
    with Session(engine) as s:
        act = _active(s, kind, workspace_id, user.id)
        cur = dict(act.spec or {})
        act_id = act.id
    lean = {"widgets": [{k: w.get(k) for k in ("id", "type", "title", "params", "size")} for w in cur.get("widgets") or []]}
    content = f"{PROMPT}\n\n{catalog_text(kind)}\n\n## 지금 구성\n{json.dumps(lean, ensure_ascii=False)}\n\n## 사용자 요청\n{text}"
    llm = llm or ReportLlm()
    got = None
    for tokens in (5000, 8000):
        try:
            res = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": content}], temperature=0.1, max_tokens=tokens, reasoning_effort="low", timeout_s=150))
        except Exception:  # noqa: BLE001
            log.exception("dashboard propose failed")
            continue
        got = _json(getattr(res, "content", "") or "")
        if got and (isinstance(got.get("spec"), dict) or got.get("template")):
            break
    if not got or not (isinstance(got.get("spec"), dict) or got.get("template")):
        raise HTTPException(502, "AI 가 구성을 만들지 못했습니다. 다시 말해 주세요.")
    from app.dashboards import templates

    built = await templates.build(got, kind, workspace_id, user, llm) if got.get("template") else None  # 양식이면 구성은 코드가 만든다(자료도 이때 받는다)
    if built is None and not isinstance(got.get("spec"), dict):
        raise HTTPException(400, "이 화면에서는 쓸 수 없는 양식입니다.")
    spec = clean(built or got["spec"], kind)
    if not spec["widgets"]:
        raise HTTPException(400, "쓸 수 있는 위젯이 남지 않았습니다. 다시 말해 주세요.")
    with Session(engine) as s:
        old = _draft(s, kind, workspace_id)
        if old is not None:
            old.status = "archived"  # 앞선 제안은 버린다(제안은 하나)
            s.add(old)
        dr = DashboardSpec(id=id36("db", 4), scope=_scope(kind), workspace_id=workspace_id if kind == "workspace" else "", kind=kind, status="draft", spec=spec, prompt=text, summary=str(got.get("summary") or "")[:300], base_id=act_id, created_by=user.id)
        dr_id = dr.id
        s.add(dr)
        s.commit()
    if kind == "workspace":
        from app.notify import member_ids, notify

        notify(member_ids(workspace_id), workspace_id=workspace_id, kind="dashboard", title="대시보드 변경 제안", body=str(got.get("summary") or "")[:200], link={"w": workspace_id, "v": "dashboard"}, exclude=[user.id], dedupe_key=f"dash-draft:{dr_id}")
    return view(kind, workspace_id, user, preview=True)


def decide(draft_id: str, user: User, approve: bool) -> Tuple[str, str]:
    with Session(engine) as s:
        dr = s.get(DashboardSpec, draft_id)
        if dr is None or dr.status != "draft":
            raise HTTPException(404, "제안을 찾지 못했습니다.")
        _check(dr.kind, dr.workspace_id, user, write=True)
        if dr.created_by != user.id:
            raise HTTPException(403, "제안한 사람이 승인하거나 버립니다.")
        if approve:
            act = _active(s, dr.kind, dr.workspace_id, user.id)
            act.status = "archived"
            s.add(act)
            dr.status = "active"
        else:
            dr.status = "archived"
        s.add(dr)
        s.commit()
        return dr.kind, dr.workspace_id


def allowed_kinds() -> Dict[str, Any]:
    return {k: sorted(v) for k, v in ALLOWED.items()}
