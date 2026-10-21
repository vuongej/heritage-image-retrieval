"""Semantic / exact cache cho query parse + kết quả search."""

from __future__ import annotations

import hashlib
import json

TTL_SEARCH_S = 900
TTL_PARSE_S = 86400


def qkey(query: str, top_k: int, filters: dict | None) -> str:
    raw = json.dumps(
        {"q": query.strip().lower(), "k": top_k, "f": filters or {}},
        sort_keys=True,
        ensure_ascii=False,
    )
    return "search:" + hashlib.sha256(raw.encode()).hexdigest()


def pkey(query: str) -> str:
    return "parse:" + hashlib.sha256(query.strip().lower().encode()).hexdigest()


def get_json(r, key: str):
    v = r.get(key)
    return json.loads(v) if v else None


def set_json(r, key: str, value, ttl: int) -> None:
    r.setex(key, ttl, json.dumps(value, ensure_ascii=False))


def hit_rate(r, prefix: str) -> float:
    """TODO(impl): đọc counter hits/misses để báo cáo cache hit-rate (mục tiêu >= 0.90)."""
    raise NotImplementedError
