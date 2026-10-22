"""Hàng đợi job xử lý: một worker (GPU / SigLIP2 dùng chung), trạng thái lưu ra đĩa.

Mỗi job ở PROCESS_DIR/jobs/<id>/: upload.csv, status.json, results.jsonl, results.csv.
Khởi động lại service: job đang chạy dở được đánh dấu `interrupted`, job đã xong vẫn xem được.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import traceback
import uuid
from pathlib import Path

from processing import pipeline

STATUS_FILE = "status.json"
TERMINAL = {"done", "failed", "cancelled", "interrupted"}


def jobs_dir() -> Path:
    path = pipeline.PROCESS_DIR / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


class Job:
    def __init__(self, job_id: str, filename: str, options: pipeline.Options, info: dict):
        self.id = job_id
        self.filename = filename
        self.options = options
        self.info = info
        self.status = "queued"
        self.created_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.stages = {k: {"key": k, "label": label, "status": "pending", "done": 0, "total": 0,
                           "started_at": None, "seconds": None} for k, label in pipeline.STAGES}
        self.summary: dict | None = None
        self.error: str | None = None
        self.cancel_requested = False
        self._lock = threading.Lock()
        self._saved = 0.0

    @property
    def dir(self) -> Path:
        return jobs_dir() / self.id

    def to_dict(self) -> dict:
        with self._lock:
            now = time.time()
            stages = []
            for s in self.stages.values():
                s = dict(s)
                if s["status"] == "running" and s["started_at"]:
                    s["seconds"] = round(now - s["started_at"], 1)
                stages.append(s)
            return {
                "id": self.id,
                "filename": self.filename,
                "status": self.status,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "elapsed_seconds": round((self.finished_at or now) - self.started_at, 1)
                if self.started_at else None,
                "options": self.options.to_dict(),
                "input": self.info,
                "stages": stages,
                "summary": self.summary,
                "error": self.error,
            }

    def save(self, force: bool = False) -> None:
        if not force and time.time() - self._saved < 2:
            return
        self._saved = time.time()
        tmp = self.dir / (STATUS_FILE + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False), "utf-8")
        tmp.replace(self.dir / STATUS_FILE)

    def progress(self, stage: str, done: int, total: int) -> None:
        with self._lock:
            now = time.time()
            for s in self.stages.values():  # stage trước coi như xong khi stage sau bắt đầu
                if s["status"] == "running" and s["key"] != stage:
                    s["status"] = "done"
                    s["seconds"] = round(now - s["started_at"], 3)
            s = self.stages[stage]
            if s["status"] == "pending":
                s["status"], s["started_at"] = "running", now
            s["done"], s["total"] = done, total
            if total == 0 and stage in ("embed", "classify", "route", "vlm"):
                s["status"], s["seconds"] = "skipped", 0.0
        self.save()

    def check(self) -> None:
        if self.cancel_requested:
            raise pipeline.Cancelled()


class JobManager:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.queue: queue.Queue[str] = queue.Queue()
        self._load()
        threading.Thread(target=self._worker, name="process-worker", daemon=True).start()

    def _load(self) -> None:
        for path in sorted(jobs_dir().glob(f"*/{STATUS_FILE}")):
            try:
                d = json.loads(path.read_text("utf-8"))
            except (OSError, ValueError):
                continue
            job = Job(d["id"], d["filename"], pipeline.Options(**d["options"]), d["input"])
            job.status = d["status"] if d["status"] in TERMINAL else "interrupted"
            job.created_at, job.started_at = d["created_at"], d["started_at"]
            job.finished_at = d["finished_at"] or (time.time() if job.status == "interrupted" else None)
            job.stages = {s["key"]: s for s in d["stages"]}
            job.summary, job.error = d["summary"], d["error"]
            if d["status"] not in TERMINAL:
                job.error = "Service khởi động lại khi job đang chạy"
                job.save(force=True)
            self.jobs[job.id] = job

    def submit(self, data: bytes, filename: str, options: pipeline.Options) -> Job:
        rows, info = pipeline.read_csv(data)  # lỗi định dạng báo ngay, trước khi xếp hàng
        job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        job = Job(job_id, filename, options, info)
        job.dir.mkdir(parents=True)
        (job.dir / "upload.csv").write_bytes(data)
        job.save(force=True)
        self.jobs[job_id] = job
        self.queue.put(job_id)
        return job

    def cancel(self, job_id: str) -> Job:
        job = self.jobs[job_id]
        if job.status == "queued":
            job.status, job.finished_at = "cancelled", time.time()
            job.save(force=True)
        elif job.status == "running":
            job.cancel_requested = True
        return job

    def queued_ahead(self, job_id: str) -> int:
        return sum(1 for j in self.jobs.values() if j.status == "queued" and j.created_at <
                   self.jobs[job_id].created_at)

    def _worker(self) -> None:
        while True:
            job = self.jobs.get(self.queue.get())
            if job is None or job.status != "queued":
                continue
            job.status, job.started_at = "running", time.time()
            job.save(force=True)
            try:
                rows, _ = pipeline.read_csv((job.dir / "upload.csv").read_bytes())
                job.summary = pipeline.run(rows, job.options, job.dir, job.progress, job.check)
                job.status = "done"
            except pipeline.Cancelled:
                job.status = "cancelled"
            except Exception as exc:  # job lỗi không làm chết worker
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                (job.dir / "error.log").write_text(traceback.format_exc(), "utf-8")
            finally:
                job.finished_at = time.time()
                for s in job.stages.values():
                    if s["status"] == "running":
                        s["status"] = "done" if job.status == "done" else job.status
                        s["seconds"] = round(job.finished_at - (s["started_at"] or job.finished_at), 3)
                job.save(force=True)
