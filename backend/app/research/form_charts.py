"""양식 2.0 그림 자리 채우기 — 원본 차트 모양(templates_import/layout.chart_look: 종류·계열 색·값 표시·범주) + 우리 자료 → 차트 블록(LLM 0회).

무엇을 그릴지는 그림 제목으로 정한다(CHARTS — 표의 research/fs_rows 처럼 손으로 만든 사전). 범주는 샘플의 기간(내용)을 우리 자료의 최근 기간으로 옮긴다:
  연도 '2021 … 2026F' → shift_years(실적 열은 자료의 최근 연간 실적 연도까지, F 열은 빈 값) · 분기 '1Q23 … 3Q25' → 같은 개수로 자료의 최근 분기까지.
분기 값 = 누적 차이(1분기 = 1분기 누적, 2분기 = 반기 누적 − 1분기 누적, 3분기 = 3분기 누적 − 반기 누적, 4분기 = 연간 − 3분기 누적, DART 기간 키).
사전에 없거나 자료가 모자라면 None — 그림 자리로 남는다(사진·연혁 그림·경쟁사·시장 전망처럼 우리 자료가 없는 것).
블록 모양은 report/view·FE ChartBlock·Word format_export._chart 가 그리는 차트(chartType bar|line|combo, series[{name, values, type, axis}], look{colors, labels, grid}).
"""
from __future__ import annotations

import re
import time
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.docs.store import doc_dir, doc_label, load_meta
from app.ledger.figures import period_key
from app.research.form_rows import _Book
from app.research.forms import shift_years

_RND = ["연구개발비용계", "연구개발비용합계", "경상연구개발비"]
# (그림 제목 정규식, 사양) — 위에서부터 처음 맞는 것. series = (이름, 원장 계정 후보, 모양)
CHARTS: List[Tuple[re.Pattern, Dict[str, Any]]] = [
    (re.compile(r"price.*relative|relative.*performance|주가\s*(및|와)?\s*상대", re.I), {"kind": "price"}),
    (re.compile(r"분기.*매출"), {"kind": "quarter", "series": [("매출액", ["매출액"], "bar")]}),
    (re.compile(r"분기.*영업이익"), {"kind": "quarter", "series": [("영업이익", ["영업이익"], "bar")]}),
    # 원본의 '경상연구개발비'(손익 비용)와 사업보고서 '연구개발비용 계'(정부보조금 등 포함)는 다른 값 — 계열 이름은 자료 이름 그대로
    (re.compile(r"연구개발비.*비중"), {"kind": "annual", "series": [("매출액", ["매출액"], "bar"), ("연구개발비용(사업보고서)", _RND, "bar"), ("매출액 대비 비중", "ratio", "line")]}),
    (re.compile(r"(연간|연도별)?\s*매출액\s*추이"), {"kind": "annual", "series": [("매출액", ["매출액"], "bar")]}),
    (re.compile(r"(연간|연도별)?\s*영업이익\s*추이"), {"kind": "annual", "series": [("영업이익", ["영업이익"], "bar")]}),
]
_SCALES = {"조원": 1e12, "십억원": 1e9, "억원": 1e8, "백만원": 1e6, "천원": 1e3, "원": 1.0}
_QUARTER = re.compile(r"^([1-4])Q(\d{2})$")
_YTD = {1: "Q1YTD", 2: "H1YTD", 3: "Q3YTD", 4: ""}
_CACHE: Dict[Tuple[Any, ...], Tuple[float, Optional[Dict[str, Any]]]] = {}


def chart_spec(form: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title = f"{form.get('sampleTitle') or ''} {form.get('title') or ''}"
    return next((spec for pat, spec in CHARTS if pat.search(title)), None)


def _scale(look: Dict[str, Any]) -> Tuple[float, str]:
    unit = next((u.strip("() ") for u in look.get("units") or [] if u.strip("() ") in _SCALES), "억원")
    return _SCALES[unit], unit


def _annual(spec: Dict[str, Any], look: Dict[str, Any], book: _Book) -> Optional[Dict[str, Any]]:
    cats = [c for c in look.get("categories") or [] if re.fullmatch(r"(?:19|20)\d{2}[EF]?", c.strip())]
    if len(cats) < 2:
        return None
    cats = shift_years(cats, book.latest_year())
    div, unit = _scale(look)
    series: List[Dict[str, Any]] = []
    calcs: List[Dict[str, Any]] = []
    raw: Dict[str, List[Optional[float]]] = {}
    for name, keys, shape in spec["series"]:
        if keys == "ratio":
            a, b = raw.get("연구개발비용(사업보고서)") or [], raw.get("매출액") or []
            vals = [round(x / y * 100, 1) if x is not None and y else None for x, y in zip(a, b)]
            series.append({"name": name, "values": vals, "type": "line", "axis": "right"})
            calcs += [{"label": f"{name} {c}", "expression": "ratio(연구개발비용, 매출액)", "readable": f"{c} 연구개발비용 ÷ 매출액", "value": v, "display": f"{v:.1f}%",
                       "percent": True, "inputs": []} for c, v in zip(cats, vals) if v is not None]
            continue
        vals_abs = []
        for c in cats:
            pk = period_key(c)
            f = book.get(keys, pk) if re.fullmatch(r"\d{4}", pk) else None  # 예상(F) 열은 비운다
            vals_abs.append(float(f["abs"]) if f else None)
        raw[name] = vals_abs
        series.append({"name": name, "values": [round(v / div, 1 if abs(v / div) < 10 else 0) if v is not None else None for v in vals_abs], "type": shape})
    if not any(v is not None for s in series for v in s["values"]):
        return None
    return {"categories": cats, "series": series, "unit": unit, "unit2": "%" if any(s.get("axis") == "right" for s in series) else None, "calcs": calcs}


def _ytd(book: _Book, keys: Sequence[str], y: int, q: int) -> Optional[float]:
    f = book.get(keys, f"{y}{_YTD[q]}")
    return float(f["abs"]) if f else None


def _quarter_value(book: _Book, keys: Sequence[str], y: int, q: int) -> Optional[float]:
    cur = _ytd(book, keys, y, q)
    if cur is None:
        return None
    if q == 1:
        return cur
    prev = _ytd(book, keys, y, q - 1)
    return None if prev is None else cur - prev


def _quarter(spec: Dict[str, Any], look: Dict[str, Any], book: _Book) -> Optional[Dict[str, Any]]:
    n = sum(1 for c in look.get("categories") or [] if _QUARTER.match(c.strip()))
    if n < 2:
        return None
    keys = spec["series"][0][1]
    year = (book.latest_year() or 2000) + 1
    last = next(((y, q) for y in range(year, year - 3, -1) for q in (4, 3, 2, 1) if _quarter_value(book, keys, y, q) is not None), None)
    if last is None:
        return None
    qs: List[Tuple[int, int]] = []
    y, q = last
    for _ in range(n):
        qs.append((y, q))
        y, q = (y, q - 1) if q > 1 else (y - 1, 4)
    qs.reverse()
    div, unit = _scale(look)
    series = []
    calcs: List[Dict[str, Any]] = []  # 분기 값은 누적 차이(계산값) — 본문이 쓰면 숫자 확인이 계산값으로 본다
    for name, ks, shape in spec["series"]:
        vals = [_quarter_value(book, ks, y, q) for y, q in qs]
        series.append({"name": name, "values": [round(v / div, 1 if abs(v / div) < 10 else 0) if v is not None else None for v in vals], "type": shape})
        calcs += [{"label": f"{name} {q}Q{y % 100:02d}", "expression": "분기 = 누적 차이",
                   "readable": f"{y}년 {q}분기 {name} = " + (f"{q}분기 누적" if q == 1 else f"{'연간' if q == 4 else f'{q}분기 누적'} − {q - 1 if q > 2 else 1}분기 누적".replace("2분기 누적", "반기 누적")),
                   "value": v, "display": f"{v / div:,.0f}{unit}", "percent": False, "inputs": []} for (y, q), v in zip(qs, vals) if v is not None]
    return {"categories": [f"{q}Q{y % 100:02d}" for y, q in qs], "series": series, "unit": unit, "calcs": calcs}


def _price(look: Dict[str, Any], doc_ids: Sequence[str], entity: str) -> Optional[Dict[str, Any]]:
    """주가(왼쪽 축, 원) + 시장 지수(오른쪽 축, 첫날 = 100) — 사내 공용 일봉(price_bar). 종목은 자료의 주가 스냅샷에서."""
    from app.market.prices import BENCHMARKS, view

    ticker = next((((load_meta(d) or {}).get("snapshot") or {}).get("params", {}).get("ticker") for d in doc_ids
                   if ((load_meta(d) or {}).get("snapshot") or {}).get("connector") == "prices"
                   and (not entity or entity in str(((load_meta(d) or {}).get("card") or {}).get("title") or ""))), None)
    if not ticker:
        return None
    bars = view(ticker, 365)["bars"]
    if len(bars) < 20:
        return None
    pick = bars[::5] + ([bars[-1]] if (len(bars) - 1) % 5 else [])  # 주 단위(약 52점)
    series = [{"name": entity or ticker, "values": [round(b["close"]) for b in pick], "type": "line"}]
    bench = BENCHMARKS.get(ticker.rsplit(".", 1)[-1]) if "." in ticker else None
    if bench:
        ib = {b["date"]: b["close"] for b in view(bench[0], 380)["bars"]}
        base = next((ib[d] for d in sorted(ib) if d >= bars[0]["date"]), None)
        if base:
            vals = []
            for b in pick:
                d = max((x for x in ib if x <= b["date"]), default=None)
                vals.append(round(ib[d] / base * 100, 1) if d else None)
            series.append({"name": bench[1], "values": vals, "type": "line", "axis": "right"})
    return {"categories": [b["date"][2:].replace("-", "/")[:5] for b in pick], "series": series, "unit": "원",
            "unit2": f"{bars[0]['date']}=100" if len(series) > 1 else None, "tickers": [ticker] + ([bench[0]] if bench else [])}


def fill_chart(form: Dict[str, Any], doc_ids: Sequence[str], entity: str = "", choices: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """그림 자리 → 차트 블록(원본 모양 + 우리 자료). 그릴 수 없으면 None."""
    look = form.get("chart") or {}
    spec = chart_spec(form)
    if not look or spec is None:
        return None
    # 캐시 — 표(fill_form)와 같은 열쇠(양식·자료·원장 파일 시각) + 오늘 날짜(주가 일봉은 날마다 쌓인다), 10분
    stamp = tuple(round((doc_dir(d) / "figures.json").stat().st_mtime, 3) if (doc_dir(d) / "figures.json").exists() else 0 for d in doc_ids)
    key = (form.get("id"), tuple(doc_ids), entity, stamp, date.today().isoformat(), tuple(sorted((choices or {}).keys())))
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    block = _fill(form, look, spec, doc_ids, entity, choices)
    _CACHE[key] = (time.time(), block)
    return block


def _fill(form: Dict[str, Any], look: Dict[str, Any], spec: Dict[str, Any], doc_ids: Sequence[str], entity: str, choices: Optional[Dict[str, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    book = _Book(doc_ids, entity, choices or {})
    data = _price(look, doc_ids, entity) if spec["kind"] == "price" else _quarter(spec, look, book) if spec["kind"] == "quarter" else _annual(spec, look, book)
    if not data:
        return None
    combo = any(s.get("type") == "line" for s in data["series"]) and (any(s.get("type") == "bar" for s in data["series"]) or any(s.get("axis") for s in data["series"]))
    chart_type = "combo" if combo else ("line" if all(s.get("type") == "line" for s in data["series"]) else "bar")
    colors = list(look.get("colors") or [])
    if spec["kind"] == "price":
        colors = [colors[0] if colors else "#C00000", "#A6A6A6"]  # 원본: 종목 빨강·지수 회색
    labels = [doc_label(load_meta(d), d) for d in book.used] if spec["kind"] != "price" else ["주가 일봉(Yahoo Finance)"]
    return {
        "kind": "chart", "blockId": form.get("id"), "formId": form.get("id"), "title": form.get("title") or "", "caption": form.get("title") or "",
        "categories": data["categories"], "series": [{k: v for k, v in s.items() if v is not None} for s in data["series"]],
        "chartType": chart_type, "horizontal": bool(look.get("horizontal")), "unit": data.get("unit") or "", "unit2": data.get("unit2"),
        "legend": "top" if len(data["series"]) > 1 else "none", "number": "#,##0" if spec["kind"] == "price" else "#,##0.0;-#,##0.0",
        "look": {"colors": colors, "labels": bool(look.get("labels")) and spec["kind"] != "price", "grid": False, "captionColor": (form.get("captionStyle") or {}).get("color")},
        "sourceLine": "자료: " + (", ".join(labels[:2]) + (f" 외 {len(labels) - 2}건" if len(labels) > 2 else "") if labels else "자료 없음"),
        "sourceDocIds": list(book.used), "position": form.get("position") or "main", "missing": False, "calcs": data.get("calcs") or [],
    }


__all__ = ["CHARTS", "chart_spec", "fill_chart"]
