# DCF — 투자 문서 작성·검수 AI 에이전트 (맛보기)

올린 자료(PDF·Word·엑셀)를 근거로 투자 리포트를 AI와 대화하며 쓰고, 문장·숫자마다 원본 파일의 위치까지 바로 확인하는 웹 앱입니다.

- **AI 작업**: 리서치(자료 찾기, 출처 달린 표·차트) / 문서 작성(양식대로 섹션 쓰기·고치기)
- **근거 확인**: 인용·숫자를 누르면 원본 파일의 그 쪽·문단·표 칸이 열립니다
- **문서 양식**: 샘플 보고서(PDF·Word)를 올리면 AI가 섹션 틀과 표·차트 양식을 뽑아 줍니다 → 다른 대상의 문서도 같은 모양으로
- **문서 검수**: 초안의 숫자를 자료와 대조합니다

## 준비물

- Python 3.11, Node.js 20+
- [NVIDIA build](https://build.nvidia.com) API 키 (채팅·임베딩 모델)

## 설치·실행

### 1. 백엔드 (FastAPI, 포트 8200)

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env  → NVIDIA_API_KEY 채우기
uvicorn main:app --port 8200
```

### 2. 프론트엔드 (Next.js, 포트 3200)

```bash
cd frontend
npm install
npm run dev
```

브라우저에서 http://localhost:3200 을 엽니다.

### 3. 데모 데이터 (선택)

백엔드를 띄운 채로, 백엔드 가상환경에서 (저장소 맨 위 폴더 기준):

```bash
python demo/make_materials.py
python demo/setup_demo.py
```

'A사 투자 검토' 워크스페이스와 자료·리포트가 만들어지고, 마지막에 열 주소가 나옵니다.

## 참고

- 데이터(올린 자료·DB·벡터)는 `backend/data` 에 저장되며 저장소에는 없습니다.
- `demo/public_samples` 의 외부 기관 보고서 PDF는 올리지 않았습니다. 받는 곳은 그 폴더의 README에 있습니다.
- 개발 기록은 `PLAN.md` 에 있습니다.
