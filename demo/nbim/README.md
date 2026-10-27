# 반기 운용보고서(NBIM 양식) MVP — 고정 양식 + 양식별 표·그림 도구

공개 샘플 `demo/public_samples/03_nbim_gpfg_half_year_2025_investments.pdf` 의 구성을 고정 양식으로 옮겼다.
섹션 9개 · 표 13개(원본 TABLE 1–13) · 그림 4개(표 데이터 막대 그래프). 정의 = `backend/app/formats/nbim_half_year.py`.

## 준비 (백엔드 8200 이 떠 있어야 한다)

```bash
backend/.venv/Scripts/python demo/nbim/make_pack.py        # 성과 데이터 엑셀(표 13개 = 시트 13개, 값은 공개 보고서에서)
backend/.venv/Scripts/python demo/nbim/check_pack.py       # 업로드와 같은 경로로 읽어 보기(칸 값·소수 자리·원장 충돌 0)
backend/.venv/Scripts/python demo/nbim/fetch_sources.py    # NBIM 보도자료를 받아 sources/*.md 로(연락처 제외)
backend/.venv/Scripts/python demo/nbim/setup_nbim.py       # 워크스페이스 'NBIM (공개 자료 가정)' + 자료 + 양식 리포트
```

원본 반기 보고서 PDF 는 근거로 올리지 않는다 — 작성 결과와 비교할 정답지.
정답지 대조: `backend/.venv/Scripts/python -I demo/nbim/compare.py [세션 id]` (기본 = `.report`) — 본문 숫자가 원본 PDF 에 있는 비율(섹션별·전체)과 없는 숫자 목록 → 콘솔 + `compare_result.md` (LLM 0회).

## 흐름

1. 쓰기 → '보고서 양식'에서 검색(예: 반기 운용성과) → **이 양식으로 쓰기**. 쓰기 전에도 표·그림은 데이터에서 채워져 보인다.
2. "주식 섹션 써줘" → 확인 카드 없이 바로 작성(전문가용). 끝나면 대화에 **작업 설명** — 이렇게 쓴 이유(작성 메모) · 사용한 근거(자료·시트·인용 숫자) · 붙인 표·그림 · 숫자 대조.
3. "주식 섹션에서 섹터별 그래프 빼줘" / "그림 3 다시 넣어줘" → 양식에 딸린 도구(add_block·remove_block).
4. 표 칸을 누르면 원본 데이터 칸이 강조되어 열린다. 본문 숫자는 숫자 확인 탭이 데이터 칸과 대조.
5. 내려받기: DOCX(양식 스타일 · 네이티브 워드 표 · 데이터 편집되는 워드 차트) + 표·그래프 데이터 XLSX(블록마다 시트 · 엑셀 차트).

## 새 양식을 더하려면

`backend/app/formats/` 에 모듈 하나(섹션 items·order + blocks)를 만들고 `registry.py` 의 FORMATS 에 등록한다.
표 블록 = 데이터 워크북의 시트 이름, 그림 블록 = 표 블록의 행·열. 워크북 규칙: 시트 1개 = 표 1개, 제목 줄 → (단위: …) 줄 → 머리 행,
빈 줄·병합 없음, 행 이름 × 열 이름이 워크북 전체에서 겹치지 않게(원장 충돌 방지), 기간 머리는 '2025 상반기'·'2025 1분기'·'2024년'.
