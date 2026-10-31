"""검색·자료 가공 탭 — 찾기(문서·문단·숫자·자료 속 표·시계열·정리한 데이터, 종류·발행처·기간 거르기) →
담기 → 가공(표로·차트로, 칸마다 원문) → 드라이브에 저장 → 이 자료로 문서 쓰기.

자연어 질의("가온전자·나래바이오 2022~2024 영업이익률")는 LLM 이 표 계획(행·열·기간)만 내고, 값은 리서치 엔진(fill_table)이 원장에서 칸마다 원문과 함께 채운다.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session

from app.auth import require_member
from app.db import Repo, ResearchTable, User, engine, scope_ids
from app.docs.asof import doc_date
from app.docs.store import doc_label, load_meta
from app.ids import id36
from app.llm.base import ChatParams

log = logging.getLogger(__name__)
KINDS = ("document", "file", "figure", "table", "series", "asset", "doc", "folder")


def _meta_ok(doc_id: Optional[str], doc_type: str, issuer: str, since: str, until: str) -> bool:
    if not doc_id:
        return not (doc_type or issuer or since or until)
    meta = load_meta(doc_id) or {}
    c = meta.get("card") or {}
    if doc_type and c.get("docType") != doc_type:
        return False
    if issuer and issuer.lower() not in f"{c.get('issuer') or ''} {c.get('company') or ''} {c.get('title') or ''}".lower():
        return False
    if since or until:
        d = doc_date(meta)
        if d is None or (since and d.isoformat() < since) or (until and d.isoformat() > until):
            return False
    return True


def search(session: Session, workspace_id: str, user: User, q: str, kinds: List[str], doc_type: str = "", issuer: str = "", since: str = "", until: str = "") -> Dict[str, Any]:
    from app.market.catalog import SERIES
    from app.market.service import series_card
    from app.research.doc_tables import table_list
    from app.search import search_workspace

    ws, _m = require_member(session, workspace_id, user)
    base = search_workspace(session, workspace_id, user, q) if q.strip() else {"query": q, "groups": []}
    groups = []
    for g in base.get("groups") or []:
        if kinds and g["kind"] not in kinds:
            continue
        items = [it for it in g["items"] if _meta_ok(it.get("docId"), doc_type, issuer, since, until)] if g["kind"] in ("document", "file", "figure") else g["items"]
        if items:
            groups.append({**g, "items": items})
    terms = [t for t in re.split(r"\s+", q.strip().lower()) if t]
    # 자료 속 표 — 이름·발행처가 맞는 자료, 또는 표 제목에 낱말이 든 것
    if (not kinds or "table" in kinds) and terms:
        tbl = []
        for d in scope_ids(ws)[:200]:
            if not _meta_ok(d, doc_type, issuer, since, until):
                continue
            label = doc_label(load_meta(d), d)
            try:
                tl = table_list(d)
            except Exception:  # noqa: BLE001
                continue
            for t in tl:
                hay = f"{label} {t.get('caption') or ''} {' '.join(map(str, t.get('header') or []))}".lower()
                if all(x in hay for x in terms[:3]) or any(x in (t.get("caption") or "").lower() for x in terms):
                    tbl.append({"kind": "table", "docId": d, "chunk": t["chunk"], "title": t.get("caption") or f"표 {t['no']}", "sub": f"{label} · {'p.' + str(t['page']) + ' · ' if t.get('page') else ''}{t['rows']}행 × {t['cols']}열"})
            if len(tbl) >= 12:
                break
        if tbl:
            groups.append({"kind": "table", "label": "자료 속 표", "items": tbl[:12]})
    # 시장·거시 시계열 — 이름 일부
    if (not kinds or "series" in kinds) and terms:
        hits = [s for s in SERIES if any(x in s.name.lower() or x in s.id for x in terms)]
        if hits:
            items = []
            for s in hits[:8]:
                c = series_card(s.id, spark=0)
                items.append({"kind": "series", "id": s.id, "title": s.name, "sub": f"{c.get('display') or '—'} {s.unit} · {c.get('date') or ''} · {c.get('sourceLabel') or ''}{' · 가상' if c.get('virtual') else ''}"})
            groups.append({"kind": "series", "label": "시장·거시 시계열", "items": items})
    return {"query": q, "groups": groups}


# ── 자연어 질의 → 표 ──

PLAN_PROMPT = """사용자 질문을 '출처 달린 비교 표' 계획으로 바꾼다. JSON 하나로만 답한다(설명·코드 블록 없이).
{"title": "표 제목", "row_kind": "company|document|period|label", "rows": ["행 이름(기업·문서·기간)"], "columns": [{"label": "열 이름(지표)", "type": "number|text|calc", "unit": "단위(선택)", "formula": "calc 열만 — 앞 열 이름으로 ratio(영업이익, 매출액)·growth(새, 옛)·diff(a, b)"}], "period": "기준 기간(예: 2024 — 여러 기간을 행으로 볼 때는 비움)", "series": ["시장 시리즈 이름(금리·환율 추이를 물을 때만)"]}
규칙:
- 숫자 값은 쓰지 않는다(값은 원장에서 코드가 채운다). 행·열·기간만 정한다.
- 기간 비교(2022~2024)는 row_kind=period, rows=["2022","2023","2024"], 기업이 하나면 title 에 기업 이름을 넣는다. 기업이 여럿이고 기간도 여럿이면 기업을 행으로, 마지막 기간을 period 로.
- 비율·증가율 같은 계산 지표(영업이익률·순이익률·매출 증가율)는 type=calc 로 두고, 계산에 쓸 원 지표(영업이익·매출액 등)를 앞에 number 열로 함께 넣는다(예: 매출액, 영업이익, 영업이익률=ratio(영업이익, 매출액)). 증가율은 periodOffset=-1 인 전년 열을 같이 넣는다."""


def _json(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M))
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


def _studio_doc(session: Session, workspace_id: str, user: User) -> Dict[str, Any]:
    from app.drive import report_scope_ids
    from app.ledger.service import choices_of
    from app.research.service import visible_templates

    ws = Repo(session).workspace(workspace_id)
    doc = {"id": "", "workspaceId": workspace_id, "ownerId": user.id, "dataScope": {"groups": ["workspace", "company"]}}
    doc["documentIds"] = report_scope_ids(session, ws, doc, user.id)
    doc["ledgerChoices"] = {k: v for k, v in (choices_of(session, workspace_id) or {}).items()} if callable(choices_of) else {}
    doc["_templates"] = visible_templates(session, workspace_id, user.id)
    return doc


async def query(workspace_id: str, user: User, q: str, llm: Any = None) -> Dict[str, Any]:
    from app.agent.tools import ToolContext
    from app.llm.client import ReportLlm
    from app.market.catalog import SERIES
    from app.market.service import series_view
    from app.research.tools import ResearchContext, _build_table

    text = (q or "").strip()[:500]
    if not text:
        raise HTTPException(400, "무엇을 찾을지 적어 주세요.")
    with Session(engine) as s:
        require_member(s, workspace_id, user)
        sdoc = _studio_doc(s, workspace_id, user)
    llm = llm or ReportLlm()
    res = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": f"{PLAN_PROMPT}\n\n## 질문\n{text}"}], temperature=0.1, max_tokens=2500, reasoning_effort="low", timeout_s=120))
    plan = _json(getattr(res, "content", "") or "") or {}
    out: Dict[str, Any] = {"query": text, "plan": plan, "tableId": None, "summary": "", "series": []}
    want = [str(x) for x in plan.get("series") or []]
    if want:
        out["series"] = [series_view(sr.id, "1Y") for sr in SERIES if any(w and (w in sr.name or sr.name in w) for w in want)][:4]
    if plan.get("rows") and plan.get("columns"):
        noop = lambda _e: None  # noqa: E731 — 화면 이벤트 없음(결과는 응답으로)
        rc = ResearchContext(doc=sdoc, llm=llm, emit=noop, agent=ToolContext(doc=sdoc, llm=llm, emit=noop))
        args = {"title": plan.get("title") or text[:40], "rows": plan.get("rows"), "row_kind": plan.get("row_kind") or "company", "columns": plan.get("columns"), "period": plan.get("period") or ""}
        out["summary"] = await _build_table(args, rc)
        out["tableId"] = sdoc.get("currentTableId")
    return out


# ── 담은 것 → 표·차트 ──

def compose(session: Session, workspace_id: str, user: User, items: List[Dict[str, Any]], op: str = "table", title: str = "") -> Dict[str, Any]:
    from app.anchors import pin_table_cells
    from app.ledger.service import ledger_for
    from app.research.doc_tables import create_from_doc
    from app.research.fill import format_columns, number_cell
    from app.research.service import ResearchService

    require_member(session, workspace_id, user, "reviewer")
    figs = [i for i in items if i.get("kind") == "figure"]
    tables = [i for i in items if i.get("kind") == "table"]
    paras = [i for i in items if i.get("kind") == "document"]
    made: List[str] = []
    if figs:
        led = ledger_for(session, workspace_id)
        by_key = {g["key"]: g for g in led["groups"]}
        by_fid = {f["fid"]: f for f in led["figures"]}
        subjects, cells = [], []
        for it in figs:
            g = by_key.get(it.get("key") or "")
            f = by_fid.get((g or {}).get("figureIds", [None])[0] or "") if g else None
            if not f:
                continue
            subjects.append({"label": f"{g['metric']} · {g['period']}"[:80], "docId": f["doc"]})
            cells.append({"v": number_cell(f, "picked")})
        if subjects:
            data = {"spec": {"name": title or "담은 숫자", "subject": {"kind": "label"}, "items": [{"key": "v", "label": "값", "type": "number"}]}, "templateId": None, "subjects": subjects,
                    "items": [{"key": "v", "label": "값", "type": "number"}], "inputs": {}, "cells": cells, "progress": {"done": len(subjects), "total": len(subjects)}}
            data["columns"] = format_columns(data["items"], cells)  # 열 단위·표기(차트가 숫자 열을 찾는 데 쓴다)
            pin_table_cells(data)
            row = Repo(session).save(ResearchTable(id=id36("rt", 4), workspace_id=workspace_id, chat_id="", created_by=user.id, title=(title or "담은 숫자")[:80], status="done", data=data))
            made.append(row.id)
    for t in tables[:4]:
        row = create_from_doc(session, workspace_id, user, t["docId"], t["chunk"], chat_id="", title=t.get("title") or "")
        made.append(row.id)
    if paras:
        lines, cites = [], []
        for p in paras[:20]:
            label = doc_label(load_meta(p["docId"]), p["docId"])
            lines.append(f"- “{(p.get('text') or '').strip()[:240]}” [{label}{' ' + p['sub'] if p.get('sub') else ''}](#cite={p['docId']}~{p['chunk']})")
            cites.append({"docId": p["docId"], "chunk": p["chunk"], "label": label})
        row = Repo(session).save(ResearchTable(id=id36("rt", 4), workspace_id=workspace_id, chat_id="", created_by=user.id, title=(title or "담은 문단")[:80], status="done", kind="note",
                                               data={"text": "\n".join(lines), "cites": cites, "question": ""}))
        made.append(row.id)
    if not made:
        raise HTTPException(400, "표·차트로 만들 수 있는 것을 담아 주세요(숫자·자료 속 표·문단).")
    charts: List[str] = []
    if op == "chart":
        for tid in made:
            try:
                charts.append(ResearchService(session).make_chart(tid, user, {"type": "bar", "title": title or ""}).id)
            except HTTPException:
                continue
    return {"tables": made, "charts": charts, "open": (charts or made)[0]}
