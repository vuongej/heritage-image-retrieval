"""Entrypoint: uvicorn api.main:app

Chạy được KHÔNG cần API key của bên thứ ba.
X-API-Key là key nội bộ (cho auto test), không phải key Gemini.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routers import (
    backfill,
    embed,
    entities,
    graph,
    health,
    ingest,
    reports,
    rerank,
    search,
    verify,
)
from storage.runtime import load_env

load_env()


def _preload() -> None:
    """Nạp sẵn catalog tên + reranker local ở luồng nền: truy vấn đầu không phải chờ ~20 s."""
    try:
        from retrieval import rerank
        from retrieval.catalog import for_index
        from retrieval.local_index import manifest

        for_index(manifest().get("csv_sha256"))
        if rerank.backend() == "local_ce":
            rerank._load_local(rerank.local_model())
    except Exception:  # nạp sẵn chỉ là tối ưu; lỗi thật sẽ lộ ở request đầu tiên
        pass


@asynccontextmanager
async def lifespan(_app):
    if os.getenv("PRELOAD_MODELS", "true").lower() == "true":
        threading.Thread(target=_preload, name="preload", daemon=True).start()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Heritage Image Retrieval API",
    version="0.1.0",
    description="Phần A (lọc ảnh) + Phần B (truy xuất ảnh). Chỉ embed/rerank, không agent.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_key_and_timing(request: Request, call_next):
    t0 = time.perf_counter()

    enforce = os.getenv("API_KEY_ENFORCE", "true").lower() == "true"
    path = request.url.path
    if enforce and request.method != "OPTIONS" and path.startswith("/v1") and path != "/v1/health":
        key = request.headers.get("X-API-Key")
        if not key:
            return JSONResponse({"detail": "X-API-Key thiếu"}, status_code=401)
        from api.security import verify_key

        if not verify_key(key):
            return JSONResponse({"detail": "X-API-Key không hợp lệ"}, status_code=403)

    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    response.headers["X-Response-Time"] = str(elapsed_ms)
    return response


@app.exception_handler(RuntimeError)
async def runtime_error(request: Request, exc: RuntimeError):
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.exception_handler(ValueError)
async def invalid_value(request: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=422)


app.include_router(health.router, prefix="/v1", tags=["health"])
app.include_router(search.router, prefix="/v1", tags=["search"])
app.include_router(embed.router, prefix="/v1", tags=["embed"])
app.include_router(rerank.router, prefix="/v1", tags=["rerank"])
app.include_router(entities.router, prefix="/v1", tags=["entities"])
app.include_router(graph.router, prefix="/v1", tags=["graph"])
app.include_router(ingest.router, prefix="/v1", tags=["ingest"])
app.include_router(backfill.router, prefix="/v1", tags=["backfill"])
app.include_router(verify.router, prefix="/v1", tags=["verify"])
app.include_router(reports.router, prefix="/v1", tags=["reports"])
app.include_router(verify.thumbs)

# Giao diện là web/spa (Vite + React), chạy riêng và gọi API qua proxy /api (gắn X-API-Key phía
# server dev/preview). API chỉ phục vụ /v1/*; trang gốc chỉ trỏ tới UI và tài liệu API.
WEB_UI_URL = os.getenv("WEB_UI_URL", "http://localhost:5173")


@app.get("/", include_in_schema=False)
def root() -> JSONResponse:
    return JSONResponse({"service": app.title, "ui": WEB_UI_URL, "api_docs": "/docs"})
