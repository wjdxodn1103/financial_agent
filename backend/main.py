"""에비던스 데스크 백엔드 — FastAPI(워크스페이스·자료·근거 원장·리포트·검수·협업).

실행: .venv\\Scripts\\python.exe main.py   (backend 폴더에서 — 127.0.0.1:8200)
     .venv\\Scripts\\python.exe -m uvicorn main:app --port 8200   (uvicorn 옵션을 직접 줄 때)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.api.import_routes import router as import_router
from app.api.research_routes import router as research_router
from app.api.routes import router
from app.auth import seed_users
from app.db import init_db
from app import scheduler
from app.docs import queue as docs_queue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    seed_users()
    docs_queue.start_worker()  # 인제스트 큐 재개 + 벡터 없는 문서 임베딩(백그라운드)
    scheduler.start()  # 예약 작업(기록 비서 퇴근 시각 배치)
    yield
    scheduler.stop()
    docs_queue.stop_worker()


app = FastAPI(title="Evidence Desk", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"], expose_headers=["Content-Disposition"])
app.include_router(router)
app.include_router(research_router)
app.include_router(import_router)


@app.get("/health")
def health():
    return {"ok": True, "model": config.CHAT_MODEL, "embed": config.EMBED_MODEL or None, "keySet": bool(config.NVIDIA_API_KEY)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8200)
