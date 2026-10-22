"""Production smoke: health -> sample CSV -> upload -> poll -> items -> download CSV.

Chạy bằng stdlib: APP_URL=https://... python -m deploy.smoke_processing.
Ba ảnh đầu CSV mẫu phải có ít nhất một ảnh đi qua classifier thật. Không gọi VLM.
"""

from __future__ import annotations

import csv
import io
import json
import os
import time
import urllib.request
import uuid


def smoke(base: str, timeout: int = 600) -> None:
    base = base.rstrip("/") + "/api/v1/process"

    def request(path: str, data: bytes | None = None, content_type: str | None = None):
        headers = {"Content-Type": content_type} if content_type else {}
        req = urllib.request.Request(base + path, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()

    health = json.loads(request("/health"))
    if health.get("status") != "ok":
        raise RuntimeError("Processing health chưa sẵn sàng")
    json.loads(request("/jobs"))  # kiểm tra API key/HF auth qua proxy
    rows = list(csv.DictReader(io.StringIO(request("/sample.csv").decode("utf-8-sig"))))[:3]
    if len(rows) != 3:
        raise RuntimeError("CSV mẫu phải có ít nhất 3 ảnh")
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    boundary = "smoke-" + uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="use_vlm"\r\n\r\nfalse\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="ci-smoke.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n{buf.getvalue()}\r\n--{boundary}--\r\n"
    ).encode()
    created = json.loads(request("/jobs", body, f"multipart/form-data; boundary={boundary}"))
    job_id = created["id"]
    print(f"[processing smoke] created {job_id}", flush=True)
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        job = json.loads(request(f"/jobs/{job_id}"))
        active = next((s["key"] for s in job["stages"] if s["status"] == "running"), "")
        state = (job["status"], active)
        if state != last:
            print(f"[processing smoke] {state}", flush=True)
            last = state
        if job["status"] == "done":
            break
        if job["status"] not in ("queued", "running"):
            raise RuntimeError(f"Processing job {job_id}: {job['status']} / {job.get('error')}")
        time.sleep(5)
    else:
        request(f"/jobs/{job_id}/cancel", b"")
        raise TimeoutError(f"Processing job {job_id} quá {timeout}s")

    items = json.loads(request(f"/jobs/{job_id}/items"))
    if items["total"] != 3 or not any(item["stage"] == "classifier" for item in items["items"]):
        raise RuntimeError(f"Smoke phải xử lý đủ 3 dòng và chạy classifier: {job['summary']['by_reason']}")
    result = list(csv.DictReader(io.StringIO(request(f"/jobs/{job_id}/result.csv").decode("utf-8-sig"))))
    if len(result) != 3 or any(row.get("decision") not in ("yes", "no") for row in result):
        raise RuntimeError("CSV kết quả thiếu dòng hoặc quyết định")
    print(f"[processing smoke] PASS: 3 rows, classifier, CSV download; job {job_id}", flush=True)


if __name__ == "__main__":
    smoke(os.environ["APP_URL"])
