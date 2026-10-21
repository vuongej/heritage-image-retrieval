"""Sinh API key nội bộ cho auto test.

python -m scripts.issue_test_key --label ci --scope test --rpm 600
"""

from __future__ import annotations

import argparse
import secrets

from api.security import hash_key


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="ci")
    ap.add_argument("--scope", default="test", choices=["test", "prod", "admin"])
    ap.add_argument("--rpm", type=int, default=600)
    args = ap.parse_args()

    plaintext = "gsk_" + args.scope + "_" + secrets.token_urlsafe(32)
    print("KEY (chỉ hiện 1 lần):", plaintext)
    print("HASH (lưu vào bảng api_keys):", hash_key(plaintext))
    print(f"label={args.label} scope={args.scope} rate_limit_rpm={args.rpm}")


if __name__ == "__main__":
    main()
