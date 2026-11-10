"""AssociateLM 백엔드 — FastAPI(워크스페이스·자료·근거 원장·리포트·검수·협업).

실행: .venv\\Scripts\\python.exe main.py   (backend 폴더에서 — 127.0.0.1:8200)
     .venv\\Scripts\\python.exe -m uvicorn main:app --port 8200   (uvicorn 옵션을 직접 줄 때)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.api.common_routes import router as common_router
from app.api.import_routes import router as import_router
from app.api.pipeline_routes import router as pipeline_router
from app.api.dashboard_routes import router as dashboard_router
from app.api.routine_routes import router as routine_router
from app.api.search_routes import router as search_router
from app.api.assumption_routes import router as assumption_router
from app.api.assistant_routes import router as assistant_router
from app.api.quality_routes import router as quality_router
from app.api.calendar_routes import router as calendar_router
from app.api.criteria_routes import router as criteria_router
from app.api.research_routes import router as research_router
from app.api.routes import router
from app.auth import seed_users
from app.db import init_db
from app.usage import UsageMiddleware
from app import scheduler
from app.docs import queue as docs_queue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_users()
    from app.seed_formats import seed as seed_formats

    seed_formats()  # 사내 공통 '예시' 양식(재심의 안건·IC 심의 요약·해외주식 동향 브리핑 …)
    docs_queue.start_worker()  # 인제스트 큐 재개 + 벡터 없는 문서 임베딩(백그라운드)
    scheduler.start()  # 예약 작업(기록 비서 퇴근 시각 배치)
    yield
    scheduler.stop()
    docs_queue.stop_worker()


app = FastAPI(title="AssociateLM", lifespan=lifespan)
app.add_middleware(UsageMiddleware)  # 사용 귀속(사람·워크스페이스·기능) — CORS 안쪽
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition"])
app.include_router(router)
app.include_router(research_router)
app.include_router(import_router)
app.include_router(common_router)
app.include_router(pipeline_router)
app.include_router(dashboard_router)
app.include_router(routine_router)
app.include_router(search_router)
app.include_router(assumption_router)
app.include_router(assistant_router)
app.include_router(quality_router)
app.include_router(calendar_router)
app.include_router(criteria_router)


@app.get("/health")
def health():
    return {"ok": True, "model": config.CHAT_MODEL, "embed": config.EMBED_MODEL or None, "keySet": bool(config.NVIDIA_API_KEY)}


if __name__ == "__main__":
    import os

    import uvicorn

    # 기본은 이 PC 에서만 열린다. 서버에 올릴 때는 환경 변수로 바꾼다(예: HOST=0.0.0.0 PORT=8200).
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8200")))
