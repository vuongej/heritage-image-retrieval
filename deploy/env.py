"""Sinh file .env cho server từ .env local — chỉ giữ khóa API và cấu hình runtime.

  python -m deploy.env --out <đường-dẫn> --domain <api-domain>

Không in giá trị ra màn hình. Nếu .env local chưa có PROD_API_KEY (key giữa proxy Vercel và API),
sinh mới và ghi thêm vào .env local để dùng lại khi đặt env cho Vercel.
"""

from __future__ import annotations

import argparse
import secrets
from pathlib import Path

from storage.runtime import ROOT

# Biến chỉ có nghĩa trên máy local hoặc với hạ tầng compose cũ; không đưa lên server.
LOCAL_ONLY = {
    "VERCEL_TOKEN", "HF_TOKEN", "HF_READ_TOKEN", "PROD_API_KEY", "TEST_API_KEY", "API_KEY_ENFORCE",
    "VECTOR_BACKEND", "LOCAL_DATA_DIR", "LOCAL_LLM_BASE_URL", "EMBED_ONNX_PATH", "S3_ENDPOINT",
    "S3_BUCKET", "S3_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "POSTGRES_DSN",
    "REDIS_URL", "QDRANT_URL", "QDRANT_HOST_PORT", "VERIFY_DIR", "SOURCE_CSV",
    "HF_HUB_DISABLE_SYMLINKS_WARNING",
}


def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            value = value.strip().strip("\"'")
            if value:
                out[key.strip()] = value
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m deploy.env")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--domain", required=True, help="tên miền của API, ví dụ 1-2-3-4.sslip.io")
    ap.add_argument("--dataset", default="", help="HF dataset chứa index (mặc định <user>/heritage-data)")
    args = ap.parse_args()

    local = ROOT / ".env"
    env = read_env(local)
    key = env.get("PROD_API_KEY")
    if not key:
        key = "hir_" + secrets.token_urlsafe(32)
        with open(local, "a", encoding="utf-8") as fh:
            fh.write(f"\n# Key giữa proxy Vercel và API production (sinh bởi deploy.env)\nPROD_API_KEY={key}\n")
        print("[env] Đã sinh PROD_API_KEY mới và ghi vào .env local")
    hf_token = env.get("HF_READ_TOKEN") or env.get("HF_TOKEN", "")
    dataset = args.dataset
    if not dataset and hf_token:
        from huggingface_hub import HfApi

        dataset = f"{HfApi(token=hf_token).whoami()['name']}/heritage-data"

    out = {k: v for k, v in env.items() if k not in LOCAL_ONLY}
    out.update(
        TEST_API_KEY=key,
        API_KEY_ENFORCE="true",
        HF_TOKEN=hf_token,
        HF_DATASET=dataset,
        API_DOMAIN=args.domain,
    )
    args.out.write_text("".join(f"{k}={v}\n" for k, v in sorted(out.items())), encoding="utf-8")
    print(f"[env] {args.out}: {len(out)} biến ({', '.join(sorted(out))})")


if __name__ == "__main__":
    main()
