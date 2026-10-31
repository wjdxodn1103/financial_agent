"""등록한 문서 양식(ReportTemplate) — 누가 보나(scope), 새 문서 화면에 보일 모양, 지우기, 양식 메뉴(목록·사용 통계·예시 문서·고치기).
샘플로 만든 양식은 spec.assets 에 표·차트 양식(forms.py — 형식만, 원본 위치 포함)을 둔다. 섹션과는 묶지 않는다(양식 전체의 모음).
샘플 분석이 끝나면 '등록 전'(spec.draft) 양식이 된다 — 만든 사람의 양식 목록에만 보이고(고치기·말로 고치기), 등록(register_draft)해야
다른 사람·새 문서·양식 고르기에 보인다.
범위는 워크스페이스·사내 둘(예전 '나만'(user) 양식은 워크스페이스 묶음에 보인다). 고치기·지우기 = 만든 사람이나 관리자(워크스페이스 소유자)만.

보이는 것: 사내(company) + 이 워크스페이스(workspace) + 내 것(user, 이 워크스페이스). 표 양식(ResearchTemplate)과 같은 규칙.
"""
from __future__ import annotations

import copy
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app.agent.template import REGISTERED, REPORT_TYPES, forget_registered, registered_to_type
from app.auth import ROLE_RANK, display_name, require_member
from app.config import BACKEND_DIR, TEMPLATE_DIR
from app.db import Membership, Repo, ReportSession, ReportTemplate, User, iso, utcnow
from app.formats.registry import label
from app.ids import id36
from app.templates_import.blueprint_edit import apply_outline, preview_blocks
from app.templates_import.forms import clean_assets


def _draft(row: ReportTemplate) -> bool:
    return bool((row.spec or {}).get("draft"))


def _visible(row: ReportTemplate, workspace_id: str, user_id: str) -> bool:
    if _draft(row) and row.owner_id != user_id:  # 등록 전 — 만든 사람만
        return False
    return row.scope == "company" or (row.workspace_id == workspace_id and (row.scope == "workspace" or row.owner_id == user_id))


def can_use(session: Session, type_id: str, workspace_id: str, user_id: str) -> bool:
    """문서를 이 양식으로 쓸 수 있나 — 등록 전 양식은 안 된다."""
    row = session.get(ReportTemplate, type_id[len(REGISTERED):]) if type_id.startswith(REGISTERED) else None
    return row is not None and not _draft(row) and _visible(row, workspace_id, user_id)


def report_type_views(session: Session, workspace_id: str, user: User) -> List[Dict[str, Any]]:
    """새 문서·양식 고르기 화면 — meta 의 reportTypes 와 같은 모양(kind=registered) + 범위·만든 사람."""
    require_member(session, workspace_id, user)
    names = {u.id: display_name(u) for u in Repo(session).users()}
    rows = session.exec(select(ReportTemplate).where((ReportTemplate.scope == "company") | (ReportTemplate.workspace_id == workspace_id)).order_by(ReportTemplate.created_at)).all()  # type: ignore[arg-type]
    out = []
    for r in rows:
        if _draft(r) or not _visible(r, workspace_id, user.id):
            continue
        t = registered_to_type(r)
        slots = [x for it in t["items"] for x in it.get("slots") or []] + list((r.spec or {}).get("assets") or [])
        out.append(
            {
                "id": f"{REGISTERED}{r.id}",
                "title": t["title"],
                "desc": t["desc"] or (f"샘플 '{r.source_name}' 에서 등록" if r.source_name else ""),
                "kind": "registered",
                "tags": [],
                "sample": r.source_name,
                "dataNote": "",
                "items": [{"id": it["id"], "title": it["title"], "phase": "body", "level": "recommended", "desc": it["desc"], "inputs": [], "blocks": [], "slots": it.get("slots") or []} for it in t["items"]],
                "order": t["order"],
                "tables": sum(1 for x in slots if x.get("kind") == "table"),
                "charts": sum(1 for x in slots if x.get("kind") == "chart"),
                "scope": r.scope,
                "owner": names.get(r.owner_id, ""),
                "ownerId": r.owner_id,
                "updatedAt": iso(r.updated_at),
            }
        )
    return out


def check_scope(session: Session, workspace_id: str, user: User, scope: str) -> str:
    """표 양식과 같은 권한 — 워크스페이스는 편집자 이상, 사내는 소유자. 문서 양식은 워크스페이스·사내 둘(그 밖은 워크스페이스)."""
    _ws, m = require_member(session, workspace_id, user)
    scope = scope if scope in ("company", "workspace", "user") else "workspace"
    if scope == "workspace" and ROLE_RANK.get(m.role, 0) < ROLE_RANK["editor"]:
        raise HTTPException(403, "워크스페이스 양식은 편집자 이상만 저장합니다.")
    if scope == "company" and m.role != "owner":
        raise HTTPException(403, "사내 양식은 워크스페이스 소유자만 저장합니다.")
    return scope


def _can_change(row: ReportTemplate, user: User, m: Optional[Membership]) -> bool:
    """고치기·지우기 — 만든 사람이나 관리자(워크스페이스 소유자)만. 다른 멤버는 보기·쓰기만."""
    return row.owner_id == user.id or (m is not None and m.role == "owner")


def delete_report_template(session: Session, type_id: str, user: User) -> None:
    row = session.get(ReportTemplate, type_id[len(REGISTERED):] if type_id.startswith(REGISTERED) else type_id)
    if row is None or (_draft(row) and row.owner_id != user.id):  # 등록 전 양식은 만든 사람에게만 있다
        raise HTTPException(404, "양식이 없습니다.")
    if row.scope == "workspace":
        _ws, m = require_member(session, row.workspace_id, user)
        if not _can_change(row, user, m):
            raise HTTPException(403, "양식은 만든 사람이나 관리자만 지웁니다.")
    elif row.owner_id != user.id:
        raise HTTPException(403 if row.scope == "company" else 404, "양식을 지울 수 없습니다.")
    forget_registered(f"{REGISTERED}{row.id}")
    shutil.rmtree(TEMPLATE_DIR / "formats" / row.id, ignore_errors=True)  # 예시 문서
    session.delete(row)
    session.commit()


# ── 양식 메뉴 — 목록·만들기(빈 것·복사)·고치기 ─────────────────────────────

SECTION_MAX = 40
SLOT_MAX = 8
_SID = re.compile(r"s\d{1,4}")


# 기본 양식의 예시 문서(있는 것만) — 고정 양식은 그 양식을 만든 공개 보고서
BUILTIN_SAMPLES = {"nbim_half_year": BACKEND_DIR.parent / "demo" / "public_samples" / "03_nbim_gpfg_half_year_2025_investments.pdf"}


def sample_path(session: Session, workspace_id: str, user: User, type_id: str) -> Path:
    """예시 문서 파일 — 등록 양식은 등록할 때 올린 샘플(TEMPLATE_DIR/formats/<id>/), 기본 양식은 BUILTIN_SAMPLES."""
    require_member(session, workspace_id, user)
    if type_id.startswith(REGISTERED):
        row = _format_row(session, type_id)
        rel = (row.spec or {}).get("sampleFile")
        if not _visible(row, workspace_id, user.id) or not rel:
            raise HTTPException(404, "예시 문서가 없습니다.")
        p = TEMPLATE_DIR / rel
    else:
        p = BUILTIN_SAMPLES.get(type_id) or Path("")
    if not p.is_file():
        raise HTTPException(404, "예시 문서가 없습니다.")
    return p


def _usage(session: Session, workspace_id: str, user_id: str) -> Dict[str, Any]:
    """양식별 쓴 문서 수(이 워크스페이스·전체)와 내가 마지막으로 쓴 때."""
    here: Counter = Counter()
    every: Counter = Counter()
    last: Dict[str, Any] = {}
    for t, w, by, at in session.exec(select(ReportSession.report_type, ReportSession.workspace_id, ReportSession.created_by, ReportSession.updated_at)):  # type: ignore[call-overload]
        if not t or t == "free":
            continue
        every[t] += 1
        if w == workspace_id:
            here[t] += 1
            if by == user_id and (t not in last or at > last[t]):
                last[t] = at
    return {"here": here, "every": every, "last": last}


def _builtin_view(tid: str, t: Dict[str, Any], use: Dict[str, Any]) -> Dict[str, Any]:
    """코드에 든 기본 양식(사내 공통) — 고칠 수 없다. 고정 양식의 표·그림 블록은 이름만 보인다."""
    blocks = t.get("blocks") or {}
    sections = [
        {"id": it["id"], "title": it["title"], "level": 1, "guide": it.get("desc") or "", "slots": [{"kind": blocks[b]["kind"], "title": label(blocks[b]), "builtin": True} for b in it.get("blocks") or [] if b in blocks]}
        for it in t["items"]
    ]
    return {
        "id": tid, "title": t["title"], "desc": t["desc"], "kind": t.get("kind", "type"), "scope": "builtin", "owner": "", "ownerId": "", "editable": False,
        "sample": t.get("sample") or "", "hasSample": BUILTIN_SAMPLES.get(tid, Path("")).is_file(), "style": t.get("style") or "", "sections": sections, "assets": [], "updatedAt": "",
        "uses": use["every"].get(tid, 0), "lastUsed": iso(use["last"][tid]) if tid in use["last"] else None,
    }


def _sections_of(row: ReportTemplate) -> List[Dict[str, Any]]:
    secs = (row.spec or {}).get("sections") or []
    return [{"id": s.get("id") or f"s{i + 1}", "title": s.get("title") or "", "level": s.get("level") or 1, "guide": s.get("guide") or "", "slots": s.get("slots") or []} for i, s in enumerate(secs)]


def _row_view(row: ReportTemplate, user: User, m: Optional[Membership], names: Dict[str, str], use: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    tid = f"{REGISTERED}{row.id}"
    use = use or {"here": Counter(), "every": Counter(), "last": {}}
    return {
        "id": tid,
        "title": row.name,
        "desc": (row.spec or {}).get("desc") or "",
        "kind": "registered",
        "scope": row.scope,
        "owner": names.get(row.owner_id, ""),
        "ownerId": row.owner_id,
        "editable": _can_change(row, user, m),
        "draft": _draft(row),
        "sample": row.source_name,
        "hasSample": bool((row.spec or {}).get("sampleFile")) and (TEMPLATE_DIR / str((row.spec or {}).get("sampleFile"))).is_file(),
        "style": (row.spec or {}).get("style") or "",
        "sections": _sections_of(row),
        "assets": (row.spec or {}).get("assets") or [],
        "blueprint": (row.spec or {}).get("blueprint"),
        # 양식 2.0 — 표·차트 양식마다 샘플 값으로 채운 미리보기 블록(문서 화면과 같은 모양)
        **({"previews": preview_blocks((row.spec or {}).get("blueprint"))} if (row.spec or {}).get("blueprint") else {}),
        "updatedAt": iso(row.updated_at),
        "uses": (use["every"] if row.scope == "company" else use["here"]).get(tid, 0),
        "lastUsed": iso(use["last"][tid]) if tid in use["last"] else None,
    }


def format_views(session: Session, workspace_id: str, user: User) -> List[Dict[str, Any]]:
    """기본(코드) → 사내 → 워크스페이스. 양식마다 쓴 문서 수(uses — 사내는 전체, 워크스페이스는 이 워크스페이스)·내가 마지막으로 쓴 때(lastUsed)."""
    _ws, m = require_member(session, workspace_id, user)
    names = {u.id: display_name(u) for u in Repo(session).users()}
    use = _usage(session, workspace_id, user.id)
    rows = session.exec(select(ReportTemplate).where((ReportTemplate.scope == "company") | (ReportTemplate.workspace_id == workspace_id)).order_by(ReportTemplate.created_at)).all()  # type: ignore[arg-type]
    order = {"company": 0, "workspace": 1, "user": 2}
    mine = sorted((r for r in rows if _visible(r, workspace_id, user.id)), key=lambda r: order.get(r.scope, 3))
    return [*(_builtin_view(k, t, use) for k, t in REPORT_TYPES.items() if k != "free"), *(_row_view(r, user, m, names, use) for r in mine)]


def _int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def clean_sections(session: Session, workspace_id: str, user: User, raw: Any, keep_ids: List[str]) -> List[Dict[str, Any]]:
    """화면에서 고친 섹션 → 저장 모양. 자리의 표 양식은 이 사용자가 볼 수 있는 것만(fill_slots 가 같은 목록에서 찾는다).
    섹션 id 는 받은 것을 지키고 새 섹션은 지금까지 쓴 적 없는 번호를 받는다(이미 만든 문서의 섹션이 엉뚱한 항목을 가리키지 않게)."""
    from app.research.service import visible_templates

    if not isinstance(raw, list) or not raw:
        raise HTTPException(400, "섹션을 하나 이상 두세요.")
    if len(raw) > SECTION_MAX:
        raise HTTPException(400, f"섹션은 {SECTION_MAX}개까지 둘 수 있습니다.")
    tpls = {t["id"]: t for t in visible_templates(session, workspace_id, user.id)}
    nums = [int(x[1:]) for x in [*keep_ids, *(str(s.get("id") or "") for s in raw if isinstance(s, dict))] if _SID.fullmatch(x)]
    next_n = max(nums, default=0) + 1
    seen: set = set()
    out = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        title = str(s.get("title") or "").strip()[:60]
        if not title:
            raise HTTPException(400, "섹션 이름을 적어 주세요.")
        sid = str(s.get("id") or "")
        if not _SID.fullmatch(sid) or sid in seen:
            sid, next_n = f"s{next_n}", next_n + 1
        seen.add(sid)
        slots = []
        for x in (s.get("slots") or [])[:SLOT_MAX]:
            if not isinstance(x, dict):
                continue
            if x.get("kind") == "figure" or not x.get("templateId"):
                # 설명 자리(샘플 분석·화면에서 더한 것) — 표·차트·그림 이름과 구성 한 줄. 표 양식 없이 작성기가 보고 쓴다
                if str(x.get("title") or "").strip():
                    kind = x.get("kind") if x.get("kind") in ("table", "chart", "figure") else "table"
                    slots.append({"kind": kind, "title": str(x["title"]).strip()[:80], **({"desc": str(x["desc"]).strip()[:200]} if str(x.get("desc") or "").strip() else {}), **({"position": "sidebar"} if x.get("position") == "sidebar" else {})})
                continue
            tpl = tpls.get(str(x.get("templateId") or ""))
            if tpl is None:
                raise HTTPException(400, "볼 수 없는 표 양식이 자리에 있습니다.")
            kind = "chart" if x.get("kind") == "chart" and tpl["spec"].get("chart") else "table"
            slot: Dict[str, Any] = {"templateId": tpl["id"], "kind": kind, "title": str(x.get("title") or "").strip()[:80] or tpl["name"]}
            if (tpl["spec"].get("subject") or {}).get("kind") == "period" and isinstance(x.get("rows"), list) and x["rows"]:
                slot["rows"] = [str(r)[:40] for r in x["rows"][:30]]
            slots.append(slot)
        out.append({"id": sid, "title": title, "level": _int(s.get("level"), 1, 3, 1), "guide": str(s.get("guide") or "").strip()[:600], "slots": slots})
    if not out:
        raise HTTPException(400, "섹션을 하나 이상 두세요.")
    return out


def _format_row(session: Session, type_id: str) -> ReportTemplate:
    row = session.get(ReportTemplate, type_id[len(REGISTERED):] if type_id.startswith(REGISTERED) else type_id)
    if row is None:
        raise HTTPException(404, "양식이 없습니다.")
    return row


def create_format(session: Session, workspace_id: str, user: User, body: Dict[str, Any]) -> Dict[str, Any]:
    """{name?, scope?, from?} — from 이 있으면 그 양식(기본·등록)을 복사, 없으면 빈 섹션 하나짜리."""
    scope = check_scope(session, workspace_id, user, str(body.get("scope") or "workspace"))
    src = str(body.get("from") or "")
    desc, source = "", ""
    if src.startswith(REGISTERED):
        row = _format_row(session, src)
        if not _visible(row, workspace_id, user.id):
            raise HTTPException(404, "양식이 없습니다.")
        raw, default, desc, source = copy.deepcopy(_sections_of(row)), f"{row.name} 사본", (row.spec or {}).get("desc") or "", row.source_name
    elif src:
        t = REPORT_TYPES.get(src)
        if t is None or src == "free":
            raise HTTPException(404, "양식이 없습니다.")
        raw, default, desc = [{"id": f"s{i + 1}", "title": it["title"], "level": 1, "guide": it.get("desc") or "", "slots": []} for i, it in enumerate(t["items"])], f"{t['title']} 사본", t["desc"]
    else:
        raw, default = [{"title": "새 섹션"}], "새 양식"
    sections = clean_sections(session, workspace_id, user, raw, [])
    name = str(body.get("name") or default).strip()[:60] or default
    rt = ReportTemplate(id=id36("rp", 4), scope=scope, workspace_id="" if scope == "company" else workspace_id, owner_id=user.id, name=name, source_name=source, spec={"desc": desc, "sections": sections})
    session.add(rt)
    session.commit()
    _ws, m = require_member(session, workspace_id, user)
    return _row_view(rt, user, m, {u.id: display_name(u) for u in Repo(session).users()})


def update_format(session: Session, workspace_id: str, user: User, type_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """{name?, desc?, style?, sections?, assets?, scope?} — 이미 만든 문서는 그대로(새 문서부터 이 양식).
    assets 는 이름·설명·빼기·순서만 받는다(구성·겉모양·위치는 저장된 것). 섹션을 빼면 그 섹션을 가리키던 에셋은 섹션 없이 남는다."""
    row = _format_row(session, type_id)
    _ws, m = require_member(session, workspace_id, user)
    if not _visible(row, workspace_id, user.id):
        raise HTTPException(404, "양식이 없습니다.")
    if not _can_change(row, user, m):
        raise HTTPException(403, "양식은 만든 사람이나 관리자만 고칩니다.")
    spec = copy.deepcopy(row.spec or {})
    # 양식 2.0 틀이 있으면 구성은 틀(장·소주제 — outline)이 정한다. 옛 화면·도구용 섹션·에셋은 틀에서 다시 만든다(blueprint.to_v1)
    if "outline" in body and spec.get("blueprint"):
        from app.templates_import.blueprint import to_v1

        spec["blueprint"] = apply_outline(spec["blueprint"], body["outline"])
        spec["sections"], spec["assets"] = to_v1(spec["blueprint"])
    if "sections" in body and not spec.get("blueprint"):
        spec["sections"] = clean_sections(session, workspace_id, user, body["sections"], [s["id"] for s in _sections_of(row)])
    if (spec.get("assets") or "assets" in body) and not ("outline" in body and spec.get("blueprint")):
        spec["assets"] = clean_assets(body.get("assets"), spec.get("assets") or [], [s["id"] for s in spec.get("sections") or []])
    if "desc" in body:
        spec["desc"] = str(body.get("desc") or "").strip()[:300]
    if "style" in body:
        spec["style"] = str(body.get("style") or "").strip()[:1200]
    if body.get("name"):
        row.name = str(body["name"]).strip()[:60] or row.name
    if body.get("scope") and body["scope"] != row.scope:
        row.scope = check_scope(session, workspace_id, user, str(body["scope"]))
        row.workspace_id = "" if row.scope == "company" else workspace_id
    row.spec = spec
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    forget_registered(f"{REGISTERED}{row.id}")
    return _row_view(row, user, m, {u.id: display_name(u) for u in Repo(session).users()})


def create_from_proposal(session: Session, workspace_id: str, user: User, body: Dict[str, Any], sample: Path, source_name: str, base_assets: List[Dict[str, Any]], draft: bool = False) -> Dict[str, Any]:
    """샘플 분석 제안 → 문서 양식. 샘플 파일은 양식 폴더로 옮겨 '예시 문서'(원본)로 둔다.
    에셋은 분석 결과(base_assets)에서 — body 의 assets 는 이름·설명·빼기만(없으면 전부). draft = 등록 전(분석이 끝나면 바로 이렇게 만든다)."""
    scope = check_scope(session, workspace_id, user, str(body.get("scope") or "workspace"))
    sections = clean_sections(session, workspace_id, user, body.get("sections"), [])
    assets = clean_assets(body.get("assets"), base_assets, [s["id"] for s in sections])
    name = str(body.get("name") or "").strip()[:60] or Path(source_name).stem[:60] or "새 양식"
    rt = ReportTemplate(id=id36("rp", 4), scope=scope, workspace_id="" if scope == "company" else workspace_id, owner_id=user.id, name=name, source_name=source_name, spec={})
    dest = TEMPLATE_DIR / "formats" / rt.id / Path(source_name).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sample, dest)
    rt.spec = {"desc": str(body.get("desc") or "").strip()[:300], "style": str(body.get("style") or "").strip()[:1200], "sections": sections, "assets": assets, "sampleFile": f"formats/{rt.id}/{dest.name}", **({"draft": True} if draft else {})}
    if isinstance(body.get("blueprint"), dict) and body["blueprint"].get("version") == 2:
        rt.spec["blueprint"] = body["blueprint"]  # 양식 2.0 틀 — 문서를 만들 때 doc["layout"] 으로 복사된다(agent/session.seed_sections)
    session.add(rt)
    session.commit()
    _ws, m = require_member(session, workspace_id, user)
    return _row_view(rt, user, m, {u.id: display_name(u) for u in Repo(session).users()})


def register_draft(session: Session, workspace_id: str, user: User, type_id: str, scope: str) -> Dict[str, Any]:
    """등록 전 양식 → 등록(범위 = 워크스페이스·사내). 이제 다른 사람·새 문서·양식 고르기에 보인다."""
    row = _format_row(session, type_id)
    _ws, m = require_member(session, workspace_id, user)
    if not _visible(row, workspace_id, user.id):
        raise HTTPException(404, "양식이 없습니다.")
    if not _draft(row):
        raise HTTPException(409, "이미 등록한 양식입니다.")
    if not _can_change(row, user, m):
        raise HTTPException(403, "양식은 만든 사람이나 관리자만 등록합니다.")
    row.scope = check_scope(session, workspace_id, user, scope or "workspace")
    row.workspace_id = "" if row.scope == "company" else workspace_id
    spec = copy.deepcopy(row.spec or {})
    spec.pop("draft", None)
    row.spec = spec
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    forget_registered(f"{REGISTERED}{row.id}")
    return _row_view(row, user, m, {u.id: display_name(u) for u in Repo(session).users()})


def format_view(session: Session, workspace_id: str, user: User, type_id: str) -> Dict[str, Any]:
    """양식 하나의 화면 모양(말로 고치기 전에 지금 양식을 읽는다). 고칠 수 없으면 403."""
    row = _format_row(session, type_id)
    _ws, m = require_member(session, workspace_id, user)
    if not _visible(row, workspace_id, user.id):
        raise HTTPException(404, "양식이 없습니다.")
    if not _can_change(row, user, m):
        raise HTTPException(403, "양식은 만든 사람이나 관리자만 고칩니다.")
    return _row_view(row, user, m, {u.id: display_name(u) for u in Repo(session).users()})


def asset_image(session: Session, workspace_id: str, user: User, type_id: str, asset_id: str) -> bytes:
    """에셋이 샘플(PDF)에서 있던 부분만 잘라 PNG 로 — 분석 때 받은 위치(box)에 여백을 조금 둔다. 위치가 없으면 404(화면은 원본 쪽 전체)."""
    import fitz  # PyMuPDF

    p = sample_path(session, workspace_id, user, type_id)
    row = _format_row(session, type_id)
    a = next((x for x in (row.spec or {}).get("assets") or [] if x.get("id") == asset_id), None)
    src = (a or {}).get("source") or {}
    f = (((row.spec or {}).get("blueprint") or {}).get("forms") or {}).get(asset_id)
    if not (a and src.get("box")) and f and f.get("bbox") and f.get("page"):
        # 양식 2.0 틀의 표·그림 양식(차트·그림 자리 포함) — 원본 쪽 좌표(pt)를 쪽 크기로 나눈다(A4 기준, 실제 쪽 크기는 아래에서 곱한다)
        x0, y0, x1, y1 = f["bbox"]
        a, src = f, {"page": f["page"], "box": [x0 / 595.32, max(0.0, y0 - 14) / 841.92, x1 / 595.32, y1 / 841.92]}
    if not a or not src.get("box") or not src.get("page") or p.suffix.lower() != ".pdf":
        raise HTTPException(404, "원본 위치가 없습니다.")
    doc = fitz.open(str(p))
    try:
        if not 1 <= int(src["page"]) <= len(doc):
            raise HTTPException(404, "원본 위치가 없습니다.")
        page = doc[int(src["page"]) - 1]
        w, h = page.rect.width, page.rect.height
        x0, y0, x1, y1 = src["box"]
        # 아래 여백을 더 — VL 상자가 표 밑 '자료:' 줄을 자주 조금 못 미친다(인디아 브리핑 표 1)
        clip = fitz.Rect(max(0.0, x0 - 0.015) * w, max(0.0, y0 - 0.01) * h, min(1.0, x1 + 0.015) * w, min(1.0, y1 + 0.022) * h)
        return page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), clip=clip).tobytes("png")
    finally:
        doc.close()


__all__ = ["asset_image", "can_use", "format_view", "register_draft", "check_scope", "clean_sections", "create_format", "create_from_proposal", "delete_report_template", "format_views", "report_type_views", "sample_path", "update_format"]
