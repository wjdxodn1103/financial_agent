"""주요 지표 목록 — 지표마다 발표 기관·현지 발표 시각·값 변환·감지 소스(앞에서부터 시도).

transform: yoy(전년 같은 달 대비 %) · mom(전월 대비 %) · chg(전월 대비 차이) · level(그대로) · level_k(÷1000)
sources: bls(미 노동통계국 시리즈 — 키 없이도 하루 25회, 키 있으면 500회) · fred(키 필요) · fomc(연준 보도자료 RSS) · ecos(한국은행, 키 필요)
값 감지 소스가 없는 지표는 일정만 보인다(실제치는 관리자가 넣을 수 있다).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

ET, KST, CET = "America/New_York", "Asia/Seoul", "Europe/Berlin"
COUNTRY_KO = {"KR": "한국", "US": "미국", "EU": "유럽", "CN": "중국", "JP": "일본"}
CATEGORY_KO = {"release": "발표", "meeting": "회의", "issue": "이슈", "industry": "산업", "earnings": "실적", "holiday": "휴장"}


@dataclass(frozen=True)
class Indicator:
    id: str
    name: str
    short: str
    country: str
    category: str  # release | meeting
    importance: int
    agency: str
    time: str  # 현지 발표 시각 HH:MM
    tz: str
    unit: str
    transform: str
    decimals: int = 1
    freq: str = "M"  # M | Q | W | meeting
    fred: Optional[str] = None
    bls: Optional[str] = None
    ecos: Optional[Tuple[str, str, str]] = None  # (통계표 이름에 든 말, 항목 이름, 주기) — 코드는 처음 쓸 때 찾는다
    fomc: bool = False
    aliases: Tuple[str, ...] = ()
    url: str = ""


def I(id: str, name: str, short: str, country: str, category: str, importance: int, agency: str, time: str, tz: str, unit: str, transform: str, **kw) -> Indicator:
    kw["aliases"] = tuple(kw.get("aliases") or ())
    return Indicator(id, name, short, country, category, importance, agency, time, tz, unit, transform, **kw)


INDICATORS: List[Indicator] = [
    # 미국 — 시각은 현지(ET, 서머타임 반영해 한국 시각으로 바꾼다)
    I("us_cpi", "미국 소비자물가(CPI) 전년비", "CPI", "US", "release", 3, "BLS", "08:30", ET, "%", "yoy", fred="CPIAUCSL", bls="CUSR0000SA0",
      aliases=("CPI", "소비자물가", "물가", "인플레이션"), url="https://www.bls.gov/cpi/"),
    I("us_core_cpi", "미국 근원 CPI 전년비", "근원 CPI", "US", "release", 3, "BLS", "08:30", ET, "%", "yoy", fred="CPILFESL", bls="CUSR0000SA0L1E",
      aliases=("근원 CPI", "근원물가", "core CPI"), url="https://www.bls.gov/cpi/"),
    I("us_nfp", "미국 비농업 고용 증감", "비농업 고용", "US", "release", 3, "BLS", "08:30", ET, "천 명", "chg", decimals=0, fred="PAYEMS", bls="CES0000000001",
      aliases=("고용보고서", "고용 보고서", "비농업", "NFP", "고용지표", "일자리"), url="https://www.bls.gov/ces/"),
    I("us_unrate", "미국 실업률", "실업률", "US", "release", 3, "BLS", "08:30", ET, "%", "level", fred="UNRATE", bls="LNS14000000",
      aliases=("실업률", "고용보고서", "고용 보고서"), url="https://www.bls.gov/cps/"),
    I("us_ppi", "미국 생산자물가(PPI) 전월비", "PPI", "US", "release", 2, "BLS", "08:30", ET, "%", "mom", fred="PPIFIS", bls="WPSFD4",
      aliases=("PPI", "생산자물가"), url="https://www.bls.gov/ppi/"),
    I("us_jolts", "미국 구인건수(JOLTS)", "JOLTS", "US", "release", 2, "BLS", "10:00", ET, "천 건", "level", decimals=0, fred="JTSJOL", bls="JTS000000000000000JOL",
      aliases=("JOLTS", "구인", "구인건수"), url="https://www.bls.gov/jlt/"),
    I("us_retail", "미국 소매판매 전월비", "소매판매", "US", "release", 2, "Census", "08:30", ET, "%", "mom", fred="RSAFS",
      aliases=("소매판매", "리테일"), url="https://www.census.gov/retail/"),
    I("us_gdp", "미국 실질 GDP(전기비 연율)", "GDP", "US", "release", 3, "BEA", "08:30", ET, "%", "level", freq="Q", fred="A191RL1Q225SBEA",
      aliases=("GDP", "성장률", "국내총생산"), url="https://www.bea.gov/data/gdp/gross-domestic-product"),
    I("us_core_pce", "미국 근원 PCE 물가 전년비", "근원 PCE", "US", "release", 3, "BEA", "08:30", ET, "%", "yoy", fred="PCEPILFE",
      aliases=("PCE", "근원 PCE", "개인소비지출"), url="https://www.bea.gov/data/personal-consumption-expenditures-price-index"),
    I("us_claims", "미국 신규 실업수당 청구", "실업수당 청구", "US", "release", 2, "DOL", "08:30", ET, "천 건", "level_k", decimals=0, freq="W", fred="ICSA",
      aliases=("실업수당", "신규 실업수당", "주간 실업"), url="https://www.dol.gov/ui/data.pdf"),
    I("us_fomc", "FOMC 기준금리 결정(상단)", "FOMC", "US", "meeting", 3, "Fed", "14:00", ET, "%", "level", decimals=2, freq="meeting", fred="DFEDTARU", fomc=True,
      aliases=("FOMC", "연준", "미국 금리", "연방기금금리", "Fed"), url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"),
    # 유럽
    I("eu_ecb", "ECB 통화정책 결정(예금금리)", "ECB", "EU", "meeting", 3, "ECB", "14:15", CET, "%", "level", decimals=2, freq="meeting",
      aliases=("ECB", "유럽중앙은행", "유럽 금리"), url="https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"),
    # 한국 — 국가데이터처 보도는 08:00(KST)
    I("kr_cpi", "한국 소비자물가 전년비", "소비자물가", "KR", "release", 3, "국가데이터처", "08:00", KST, "%", "yoy", ecos=("소비자물가지수", "총지수", "M"),
      aliases=("한국 CPI", "한국 물가", "소비자물가동향", "물가"), url="https://mods.go.kr/lcofNewsPln.es?mid=a60303000000"),
    I("kr_jobs", "한국 고용동향(실업률)", "고용동향", "KR", "release", 2, "국가데이터처", "08:00", KST, "%", "level", ecos=("경제활동인구", "실업률", "M"),
      aliases=("고용동향", "한국 실업률", "한국 고용"), url="https://mods.go.kr/lcofNewsPln.es?mid=a60303000000"),
    I("kr_ip", "한국 산업활동동향", "산업활동동향", "KR", "release", 2, "국가데이터처", "08:00", KST, "", "level",
      aliases=("산업활동", "산업생산"), url="https://mods.go.kr/lcofNewsPln.es?mid=a60303000000"),
    I("kr_bok", "한국은행 기준금리 결정", "금통위", "KR", "meeting", 3, "한국은행", "10:00", KST, "%", "level", decimals=2, freq="meeting", ecos=("한국은행 기준금리", "한국은행 기준금리", "D"),
      aliases=("금통위", "한국은행", "한은", "기준금리", "한국 금리"), url="https://www.bok.or.kr/"),
]
BY_ID: Dict[str, Indicator] = {i.id: i for i in INDICATORS}


def detectable(ind: Indicator) -> bool:
    """값을 자동으로 감지할 소스가 있는지(키 상태와 별개로 지표 정의상)."""
    return bool(ind.bls or ind.fred or ind.fomc or ind.ecos)


def find(text: str) -> List[Indicator]:
    """'CPI랑 고용보고서' → 지표들(이름·약칭·별칭에 든 말). 한국/미국 말이 있으면 그 나라 먼저."""
    t = (text or "").lower()
    hits = [i for i in INDICATORS if any(a.lower() in t for a in (i.short, i.name, *i.aliases))]
    if "한국" in t or "국내" in t:
        hits = [i for i in hits if i.country == "KR"] or hits
    elif "미국" in t or "미 " in t:
        hits = [i for i in hits if i.country == "US"] or hits
    return hits
