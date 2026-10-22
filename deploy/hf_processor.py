"""Deploy Pipeline A lên HF Space private: secrets (local), push, wait, url.

HF_PROCESS_SPACE mặc định <user>/heritage-processor. Chỉ stage file được git track;
không tải CSV người dùng, cache hay .env lên repository của Space.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from deploy.hf_space import _api, space_url, wait_for_space
from storage.runtime import ROOT

STAGE = [
    "processing", "pipeline", "storage", "retrieval", "models/verify",
    "api/__init__.py", "api/security.py", "deploy/processor.requirements.txt",
]
README = """---
title: Heritage Image Processing
emoji: 🖼️
colorFrom: purple
colorTo: blue
sdk: docker
app_port: 8100
startup_duration_timeout: 1h
pinned: false
---

Pipeline A của https://github.com/VSF-AR-ES-V-Lookup/PhamVanVuong_search_image.
Được đồng bộ tự động bởi GitHub Actions; không sửa trực tiếp ở đây.
"""


def _space(api) -> str:
    return os.getenv("HF_PROCESS_SPACE") or f"{api.whoami()['name']}/heritage-processor"


def stage_files(stage: Path) -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", *STAGE], cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode().split("\0")
    for rel in filter(None, tracked):
        (stage / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, stage / rel)
    shutil.copy2(ROOT / "deploy/processor.Dockerfile", stage / "Dockerfile")
    (stage / "README.md").write_text(README, encoding="utf-8")


def push(_args) -> None:
    api = _api()
    space = _space(api)
    api.create_repo(space, repo_type="space", space_sdk="docker", private=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        stage_files(stage)
        info = api.upload_folder(
            repo_id=space, repo_type="space", folder_path=stage,
            delete_patterns=[f"{d}/**" for d in ("processing", "pipeline", "storage", "retrieval", "models", "api", "deploy")],
            commit_message=f"Deploy processor {os.getenv('GITHUB_SHA', 'local')[:7]}",
        )
    print(f"[processor] {space} @ {info.oid[:7]}")


def set_secrets(_args) -> None:
    from huggingface_hub import Volume

    api = _api()
    space = _space(api)
    key = os.getenv("PROD_API_KEY")
    if not key:
        sys.exit("Thiếu PROD_API_KEY: dùng cùng key production của proxy Vercel")
    api.create_repo(space, repo_type="space", space_sdk="docker", private=True, exist_ok=True)
    # Bucket private giữ job, CSV kết quả và cache qua lần rebuild/restart.
    bucket = f"{space}-data"
    api.create_bucket(bucket, private=True, exist_ok=True)
    volumes = list(api.get_space_runtime(space).volumes or [])
    mount_path = "/home/user/work"
    existing = next((v for v in volumes if v.mount_path == mount_path), None)
    if existing is None:
        api.set_space_volumes(space, [*volumes, Volume(type="bucket", source=bucket, mount_path=mount_path)])
    elif existing.source != bucket or existing.read_only:
        sys.exit(f"Mount {mount_path} đã có cấu hình khác; kiểm tra trước khi đổi")
    values = {"TEST_API_KEY": key}
    if os.getenv("DEEPSEEK_API_KEY"):
        values["DEEPSEEK_API_KEY"] = os.environ["DEEPSEEK_API_KEY"]
    for name, value in values.items():
        api.add_space_secret(space, name, value)
    variables = {"API_KEY_ENFORCE": "true", "PROCESS_MAX_UPLOAD_MB": "4"}
    variables.update({k: os.environ[k] for k in ("DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL") if os.getenv(k)})
    for name, value in variables.items():
        api.add_space_variable(space, name, value)
    print(f"[processor] configured secrets: {', '.join(sorted(values))} (values hidden)")
    print(f"[processor] persistent bucket: {bucket} -> {mount_path}")


def wait(args) -> None:
    api = _api()
    wait_for_space(api, _space(api), "/v1/process/health", args.timeout)


def url(_args) -> None:
    api = _api()
    print(space_url(_space(api)))


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m deploy.hf_processor")
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
