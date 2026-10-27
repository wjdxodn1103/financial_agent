"""올린 문서 속 표 → 에셋(LLM 없음) + 에셋 메타데이터(출처·모양 지문)로 비슷한 문서 알아보기.

표 꺼내기: 문서의 표 청크(큰 표는 p12·p12r1… 행 묶음 — 머리 행은 한 번만)를 합쳐, 칸마다 원장 수치(fid)로 잇는다.
          원장이 못 읽은 칸은 글 칸 + 그 표 문단 인용. 양식 모양(행 종류·열·단위·방향)은 규칙(templates_import.spec.rule_spec).
메타데이터: data.source = {docId, chunk, page, docLabel, issuer, docType, date}
           data.sig    = {caption, labels} — 캡션·행 이름·열 이름에서 숫자·연도·기간 말을 뗀 것(다음 판 보고서는 값·연도만 바뀐다)
비슷한 문서: 새 문서의 표 지문을 내가 볼 수 있는 에셋(내 것 + 공유된 것)의 지문과 비교 — 똑같은 문서면 '이미 만든 에셋',
            다른 문서면 '같은 모양' → 같은 모양으로 만들기(옛 에셋의 열·단위·이름 그대로, 그 표로 만든 차트도 같이).
"""
from __future__ import annotations

import copy
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session

from app.db import ResearchTable, User
from app.docs.extract import is_data_table
from app.docs.store import doc_label, load_meta, paragraphs
from app.research.entities import norm
from app.research.fill import Scope, format_columns, new_data, number_cell

_ROW_GROUP = re.compile(r"r\d+$")
_PERIODISH = re.compile(r"\d+|년도?|분기|상반기|하반기|반기|월|fy|ytd|[1-4]q|q[1-4]|기준|말|초")
_UNIT_TAIL = re.compile(r"\s*[(\[][^()\[\]]{1,12}[)\]]\s*$")
SIMILAR_MIN = 0.6


def label_key(label: str) -> str:
    """'영업이익률(%)' → '영업이익률' — 표 칸과 양식 열 이름 맞추기."""
    return norm(_UNIT_TAIL.sub("", label or ""))


def _shape_key(text: str) -> str:
    return _PERIODISH.sub("", norm(_UNIT_TAIL.sub("", text or "")))


@lru_cache(maxsize=256)
def _doc_tables(doc_id: str) -> Tuple[Dict[str, Any], ...]:
    """문서의 칸 구조 표 — 본문 순서. 행마다 원래 (청크, 행 번호)를 지닌다(원장 칸 찾기). 문서 id = 내용 해시라 캐시해도 된다."""
    groups: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for p in paragraphs(doc_id):
        rows = p.get("rows")
        if p.get("kind") != "table" or not rows:
            continue
        cid = str(p.get("id"))
        base = _ROW_GROUP.sub("", cid)
        g = groups.get(base)
        if g is None:
            g = {"chunk": base, "page": p.get("page"), "caption": p.get("heading") or "", "unit": p.get("unit"), "rows": [rows[0]], "refs": [(cid, 0)]}
            groups[base] = g
            order.append(base)
        for ri in range(1, len(rows)):
            g["rows"].append(rows[ri])
            g["refs"].append((cid, ri))
    out = []
    for n, base in enumerate(order, 1):
        g = groups[base]
        if is_data_table(g["rows"]):
            out.append({**g, "no": n, "sig": signature(g["caption"], g["rows"])})
    return tuple(out)


def doc_tables(doc_id: str) -> List[Dict[str, Any]]:
    return [dict(t) for t in _doc_tables(doc_id)]


def table_list(doc_id: str) -> List[Dict[str, Any]]:
    """화면·AI 용 목록 — 표 번호·캡션·쪽·크기·머리 줄."""
    return [{"chunk": t["chunk"], "no": t["no"], "page": t["page"], "caption": t["caption"], "unit": t["unit"], "rows": len(t["rows"]) - 1, "cols": max(len(r) for r in t["rows"]), "header": t["rows"][0]} for t in _doc_tables(doc_id)]


def signature(caption: str, rows: List[List[str]]) -> Dict[str, Any]:
    labels = {_shape_key(r[0]) for r in rows[1:] if r} | {_shape_key(h) for h in rows[0][1:]}
    return {"caption": _shape_key(caption), "labels": sorted(x for x in labels if len(x) >= 2)}


def similarity(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    la, lb = set(a.get("labels") or []), set(b.get("labels") or [])
    if len(la) < 2 or len(lb) < 2:
        return 0.0
    jac = len(la & lb) / len(la | lb)
    cap = 1.0 if a.get("caption") and a.get("caption") == b.get("caption") else 0.0
    return round(0.8 * jac + 0.2 * cap, 3)


def source_of(doc_id: str, t: Dict[str, Any]) -> Dict[str, Any]:
    m = load_meta(doc_id) or {}
    c = m.get("card") or {}
    return {"docId": doc_id, "chunk": t["chunk"], "page": t.get("page"), "docLabel": doc_label(m, doc_id), "issuer": c.get("issuer") or "", "docType": c.get("docType") or "", "date": c.get("date") or ""}


def build_from_doc(doc_id: str, chunk: str, spec: Optional[Dict[str, Any]] = None, col_map: Optional[Dict[str, int]] = None, max_rows: int = 0) -> Tuple[str, Dict[str, Any]]:
    """문서 표 하나 → (제목, 표 data). spec 을 주면 그 열(이름·단위·방향)로 — 같은 모양으로 만들기.
    col_map = {열 key: 원 표 열 번호} — 문서 양식의 표 양식으로 옮길 때(research/forms.map_columns), 이름 대신 이 번호로 칸을 가져온다.
    max_rows = 행 상한(0 이면 채우는 표와 같은 MAX_ROWS) — 양식 차트의 기간 행은 더 길다."""
    from app.templates_import.spec import rule_spec

    t = next((x for x in _doc_tables(doc_id) if x["chunk"] == chunk), None)
    if t is None:
        raise ValueError("그런 표가 없습니다.")
    rows, refs = t["rows"], t["refs"]
    caption = t["caption"] or f"표 {t['no']}"
    spec = copy.deepcopy(spec) if spec else rule_spec(rows, caption, t.get("unit"))
    items = [it for it in spec.get("items") or [] if not it.get("hidden")]
    scope = Scope([doc_id], {})
    label = doc_label(load_meta(doc_id), doc_id)

    def cell(r: int, c: int) -> Dict[str, Any]:
        raw = rows[r][c].strip() if c < len(rows[r]) else ""
        if not raw or raw in ("-", "–", "—"):
            return {"type": "empty", "reason": "원문 칸이 비어 있음"}
        cid, ri = refs[r]
        f = scope.cell_figure(doc_id, cid, ri, c)
        if f is not None:
            return number_cell(f, "doc")
        return {"type": "text", "text": raw, "cites": [{"docId": doc_id, "chunk": cid, "label": label, "page": t.get("page")}]}

    by_col = {label_key(h): j for j, h in enumerate(rows[0]) if j > 0}
    by_row = {label_key(r[0]): i for i, r in enumerate(rows) if i > 0 and r}
    if spec.get("orientation") == "items_as_rows" and any(label_key(it["label"]) in by_row for it in items):
        subjects = [{"label": h} for h in rows[0][1:] if h.strip()]
        cols = [j for j, h in enumerate(rows[0]) if j > 0 and h.strip()]
        cells = [{it["key"]: cell(by_row[label_key(it["label"])], j) if label_key(it["label"]) in by_row else {"type": "empty", "reason": "원문에 없는 행"} for it in items} for j in cols]
    else:
        body = [i for i in range(1, len(rows)) if rows[i] and rows[i][0].strip()]
        if col_map is not None:  # 양식 열 ← 원 표 열 번호. 둘째 머리 줄(첫 칸이 빈 이어짐)은 위에서 이미 빠진다
            body = body[: max_rows or None]
            subjects = [{"label": rows[i][0]} for i in body]
            cells = [{it["key"]: cell(i, col_map[it["key"]]) if it["key"] in col_map else {"type": "empty", "reason": "원 표에 없는 열"} for it in items} for i in body]
        else:
            subjects = [{"label": rows[i][0]} for i in body]
            cells = [{it["key"]: cell(i, by_col[label_key(it["label"])]) if label_key(it["label"]) in by_col else {"type": "empty", "reason": "원문에 없는 열"} for it in items} for i in body]
    data = new_data(spec, subjects, {}, None, spec.get("items"))
    if max_rows:
        data["subjects"] = [{"label": s["label"]} for s in subjects[:max_rows]]
    data["cells"] = cells
    data["columns"] = format_columns(data["items"], cells)
    data["progress"] = {"done": len(subjects), "total": len(subjects)}
    data["period"] = None
    data["source"] = source_of(doc_id, t)
    data["sig"] = t["sig"]
    return caption, data


def create_from_doc(session: Session, workspace_id: str, user: User, doc_id: str, chunk: str, chat_id: str = "", spec: Optional[Dict[str, Any]] = None, title: str = "", col_map: Optional[Dict[str, int]] = None, max_rows: int = 0, form: Optional[Dict[str, Any]] = None) -> ResearchTable:
    from app.db import Repo
    from app.ids import id36

    cap, data = build_from_doc(doc_id, chunk, spec, col_map, max_rows)
    if form:
        data["form"] = form
    return Repo(session).save(ResearchTable(id=id36("rt", 4), workspace_id=workspace_id, chat_id=chat_id, created_by=user.id, title=(title or cap)[:80], status="done", data=data))


def similar_for_doc(session: Session, workspace_id: str, user: User, doc_id: str) -> Dict[str, Any]:
    """→ {same: [이 문서로 이미 만든 에셋], similar: [{chunk, caption, page, asset{…}, score}]} — 내 것 + 공유된 에셋만 본다."""
    from app.auth import display_name
    from app.db import Repo
    from app.research.assets import visible_assets

    names = {u.id: display_name(u) for u in Repo(session).users()}
    assets = [a for a in visible_assets(session, workspace_id, user) if (a.kind or "table") == "table" and (a.data or {}).get("sig")]
    same = [a for a in assets if ((a.data or {}).get("source") or {}).get("docId") == doc_id]
    done_chunks = {((a.data or {}).get("source") or {}).get("chunk") for a in same}
    others = [a for a in assets if ((a.data or {}).get("source") or {}).get("docId") != doc_id]
    similar = []
    for t in _doc_tables(doc_id):
        if t["chunk"] in done_chunks:
            continue
        best = max(((similarity(t["sig"], a.data["sig"]), a) for a in others), key=lambda x: (x[0], x[1].updated_at), default=(0.0, None))
        if best[1] is not None and best[0] >= SIMILAR_MIN:
            a = best[1]
            src = (a.data or {}).get("source") or {}
            similar.append({"chunk": t["chunk"], "no": t["no"], "caption": t["caption"], "page": t["page"], "score": best[0], "asset": {"id": a.id, "title": a.title, "createdBy": names.get(a.created_by, ""), "mine": a.created_by == user.id, "sourceDocLabel": src.get("docLabel") or ""}})
    view = lambda a: {"id": a.id, "title": a.title, "createdBy": names.get(a.created_by, ""), "mine": a.created_by == user.id, "chunk": ((a.data or {}).get("source") or {}).get("chunk")}  # noqa: E731
    return {"same": [view(a) for a in same], "similar": similar}


def asset_hints(session: Session, workspace_id: str, user: User, doc_ids: List[str]) -> Dict[str, Dict[str, int]]:
    """드라이브 목록용 — 자료마다 {tables: 표 수, same: 이 자료로 만든 에셋, similar: 같은 모양 표}(내 것 + 공유된 에셋 기준)."""
    from app.research.assets import visible_assets

    assets = [a for a in visible_assets(session, workspace_id, user) if (a.kind or "table") == "table" and (a.data or {}).get("sig")]
    out: Dict[str, Dict[str, int]] = {}
    for d in doc_ids:
        tables = _doc_tables(d)
        if not tables:
            continue
        mine = [a for a in assets if ((a.data or {}).get("source") or {}).get("docId") == d]
        done = {((a.data or {}).get("source") or {}).get("chunk") for a in mine}
        others = [a for a in assets if ((a.data or {}).get("source") or {}).get("docId") != d]
        similar = sum(1 for t in tables if t["chunk"] not in done and any(similarity(t["sig"], a.data["sig"]) >= SIMILAR_MIN for a in others))
        out[d] = {"tables": len(tables), "same": len(mine), "similar": similar}
    return out


def apply_similar(session: Session, workspace_id: str, user: User, doc_id: str, picks: List[Dict[str, str]], chat_id: str = "") -> List[ResearchTable]:
    """같은 모양으로 만들기 — 옛 에셋의 spec(열·단위·방향)과 이름으로 이 문서의 표를, 그 표로 만든 (볼 수 있는) 차트도 같은 설정으로."""
    from fastapi import HTTPException

    from app.research.chart import ChartError, dependents
    from app.research.service import ResearchService

    svc = ResearchService(session)
    made: List[ResearchTable] = []
    for p in picks:
        old = svc.table_row(str(p.get("assetId") or ""), user)
        t = next((x for x in _doc_tables(doc_id) if x["chunk"] == p.get("chunk")), None)
        if t is None:
            continue
        new = create_from_doc(session, workspace_id, user, doc_id, t["chunk"], chat_id, spec=(old.data or {}).get("spec"), title=t["caption"] or old.title)
        made.append(new)
        for ch in dependents(session, old):
            try:
                svc.table_row(ch.id, user)
            except HTTPException:
                continue  # 남의 비공개 차트
            spec = (ch.data or {}).get("chart") or {}
            names = [s["name"] for s in (ch.data or {}).get("series") or []]
            try:
                # 원 표 제목을 그대로 쓴 차트면 새 표 제목으로(옛 판의 연도가 남지 않게)
                title = new.title if ch.title == old.title else ch.title
                made.append(svc.make_chart(new.id, user, {"type": spec.get("type"), "series": names, "horizontal": spec.get("horizontal"), "title": title}, chat_id=chat_id))
            except (HTTPException, ChartError):
                continue
    return made


__all__ = ["apply_similar", "asset_hints", "build_from_doc", "create_from_doc", "doc_tables", "label_key", "signature", "similar_for_doc", "similarity", "table_list"]
