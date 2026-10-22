#!/bin/sh
# Khởi động container api: chuẩn bị index (SQLite + vectors.npy + KG) rồi chạy API.
#  1. HF_DATASET + HF_TOKEN: kéo index dựng sẵn từ dataset private (deploy/hf_data.py).
#  2. /home/user/seed (docker compose mount ./data/local read-only): chép file mới hơn vào
#     LOCAL_DATA_DIR. SQLite (WAL) phải nằm trên file system của container: mở thẳng trên
#     bind mount Windows/macOS lỗi "unable to open database file" khi có request đồng thời.
# 1 worker: limiter của endpoint embedding (EMBED_API_RPM) tính theo process; nhiều worker sẽ vượt
# quota 100 request/phút dùng chung.
set -e
python -m deploy.hf_data pull
SEED=/home/user/seed
if [ -d "$SEED" ] && [ -f "$SEED/catalog.sqlite3" ]; then
  mkdir -p "$LOCAL_DATA_DIR"
  for f in catalog.sqlite3 vectors.npy index.json; do
    if [ -f "$SEED/$f" ] && { [ ! -f "$LOCAL_DATA_DIR/$f" ] || [ "$SEED/$f" -nt "$LOCAL_DATA_DIR/$f" ]; }; then
      echo "[data] chép $f từ ./data/local"
      cp -p "$SEED/$f" "$LOCAL_DATA_DIR/$f"
      [ "$f" = catalog.sqlite3 ] && rm -f "$LOCAL_DATA_DIR/catalog.sqlite3-wal" "$LOCAL_DATA_DIR/catalog.sqlite3-shm"
    fi
  done
  [ -d "$SEED/kg" ] && cp -rpu "$SEED/kg" "$LOCAL_DATA_DIR/" 2>/dev/null || true
fi
exec python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-1}"
