"""하우스뷰 흐름 — 하우스뷰 문서(이름에 '하우스뷰'·'house view')마다 자산군별 입장(긍정·중립·부정)과 그 문장을 뽑아 분기 줄로 늘어놓는다.
'자산: 긍정.' 꼴 줄은 코드가 읽고, 아니면 LLM 이 줄 번호·입장·글자 그대로 인용을 낸다(인용이 원문에 없으면 버린다). 문서마다 한 번만(DATA_DIR/houseview/<docId>.json).
워크스페이스 대시보드 위젯 'houseview' — 칸을 누르면 그 문장 원문, 아래에는 하우스뷰 문서의 감시 가정과 지금 판정.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.anchors import pin
from app.config import DATA_DIR
from app.db import Assumption, Repo, User, engine, scope_ids
from app.docs.asof import doc_date
from app.docs.store import _read_json, doc_label, load_meta, paragraphs, write_json_atomic
from app.ids import now_iso
from app.llm.base import ChatParams

log = logging.getLogger(__name__)
DIR = DATA_DIR / "houseview"
STANCE = {"긍정": "positive", "비중 확대": "positive", "확대": "positive", "중립": "neutral", "부정": "negative", "비중 축소": "negative", "축소": "negative",
          "overweight": "positive", "positive": "positive", "neutral": "neutral", "underweight": "negative", "negative": "negative"}
STANCE_KO = {"positive": "긍정", "neutral": "중립", "negative": "부정"}
LINE_RX = re.compile(r"^\s*[-•*]?\s*([^:：\n]{2,30}?)\s*[:：]\s*(긍정|중립|부정|비중 확대|비중 축소|overweight|neutral|underweight)\b", re.I)

PROMPT = """아래는 하우스뷰(자산군별 투자 입장) 문서의 줄들이다(번호 붙음). 자산군마다 입장을 JSON 하나로만 답한다(설명 없이).
{"stances": [{"asset": "자산군 이름", "stance": "positive|neutral|negative", "n": 줄 번호, "quote": "그 줄에서 입장이 드러난 부분을 글자 그대로"}]}
자산군 이름은 가능하면 이 목록의 이름을 쓴다: {names}"""


def is_houseview(doc_id: str) -> bool:
    m = load_meta(doc_id) or {}
    t = f"{doc_label(m, doc_id)} {m.get('fileName') or ''}".lower()
    return "하우스뷰" in t or "house view" in t or "houseview" in t


def period_of(doc_id: str) -> str:
    m = load_meta(doc_id) or {}
    t = f"{doc_label(m, doc_id)} {m.get('fileName') or ''}"
    got = re.search(r"(20\d{2})\s*(?:년\s*([1-4])\s*분기|[Qq]([1-4]))", t)
    if got:
        return f"{got.group(1)}Q{got.group(2) or got.group(3)}"
    d = doc_date(m)
    return f"{d.year}Q{(d.month - 1) // 3 + 1}" if d else ""


def _lines(doc_id: str) -> List[Tuple[str, str]]:
    out = []
    for p in paragraphs(doc_id):
        if p.get("rows"):
            out += [(p["id"], " | ".join(str(x) for x in r)) for r in p["rows"]]
            continue
        out += [(p["id"], s.strip()) for s in re.split(r"\n+|\s+(?=[-•*]\s+\S)", p.get("text") or "") if s.strip()]  # 목록이 한 문단으로 붙은 경우도 줄로
    return out[:300]


def _by_code(doc_id: str) -> List[Dict[str, Any]]:
    out = []
    for chunk, line in _lines(doc_id):
        m = LINE_RX.match(line)
        if m:
            out.append({"asset": m.group(1).strip(), "stance": STANCE.get(m.group(2).lower(), STANCE.get(m.group(2), "neutral")), "chunk": chunk, "quote": line.lstrip("-•* ").strip()[:200]})
    return out


async def _by_llm(doc_id: str, names: List[str]) -> List[Dict[str, Any]]:
    from app.llm.client import ReportLlm

    lines = _lines(doc_id)
    body = "\n".join(f"[{i + 1}] {t}" for i, (_c, t) in enumerate(lines))[:12000]
    res = await ReportLlm().complete("chat", ChatParams(messages=[{"role": "user", "content": PROMPT.replace("{names}", ", ".join(names) or "(없음)") + f"\n\n## 줄\n{body}"}],
                                                          temperature=0, max_tokens=2500, reasoning_effort="low", timeout_s=180))
    m = re.search(r"\{[\s\S]*\}", getattr(res, "content", "") or "")
    try:
        raw = json.loads(m.group(0)).get("stances") if m else []
    except (ValueError, AttributeError):
        raw = []
    out = []
    for s in raw or []:
        try:
            n = int(s.get("n"))
        except (TypeError, ValueError):
            continue
        q = str(s.get("quote") or "").strip()
        if not (1 <= n <= len(lines)) or not q or re.sub(r"\s+", "", q) not in re.sub(r"\s+", "", lines[n - 1][1]):
            continue
        if s.get("stance") in STANCE_KO:
            out.append({"asset": str(s.get("asset") or "").strip()[:30], "stance": s["stance"], "chunk": lines[n - 1][0], "quote": q[:200]})
    return out


def _cached(doc_id: str) -> Optional[Dict[str, Any]]:
    got = _read_json(DIR / f"{doc_id}.json")
    meta = load_meta(doc_id) or {}
    return got if isinstance(got, dict) and got.get("stamp") == meta.get("chunkCount") else None


async def extract(doc_id: str, names: List[str]) -> Dict[str, Any]:
    stances = _by_code(doc_id)
    how = "code"
    if len(stances) < 3:
        stances, how = await _by_llm(doc_id, names), "llm"
    for s in stances:
        s["anchor"] = pin(doc_id, s["chunk"], quote=s["quote"])
    out = {"stamp": (load_meta(doc_id) or {}).get("chunkCount"), "docId": doc_id, "period": period_of(doc_id), "stances": stances, "how": how, "at": now_iso()}
    DIR.mkdir(parents=True, exist_ok=True)
    write_json_atomic(DIR / f"{doc_id}.json", out)
    return out


async def _extract_pending(doc_ids: List[str]) -> None:
    names: List[str] = []
    for d in doc_ids:
        try:
            got = await extract(d, names)
            names += [s["asset"] for s in got["stances"] if s["asset"] not in names]
        except Exception:  # noqa: BLE001
            log.exception("houseview extract failed: %s", d)


def widget(workspace_id: str, user: User) -> Dict[str, Any]:
    """→ {periods, rows:[{asset, cells:{period:{stance, stanceKo, quote, anchor, changed}}}], pending, assumptions}"""
    from app import scheduler
    from app.assumptions.service import RESULT_KO, condition_text

    with Session(engine) as s:
        docs = [d for d in scope_ids(Repo(s).workspace(workspace_id)) if is_houseview(d)]
    done, todo = [], []
    for d in docs:
        c = _cached(d)
        if c:
            done.append(c)
        else:
            stances = _by_code(d)  # 코드로 읽히면 바로(LLM 없이)
            if len(stances) >= 3:
                for x in stances:
                    x["anchor"] = pin(d, x["chunk"], quote=x["quote"])
                c = {"stamp": (load_meta(d) or {}).get("chunkCount"), "docId": d, "period": period_of(d), "stances": stances, "how": "code", "at": now_iso()}
                DIR.mkdir(parents=True, exist_ok=True)
                write_json_atomic(DIR / f"{d}.json", c)
                done.append(c)
            else:
                todo.append(d)
    if todo:
        scheduler.spawn("houseview", _extract_pending(todo), workspace_id)
    # 같은 분기 문서가 여럿이면 늦은 것
    by_p: Dict[str, Dict[str, Any]] = {}
    for c in sorted(done, key=lambda c: str(doc_date(load_meta(c["docId"])) or "")):
        if c["period"]:
            by_p[c["period"]] = c
    periods = sorted(by_p)[-6:]
    order: List[str] = []
    for p in reversed(periods):
        for x in by_p[p]["stances"]:
            if x["asset"] not in order:
                order.append(x["asset"])
    rows = []
    for asset in order:
        cells: Dict[str, Any] = {}
        prev = None
        for p in periods:
            x = next((y for y in by_p[p]["stances"] if y["asset"] == asset), None)
            if x:
                cells[p] = {"stance": x["stance"], "stanceKo": STANCE_KO[x["stance"]], "quote": x["quote"], "anchor": x.get("anchor"), "docId": by_p[p]["docId"], "chunk": x["chunk"],
                            "changed": prev is not None and prev != x["stance"]}
                prev = x["stance"]
        rows.append({"asset": asset, "cells": cells})
    hv_ids = {c["docId"] for c in done}
    with Session(engine) as s:
        asm = s.exec(select(Assumption).where(Assumption.workspace_id == workspace_id, Assumption.watch == True)).all()  # noqa: E712
        items = [{"id": a.id, "quote": a.quote[:140], "docRef": a.doc_ref, "period": period_of(a.doc_ref), "condition": condition_text(a),
                  "result": RESULT_KO.get((a.latest or {}).get("result") or "", None), "value": ((a.latest or {}).get("value") or {}).get("display")} for a in asm if a.doc_ref in hv_ids]
    return {"periods": periods, "rows": rows, "pending": len(todo), "assumptions": items, "docs": {p: {"docId": by_p[p]["docId"], "title": doc_label(load_meta(by_p[p]["docId"]), by_p[p]["docId"])} for p in periods}}
