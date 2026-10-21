#!/bin/sh
# Khởi động container: kéo index (SQLite + vectors.npy + KG) từ dataset private rồi chạy API.
# 1 worker: limiter của endpoint embedding (EMBED_API_RPM) tính theo process; nhiều worker sẽ vượt
# quota 100 request/phút dùng chung.
set -e
python -m deploy.hf_data pull
exec python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-1}"
