"""작성기와 근거 원장 사이 — 원장 수치를 브리프에 싣고(F번호·S번호), calculate 도구로 파생 수치를 코드가 계산하고,
다 쓴 본문의 숫자를 원장·계산 결과와 대조한다. 숫자는 코드가 — LLM 은 고르고 옮길 뿐이다.

 - select_figures: 섹션 질의와 겹치는 원장 묶음(채택값·일치값 우선, 충돌은 충돌로 표시)
 - LedgerBook: F번호 ↔ figure, 계산 기록(calcs). calculate 도구 처리기
 - number_checks: 본문 속 금액·비율이 원장 값·계산 결과·사용자 입력 가운데 하나와 같은가(반올림 차이까지 — 같은 자릿수 한 단위 차이는 다름)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.docs.citations import tokens
from app.docs.search_tool import SourceBook
from app.docs.store import load_chunks
from app.ledger.calc import CalcError, evaluate, readable, refs_in
from app.ledger.figures import Figure, workspace_ledger
from app.ledger.numbers import find_amounts, human_amount, is_rounding_of, korean_amount, same_value
from app.ledger.service import doc_labels

BRIEF_MAX = 28
_TOKEN = re.compile(r"[A-Za-z]{2,}|[가-힣]{2,}|\d{4}")

CALC_TOOL_NAME = "calculate"
CALC_TOOL_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": CALC_TOOL_NAME,
        "description": (
            "증감률·비율·차이 같은 파생 수치를 계산한다(직접 계산하지 말고 반드시 이 도구로). '근거 원장' 블록의 F번호로 식을 쓴다. "
            "함수: growth(새, 옛)=증감률%, ratio(분자, 분모)=비율%, cagr(끝, 시작, 햇수)=연평균 성장률%, diff(a, b)=차이. 예: growth(F3, F1)"
        ),
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "F번호와 함수로 쓴 식"}, "label": {"type": "string", "description": "무엇을 계산하는지(예: 2024년 매출 증가율)"}},
            "required": ["expression"],
        },
    },
}


def _terms(text: str) -> set:
    return {t.lower() for t in _TOKEN.findall(text or "")}


def _chunk(doc_id: str, chunk_id: str) -> Optional[Dict[str, Any]]:
    return next((c for c in load_chunks(doc_id) if c.get("id") == chunk_id), None)


class LedgerBook:
    """한 번의 섹션 작성에서 브리프에 보인 원장 수치(F번호)와 계산 기록."""

    def __init__(self) -> None:
        self.refs: Dict[str, Figure] = {}
        self.calcs: List[Dict[str, Any]] = []
        self.figures: List[Figure] = []  # 대조용 — 워크스페이스 원장 전체

    def add(self, f: Figure) -> str:
        for k, v in self.refs.items():
            if v["fid"] == f["fid"]:
                return k
        k = f"F{len(self.refs) + 1}"
        self.refs[k] = f
        return k

    def calculate(self, args: Dict[str, Any]) -> str:
        expr = str(args.get("expression") or "").strip()
        label = str(args.get("label") or "").strip() or "계산"
        if not expr:
            return "식이 비었습니다. 예: growth(F3, F1)"
        missing = [r for r in refs_in(expr) if r not in self.refs]
        if missing:
            return f"없는 원장 번호: {', '.join(missing)}. '근거 원장' 블록의 F번호만 쓴다."
        # 단위 표기가 없는 칸(3,200)과 단위가 있는 칸(2,800 억원 = 2.8e11)을 섞으면 배율이 달라 엉뚱한 값(-100%)이 나온다
        amounts = [r for r in dict.fromkeys(refs_in(expr)) if not self.refs[r].get("percent")]
        bare = [r for r in amounts if not self.refs[r].get("unitKnown", True)]
        if bare and len(bare) < len(amounts):
            listed = ", ".join(f"{r}={_shown(self.refs[r])}" for r in bare)
            return f"계산 안 함: 단위 표기가 없는 수치({listed})와 단위가 있는 수치를 섞을 수 없다. 같은 자료의 수치끼리 계산하거나, 단위를 알 수 없다고 밝힌다."
        try:
            value = evaluate(expr, {k: float(v["abs"]) for k, v in self.refs.items()})
        except CalcError as e:
            return f"계산 실패: {e}"
        names = {k: f"{v['metric']} {v['period']} {v.get('display') or v['raw']}" for k, v in self.refs.items()}
        percent = bool(re.match(r"\s*(growth|ratio|cagr)\(", expr))
        inputs = [self.refs[r] for r in refs_in(expr)]
        currency = next((f.get("currency") for f in inputs if f.get("currency")), None)
        if percent:
            display = f"{value:.1f}%"
        elif re.match(r"\s*diff\(", expr) or all(not f.get("percent") for f in inputs) and ("+" in expr or "-" in expr):
            display = human_amount(value, currency)
        else:
            display = f"{value:,.4g}"
        calc = {"label": label, "expression": expr, "readable": readable(expr, names), "value": value, "display": display, "percent": percent, "inputs": [f["fid"] for f in inputs]}
        self.calcs.append(calc)
        cites = ", ".join(dict.fromkeys(f"[S{f['_s']}]" for f in inputs if f.get("_s")))
        return f"결과: {label} = {display}\n계산식: {calc['readable']}\n[내부 메모] 이 값을 그대로 쓰고, 문장 끝에 입력 수치의 출처 {cites} 를 단다."


def select_figures(doc_ids: Sequence[str], choices: Dict[str, Dict[str, Any]], queries: Sequence[str], book: SourceBook, lb: LedgerBook) -> List[str]:
    """브리프의 '근거 원장' 줄들. 원장 전체는 lb.figures 에 담아 대조에 쓴다."""
    led = workspace_ledger(list(doc_ids), doc_labels(list(doc_ids)), choices)
    lb.figures = led["figures"]
    by_fid = {f["fid"]: f for f in led["figures"]}
    want = set().union(*(_terms(q) for q in queries)) if queries else set()
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for g in led["groups"]:
        terms = _terms(f"{g['metric']} {g['metricKey']} {g['period']}")
        overlap = len(terms & want)
        if not overlap and want:
            continue
        bonus = 0.5 if g.get("chosen") else (0.2 if g["documents"] > 1 and not g["conflict"] else 0.0)
        scored.append((overlap + bonus, g))
    scored.sort(key=lambda x: (-x[0], x[1]["metric"], x[1]["periodKey"]))
    lines: List[str] = []
    for _s, g in scored[:BRIEF_MAX]:
        if g["conflict"] and not g.get("chosen"):
            parts = []
            for v in g["values"]:
                f = by_fid[v["figureIds"][0]]
                s_no = _register(book, f)
                k = lb.add({**f, "_s": s_no})
                parts.append(f"{k}={_shown(f)}({f['docLabel']}) [S{s_no}]")
            lines.append(f"[충돌] {g['metric']} · {g['period']}{' · ' + g['basis'] if g.get('basis') else ''}: " + " / ".join(parts) + " — 자료마다 값이 다르다. 하나를 고르지 말고 다름을 밝힌다.")
            continue
        fid = (g.get("chosen") or {}).get("figureId") or (g.get("value") or {}).get("figureId")
        f = by_fid.get(fid or "")
        if not f:
            continue
        s_no = _register(book, f)
        k = lb.add({**f, "_s": s_no})
        tag = " (채택값)" if g.get("chosen") else (f" ({g['documents']}개 자료 일치)" if g["documents"] > 1 else "")
        approx = approx_note(f)
        lines.append(f"{k} [S{s_no}] {g['metric']} · {g['period']}{' · ' + g['basis'] if g.get('basis') else ''} = {_shown(f)}{approx}{tag}")
    lines += precompute_changes([g for _s, g in scored], by_fid, book, lb)
    return lines


CHANGES_MAX = 12


def _year(period_key: str) -> Optional[int]:
    return int(period_key) if re.fullmatch(r"\d{4}", period_key or "") else None


def precompute_changes(groups: Sequence[Dict[str, Any]], by_fid: Dict[str, Figure], book: SourceBook, lb: LedgerBook) -> List[str]:
    """연속한 두 해(같은 지표·기준·금액/비율)의 전년 대비 증감을 **코드가 미리 계산**해 브리프에 싣는다.
    작성 모델이 계산 도구를 한 번씩 부르며 왕복하지 않게(속도) — 직접 계산하지도 않게.
    금액 = 증감률(%), 비율 지표 = 차이(%p). 올해 값이 자료마다 다르면(미채택) 값마다 따로, 작년 값이 다르면 건너뛴다.
    결과는 lb.calcs 에 auto=True 로 들어가 숫자 대조가 '계산값'으로 알아보고, 본문에 안 쓴 것은 작성 끝에 뺀다."""
    idx: Dict[Tuple[str, str, bool, int], Dict[str, Any]] = {}
    for g in groups:
        y = _year(g["periodKey"])
        if y is not None:
            idx[(g["metricKey"], g.get("basis") or "", g["key"].split("|")[2] == "%", y)] = g

    def rep(g: Dict[str, Any]) -> Optional[Figure]:
        fid = (g.get("chosen") or {}).get("figureId") or (None if g["conflict"] else (g.get("value") or {}).get("figureId"))
        return by_fid.get(fid or "")

    def variants(g: Dict[str, Any]) -> List[Figure]:
        if not g.get("chosen") and g["conflict"]:
            return [by_fid[v["figureIds"][0]] for v in g["values"] if v["figureIds"][0] in by_fid]
        f = rep(g)
        return [f] if f else []

    def ref(f: Figure) -> Tuple[str, int]:
        s_no = _register(book, f)
        return lb.add({**f, "_s": s_no}), s_no

    out: List[str] = []
    for (mk, basis, pct, y), g in sorted(idx.items(), key=lambda kv: (kv[1]["metric"], -kv[0][3])):
        prev = idx.get((mk, basis, pct, y - 1))
        old = rep(prev) if prev else None
        if old is None:
            continue
        news = variants(g)
        for new in news:
            if bool(new.get("unitKnown", True)) != bool(old.get("unitKnown", True)):
                continue
            kn, sn = ref(new)
            ko, so = ref(old)
            who = f" — {new.get('docLabel')} 값 기준" if len(news) > 1 else ""
            label = f"{g['metric']} {y} 전년 대비"
            if pct:
                value = float(new["value"]) - float(old["value"])
                expr = f"diff({kn}, {ko})"
                names = {k: f"{v['metric']} {v['period']} {v.get('display') or v['raw']}" for k, v in lb.refs.items()}
                calc = {"label": label, "expression": expr, "readable": readable(expr, names), "value": value, "display": f"{abs(value):.1f}%p", "percent": True, "inputs": [new["fid"], old["fid"]], "auto": True}
                lb.calcs.append(calc)
                word = "상승" if value > 0 else "하락" if value < 0 else "변화 없음"
                out.append(f"[계산] {label}: {calc['display']} {word} (= {new.get('display') or new['raw']} − {old.get('display') or old['raw']}){who} {_cites(sn, so)}")
            else:
                before = len(lb.calcs)
                lb.calculate({"expression": f"growth({kn}, {ko})", "label": label})
                if len(lb.calcs) == before:
                    continue  # 단위가 섞였거나 0 으로 나눔 — 계산 도구가 거절
                calc = lb.calcs[-1]
                calc["auto"] = True
                calc["display"] = f"{abs(calc['value']):.1f}%"
                word = "증가" if calc["value"] > 0 else "감소" if calc["value"] < 0 else "변화 없음"
                out.append(f"[계산] {label}: {calc['display']} {word} (= {new.get('display') or new['raw']} ÷ {old.get('display') or old['raw']} − 1){who} {_cites(sn, so)}")
            if len(out) >= CHANGES_MAX:
                return out
    return out


def _cites(*nums: int) -> str:
    return "".join(f"[S{n}]" for n in dict.fromkeys(nums))


def used_calcs(content: str, calcs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """미리 계산한 것(auto) 중 본문에 실제로 쓴 값만 남긴다(도구로 부른 계산은 모두 남긴다)."""
    plain = re.sub(r"\[@[^\]]+\]", "", content or "")
    amounts = [a for a in find_amounts(plain) if a["percent"]]
    return [c for c in calcs if not c.get("auto") or any(is_rounding_of(abs(a["value"]), a["step"], abs(c["value"])) for a in amounts)]


def approx_note(f: Figure) -> str:
    """원장 줄 옆의 한국어 단위 표기 — 본문에 이대로 옮겨 쓰면 숫자 확인이 맞춘다.
    원화: 억원 아래 배율 칸만(3,150 억원 칸은 이미 읽기 쉬움) / 외화(크로네 등): 1억 이상이면 배율과 상관없이(13,841 십억 크로네 → 13조 8,410억 크로네)."""
    if f.get("percent") or abs(f.get("abs") or 0) < 1e8:
        return ""
    cur = f.get("currency")
    if cur == "KRW" and f.get("scale", 1) < 1e8:
        return f" (≈ {human_amount(f['abs'], 'KRW')})"
    if cur and cur != "KRW":
        return f" (= {korean_amount(f['abs'], cur)})"
    return ""


def _shown(f: Figure) -> str:
    """표기 값 — 단위를 표에서 못 찾은 금액은 그렇다고 붙인다(모델이 억원 등으로 짐작하지 않게)."""
    v = f.get("display") or f["raw"]
    return v if f.get("percent") or f.get("unitKnown", True) else f"{v} (단위 표기 없음)"


def _register(book: SourceBook, f: Figure) -> int:
    ch = _chunk(f["doc"], f["chunk"]) or {"id": f["chunk"], "text": "", "page": f.get("page")}
    return book.add(f["doc"], ch, f.get("docLabel") or f["doc"][:8])


def number_checks(content: str, lb: LedgerBook, user_values: Sequence[str] = ()) -> Dict[str, Any]:
    """본문 속 금액·비율 → 원장·계산·사용자 입력·인용한 문단 글과 대조. 출처 토큰이 있는데 어디에도 없는 숫자 = mismatched.
    인용한 문단 글은 숫자 확인 탭(report/number_check)의 '인용한 자료의 근거'와 같은 기준 — 표 칸이 아닌 글 속 수치(시나리오·비중 등)."""
    checked = 0
    matched = 0
    mismatched: List[str] = []
    user_text = " ".join(user_values)
    chunks: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def in_cited_text(a: Dict[str, Any], d: str, c: str) -> bool:
        if d not in chunks:
            chunks[d] = {x.get("id"): x for x in load_chunks(d)}
        for b in find_amounts((chunks[d].get(c) or {}).get("text") or ""):
            if bool(b["percent"]) == bool(a["percent"]) and (same_value(a["abs"], a["step"], b["abs"], b["step"]) or (not b.get("unit") and same_value(a["value"], 10 ** -a["decimals"], b["value"], 10 ** -b.get("decimals", 0)))):
                return True
        return False
    for sent in re.split(r"(?<=[.!?。])\s+|\n+", content or ""):
        if not sent.strip():
            continue
        plain = re.sub(r"\[@[^\]]+\]", "", sent)
        has_cite = bool(tokens(sent))
        for a in find_amounts(plain):
            checked += 1
            ok = False
            for f in lb.figures:
                if bool(f.get("percent")) != bool(a["percent"]):
                    continue
                if same_value(a["abs"], a["step"], f["abs"], f["step"]) or (not f.get("unitKnown", True) and same_value(a["value"], 10 ** -a["decimals"], f["value"], 10 ** -f.get("decimals", 0))):
                    ok = True
                    break
            if not ok:
                for c in lb.calcs:
                    if c["percent"] and a["percent"] and is_rounding_of(abs(a["value"]), a["step"], abs(c["value"])):
                        ok = True
                        break
                    if not c["percent"] and not a["percent"] and is_rounding_of(a["abs"], a["step"], c["value"]):
                        ok = True
                        break
            if not ok and a.get("pp"):
                # %p 는 같은 문장의 두 비율의 차이면 확인된 파생 수치(예: 10.0%→11.0%, 1.0%p)
                pcts = [b["value"] for b in find_amounts(plain) if b["percent"] and not b.get("pp")]
                ok = any(is_rounding_of(abs(a["value"]), a["step"], abs(x - y)) for i, x in enumerate(pcts) for y in pcts[i + 1 :])
            if not ok and a["raw"].replace(" ", "") in user_text.replace(" ", ""):
                ok = True
            if not ok and has_cite:
                ok = any(in_cited_text(a, d, c) for d, c in tokens(sent))
            if ok:
                matched += 1
            elif has_cite:
                where = re.sub(r"\s+", " ", plain).strip()[:120]
                mismatched.append(f"{a['raw']} — {where}")
    return {"checked": checked, "matched": matched, "mismatched": mismatched[:6]}
