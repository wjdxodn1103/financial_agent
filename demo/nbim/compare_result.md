# 작성 결과 ↔ 원본 반기 보고서 숫자 대조

- 리포트 세션 `rmvkazd0pexh9` · 원본 `03_nbim_gpfg_half_year_2025_investments.pdf` · 2026-10-30 15:17 · `demo/nbim/compare.py` (LLM 0회)
- 원본에서 읽은 숫자 656개 (amount 94 · percent 126 · plain 394 · pp 34 · unknown 8) — 본문 단위 숫자 + 표 칸(표 제목의 단위), 그림 축 눈금·연도 머리 제외
- 같은 값 = 반올림 한 단위까지(`same_value`, 같은 자릿수의 한 단위 차이 6.74% vs 6.73% 는 다름) · %·%p 는 값끼리 · 금액은 abs 값끼리(통화가 둘 다 있으면 같아야) · 크기만 같으면 '부호 다름'으로 일치
- '있음' = 그 값이 원본 어딘가에 있다는 뜻 — 같은 지표의 값인지는 아래 '원본 위치' 칸으로 확인

## 원본에 있는 숫자 비율

| 섹션 | 본문 숫자 | 원본에 있음 | 비율 |
|---|---:|---:|---:|
| 주식 | 16 | 16 | 100.0% |
| 채권 | 20 | 18 | 90.0% |
| 투자 체계(위임 한도) | 16 | 16 | 100.0% |
| **전체** | **52** | **50** | **96.2%** |

## 원본에 없는 숫자 (2개)

| 섹션 | 숫자 | 숫자 확인 판정 | 문장 |
|---|---|---|---|
| 채권 | 4.20% | 자료와 일치 | 금리 환경의 경우 미국 국채 10년 금리는 2024년 연말 4.57%에서 2025년 연말 4.20%로 하락했으며, 미국 기준금리 상단 역시 4.50%에서 3.75%로 인하됐다. |
| 채권 | 3.75% | 자료와 일치 | 금리 환경의 경우 미국 국채 10년 금리는 2024년 연말 4.57%에서 2025년 연말 4.20%로 하락했으며, 미국 기준금리 상단 역시 4.50%에서 3.75%로 인하됐다. |

## 숫자별 대조

| 섹션 | 숫자 | 원본 | 원본 위치 | 비고 |
|---|---|---|---|---|
| 주식 | 6.73% | 있음 | p.7 TABLE 2 · Equity investments |  |
| 주식 | 3.31% | 있음 | p.7 TABLE 2 · Fixed-income investments |  |
| 주식 | 4.02% | 있음 | p.7 TABLE 2 · Unlisted real estate investments |  |
| 주식 | 5.74% | 있음 | p.7 TABLE 2 · Return on fund |  |
| 주식 | 70.4% | 있음 | p.16 TABLE 13 · Equity portfolio 60–80 percent of fund's market value1 | 단위 미표기 표 값 |
| 주식 | 80% | 있음 | p.16 본문: ….06.2025 Allocation Equity portfolio 60–**80 percent** of fund's market value1 70.4 … |  |
| 주식 | 16.5% | 있음 | p.8 본문: …ncials perform best Financials returned **16.5 percent** in the first half of the year… |  |
| 주식 | -2.9% | 있음 | p.8 본문: …gas prices. Health care stocks returned **-2.9 percent** and amounted to 9.2 percent o… |  |
| 주식 | 17.0% | 있음 | p.9 TABLE 5 · Financials |  |
| 주식 | 27.5% | 있음 | p.9 TABLE 5 · Technology |  |
| 주식 | 17.8% | 있음 | p.8 TABLE 4 · Europe |  |
| 주식 | 1.4% | 있음 | p.8 TABLE 4 · North America |  |
| 주식 | 57.7% | 있음 | p.8 TABLE 4 · North America |  |
| 주식 | 22.2% | 있음 | p.8 TABLE 4 · Europe |  |
| 주식 | 10.5% | 있음 | p.8 TABLE 4 · Asia and Oceania |  |
| 주식 | 10.8% | 있음 | p.8 TABLE 4 · Emerging markets |  |
| 채권 | 3.31% | 있음 | p.7 TABLE 2 · Fixed-income investments |  |
| 채권 | 1.61% | 있음 | p.7 TABLE 2 · Fixed-income investments |  |
| 채권 | 1.67% | 있음 | p.7 TABLE 2 · Fixed-income investments |  |
| 채권 | 5.74% | 있음 | p.7 TABLE 2 · Return on fund |  |
| 채권 | 2.5% | 있음 | p.11 TABLE 6 · Government bonds2 |  |
| 채권 | 57.9% | 있음 | p.11 TABLE 6 · Government bonds2 |  |
| 채권 | 9.5% | 있음 | p.11 TABLE 6 · Securitised bonds |  |
| 채권 | 6.0% | 있음 | p.11 TABLE 6 · Securitised bonds |  |
| 채권 | 2.9% | 있음 | p.11 TABLE 6 · Inflation-linked bonds2 |  |
| 채권 | 24.9% | 있음 | p.11 TABLE 6 · Corporate bonds |  |
| 채권 | 5.5% | 있음 | p.11 TABLE 6 · Government-related bonds2 |  |
| 채권 | 9.8% | 있음 | p.11 TABLE 6 · Government-related bonds2 |  |
| 채권 | 2.9% | 있음 | p.11 TABLE 6 · Inflation-linked bonds2 |  |
| 채권 | 6.3% | 있음 | p.11 TABLE 6 · Inflation-linked bonds2 |  |
| 채권 | 4.57% | 있음 | p.16 본문: …d's investments 0.4 Credit risk Maximum **5 percent** of fixed-income investments m… |  |
| 채권 | 4.20% | **없음** | | 자료와 일치 |
| 채권 | 4.50% | 있음 | p.16 본문: …d's investments 0.4 Credit risk Maximum **5 percent** of fixed-income investments m… |  |
| 채권 | 3.75% | **없음** | | 자료와 일치 |
| 채권 | 5조 3,110억 크로네 | 있음 | p.5 TABLE 1 · Fixed-income investments |  |
| 채권 | 5조 2,530억 크로네 | 있음 | p.5 TABLE 1 · Fixed-income investments |  |
| 투자 체계(위임 한도) | 70.4% | 있음 | p.16 TABLE 13 · Equity portfolio 60–80 percent of fund's market value1 | 단위 미표기 표 값 |
| 투자 체계(위임 한도) | 80% | 있음 | p.16 본문: ….06.2025 Allocation Equity portfolio 60–**80 percent** of fund's market value1 70.4 … |  |
| 투자 체계(위임 한도) | 27.7% | 있음 | p.16 TABLE 13 · Fixed-income portfolio 20–40 percent of fund's market value1 | 단위 미표기 표 값 |
| 투자 체계(위임 한도) | 40% | 있음 | p.16 본문: …ket value 1.9 Fixed-income portfolio 20–**40 percent** of fund's market value1 27.7 … |  |
| 투자 체계(위임 한도) | 1.9% | 있음 | p.16 TABLE 13 · Unlisted real estate no more than 7 percent of the fund's market value | 단위 미표기 표 값 |
| 투자 체계(위임 한도) | 7% | 있음 | p.16 본문: … 70.4 Unlisted real estate no more than **7 percent** of the fund's market value 1.… |  |
| 투자 체계(위임 한도) | 0.4% | 있음 | p.16 TABLE 13 · Unlisted renewable energy infrastructure no more than 2 percent of the fund's market value | 단위 미표기 표 값 |
| 투자 체계(위임 한도) | 2% | 있음 | p.16 본문: …able energy infrastructure no more than **2 percent** of the fund's market value 0.… |  |
| 투자 체계(위임 한도) | 0.4%p | 있음 | p.16 TABLE 13 · Unlisted renewable energy infrastructure no more than 2 percent of the fund's market value | 단위 미표기 표 값 |
| 투자 체계(위임 한도) | 1.25%p | 있음 | p.16 본문: …the fund's market value 0.4 Market risk **1.25 percentage points** expected relative volatility … |  |
| 투자 체계(위임 한도) | 1.3% | 있음 | p.16 TABLE 13 · Maximum 5 percent of fixed-income investments may be rated below BBB- | 단위 미표기 표 값 |
| 투자 체계(위임 한도) | 5% | 있음 | p.16 본문: …d's investments 0.4 Credit risk Maximum **5 percent** of fixed-income investments m… |  |
| 투자 체계(위임 한도) | 3.2% | 있음 | p.16 TABLE 13 · Maximum 5 percent of fixed-income investments may be in emerging markets | 단위 미표기 표 값 |
| 투자 체계(위임 한도) | 5% | 있음 | p.16 본문: …d's investments 0.4 Credit risk Maximum **5 percent** of fixed-income investments m… |  |
| 투자 체계(위임 한도) | 9.7% | 있음 | p.16 TABLE 13 · Maximum 10 percent of voting shares in a listed company in the equity portfolio2 | 단위 미표기 표 값 |
| 투자 체계(위임 한도) | 10% | 있음 | p.16 본문: … emerging markets 3.2 Ownership Maximum **10 percent** of voting shares in a listed … |  |
