"""자료 버전 — 워크스페이스 안에서 "이 파일은 저 자료의 새 판"을 묶는다.

 - 새 판을 올리면 활성 목록(workspace.document_ids)에서 이전 판 자리를 새 판이 **같은 순서로** 차지한다.
   원장·검색·리포트는 활성 목록만 본다(이전 판 숫자가 새 판과 '충돌'로 잡히지 않게). 이전 판은 보관 — 비교·원문 보기만.
 - 버전 관계는 워크스페이스마다 다르다(같은 파일이 다른 워크스페이스에서는 다른 자료의 판일 수 있다) → doc_version 표.
 - 숫자 비교는 두 판의 원장(figures.json)을 (지표·기간·기준·%) 로 맞춰 바뀜·새로 생김·없어짐을 낸다(LLM 0회).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.db import DocVersion, Repo, Workspace, excluded_ids, iso, set_excluded, utcnow
from app.docs.store import doc_label, load_meta
from app.ledger.figures import Figure, load_figures
from app.ledger.numbers import same_value


def _row(session: Session, workspace_id: str, doc_id: str) -> Optional[DocVersion]:
    return session.get(DocVersion, (workspace_id, doc_id))


def register_version(session: Session, ws: Workspace, old_id: str, new_id: str, user_id: str) -> Optional[DocVersion]:
    """old 의 새 판으로 new 를 등록하고 활성 목록에서 자리를 바꾼다. 같은 파일이면 아무것도 안 한다."""
    if old_id == new_id:
        return None
    repo = Repo(session)
    old = _row(session, ws.id, old_id)
    if old is None:
        old = DocVersion(workspace_id=ws.id, doc_id=old_id, root_id=old_id, version=1, prev_id=None, created_by=user_id)
        repo.save(old)
    new = _row(session, ws.id, new_id) or DocVersion(workspace_id=ws.id, doc_id=new_id, root_id=old.root_id, created_by=user_id)
    new.root_id, new.version, new.prev_id = old.root_id, old.version + 1, old_id
    repo.save(new)
    ids = list(ws.document_ids or [])
    if old_id in ids:
        ids = [new_id if d == old_id else d for d in ids if d != new_id]
    elif new_id not in ids:
        ids.append(new_id)
    ws.document_ids = ids  # 새 list 대입(JSON 컬럼 변경)
    if old_id in excluded_ids(ws):  # 근거 제외(검수 대상 초안)의 새 판도 근거 제외
        set_excluded(ws, new_id, True)
    repo.save(ws)
    return new


def chain(session: Session, workspace_id: str, doc_id: str) -> List[str]:
    """같은 묶음의 판들(옛 → 새). 묶음이 없으면 [doc_id]."""
    row = _row(session, workspace_id, doc_id)
    if row is None:
        return [doc_id]
    rows = session.exec(select(DocVersion).where(DocVersion.workspace_id == workspace_id, DocVersion.root_id == row.root_id)).all()
    return [r.doc_id for r in sorted(rows, key=lambda r: r.version)]


def archived_ids(session: Session, workspace_id: str) -> List[str]:
    """보관된 이전 판들(활성 목록에 없는 버전 행) — 원문 보기·비교만 허용한다."""
    ws = Repo(session).workspace(workspace_id)
    active = set((ws.document_ids if ws else None) or [])
    return [r.doc_id for r in session.exec(select(DocVersion).where(DocVersion.workspace_id == workspace_id)).all() if r.doc_id not in active]


def version_map(session: Session, workspace_id: str) -> Dict[str, Dict[str, Any]]:
    """활성 자료 카드에 붙일 판 정보 — {doc_id: {version, prevId, history:[{docId, version, label, at}]}}."""
    rows = list(session.exec(select(DocVersion).where(DocVersion.workspace_id == workspace_id)).all())
    by_root: Dict[str, List[DocVersion]] = {}
    for r in rows:
        by_root.setdefault(r.root_id, []).append(r)
    out: Dict[str, Dict[str, Any]] = {}
    for group in by_root.values():
        group.sort(key=lambda r: r.version)
        history = [{"docId": r.doc_id, "version": r.version, "label": doc_label(load_meta(r.doc_id), r.doc_id), "fileName": (load_meta(r.doc_id) or {}).get("fileName") or "", "at": iso(r.created_at)} for r in group]
        for r in group:
            out[r.doc_id] = {"version": r.version, "prevId": r.prev_id, "history": history}
    return out


# ── 숫자 비교 ───────────────────────────────────────────────────────────

def _key(f: Figure) -> Tuple[str, str, str, bool]:
    return (f["metricKey"], f["periodKey"], f.get("basis") or "", bool(f.get("percent")))


def _same(a: Figure, b: Figure) -> bool:
    if a.get("unitKnown", True) and b.get("unitKnown", True):
        return same_value(a["abs"], a["step"], b["abs"], b["step"])
    return same_value(a["value"], 10 ** -int(a.get("decimals") or 0), b["value"], 10 ** -int(b.get("decimals") or 0))


def _ref(f: Figure) -> Dict[str, Any]:
    return {"docId": f["doc"], "chunk": f["chunk"], "cell": f.get("cell"), "page": f.get("page"), "sheet": f.get("sheet"), "display": f.get("display") or f["raw"]}


def compare_figures(old_id: str, new_id: str) -> Dict[str, Any]:
    """두 판의 표 칸 수치 비교. 같은 키가 한 판에 여럿이면 첫 칸끼리(표가 둘인 문서는 첫 표 기준)."""
    def index(doc_id: str) -> Dict[Tuple[str, str, str, bool], Figure]:
        out: Dict[Tuple[str, str, str, bool], Figure] = {}
        for f in load_figures(doc_id):
            out.setdefault(_key(f), f)
        return out

    a, b = index(old_id), index(new_id)
    changed, added, removed = [], [], []
    same = 0
    for k, fa in a.items():
        fb = b.get(k)
        if fb is None:
            removed.append({"metric": fa["metric"], "period": fa["period"], "basis": fa.get("basis"), "before": _ref(fa)})
        elif _same(fa, fb):
            same += 1
        else:
            delta = fb["abs"] - fa["abs"] if fa.get("unitKnown", True) and fb.get("unitKnown", True) else fb["value"] - fa["value"]
            changed.append({"metric": fb["metric"], "period": fb["period"], "basis": fb.get("basis"), "before": _ref(fa), "after": _ref(fb), "delta": delta, "percent": bool(fb.get("percent"))})
    for k, fb in b.items():
        if k not in a:
            added.append({"metric": fb["metric"], "period": fb["period"], "basis": fb.get("basis"), "after": _ref(fb)})
    order = lambda x: (x["metric"], x["period"])  # noqa: E731
    return {
        "old": {"docId": old_id, "label": doc_label(load_meta(old_id), old_id)},
        "new": {"docId": new_id, "label": doc_label(load_meta(new_id), new_id)},
        "changed": sorted(changed, key=order),
        "added": sorted(added, key=order),
        "removed": sorted(removed, key=order),
        "same": same,
        "comparedAt": iso(utcnow()),
    }


__all__ = ["archived_ids", "chain", "compare_figures", "register_version", "version_map"]
