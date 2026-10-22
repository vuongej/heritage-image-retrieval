"""Processing service (Pipeline A): uvicorn processing.main:app --port 8100

POST /v1/process/jobs              multipart `file` (.csv) + use_vlm / vlm_budget / threshold
GET  /v1/process/jobs              danh sách job
GET  /v1/process/jobs/{id}         trạng thái, tiến độ từng tầng, tóm tắt
GET  /v1/process/jobs/{id}/items   kết quả từng ảnh (lọc decision / stage / reason / q, phân trang)
GET  /v1/process/jobs/{id}/result.csv  CSV gốc + cột quyết định
POST /v1/process/jobs/{id}/cancel
GET  /v1/process/thumbs/{key}.jpg  thumbnail đã tải
GET  /v1/process/sample.csv        CSV mẫu có nhãn người
GET  /v1/process/health
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from processing import pipeline
from processing.jobs import JobManager
from processing.model import load as load_model

MAX_UPLOAD_BYTES = int(float(os.getenv("PROCESS_MAX_UPLOAD_MB", "50")) * 1024 * 1024)
SAMPLE = Path(__file__).resolve().parent / "samples" / "sample.csv"
KEY = re.compile(r"^[0-9a-f]{64}$")

app = FastAPI(title="Heritage Image Processing (Pipeline A)", version="1.0.0")
manager: JobManager | None = None


def jobs() -> JobManager:
    global manager
    if manager is None:
        manager = JobManager()
    return manager


@app.on_event("startup")
def _startup() -> None:
    jobs()
    load_model()  # artifact hỏng thì báo ngay khi khởi động, không đợi job đầu
    if os.getenv("PRELOAD_MODELS", "true").lower() == "true":
        # Tải + nạp SigLIP2 ở nền: job đầu tiên không phải chờ (~375 MB lần đầu, sau đó từ cache).
        from pipeline.verify import encoder

        threading.Thread(target=encoder.loaded, name="preload-siglip2", daemon=True).start()


@app.middleware("http")
async def api_key(request: Request, call_next):
    t0 = time.perf_counter()
    path = request.url.path
    public = path in ("/v1/process/health",) or path.startswith("/v1/process/thumbs/")
    if os.getenv("API_KEY_ENFORCE", "true").lower() == "true" and not public and request.method != "OPTIONS":
        from api.security import verify_key

        key = request.headers.get("X-API-Key")
        if not key:
            return JSONResponse({"detail": "X-API-Key thiếu"}, status_code=401)
        if not verify_key(key):
            return JSONResponse({"detail": "X-API-Key không hợp lệ"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Response-Time"] = str(int((time.perf_counter() - t0) * 1000))
    return response


def _job(job_id: str):
    job = jobs().jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Không có job này")
    return job


@app.get("/v1/process/health")
def health() -> dict:
    from pipeline.verify import encoder

    m = jobs()
    model = load_model()
    try:
        import torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        device = "unavailable"
    return {
        "status": "ok",
        "model": model.summary(),
        "encoder": encoder.ENCODER,
        "device": device,
        "vlm_available": pipeline.vlm_available(),
        "queue": sum(j.status == "queued" for j in m.jobs.values()),
        "running": next((j.id for j in m.jobs.values() if j.status == "running"), None),
        "max_rows": pipeline.MAX_ROWS,
        "max_upload_mb": round(MAX_UPLOAD_BYTES / 1024 / 1024),
        "stages": [{"key": k, "label": label} for k, label in pipeline.STAGES],
    }


@app.post("/v1/process/jobs", status_code=201)
async def create_job(
    file: Annotated[UploadFile, File()],
    use_vlm: Annotated[bool, Form()] = True,
    vlm_budget: Annotated[float | None, Form()] = None,
    threshold: Annotated[float | None, Form()] = None,
) -> dict:
    name = file.filename or "upload.csv"
    if not name.lower().endswith(".csv"):
        raise HTTPException(422, "Chỉ nhận file .csv")
    if vlm_budget is not None and not 0 <= vlm_budget <= 0.5:
        raise HTTPException(422, "vlm_budget phải trong [0, 0.5]")
    if threshold is not None and not 0 < threshold < 1:
        raise HTTPException(422, "threshold phải trong (0, 1)")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File quá {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    try:
        job = jobs().submit(data, name, pipeline.Options(use_vlm, vlm_budget, threshold))
    except pipeline.InvalidCsv as exc:
        raise HTTPException(422, str(exc)) from None
    return {**job.to_dict(), "queued_ahead": jobs().queued_ahead(job.id)}


@app.get("/v1/process/jobs")
def list_jobs(limit: int = Query(20, ge=1, le=100)) -> dict:
    items = sorted(jobs().jobs.values(), key=lambda j: j.created_at, reverse=True)[:limit]
    out = []
    for j in items:
        d = j.to_dict()
        s = d["summary"] or {}
        out.append({k: d[k] for k in ("id", "filename", "status", "created_at", "elapsed_seconds")}
                   | {"rows": d["input"]["rows"], "approved": s.get("approved"),
                      "rejected": s.get("rejected")})
    return {"items": out}


@app.get("/v1/process/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = _job(job_id)
    return {**job.to_dict(), "queued_ahead": jobs().queued_ahead(job_id)}


@app.post("/v1/process/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    _job(job_id)
    return jobs().cancel(job_id).to_dict()


@lru_cache(maxsize=8)
def _results(path: str, mtime: float) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text("utf-8").splitlines() if x]


@app.get("/v1/process/jobs/{job_id}/items")
def items(
    job_id: str,
    decision: str | None = Query(None, pattern="^(yes|no)$"),
    stage: str | None = Query(None, pattern="^(rule|classifier|vlm)$"),
    reason: str | None = Query(None, max_length=40),
    q: str | None = Query(None, max_length=200),
    mismatch: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(60, ge=1, le=200),
) -> dict:
    job = _job(job_id)
    path = job.dir / "results.jsonl"
    if not path.exists():
        raise HTTPException(409, "Job chưa có kết quả")
    rows = _results(str(path), path.stat().st_mtime)
    if decision:
        rows = [r for r in rows if r["decision"] == decision]
    if stage:
        rows = [r for r in rows if r["stage"] == stage]
    if reason:
        rows = [r for r in rows if r["reason"] == reason]
    if q:
        needle = q.lower()
        rows = [r for r in rows if needle in r["entity_name"].lower() or needle in r["image_url"].lower()]
    if mismatch:  # chỉ ảnh mà quyết định khác nhãn người trong CSV
        rows = [r for r in rows if r["label"] and r["label"] != r["decision"]]
    return {"total": len(rows), "offset": offset, "items": rows[offset : offset + limit]}


@app.get("/v1/process/jobs/{job_id}/result.csv")
def result_csv(job_id: str):
    job = _job(job_id)
    path = job.dir / "results.csv"
    if not path.exists():
        raise HTTPException(409, "Job chưa có kết quả")
    stem = Path(job.filename).stem
    return FileResponse(path, media_type="text/csv", filename=f"{stem}_processed.csv")


@app.get("/v1/process/thumbs/{name}")
def thumb(name: str):
    from pipeline.verify import fetch

    key = name.removesuffix(".jpg")
    if not KEY.match(key):
        raise HTTPException(404, "Not found")
    path = fetch.thumb_path(key)
    if not path.exists():
        raise HTTPException(404, "Chưa có thumbnail")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/v1/process/sample.csv")
def sample():
    if not SAMPLE.exists():
        raise HTTPException(404, "Không có CSV mẫu")
    return FileResponse(SAMPLE, media_type="text/csv", filename="sample_pipeline_a.csv")
