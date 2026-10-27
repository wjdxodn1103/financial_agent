"""검수 대상 문서의 숫자 주장(claim) 뽑기 — LLM 은 후보만 내고, 코드가 원문에서 다시 확인한다.

claim = {id, chunk, quote, metric, metricKey, period, periodKey, basis, raw, value, abs, step, percent, pp, kind: figure|change,
         basePeriod, basePeriodKey, source: llm|rule|table}
 - 표 칸: 대상 문서 자신의 figures(결정적) → kind=figure, source=table
 - 문장: LLM 이 {문단, 인용문, 지표, 기간, 값, 종류} 를 내면 — 인용문이 그 문단에 글자 그대로 있고 값이 인용문 안에 있을 때만 받는다.
         LLM 이 없으면(키 없음) 규칙 추출: 문장 속 금액 앞의 가장 가까운 지표 이름 + 문장의 연도.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from app.docs.store import load_chunks
from app.ledger.figures import METRIC_ALIASES, basis_of, load_figures, metric_key, period_key
from app.ledger.numbers import find_amounts
from app.llm.base import ChatParams

log = logging.getLogger(__name__)

BATCH_CHARS = 5000
CLAIM_SYSTEM = """너는 금융 문서 검수 보조다. 주어진 문단들에서 '숫자 주장'을 뽑아 JSON 하나만 출력한다(설명·코드블록 없이).
{"claims": [{"p": "문단 id", "quote": "숫자가 든 문장(문단에서 글자 그대로 복사)", "metric": "지표 이름(예: 매출액, 영업이익, 영업이익률, 당기순이익)",
  "period": "기간(예: 2024, 2024Q2, 2024E) — 문장·문단에 없으면 빈 문자열", "basis": "연결|별도|빈 문자열", "value": "숫자와 단위 그대로(예: 3,150억원, 11.0%)",
  "type": "figure 또는 change", "base_period": "change 일 때 비교 대상 기간(예: 2023), 아니면 빈 문자열"}]}
규칙
- 문단에 실제로 있는 숫자만 뽑는다. 지어내거나 계산하지 않는다. quote 는 문단 원문을 그대로 복사한다(고치지 않는다).
- change 는 '전년 대비 12.5% 증가', '1.0%p 상승'처럼 변화율·변화폭이다. 그 밖의 금액·비율은 figure.
- 연도·날짜·쪽 번호·전화번호·조항 번호·사람 수 같은 숫자는 뺀다. 재무·실적·밸류에이션 지표만.
- 지표 이름은 줄임말만 표준 이름으로 바꾸고(매출 → 매출액, 영업익 → 영업이익) 앞의 수식어는 남긴다(변동금리 차입금, 데이터센터 인프라 매출액).
- 숫자가 든 문장의 재무 숫자는 하나도 빠뜨리지 않는다."""

_ALIAS_WORDS = sorted({a for al in METRIC_ALIASES.values() for a in al if re.search(r"[가-힣]", a)} | {"매출", "영업익", "순익", "EBITDA", "ROE", "ROA", "EPS", "BPS", "DPS", "PER", "PBR"}, key=len, reverse=True)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*(?:년|년도|FY)?(?:\s*([1-4])\s*(?:분기|Q))?")
_CHANGE = re.compile(r"(증가|감소|늘|줄|상승|하락|성장|개선|악화|확대|축소|증|감)")
_VS = re.compile(r"(전년|전기|전분기|대비|YoY|QoQ|yoy|qoq)")
_SENTENCES = re.compile(r"(?<=[.!?。다])\s+|\n+")
_FLAT = re.compile(r"[\s·・,.\-_/]")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def _nospace(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _year_of(m: "re.Match[str]") -> str:
    return f"{m.group(1)}{'Q' + m.group(2) if m.group(2) else ''}"


class YearContext:
    """문장에 기간이 없을 때 쓰는 문맥 기간 — 문서 순서로 그 문장 앞에서 마지막으로 나온 연도(문단 제목 포함)."""

    def __init__(self, chunks: Sequence[Dict[str, Any]]):
        self.before: Dict[str, str] = {}
        self.marks: Dict[str, List[tuple]] = {}
        last = ""
        for c in chunks:
            hm = _YEAR.search(c.get("heading") or "")
            start = _year_of(hm) if hm else last
            self.before[c["id"]] = start
            marks = [(m.start(), _year_of(m)) for m in _YEAR.finditer(c.get("text") or "")]
            self.marks[c["id"]] = marks
            last = marks[-1][1] if marks else start

    def at(self, chunk: Dict[str, Any], quote: str) -> str:
        text = chunk.get("text") or ""
        i = text.find((quote or "").strip()[:12])
        pos = i if i >= 0 else len(text)
        prior = [y for p, y in self.marks.get(chunk["id"], []) if p < pos]
        return prior[-1] if prior else self.before.get(chunk["id"], "")


def _claim_from(
    chunk: Dict[str, Any], quote: str, metric: str, period: str, basis: Optional[str], value_text: str, kind: str, base_period: str, source: str, default_period: str = ""
) -> Optional[Dict[str, Any]]:
    """원문 재확인 — quote 가 문단에 있고 value 가 quote 에 있어야 한다. 기간이 없으면 문장 → 문단 제목 → 문맥 기간(default_period)."""
    text = chunk.get("text") or ""
    if not quote or _nospace(quote) not in _nospace(text):
        return None
    if not value_text or _nospace(value_text) not in _nospace(quote):
        return None
    amts = find_amounts(value_text) or [a for a in find_amounts(quote) if _nospace(a["raw"]) in _nospace(value_text)]
    if not amts:
        return None
    a = amts[0]
    inferred = False
    if not period:
        m = _YEAR.search(quote) or _YEAR.search(chunk.get("heading") or "")
        if m:
            period = _year_of(m)
        elif default_period:
            period, inferred = default_period, True
    pk = period_key(period) if period else ""
    if kind == "change" and not base_period and re.fullmatch(r"\d{4}", pk or ""):
        base_period = str(int(pk) - 1)
    return {
        "chunk": chunk["id"],
        "quote": _norm(quote)[:300],
        "metric": metric.strip(),
        "metricKey": metric_key(metric),
        "period": period,
        "periodKey": pk,
        "basis": basis or basis_of(quote, chunk.get("heading")),
        "raw": a["raw"],
        "value": a["value"],
        "abs": a["abs"],
        "step": a["step"],
        "decimals": a.get("decimals", 0),
        "percent": a["percent"],
        "pp": bool(a.get("pp")),
        "currency": a.get("currency"),
        "unitKnown": bool(a.get("unit")),
        "kind": kind if kind in ("figure", "change") else "figure",
        "basePeriod": base_period,
        "basePeriodKey": period_key(base_period) if base_period else "",
        "periodInferred": inferred,
        "source": source,
    }


def rule_claims(chunks: Sequence[Dict[str, Any]], years: Optional[YearContext] = None) -> List[Dict[str, Any]]:
    """LLM 없이 — 문장마다 금액 앞의 가장 가까운 지표 이름, 문장(없으면 문맥)의 연도."""
    years = years or YearContext(chunks)
    out: List[Dict[str, Any]] = []
    for ch in chunks:
        for sent in _SENTENCES.split(ch.get("text") or ""):
            amts = find_amounts(sent)
            for a in amts:
                head = sent[: a["start"]]
                best = None
                for w in _ALIAS_WORDS:
                    i = head.upper().rfind(w.upper()) if w.isascii() else head.rfind(w)
                    if i >= 0 and (best is None or i + len(w) > best[0]):
                        best = (i + len(w), w)
                if best is None:
                    continue
                tail = sent[a["end"] : a["end"] + 8]
                kind = "change" if a["percent"] and _CHANGE.search(tail) and _VS.search(sent) else "figure"
                c = _claim_from(ch, sent, best[1], "", None, a["raw"], kind, "", "rule", default_period=years.at(ch, sent))
                if c:
                    out.append(c)
    return out


def _nearest_name(head: str, names: Sequence[str]) -> Optional[str]:
    """숫자 앞 글에서 끝이 숫자에 가장 가까운 지표 이름(같으면 긴 이름 — '변동금리 차입금' > '차입금')."""
    flat = _FLAT.sub("", head).lower()
    best: Optional[tuple] = None
    for n in names:
        fn = _FLAT.sub("", n).lower()
        i = flat.rfind(fn) if fn else -1
        if i >= 0 and (best is None or (i + len(fn), len(fn)) > best[:2]):
            best = (i + len(fn), len(fn), n)
    return best[2] if best else None


def sweep_claims(chunks: Sequence[Dict[str, Any]], claims: Sequence[Dict[str, Any]], years: YearContext, names: Sequence[str]) -> Dict[str, Any]:
    """추출이 빠뜨린 숫자를 코드가 훑는다 — 문장의 금액 가운데 어떤 주장도 덮지 않은 것마다
    앞의 가장 가까운 지표 이름(근거 원장의 지표 이름 + 표준 이름)으로 주장을 만든다. 이름을 못 찾으면 missed — 대조하지 않았다고 화면에 남긴다.
    → {"claims": [...], "missed": [{chunk, raw, quote}]}"""
    left: Dict[tuple, int] = {}
    for c in claims:
        k = (c["chunk"], _nospace(c["raw"]))
        left[k] = left.get(k, 0) + 1
    vocab = list(dict.fromkeys([*names, *_ALIAS_WORDS]))
    out: List[Dict[str, Any]] = []
    missed: List[Dict[str, Any]] = []
    for ch in chunks:
        for sent in _SENTENCES.split(ch.get("text") or ""):
            for a in find_amounts(sent):
                k = (ch["id"], _nospace(a["raw"]))
                if left.get(k, 0) > 0:
                    left[k] -= 1
                    continue
                name = _nearest_name(sent[: a["start"]], vocab)
                tail = sent[a["end"] : a["end"] + 8]
                kind = "change" if a["percent"] and _CHANGE.search(tail) and _VS.search(sent) else "figure"
                c = _claim_from(ch, sent, name, "", None, a["raw"], kind, "", "sweep", default_period=years.at(ch, sent)) if name else None
                if c:
                    out.append(c)
                else:
                    missed.append({"chunk": ch["id"], "raw": a["raw"].strip(), "quote": _norm(sent)[:200]})
    return {"claims": out, "missed": missed}


def _parse_json(raw: str) -> List[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return []
    try:
        v = json.loads(m.group(0))
    except ValueError:
        return []
    items = v.get("claims") if isinstance(v, dict) else None
    return [x for x in items or [] if isinstance(x, dict)]


async def llm_claims(llm: Any, chunks: Sequence[Dict[str, Any]], years: Optional[YearContext] = None) -> Dict[str, Any]:
    """→ {"claims": [...], "proposed": n, "rejected": n}. 배치마다 LLM 1회. 원문 재확인에서 떨어진 후보는 rejected."""
    years = years or YearContext(chunks)
    by_id = {c["id"]: c for c in chunks}
    batches: List[List[Dict[str, Any]]] = []
    cur: List[Dict[str, Any]] = []
    size = 0
    for c in chunks:
        t = len(c.get("text") or "")
        if cur and size + t > BATCH_CHARS:
            batches.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += t
    if cur:
        batches.append(cur)
    claims: List[Dict[str, Any]] = []
    proposed = rejected = 0
    for b in batches:
        user = "\n\n".join(f"[{c['id']}]{(' § ' + c['heading']) if c.get('heading') else ''}\n{c.get('text') or ''}" for c in b)
        params = ChatParams(messages=[{"role": "system", "content": CLAIM_SYSTEM}, {"role": "user", "content": user}], temperature=0.0, max_tokens=4000, reasoning_effort="low", timeout_s=180)
        try:
            res = await llm.complete("chat", params)
        except Exception as e:  # noqa: BLE001 — 한 배치 실패는 규칙 추출로 메운다
            log.warning("[review] claim batch failed: %s", e)
            claims.extend(rule_claims(b, years))
            continue
        for x in _parse_json(res.content):
            proposed += 1
            ch = by_id.get(str(x.get("p") or ""))
            quote = str(x.get("quote") or "")
            c = (
                _claim_from(ch, quote, str(x.get("metric") or ""), str(x.get("period") or ""), (str(x.get("basis") or "") or None), str(x.get("value") or ""), str(x.get("type") or "figure"), str(x.get("base_period") or ""), "llm", default_period=years.at(ch, quote))
                if ch
                else None
            )
            if c is None or not c["metric"]:
                rejected += 1
                continue
            claims.append(c)
    return {"claims": claims, "proposed": proposed, "rejected": rejected}


def table_claims(doc_id: str) -> List[Dict[str, Any]]:
    """대상 문서 자신의 표 칸 수치(결정적)."""
    out = []
    for f in load_figures(doc_id):
        out.append(
            {
                "chunk": f["chunk"],
                "cell": f.get("cell"),
                "quote": f"{f['metric']} · {f['period']} = {f.get('display') or f['raw']} (표)",
                "metric": f["metric"],
                "metricKey": f["metricKey"],
                "period": f["period"],
                "periodKey": f["periodKey"],
                "basis": f.get("basis"),
                "raw": f["raw"],
                "value": f["value"],
                "abs": f["abs"],
                "step": f["step"],
                "decimals": f.get("decimals", 0),
                "percent": f.get("percent", False),
                "pp": False,
                "currency": f.get("currency"),
                "unitKnown": f.get("unitKnown", True),
                "kind": "figure",
                "basePeriod": "",
                "basePeriodKey": "",
                "source": "table",
            }
        )
    return out


async def extract_claims(doc_id: str, llm: Optional[Any], names: Sequence[str] = ()) -> Dict[str, Any]:
    """names = 근거 원장의 지표 이름 — 추출이 빠뜨린 숫자를 훑을 때 쓴다(sweep_claims)."""
    chunks = load_chunks(doc_id)
    years = YearContext(chunks)  # 문맥 기간은 표·제목까지 문서 전체 순서로
    prose = [c for c in chunks if not c.get("rows") and find_amounts(c.get("text") or "")]
    if llm is not None and prose:
        got = await llm_claims(llm, prose, years)
    else:
        got = {"claims": rule_claims(prose, years), "proposed": 0, "rejected": 0}
    swept = sweep_claims(prose, got["claims"], years, names)
    claims = got["claims"] + swept["claims"] + table_claims(doc_id)
    # 같은 문단·같은 숫자는 한 번만
    seen = set()
    uniq = []
    for c in claims:
        key = (c["chunk"], c["raw"], c["metricKey"], c["periodKey"], c["kind"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)
    for i, c in enumerate(uniq, 1):
        c["id"] = f"c{i}"
    return {"claims": uniq, "proposed": got["proposed"], "rejected": got["rejected"], "mode": "llm" if llm is not None and prose else "rule", "swept": len(swept["claims"]), "missed": swept["missed"]}
