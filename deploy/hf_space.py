"""Backend production trên Hugging Face Space (Docker, private, cần tài khoản PRO).

  python -m deploy.hf_space secrets   # local, một lần và mỗi khi đổi key: .env -> secrets của Space
  python -m deploy.hf_space push      # CI mỗi lần push main: đồng bộ code -> Space (Space tự build)
  python -m deploy.hf_space wait      # CI: chờ Space chạy đúng commit vừa đẩy và /v1/health trả 200
  python -m deploy.hf_space url       # in URL của Space (dùng làm BACKEND_URL trên Vercel)

Space dùng chính deploy/backend.Dockerfile; index tải từ dataset private khi container khởi động
(deploy/hf_data.py). Space mặc định `<user>/heritage-api`, đổi bằng HF_SPACE. Không in giá trị secret.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from deploy.env import LOCAL_ONLY, read_env
from storage.runtime import ROOT

# Khớp các lệnh COPY trong deploy/backend.Dockerfile. Chỉ lấy file git track (reports/ local có
# hàng chục MB kết quả thử nghiệm, git chỉ giữ 5 file mà trang Benchmark đọc).
STAGE = [
    "api", "retrieval", "storage", "pipeline", "config", "reports",
    "deploy/__init__.py", "deploy/hf_data.py", "deploy/start.sh", "deploy/requirements.txt",
]
README = """---
title: Heritage Image Retrieval API
emoji: 🏛️
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 8000
startup_duration_timeout: 1h
pinned: false
---

Backend FastAPI của https://github.com/VSF-AR-ES-V-Lookup/PhamVanVuong_search_image.
Được đồng bộ tự động bởi GitHub Actions; không sửa trực tiếp ở đây.
"""
FAILED = {"BUILD_ERROR", "CONFIG_ERROR", "RUNTIME_ERROR", "NO_APP_FILE", "DELETING", "PAUSED", "STOPPED"}


def _token() -> str:
    token = os.getenv("HF_TOKEN") or os.getenv("HF_READ_TOKEN")
    if not token:
        sys.exit("Thiếu HF_TOKEN (thêm vào .env khi chạy local, hoặc secret HF_TOKEN trong GitHub)")
    return token


def _api():
    from huggingface_hub import HfApi

    return HfApi(token=_token())


def _space(api) -> str:
    return os.getenv("HF_SPACE") or f"{api.whoami()['name']}/heritage-api"


def space_url(space: str) -> str:
    return "https://" + space.replace("/", "-").replace("_", "-").replace(".", "-").lower() + ".hf.space"


def push(_args) -> None:
    api = _api()
    space = _space(api)
    api.create_repo(space, repo_type="space", space_sdk="docker", private=True, exist_ok=True)
    before = api.space_info(space).sha
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "--", *STAGE], cwd=ROOT, capture_output=True, check=True
        ).stdout.decode().split("\0")
        for rel in filter(None, tracked):
            (stage / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, stage / rel)
        shutil.copy2(ROOT / "deploy/backend.Dockerfile", stage / "Dockerfile")
        (stage / "README.md").write_text(README, encoding="utf-8")
        info = api.upload_folder(
            repo_id=space,
            repo_type="space",
            folder_path=stage,
            # Đồng bộ đúng nghĩa: file đã xóa ở GitHub cũng bị xóa trên Space (giữ .gitattributes của HF).
            delete_patterns=[f"{d}/**" for d in STAGE if "/" not in d] + ["deploy/**"],
            commit_message=f"Deploy {os.getenv('GITHUB_SHA', 'local')[:7]}",
        )
    changed = info.oid != before
    print(f"[space] {space} @ {info.oid[:7]} ({'commit mới, Space sẽ build lại' if changed else 'không đổi'})")


def set_secrets(_args) -> None:
    api = _api()
    space = _space(api)
    api.create_repo(space, repo_type="space", space_sdk="docker", private=True, exist_ok=True)
    local = ROOT / ".env"
    env = read_env(local)
    key = env.get("PROD_API_KEY")
    if not key:
        key = "hir_" + secrets.token_urlsafe(32)
        with open(local, "a", encoding="utf-8") as fh:
            fh.write(f"\n# Key giữa proxy Vercel và API production (sinh bởi deploy.hf_space)\nPROD_API_KEY={key}\n")
        print("[secrets] Đã sinh PROD_API_KEY mới và ghi vào .env local")
    dataset = os.getenv("HF_DATASET") or f"{api.whoami()['name']}/heritage-data"
    # Space chỉ cần đọc dataset: không đưa token quyền ghi vào môi trường chạy.
    if not env.get("HF_READ_TOKEN"):
        sys.exit("Thiếu HF_READ_TOKEN (token loại Read) trong .env: Space dùng nó để tải dataset")

    pushed = {k: v for k, v in env.items() if k not in LOCAL_ONLY}
    pushed.update(TEST_API_KEY=key, HF_TOKEN=env["HF_READ_TOKEN"])
    for k, v in sorted(pushed.items()):
        api.add_space_secret(space, k, v)
    variables = {"HF_DATASET": dataset, "API_KEY_ENFORCE": "true"}
    for k, v in variables.items():
        api.add_space_variable(space, k, v)
    print(f"[secrets] {space}: {len(pushed)} secret ({', '.join(sorted(pushed))}) + {len(variables)} variable")


def wait(args) -> None:
    api = _api()
    space = _space(api)
    wait_for_space(api, space, "/v1/health", args.timeout)


def wait_for_space(api, space: str, health_path: str, timeout: int) -> None:
    """Chờ đúng revision và endpoint health của từng service."""
    head = api.space_info(space).sha
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        rt = api.get_space_runtime(space)
        stage = str(rt.stage)
        if stage != last:
            print(f"[wait] {stage}", flush=True)
            last = stage
        if stage in FAILED:
            sys.exit(f"Space lỗi ở stage {stage}: xem log tại https://huggingface.co/spaces/{space}?logs=container")
        if stage == "RUNNING" and (rt.raw or {}).get("sha") in (None, head):
            break
        time.sleep(15)
    else:
        sys.exit(f"Quá {timeout} s mà Space chưa RUNNING")

    url = f"{space_url(space)}{health_path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_token()}"})
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200:
                    print(f"[wait] {url} -> 200")
                    return
        except OSError:
            pass
        time.sleep(10)
    sys.exit(f"{url} chưa trả 200")


def url(_args) -> None:
    print(space_url(_space(_api())))


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m deploy.hf_space")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("push", push), ("secrets", set_secrets), ("url", url)]:
        sub.add_parser(name).set_defaults(fn=fn)
    w = sub.add_parser("wait")
    w.add_argument("--timeout", type=int, default=2400)
    w.set_defaults(fn=wait)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
