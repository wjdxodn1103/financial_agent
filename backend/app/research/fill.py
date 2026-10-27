"""표 칸 채우기 — 행(기업·문서·기간) × 열(숫자·글·계산). 칸마다 원문으로 이어지고, 확인할 수 없는 값은 비운다.

순서(행마다):
 1) 숫자 열 — 근거 원장에서 코드로 찾는다(LLM 없음).
    a. 그 행의 자료(entities.candidate_docs, 회사 이름이 자료를 가리킬 때)에서 지표·기간·기준이 맞는 수치
    b. 한 자료에 여러 기업이 행 이름으로 든 표(사내 DB "가온전자 매출액") — 지표 이름에서 기업 이름을 빼고 다시 맞춤
    값이 여럿이면 원장 채택값 → 연결(API) 스냅샷 → 나중 자료 순. 다른 값은 alts(툴팁).
 2) 남은 숫자 열 + 글 열 — 행당 LLM 한 번. 후보 원장 수치(F#)와 검색 문단(S#)만 보여 주고 고르게 한 뒤, 코드가 검증한다
    (F# 는 보여 준 것·기간 일치, S# 값은 그 문단에 실제로 있고 문단에 지표·회사가 나와야 함). 통과 못 하면 빈 칸.
 3) 계산 열 — 같은 행 칸으로 코드 계산(ledger/calc). 입력이 비면 빈 칸.
 4) 열 단위 맞추기 — 열의 칸이 모두 단위를 알면 한 단위로 바꿔 머리에 적고, 아니면 칸마다 원래 표기.
칸 = {type: number|text|calc|empty, text, …}. empty 의 reason 은 툴팁에만 쓴다(판정 문구 아님).
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from collections import Counter
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple

from app.docs.search_tool import S_REF, SourceBook, run_search
from app.docs.store import doc_label, load_chunks, load_meta
from app.ledger.calc import CalcError, evaluate, readable, refs_in
from app.ledger.figures import METRIC_ALIASES, base_key, figure_line, fid as fid_of, load_figures, metric_key, period_key
from app.ledger.numbers import find_amounts, fmt_number, human_amount, parse_number, parse_unit, same_value, step_of
from app.llm.base import ChatParams, LlmError
from app.research import entities
from app.research.templates import MAX_ITEMS, MAX_ROWS, SUBJECT_KINDS

log = logging.getLogger(__name__)
Figure = Dict[str, Any]
Cell = Dict[str, Any]
Progress = Callable[[Dict[str, Any]], Awaitable[None]]

ROW_CONCURRENCY = 3
LLM_TIMEOUT = 120.0
LLM_MAX_TOKENS = 2500
SNIPPET_CHARS = 900
FIG_LIST_MAX = 40
PERCENT_FUNCS = re.compile(r"^\s*(growth|ratio|cagr)\(")
_PK = re.compile(r"^(\d{4})(Q[1-4]|H[12])?(E)?$")
NOT_FOUND = "자료에서 찾지 못함"


# ── 기간 ────────────────────────────────────────────────────────────────

def shift_period(pk: str, years: int) -> str:
    if not years:
        return pk
    m = _PK.match(pk or "")
    return f"{int(m.group(1)) + years}{m.group(2) or ''}{m.group(3) or ''}" if m else ""


def period_label(pk: str) -> str:
    m = _PK.match(pk or "")
    if not m:
        return pk or ""
    sub = {"H1": " 상반기", "H2": " 하반기"}.get(m.group(2) or "", f" {m.group(2)[1]}분기" if m.group(2) else "")
    return f"{m.group(1)}년{sub}" + (" (추정)" if m.group(3) else "")


def _rank(pk: str) -> Tuple[int, int, int]:
    """최신 실적 우선: (추정 아님, 해, 연간=5·하반기=4·4분기=…)."""
    m = _PK.match(pk or "")
    if not m:
        return (0, -1, 0)
    sub = m.group(2) or ""
    order = {"": 5, "H2": 4, "Q4": 3, "Q3": 2, "H1": 1, "Q2": 1, "Q1": 0}.get(sub, 0)
    return (0 if m.group(3) else 1, int(m.group(1)), order)


# ── 범위(자료·원장) ─────────────────────────────────────────────────────

class Scope:
    """한 번의 채우기에서 쓰는 자료·원장 — 파일을 한 번만 읽는다(스레드에서 만든다)."""

    def __init__(self, doc_ids: Sequence[str], choices: Dict[str, Dict[str, Any]]):
        self.doc_ids = list(doc_ids)
        self.choices = choices or {}
        self.labels = {d: doc_label(load_meta(d), d) for d in self.doc_ids}
        self.order = {d: i for i, d in enumerate(self.doc_ids)}
        self.snapshots = {d for d in self.doc_ids if (load_meta(d) or {}).get("snapshot")}
        self.figs: List[Figure] = []
        self._by_cell: Dict[Tuple[str, str, int, int], Figure] = {}
        for d in self.doc_ids:
            for f in load_figures(d):
                g = {**f, "fid": fid_of(f), "docLabel": self.labels[d]}
                self.figs.append(g)
                if f.get("cell"):
                    self._by_cell[(d, str(f["chunk"]), f["cell"][0], f["cell"][1])] = g
        self._chunks: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def chunk(self, doc_id: str, chunk_id: str) -> Optional[Dict[str, Any]]:
        if doc_id not in self._chunks:
            self._chunks[doc_id] = {str(c.get("id")): c for c in load_chunks(doc_id)}
        return self._chunks[doc_id].get(str(chunk_id))

    def cell_figure(self, doc_id: str, chunk_id: str, r: int, c: int) -> Optional[Figure]:
        return self._by_cell.get((doc_id, str(chunk_id), r, c))


def _same_fig(f: Figure, g: Figure) -> bool:
    if f.get("unitKnown", True) and g.get("unitKnown", True):
        return same_value(f["abs"], f["step"], g["abs"], g["step"])
    return same_value(f["value"], step_of(f.get("decimals", 0), 1.0), g["value"], step_of(g.get("decimals", 0), 1.0))


def _strip_name(metric: str, name: str) -> str:
    out = metric
    for part in {name, name.replace(" ", "")}:
        if part:
            out = re.sub(re.escape(part), " ", out, flags=re.I)
    return out


def _basis_ok(f: Figure, basis: str) -> bool:
    return not basis or not f.get("basis") or f.get("basis") == basis


def ledger_hits(scope: Scope, subject: Dict[str, Any], kind: str, docs: Sequence[str], strong: bool, mk: str, pk: str, basis: str) -> List[Figure]:
    """원장에서 (행, 지표, 기간) 수치 후보 — a) 행의 자료 안 정확 일치 b) 지표 이름에 행 이름이 든 칸."""
    hits: List[Figure] = []
    if strong and docs:
        ds = set(docs)
        hits = [f for f in scope.figs if f["doc"] in ds and f.get("metricKey") == mk and f.get("periodKey") == pk and _basis_ok(f, basis)]
    if not hits and kind in ("company", "label"):
        name = subject.get("label") or ""
        key = entities.norm(name)
        if key:
            for f in scope.figs:
                if f.get("periodKey") != pk or not _basis_ok(f, basis) or key not in entities.norm(f.get("metric")):
                    continue
                if metric_key(_strip_name(f.get("metric") or "", name)) == mk:
                    hits.append(f)
    return hits


def choose(scope: Scope, hits: List[Figure]) -> Tuple[Optional[Figure], List[Figure]]:
    """여러 값이면 채택값 → API 스냅샷 → 나중 자료. 같은 기준이 둘이면 연결 우선. → (고른 것, 다른 값 대표들)."""
    if not hits:
        return None, []
    bases = {f.get("basis") for f in hits if f.get("basis")}
    if len(bases) > 1:
        hits = [f for f in hits if f.get("basis") in ("연결", None)] or hits
    chosen = None
    for f in hits:
        ch = scope.choices.get(f"{base_key(f)}|{f.get('basis') or ''}")
        if ch and ch.get("figureId") == f["fid"]:
            chosen = f
            break
    if chosen is None:
        chosen = sorted(hits, key=lambda f: (f["doc"] in scope.snapshots, scope.order.get(f["doc"], 0)))[-1]
    alts: List[Figure] = []
    for f in hits:
        if not _same_fig(f, chosen) and not any(_same_fig(f, a) for a in alts):
            alts.append(f)
    return chosen, alts


def number_cell(f: Figure, via: str, alts: Sequence[Figure] = ()) -> Cell:
    return {
        "type": "number",
        "value": f["abs"],
        "raw": f.get("raw"),
        "display": f.get("display") or f.get("raw"),
        "fid": f["fid"],
        "docId": f["doc"],
        "docLabel": f.get("docLabel"),
        "chunk": f["chunk"],
        "cell": f.get("cell"),
        "page": f.get("page"),
        "metric": f.get("metric"),
        "period": f.get("period"),
        "basis": f.get("basis"),
        "unitKnown": f.get("unitKnown", True),
        "percent": bool(f.get("percent")),
        "currency": f.get("currency"),
        "scale": f.get("scale", 1.0),
        "unit": f.get("unit") or "",
        "decimals": f.get("decimals", 0),
        "via": via,
        "alts": [{"fid": a["fid"], "display": a.get("display") or a.get("raw"), "docLabel": a.get("docLabel")} for a in alts],
    }


def empty(reason: str = NOT_FOUND) -> Cell:
    return {"type": "empty", "reason": reason}


# ── 행 준비 ─────────────────────────────────────────────────────────────

def _row_docs(scope: Scope, subject: Dict[str, Any], kind: str) -> Tuple[List[str], bool]:
    """→ (그 행의 자료, 자료 자체가 그 행을 가리키는가)."""
    if subject.get("docId") in scope.order:
        return [subject["docId"]], True
    if kind == "company":
        strong = entities.company_docs(scope.doc_ids, subject.get("label") or "")
        if strong:
            return strong, True
    docs = entities.candidate_docs(subject, kind, scope.doc_ids)
    return docs, kind == "document" and bool(docs)


def _row_period(kind: str, subject: Dict[str, Any], period: str) -> str:
    return period_key(subject.get("label") or "") if kind == "period" else period


def auto_period(scope: Scope, subjects: List[Dict[str, Any]], kind: str, items: List[Dict[str, Any]], basis: str) -> str:
    """기준 기간을 안 정했으면 — 행들이 함께 가진 최신 기간(실적·연간 우선)."""
    targets = [metric_key(it["metric"]) for it in items if it["type"] == "number" and not it.get("periodOffset")]
    if not targets:
        return ""
    per_row: List[Set[str]] = []
    for s in subjects:
        docs, strong = _row_docs(scope, s, kind)
        name = s.get("label") or ""
        key = entities.norm(name)
        have: Set[str] = set()
        for f in scope.figs:
            pk = f.get("periodKey") or ""
            if not _PK.match(pk):
                continue
            if strong and f["doc"] in docs and f.get("metricKey") in targets:
                have.add(pk)
            elif kind in ("company", "label") and key and key in entities.norm(f.get("metric")) and metric_key(_strip_name(f.get("metric") or "", name)) in targets:
                have.add(pk)
        if have:
            per_row.append(have)
    if not per_row:
        return ""
    common = set.intersection(*per_row) or set.union(*per_row)
    return max(common, key=_rank)


# ── LLM 보충 ────────────────────────────────────────────────────────────

SYSTEM = """너는 표 칸을 채우는 리서치 보조다. 아래에 보인 원장 수치(F번호)와 자료 문단(S번호)만 쓴다. 없는 값을 짐작하거나 계산하지 않는다.
- 숫자 열: 맞는 원장 수치가 있으면 {"f": "F번호"}. 원장에 없고 문단에 그대로 적힌 값이면 {"s": 문단번호, "value": "문단에 적힌 그대로의 숫자와 단위"}. 없으면 null.
- 글 열: 문단에 근거가 있으면 {"text": "한두 문장, 120자 이내", "s": [문단번호, …]}. 없으면 null.
- 행(기업·문서)과 기간이 맞는지 꼭 확인한다. 다른 회사·다른 기간 값이면 null.
- JSON 객체 하나만 답한다(설명·마크다운 없이). 키는 열 key."""


def _parse_json(content: str) -> Optional[Dict[str, Any]]:
    t = re.sub(r"^```(?:json)?|```$", "", (content or "").strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else None
    except ValueError:
        from app.agent.loop import salvage_json

        return salvage_json(m.group(0))


def _snum(x: Any) -> Optional[int]:
    """문단 번호 — 2 · "2" · "S2" · "[S2]" 모두 받는다."""
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return int(x)
    m = re.search(r"\d+", str(x or ""))
    return int(m.group(0)) if m else None


def _aliases(item: Dict[str, Any]) -> List[str]:
    mk = metric_key(item.get("metric") or item["label"])
    return [entities.norm(a) for a in [mk, item["label"], item.get("metric") or "", *METRIC_ALIASES.get(mk, [])] if a]


def _mentions_metric(text: str, item: Dict[str, Any]) -> bool:
    t = entities.norm(text)
    return any(a and a in t for a in _aliases(item))


def _value_in_chunk(chunk: Dict[str, Any], value: str) -> Optional[Dict[str, Any]]:
    """LLM 이 옮긴 값이 문단에 실제로 있나 → {abs, step, unitKnown, cell?}. 표 문단이면 칸 위치까지."""
    want = find_amounts(value)
    bare = parse_number(re.sub(r"[^\d.,\-△()%]", "", value or ""))
    if chunk.get("rows"):
        for r, row in enumerate(chunk["rows"]):
            for c, txt in enumerate(row):
                got = parse_number(txt)
                if got and bare and same_value(abs(got[0]), step_of(got[1]["decimals"], 1.0), abs(bare[0]), step_of(bare[1]["decimals"], 1.0)):
                    return {"cell": [r, c], "raw": str(txt).strip(), "value": got[0], "percent": got[1]["percent"], "decimals": got[1]["decimals"]}
    if want:
        w = want[0]
        for a in find_amounts(chunk.get("text") or ""):
            if a["percent"] == w["percent"] and same_value(abs(a["abs"]), a["step"], abs(w["abs"]), w["step"]):
                return {"abs": a["abs"], "step": a["step"], "raw": a["raw"], "currency": a.get("currency"), "percent": a["percent"]}
    return None


async def llm_row(llm: Any, scope: Scope, kind: str, subject: Dict[str, Any], docs: List[str], strong: bool, todo: List[Dict[str, Any]], periods: Dict[str, str]) -> Dict[str, Cell]:
    """원장으로 못 채운 숫자 열 + 글 열을 한 번의 호출로. 검증 못 한 칸은 빈 칸."""
    name = subject.get("label") or ""
    search_docs_ = docs or scope.doc_ids

    def prepare() -> Tuple[List[str], Dict[str, Figure], SourceBook, List[str]]:
        fmap: Dict[str, Figure] = {}
        want_periods = {periods[it["key"]] for it in todo if it["type"] == "number" and periods.get(it["key"])}
        cands = [f for f in scope.figs if f.get("periodKey") in want_periods and ((strong and f["doc"] in docs) or entities.mentions(f.get("metric"), name))]
        targets = [it for it in todo if it["type"] == "number"]
        cands.sort(key=lambda f: -sum(_mentions_metric(f.get("metric") or "", it) for it in targets))
        lines = []
        for f in cands[:FIG_LIST_MAX] if targets else []:
            k = f"F{len(fmap) + 1}"
            fmap[k] = f
            lines.append(f"{k}. {figure_line(f)}")
        book = SourceBook()
        snippets: List[str] = []
        texts = [it for it in todo if it["type"] == "text"]
        queries: List[Tuple[str, List[str]]] = []
        if targets:
            queries.append((f"{name if kind != 'document' else ''} {' '.join(it['label'] for it in targets)} {period_label(next(iter(want_periods), ''))}".strip(), search_docs_))
        for it in texts[:4]:
            queries.append((f"{name if kind != 'document' else ''} {it['label']} {it.get('instruction') or ''}".strip(), search_docs_))
        for q, ds in queries:
            before = len(book.items)
            run_search(book, ds, {"query": q}, k=4 if kind == "document" else 6)
            for it in book.items[before:]:  # 앞 질의에서 이미 보인 문단은 다시 싣지 않는다
                where = f"p.{it['page']}" if it.get("page") else f"문단 {it['chunk']}"
                head = f" · {it['heading']}" if it.get("heading") else ""
                body = it["text"] if len(it["text"]) <= SNIPPET_CHARS else it["text"][:SNIPPET_CHARS] + "…"
                snippets.append(f"[S{it['n']}] {it['label']}, {where}{head}\n{body}")
        return lines, fmap, book, snippets

    lines, fmap, book, snippets = await asyncio.to_thread(prepare)
    if not lines and not book.items:
        return {it["key"]: empty() for it in todo}
    cols = []
    for it in todo:
        what = "숫자" if it["type"] == "number" else "글"
        per = f", 기간 {period_label(periods.get(it['key'], ''))}" if it["type"] == "number" and periods.get(it["key"]) else ""
        tip = f" — {it['instruction']}" if it.get("instruction") else ""
        cols.append(f"- {it['key']}: {it['label']} ({what}{per}){tip}")
    user = "\n".join(
        [
            f"행: {name} ({SUBJECT_KINDS.get(kind, '항목')})",
            "채울 열:",
            *cols,
            "",
            "원장 수치:",
            *(lines or ["(없음)"]),
            "",
            "자료 문단:",
            *(snippets or ["(없음)"]),
        ]
    )
    try:
        answer: Dict[str, Any] = {}
        for _try in range(2):  # 생각만 하다 상한에 걸려 빈 답이 오면 한 번 더
            res = await llm.complete("chat", ChatParams(messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], max_tokens=LLM_MAX_TOKENS, timeout_s=LLM_TIMEOUT, reasoning_effort="low"))
            answer = _parse_json(res.content) or {}
            if answer:
                break
    except (LlmError, asyncio.TimeoutError) as e:
        log.warning("research row %s: llm failed %s", name, e)
        return {it["key"]: empty("모델 응답 없음") for it in todo}

    def check() -> Dict[str, Cell]:
        out: Dict[str, Cell] = {}
        for it in todo:
            a = answer.get(it["key"])
            out[it["key"]] = empty()
            if not isinstance(a, dict):
                continue
            if it["type"] == "number":
                pk = periods.get(it["key"], "")
                mk = metric_key(it.get("metric") or it["label"])
                f = fmap.get(str(a.get("f") or "").strip().upper())
                if f is not None:
                    ok_metric = f.get("metricKey") == mk or metric_key(_strip_name(f.get("metric") or "", name)) == mk or _mentions_metric(f.get("metric") or "", it)
                    if (not pk or f.get("periodKey") == pk) and ok_metric:
                        out[it["key"]] = number_cell(f, "llm")
                    continue
                n = _snum(a.get("s")[0] if isinstance(a.get("s"), list) and a.get("s") else a.get("s"))
                src = book.get(n) if n else None
                if not src or not a.get("value"):
                    continue
                ch = scope.chunk(src["docId"], src["chunk"]) or {"text": src["text"]}
                body = f"{ch.get('heading') or ''} {ch.get('text') or ''}"
                if kind in ("company", "label") and not (strong and src["docId"] in docs) and not entities.mentions(body, name):
                    continue
                if not _mentions_metric(body, it):
                    continue
                hit = _value_in_chunk(ch, str(a["value"]))
                if not hit:
                    continue
                if hit.get("cell"):
                    fig = scope.cell_figure(src["docId"], src["chunk"], hit["cell"][0], hit["cell"][1])
                    if fig is not None:
                        if not pk or fig.get("periodKey") == pk:
                            out[it["key"]] = number_cell(fig, "extract")
                        continue
                    # 원장이 칸을 수치로 못 읽은 표(머리 모양이 특이한 표) — 칸 위치만 잇고 단위는 모른다고 둔다
                    out[it["key"]] = {
                        "type": "number", "value": hit["value"], "raw": hit["raw"], "display": hit["raw"], "docId": src["docId"], "docLabel": src["label"],
                        "chunk": src["chunk"], "cell": hit["cell"], "page": src.get("page"), "unitKnown": False, "percent": hit["percent"],
                        "currency": None, "scale": 1.0, "unit": "", "decimals": hit["decimals"], "via": "extract", "alts": [],
                    }
                    continue
                out[it["key"]] = {
                    "type": "number", "value": hit["abs"], "raw": hit["raw"], "display": hit["raw"], "docId": src["docId"], "docLabel": src["label"],
                    "chunk": src["chunk"], "page": src.get("page"), "unitKnown": bool(hit.get("currency") or hit.get("percent")), "percent": hit["percent"],
                    "currency": hit.get("currency"), "scale": 1.0, "unit": "", "decimals": 0, "via": "text", "alts": [],
                }
            else:
                nums = a.get("s") if isinstance(a.get("s"), list) else [a.get("s")]
                srcs = [book.get(n) for n in (_snum(x) for x in nums) if n]
                srcs = [x for x in srcs if x]
                text = S_REF.sub("", str(a.get("text") or "")).strip()
                if srcs and text:
                    out[it["key"]] = {"type": "text", "text": text[:240], "cites": [{"docId": x["docId"], "chunk": x["chunk"], "label": x["label"], "page": x.get("page")} for x in srcs]}
        return out

    return await asyncio.to_thread(check)


# ── 계산·표기 ───────────────────────────────────────────────────────────

def calc_cell(item: Dict[str, Any], row: Dict[str, Cell], items: Dict[str, Dict[str, Any]]) -> Cell:
    formula = item.get("formula") or ""
    refs = refs_in(formula)
    ins = [row.get(r) for r in refs]
    if not refs or any(c is None or c.get("type") not in ("number", "calc") or c.get("value") is None for c in ins):
        return empty("입력 값 없음")
    amounts = [c for c in ins if c["type"] == "number" and not c.get("percent")]
    if any(not c.get("unitKnown", True) for c in amounts) and any(c.get("unitKnown", True) for c in amounts):
        return empty("단위를 맞출 수 없음")
    try:
        v = evaluate(formula, {r: float(row[r]["value"]) for r in refs})
    except CalcError:
        return empty("계산할 수 없음")
    names = {r: f"{items[r]['label']} {row[r].get('display') or row[r].get('text') or ''}".strip() for r in refs}
    inputs: List[str] = []
    for r in refs:
        c = row[r]
        inputs.extend([c["fid"]] if c.get("fid") else c.get("inputs") or [])
    cur = next((c.get("currency") for c in amounts if c.get("currency")), None)
    return {"type": "calc", "value": v, "formula": formula, "readable": readable(formula, names), "inputs": inputs, "percent": bool(PERCENT_FUNCS.match(formula)), "currency": cur, "docIds": list(dict.fromkeys(row[r].get("docId") for r in refs if row[r].get("docId")))}


def _decimals_for(v: float) -> int:
    return 0 if abs(v) >= 100 else 1 if abs(v) >= 1 else 2


def format_columns(items: List[Dict[str, Any]], rows: List[Dict[str, Cell]]) -> Dict[str, Dict[str, Any]]:
    """열마다 단위 정하고 칸 text 를 채운다 → {key: {unit}}(머리에 붙일 단위)."""
    cols: Dict[str, Dict[str, Any]] = {}
    for it in items:
        cells = [r.get(it["key"]) for r in rows]
        cells = [c for c in cells if c and c.get("type") in ("number", "calc")]
        unit_label = ""
        if it["type"] == "number":
            amounts = [c for c in cells if not c.get("percent")]
            target = parse_unit(it["unit"]) if it.get("unit") else None
            currencies = {c.get("currency") for c in amounts if c.get("currency")}
            if target is None and amounts and all(c.get("unitKnown", True) and c.get("unit") for c in amounts) and len(currencies) <= 1:
                common = Counter((c.get("scale") or 1.0, c.get("unit")) for c in amounts).most_common(1)[0][0]
                target = parse_unit(common[1])
                target.scale = common[0]
                target.label = common[1]
            convertible = bool(target) and all(c.get("unitKnown", True) and (not target.currency or c.get("currency") in (None, target.currency)) for c in amounts)
            if amounts and convertible and target:
                unit_label = target.label
            elif cells and all(c.get("percent") for c in cells):
                unit_label = "%"
            for c in cells:
                if c.get("percent"):
                    d = it.get("decimals", c.get("decimals", 1))
                    c["text"] = f"{fmt_number(c['value'], d)}" if unit_label == "%" else f"{fmt_number(c['value'], d)}%"
                elif unit_label and target:
                    v = c["value"] / (target.scale or 1.0)
                    c["text"] = fmt_number(v, it.get("decimals", _decimals_for(v) if c.get("scale", 1) != target.scale else c.get("decimals", 0)))
                else:
                    c["text"] = c.get("display") or c.get("raw") or ""
        elif it["type"] == "calc":
            pct = all(c.get("percent") for c in cells) if cells else bool(PERCENT_FUNCS.match(it.get("formula") or ""))
            unit_label = "%" if pct else it.get("unit") or ""
            for c in cells:
                d = it.get("decimals", 1)
                if c.get("percent"):
                    c["text"] = fmt_number(c["value"], d)
                elif it.get("unit"):
                    u = parse_unit(it["unit"])
                    c["text"] = fmt_number(c["value"] / (u.scale or 1.0), d)
                else:
                    c["text"] = human_amount(c["value"], c.get("currency")) if abs(c["value"]) >= 1e4 else fmt_number(c["value"], d)
        if it["type"] != "text":
            cols[it["key"]] = {"unit": unit_label}
    return cols


# ── 진입점 ──────────────────────────────────────────────────────────────

async def fill_table(data: Dict[str, Any], doc_ids: Sequence[str], choices: Dict[str, Dict[str, Any]], llm: Any = None, on_progress: Optional[Progress] = None) -> Dict[str, Any]:
    """data = {spec, subjects, items, inputs, cells?} → 빈 칸만 채운 새 data(이미 채운 칸은 그대로 — 행·열을 더할 때)."""
    data = copy.deepcopy(data)
    spec = data.get("spec") or {}
    kind = (spec.get("subject") or {}).get("kind") or "company"
    items: List[Dict[str, Any]] = list(data.get("items") or [])[: MAX_ITEMS * 2]
    subjects: List[Dict[str, Any]] = list(data.get("subjects") or [])[:MAX_ROWS]
    data["subjects"], data["items"] = subjects, items
    by_key = {it["key"]: it for it in items}
    old = data.get("cells") or []
    rows: List[Dict[str, Cell]] = [dict(old[i]) if i < len(old) and isinstance(old[i], dict) else {} for i in range(len(subjects))]
    inputs = data.get("inputs") or {}
    basis = str(inputs.get("basis") or "").strip()
    # 기간 표(행 = 연도·분기)에 대상 기업이 정해졌으면 — 행마다 (그 기업, 그 기간)으로 찾는다(등록 양식의 자리 채우기)
    entity = str(inputs.get("entity") or "").strip()
    row_kind = "company" if entity and kind == "period" else kind

    def who(s: Dict[str, Any]) -> Dict[str, Any]:
        return {"label": entity} if row_kind != kind else s

    if basis not in ("연결", "별도"):
        basis = ""
    total = len(subjects)

    scope = await asyncio.to_thread(Scope, doc_ids, choices)
    period = period_key(str(inputs.get("period") or "")) if inputs.get("period") else ""
    if not period and kind != "period":
        period = await asyncio.to_thread(auto_period, scope, subjects, kind, items, basis)
    data["period"] = {"key": period, "label": period_label(period)} if period else None

    async def emit(done: int) -> None:
        data["cells"] = rows
        data["columns"] = format_columns(items, rows)
        data["progress"] = {"done": done, "total": total}
        if on_progress:
            await on_progress(copy.deepcopy(data))

    def ledger_pass() -> List[Tuple[int, List[str], bool, List[Dict[str, Any]], Dict[str, str]]]:
        pending = []
        for i, s in enumerate(subjects):
            docs, strong = _row_docs(scope, who(s), row_kind)
            row_pk = _row_period(kind, s, period)
            periods: Dict[str, str] = {}
            todo: List[Dict[str, Any]] = []
            for it in items:
                if it["key"] in rows[i] or it["type"] == "calc":
                    continue
                if it["type"] == "number":
                    pk = shift_period(row_pk, it.get("periodOffset") or 0)
                    periods[it["key"]] = pk
                    hits = ledger_hits(scope, who(s), row_kind, docs, strong, metric_key(it.get("metric") or it["label"]), pk, basis) if pk else []
                    f, alts = choose(scope, hits)
                    if f:
                        rows[i][it["key"]] = number_cell(f, "ledger", alts)
                        continue
                todo.append(it)
            pending.append((i, docs, strong, todo, periods))
        return pending

    pending = await asyncio.to_thread(ledger_pass)
    for i in range(len(subjects)):
        for it in items:
            if it["type"] == "calc":
                rows[i][it["key"]] = calc_cell(it, rows[i], by_key)
    await emit(sum(1 for p in pending if not p[3]))

    need = [p for p in pending if p[3]]
    if need and llm is not None:
        sem = asyncio.Semaphore(ROW_CONCURRENCY)
        done = total - len(need)

        async def one(p: Tuple[int, List[str], bool, List[Dict[str, Any]], Dict[str, str]]) -> None:
            nonlocal done
            i, docs, strong, todo, periods = p
            async with sem:
                got = await llm_row(llm, scope, row_kind, who(subjects[i]), docs, strong, todo, periods)
            rows[i].update(got)
            for it in items:
                if it["type"] == "calc":
                    rows[i][it["key"]] = calc_cell(it, rows[i], by_key)
            done += 1
            await emit(done)

        await asyncio.gather(*(one(p) for p in need))
    else:
        for i, _d, _s, todo, _p in need:
            for it in todo:
                rows[i].setdefault(it["key"], empty())
    await emit(total)
    return data


def new_data(spec: Dict[str, Any], subjects: List[Dict[str, Any]], inputs: Dict[str, Any], template_id: Optional[str] = None, items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "spec": copy.deepcopy(spec),
        "templateId": template_id,
        "subjects": [{k: v for k, v in s.items() if k in ("label", "docId")} for s in subjects if s.get("label")][:MAX_ROWS],
        "items": copy.deepcopy(items if items is not None else spec.get("items") or []),
        "inputs": {k: v for k, v in (inputs or {}).items() if k in ("period", "basis", "entity") and v},
        "cells": [],
        "progress": {"done": 0, "total": len(subjects)},
    }


def used_doc_ids(data: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for row in data.get("cells") or []:
        for c in row.values():
            out.extend([c["docId"]] if c.get("docId") else [])
            out.extend(x["docId"] for x in c.get("cites") or [])
            out.extend(c.get("docIds") or [])
    return list(dict.fromkeys(out))
