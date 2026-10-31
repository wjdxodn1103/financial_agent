"""심의 준비(가상 투자위원) — 새 안건의 가정을 과거 문서의 가정·판정과 맞추고, 과거 회의록·자료에서 반대 논거·미해결 질문을 원문 인용과 함께 낸다.
- 비슷한 과거 가정 = 코드(같은 대상 이름·티커, 또는 낱말 겹침) + 그 가정의 최근 판정(미충족·반박 먼저).
- 반대 논거·미해결 질문 = LLM(문단 번호 + 글자 그대로 인용 — 원문에 없으면 버린다). 추가로 물을 질문은 근거 문단이 없어도 낸다.
판단(승인·반대)은 하지 않는다. 마지막 결과는 문서마다 남긴다(DATA_DIR/committee/<docRef>.json).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Set

from fastapi import HTTPException
from sqlmodel import Session, select

from app.anchors import pin
from app.auth import require_member
from app.config import DATA_DIR
from app.db import Assumption, Repo, ReportSession, User, engine, scope_ids
from app.docs.store import _read_json, doc_label, load_meta, search_docs, write_json_atomic
from app.ids import now_iso
from app.llm.base import ChatParams

log = logging.getLogger(__name__)

DIR = DATA_DIR / "committee"
BAD = ("not_met", "refute")

PROMPT = """너는 투자위원회 위원이다. 새 안건이 기댄 가정들과 과거 자료(회의록·보고서) 문단을 보고, 심의 때 짚을 것을 JSON 하나로만 낸다(설명 없이).
{"items": [{"kind": "counter|open|ask", "a": 가정 번호(전체에 대한 것이면 0), "text": "한두 문장", "s": 문단 번호(없으면 0), "quote": "그 문단에서 글자 그대로 옮긴 근거 문장"}]}
- counter = 반대 논거(가정을 흔드는 사실·발언), open = 과거에 나왔지만 아직 답이 없는 질문 — 둘 다 문단 근거가 꼭 있어야 한다.
- ask = 이번 심의에서 추가로 물을 질문(근거 문단이 없으면 s=0, quote 빈칸).
- 문단에 없는 숫자·사실을 만들지 않는다. 찬반 결론은 내지 않는다. 최대 8개."""


def _toks(s: str) -> Set[str]:
    return {t for t in re.findall(r"[A-Za-z]{3,}|[가-힣]{2,}", (s or "").lower()) if t not in ("것이다", "있다", "이다", "the", "and")}


def _norm(s: Any) -> str:
    return re.sub(r"[\s·\-_()]+", "", str(s or "")).lower()


def _same_target(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    na, nb = _norm(a.get("name")), _norm(b.get("name"))
    ta, tb = _norm(a.get("ticker")), _norm(b.get("ticker"))
    return bool((ta and ta == tb) or (na and nb and (na[:10] in nb or nb[:10] in na)))


def _title(s: Session, a: Assumption) -> str:
    if a.doc_kind == "report":
        r = s.get(ReportSession, a.doc_ref)
        return (r.title if r else "") or "문서"
    return doc_label(load_meta(a.doc_ref), a.doc_ref)


async def prepare(workspace_id: str, user: User, doc_kind: str, doc_ref: str) -> Dict[str, Any]:
    from app.assumptions import service as asm
    from app.llm.client import ReportLlm

    with Session(engine) as s:
        require_member(s, workspace_id, user)
        mine = s.exec(select(Assumption).where(Assumption.workspace_id == workspace_id, Assumption.doc_ref == doc_ref, Assumption.status != "dismissed")).all()
    if not mine:
        await asm.run_extract(workspace_id, user, doc_kind, doc_ref)  # 편집자가 아니면 여기서 403
        with Session(engine) as s:
            mine = s.exec(select(Assumption).where(Assumption.workspace_id == workspace_id, Assumption.doc_ref == doc_ref, Assumption.status != "dismissed")).all()
    if not mine:
        raise HTTPException(400, "이 문서에서 가정 문장을 찾지 못했습니다.")
    mine = mine[:6]

    # 1) 비슷한 과거 가정 — 코드
    with Session(engine) as s:
        others = s.exec(select(Assumption).where(Assumption.workspace_id == workspace_id, Assumption.doc_ref != doc_ref, Assumption.status != "dismissed")).all()
        past: List[Dict[str, Any]] = []
        for p in others:
            score = max((len(_toks(p.quote) & _toks(m.quote)) / max(1, len(_toks(p.quote) | _toks(m.quote))) for m in mine), default=0)
            if not (any(_same_target(p.target or {}, m.target or {}) for m in mine) or score >= 0.2):
                continue
            lt = p.latest or {}
            past.append({"id": p.id, "quote": p.quote, "docKind": p.doc_kind, "docRef": p.doc_ref, "docTitle": _title(s, p), "conditionText": asm.condition_text(p),
                         "result": lt.get("result"), "resultKo": asm.RESULT_KO.get(lt.get("result") or "", ""), "value": (lt.get("value") or {}).get("display"),
                         "anchors": lt.get("anchors") or [], "score": round(score, 2)})
        past.sort(key=lambda x: (x["result"] not in BAD, -x["score"]))
        past = past[:6]
        doc_ids = [d for d in scope_ids(Repo(s).workspace(workspace_id)) if d != doc_ref]

    # 2) 과거 자료 문단 — 가정 문장·대상 이름으로 찾는다(이 문서 자신은 뺀다)
    hits: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    names = " ".join(dict.fromkeys((m.target or {}).get("name") or "" for m in mine))
    for q in [*(m.quote for m in mine[:4]), f"{names} 리스크 우려 반대", f"{names} 질문 확인 필요"]:
        for h in search_docs(doc_ids, q, k=4, per_doc=2):
            key = f"{h['docId']}#{h['chunk']['id']}"
            if key not in seen:
                seen.add(key)
                hits.append(h)
    hits = hits[:12]
    items: List[Dict[str, Any]] = []
    if hits:
        body_a = "\n".join(f"[{i + 1}] {m.quote}" for i, m in enumerate(mine))
        body_p = "\n\n".join(f"[{i + 1}] ({doc_label(load_meta(h['docId']), h['docId'])}) {(h['chunk'].get('text') or '')[:800]}" for i, h in enumerate(hits))
        raw: List[Dict[str, Any]] = []
        for _ in range(2):  # 빈 답·깨진 JSON 이면 한 번 더
            res = await ReportLlm().complete("chat", ChatParams(messages=[{"role": "user", "content": f"{PROMPT}\n\n## 새 안건의 가정\n{body_a}\n\n## 과거 자료 문단\n{body_p}"}],
                                                                  temperature=0, max_tokens=4000, reasoning_effort="low", timeout_s=180))
            text = getattr(res, "content", "") or ""
            m = re.search(r"\{[\s\S]*\}", text)
            try:
                raw = json.loads(m.group(0)).get("items") or [] if m else []
            except (ValueError, AttributeError):
                raw = []
            if raw:
                break
            log.warning("[committee] %s no items (finish=%s) head=%r", doc_ref, getattr(res, "finish_reason", None), text[:300])
        for it in raw or []:
            kind = it.get("kind") if it.get("kind") in ("counter", "open", "ask") else None
            text = str(it.get("text") or "").strip()
            if not kind or not text:
                continue
            try:
                n = int(it.get("s") or 0)
            except (TypeError, ValueError):
                n = 0
            q = str(it.get("quote") or "").strip()
            anchor = None
            if 1 <= n <= len(hits) and q and re.sub(r"\s+", "", q) in re.sub(r"\s+", "", hits[n - 1]["chunk"].get("text") or ""):
                h = hits[n - 1]
                anchor = pin(h["docId"], h["chunk"]["id"], quote=q)
            if kind in ("counter", "open") and not anchor:
                continue  # 근거를 원문에서 확인하지 못한 반대 논거·미해결 질문은 버린다
            try:
                ai = int(it.get("a") or 0)
            except (TypeError, ValueError):
                ai = 0
            items.append({"kind": kind, "kindKo": {"counter": "반대 논거", "open": "미해결 질문", "ask": "추가 질문"}[kind], "text": text[:400],
                          "assumptionId": mine[ai - 1].id if 1 <= ai <= len(mine) else None, "quote": q if anchor else "", "anchor": anchor,
                          "source": doc_label(load_meta(anchor["docId"]), anchor["docId"]) if anchor else ""})
    items.sort(key=lambda x: ("counter", "open", "ask").index(x["kind"]))
    out = {"docRef": doc_ref, "at": now_iso(), "by": user.id, "assumptions": [{"id": m.id, "quote": m.quote} for m in mine], "past": past, "items": items[:10]}
    DIR.mkdir(parents=True, exist_ok=True)
    write_json_atomic(DIR / f"{re.sub(r'[^A-Za-z0-9_-]', '', doc_ref)}.json", out)
    return out


def last(session: Session, workspace_id: str, user: User, doc_ref: str) -> Dict[str, Any] | None:
    require_member(session, workspace_id, user)
    got = _read_json(DIR / f"{re.sub(r'[^A-Za-z0-9_-]', '', doc_ref)}.json")
    return got if isinstance(got, dict) else None
