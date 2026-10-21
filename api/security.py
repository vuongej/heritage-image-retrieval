"""X-API-Key — key nội bộ cho auto test, lưu dạng hash."""

from __future__ import annotations

import hashlib
import os


def hash_key(key: str) -> str:
    salt = os.getenv("API_KEY_SALT", "dev-salt-change-me")
    return hashlib.sha256(f"{salt}:{key}".encode()).hexdigest()


def verify_key(key: str) -> bool:
    """TODO(impl): tra bảng api_keys theo key_hash + active = true + rate limit theo scope."""
    expected = os.getenv("TEST_API_KEY", "gsk_test_dev_only")
    if key == expected:
        return True
    return False


def issue_key(label: str, scope: str = "test", rate_limit_rpm: int = 600) -> dict:
    """TODO(impl): sinh key ngẫu nhiên, lưu hash, trả plaintext DUY NHẤT một lần."""
    raise NotImplementedError
