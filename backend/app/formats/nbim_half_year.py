"""반기 운용보고서 — NBIM(노르웨이 국부펀드) 2025 반기 보고서 Investments 장의 구성을 옮긴 고정 양식.

원본: demo/public_samples/03_nbim_gpfg_half_year_2025_investments.pdf (TABLE 1–13, CHART 1–8).
표 13개는 원본 표와 같은 순서·번호, 그림은 표 데이터로 그리는 막대 그래프 4개(원본의 분기 시계열 그래프는 다음 단계).

블록 = 양식에 딸린 도구. 표는 '데이터 워크북'(성과 데이터 엑셀)의 시트 하나를 그대로 옮기고(sheet), 그림은 표 블록의 행·열로 그린다(from).
  id      숫자 없는 slug — 본문 숫자 인식에 걸리지 않게
  no      양식에 고정된 번호(<표 4>·<그림 2>) — 본문이 이 번호로 가리킨다
  unit    캡션 단위, number  워드·엑셀 숫자 서식
  rows    그림: 범주로 쓸 행 이름(없으면 '합계'가 아닌 모든 행), cols  계열로 쓸 열 이름
"""
from __future__ import annotations

from typing import Any, Dict, List

SOURCE = "NBIM 성과 데이터"

BLOCKS: Dict[str, Dict[str, Any]] = {
    # ── 표 ──
    "key_figures": {"kind": "table", "no": 1, "title": "기금 핵심 수치(시장가치·기금 가치 변동)", "sheet": "표1_핵심수치", "unit": "십억 크로네", "number": "#,##0"},
    "returns_by_asset": {"kind": "table", "no": 2, "title": "자산군별 수익률", "sheet": "표2_자산군별수익률", "unit": "%", "number": "0.00"},
    "historical_key": {"kind": "table", "no": 3, "title": "장기 핵심 지표(1998년 이후·최근 10년·최근 12개월, 연환산)", "sheet": "표3_장기핵심지표", "unit": "%", "number": "0.00"},
    "equity_by_region": {"kind": "table", "no": 4, "title": "지역별 주식 투자 수익률과 비중", "sheet": "표4_주식_지역별", "unit": "%", "number": "0.0"},
    "equity_by_sector": {"kind": "table", "no": 5, "title": "섹터별 주식 투자 수익률과 비중", "sheet": "표5_주식_섹터별", "unit": "%", "number": "0.0"},
    "fixed_income_by_sector": {"kind": "table", "no": 6, "title": "섹터별 채권 투자 수익률과 비중", "sheet": "표6_채권_섹터별", "unit": "%", "number": "0.0"},
    "real_estate_value": {"kind": "table", "no": 7, "title": "부동산 투자 평가액", "sheet": "표7_부동산_평가액", "unit": "백만 크로네", "number": "#,##0"},
    "real_estate_return": {"kind": "table", "no": 8, "title": "비상장 부동산 수익 구성", "sheet": "표8_비상장부동산_수익구성", "unit": "%p", "number": "0.0"},
    "infra_value": {"kind": "table", "no": 9, "title": "비상장 재생에너지 인프라 평가액", "sheet": "표9_인프라_평가액", "unit": "백만 크로네", "number": "#,##0"},
    "infra_return": {"kind": "table", "no": 10, "title": "비상장 재생에너지 인프라 수익률", "sheet": "표10_인프라_수익률", "unit": "%", "number": "0.0"},
    "relative_history": {"kind": "table", "no": 11, "title": "기간별 상대수익률·추적오차·정보비율(연환산)", "sheet": "표11_상대수익", "unit": "%p", "number": "0.00"},
    "relative_contrib": {"kind": "table", "no": 12, "title": "운용 영역별 상대수익 기여", "sheet": "표12_운용영역별기여", "unit": "%p", "number": "0.00"},
    "mandate_limits": {"kind": "table", "no": 13, "title": "위임 한도와 실제(위험·노출)", "sheet": "표13_위임한도", "unit": "%", "number": "0.0"},
    # ── 그림(표 데이터) ──
    "chart_asset_value": {"kind": "chart", "no": 1, "title": "자산군별 시장가치", "from": "key_figures", "unit": "십억 크로네", "number": "#,##0",
                          "rows": ["주식 투자 시장가치", "채권 투자 시장가치", "비상장 부동산 시장가치", "비상장 인프라 시장가치"], "cols": ["2024년", "2025 상반기"]},
    "chart_equity_region": {"kind": "chart", "no": 2, "title": "지역별 주식 투자 수익률", "from": "equity_by_region", "unit": "%", "number": "0.0", "cols": ["수익률"]},
    "chart_equity_sector": {"kind": "chart", "no": 3, "title": "섹터별 주식 투자 수익률", "from": "equity_by_sector", "unit": "%", "number": "0.0", "cols": ["수익률"], "horizontal": True},
    "chart_relative_contrib": {"kind": "chart", "no": 4, "title": "운용 영역별 상대수익 기여", "from": "relative_contrib", "unit": "%p", "number": "0.00", "cols": ["기여도"]},
}
for _id, _b in BLOCKS.items():
    _b["id"] = _id
    _b.setdefault("source", SOURCE)

_STYLE = "NBIM 반기 보고서 문체: 첫 문장에 기간 수익률·핵심 결론, 짧은 단락 2~4개, 소제목 없이. 표·그림은 시스템이 섹션 뒤에 붙이니 본문은 핵심 숫자만 쓰고 <표 n>·<그림 n> 으로 가리킨다."

ITEMS: List[Dict[str, Any]] = [
    {"id": "investments", "title": "투자 요약", "phase": "front", "level": "required", "aliases": ["투자", "요약", "investments", "summary"],
     "desc": "기금 전체의 반기 수익률과 벤치마크 대비 상대수익, 기금 가치 변동(투자 수익·정부 자금 유입·크로네 환율 효과)을 첫 단락에 쓰고, 기말 자산군 비중과 자산군별 수익률을 이어서 쓴다. " + _STYLE,
     "queries": ["fund return first half 2025 benchmark", "fund value change krone inflow", "기금 수익률 상반기 기금 가치 변동"],
     "blocks": ["key_figures", "returns_by_asset", "historical_key", "chart_asset_value"]},
    {"id": "equities", "title": "주식", "phase": "body", "level": "required", "aliases": ["주식 투자", "equities", "equity investments"],
     "desc": "주식 투자 수익률과 가장 강한·약한 섹터를 먼저 쓰고, 최고 성과 섹터의 기여 요인(자료에 있는 만큼), 지역별 수익률을 이어 쓴다. " + _STYLE,
     "queries": ["equity investments return sectors financials", "European banks contribution equity", "주식 투자 수익률 섹터 지역"],
     "blocks": ["equity_by_region", "equity_by_sector", "chart_equity_region", "chart_equity_sector"]},
    {"id": "fixed_income", "title": "채권", "phase": "body", "level": "required", "aliases": ["채권 투자", "fixed income", "fixed-income investments"],
     "desc": "채권 투자 수익률, 금리·환율 환경, 섹터별 수익률(국채·회사채 등)과 비중을 쓴다. " + _STYLE,
     "queries": ["fixed-income investments return government bonds yields", "채권 투자 수익률 국채 금리"],
     "blocks": ["fixed_income_by_sector"]},
    {"id": "real_estate", "title": "부동산", "phase": "body", "level": "required", "aliases": ["부동산 투자", "real estate"],
     "desc": "전체 부동산(비상장+상장) 수익률과 기금 내 비중, 비상장 부동산 수익의 구성(임대 수익·가치 변동·환율)을 쓴다. " + _STYLE,
     "queries": ["real estate investments return unlisted listed", "부동산 투자 수익률 비상장 임대 수익"],
     "blocks": ["real_estate_value", "real_estate_return"]},
    {"id": "infrastructure", "title": "재생에너지 인프라", "phase": "body", "level": "recommended", "aliases": ["인프라", "infrastructure", "renewable energy infrastructure"],
     "desc": "비상장 재생에너지 인프라 수익률과 그 원인(전력 판매 수익·가치 변동·환율), 운영 중·개발 중 자산을 자료에 있는 만큼 쓴다. " + _STYLE,
     "queries": ["unlisted renewable energy infrastructure return", "재생에너지 인프라 수익률"],
     "blocks": ["infra_value", "infra_return"]},
    {"id": "relative_return", "title": "상대수익률", "phase": "body", "level": "required", "aliases": ["상대 수익률", "relative return"],
     "desc": "벤치마크 대비 상대수익률(%p·금액)과 운용 영역별 기여(주식·채권·실물자산·자산배분)를 쓰고, 장기 상대수익·추적오차를 덧붙인다. " + _STYLE,
     "queries": ["relative return benchmark equity management contribution", "상대수익률 벤치마크 운용 기여"],
     "blocks": ["relative_history", "relative_contrib", "chart_relative_contrib"]},
    {"id": "framework", "title": "투자 체계(위임 한도)", "phase": "body", "level": "required", "aliases": ["투자 체계", "위임 한도", "investment framework"],
     "desc": "재무부 위임 한도(자산배분·시장위험·신용위험·신흥시장·지분 한도)와 기말 실제 값을 비교해 한도 안에서 운용됐는지 쓴다. " + _STYLE,
     "queries": ["investment framework limits Ministry of Finance", "위임 한도 위험 노출"],
     "blocks": ["mandate_limits"]},
    {"id": "operational_risk", "title": "운영 리스크 관리", "phase": "back", "level": "recommended", "aliases": ["운영 리스크", "operational risk"],
     "desc": "운영 리스크 관리 체계와 기간 중 사건(있으면)을 자료에 있는 만큼 짧게 쓴다. 자료에 없으면 없다고 쓴다.",
     "queries": ["operational risk management", "운영 리스크"], "blocks": []},
    {"id": "responsible", "title": "책임투자", "phase": "back", "level": "recommended", "aliases": ["책임 투자", "responsible investment"],
     "desc": "의결권 행사(안건 수·주총 수)와 기업 관여 활동을 자료에 있는 만큼 쓴다.",
     "queries": ["voting shareholder meetings proposals responsible investment", "책임투자 의결권 행사"], "blocks": []},
]

FORMAT: Dict[str, Any] = {
    "kind": "format",
    "title": "반기 운용보고서 (NBIM 양식)",
    "desc": "국부펀드 반기 운용성과 보고서 — 기금 가치 변동·자산군별 수익률·상대수익·위임 한도를 정해진 표 13개·그림 4개와 함께 씁니다. 숫자는 성과 데이터 엑셀에서 코드가 채웁니다.",
    "tags": ["운용성과", "반기", "국부펀드", "NBIM", "자산배분", "상대수익"],
    "sample": "NBIM Government Pension Fund Global — Half-year report 2025(Investments)",
    "dataNote": "성과 데이터 엑셀: 시트 이름 = 블록의 시트(표1_핵심수치 …). 제목 줄·(단위: …) 줄 바로 아래 머리 행.",
    "items": ITEMS,
    "order": ["equities", "fixed_income", "real_estate", "infrastructure", "relative_return", "framework", "operational_risk", "responsible", "investments"],
    "blocks": BLOCKS,
}
