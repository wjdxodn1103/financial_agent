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
# 본문 금액 뒤에 붙는 통화 낱말 — '19조 5,860억 크로네' · '18억 6,000만 달러'
_CUR_TAIL = r"(?:원|크로네|달러|유로|엔|위안)?"
# 천 단위 띄어쓰기('19 586' — 노르웨이·유럽 보고서): 일반 공백·줄 바꿈 없는 공백·좁은 공백·가는 공백
_THIN = r"[    ]"
_NUM = re.compile(r"^\s*([(\[]?)\s*([△▲▼\-–−+]?)\s*([$€£¥₩]?)\s*(\d{1,3}(?:,\d{3})+|\d{1,3}(?:" + _THIN + r"\d{3})+|\d+)(\.\d+)?\s*(%|%p|bp)?\s*([)\]]?)\s*$")


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
    value = float(re.sub(r"[,\s   ]", "", ip) + (fp or ""))
    negative = bool(sign and sign in "△▲▼-–−") or bool(paren_l and paren_r)
    # ▲ 는 한국 공시에서 '증가'를 뜻하기도 한다 — 표 칸 단독이면 대개 음수(△)와 같은 쓰임이라 같이 본다(△가 표준)
    if negative:
        value = -value
    return value, {"percent": pct in ("%", "%p"), "pp": pct == "%p", "bp": pct == "bp", "decimals": len(fp) - 1 if fp else 0}


_AMOUNT = re.compile(
    r"(?P<sign>[△▲\-−]?)(?P<cur1>[$€£¥₩]|US\$)?\s?(?P<num>(?<![\d.,])\d{1,3}(?:[    ]\d{3})+(?=\s?(?:billion|million|trillion|bn|mn)\b)|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s?"
    rf"(?P<unit>%p|%|bp|조\s?\d{{1,4}}(?:,\d{{3}})*\s?억\s?{_CUR_TAIL}|조\s?{_CUR_TAIL}|십억\s?{_CUR_TAIL}|억\s?\d{{1,4}}(?:,\d{{3}})*\s?만\s?{_CUR_TAIL}|억\s?{_CUR_TAIL}|백만\s?{_CUR_TAIL}|천만\s?{_CUR_TAIL}|천\s?원|만\s?{_CUR_TAIL}|원|크로네|달러|유로|엔|위안|배|bn|mn|billion|million|trillion|명|개|건|톤)?",
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
        num = float(re.sub(r"[,\s   ]", "", m.group("num")))
        sign = -1.0 if m.group("sign") in ("△", "-", "−") else 1.0
        decimals = len(m.group("num").split(".")[1]) if "." in m.group("num") else 0
        if (unit.startswith("조") and "억" in unit) or (unit.startswith("억") and "만" in unit):
            # "3조 1,500억원" — 조 + 억 · "18억 6,000만 달러" — 억 + 만
            big, small = (1e12, 1e8) if unit.startswith("조") else (1e8, 1e4)
            rest = float(re.sub(r"[^\d]", "", unit.split("조" if big == 1e12 else "억", 1)[1].split("억" if big == 1e12 else "만", 1)[0]) or 0)
            absval = sign * (num * big + rest * small)
            cur_word = parse_unit(re.sub(r"[\d,\s조억만]", "", unit)).currency or "KRW"
            out.append({"raw": raw, "value": sign * num, "unit": unit, "abs": absval, "percent": False, "step": small, "decimals": decimals, "currency": cur_word, "start": m.start(), "end": m.end()})
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
    """한국어 본문용 '19조 5,860억 크로네' · '18억 6,000만 달러' — 위 두 단계(조·억 또는 억·만, 그 아래는 반올림). find_amounts 가 그대로 읽는 꼴이라
    작성 모델이 이 표기를 옮겨 쓰면 숫자 확인이 원장 값과 맞춘다(모델에게 단위 환산을 시키지 않는다)."""
    word = "원" if currency in (None, "KRW") else CURRENCY_KO.get(currency, currency)
    sep = "" if word == "원" else " "
    sign = "-" if absval < 0 else ""
    if abs(absval) >= 1e12:
        jo, rest = divmod(round(abs(absval) / 1e8), 10000)
        return f"{sign}{jo:,}조 {rest:,}억{sep}{word}" if rest else f"{sign}{jo:,}조{sep}{word}"
    if abs(absval) >= 1e8:  # 1조 아래는 억·만(18.6억을 19억으로 반올림하지 않는다)
        eok, man = divmod(round(abs(absval) / 1e4), 10000)
        return f"{sign}{eok:,}억 {man:,}만{sep}{word}" if man else f"{sign}{eok:,}억{sep}{word}"
    if abs(absval) >= 1e4:
        return f"{sign}{round(abs(absval) / 1e4):,}만{sep}{word}"
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


# 한국어는 손실을 양수로 쓴다('영업손실 68.63억원' · '영업손실은 2023년 55.72억원, 2024년 68.93억원' · '110.13억원 손실') — 원장은 −6,862,597,018.
# 금액 앞에서 가장 가까운 지표 낱말이 손실·적자이거나 금액 바로 뒤가 손실·적자면 부호를 뒤집은 값도 같은 값으로 본다(원래 값도 남긴다).
_METRIC_WORD = re.compile(r"손실|적자|이익|흑자|매출|수익|비용|자산|부채|자본|현금|원가")
_LOSS_AFTER = re.compile(r"^\s*(?:의\s*)?(?:손실|적자)")


def loss_variants(a: Dict[str, Any], sentence: str) -> List[Dict[str, Any]]:
    """본문 금액 → [그 금액] 또는 손실 문맥이면 [그 금액, 부호 뒤집은 금액]."""
    if a.get("percent") or (a.get("value") or 0) <= 0:
        return [a]
    s, raw = sentence or "", a.get("raw") or ""
    i = s.find(raw)
    if i < 0:
        return [a]
    words = _METRIC_WORD.findall(s[:i])
    if (words and words[-1] in ("손실", "적자")) or _LOSS_AFTER.match(s[i + len(raw):]):
        return [a, {**a, "value": -a["value"], "abs": -(a.get("abs") or 0)}]
    return [a]


def scale_slip(a_abs: float, b_abs: float) -> int:
    """두 금액의 유효 숫자는 같은데 자릿수만 10^k 배 다르면 k(≠0), 아니면 0.
    '1조 9,586억'(1.9586e12) vs 원문 '19 586 billion'(1.9586e13) → -1. 단위 환산 실수를 잡는 데 쓴다."""
    import math

    if not a_abs or not b_abs or (a_abs > 0) != (b_abs > 0):
        return 0
    r = math.log10(abs(a_abs) / abs(b_abs))
    k = round(r)
    return k if k and abs(r - k) < 0.002 else 0


_EN_SCALE = ("billion", "million", "trillion", "bn", "mn")
_TAIL_CUR = re.compile(r"\s*(kroner|nok|dollars?|usd|euros?|eur|yen|jpy|won|krw|pounds?|gbp)\b", re.I)
_CUR_CODE = {"kroner": "NOK", "nok": "NOK", "dollar": "USD", "dollars": "USD", "usd": "USD", "euro": "EUR", "euros": "EUR", "eur": "EUR",
             "yen": "JPY", "jpy": "JPY", "won": "KRW", "krw": "KRW", "pound": "GBP", "pounds": "GBP", "gbp": "GBP"}


def korean_hints(text: str, limit: int = 6) -> List[str]:
    """영문 규모 금액('19 586 billion kroner') → '19 586 billion kroner = 19조 5,860억 크로네'. 작성 자료 옆에 붙여
    모델이 billion 을 조·억으로 바꾸다 자릿수를 틀리지 않게 한다(2026-10-29 시험: 15번 중 4번 틀림)."""
    out: List[str] = []
    for a in find_amounts(text or ""):
        unit = (a.get("unit") or "").lower()
        if a["percent"] or not any(unit.startswith(w) for w in _EN_SCALE):
            continue
        cur = a.get("currency")
        m = _TAIL_CUR.match(text, a["end"])
        if m:
            cur = _CUR_CODE.get(m.group(1).lower(), cur)
        ko = korean_amount(a["abs"], cur) if cur else korean_amount(a["abs"], "KRW").removesuffix("원")
        out.append(f"{a['raw']}{(' ' + m.group(1)) if m else ''} = {ko}")
    return list(dict.fromkeys(out))[:limit]


def sig_digits(raw: str) -> int:
    """표기의 유효 숫자 수 — '1조 9,586억' → 5, '7억' → 1. 단위 의심은 3자리 이상일 때만(우연히 같은 짧은 숫자를 피한다)."""
    return len(re.sub(r"\D", "", raw or "").lstrip("0"))
