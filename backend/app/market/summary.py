"""오늘의 시장 요약 — 숫자는 코드가(사실표), 말은 LLM 이(사실표의 [F#]를 가리키는 문장), 검증은 다시 코드가.

 - 사실표: 시리즈마다 값·기준일·전일/1주/1달 변화·출처(가상 표시), 크게 움직인 순, 금리 곡선, 대체 소스·품질 문제 수
 - LLM: "오늘 요약" 3~5문장 + "AI 판단" 1~2문장 — 숫자를 직접 쓰지 않고 [F번호]로만 가리킨다
 - 검증: 문장에 숫자가 직접 들어 있으면(사실표 밖의 숫자) 그 문장을 뺀다, 없는 F 번호를 가리켜도 뺀다
화면은 [F#] 자리에 사실표 값을 칩으로 보이고, 누르면 그 시리즈 차트(관측값)로 간다.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.db import DataIssue, MarketBrief, engine, iso, utcnow
from app.llm.base import ChatParams
from app.market.service import board

log = logging.getLogger(__name__)
KEY_SERIES = ("us_10y", "us_2y", "krw_usd", "usd_broad", "wti", "spx", "acwi", "kospi", "us_hy_oas")
FACT_RX = re.compile(r"\[F(\d+)\]")
NUM_RX = re.compile(r"\d")

PROMPT = """너는 국부펀드 운용역에게 아침 시장 요약을 쓰는 보조다. 아래 '사실표'만 근거로 JSON 하나로만 답한다(설명·코드 블록 없이).
{"summary": ["오늘 요약 문장", …(3~5개)], "judgement": ["AI 판단 문장", …(1~2개)]}
규칙:
- 숫자(값·변화·날짜)를 문장에 직접 쓰지 않는다. 숫자가 필요한 자리는 사실표의 [F번호]로만 가리킨다(예: "미 10년 금리가 [F3] 올랐다").
- 사실표에 없는 사건·원인·전망·종목을 지어내지 않는다. 원인을 모르면 움직임만 말한다.
- '가상' 표시가 붙은 시리즈는 데모 값이다 — 쓰려면 '가상'이라고 밝힌다.
- AI 판단은 사실표의 움직임끼리의 관계(예: 금리와 달러가 같이 움직임)나 확인할 점만 짧게. 투자 권유·매매 제안은 하지 않는다.
- 한국어, 짧은 문장."""


def _score(c: Dict[str, Any]) -> float:
    d1 = (c.get("changes") or {}).get("d1")
    if not d1:
        return 0.0
    return abs(d1["value"]) / (10.0 if d1["unit"] == "bp" else 1.0 if d1["unit"] == "%" else 0.2)


def make_facts(as_of: Optional[str] = None) -> List[Dict[str, Any]]:
    b = board(as_of)
    cards = [c for g in b["groups"] for c in g["series"] if c.get("value") is not None]
    # 실데이터 시리즈의 큰 움직임 먼저(6개), 가상(데모) 시리즈는 3개까지
    real = sorted([c for c in cards if not c.get("virtual")], key=_score, reverse=True)[:6]
    virt = sorted([c for c in cards if c.get("virtual")], key=_score, reverse=True)[:3]
    picked = [*real, *virt]
    for c in cards:
        if c["id"] in KEY_SERIES and c not in picked:
            picked.append(c)
    facts: List[Dict[str, Any]] = []
    for c in picked:
        ch = c.get("changes") or {}
        parts = [f"{c['display']} {c['unit']}"]
        for k, ko in (("d1", "전일"), ("w1", "1주"), ("m1", "1달")):
            if ch.get(k):
                parts.append(f"{ko} {ch[k]['display']}")
        facts.append({"id": f"F{len(facts) + 1}", "seriesId": c["id"], "name": c["name"], "group": c["group"], "date": c["date"], "source": c["sourceLabel"], "virtual": c["virtual"],
                      "value": c["display"], "unit": c["unit"], "changes": {k: v["display"] for k, v in ch.items()}, "text": f"{c['name']}: " + ", ".join(parts) + f" (기준일 {c['date']}, 출처 {c['sourceLabel']})" + (" [가상]" if c["virtual"] else "")})
    with Session(engine) as s:
        n_issues = len(s.exec(select(DataIssue.id).where(DataIssue.resolved_at == None)).all())  # noqa: E711
    fb = sum(1 for c in cards if c.get("fallback"))
    facts.append({"id": f"F{len(facts) + 1}", "seriesId": None, "name": "데이터 상태", "text": f"데이터 상태: 대체 소스로 받은 시리즈 {fb}개, 열린 품질 문제 {n_issues}건", "value": f"대체 {fb} · 문제 {n_issues}", "virtual": False})
    return facts


def _json(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M))
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


# 숫자 검사에서 빼는 것 — 시리즈 이름 속 숫자(S&P 500·닛케이 225·미 국채 10년)와 기간 낱말(10년물·1주·1달·3개월)
_NAMES = sorted({x.name for x in __import__("app.market.catalog", fromlist=["SERIES"]).SERIES}, key=len, reverse=True)
_PERIOD = re.compile(r"\d+\s*(?:년물|년|개월|달|주|일)(?![\d.,])")


def _check(sentences: List[Any], ids: set) -> tuple[List[str], List[str]]:
    keep, drop = [], []
    for s in sentences:
        if not isinstance(s, str) or not s.strip():
            continue
        refs = {f"F{x}" for x in FACT_RX.findall(s)}
        bare = FACT_RX.sub("", s)
        for nm in _NAMES:
            bare = bare.replace(nm, "")
        bare = _PERIOD.sub("", bare)
        if NUM_RX.search(bare) or not refs <= ids:
            drop.append(s.strip())  # 사실표 밖의 숫자·없는 번호 — 뺀다
            continue
        keep.append(s.strip())
    return keep, drop


async def make_brief(as_of: Optional[str] = None, llm: Any = None) -> Dict[str, Any]:
    from app.llm.client import ReportLlm, provider_ready

    day = as_of or date.today().isoformat()
    facts = make_facts(as_of)
    ids = {f["id"] for f in facts}
    summary: List[str] = []
    judgement: List[str] = []
    dropped: List[str] = []
    model = ""
    if provider_ready():
        llm = llm or ReportLlm()
        content = f"{PROMPT}\n\n## 사실표\n" + "\n".join(f"[{f['id']}] {f['text']}" for f in facts)
        for _ in range(2):
            try:
                res = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": content}], temperature=0.2, max_tokens=2500, reasoning_effort="low", timeout_s=120))
            except Exception:  # noqa: BLE001
                log.exception("market brief failed")
                continue
            got = _json(getattr(res, "content", "") or "")
            if not got:
                continue
            summary, d1 = _check(list(got.get("summary") or []), ids)
            judgement, d2 = _check(list(got.get("judgement") or []), ids)
            dropped = d1 + d2
            model = getattr(llm, "model_name", "") or ""
            if summary:
                break
    with Session(engine) as s:
        row = s.get(MarketBrief, day) or MarketBrief(date=day)
        row.summary, row.judgement, row.facts, row.dropped, row.model, row.created_at = summary, judgement, facts, dropped, model, utcnow()
        s.add(row)
        s.commit()
    return brief_view(day)


def brief_view(day: Optional[str] = None) -> Dict[str, Any]:
    with Session(engine) as s:
        if day:
            row = s.get(MarketBrief, day)
        else:
            row = s.exec(select(MarketBrief).order_by(MarketBrief.date.desc())).first()
        dates = [r for r in s.exec(select(MarketBrief.date).order_by(MarketBrief.date.desc()).limit(14)).all()]
    if row is None:
        return {"date": day, "summary": [], "judgement": [], "facts": [], "dropped": [], "dates": dates, "createdAt": None}
    return {"date": row.date, "summary": row.summary, "judgement": row.judgement, "facts": row.facts, "dropped": row.dropped, "model": row.model, "dates": dates, "createdAt": iso(row.created_at)}
