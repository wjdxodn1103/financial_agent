"""가이드라인 점검 — 사내 투자정책서의 한도 문장을 조건으로 바꾸고(LLM 은 줄 번호·인용·조건만, 인용은 코드가 원문 대조),
포트폴리오 보유 내역 표로 코드가 계산해 대조한다. 판정 낱말은 지킴·넘음(목표 비중은 '목표', 비중으로 셀 수 없는 것은 '계산 못 함').

계산하는 지표: asset_class(자산군 비중 합) · issuer(단일 발행자 비중 — 발행자 '다수'·빈칸은 제외) · unlisted(비상장 비중 합).
정책서 조건은 문서마다 한 번만 뽑아 둔다(DATA_DIR/guideline/rules_<docId>.json). 마지막 점검 결과는 워크스페이스마다 남긴다.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlmodel import Session

from app.anchors import pin
from app.auth import require_member
from app.config import DATA_DIR
from app.db import Repo, User, engine, scope_ids
from app.docs.asof import doc_date
from app.docs.store import _read_json, doc_label, load_meta, paragraphs, write_json_atomic
from app.ledger.numbers import parse_number
from app.llm.base import ChatParams
from app.ids import now_iso

log = logging.getLogger(__name__)
DIR = DATA_DIR / "guideline"
OPS = {"<=": lambda a, b: a <= b + 1e-9, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b - 1e-9, ">": lambda a, b: a > b}
OP_KO = {"<=": "이하", "<": "미만", ">=": "이상", ">": "초과", "==": "목표"}
SKIP_ISSUER = {"", "-", "—", "다수", "복수", "various", "n/a"}

PROMPT = """아래는 사내 투자정책서의 줄들이다(번호 붙음). 포트폴리오 보유 비중으로 확인할 수 있는 한도·범위·목표를 골라 JSON 하나로만 답한다(설명 없이).
{"rules": [{"n": 줄 번호, "quote": "그 줄에서 글자 그대로", "metric": "asset_class|issuer|unlisted|other", "scope": "자산군 이름(asset_class 만, 예: 주식·채권·대체)", "op": "<=|>=|<|>|==", "threshold": 숫자(%), "kind": "limit|target"}]}
규칙:
- 허용 하한·상한은 규칙 두 개로 나눈다(>= 하한, <= 상한). 목표 비중은 kind=target, op ==.
- 단일 발행자 한도는 metric=issuer, 비상장 자산 합계 한도는 metric=unlisted.
- 비중으로 셀 수 없는 것(추적오차·승인 절차·보고 기한)도 한도라면 metric=other 로 넣는다(threshold 는 있으면).
- quote 는 줄 글자를 바꾸지 않는다."""


def _norm(s: Any) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def _lines(doc_id: str) -> List[Tuple[str, str, Optional[List[int]]]]:
    """정책서 → [(chunk, 줄 글자, 표면 행 번호)] — 문장과 표 행을 한 줄씩."""
    out: List[Tuple[str, str, Optional[List[int]]]] = []
    for p in paragraphs(doc_id):
        rows = p.get("rows") or []
        if rows:
            for ri, r in enumerate(rows):
                t = " | ".join(str(x) for x in r if str(x).strip())
                if t:
                    out.append((p["id"], t, [ri, len(r) - 1]))
            continue
        for s in re.split(r"(?<=[.!?。])\s+|\n+", p.get("text") or ""):
            s = s.strip(" -•")
            if len(s) >= 6:
                out.append((p["id"], s, None))
    return out[:300]


def _label(d: str) -> str:
    m = load_meta(d) or {}
    return f"{doc_label(m, d)} {m.get('fileName') or ''}"


def _latest(cands: List[str]) -> Optional[str]:
    return max(cands, key=lambda d: str(doc_date(load_meta(d)) or ""), default=None)


def portfolio_doc(doc_ids: List[str]) -> Optional[str]:
    """보유 내역 자료 — 이름에 '포트폴리오'가 있고 머리에 '비중'이 있는 표. 여럿이면 가장 늦은 것(가정 판정도 같이 쓴다)."""
    return _latest([d for d in doc_ids if "포트폴리오" in _label(d) and any(_holdings_table(p) for p in paragraphs(d))])


def _find_docs(session: Session, workspace_id: str) -> Tuple[Optional[str], Optional[str]]:
    """(정책서, 포트폴리오) — 이름으로 찾고, 여럿이면 가장 늦은 자료."""
    ids = scope_ids(Repo(session).workspace(workspace_id))
    policy = _latest([d for d in ids if "투자정책" in _label(d) or "investment policy" in _label(d).lower()])
    return policy, portfolio_doc(ids)


def _holdings_table(p: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """보유 내역 표의 열 자리 — 머리 행에 '비중'이 있고 자산군·발행자·상장 여부 중 하나가 있으면."""
    rows = p.get("rows") or []
    for hi, r in enumerate(rows[:4]):
        head = [str(x).strip() for x in r]
        cols: Dict[str, int] = {"header": hi}
        for i, h in enumerate(head):
            if "비중" in h or h.lower() in ("weight", "weight (%)"):
                cols["weight"] = i
            elif "자산군" in h or "asset class" in h.lower():
                cols["class"] = i
            elif "발행" in h or "issuer" in h.lower():
                cols["issuer"] = i
            elif "상장" in h or "listed" in h.lower():
                cols["listed"] = i
        if "weight" in cols and len(cols) >= 3:
            return cols
    return None


async def _rules(llm: Any, policy: str) -> List[Dict[str, Any]]:
    meta = load_meta(policy) or {}
    cache = DIR / f"rules_{policy}.json"
    got = _read_json(cache)
    if isinstance(got, dict) and got.get("stamp") == meta.get("chunkCount"):
        return got.get("rules") or []
    lines = _lines(policy)
    body = "\n".join(f"[{i + 1}] {t}" for i, (_c, t, _cell) in enumerate(lines))[:12000]
    res = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": f"{PROMPT}\n\n## 정책서 줄\n{body}"}], temperature=0, max_tokens=3000, reasoning_effort="low", timeout_s=180))
    m = re.search(r"\{[\s\S]*\}", getattr(res, "content", "") or "")
    try:
        raw = json.loads(m.group(0)).get("rules") if m else []
    except (ValueError, AttributeError):
        raw = []
    rules: List[Dict[str, Any]] = []
    for r in raw or []:
        try:
            n = int(r.get("n"))
        except (TypeError, ValueError):
            continue
        if not (1 <= n <= len(lines)):
            continue
        chunk, text, cell = lines[n - 1]
        q = str(r.get("quote") or "").strip()
        if not q or _norm(q) not in _norm(text):
            continue  # 원문에 그대로 없는 인용은 버린다
        metric = r.get("metric") if r.get("metric") in ("asset_class", "issuer", "unlisted", "other") else "other"
        try:
            th = float(r.get("threshold")) if r.get("threshold") is not None else None
        except (TypeError, ValueError):
            th = None
        rules.append({"chunk": chunk, "cell": cell, "quote": q, "line": text, "metric": metric, "scope": str(r.get("scope") or "").strip(),
                      "op": r.get("op") if r.get("op") in OP_KO else "<=", "threshold": th, "kind": "target" if r.get("kind") == "target" else "limit"})
    DIR.mkdir(parents=True, exist_ok=True)
    write_json_atomic(cache, {"stamp": meta.get("chunkCount"), "rules": rules, "at": now_iso()})
    return rules


def _holdings(port: str) -> Tuple[Optional[str], List[Dict[str, Any]], Dict[str, int]]:
    for p in paragraphs(port):
        cols = _holdings_table(p)
        if not cols:
            continue
        out = []
        for ri, r in enumerate(p["rows"][cols["header"] + 1:], start=cols["header"] + 1):
            got = parse_number(r[cols["weight"]] if cols["weight"] < len(r) else "")
            if got is None:
                continue
            g = lambda k: str(r[cols[k]]).strip() if k in cols and cols[k] < len(r) else ""  # noqa: E731
            out.append({"row": ri, "name": str(r[0]).strip(), "class": g("class"), "issuer": g("issuer"), "listed": g("listed"), "weight": got[0]})
        return p["id"], out, cols
    return None, [], {}


def _judge(rule: Dict[str, Any], hold: List[Dict[str, Any]]) -> Tuple[Optional[float], List[Dict[str, Any]], str]:
    """→ (값, 계산에 쓴 행, 설명)"""
    m = rule["metric"]
    if m == "asset_class":
        sc = rule["scope"]
        rows = [h for h in hold if sc and (sc in h["class"] or h["class"] in sc)]
        return (round(sum(h["weight"] for h in rows), 4) if rows else None), rows, f"{sc} {len(rows)}개 합"
    if m == "unlisted":
        rows = [h for h in hold if "비상장" in h["listed"] or h["listed"].lower() in ("unlisted", "private")]
        return round(sum(h["weight"] for h in rows), 4), rows, f"비상장 {len(rows)}개 합"
    if m == "issuer":
        by: Dict[str, List[Dict[str, Any]]] = {}
        for h in hold:
            if h["issuer"].lower() not in SKIP_ISSUER:
                by.setdefault(h["issuer"], []).append(h)
        if not by:
            return None, [], "발행자 열이 비어 있음"
        top = max(by.items(), key=lambda kv: sum(x["weight"] for x in kv[1]))
        return round(sum(x["weight"] for x in top[1]), 4), top[1], f"가장 큰 발행자 {top[0]}"
    return None, [], "보유 비중으로 계산할 수 없음"


async def check(workspace_id: str, user: User) -> Dict[str, Any]:
    from app.llm.client import ReportLlm

    with Session(engine) as s:
        require_member(s, workspace_id, user)
        policy, port = _find_docs(s, workspace_id)
    if not policy:
        raise HTTPException(404, "투자정책서를 찾지 못했습니다(이름에 '투자정책'이 든 자료).")
    if not port:
        raise HTTPException(404, "포트폴리오 보유 내역을 찾지 못했습니다(이름에 '포트폴리오'가 든 자료, 머리에 '비중').")
    rules = await _rules(ReportLlm(), policy)
    chunk, hold, cols = _holdings(port)
    items = []
    for r in rules:
        val, rows, how = _judge(r, hold)
        pol = pin(policy, r["chunk"], cell=r["cell"], quote=None if r["cell"] else r["quote"])
        anchors = [a for a in (pin(port, chunk, cell=[h["row"], cols["weight"]]) for h in rows[:12]) if a] if chunk else []
        th = r["threshold"]
        if val is None or th is None:
            result = "na"
        elif r["kind"] == "target" or r["op"] == "==":
            result = "target"
        else:
            result = "ok" if OPS[r["op"]](val, th) else "breach"
        limit = f"{th:g}% {OP_KO.get(r['op'], '')}" if th is not None else "—"
        label = {"asset_class": f"{r['scope']} 비중", "issuer": "단일 발행자 비중", "unlisted": "비상장 비중"}.get(r["metric"], "기타")
        items.append({"quote": r["quote"], "policyAnchor": pol, "metric": r["metric"], "label": label, "limit": limit, "kind": r["kind"],
                      "value": val, "valueDisplay": f"{val:g}%" if val is not None else "—", "how": how, "result": result,
                      "resultKo": {"ok": "지킴", "breach": "넘음", "target": "목표", "na": "계산 못 함"}[result],
                      "gap": round(val - th, 2) if val is not None and th is not None else None, "anchors": anchors})
    order = {"breach": 0, "ok": 1, "target": 2, "na": 3}
    items.sort(key=lambda x: order[x["result"]])
    pm = load_meta(port) or {}
    out = {"checkedAt": now_iso(), "by": user.id, "policy": {"docId": policy, "title": doc_label(load_meta(policy), policy)},
           "portfolio": {"docId": port, "title": doc_label(pm, port), "date": str(doc_date(pm) or "")}, "items": items,
           "counts": {k: sum(1 for x in items if x["result"] == k) for k in order}}
    DIR.mkdir(parents=True, exist_ok=True)
    write_json_atomic(DIR / f"ws_{workspace_id}.json", out)
    return out


def last(session: Session, workspace_id: str, user: User) -> Optional[Dict[str, Any]]:
    require_member(session, workspace_id, user)
    got = _read_json(DIR / f"ws_{workspace_id}.json")
    return got if isinstance(got, dict) else None
