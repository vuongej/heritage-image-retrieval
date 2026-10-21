"""Index (SQLite + vectors.npy + KG) lưu trong một Hugging Face dataset private.

  python -m deploy.hf_data upload   # từ máy local, một lần mỗi khi index đổi (cần HF_TOKEN quyền write)
  python -m deploy.hf_data pull     # trong container khi khởi động (deploy/start.sh)

Dataset mặc định `<user>/heritage-data`, đổi bằng HF_DATASET. `pull` chỉ tải file đã đổi, nên
khởi động lại trên volume cũ gần như tức thì.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

from storage.runtime import data_dir

DATA_FILES = ["catalog.sqlite3", "vectors.npy", "index.json", "kg/**"]


def _token() -> str | None:
    return os.getenv("HF_TOKEN") or os.getenv("HF_READ_TOKEN")


def upload(_args) -> None:
    from huggingface_hub import HfApi

    token = _token()
    if not token:
        sys.exit("Thiếu HF_TOKEN trong .env")
    api = HfApi(token=token)
    dataset = os.getenv("HF_DATASET") or f"{api.whoami()['name']}/heritage-data"
    src = data_dir()
    db = src / "catalog.sqlite3"
    if not (db.exists() and (src / "vectors.npy").exists()):
        sys.exit(f"Không thấy catalog.sqlite3 / vectors.npy trong {src}")
    # Gộp WAL vào file chính để bản tải lên nhất quán (nên tắt API local trước).
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    api.create_repo(dataset, repo_type="dataset", private=True, exist_ok=True)
    info = api.upload_folder(
        repo_id=dataset,
        repo_type="dataset",
        folder_path=src,
        allow_patterns=DATA_FILES,
        commit_message="Cập nhật index",
    )
    print(f"[data] {dataset} @ {info.oid[:7]}")


def pull(_args) -> None:
    dataset, token = os.getenv("HF_DATASET"), _token()
    if not dataset or not token:
        print("[data] Không có HF_DATASET/HF_TOKEN: dùng dữ liệu sẵn có trong LOCAL_DATA_DIR")
        return
    from huggingface_hub import snapshot_download

    t0 = time.time()
    snapshot_download(dataset, repo_type="dataset", local_dir=data_dir(), token=token)
    print(f"[data] {dataset} -> {data_dir()} trong {time.time() - t0:.0f} s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m deploy.hf_data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("upload").set_defaults(fn=upload)
    sub.add_parser("pull").set_defaults(fn=pull)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
