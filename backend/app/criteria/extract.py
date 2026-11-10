"""판단 기준 뽑기 — 자료(투자정책서·하우스뷰·회의록·안건·보고서)에서 기준 초안(draft)을 낸다. 사람이 승인해야 쓰인다.

 - 투자정책서: 가이드라인 점검이 뽑아 둔 한도 문장(guideline._rules — 캐시)을 그대로 쓴다. 한도는 '넘으면 검토' 조건으로 뒤집는다(≤5% → >5% 도달 시 축소 검토).
 - 하우스뷰: '자산: 긍정.' 줄을 코드가 읽는다(LLM 0회). 입장 기준(stance)은 프롬프트에만 싣고 사건 판정에는 쓰지 않는다.
 - 그 밖(회의록·안건·보고서): LLM 1회 — 문장 번호·원문 그대로의 인용·조건·방향만 낸다. 코드가 확인한다:
   인용이 그 문장에 그대로 있는가 · 방향 낱말(재심의·축소·확대·유지)이 그 문장에 있는가 · 숫자 조건이면 기준값이 숫자인가 · 대상 이름이 자료에 나오는가.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.anchors import pin
from app.assistants import guideline, houseview
from app.assumptions.extract import _sentences_data, _sentences_report
from app.assumptions.judge import PORTFOLIO_RX
from app.criteria.match import OP_KO
from app.docs.store import doc_label, load_meta
from app.llm.base import ChatParams

NEGATE = {"<=": ">", "<": ">=", ">=": "<", ">": "<="}
DIRECTIONS = ("expand", "hold", "reduce", "review")
DIR_RX = {"review": re.compile(r"재심의|재검토|다시 심의|다시 검토|재상정|review", re.I), "reduce": re.compile(r"축소|줄이|줄인|낮추|낮춘|감축|reduce|trim", re.I),
          "expand": re.compile(r"확대|늘리|늘린|높이|높인|증액|expand|increase", re.I), "hold": re.compile(r"유지|hold|maintain", re.I)}
METRIC_KO = {"issuer": "단일 발행자 비중", "unlisted": "비상장 비중"}

PROMPT = """아래는 투자 회의록·안건·보고서의 문장들이다(번호 붙음). 앞으로의 투자 판단에 다시 쓸 '판단 기준'(그렇게 되면 어떻게 검토한다는 규칙·원칙)을 최대 6개 골라 JSON 하나로만 답한다(설명 없이).
{"criteria": [{"n": 문장 번호, "quote": "그 문장에서 기준 부분을 글자 그대로", "title": "짧은 이름(20자 안)", "when": "조건을 한 줄로", "direction": "expand|hold|reduce|review",
  "kind": "numeric|qualitative", "applies": {"name": "특정 회사·자산에만 해당하면 그 이름(아니면 빈 문자열)", "ticker": "", "assetClass": ""},
  "condition": {"metric": "지표 이름", "period": "latest_q_yoy|latest_q|latest_fy|latest_fy_yoy", "op": ">=|>|<=|<", "threshold": 숫자, "unit": "%|억원|USD mn 등"}}]}
규칙:
- 이미 일어난 사실·그 자리의 결정 자체는 기준이 아니다. '~이면 재심의한다', '~를 넘으면 축소한다' 처럼 다음에도 쓸 수 있는 규칙만.
- direction: 재심의·재검토 → review, 축소 → reduce, 확대 → expand, 유지 → hold. 그 문장에 방향 낱말이 있어야 한다.
- condition 은 '조건이 참이면 그 방향을 검토한다'가 되게 쓴다(예: '30% 아래로 내려가면 재심의' → op "<", threshold 30). 숫자로 확인할 수 없으면 kind=qualitative, condition 은 빈 객체.
- 성장률은 period latest_q_yoy(분기) 또는 latest_fy_yoy(연간), threshold 는 % 숫자. 포트폴리오 비중 조건은 metric 에 '…비중'(단일 발행자 비중·비상장 비중)을 쓰고 period 는 비운다.
- quote 는 문장 글자를 바꾸지 않고 그대로 옮긴다."""


def _norm(s: Any) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def _json(text: str) -> Dict[str, Any]:
    """답 속 첫 JSON 객체 — 모델이 객체 뒤에 다른 객체·글을 덧붙여도(실측: 끝에 빈 '{}') 첫 것만 읽는다."""
    t = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M)
    start = t.find("{")
    while start >= 0:
        try:
            v, _end = json.JSONDecoder().raw_decode(t, start)
            if isinstance(v, dict):
                return v
        except ValueError:
            pass
        start = t.find("{", start + 1)
    return {}


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _source(doc_kind: str, doc_ref: str, title: str, step: Optional[str], quote: str, chunk: Optional[str] = None, cell: Optional[List[int]] = None) -> Dict[str, Any]:
    """기준이 나온 원문 — 올린 자료면 문단 앵커(근거 고정), AI 작업 문서면 섹션·문장."""
    if doc_kind == "report":
        return {"docKind": "report", "docRef": doc_ref, "docTitle": title, "step": step, "quote": quote, "anchor": {"kind": "report", "sessionId": doc_ref, "step": step, "quote": quote}}
    a = pin(doc_ref, chunk or step or "", quote=None if cell else quote, cell=cell)
    return {"docKind": "data", "docRef": doc_ref, "docTitle": title, "step": None, "quote": quote, "anchor": a or {"docId": doc_ref, "chunk": chunk or step, "quote": quote}}


def limit_of(cond: Dict[str, Any]) -> Dict[str, Any]:
    """비중 조건(단일 발행자·비상장·자산군)이면 그 반대가 한도 — '>5% 면 축소' → 한도 ≤5%."""
    th = _num(cond.get("threshold"))
    if th is None or not PORTFOLIO_RX.search(str(cond.get("metric") or "")) or cond.get("op") not in NEGATE:
        return {}
    return {"op": NEGATE[cond["op"]], "threshold": th, "unit": cond.get("unit") or "%"}


async def from_policy(llm: Any, doc_id: str) -> List[Dict[str, Any]]:
    """투자정책서 → 한도·범위 기준(코드 판정) + 판정할 수 없는 원칙(정성 — 프롬프트에만)."""
    title = doc_label(load_meta(doc_id), doc_id)
    out: List[Dict[str, Any]] = []
    for r in await guideline._rules(llm, doc_id):
        th, op, m = r.get("threshold"), r.get("op") or "<=", r.get("metric")
        src = _source("data", doc_id, title, None, r["quote"], r["chunk"], r.get("cell"))
        if r.get("kind") == "target" and th is not None:  # 목표 비중 — 판정하지 않고 프롬프트에만(이름은 표 행 원문 대신 사람 말로)
            name = f"{r.get('scope') or '자산군'} 목표 비중 {th:g}%"
            out.append({"title": name, "when_text": name, "kind": "qualitative", "condition": {}, "direction": "hold", "source": src})
            continue
        if m == "other" or th is None:
            out.append({"title": r["quote"][:40], "when_text": r["line"][:200], "kind": "qualitative", "condition": {}, "direction": "review", "source": src})
            continue
        metric = METRIC_KO.get(m) or f"{r.get('scope') or '자산군'} 비중"
        cond = {"metric": metric, "op": NEGATE.get(op, ">"), "threshold": th, "unit": "%"}
        upper = op in ("<=", "<")
        name = {"issuer": "단일 발행자 한도", "unlisted": "비상장 합계 한도"}.get(m) or f"{r.get('scope') or '자산군'} {'상한' if upper else '하한'}"
        out.append({"title": f"{name} {th:g}%", "when_text": f"{metric} {th:g}% {OP_KO.get(cond['op'], '')}", "kind": "numeric", "condition": cond,
                    "direction": "reduce" if upper else "expand", "limit": {"op": op, "threshold": th, "unit": "%"}, "source": src})
    return out


def from_houseview(doc_id: str) -> List[Dict[str, Any]]:
    """하우스뷰 → 자산군별 입장(stance). 문서의 분기를 제목에 둔다."""
    title, period = doc_label(load_meta(doc_id), doc_id), houseview.period_of(doc_id)
    out = []
    for st in houseview._by_code(doc_id):
        ko = houseview.STANCE_KO.get(st["stance"], st["stance"])
        # 입장 → 비중 방향 매핑은 정하지 않는다(사람 판단) — 입장 그대로 두고 방향은 '유지'(사건 판정에 쓰지 않음)
        out.append({"title": f"하우스뷰 {period} {st['asset']} {ko}".strip(), "when_text": st["quote"], "kind": "stance", "condition": {}, "direction": "hold",
                    "applies": {"assetClass": st["asset"], "stance": ko}, "source": _source("data", doc_id, title, None, st["quote"], st["chunk"])})
    return out


async def from_text(llm: Any, doc_kind: str, doc_ref: str, report_doc: Optional[Dict[str, Any]] = None, title: str = "") -> List[Dict[str, Any]]:
    sents: List[Tuple[str, str, str]] = _sentences_report(report_doc or {}) if doc_kind == "report" else _sentences_data(doc_ref)
    if not sents:
        return []
    title = title or doc_label(load_meta(doc_ref), doc_ref)
    body = "\n".join(f"[{i + 1}] {plain}" for i, (_s, _raw, plain) in enumerate(sents))[:16000]
    got: Dict[str, Any] = {}
    for _ in range(2):  # 빈 답·깨진 JSON 이면 한 번 더
        res = await llm.complete("chat", ChatParams(messages=[{"role": "user", "content": f"{PROMPT}\n\n## 문장\n{body}"}], temperature=0, max_tokens=4000, reasoning_effort="low", timeout_s=180))
        got = _json(getattr(res, "content", "") or "")
        if got.get("criteria"):
            break
    return verify(got.get("criteria") or [], sents, doc_kind, doc_ref, title)


def verify(items: List[Dict[str, Any]], sents: List[Tuple[str, str, str]], doc_kind: str, doc_ref: str, title: str) -> List[Dict[str, Any]]:
    """LLM 답 → 기준 초안. 원문에 그대로 없는 인용·방향 낱말 없는 문장·자료에 없는 대상은 버린다(숫자 조건이 깨졌으면 정성으로 낮춘다)."""
    whole = _norm(" ".join(p for _s, _r, p in sents))
    out: List[Dict[str, Any]] = []
    for it in items:
        try:
            n = int(it.get("n"))
        except (TypeError, ValueError):
            continue
        if not (1 <= n <= len(sents)):
            continue
        step, _raw, plain = sents[n - 1]
        quote = str(it.get("quote") or "").strip()
        direction = it.get("direction") if it.get("direction") in DIRECTIONS else ""
        if not quote or _norm(quote) not in _norm(plain) or not direction or not DIR_RX[direction].search(plain):
            continue
        ap = it.get("applies") if isinstance(it.get("applies"), dict) else {}
        applies = {k: str(ap.get(k) or "").strip()[:80] for k in ("name", "ticker", "assetClass") if str(ap.get(k) or "").strip()}
        if applies.get("name") and _norm(applies["name"])[:10].lower() not in whole.lower():
            continue  # 자료에 나오지 않는 대상
        cond = it.get("condition") if isinstance(it.get("condition"), dict) else {}
        numeric = it.get("kind") == "numeric" and bool(cond.get("metric")) and _num(cond.get("threshold")) is not None and cond.get("op") in OP_KO
        cond = {k: cond[k] for k in ("metric", "period", "op", "threshold", "unit") if cond.get(k) not in (None, "")} if numeric else {}
        if numeric:
            cond["threshold"] = _num(cond["threshold"])
        out.append({"title": str(it.get("title") or quote)[:40], "when_text": str(it.get("when") or quote)[:200], "kind": "numeric" if numeric else "qualitative", "condition": cond,
                    "direction": direction, "applies": applies, "limit": limit_of(cond) if numeric else {}, "source": _source(doc_kind, doc_ref, title, step, quote)})
    return out


def kind_of(doc_kind: str, doc_ref: str) -> str:
    """자료 종류 → 뽑는 길: policy | houseview | text"""
    if doc_kind == "data":
        if houseview.is_houseview(doc_ref):
            return "houseview"
        label = guideline._label(doc_ref)
        if "투자정책" in label or "investment policy" in label.lower():
            return "policy"
    return "text"


async def extract(llm: Any, doc_kind: str, doc_ref: str, report_doc: Optional[Dict[str, Any]] = None, title: str = "") -> List[Dict[str, Any]]:
    k = kind_of(doc_kind, doc_ref)
    if k == "policy":
        return await from_policy(llm, doc_ref)
    if k == "houseview":
        return from_houseview(doc_ref)
    return await from_text(llm, doc_kind, doc_ref, report_doc, title)
