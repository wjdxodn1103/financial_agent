"""평가 세트 채점 — 질의응답(검색·가공 탭의 자연어 질의 → 표 칸 값)과 가정 판정(기준일별 코드 판정)을 기대 값과 코드가 맞춘다.
세트: demo/eval/qa_set.json · assumption_set.json. 질의 평가가 만든 표는 채점 뒤 지운다. 결과는 DATA_DIR/quality/eval_last.json (+ 기록 evals.jsonl).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app import config
from app.db import Membership, Repo, ResearchTable, User, engine, scope_ids
from app.ids import now_iso
from app.ledger.numbers import parse_number

log = logging.getLogger(__name__)
SETS = config.BACKEND_DIR.parent / "demo" / "eval"
OUT = config.DATA_DIR / "quality"


def _load(name: str) -> List[Dict[str, Any]]:
    p = SETS / name
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("cases") or []
    except (OSError, ValueError):
        return []


def _norm(s: Any) -> str:
    return re.sub(r"[\s·()]+", "", str(s or "")).lower()


def _cell_value(data: Dict[str, Any], row: str, column: str) -> Optional[float]:
    """표에서 행(이름 일부)·열(이름 일부)의 값 — 숫자 칸은 원문 칸 숫자, 계산 칸은 계산 값."""
    items = data.get("items") or []
    cols = [i for i in items if _norm(column) in _norm(i.get("label"))]
    subs = data.get("subjects") or []
    rows = [i for i, s in enumerate(subs) if _norm(row) in _norm(s.get("label"))] or ([0] if len(subs) == 1 else [])
    for ri in rows:
        cells = (data.get("cells") or [])[ri] if ri < len(data.get("cells") or []) else {}
        for c in sorted(cols, key=lambda i: len(i.get("label") or "")):  # 가장 짧은 이름(정확히 맞는 열) 먼저
            cell = cells.get(c["key"]) or {}
            if cell.get("type") == "number" and cell.get("raw") is not None:
                got = parse_number(str(cell["raw"]))
                if got:
                    return got[0]
            if cell.get("value") is not None:
                try:
                    return float(cell["value"])
                except (TypeError, ValueError):
                    continue
    return None


def _same(got: Optional[float], expect: float, tol: Optional[float]) -> bool:
    if got is None:
        return False
    t = tol if tol is not None else max(abs(expect) * 0.001, 0.5)
    return abs(got - expect) <= t or abs(got * 100 - expect) <= t  # 비율은 0.0847 · 8.47 둘 다


def _workspace_of(user: User) -> Optional[str]:
    with Session(engine) as s:
        m = s.exec(select(Membership).where(Membership.user_id == user.id)).first()
        return m.workspace_id if m else None


async def run(user: User) -> Dict[str, Any]:
    from app.assumptions.judge import judge_numeric
    from app.search_studio import query

    ws_id = _workspace_of(user)
    cases: List[Dict[str, Any]] = []
    qa_ok = qa_n = 0
    for c in _load("qa_set.json"):
        qa_n += 1
        got, err, tid = None, "", None
        try:
            res = await query(ws_id, user, c["q"])
            tid = res.get("tableId")
            if tid:
                with Session(engine) as s:
                    row = s.get(ResearchTable, tid)
                    got = _cell_value(row.data or {}, c.get("row") or "", c.get("column") or "") if row else None
        except Exception as e:  # noqa: BLE001 — 한 문항 실패는 '틀림'으로
            err = str(e)[:120]
        finally:
            if tid:
                with Session(engine) as s:
                    for r in s.exec(select(ResearchTable).where(ResearchTable.id == tid)).all():
                        s.delete(r)
                    s.commit()
        ok = _same(got, float(c["expect"]), c.get("tol"))
        qa_ok += ok
        cases.append({"id": c["id"], "kind": "qa", "q": c["q"], "expect": c["expect"], "got": got, "ok": ok, "error": err})
    as_ok = as_n = 0
    with Session(engine) as s:
        doc_ids = scope_ids(Repo(s).workspace(ws_id)) if ws_id else []
    for c in _load("assumption_set.json"):
        as_n += 1
        res = judge_numeric(c["condition"], c["target"], doc_ids, c.get("asOf"))
        ok = res["result"] == c["expect"]
        as_ok += ok
        cases.append({"id": c["id"], "kind": "assumption", "q": f"{c['target'].get('name')} · {c['condition'].get('ledgerMetric')} {c['condition'].get('op')} {c['condition'].get('threshold')} · 기준일 {c.get('asOf') or '지금'}",
                      "expect": c["expect"], "got": res["result"], "ok": ok, "value": (res.get("value") or {}).get("display")})
    out = {"at": now_iso(), "by": user.id, "workspaceId": ws_id, "qa": {"correct": qa_ok, "total": qa_n}, "assumption": {"correct": as_ok, "total": as_n}, "cases": cases}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "eval_last.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(OUT / "evals.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({k: out[k] for k in ("at", "by", "qa", "assumption")}, ensure_ascii=False) + "\n")
    from app.quality import kpi

    kpi._cache.clear()
    return out


def history(limit: int = 20) -> List[Dict[str, Any]]:
    p = OUT / "evals.jsonl"
    if not p.exists():
        return []
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    return rows[-limit:][::-1]


__all__ = ["run", "history", "Path"]
