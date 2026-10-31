"""설정 — backend/.env 를 읽는다(.env.example 참고). 값은 프로세스 시작 때 한 번 정해진다."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


# ── NVIDIA build (OpenAI 호환) ──────────────────────────────────────────
NVIDIA_API_KEY = _env("NVIDIA_API_KEY")
NVIDIA_BASE_URL = _env("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
CHAT_MODEL = _env("CHAT_MODEL", "nvidia/nemotron-3-super-120b-a12b")
WRITER_MODEL = _env("WRITER_MODEL", CHAT_MODEL)
# 임베딩 — 비우면 BM25 만으로 검색한다(벡터 없이도 동작)
EMBED_MODEL = _env("EMBED_MODEL", "nvidia/nemotron-3-embed-1b")

# ── 예비 경로 OpenRouter(선택) — NVIDIA 호출이 실패하면 같은 모델을 여기로. 키가 없으면 예비 경로 없음, 임베딩은 NVIDIA 그대로 ──
OPENROUTER_API_KEY = _env("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
FALLBACK_CHAT_MODEL = _env("FALLBACK_CHAT_MODEL", "nvidia/nemotron-3.5-super-vl")
FALLBACK_WRITER_MODEL = _env("FALLBACK_WRITER_MODEL", FALLBACK_CHAT_MODEL)
# 호스트 고르기 — 순서(쉼표, 예: crusoe,nebius), 양자화 제한(기본 bf16,fp8 — 'any' 면 제한 없음), 데이터 수집 거부(deny)
OPENROUTER_PROVIDERS = [s.strip() for s in _env("OPENROUTER_PROVIDERS").split(",") if s.strip()]
OPENROUTER_QUANTIZATIONS = [] if _env("OPENROUTER_QUANTIZATIONS", "bf16,fp8").lower() == "any" else [s.strip() for s in _env("OPENROUTER_QUANTIZATIONS", "bf16,fp8").split(",") if s.strip()]
OPENROUTER_DATA_COLLECTION = _env("OPENROUTER_DATA_COLLECTION").lower()

# ── 저장소 ────────────────────────────────────────────────────────────
DATA_DIR = Path(_env("DATA_DIR", str(BACKEND_DIR / "data"))).resolve()
DOCUMENTS_DIR = DATA_DIR / "documents"  # 문서 한 편 = 폴더 하나(sha1 16자), 세션과 무관하게 공유
INBOX_DIR = DATA_DIR / "inbox"  # 업로드 원본(인제스트 대기)
LOG_DIR = DATA_DIR / "logs"
CONNECTOR_DIR = DATA_DIR / "connectors"  # 데이터 연결 캐시(DART 회사 코드 목록 등)
TEMPLATE_DIR = DATA_DIR / "templates"  # 등록한 DOCX 양식 원본
DB_PATH = DATA_DIR / "workspace.db"  # 워크스페이스 구조(2026-10-19~) — 예전 단일 리포트 틀의 app.db 는 그대로 둔다
# 벡터 저장소(Qdrant) — QDRANT_URL 이 비면 로컬 모드(이 폴더, 백엔드 프로세스 안), 있으면 Qdrant 서버
QDRANT_PATH = DATA_DIR / "qdrant"
QDRANT_URL = _env("QDRANT_URL")
QDRANT_API_KEY = _env("QDRANT_API_KEY")

# ── 데이터 연결 ───────────────────────────────────────────────────────
# 에이전트가 대화 중에 외부 API(DART)에서 직접 가져오는 도구 — 기본 끔. 데이터는 사내 공용 데이터(미리 넣어 둔 DB)로 들어온다
LIVE_CONNECTOR_TOOLS = _env("LIVE_CONNECTOR_TOOLS", "0") == "1"
DART_API_KEY = _env("DART_API_KEY")  # https://opendart.fss.or.kr 무료 인증키 — 비우면 DART 연결은 안내만
SEC_USER_AGENT = _env("SEC_USER_AGENT")  # SEC EDGAR 는 키 대신 연락처가 든 User-Agent 를 요구(예: "회사명 담당자 이메일") — 비우면 안내만
ECOS_API_KEY = _env("ECOS_API_KEY")  # https://ecos.bok.or.kr 무료 인증키 — 비우면 ECOS 연결은 안내만
FRED_API_KEY = _env("FRED_API_KEY")  # https://fred.stlouisfed.org 무료 키 — 비우면 시장 시계열은 미 재무부·ECB·뉴욕 연은·데모(가상) 사슬로
# 경제 일정·발표 감지(2026-10-29) — 비우면 그 소스는 건너뛰고 FRED 로(늦을 수 있음)
BLS_API_KEY = _env("BLS_API_KEY")  # https://data.bls.gov/registrationEngine/ 무료 등록키 — CPI·고용·PPI 발표 직후 감지(하루 500회, 없으면 25회)
BEA_API_KEY = _env("BEA_API_KEY")  # https://apps.bea.gov/API/signup/ 무료 UserID — GDP·PCE 발표 직후 감지
KOSIS_API_KEY = _env("KOSIS_API_KEY")  # https://kosis.kr/openapi 무료 인증키 — 통계청 세부 지표(대부분은 ECOS 로 충분)
DATA_GO_KR_API_KEY = _env("DATA_GO_KR_API_KEY")  # https://www.data.go.kr '금융위원회_주식시세정보' 무료 키 — 한국 주식 일봉 공식 대안(다음 날 13시 이후)
ALERT_WEBHOOK_URL = _env("ALERT_WEBHOOK_URL")  # 일정 알림을 밖으로 보낼 웹훅(Slack·Teams 호환 {"text": …}) — 비우면 앱 알림함·워크스페이스 메시지만

# ── 협업 ──────────────────────────────────────────────────────────────
TIMEZONE = _env("TIMEZONE", "Asia/Seoul")
DEFAULT_OFF_HOUR = _env("DEFAULT_OFF_HOUR", "19:00")  # 기록 비서 배치 기본 시각(워크스페이스 설정이 우선)

# ── 관리자 ────────────────────────────────────────────────────────────
# 사내 공용(전사 대시보드 고치기·시장 갱신·사내 수집 소스·품질 화면)을 다루는 계정 — 데모는 계정 id 목록(SSO 로 바꿀 때 auth 와 같이)
ADMIN_USER_IDS = [s.strip() for s in _env("ADMIN_USER_IDS", "u_kim").split(",") if s.strip()]

# ── 서버 ──────────────────────────────────────────────────────────────
CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "http://localhost:3200,http://127.0.0.1:3200").split(",") if o.strip()]
MAX_UPLOAD_MB = int(_env("MAX_UPLOAD_MB", "50"))

for d in (DATA_DIR, DOCUMENTS_DIR, INBOX_DIR, LOG_DIR, CONNECTOR_DIR, TEMPLATE_DIR):
    d.mkdir(parents=True, exist_ok=True)
