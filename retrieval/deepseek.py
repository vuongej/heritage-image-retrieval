"""DeepSeek JSON calls with bounded retries, disk cache and token accounting."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time

import httpx

from storage.local import cache_get, cache_put
from storage.runtime import data_dir

_lock = threading.Lock()


class BudgetExhausted(RuntimeError):
    """HTTP 401/402/403: key invalid or out of credit. Callers stop softly, never retry."""


def json_chat(
    system: str,
    user: str | list,
    *,
    max_tokens: int = 2048,
    cache: bool = True,
    temperature: float = 0,
    tag: str | None = None,
) -> dict:
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        raise RuntimeError("DEEPSEEK_API_KEY is not configured")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
        "temperature": temperature,
        "thinking": {"type": "disabled"},
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    if cache:
        found = cache_get("deepseek:" + digest)
        if found is not None:
            return found
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    started = time.perf_counter()
    for attempt in range(3):
        try:
            response = httpx.post(
                base + "/chat/completions",
                json=payload,
                headers={"Authorization": "Bearer " + key},
                timeout=httpx.Timeout(120, connect=20),
            )
        except httpx.TransportError:
            if attempt == 2:
                raise RuntimeError("DeepSeek connection failed after 3 attempts") from None
            time.sleep(2**attempt)
            continue
        if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
            time.sleep(2**attempt)
            continue
        if response.status_code in {401, 402, 403}:
            raise BudgetExhausted(f"DeepSeek HTTP {response.status_code}: key invalid or no credit")
        if not response.is_success:
            raise RuntimeError(f"DeepSeek HTTP {response.status_code}; response body omitted")
        body = response.json()
        if body["choices"][0].get("finish_reason") == "length":
            raise RuntimeError("DeepSeek JSON output was truncated")
        result = json.loads(body["choices"][0]["message"].get("content") or "{}")
        if not isinstance(result, dict) or not result:
            raise ValueError("DeepSeek returned empty or non-object JSON")
        event = {
            "model": model,
            "usage": body.get("usage", {}),
            "request_hash": digest,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
        if tag:
            event["tag"] = tag
        with _lock, (data_dir() / "deepseek_usage.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event) + "\n")
        if cache:
            cache_put("deepseek:" + digest, result)
        return result
    raise RuntimeError("DeepSeek retry budget exhausted")
