"""시장·거시 시리즈 목록 — 시리즈마다 공급자 사슬(앞에서부터 받아 보고 안 되면 다음), 대조 공급자, 허용 오차, 단위.

공급자를 바꿔 끼우는 자리: chain 의 (공급자, 코드)만 바꾸면 된다(Bloomberg·LSEG 를 붙이면 맨 앞에 둔다).
- 실데이터: fred(키 필요 — FRED_API_KEY), treasury(미 재무부 수익률 곡선, 키 없음), ecb(ECB 기준환율, 키 없음), nyfed(뉴욕 연은 실효금리, 키 없음)
- demo: 고정 시드로 만든 '가상' 값 — 저작권 있는 시리즈(주가지수·신용 스프레드·금)는 이것만, 실데이터 시리즈는 모든 실공급자가 실패할 때의 마지막 대체
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Series:
    id: str
    name: str
    group: str  # 금리 | 환율 | 원자재 | 주가지수 | 신용 | 거시
    unit: str
    change: str  # bp(금리·스프레드: 차이×100) | pct(나머지: 변화율 %) | pp(월간 지표: 차이 %p)
    freq: str = "D"  # D | M
    decimals: int = 2
    chain: Tuple[Tuple[str, str], ...] = ()
    check: Tuple[Tuple[str, str], ...] = ()  # 대조 공급자(같은 값을 다른 실데이터로)
    tol: float = 0.0  # 대조 허용 오차 — 금리: 절대(%p), 그 밖: 상대(0.005 = 0.5%)
    calc: Optional[Tuple[str, ...]] = None  # ("sub", a, b) — 다른 시리즈로 계산
    virtual: bool = False  # 실데이터 없이 데모 값만(가상)
    demo: Dict[str, float] = field(default_factory=dict)  # 데모 값 {base, vol, drift, kind: walk|level}


def S(id: str, name: str, group: str, unit: str, change: str, freq: str = "D", decimals: int = 2, chain=(), check=(), tol: float = 0.0, calc=None, virtual: bool = False, **demo: float) -> Series:
    return Series(id, name, group, unit, change, freq, decimals, tuple(chain), tuple(check), tol, calc, virtual, dict(demo))


SERIES: List[Series] = [
    # 금리
    S("us_ff", "미 연방기금 실효금리", "금리", "%", "bp", chain=[("fred", "DFF"), ("nyfed", "effr")], check=[("nyfed", "effr")], tol=0.02, base=3.9, vol=0.01, level=1),
    S("us_2y", "미 국채 2년", "금리", "%", "bp", chain=[("fred", "DGS2"), ("treasury", "2 Yr")], check=[("treasury", "2 Yr")], tol=0.03, base=3.6, vol=0.04, level=1),
    S("us_10y", "미 국채 10년", "금리", "%", "bp", chain=[("fred", "DGS10"), ("treasury", "10 Yr")], check=[("treasury", "10 Yr")], tol=0.03, base=4.1, vol=0.04, level=1),
    S("us_10y2y", "미 10년−2년 금리차", "금리", "%p", "bp", calc=("sub", "us_10y", "us_2y")),
    # 환율
    S("krw_usd", "원/달러", "환율", "원", "pct", chain=[("fred", "DEXKOUS"), ("ecb", "KRW")], check=[("ecb", "KRW")], tol=0.006, base=1395, vol=0.004),
    S("jpy_usd", "엔/달러", "환율", "엔", "pct", chain=[("fred", "DEXJPUS"), ("ecb", "JPY")], check=[("ecb", "JPY")], tol=0.006, base=150, vol=0.005),
    S("usd_eur", "달러/유로", "환율", "달러", "pct", decimals=4, chain=[("fred", "DEXUSEU"), ("ecb", "USD")], check=[("ecb", "USD")], tol=0.006, base=1.16, vol=0.004),
    S("usd_broad", "달러지수(광의)", "환율", "pt", "pct", chain=[("fred", "DTWEXBGS")], base=121, vol=0.003),
    # 원자재
    S("wti", "WTI 유가", "원자재", "달러/배럴", "pct", chain=[("fred", "DCOILWTICO")], base=64, vol=0.018),
    S("brent", "Brent 유가", "원자재", "달러/배럴", "pct", chain=[("fred", "DCOILBRENTEU")], base=67, vol=0.017),
    S("natgas", "천연가스(헨리허브)", "원자재", "달러/MMBtu", "pct", chain=[("fred", "DHHNGSP")], base=3.3, vol=0.035),
    S("gold", "금", "원자재", "달러/온스", "pct", virtual=True, base=3950, vol=0.009),
    # 거시(월간)
    S("us_cpi_yoy", "미 CPI 전년비", "거시", "%", "pp", freq="M", decimals=1, chain=[("fred", "CPIAUCSL:pc1")], base=2.9, vol=0.12, level=1),
    S("us_unrate", "미 실업률", "거시", "%", "pp", freq="M", decimals=1, chain=[("fred", "UNRATE")], base=4.3, vol=0.08, level=1),
    # 주가지수(가상 — 지수 값은 라이선스 데이터)
    S("spx", "S&P 500", "주가지수", "pt", "pct", virtual=True, base=6650, vol=0.009),
    S("acwi", "MSCI ACWI", "주가지수", "pt", "pct", virtual=True, base=960, vol=0.008),
    S("nasdaq", "나스닥 종합", "주가지수", "pt", "pct", virtual=True, base=22400, vol=0.012),
    S("sx5e", "Euro Stoxx 50", "주가지수", "pt", "pct", virtual=True, base=5550, vol=0.009),
    S("nikkei", "닛케이 225", "주가지수", "pt", "pct", virtual=True, base=46500, vol=0.011),
    S("kospi", "KOSPI", "주가지수", "pt", "pct", virtual=True, base=3550, vol=0.010),
    # 신용(가상)
    S("us_ig_oas", "미 투자등급 스프레드", "신용", "bp", "bp", decimals=0, virtual=True, base=82, vol=1.6, level=1),
    S("us_hy_oas", "미 하이일드 스프레드", "신용", "bp", "bp", decimals=0, virtual=True, base=295, vol=6.0, level=1),
]

BY_ID: Dict[str, Series] = {s.id: s for s in SERIES}
GROUPS: List[str] = ["금리", "환율", "원자재", "주가지수", "신용", "거시"]
PROVIDER_KO = {"fred": "FRED", "treasury": "미 재무부", "ecb": "ECB", "nyfed": "뉴욕 연은", "demo": "데모(가상)"}


def full_chain(s: Series) -> List[Tuple[str, str]]:
    """실공급자 사슬 + 마지막 대체 = 데모(가상). 가상 시리즈는 데모만. 계산 시리즈는 빈 목록."""
    if s.calc:
        return []
    if s.virtual:
        return [("demo", s.id)]
    return [*s.chain, ("demo", s.id)]


def view(s: Series) -> Dict[str, object]:
    return {"id": s.id, "name": s.name, "group": s.group, "unit": s.unit, "change": s.change, "freq": s.freq, "decimals": s.decimals,
            "virtual": s.virtual, "calc": list(s.calc) if s.calc else None, "providers": [p for p, _c in full_chain(s)]}
