"""숫자·단위 해석 — 근거 원장의 바닥. 전부 결정적(LLM 0회).

 - parse_number("(1,234)") → -1234.0, "△12.5" → -12.5, "10.0%" → (10.0, percent)
 - parse_unit("억원") → {scale: 1e8, currency: "KRW", label: "억원"}, "USD mn" → {1e6, "USD"}, "%" → percent
 - find_amounts("매출은 3,150억원, 이익률 11.0%") → 본문 속 금액·비율과 위치
 - precision step: 원문 표기의 마지막 자릿수 × 배율 — 같은 값인지 볼 때 반올림 차이(반 단위)까지만 같다고 본다
   (같은 자릿수의 한 단위 차이는 다르다)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

SCALE_WORDS: List[Tuple[str, float]] = [
    ("십억", 1e9), ("백억", 1e10), ("천억", 1e11), ("백만", 1e6), ("천만", 1e7), ("조", 1e12), ("억", 1e8), ("만", 1e4), ("천", 1e3),
    ("trillion", 1e12), ("billion", 1e9), ("million", 1e6), ("thousand", 1e3), ("tn", 1e12), ("bn", 1e9), ("mn", 1e6), ("mil", 1e6), ("k", 1e3), ("m", 1e6), ("b", 1e9),
]
CURRENCY_WORDS: List[Tuple[str, str]] = [
    ("원", "KRW"), ("krw", "KRW"), ("₩", "KRW"), ("달러", "USD"), ("usd", "USD"), ("$", "USD"), ("us$", "USD"), ("유로", "EUR"), ("eur", "EUR"), ("€", "EUR"),
    ("엔", "JPY"), ("jpy", "JPY"), ("¥", "JPY"), ("위안", "CNY"), ("cny", "CNY"), ("파운드", "GBP"), ("gbp", "GBP"), ("£", "GBP"),
    ("크로네", "NOK"), ("nok", "NOK"),
]
# 본문 금액 뒤에 붙는 통화 낱말(원 외) — '19조 5,860억 크로네'
_CUR_TAIL = r"(?:원|크로네)?"
_NUM = re.compile(r"^\s*([(\[]?)\s*([△▲▼\-–−+]?)\s*([$€£¥₩]?)\s*(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s*(%|%p|bp)?\s*([)\]]?)\s*$")


@dataclass
class Unit:
    scale: float = 1.0
    currency: Optional[str] = None
    percent: bool = False
    label: str = ""


def parse_unit(text: Optional[str]) -> Unit:
    t = (text or "").strip()
    low = t.lower().replace(" ", "")
    if not low:
        return Unit()
    if low in ("%", "퍼센트", "percent", "pct") or low.startswith("%"):
        return Unit(percent=True, label="%")
    scale = 1.0
    for w, s in SCALE_WORDS:
        if len(w) <= 2 and w.isascii():
            # 영문 한두 글자 배율(k·m·b·mn·bn)은 단어 경계에서만
            if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low):
                scale = s
                break
        elif w in low:
            scale = s
            break
    currency = next((c for w, c in CURRENCY_WORDS if w in low), None)
    return Unit(scale=scale, currency=currency, label=t)


def parse_number(raw: Optional[str]) -> Optional[Tuple[float, Dict[str, Any]]]:
    """표 칸 하나 → (값, {percent, decimals, negative}). 숫자가 아니면 None."""
    if raw is None:
        return None
    s = str(raw).strip().replace(" ", " ")
    if not s or s in ("-", "–", "—", "N/A", "n/a", "NA", "nm", "n.m."):
        return None
    m = _NUM.match(s)
    if not m:
        return None
    paren_l, sign, _cur, ip, fp, pct, paren_r = m.groups()
    value = float(ip.replace(",", "") + (fp or ""))
    negative = bool(sign and sign in "△▲▼-–−") or bool(paren_l and paren_r)
    # ▲ 는 한국 공시에서 '증가'를 뜻하기도 한다 — 표 칸 단독이면 대개 음수(△)와 같은 쓰임이라 같이 본다(△가 표준)
    if negative:
        value = -value
    return value, {"percent": pct in ("%", "%p"), "pp": pct == "%p", "bp": pct == "bp", "decimals": len(fp) - 1 if fp else 0}


_AMOUNT = re.compile(
    r"(?P<sign>[△▲\-−]?)(?P<cur1>[$€£¥₩]|US\$)?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?"
    rf"(?P<unit>%p|%|bp|조\s?\d{{1,4}}(?:,\d{{3}})*\s?억\s?{_CUR_TAIL}|조\s?{_CUR_TAIL}|십억\s?{_CUR_TAIL}|억\s?{_CUR_TAIL}|백만\s?{_CUR_TAIL}|천만\s?{_CUR_TAIL}|천\s?원|만\s?원?|원|크로네|달러|유로|엔|위안|배|bn|mn|billion|million|trillion|명|개|건|톤)?",
    re.I,
)


def find_amounts(text: str) -> List[Dict[str, Any]]:
    """본문 속 금액·비율 → [{raw, value, unit, abs, percent, start, end}]. 단위 없는 맨 숫자(연도·쪽 번호 등)는 뺀다."""
    out: List[Dict[str, Any]] = []
    for m in _AMOUNT.finditer(text or ""):
        unit = (m.group("unit") or "").strip()
        cur = m.group("cur1")
        if not unit and not cur:
            continue
        raw = m.group(0).strip()
        num = float(m.group("num").replace(",", ""))
        sign = -1.0 if m.group("sign") in ("△", "-", "−") else 1.0
        decimals = len(m.group("num").split(".")[1]) if "." in m.group("num") else 0
        if unit.startswith("조") and "억" in unit:
            # "3조 1,500억원" — 조 + 억
            eok = float(re.sub(r"[^\d]", "", unit.split("조", 1)[1]) or 0)
            absval = sign * (num * 1e12 + eok * 1e8)
            out.append({"raw": raw, "value": sign * num, "unit": unit, "abs": absval, "percent": False, "step": 1e8, "decimals": decimals, "currency": "NOK" if "크로네" in unit else "KRW", "start": m.start(), "end": m.end()})
            continue
        u = parse_unit(unit or (cur or ""))
        if cur and not u.currency:
            u.currency = parse_unit(cur).currency
        pct = unit.lower() in ("%", "%p")
        absval = sign * num * (1.0 if pct else u.scale)
        out.append({"raw": raw, "value": sign * num, "unit": unit or cur, "abs": absval, "percent": pct, "pp": unit.lower() == "%p", "step": (10 ** -decimals) * (1.0 if pct else u.scale), "decimals": decimals, "currency": u.currency, "start": m.start(), "end": m.end()})
    return out


def step_of(decimals: int, scale: float) -> float:
    return (10 ** -decimals) * scale


def same_value(a: float, step_a: float, b: float, step_b: float) -> bool:
    """두 표기가 같은 참값의 반올림일 수 있으면 같은 값 — |a-b| < (반올림 반 단위 a + 반 단위 b).
    3,150억원 vs 315,012백만원 → 같다 / 280억 vs 281억(같은 자릿수) → 다르다 / 10% vs 10.4% → 같다.
    경계(같은 자릿수의 한 단위 차이: 6.74% vs 6.73%)는 다르다 — 부동소수 오차 여유는 경계 안쪽으로만 둔다
    (예전에는 바깥쪽으로 더해 한 단위 차이까지 같다고 봤다)."""
    if a == b:
        return True
    return abs(a - b) < 0.5 * (step_a + step_b) - 1e-9 * max(1.0, abs(a), abs(b))


def is_rounding_of(shown: float, step: float, exact: float) -> bool:
    """본문 표기 shown(마지막 자리 step)이 코드가 계산한 값 exact 를 반올림한 것인가 — |shown-exact| ≤ 반 단위.
    계산값 12.3456% → 본문 12.3%·12% 는 맞다 / 12.4%(같은 자릿수 한 단위 차이)는 다르다. 금액도 같다: 280.4억 → 280억 맞음 / 281억 다름.
    정확히 반 단위(12.35 → 12.3 또는 12.4)는 어느 쪽으로 반올림했든 맞다고 본다 — 계산값은 반올림 전 값이라 경계를 넣는다."""
    return abs(shown - exact) <= 0.5 * step + 1e-9 * max(1.0, abs(shown), abs(exact))


def fmt_number(v: float, decimals: int = 0) -> str:
    return f"{v:,.{decimals}f}"


CURRENCY_KO = {"NOK": "크로네", "USD": "달러", "EUR": "유로", "JPY": "엔", "CNY": "위안"}


def korean_amount(absval: float, currency: Optional[str]) -> str:
    """한국어 본문용 '19조 5,860억 크로네' — 조·억 두 단계(억 아래는 반올림). find_amounts 가 그대로 읽는 꼴이라
    작성 모델이 이 표기를 옮겨 쓰면 숫자 확인이 원장 값과 맞춘다(모델에게 단위 환산을 시키지 않는다)."""
    word = "원" if currency in (None, "KRW") else CURRENCY_KO.get(currency, currency)
    sep = "" if word == "원" else " "
    sign = "-" if absval < 0 else ""
    eok = round(abs(absval) / 1e8)
    jo, rest = divmod(eok, 10000)
    if jo and rest:
        return f"{sign}{jo:,}조 {rest:,}억{sep}{word}"
    if jo:
        return f"{sign}{jo:,}조{sep}{word}"
    if eok:
        return f"{sign}{eok:,}억{sep}{word}"
    return f"{sign}{abs(absval):,.0f}{sep}{word}"


def human_amount(absval: float, currency: Optional[str]) -> str:
    """원 단위 값을 읽기 쉬운 단위로(엑셀·화면 보조 표기)."""
    if currency == "KRW" or currency is None:
        for s, w in ((1e12, "조"), (1e8, "억"), (1e4, "만")):
            if abs(absval) >= s:
                return f"{absval / s:,.2f}{w}{'원' if currency else ''}".replace(".00", "")
        return f"{absval:,.0f}{'원' if currency else ''}"
    for s, w in ((1e9, "bn"), (1e6, "mn"), (1e3, "k")):
        if abs(absval) >= s:
            return f"{currency} {absval / s:,.2f}{w}".replace(".00", "")
    return f"{currency} {absval:,.2f}"
