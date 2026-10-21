#!/bin/sh
# Khởi động trong Space: kéo index (SQLite + vectors.npy + KG) từ dataset private rồi chạy API.
set -e
python -m deploy.hf_deploy pull-data
exec python -m uvicorn api.main:app --host 0.0.0.0 --port 7860 --workers "${WEB_CONCURRENCY:-1}"
