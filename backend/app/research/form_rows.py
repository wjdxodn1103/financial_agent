"""양식 2.0 표 채우기 — 틀의 표 양식(행·열 그대로) + 원장 → 표 블록. LLM 0회, 동기(문서 보기·숫자 확인·내보내기가 자주 부른다 — 캐시).

행 = 양식의 행(계정·지표, 들여쓰기·굵게·묶음 그대로), 열 = 양식의 기간 열(실적 열은 자료의 최근 연도로 옮김 — forms.shift_years, F·E 열은 비움).
칸 = 행 종류(research/fs_rows.py)대로: 원장 값(대상 기업 자료에서, 칸마다 원문 칸 fid) · 같은 기간 계산(ratio·times·diff·avg) ·
     위 행의 전년 대비(적자 끼면 적지·적전·흑전) · 자료가 없는 행은 빈 칸(이유를 칸 설명에).
블록 모양은 research/block.to_block 과 같은 칸(cell_view: kind·text·num·title·fid·docId·chunk·cell) — 화면 칸 클릭 출처·숫자 확인·Word 가 그대로 쓴다.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.docs.store import doc_dir, doc_label, load_meta
from app.ledger.figures import period_key
from app.research import entities
from app.research.forms import shift_years
from app.research.fs_rows import asof_spec, returns_metric, row_spec

_FORECAST = re.compile(r"[EF]$")
_YOY_HEAD = re.compile(r"YoY|증감률|증가율|성장률", re.I)
_DAY_MARK = re.compile(r"\(\s*\d{1,2}\s*/\s*\d{1,2}\s*\)")
_SCALE = {"조원": 1e12, "십억원": 1e9, "억원": 1e8, "백만원": 1e6, "천원": 1e3, "원": 1.0}
_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}


def _fmt(v: float, decimals: int) -> str:
    s = f"{v:,.{decimals}f}"
    return s[1:] if re.fullmatch(r"-0(?:\.0+)?", s) else s  # '-0' → '0'


class _Book:
    """대상 기업 자료의 원장 — (metric_key, 연도) → 고른 값."""

    def __init__(self, doc_ids: Sequence[str], entity: str, choices: Dict[str, Dict[str, Any]]):
        from app.research.fill import Scope

        self.scope = Scope(doc_ids, choices or {})
        docs = entities.company_docs(self.scope.doc_ids, entity) if entity else []
        self.docs = set(docs or self.scope.doc_ids)
        self.used: List[str] = []

    def latest_year(self) -> Optional[int]:
        """최근 연간 실적 연도 — 핵심 계정(매출액·영업이익·순이익·자산총계)의 연도만(주가 요약 같은 날짜 표의 연도는 빼고)."""
        core = {"매출액", "영업이익", "당기순이익", "자산총계"}
        ys = [int(f["periodKey"]) for f in self.scope.figs if f["doc"] in self.docs and f.get("metricKey") in core and re.fullmatch(r"(?:19|20)\d{2}", str(f.get("periodKey") or ""))]
        return max(ys) if ys else None

    def get(self, mks: Sequence[str], pk: Optional[str]) -> Optional[Dict[str, Any]]:
        """pk = 기간 키. None 이면 가장 최근 값(시점 값 표 — 기간 글의 날짜 'YYYY-MM-DD' 가 있으면 그것, 없으면 기간 키로 최근)."""
        from app.research.fill import choose

        for mk in mks:
            hits = [f for f in self.scope.figs if f["doc"] in self.docs and f.get("metricKey") == mk and (pk is None or f.get("periodKey") == pk)]
            if pk is None and hits:
                top = max(_recency(f) for f in hits)
                hits = [f for f in hits if _recency(f) == top]
            f, _alts = choose(self.scope, hits)
            if f is not None:
                if f["doc"] not in self.used:
                    self.used.append(f["doc"])
                return f
        return None


def _recency(f: Dict[str, Any]) -> str:
    m = re.search(r"\d{4}-\d{2}-\d{2}", str(f.get("period") or ""))
    return m.group(0) if m else str(f.get("periodKey") or "")


def _prev(pk: str) -> str:
    return str(int(pk) - 1) if re.fullmatch(r"\d{4}", pk) else ""


# ── 식 ──────────────────────────────────────────────────────────────────────

def _split_args(s: str) -> List[str]:
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""; continue
        depth += ch == "("
        depth -= ch == ")"
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def _eval(expr: str, pk: str, book: _Book, inputs: List[Dict[str, Any]]) -> Optional[float]:
    """ratio(a,b)·times(a,b)·diff(a,b)·avg(x) — a·b 는 계정 metric_key 또는 식. 값은 원 단위(abs). 하나라도 없으면 None."""
    expr = expr.strip()
    m = re.fullmatch(r"(\w+)\((.*)\)", expr)
    if not m:
        f = book.get(expr.split("|"), pk)  # 'a|b' = a 가 없으면 b(지배주주순이익 → 당기순이익)
        if f is None:
            return None
        inputs.append(f)
        return float(f["abs"])
    fn, args = m.group(1), _split_args(m.group(2))
    if fn == "avg":
        a = _eval(args[0], pk, book, inputs)
        b = _eval(args[0], _prev(pk), book, inputs) if _prev(pk) else None
        return None if a is None or b is None else (a + b) / 2
    vals = [_eval(a, pk, book, inputs) for a in args]
    if any(v is None for v in vals):
        return None
    a, b = vals[0], vals[1]
    if fn == "diff":
        return a - b
    if fn == "mul":
        return a * b
    if b == 0:
        return None
    return a / b * 100 if fn == "ratio" else a / b


def _value(spec: Dict[str, Any], pk: str, book: _Book, inputs: List[Dict[str, Any]]) -> Optional[float]:
    """값 행·계산 행의 그 기간 값(원 단위) — 증가율 행이 기준 행의 이번·전년 값을 구할 때."""
    if spec.get("calc"):
        return _eval(spec["calc"], pk, book, inputs)
    f = book.get(spec["ledger"], pk)
    if f is None:
        return None
    inputs.append(f)
    return float(f["abs"])


def _readable(expr: str) -> str:
    return expr.replace("ratio(", "비율(").replace("times(", "배수(").replace("diff(", "차이(").replace("avg(", "평균(")


# ── 칸 ──────────────────────────────────────────────────────────────────────

def _scale_of(unit: str) -> float:
    return _SCALE.get(unit.replace(" ", ""), 1.0)


def _decimals(row: Dict[str, Any], kind: str, unit: str) -> int:
    if row.get("decimals") is not None:
        return int(row["decimals"])
    if kind in ("ratio", "growth", "times") or unit in ("%", "배"):
        return 1
    return 0


def _number_cell(f: Dict[str, Any], unit: str, decimals: int) -> Dict[str, Any]:
    v = float(f["abs"]) / (_scale_of(unit) if not f.get("percent") else 1.0)
    return {"kind": "number", "text": _fmt(v, decimals), "num": True, "value": v, "fid": f["fid"], "docId": f["doc"], "chunk": f["chunk"], "cell": f.get("cell"),
            "title": f"{f.get('docLabel') or ''} · {f.get('metric') or ''} {f.get('period') or ''} · {f.get('display') or f.get('raw') or ''}"}


def _empty(reason: str = "") -> Dict[str, Any]:
    return {"kind": "empty", "text": "", "num": False, "title": reason}


def fill_form(form: Dict[str, Any], doc_ids: Sequence[str], entity: str = "", choices: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """틀의 표 양식 → 표 블록(행·열·모양은 양식 그대로, 칸은 원장·계산). 같은 (양식, 자료, 원장 파일 시각)이면 캐시."""
    stamp = tuple(round((doc_dir(d) / "figures.json").stat().st_mtime, 3) if (doc_dir(d) / "figures.json").exists() else 0 for d in doc_ids)
    key = (form.get("id"), id(form) if not form.get("id") else 0, tuple(doc_ids), entity, stamp, tuple((k, str(v.get("figureId"))) for k, v in sorted((choices or {}).items())))
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    book = _Book(doc_ids, entity, choices or {})
    cols = shift_years(list(form.get("columns") or []), book.latest_year())
    pks = [period_key(c) for c in cols]
    table_unit = form.get("unit") or ""
    rows_out: List[List[Dict[str, Any]]] = []
    calcs: List[Dict[str, Any]] = []
    prev_spec: Optional[Tuple[Dict[str, Any], Dict[str, Any]]] = None  # 증가율 행이 기대는 바로 위 값 행
    yoy = False  # 'YoY증감률' 같은 머리 행 아래 — 값 행 이름(매출액)이 그 계정의 증가율 행이다(원본 '실적 추이 및 전망' 표)
    # 기간 열이 없는 표 — 시점 값(Company Data: 행마다 기준일 값 하나) · 기간 수익률(Stock Data: 열 1·6·12개월)
    labels = [r.get("label") or "" for r in form.get("rows") or []]
    asof = bool(cols) and not any(re.fullmatch(r"\d{4}", pk) for pk in pks) and any(asof_spec(x) for x in labels)
    rets = bool(cols) and any(returns_metric(x, c) for x in labels for c in cols)
    for row in form.get("rows") or []:
        label = row.get("label") or ""
        head = {"kind": "head", "text": label, "num": False, "indent": int(row.get("indent") or 0), "bold": bool(row.get("bold")), "group": bool(row.get("group")),
                **({"color": row["color"]} if row.get("color") else {})}  # 강조 행(원본 대상 기업 행 색)
        unit = row.get("unit") or table_unit
        spec = row_spec(label)
        cells: List[Dict[str, Any]] = []
        if asof or rets:
            pc = _point_cells(label, cols, book, asof, calcs)
            day = re.search(r"(\d{4})-(\d{2})-(\d{2})", (pc[0].get("title") or "") if pc else "")
            if day and _DAY_MARK.search(label):  # 샘플의 기준일 '(1/2)' → 이 값의 기준일
                head = {**head, "text": _DAY_MARK.sub(f"({int(day.group(2))}/{int(day.group(3))})", label)}
            rows_out.append([head] + pc)
            continue
        if spec is None and _YOY_HEAD.search(label.replace(" ", "")):
            yoy, prev_spec = True, None
            rows_out.append([head] + [_empty() for _ in cols])
            continue
        if row.get("group") or spec is None and not cols:
            rows_out.append([head] + [_empty() for _ in cols])
            continue
        if yoy and spec and spec.get("ledger"):
            prev_spec, spec = (row, spec), {"growth": True}  # 이 행 자신의 전년 대비
        if spec is None and _CIRCLED.match(label):  # '① 감속기' — 제품별 매출(사업보고서 매출실적 표)
            rows_out.append([head] + [_product_cell(label, form, pk, book, unit, calcs) if re.fullmatch(r"\d{4}", pk) else _empty("예상 열") for pk in pks])
            continue
        if spec and spec.get("eval"):  # 평가지표 — 연말 주가·주식 수로 계산(EPS 는 원장 그대로)
            rows_out.append([head] + [_valuation_cell(label, pk, book, calcs) if re.fullmatch(r"\d{4}", pk) else _empty("예상 열") for pk in pks])
            prev_spec = None
            continue
        kind = "growth" if spec and spec.get("growth") else "ledger" if spec and spec.get("ledger") else "calc" if spec and spec.get("calc") else "none"
        for c, pk in zip(cols, pks):
            if _FORECAST.search(pk) or not re.fullmatch(r"\d{4}", pk):
                cells.append(_empty("예상 열 — 자료에 없는 값은 비워 둡니다(입력값만)"))
                continue
            if spec is None:
                cells.append(_empty("이 행에 맞는 계정을 사전에서 찾지 못했다"))
                continue
            if kind == "ledger":
                f = book.get(spec["ledger"], pk)
                if f is not None and spec.get("sign") == -1 and float(f["abs"]) > 0:
                    f = {**f, "abs": -float(f["abs"])}  # 현금 유출(취득·상환·지급) — 공시는 양수, 표는 음수(원본 꼴)
                cells.append(_number_cell(f, unit, _decimals(row, kind, unit)) if f else _empty("자료에 이 계정·연도 값이 없다"))
            elif kind == "calc":
                ins: List[Dict[str, Any]] = []
                v = _eval(spec["calc"], pk, book, ins)
                if v is None:
                    cells.append(_empty("계산에 필요한 값이 없다"))
                    continue
                pct = spec["calc"].startswith("ratio(")
                is_times = spec["calc"].startswith("times(")
                shown = v if (pct or is_times) else v / _scale_of(unit)
                text = _fmt(shown, _decimals(row, "ratio" if pct else "times" if is_times else "ledger", unit))
                cells.append({"kind": "calc", "text": text, "num": True, "value": shown, "inputs": [f["fid"] for f in ins], "title": f"계산: {_readable(spec['calc'])}"})
                calcs.append({"label": f"{label} {c}", "expression": spec["calc"], "readable": _readable(spec["calc"]), "value": v if pct else shown * (1 if is_times else _scale_of(unit)),
                              "display": text + ("%" if pct else ""), "percent": pct, "inputs": [f["fid"] for f in ins]})
            elif kind == "growth":
                if prev_spec is None:
                    cells.append(_empty("기준 행이 없다"))
                    continue
                base_row, base_spec = prev_spec
                ins = []
                cur = _value(base_spec, pk, book, ins)
                old = _value(base_spec, _prev(pk), book, ins)
                if cur is None or old is None or old == 0:
                    cells.append(_empty("전년 값이 없다"))
                    continue
                if old < 0 or cur < 0:
                    word = "적지" if old < 0 and cur < 0 else ("흑전" if old < 0 else "적전")
                    cells.append({"kind": "text", "text": word, "num": False, "title": f"{base_row.get('label')} {_prev(pk)} → {pk}: 적자가 끼어 증가율 대신 {word}"})
                    continue
                g = (cur / old - 1) * 100
                text = _fmt(g, _decimals(row, "growth", "%"))
                cells.append({"kind": "calc", "text": text, "num": True, "value": g, "inputs": [f["fid"] for f in ins], "title": f"계산: 전년 대비({base_row.get('label')})"})
                calcs.append({"label": f"{base_row.get('label')} 증가율 {c}", "expression": f"growth({base_row.get('label')})", "readable": f"전년 대비 증가율({base_row.get('label')})",
                              "value": g, "display": text + "%", "percent": True, "inputs": [f["fid"] for f in ins]})
            else:
                cells.append(_empty(spec.get("eval") or spec.get("none") or ""))
        # 증가율 행의 기준 = 바로 위의 값 행(비율·증가율 행은 건너뜀). 자료 없는 행(EBITDA)이 기준이면 증가율도 비운다
        if kind in ("ledger", "calc") and spec and not spec.get("calc", "").startswith(("ratio(", "times(")):
            prev_spec = (row, spec)
        elif kind == "none" or (spec and spec.get("eval")):
            prev_spec = None
        rows_out.append([head] + cells)
    labels = [doc_label(load_meta(d), d) for d in book.used]
    source = "자료: " + (", ".join(labels[:2]) + (f" 외 {len(labels) - 2}건" if len(labels) > 2 else "") if labels else "자료 없음")
    filled = sum(1 for r in rows_out for c in r[1:] if c["kind"] in ("number", "calc", "text"))
    look = {"headerFill": "#FFFFFF", "headerText": "#000000", **dict(form.get("look") or {})}  # 원본 PDF 표 머리는 흰 바탕·검정 굵은 글자(색 칸이면 look 이 덮는다)
    if form.get("captionStyle"):
        look.update({"captionColor": form["captionStyle"].get("color"), "captionSize": form["captionStyle"].get("size"), "captionBold": form["captionStyle"].get("bold", True)})
    block = {"kind": "table", "blockId": form.get("id"), "formId": form.get("id"), "title": form.get("title") or "", "caption": form.get("title") or "", "unit": table_unit,
             "header": [form.get("stub") or ("" if not table_unit else f"({table_unit})")] + cols, "rows": rows_out, "sourceLine": source, "sourceDocIds": list(book.used),
             "look": look, "formName": form.get("title") or "", "position": form.get("position") or "main", "calcs": calcs, "missing": filled == 0, "headGroups": form.get("headGroups") or None,
             **({"unitNote": form["unitNote"]} if form.get("unitNote") else {})}
    _CACHE[key] = (time.time(), block)
    return block


def _point_cells(label: str, cols: List[str], book: _Book, asof: bool, calcs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """기간 열이 없는 표의 한 행 — 시점 값(첫 열에 기준일 값, 원본 꼴 '36,700원') 또는 기간 수익률(열마다 '6개월 수익률')."""
    out: List[Dict[str, Any]] = []
    for j, col in enumerate(cols):
        if asof:
            spec = asof_spec(label) if j == 0 else None
            if spec is None or spec.get("none"):
                out.append(_empty((spec or {}).get("none") or ("" if j else "이 행에 맞는 값을 사전에서 찾지 못했다")))
                continue
            if spec.get("holders"):
                out.append(_holders_cell(book))
                continue
            div, dec, tail = spec["fmt"]
            if spec.get("calc"):
                ins: List[Dict[str, Any]] = []
                v = _eval(spec["calc"], None, book, ins)
                if v is None:
                    out.append(_empty("계산에 필요한 값이 없다"))
                    continue
                text = _fmt(v / div, dec) + tail
                out.append({"kind": "calc", "text": text, "num": True, "value": v / div, "inputs": [f["fid"] for f in ins], "title": f"계산: {_readable(spec['calc'])}"})
                calcs.append({"label": label, "expression": spec["calc"], "readable": _readable(spec["calc"]), "value": v, "display": text, "percent": False,
                              "inputs": [f["fid"] for f in ins]})
                continue
            f = book.get(spec["ledger"], None)
            if f is None:
                out.append(_empty("자료에 이 값이 없다(주가 스냅샷·재무제표·사업보고서 본문)"))
                continue
            out.append({**_number_cell(f, "", dec), "text": _fmt(float(f["abs"]) / div, dec) + tail, "value": float(f["abs"]) / div})
        else:
            mk = returns_metric(label, col)
            f = book.get([mk], None) if mk else None
            out.append(_number_cell(f, "", 1) if f else _empty("자료에 이 기간 수익률이 없다(주가 스냅샷)"))
    return out


_CIRCLED = re.compile(r"^\s*[①-⑳]\s*")
_SALES_TABLE = re.compile(r"매출\s*실적")
_TERM = re.compile(r"제\s*(\d+)\s*기")
_UNIT_SCALE = {"천원": 1e3, "백만원": 1e6, "억원": 1e8, "원": 1.0}


def _norm(s: str) -> str:
    return re.sub(r"[\s()]+", "", s or "").lower()


def _sales_rows(book: _Book) -> List[Tuple[str, str, Dict[int, float], str]]:
    """사업보고서 본문 '매출실적' 표 → [(품목, 구분, {연도: 원 단위 값}, 문서·청크)]. 기수 열(제24기)은 보고서 연도(가장 큰 기수)로 연도에 맞춘다."""
    from app.docs.store import load_chunks

    if getattr(book, "_sales", None) is not None:  # 표 하나를 채우는 동안 한 번만 읽는다(제품 행 × 연도 칸마다 부르면 청크를 수십 번 읽었다)
        return book._sales  # type: ignore[attr-defined]
    out: List[Tuple[str, str, Dict[int, float], str]] = []
    book._sales = out  # type: ignore[attr-defined]
    for d in book.docs:
        meta = load_meta(d) or {}
        year = ((meta.get("snapshot") or {}).get("params") or {}).get("year")
        if not year:
            continue
        for c in load_chunks(d):
            rows = c.get("rows") or []
            if c.get("kind") != "table" or len(rows) < 2 or not _SALES_TABLE.search(c.get("heading") or ""):
                continue
            head = [_norm(h) for h in rows[0]]
            item = next((i for i, h in enumerate(head) if h == "품목"), None)
            kind = next((i for i, h in enumerate(head) if h == "구분"), None)
            terms = {i: int(m.group(1)) for i, h in enumerate(rows[0]) if (m := _TERM.search(h))}
            if item is None or kind is None or not terms:
                continue
            top = max(terms.values())
            unit = re.search(r"단위\s*[:：]\s*([^\s,)]+)", c.get("heading") or "")
            scale = _UNIT_SCALE.get(unit.group(1) if unit else "원", 1.0)
            for r in rows[1:]:
                vals = {}
                for i, n in terms.items():
                    t = (r[i] if i < len(r) else "").replace(",", "").strip()
                    if re.fullmatch(r"-?\d+(?:\.\d+)?", t):
                        vals[int(year) - (top - n)] = float(t) * scale
                out.append((r[item], r[kind], vals, f"{d}#{c.get('id')}"))
    return out


def _product_value(book: _Book, name: str, year: int) -> Optional[Tuple[float, str]]:
    key = _norm(name)
    for item, kind, vals, where in _sales_rows(book):
        if _norm(item) == key and _norm(kind) in ("합계", "계") and year in vals:
            return vals[year], where
    return None


def _product_cell(label: str, form: Dict[str, Any], pk: str, book: _Book, unit: str, calcs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """'① 감속기' 행의 그 해 값 — 매출실적 표의 품목 합계. '기타'는 원본처럼 매출액 − 이름 붙은 제품들(나머지)."""
    name = _CIRCLED.sub("", label).strip()
    year = int(pk)
    div = _scale_of(unit or "억원")
    if _norm(name) == "기타":
        total = book.get(["매출액"], pk)
        others = [_product_value(book, _CIRCLED.sub("", r.get("label") or "").strip(), year) for r in form.get("rows") or []
                  if _CIRCLED.match(r.get("label") or "") and _norm(_CIRCLED.sub("", r.get("label") or "")) != "기타"]
        if total is None or not others or any(o is None for o in others):
            return _empty("매출액이나 다른 제품 값이 없다")
        v = float(total["abs"]) - sum(o[0] for o in others)
        text = _fmt(v / div, 0)
        calcs.append({"label": f"{label} {pk}", "expression": "diff(매출액, 제품 합)", "readable": "매출액 − 이름 붙은 제품 매출 합", "value": v, "display": text,
                      "percent": False, "inputs": [total["fid"]]})
        return {"kind": "calc", "text": text, "num": True, "value": v / div, "inputs": [total["fid"]], "title": f"계산: 매출액 − 제품 합({pk})"}
    hit = _product_value(book, name, year)
    if hit is None:
        return _empty("사업보고서 매출실적 표에 이 제품·연도가 없다")
    v, where = hit
    d, chunk = where.split("#", 1)
    if d not in book.used:
        book.used.append(d)
    return {"kind": "number", "text": _fmt(v / div, 0), "num": True, "value": v / div, "docId": d, "chunk": chunk,
            "title": f"{doc_label(load_meta(d), d)} · 매출실적 {name} 합계 {pk}"}


# ── 평가지표(연말 주가 × 주식 수) ─────────────────────────────────────────────
_SHARE_KEYS = ["발행주식의총수주식의종류합계", "발행주식의총수주식의종류보통주"]
_VAL_NAME = {"p/e": "per", "p/b": "pbr", "p/s": "psr"}


def _year_close(book: _Book, year: int) -> Optional[Tuple[float, str]]:
    """그 해 마지막 거래일 종가(사내 공용 일봉) — 종목은 자료의 주가 스냅샷."""
    from datetime import date

    from app.market.prices import view

    ticker = next((((load_meta(d) or {}).get("snapshot") or {}).get("params", {}).get("ticker") for d in book.scope.doc_ids
                   if ((load_meta(d) or {}).get("snapshot") or {}).get("connector") == "prices" and d in book.docs), None)
    if not ticker:
        return None
    bars = [b for b in view(ticker, (date.today() - date(year, 1, 1)).days + 5)["bars"] if b["date"][:4] == str(year)]
    return (float(bars[-1]["close"]), bars[-1]["date"]) if bars else None


def _shares(book: _Book, pk: str, ins: List[Dict[str, Any]]) -> Optional[float]:
    """주식 수 — 사업보고서 '주식의 총수' 가 그 해에 있으면 그것, 없으면 순이익 ÷ 기본 EPS(가중평균 주식 수)."""
    f = book.get(_SHARE_KEYS, pk)
    if f is not None:
        ins.append(f)
        return float(f["abs"])
    ni, eps = book.get(["지배기업소유주지분", "지배주주순이익", "당기순이익"], pk), book.get(["EPS"], pk)
    if ni is None or eps is None or not float(eps["abs"]):
        return None
    ins += [ni, eps]
    return abs(float(ni["abs"]) / float(eps["abs"]))


def _valuation_cell(label: str, pk: str, book: _Book, calcs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """BPS·SPS(원) = 자본총계·매출액 ÷ 주식 수, PER·PBR·PSR(배) = 연말 종가 ÷ EPS·BPS·SPS. 적자 EPS 면 PER 은 N/A(원본 꼴). 그 밖(EV/EBITDA·DPS)은 빈 칸."""
    from app.research.fs_rows import _key

    k = _key(label)
    name = _VAL_NAME.get(k, k)
    if name not in ("bps", "sps", "per", "pbr", "psr"):
        return _empty({"ev/ebitda": "감가상각비가 요약 재무제표에 없어 EBITDA 를 못 구한다", "dps": "배당 자료가 없다", "배당수익률": "배당 자료가 없다"}.get(name, "계산 사양이 없다"))
    ins: List[Dict[str, Any]] = []
    sh = _shares(book, pk, ins)
    per_share = {}
    for nm, keys in (("bps", ["자본총계"]), ("sps", ["매출액"])):
        f = book.get(keys, pk)
        if f is not None and sh:
            per_share[nm] = float(f["abs"]) / sh
            ins.append(f)
    if name in ("bps", "sps"):
        if name not in per_share:
            return _empty("주식 수나 계정 값이 없다")
        v = per_share[name]
        text, readable = _fmt(v, 0), f"{'자본총계' if name == 'bps' else '매출액'} ÷ 주식 수"
    else:
        close = _year_close(book, int(pk))
        if close is None:
            return _empty("그 해 주가 자료가 없다")
        if name == "per":
            eps = book.get(["EPS"], pk)
            if eps is None:
                return _empty("EPS 가 없다")
            if float(eps["abs"]) <= 0:
                return {"kind": "text", "text": "N/A", "num": False, "title": f"EPS {eps.get('display') or eps.get('raw')} — 적자라 PER 을 내지 않는다"}
            base = float(eps["abs"])
            ins.append(eps)
        else:
            base = per_share.get("bps" if name == "pbr" else "sps")
            if not base or base <= 0:
                return {"kind": "text", "text": "N/A", "num": False, "title": "자본잠식 등으로 분모가 0 이하"} if base is not None and base <= 0 else _empty("주식 수나 계정 값이 없다")
        v = close[0] / base
        text, readable = _fmt(v, 1), f"{close[1]} 종가 {close[0]:,.0f}원 ÷ {name.replace('per', 'EPS').replace('pbr', 'BPS').replace('psr', 'SPS').upper()}"
    calcs.append({"label": f"{label} {pk}", "expression": name, "readable": readable, "value": v, "display": text, "percent": False, "inputs": [f["fid"] for f in ins if f.get("fid")]})
    return {"kind": "calc", "text": text, "num": True, "value": v, "inputs": [f["fid"] for f in ins if f.get("fid")], "title": f"계산: {readable}"}


_HOLDERS = re.compile(r"최대주주\s*및\s*특수관계인의\s*주식\s*소유\s*현황")


def _holders_cell(book: _Book) -> Dict[str, Any]:
    """주요 주주 칸 — 대상 기업 사업보고서 본문의 '최대주주 및 특수관계인의 주식소유 현황' 표(DART 본문 연결)에서 '최대주주 외 n인 계 기말 지분율'.
    표 머리(합친 칸을 푼 한 줄)에서 '관계'·'기 말 … 지분율' 열을 찾는다. 없으면 빈 칸."""
    from app.docs.store import load_chunks

    for d in book.docs:
        for c in load_chunks(d):
            rows = c.get("rows") or []
            if c.get("kind") != "table" or len(rows) < 3 or not _HOLDERS.search(c.get("heading") or ""):
                continue
            head = [re.sub(r"\s+", "", h) for h in rows[0]]
            rel = next((i for i, h in enumerate(head) if h == "관계"), None)
            pct = next((i for i, h in enumerate(head) if "기말" in h and h.endswith("지분율")), None)  # '…지분율 기 말 주식수' 가 아니라 '… 기 말 지분율'
            if rel is None or pct is None:
                continue
            top = next((r for r in rows[1:] if re.sub(r"\s+", "", r[rel]) == "최대주주"), None)
            total = next((r for r in rows[1:] if re.sub(r"\s+", "", r[0]) == "계" and re.fullmatch(r"[\d.]+", r[pct] or "")), None)
            if top is None or total is None:
                continue
            n = sum(1 for r in rows[1:] if "특수관계인" in r[rel])
            name = re.sub(r"^\(주\)|^㈜|주식회사\s*", "", top[0]).strip()
            if d not in book.used:
                book.used.append(d)
            text = f"{name}{f' 외 {n}인' if n else ''} {total[pct]}%"
            return {"kind": "text", "text": text, "num": False, "docId": d, "chunk": c.get("id"),
                    "title": f"{doc_label(load_meta(d), d)} · {c.get('heading') or ''} · 최대주주와 특수관계인 계(기말)"}
    return _empty("사업보고서 본문(주주에 관한 사항)이 자료에 없다")


def figure_block(form: Dict[str, Any]) -> Dict[str, Any]:
    """그림 자리(1차) — 제목·자료 줄 자리만. 화면은 옅은 자리로 보이고 Word 에는 넣지 않는다."""
    return {"kind": "figure", "blockId": form.get("id"), "formId": form.get("id"), "title": form.get("title") or "", "position": form.get("position") or "main",
            "placeholder": True, "note": form.get("kind") == "note"}


__all__ = ["fill_form", "figure_block"]
