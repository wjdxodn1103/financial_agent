"""검수 규칙 — 대상 문서의 숫자 주장을 워크스페이스 근거 원장(대상 문서를 뺀 자료들)과 대조한다. 전부 결정적.

규칙 등록표(RULES)에 하나씩 — 기관 내규 기반 점검표 같은 규칙은 여기에 더한다.
  mismatch  같은 지표·기간·기준의 근거 값과 다르다(채택값이 있으면 채택값과)
  unsourced 근거 자료에서 그 지표·기간을 찾지 못했다
  calc      '전년 대비 12.5% 증가' 같은 변화율이 근거(또는 문서 자신의) 두 값으로 계산한 값과 다르다
  internal  같은 문서 안에서 같은 지표·기간의 값이 다르다
결과에는 근거(원장 수치·원문 위치)와 계산식을 함께 남긴다.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.ledger.calc import readable
from app.ledger.figures import Figure
from app.ledger.numbers import human_amount, same_value, step_of

Claim = Dict[str, Any]
Finding = Dict[str, Any]
RULE_KO = {"mismatch": "불일치", "unsourced": "근거 없음", "calc": "계산 오류", "internal": "문서 내부 불일치", "ok": "일치"}


def _same(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    if a.get("unitKnown", True) and b.get("unitKnown", True):
        return same_value(a["abs"], a["step"], b["abs"], b["step"])
    return same_value(a["value"], step_of(a.get("decimals", 0), 1.0), b["value"], step_of(b.get("decimals", 0), 1.0))


def _basis_ok(c: Claim, f: Figure) -> bool:
    return not (c.get("basis") and f.get("basis") and c["basis"] != f["basis"])


def _ev(f: Figure) -> Dict[str, Any]:
    return {"fid": f["fid"], "docId": f["doc"], "docLabel": f.get("docLabel") or f["doc"][:8], "chunk": f["chunk"], "cell": f.get("cell"), "display": f.get("display") or f["raw"], "page": f.get("page"), "sheet": f.get("sheet")}


class Ctx:
    def __init__(self, figures: Sequence[Figure], choices: Dict[str, Dict[str, Any]], groups: Sequence[Dict[str, Any]]):
        self.idx: Dict[Tuple[str, str], List[Figure]] = {}
        for f in figures:
            self.idx.setdefault((f["metricKey"], f["periodKey"]), []).append(f)
        self.chosen = {g["key"].rsplit("|", 1)[0] + "|" + (g.get("basis") or ""): (g.get("chosen") or {}).get("figureId") for g in groups if g.get("chosen")}
        self.by_fid = {f["fid"]: f for f in figures}

    def candidates(self, c: Claim, period_key: Optional[str] = None) -> List[Figure]:
        pk = c["periodKey"] if period_key is None else period_key
        return [f for f in self.idx.get((c["metricKey"], pk), []) if bool(f.get("percent")) == bool(c.get("percent")) and _basis_ok(c, f)]

    def expected(self, c: Claim, cands: List[Figure]) -> Figure:
        """기대값 — 채택값, 없으면 가장 많은 자료가 같은 값."""
        key = f"{c['metricKey']}|{c['periodKey']}|{'%' if c.get('percent') else '#'}|{c.get('basis') or (cands[0].get('basis') or '')}"
        fid = self.chosen.get(key)
        if fid and fid in self.by_fid:
            return self.by_fid[fid]
        clusters: List[List[Figure]] = []
        for f in cands:
            for cl in clusters:
                if _same(f, cl[0]):
                    cl.append(f)
                    break
            else:
                clusters.append([f])
        return max(clusters, key=len)[0]


def r_match(claims: Sequence[Claim], ctx: Ctx) -> List[Finding]:
    out: List[Finding] = []
    for c in claims:
        if c["kind"] != "figure":
            continue
        if not c["periodKey"]:
            continue  # 기간을 알 수 없는 숫자는 대조하지 않는다(요약의 '확인 불가'로 센다)
        cands = ctx.candidates(c)
        if not cands:
            out.append({"rule": "unsourced", "severity": "medium", "claimId": c["id"], "message": f"근거 자료에서 '{c['metric']} {c['period']}' 값을 찾지 못했습니다.", "evidence": []})
            continue
        hits = [f for f in cands if _same(c, f)]
        if hits:
            out.append({"rule": "ok", "severity": "info", "claimId": c["id"], "message": f"{hits[0].get('docLabel')} 등 {len({h['doc'] for h in hits})}개 자료와 일치", "evidence": [_ev(h) for h in hits[:3]]})
            continue
        exp = ctx.expected(c, cands)
        out.append(
            {
                "rule": "mismatch",
                "severity": "high",
                "claimId": c["id"],
                "message": f"문서는 {c['raw']}, 근거 자료는 {exp.get('display') or exp['raw']}({exp.get('docLabel')})입니다.",
                "expected": _ev(exp),
                "evidence": [_ev(f) for f in cands[:4]],
            }
        )
    return out


def _value_for(c: Claim, period_key: str, ctx: Ctx, own: Sequence[Claim]) -> Optional[Tuple[float, str, Optional[Dict[str, Any]]]]:
    """변화율 계산의 입력 — 근거 원장 값(기대값) 또는 문서 자신의 값. → (abs, 표기, 근거)"""
    probe = {**c, "kind": "figure", "percent": False, "periodKey": period_key}
    cands = [f for f in ctx.idx.get((c["metricKey"], period_key), []) if not f.get("percent") and _basis_ok(c, f)]
    if cands:
        f = ctx.expected(probe, cands)
        return f["abs"], f.get("display") or f["raw"], _ev(f)
    for o in own:
        if o["kind"] == "figure" and o["metricKey"] == c["metricKey"] and o["periodKey"] == period_key and not o.get("percent"):
            return o["abs"], o["raw"], None
    return None


def r_calc(claims: Sequence[Claim], ctx: Ctx) -> List[Finding]:
    out: List[Finding] = []
    for c in claims:
        if c["kind"] != "change" or not c["periodKey"] or not c.get("basePeriodKey"):
            continue
        cur = _value_for(c, c["periodKey"], ctx, claims)
        base = _value_for(c, c["basePeriodKey"], ctx, claims)
        if not cur or not base or base[0] == 0:
            continue
        if c.get("percent") and not c.get("pp"):
            computed = (cur[0] / base[0] - 1.0) * 100.0
            tol = max(c["step"], 0.05) + 0.05
            stated = abs(c["value"])
            sign_ok = True
            q = c.get("quote") or ""
            if any(w in q for w in ("감소", "줄", "하락", "축소", "악화")) and computed > 0:
                sign_ok = False
            if any(w in q for w in ("증가", "늘", "상승", "성장", "확대", "개선")) and computed < 0:
                sign_ok = False
            if abs(abs(computed) - stated) <= tol and sign_ok:
                continue
            formula = readable("growth(A, B)", {"A": f"{c['metric']} {c['period']} {cur[1]}", "B": f"{c['metric']} {c['basePeriod']} {base[1]}"})
            out.append(
                {
                    "rule": "calc",
                    "severity": "high",
                    "claimId": c["id"],
                    "message": f"문서는 {c['raw']}{'' if sign_ok else '(방향 반대)'}, 두 값으로 계산하면 {computed:+.1f}% 입니다.",
                    "formula": f"{formula} = {computed:+.1f}%",
                    "computed": computed,
                    "evidence": [e for e in (cur[2], base[2]) if e],
                }
            )
        elif not c.get("percent"):
            diff = cur[0] - base[0]
            if same_value(abs(diff), max(cur[0], base[0]) * 1e-9 + 1, abs(c["abs"]), c["step"]):
                continue
            out.append(
                {
                    "rule": "calc",
                    "severity": "high",
                    "claimId": c["id"],
                    "message": f"문서는 증감 {c['raw']}, 두 값의 차이는 {human_amount(diff, c.get('currency') or 'KRW')} 입니다.",
                    "formula": f"{c['metric']} {c['period']} {cur[1]} − {c['basePeriod']} {base[1]}",
                    "computed": diff,
                    "evidence": [e for e in (cur[2], base[2]) if e],
                }
            )
    return out


def r_internal(claims: Sequence[Claim], ctx: Ctx) -> List[Finding]:
    out: List[Finding] = []
    base: Dict[Tuple[str, str, bool], List[Claim]] = {}
    for c in claims:
        if c["kind"] == "figure" and c["periodKey"]:
            base.setdefault((c["metricKey"], c["periodKey"], bool(c.get("percent"))), []).append(c)
    groups: List[List[Claim]] = []
    for cs in base.values():
        # 연결·별도가 둘 다 보이면 나눠 비교, 기준을 모르는 숫자는 아는 쪽과 같이 본다(원장 묶음과 같은 규칙)
        known = {c.get("basis") for c in cs if c.get("basis")}
        if len(known) < 2:
            groups.append(cs)
        else:
            groups.extend([[c for c in cs if c.get("basis") == b] for b in known] + [[c for c in cs if not c.get("basis")]])
    for cs in groups:
        distinct: List[Claim] = []
        for c in cs:
            if not any(_same(c, d) for d in distinct):
                distinct.append(c)
        if len(distinct) > 1:
            vals = ", ".join(f"{d['raw']}" for d in distinct)
            for d in distinct[1:]:
                out.append({"rule": "internal", "severity": "medium", "claimId": d["id"], "relatedClaimIds": [x["id"] for x in distinct if x is not d], "message": f"같은 문서 안에서 '{d['metric']} {d['period']}' 값이 다릅니다: {vals}", "evidence": []})
    return out


RULES: List[Tuple[str, Callable[[Sequence[Claim], Ctx], List[Finding]]]] = [
    ("match", r_match),
    ("calc", r_calc),
    ("internal", r_internal),
]


_FLAT = re.compile(r"[\s·・,.\-_/]")


def align_metrics(claims: Sequence[Claim], figures: Sequence[Figure]) -> List[Claim]:
    """추출이 지표 이름을 줄인 주장('변동금리 차입금은 1,200억원' → 차입금)을 원장의 더 긴 지표로 바로잡는다 — 새 목록(입력은 그대로).
    원장의 지표 이름이 문장에 그대로 있고 주장의 지표 이름을 품으며 같은 기간에 값이 있을 때, 그리고
      ① 줄인 이름으로는 원장에 같은 기간 값이 없거나 ② 있어도 값이 다른데 긴 이름 쪽 값과는 같을 때만.
    문장에 맞는 긴 이름이 여럿이면 가장 긴 것 하나일 때만 바꾼다(애매하면 그대로). 변화율 주장은 ①만."""
    ctx = Ctx(figures, {}, [])
    names: Dict[str, Dict[str, str]] = {}
    for f in figures:
        names.setdefault(f["periodKey"], {}).setdefault(f["metricKey"], f["metric"])
    out: List[Claim] = []
    for c in claims:
        pk, mk = c.get("periodKey"), str(c.get("metricKey") or "")
        quote = _FLAT.sub("", c.get("quote") or "").lower()
        longer = [k for k in names.get(pk or "", {}) if mk and k != mk and mk.lower() in k.lower() and k.lower() in quote]
        best = [k for k in longer if len(k) == max(map(len, longer))] if longer else []
        if len(best) != 1:
            out.append(c)
            continue
        alt = {**c, "metricKey": best[0], "metric": names[pk][best[0]]}
        if c["kind"] == "figure":
            own = ctx.candidates(c)
            keep = bool(own) and (any(_same(c, f) for f in own) or not any(_same(c, f) for f in ctx.candidates(alt)))
        else:
            keep = (mk, pk) in ctx.idx
        out.append(c if keep else alt)
    return out


def run_rules(claims: Sequence[Claim], figures: Sequence[Figure], choices: Dict[str, Dict[str, Any]], groups: Sequence[Dict[str, Any]]) -> Tuple[List[Finding], Dict[str, Any]]:
    ctx = Ctx(figures, choices, groups)
    findings: List[Finding] = []
    for _name, rule in RULES:
        findings.extend(rule(claims, ctx))
    for i, f in enumerate(findings, 1):
        f["id"] = f"f{i}"
    counts = Counter(f["rule"] for f in findings)
    unverifiable = sum(1 for c in claims if c["kind"] == "figure" and not c["periodKey"])
    summary = {"claims": len(claims), "counts": {k: counts.get(k, 0) for k in RULE_KO}, "unverifiable": unverifiable}
    return findings, summary
