"""근거 원장(figures) — 표 칸에서 수치를 결정적으로 뽑는다(LLM 0회). 문서 폴더의 figures.json 에 둔다.

figure = {id: "<청크>.<행>.<열>", doc, chunk, cell: [r, c], metric, metricKey, period, periodKey, basis,
          raw(칸 원문), value(표기 값), percent, unit, scale, currency, abs(배율 적용 값), step(반올림 한 단위), heading, page, sheet, source}
 - 머리글 행(데이터 칸에 숫자가 없는 앞쪽 행들) → 열 이름. 첫 글자 칸 → 행 이름(지표).
 - 열 이름이 기간이 아니고 행 이름이 기간이면 표가 누운 것 — 지표·기간을 바꿔 읽는다.
 - 단위: 칸의 % → 행·열 이름의 (억원)·(%) → 표 위 "(단위: …)" 순서.
 - 기준(연결/별도): 표 제목·머리글·문서 제목에서.
raw 가 칸 원문 그대로라 "원문 재확인"은 구조상 보장된다(LLM 이 만든 숫자가 아니다).
지표 이름은 지표 사전(METRIC_ALIASES)으로 맞춘다 — 기관 맞춤 때 여기에 더한다.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from app.docs.store import doc_dir, load_chunks, load_meta, write_json_atomic
from app.ledger.numbers import Unit, parse_number, parse_unit, same_value, step_of

FIGURES_VERSION = 3  # 2: decimals·unitKnown · 3: 기간 없는 표는 '행 열' 지표 + 표 제목 연도
Figure = Dict[str, Any]

# ── 지표 사전 ───────────────────────────────────────────────────────────
METRIC_ALIASES: Dict[str, List[str]] = {
    "매출액": ["매출", "매출액", "수익(매출액)", "영업수익", "revenue", "revenues", "sales", "netsales", "totalrevenue", "totalrevenues"],
    "매출원가": ["매출원가", "costofsales", "costofrevenue", "costofgoodssold"],
    "매출총이익": ["매출총이익", "grossprofit"],
    "영업이익": ["영업이익", "영업손익", "operatingprofit", "operatingincome", "ebit"],
    "영업이익률": ["영업이익률", "operatingmargin", "opm"],
    "EBITDA": ["ebitda"],
    "당기순이익": ["당기순이익", "순이익", "당기순손익", "netincome", "netprofit", "profitfortheyear", "profitfortheperiod"],
    "지배주주순이익": ["지배주주순이익", "지배기업소유주지분순이익", "지배기업의소유주에게귀속되는당기순이익", "netincomeattributabletoowners"],
    "자산총계": ["자산총계", "총자산", "totalassets"],
    "부채총계": ["부채총계", "총부채", "totalliabilities"],
    "자본총계": ["자본총계", "총자본", "totalequity"],
    "부채비율": ["부채비율", "debtratio", "debttoequity"],
    "영업활동현금흐름": ["영업활동현금흐름", "영업활동으로인한현금흐름", "operatingcashflow", "cashflowfromoperatingactivities"],
    "EPS": ["eps", "주당순이익", "기본주당이익", "기본주당순이익"],
    "BPS": ["bps", "주당순자산"],
    "DPS": ["dps", "주당배당금"],
    "ROE": ["roe", "자기자본이익률"],
    "ROA": ["roa", "총자산이익률"],
    "PER": ["per", "주가수익비율"],
    "PBR": ["pbr", "주가순자산비율"],
    "주가": ["주가", "종가", "월말종가", "closeprice", "closingprice"],  # 주가 자료(월말 종가) ↔ 양식 차트 계열 '주가'
}
_ALIAS_TO_KEY: Dict[str, str] = {a: k for k, al in METRIC_ALIASES.items() for a in al}
_PAREN = re.compile(r"\(([^)]*)\)|（[^）]*）|\[[^\]]*\]")
_FOOTNOTE = re.compile(r"\*+|※|주\s?\d+\)?|\(\s?주\s?\d+\s?\)|[¹²³⁴⁵⁶⁷⁸⁹⁰]+")
_LOSS = re.compile(r"\((?:손실|적자|loss)\)", re.I)


_ENUM = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]{1,4}|\d{1,2}|[가-하])\s*[.)]\s*")


def metric_key(label: str) -> str:
    t = _ENUM.sub("", _FOOTNOTE.sub("", label or ""))
    t = _LOSS.sub("", t)
    flat = re.sub(r"[\s·・,.\-_/]", "", t).lower()
    if flat in _ALIAS_TO_KEY:
        return _ALIAS_TO_KEY[flat]
    no_paren = re.sub(r"[\s·・,.\-_/]", "", _PAREN.sub("", t)).lower()
    return _ALIAS_TO_KEY.get(no_paren, no_paren or flat)


def metric_label(label: str) -> str:
    return re.sub(r"\s+", " ", _ENUM.sub("", _FOOTNOTE.sub("", label or ""))).strip()


# ── 기간 ────────────────────────────────────────────────────────────────
_EST = r"\s*(?:\(?\s*(?:E|F|P|예상|추정|전망)\s*\)?)"
_Q = [
    re.compile(r"(?<!\d)([1-4])\s*Q\s*'?(\d{2}|\d{4})(?!\d)", re.I),  # 1Q24, 1Q 2024
    re.compile(r"(?<!\d)'?(\d{2}|\d{4})\s*[.\-/년]?\s*([1-4])\s*(?:Q|분기)", re.I),  # 2024 1Q, 24.1Q, 2024년 1분기
]
_H = re.compile(r"(?<!\d)'?(\d{2}|\d{4})\s*[.\-/년]?\s*(1H|2H|상반기|하반기|반기)", re.I)
_Y = re.compile(r"(?:FY\s*'?)?(?<!\d)((?:19|20)\d{2}|'\d{2})(?!\d)\s*(?:년|FY|A)?(" + _EST + r")?", re.I)
_FY2 = re.compile(r"FY\s*'?(\d{2})(?!\d)(" + _EST + r")?", re.I)
_REL = re.compile(r"^(당기|전기|전전기|당분기|전분기|제\s?\d+\s?기)")
_PERIODISH = re.compile(r"(?:19|20)\d{2}|FY\s*'?\d{2}|\d\s*Q|분기|반기|당기|전기|제\s?\d+\s?기|'\d{2}", re.I)


def _yyyy(s: str) -> str:
    s = s.lstrip("'")
    return s if len(s) == 4 else ("20" + s if int(s) < 70 else "19" + s)


_SEC_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_SEC_DUR = re.compile(r"(3|three|6|six|9|nine|12|twelve)\s+months?\s+ended\s+([A-Za-z]{3})[a-z]*\.?\s+\d{1,2},?\s+(\d{4})", re.I)


def _sec_period(t: str) -> Optional[str]:
    """SEC 재무제표 엑셀 머리('3 Months Ended Sep. 30, 2026') → 2026Q3 · 6개월 → 2026H1 · 9개월 → 2026M9(누적) · 12개월 → 2026.
    역년 기준 달로 분기를 정한다(회계연도가 다른 회사는 회계 분기와 다를 수 있다)."""
    m = _SEC_DUR.search(t)
    if not m:
        return None
    n = {"3": 3, "three": 3, "6": 6, "six": 6, "9": 9, "nine": 9, "12": 12, "twelve": 12}[m.group(1).lower()]
    mon = _SEC_MONTHS.get(m.group(2)[:3].lower())
    y = m.group(3)
    if not mon:
        return None
    if n == 3:
        return f"{y}Q{(mon - 1) // 3 + 1}"
    if n == 6:
        return f"{y}H1" if mon <= 6 else f"{y}H2"
    if n == 9:
        return f"{y}M9"
    return y


_YM = re.compile(r"^((?:19|20)\d{2})-(0[1-9]|1[0-2])(?:-(0[1-9]|[12]\d|3[01]))?$")  # 2025-10 · 2026-05-13 (ISO 꼴만 — '2024.12'는 결산 연도로 둔다)
_YM_KO = re.compile(r"^((?:19|20)\d{2})\s*년\s*(\d{1,2})\s*월$")


def period_key(label: str) -> str:
    t = (label or "").strip()
    if not t:
        return ""
    # 월·일 행(월말 종가 2025-10, 일봉 2026-05-13)을 연도로 접으면 같은 해의 다른 값이 '자료 간 불일치'가 된다
    m = _YM.match(t)
    if m:
        return t
    m = _YM_KO.match(t)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    sec = _sec_period(t)
    if sec:
        return sec
    for rx in _Q:
        m = rx.search(t)
        if m:
            a, b = m.group(1), m.group(2)
            q, y = (a, b) if rx is _Q[0] else (b, a)
            return f"{_yyyy(y)}Q{q}"
    m = _H.search(t)
    if m:
        h = "H1" if m.group(2).lower() in ("1h", "상반기", "반기") else "H2"
        return f"{_yyyy(m.group(1))}{h}"
    m = _FY2.search(t)
    if m:
        return _yyyy(m.group(1)) + ("E" if m.group(2) else "")
    m = _Y.search(t)
    if m:
        return _yyyy(m.group(1)) + ("E" if m.group(2) else "")
    m = _REL.match(t)
    if m:
        return re.sub(r"\s", "", m.group(1))
    return re.sub(r"\s+", "", t).lower()


def looks_like_period(label: str) -> bool:
    return bool(_PERIODISH.search(label or ""))


def basis_of(*texts: Optional[str]) -> Optional[str]:
    for t in texts:
        low = (t or "").lower()
        if "별도" in low or "separate" in low or "standalone" in low:
            return "별도"
        if "연결" in low or "consolidated" in low:
            return "연결"
    return None


# ── 표 → figures ────────────────────────────────────────────────────────

def _header_rows(rows: List[List[str]]) -> int:
    n = 0
    for r in rows:
        if any(parse_number(c) for c in r[1:] if c) and not all(looks_like_period(c) for c in r[1:] if c):
            break
        n += 1
        if n >= 3:
            break
    return n


def _unit_for(label: str, header: str, cell_pct: bool, table_unit: Unit) -> Unit:
    if cell_pct:
        return Unit(percent=True, label="%")
    for t in (label, header):
        for m in _PAREN.finditer(t or ""):
            inner = (m.group(1) or "").strip()
            u = parse_unit(inner)
            if u.percent or u.scale != 1.0 or u.currency:
                return u
        if re.search(r"(률|(?<!환)율|비중|margin|ratio|yield)\s*$", _PAREN.sub("", t or "").strip(), re.I):  # '환율'은 값(원/달러)이지 비율이 아니다
            return Unit(percent=True, label="%")
    if table_unit.scale != 1.0 and re.search(r"per share|\bEPS\b|주당", label or "", re.I):  # '(USD in Millions, except per share)' — 주당 값은 배율 밖
        return Unit(currency=table_unit.currency, label=table_unit.currency or "")
    return table_unit


def table_figures(doc_id: str, chunk: Dict[str, Any], doc_basis: Optional[str] = None) -> List[Figure]:
    rows: List[List[str]] = chunk.get("rows") or []
    if len(rows) < 2:
        return []
    h = _header_rows(rows)
    if h == 0 or h >= len(rows):
        return []
    width = max(len(r) for r in rows)
    headers = [" ".join(dict.fromkeys(rows[i][c] for i in range(h) if c < len(rows[i]) and rows[i][c])).strip() for c in range(width)]
    table_unit = parse_unit(chunk.get("unit"))
    basis = basis_of(chunk.get("heading"), " ".join(headers), doc_basis)
    data_rows = rows[h:]
    col_periods = sum(1 for x in headers[1:] if looks_like_period(x))
    row_periods = sum(1 for r in data_rows if r and looks_like_period(r[0]))
    transposed = col_periods == 0 and row_periods >= max(1, len(data_rows) // 2)
    # 기간 열·행이 없는 표(부문별 매출: 부문 | 매출액 | 비중) — 지표 = '행 이름 열 이름', 기간 = 표 제목의 연도(하나일 때만)
    attribute = col_periods == 0 and not transposed
    years = set(re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", chunk.get("heading") or "")) if attribute else set()
    caption_period = years.pop() if len(years) == 1 else ""
    # 제목에 날짜가 있으면(일일 시장 스냅샷 '… 2026-10-29') 기간 = 그날 — 연도로 접으면 다른 날 값끼리 '자료마다 다른 값'이 된다
    dated = re.search(r"(?<!\d)((?:19|20)\d{2}-\d{2}-\d{2})(?!\d)", chunk.get("heading") or "") if attribute else None
    if dated:
        caption_period = dated.group(1)
    out: List[Figure] = []
    last_label = ""
    for ri, row in enumerate(data_rows, start=h):
        label = row[0] if row and row[0] and not parse_number(row[0]) else last_label
        if not label:
            continue
        last_label = label
        for ci in range(1, len(row)):
            raw = row[ci]
            got = parse_number(raw)
            if got is None:
                continue
            value, info = got
            col = headers[ci] if ci < len(headers) else ""
            metric, period = (col, label) if transposed else (f"{label} {col}".strip(), caption_period) if attribute else (label, col)
            unit = _unit_for(metric, period, info["percent"], table_unit)
            absval = value if unit.percent else value * unit.scale
            out.append(
                {
                    "id": f"{chunk['id']}.{ri}.{ci}",
                    "doc": doc_id,
                    "chunk": chunk["id"],
                    "cell": [ri, ci],
                    "metric": metric_label(metric),
                    "metricKey": metric_key(metric),
                    "period": period.strip(),
                    "periodKey": caption_period if dated and attribute else period_key(period),
                    "basis": basis,
                    "raw": raw,
                    "value": value,
                    "percent": unit.percent,
                    "unit": unit.label or ("%" if unit.percent else ""),
                    "scale": 1.0 if unit.percent else unit.scale,
                    "currency": unit.currency,
                    "abs": absval,
                    "step": step_of(info["decimals"], 1.0 if unit.percent else unit.scale),
                    "decimals": info["decimals"],
                    "display": raw if (unit.percent and "%" in raw) or not unit.label else f"{raw} {unit.label}",
                    "unitKnown": bool(unit.percent or unit.label),
                    "heading": chunk.get("heading"),
                    "page": chunk.get("page"),
                    "sheet": chunk.get("sheet"),
                    "source": "table",
                }
            )
    return out


def build_figures(doc_id: str) -> List[Figure]:
    meta = load_meta(doc_id) or {}
    card = meta.get("card") or {}
    doc_basis = basis_of(card.get("title"), meta.get("fileName"), (meta.get("frontText") or "")[:400])
    out: List[Figure] = []
    for c in load_chunks(doc_id):
        if c.get("kind") == "table" and c.get("rows"):
            out.extend(table_figures(doc_id, c, doc_basis))
    return out


def save_figures(doc_id: str, figures: List[Figure], source: str = "table") -> None:
    write_json_atomic(doc_dir(doc_id) / "figures.json", {"version": FIGURES_VERSION, "source": source, "figures": figures})


def load_figures(doc_id: str) -> List[Figure]:
    """figures.json — 없거나 옛 버전이면 청크에서 다시 만든다(DART 스냅샷은 만든 그대로 둔다)."""
    p = doc_dir(doc_id) / "figures.json"
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("version") == FIGURES_VERSION or data.get("source") != "table":
                return list(data.get("figures") or [])
        except (ValueError, OSError):
            pass
    if not (doc_dir(doc_id) / "chunks.json").exists():
        return []
    figs = build_figures(doc_id)
    try:
        save_figures(doc_id, figs)
    except OSError:
        pass
    return figs


# ── 워크스페이스 원장 ───────────────────────────────────────────────────

def base_key(f: Figure) -> str:
    return f"{f.get('metricKey')}|{f.get('periodKey')}|{'%' if f.get('percent') else '#'}"


def _same(f: Figure, g: Figure) -> bool:
    """같은 값인가 — 둘 다 단위를 알면 배율 적용 값으로, 하나라도 단위를 모르면 표기 값으로(단위 불명 표시)."""
    if f.get("unitKnown", True) and g.get("unitKnown", True):
        return same_value(f["abs"], f["step"], g["abs"], g["step"])
    return same_value(f["value"], step_of(f.get("decimals", 0), 1.0), g["value"], step_of(g.get("decimals", 0), 1.0))


def _clusters(figs: Sequence[Figure]) -> List[List[Figure]]:
    """같은 값(반올림 한 단위)끼리 묶는다."""
    clusters: List[List[Figure]] = []
    for f in figs:
        for cl in clusters:
            if _same(f, cl[0]):
                cl.append(f)
                break
        else:
            clusters.append([f])
    return clusters


def _split_basis(figs: List[Figure]) -> Dict[Optional[str], List[Figure]]:
    """기준(연결/별도)이 둘 다 보이면 나눠 비교하고, 하나뿐이거나 모르면 한 묶음(기준 불명은 아는 쪽과 비교)."""
    known = {f.get("basis") for f in figs if f.get("basis")}
    if len(known) < 2:
        return {(next(iter(known)) if known else None): figs}
    out: Dict[Optional[str], List[Figure]] = {}
    for f in figs:
        out.setdefault(f.get("basis"), []).append(f)
    return out


def fid(f: Figure) -> str:
    return f"{f['doc']}:{f['id']}"


def workspace_ledger(doc_ids: Sequence[str], labels: Dict[str, str], choices: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """워크스페이스 문서들의 figures → {figures, groups}. groups 는 (지표, 기간, 기준, 단위 종류) 묶음과 충돌 여부·채택."""
    figures: List[Figure] = []
    for d in doc_ids:
        for f in load_figures(d):
            figures.append({**f, "fid": fid(f), "docLabel": labels.get(d, d[:8])})
    by_base: Dict[str, List[Figure]] = {}
    for f in figures:
        by_base.setdefault(base_key(f), []).append(f)
    by_key: Dict[str, List[Figure]] = {}
    for base, figs in by_base.items():
        for basis, sub in _split_basis(figs).items():
            by_key[f"{base}|{basis or ''}"] = sub
    groups: List[Dict[str, Any]] = []
    for key, figs in by_key.items():
        clusters = _clusters(figs)
        docs = {f["doc"] for f in figs}
        choice = choices.get(key)
        chosen = next((f for f in figs if f["fid"] == (choice or {}).get("figureId")), None)
        conflict = len(clusters) > 1
        rep = chosen or (clusters[0][0] if not conflict else None)
        groups.append(
            {
                "key": key,
                "metric": figs[0]["metric"],
                "metricKey": figs[0]["metricKey"],
                "period": figs[0]["period"],
                "periodKey": figs[0]["periodKey"],
                "basis": next((f.get("basis") for f in figs if f.get("basis")), None),
                "unitUnknown": any(not f.get("unitKnown", True) for f in figs),
                "figureIds": [f["fid"] for f in figs],
                "documents": len(docs),
                "conflict": conflict,
                "values": [{"figureIds": [f["fid"] for f in cl], "raw": cl[0]["raw"], "display": cl[0].get("display") or cl[0]["raw"], "unit": cl[0]["unit"], "abs": cl[0]["abs"]} for cl in clusters],
                "chosen": {"figureId": chosen["fid"], **{k: v for k, v in (choice or {}).items() if k != "figureId"}} if chosen else None,
                "value": {"figureId": rep["fid"], "raw": rep["raw"], "display": rep.get("display") or rep["raw"], "unit": rep["unit"], "abs": rep["abs"]} if rep else None,
            }
        )
    groups.sort(key=lambda g: (not g["conflict"], g["metric"], g["periodKey"]))
    return {"figures": figures, "groups": groups}


def figure_line(f: Figure) -> str:
    """프롬프트·검수용 한 줄 — '매출액 · 2024 · 연결 = 3,150 억원 (A사 IR, p.2, 표 2행 3열)'."""
    where = f"p.{f['page']}" if f.get("page") else (f"시트 {f['sheet']}" if f.get("sheet") else f"문단 {f['chunk']}")
    basis = f" · {f['basis']}" if f.get("basis") else ""
    return f"{f['metric']} · {f['period']}{basis} = {f.get('display') or f['raw']} ({f.get('docLabel') or f['doc'][:8]}, {where}, 표 {f['cell'][0] + 1}행 {f['cell'][1] + 1}열)"


__all__ = ["Figure", "base_key", "build_figures", "fid", "figure_line", "load_figures", "metric_key", "period_key", "save_figures", "workspace_ledger"]
