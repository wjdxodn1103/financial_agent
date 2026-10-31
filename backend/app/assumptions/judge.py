"""가정 판정 — 숫자 가정은 코드가(원장 수치 + 기간 규칙 + 조건), 정성 가정은 LLM 이(새 자료 문단 인용 필수 — 인용이 원문에 없으면 판단 보류).

기간 규칙: latest_q_yoy(최근 분기 전년 같은 분기 대비 증가율) · latest_q(최근 분기 값) · latest_fy(최근 연도 값) · latest_fy_yoy(연간 증가율).
as_of 가 있으면 그날까지 나온 자료만 본다(날짜 지정 재현 — '그때는 충족, 지금은 미충족'을 보일 수 있다).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.anchors import pin as make_anchor  # 판정 근거도 색인에 고정(원문이 바뀌어도 다시 찾는다)
from app.docs.asof import doc_date, docs_as_of
from app.docs.store import load_meta, search_docs
from app.ledger.figures import load_figures, metric_key
from app.ledger.numbers import parse_unit
from app.llm.base import ChatParams

log = logging.getLogger(__name__)
OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b, "==": lambda a, b: abs(a - b) < 1e-9}
Q_RX = re.compile(r"^(\d{4})Q([1-4])$")
Y_RX = re.compile(r"^(\d{4})$")


def _norm(s: Any) -> str:
    return re.sub(r"[\s·\-_()]+", "", str(s or "")).lower()


def entity_docs(target: Dict[str, Any], doc_ids: List[str]) -> List[str]:
    """대상(회사·자산)을 다룬 자료 — 카드의 회사·발행처·제목에 이름·티커가 든 것."""
    name, ticker = _norm(target.get("name")), _norm(target.get("ticker"))
    out = []
    for d in doc_ids:
        c = (load_meta(d) or {}).get("card") or {}
        hay = _norm(f"{c.get('company') or ''}{c.get('issuer') or ''}{c.get('title') or ''}")
        if (name and name[:12] in hay) or (ticker and ticker in hay):
            out.append(d)
    return out


def ledger_metrics(doc_ids: List[str]) -> List[str]:
    seen: Dict[str, str] = {}
    for d in doc_ids:
        for f in load_figures(d):
            seen.setdefault(metric_key(f["metric"]), f["metric"])
    return list(seen.values())[:80]


def _pick(doc_ids: List[str], metric: str) -> Dict[str, Tuple[Dict[str, Any], str]]:
    """기간 → (figure, docId) — 같은 기간이 여러 자료에 있으면 가장 늦게 나온 자료의 값."""
    mk = metric_key(metric)
    best: Dict[str, Tuple[Dict[str, Any], str, str]] = {}
    for d in doc_ids:
        dd = (doc_date(load_meta(d)) or "").__str__()
        for f in load_figures(d):
            if f.get("percent") or (metric_key(f["metric"]) != mk and _norm(f["metric"]) != _norm(metric)):
                continue
            pk = f.get("periodKey") or ""
            if pk not in best or dd > best[pk][2]:
                best[pk] = (f, d, dd)
    return {k: (v[0], v[1]) for k, v in best.items()}


def _anchor(f: Dict[str, Any], d: str) -> Optional[Dict[str, Any]]:
    snap = (load_meta(d) or {}).get("snapshot") or {}
    ext = {k: snap.get(k) for k in ("accession", "form", "filed", "url", "publishedAt", "connector") if snap.get(k)}
    return make_anchor(d, f["chunk"], cell=f.get("cell"), figure=f, ext=ext or None)


def judge_numeric(cond: Dict[str, Any], target: Dict[str, Any], doc_ids: List[str], as_of: Optional[str] = None) -> Dict[str, Any]:
    docs = entity_docs(target, docs_as_of(doc_ids, as_of))
    metric = cond.get("ledgerMetric") or cond.get("metric") or ""
    rule = cond.get("period") or "latest_q_yoy"
    by = _pick(docs, metric)
    if not by:
        return {"result": "no_data", "value": {"display": "자료에서 지표를 찾지 못함", "metric": metric}, "anchors": []}
    qk = sorted((k for k in by if Q_RX.match(k)), reverse=True)
    yk = sorted((k for k in by if Y_RX.match(k)), reverse=True)
    keys = qk if rule.startswith("latest_q") else yk
    if not keys and (qk or yk):  # 분기 자료뿐이면 분기로, 연간 자료뿐이면 연간으로(기간 규칙만 바꾸고 결과에 남긴다)
        keys = qk or yk
        rule = ("latest_q" if qk else "latest_fy") + ("_yoy" if rule.endswith("_yoy") else "")
    if not keys:
        return {"result": "no_data", "value": {"display": f"{metric} — 맞는 기간이 없음"}, "anchors": []}
    cur_k = keys[0]
    cur, cur_d = by[cur_k]
    anchors = [a for a in [_anchor(cur, cur_d)] if a]
    if rule.endswith("_yoy"):
        m = Q_RX.match(cur_k)
        prev_k = f"{int(m.group(1)) - 1}Q{m.group(2)}" if m else str(int(cur_k) - 1)
        if prev_k not in by:
            return {"result": "no_data", "value": {"display": f"{cur_k} 값만 있고 {prev_k} 값이 없음", "period": cur_k}, "anchors": anchors}
        prev, prev_d = by[prev_k]
        if not prev.get("abs"):
            return {"result": "no_data", "value": {"display": "전년 값이 0"}, "anchors": anchors}
        val = (cur["abs"] / prev["abs"] - 1) * 100
        anchors += [a for a in [_anchor(prev, prev_d)] if a]
        display = f"{val:+.1f}% ({cur_k} {cur.get('display') or cur.get('raw')} / {prev_k} {prev.get('display') or prev.get('raw')})"
        value = {"value": round(val, 2), "unit": "%", "display": display, "period": cur_k, "base": prev_k, "rule": rule}
    else:
        # 기준값 단위(억원·USD mn)를 알면 배율 적용 값끼리, 모르면 표에 적힌 값끼리
        u = parse_unit(cond.get("unit"))
        val = cur["abs"] if u.scale != 1.0 and cur.get("abs") is not None else cur["value"]
        display = f"{cur.get('display') or cur.get('raw')} ({cur_k})"
        value = {"value": val, "unit": cond.get("unit") or "", "display": display, "period": cur_k, "rule": rule, "scale": u.scale}
    try:
        th = float(cond.get("threshold")) * (value.get("scale") or 1.0)
    except (TypeError, ValueError):
        return {"result": "no_data", "value": {**value, "note": "조건 기준값이 없음"}, "anchors": anchors}
    op = OPS.get(str(cond.get("op") or ">="), OPS[">="])
    return {"result": "met" if op(value["value"], th) else "not_met", "value": value, "anchors": anchors}


PORTFOLIO_RX = re.compile(r"비중|weight", re.I)


def judge_portfolio(cond: Dict[str, Any], target: Dict[str, Any], doc_ids: List[str], as_of: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """포트폴리오 비중 조건(단일 발행자·비상장·자산군 비중) — 보유 내역 표로 코드가 더한다(가이드라인 점검과 같은 계산). 비중 조건이 아니면 None."""
    from app.assistants.guideline import _holdings, portfolio_doc

    metric = str(cond.get("metric") or "")
    if not PORTFOLIO_RX.search(metric):
        return None
    port = portfolio_doc(docs_as_of(doc_ids, as_of))
    if not port:
        return {"result": "no_data", "value": {"display": "포트폴리오 보유 내역 자료가 없음", "metric": metric}, "anchors": []}
    chunk, hold, cols = _holdings(port)
    name = _norm(target.get("name"))
    mine = [h for h in hold if name and (name[:10] in _norm(h["issuer"]) or name[:10] in _norm(h["name"]))]
    cls = next((c for c in ("주식", "채권", "대체") if c in metric), "")
    if "비상장" in metric or "unlisted" in metric.lower():
        rows, label = [h for h in hold if "비상장" in h["listed"]], "비상장 합"
    elif "발행" in metric or "issuer" in metric.lower() or (mine and not cls):  # 'Helios 비중'처럼 대상 이름 + 비중도 발행자 비중
        rows, label = mine, target.get("name") or ""
        if not rows:  # 대상이 보유 내역에 없으면 가장 큰 발행자
            by: Dict[str, List[Dict[str, Any]]] = {}
            for h in hold:
                if h["issuer"] and h["issuer"] not in ("다수", "-", "—"):
                    by.setdefault(h["issuer"], []).append(h)
            label, rows = max(by.items(), key=lambda kv: sum(x["weight"] for x in kv[1]), default=("", []))
    else:
        rows, label = [h for h in hold if cls and cls in h["class"]], f"{cls} 합"
    if not rows:
        return {"result": "no_data", "value": {"display": f"보유 내역에서 '{metric}'을 셀 수 없음"}, "anchors": []}
    val = round(sum(h["weight"] for h in rows), 4)
    anchors = [a for a in (make_anchor(port, chunk, cell=[h["row"], cols["weight"]]) for h in rows[:12]) if a]
    pm = load_meta(port) or {}
    value = {"value": val, "unit": "%", "display": f"{val:g}% ({label} · 보유 내역 {doc_date(pm) or ''})", "period": str(doc_date(pm) or ""), "rule": "portfolio"}
    try:
        th = float(cond.get("threshold"))
    except (TypeError, ValueError):
        return {"result": "no_data", "value": {**value, "note": "조건 기준값이 없음"}, "anchors": anchors}
    op = OPS.get(str(cond.get("op") or ">="), OPS[">="])
    return {"result": "met" if op(val, th) else "not_met", "value": value, "anchors": anchors}


QUAL_PROMPT = """투자 가정 하나와 새 자료 문단들이 있다. 이 문단들이 가정을 지지하는지 반박하는지 판정해 JSON 하나로만 답한다(설명 없이).
{"result": "support|refute|unrelated|hold", "s": 근거 문단 번호(정수, 없으면 0), "quote": "그 문단에서 그대로 옮긴 근거 문장(바꾸지 말 것)"}
규칙: 문단에 분명한 근거가 없으면 hold. 근거 문장은 문단 글자 그대로."""


async def judge_qualitative(quote: str, target: Dict[str, Any], doc_ids: List[str], llm: Any, as_of: Optional[str] = None, exclude: Optional[List[str]] = None) -> Dict[str, Any]:
    pool = [d for d in docs_as_of(doc_ids, as_of) if d not in set(exclude or [])]  # 가정이 적힌 문서 자신은 근거가 아니다
    docs = entity_docs(target, pool) or pool
    if not docs:
        return {"result": "hold", "value": {"display": "볼 자료가 없음"}, "anchors": []}
    hits = search_docs(docs, quote, k=4, per_doc=2)
    if not hits:
        return {"result": "hold", "value": {"display": "관련 문단이 없음"}, "anchors": []}
    paras = "\n\n".join(f"[{i + 1}] {(h['chunk'].get('text') or '')[:900]}" for i, h in enumerate(hits))
    res = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": f"{QUAL_PROMPT}\n\n## 가정\n{quote}\n\n## 새 자료 문단\n{paras}"}], temperature=0, max_tokens=1500, reasoning_effort="low", timeout_s=120))
    m = re.search(r"\{[\s\S]*\}", getattr(res, "content", "") or "")
    try:
        got = json.loads(m.group(0)) if m else {}
    except ValueError:
        got = {}
    result = got.get("result") if got.get("result") in ("support", "refute", "unrelated", "hold") else "hold"
    n = int(got.get("s") or 0) if str(got.get("s") or "0").isdigit() else 0
    q = str(got.get("quote") or "").strip()
    if result in ("support", "refute"):
        if not (1 <= n <= len(hits)) or not q or re.sub(r"\s+", "", q) not in re.sub(r"\s+", "", hits[n - 1]["chunk"].get("text") or ""):
            return {"result": "hold", "value": {"display": "근거 문장을 원문에서 확인하지 못해 보류"}, "anchors": []}
        h = hits[n - 1]
        a = make_anchor(h["docId"], h["chunk"]["id"], quote=q)
        return {"result": result, "value": {"display": q[:160]}, "anchors": [a] if a else [], "quote": q}
    return {"result": result, "value": {"display": "관련 근거 없음" if result == "unrelated" else "판단 보류"}, "anchors": []}


async def map_metric(llm: Any, wanted: str, candidates: List[str]) -> Optional[str]:
    """가정의 지표 이름(한국어 등) → 원장 지표 이름 하나(목록에서). 이름이 같으면 LLM 없이."""
    if not candidates:
        return None
    for c in candidates:
        if metric_key(c) == metric_key(wanted) or _norm(c) == _norm(wanted):
            return c
    # 흔한 한국어 지표 → 영문 원장 이름(공시 엑셀은 영문) — 낱말이 모두 든 후보 중 가장 짧은 것
    w = _norm(wanted)
    hints = []
    for ko, en in KO_EN:
        if ko in w:
            hints.append(en)
            w = w.replace(ko, "")
    if hints:
        hit = sorted((c for c in candidates if all(h in c.lower() for h in hints)), key=len)
        if hit:
            return hit[0]
    res = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": f"지표 '{wanted}' 와 같은 뜻의 원장 지표 이름을 아래 목록에서 하나 골라 그 이름만 답한다(없으면 '없음').\n" + "\n".join(f"- {c}" for c in candidates)}],
                                                 temperature=0, max_tokens=1500, reasoning_effort="low", timeout_s=60))
    pick = (getattr(res, "content", "") or "").strip().strip("-`'\"").strip()
    return next((c for c in candidates if c == pick or _norm(c) == _norm(pick) or (len(pick) > 4 and _norm(pick) in _norm(c))), None)


# (한국어 낱말, 영문 원장 이름에 든 낱말) — 긴 것 먼저(매출총이익이 매출보다 먼저)
KO_EN = [("매출총이익", "gross profit"), ("데이터센터", "data center"), ("영업이익", "operating income"), ("주당순이익", "eps"), ("순이익", "net income"), ("총매출", "total revenue"),
         ("매출", "revenue"), ("영업현금흐름", "operating activities"), ("자산총계", "total assets"), ("부채총계", "total liabilities")]
