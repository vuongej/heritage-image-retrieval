"""Triển khai backend lên Hugging Face Spaces.

Một lần từ máy local (đọc HF_TOKEN trong .env):
  python -m deploy.hf_deploy upload-data    # data/local -> dataset private (SQLite, vectors.npy, KG)
  python -m deploy.hf_deploy set-secrets    # khóa API trong .env -> secrets của Space
CI (GitHub Actions) mỗi lần push main:
  python -m deploy.hf_deploy push-space     # đồng bộ code -> Space; Space tự build Dockerfile
  python -m deploy.hf_deploy wait           # chờ Space RUNNING và /v1/health trả 200
Trong container khi khởi động (deploy/hf/start.sh):
  python -m deploy.hf_deploy pull-data

Space mặc định `<user>/heritage-api`, dataset `<user>/heritage-data`; đổi bằng HF_SPACE / HF_DATASET.
Không bao giờ in giá trị secret.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from storage.runtime import ROOT, data_dir

DATA_FILES = ["catalog.sqlite3", "vectors.npy", "index.json", "kg/**"]
CODE_DIRS = ["api", "retrieval", "storage", "pipeline", "config"]
CODE_FILES = ["deploy/__init__.py", "deploy/hf_deploy.py", "deploy/hf/start.sh", "deploy/hf/requirements.txt"]
# Trang Benchmark của SPA đọc các report này qua /v1/reports (api/routers/reports.py).
REPORT_FILES = [
    "reports/v2/latency.json",
    "reports/v2/quality/eval.json",
    "reports/v2/index_counts.json",
    "reports/v2/rerank_ab.json",
    "reports/verify/report.json",
]
# Biến chỉ có nghĩa trên máy local hoặc với hạ tầng compose; không đẩy lên Space.
LOCAL_ONLY = {
    "VERCEL_TOKEN", "HF_TOKEN", "HF_READ_TOKEN", "PROD_API_KEY", "TEST_API_KEY", "API_KEY_ENFORCE",
    "VECTOR_BACKEND", "LOCAL_DATA_DIR", "LOCAL_LLM_BASE_URL", "EMBED_ONNX_PATH", "S3_ENDPOINT",
    "S3_BUCKET", "S3_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "POSTGRES_DSN",
    "REDIS_URL", "QDRANT_URL", "QDRANT_HOST_PORT", "VERIFY_DIR", "SOURCE_CSV",
    "HF_HUB_DISABLE_SYMLINKS_WARNING",
}
FAILED = {"BUILD_ERROR", "CONFIG_ERROR", "RUNTIME_ERROR", "NO_APP_FILE", "DELETING", "PAUSED", "STOPPED"}


def _api():
    from huggingface_hub import HfApi

    token = os.getenv("HF_TOKEN")
    if not token:
        sys.exit("Thiếu HF_TOKEN (thêm vào .env khi chạy local, hoặc secret HF_TOKEN trong GitHub)")
    return HfApi(token=token)


def _repo(api, env: str, name: str) -> str:
    return os.getenv(env) or f"{api.whoami()['name']}/{name}"


def space_url(space: str) -> str:
    return "https://" + space.replace("/", "-").replace("_", "-").replace(".", "-").lower() + ".hf.space"


def _env_file() -> dict[str, str]:
    path = ROOT / ".env"
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            value = value.strip().strip("\"'")
            if value:
                out[key.strip()] = value
    return out


def upload_data(_args) -> None:
    api = _api()
    dataset = _repo(api, "HF_DATASET", "heritage-data")
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


def pull_data(_args) -> None:
    dataset = os.getenv("HF_DATASET")
    token = os.getenv("HF_READ_TOKEN") or os.getenv("HF_TOKEN")
    if not dataset or not token:
        print("[data] Không có HF_DATASET/HF_TOKEN: dùng dữ liệu sẵn có trong LOCAL_DATA_DIR")
        return
    from huggingface_hub import snapshot_download

    t0 = time.time()
    snapshot_download(dataset, repo_type="dataset", local_dir=data_dir(), token=token)
    print(f"[data] {dataset} -> {data_dir()} trong {time.time() - t0:.0f} s")


def push_space(_args) -> None:
    api = _api()
    space = _repo(api, "HF_SPACE", "heritage-api")
    api.create_repo(space, repo_type="space", space_sdk="docker", exist_ok=True)
    before = api.space_info(space).sha
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
        for d in CODE_DIRS:
            shutil.copytree(ROOT / d, stage / d, ignore=ignore)
        for f in CODE_FILES + [r for r in REPORT_FILES if (ROOT / r).exists()]:
            (stage / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, stage / f)
        shutil.copy2(ROOT / "deploy/hf/Dockerfile", stage / "Dockerfile")
        shutil.copy2(ROOT / "deploy/hf/README.md", stage / "README.md")
        sha = os.getenv("GITHUB_SHA", "local")[:7]
        info = api.upload_folder(
            repo_id=space,
            repo_type="space",
            folder_path=stage,
            # Đồng bộ đúng nghĩa: file đã xóa ở GitHub cũng bị xóa trên Space.
            delete_patterns=[f"{d}/**" for d in CODE_DIRS] + ["deploy/**", "reports/**"],
            commit_message=f"Deploy {sha}",
        )
    changed = info.oid != before
    print(f"[space] {space} @ {info.oid[:7]} ({'đã đẩy commit mới' if changed else 'không có thay đổi'})")
    _github_output(space=space, url=space_url(space), changed=str(changed).lower())


def set_secrets(_args) -> None:
    api = _api()
    space = _repo(api, "HF_SPACE", "heritage-api")
    dataset = _repo(api, "HF_DATASET", "heritage-data")
    env = _env_file()
    key = env.get("PROD_API_KEY")
    if not key:
        key = "hir_" + secrets.token_urlsafe(32)
        with open(ROOT / ".env", "a", encoding="utf-8") as fh:
            fh.write(f"\n# Key giữa Vercel proxy và Space (sinh bởi deploy.hf_deploy)\nPROD_API_KEY={key}\n")
        print("[secrets] Đã sinh PROD_API_KEY mới và ghi vào .env")
    if not env.get("HF_READ_TOKEN"):
        print("[secrets] Cảnh báo: chưa có HF_READ_TOKEN, Space sẽ dùng HF_TOKEN (quyền write) để tải dataset")

    pushed = {k: v for k, v in env.items() if k not in LOCAL_ONLY}
    pushed["HF_TOKEN"] = env.get("HF_READ_TOKEN") or os.environ["HF_TOKEN"]
    pushed["TEST_API_KEY"] = key
    for k, v in sorted(pushed.items()):
        api.add_space_secret(space, k, v)
    for k, v in {"HF_DATASET": dataset, "API_KEY_ENFORCE": "true", "VECTOR_BACKEND": "numpy"}.items():
        api.add_space_variable(space, k, v)
    print(f"[secrets] {space}: {len(pushed)} secret ({', '.join(sorted(pushed))}) + 3 variable")


def wait(args) -> None:
    api = _api()
    space = _repo(api, "HF_SPACE", "heritage-api")
    head = api.space_info(space).sha
    deadline = time.time() + args.timeout
    last = None
    while time.time() < deadline:
        rt = api.get_space_runtime(space)
        stage = str(rt.stage)
        running_sha = (rt.raw or {}).get("sha")
        if stage != last:
            print(f"[wait] {stage}", flush=True)
            last = stage
        if stage in FAILED:
            sys.exit(f"Space lỗi ở stage {stage}: xem log tại https://huggingface.co/spaces/{space}?logs=container")
        if stage == "RUNNING" and running_sha in (None, head):
            break
        time.sleep(15)
    else:
        sys.exit(f"Quá {args.timeout} s mà Space chưa RUNNING")

    url = f"{space_url(space)}/v1/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                if r.status == 200:
                    print(f"[wait] {url} -> 200")
                    return
        except OSError:
            pass
        time.sleep(10)
    sys.exit(f"{url} chưa trả 200")


def url(_args) -> None:
    api = _api()
    print(space_url(_repo(api, "HF_SPACE", "heritage-api")))


def _github_output(**values: str) -> None:
    path = os.getenv("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.writelines(f"{k}={v}\n" for k, v in values.items())


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m deploy.hf_deploy")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [
        ("upload-data", upload_data),
        ("pull-data", pull_data),
        ("push-space", push_space),
        ("set-secrets", set_secrets),
        ("url", url),
    ]:
        sub.add_parser(name).set_defaults(fn=fn)
    w = sub.add_parser("wait")
    w.add_argument("--timeout", type=int, default=1800)
    w.set_defaults(fn=wait)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
