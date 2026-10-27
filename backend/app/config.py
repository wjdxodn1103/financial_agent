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

# ── 협업 ──────────────────────────────────────────────────────────────
TIMEZONE = _env("TIMEZONE", "Asia/Seoul")
DEFAULT_OFF_HOUR = _env("DEFAULT_OFF_HOUR", "19:00")  # 기록 비서 배치 기본 시각(워크스페이스 설정이 우선)

# ── 서버 ──────────────────────────────────────────────────────────────
CORS_ORIGINS = [o.strip() for o in _env("CORS_ORIGINS", "http://localhost:3200,http://127.0.0.1:3200").split(",") if o.strip()]
MAX_UPLOAD_MB = int(_env("MAX_UPLOAD_MB", "50"))

for d in (DATA_DIR, DOCUMENTS_DIR, INBOX_DIR, LOG_DIR, CONNECTOR_DIR, TEMPLATE_DIR):
    d.mkdir(parents=True, exist_ok=True)
