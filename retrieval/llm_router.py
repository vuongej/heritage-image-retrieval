"""Parse truy vấn bằng Gemini 3.5 Flash Lite qua OpenRouter (Phase 1.4).

Chỉ được gọi qua `retrieval.speculative` (luồng nền, có timeout + fallback rule), không bao giờ
đồng bộ trên đường xử lý chính của /v1/search.

Đo thật 2026-10-20 (OpenRouter, provider Google): model bắt buộc reasoning
("Reasoning is mandatory ... cannot be disabled"), nên gửi `reasoning.effort = minimal`
(1.545 ms -> ~900-1.100 ms). Độ trễ này vẫn lớn hơn timeout online 600 ms: ở lần gọi đầu kết quả
LLM thường đến muộn; luồng nền vẫn chạy xong và ghi cache, các lần sau dùng ngay.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from storage.local import cache_get, cache_put
from storage.runtime import data_dir, load_env

load_env()

PROMPT_VERSION = "b1"
HARD_TIMEOUT_S = float(os.getenv("LLM_HARD_TIMEOUT_MS", "6000")) / 1000
MAX_TOKENS = int(os.getenv("LLM_PARSE_MAX_TOKENS", "300"))

Relation = Literal[
    "child_of", "spouse_of", "chairman_of", "located_in", "parent_of", "sibling_of"
]  # fmt: skip


class EntityRef(BaseModel):
    name: str
    type: Literal["poi", "person", "org", "place"]


class Hop(BaseModel):
    subject: str
    relation: Relation
    object: str


class Modifiers(BaseModel):
    place: str
    time: str
    style: str


class QueryParse(BaseModel):
    intent_type: Literal["single", "multi_intent", "multi_hop", "set_query"]
    entities: list[EntityRef]
    sub_queries: list[str]
    hop_chain: list[Hop]
    modifiers: Modifiers


def _obj(properties: dict) -> dict:
    # strict json_schema: mọi trường bắt buộc, không thêm trường lạ (chuỗi rỗng = không có).
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


SCHEMA = _obj(
    {
        "intent_type": {
            "type": "string",
            "enum": ["single", "multi_intent", "multi_hop", "set_query"],
        },
        "entities": {
            "type": "array",
            "items": _obj(
                {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ["poi", "person", "org", "place"]},
                }
            ),
        },
        "sub_queries": {"type": "array", "items": {"type": "string"}},
        "hop_chain": {
            "type": "array",
            "items": _obj(
                {
                    "subject": {"type": "string"},
                    "relation": {
                        "type": "string",
                        "enum": [
                            "child_of",
                            "spouse_of",
                            "chairman_of",
                            "located_in",
                            "parent_of",
                            "sibling_of",
                        ],
                    },  # fmt: skip
                    "object": {"type": "string"},
                }
            ),
        },
        "modifiers": _obj(
            {"place": {"type": "string"}, "time": {"type": "string"}, "style": {"type": "string"}}
        ),
    }
)

SYSTEM_PROMPT = (
    "Bạn là bộ phân tích truy vấn tìm ảnh du lịch Việt Nam. Chỉ trả JSON đúng schema. "
    "Tên riêng địa danh/người PHẢI khớp danh sách ứng viên thực thể nếu được cung cấp. "
    "KHÔNG tách ý định khi cụm từ sau dấu phẩy là tên tỉnh/thành. "
    "Với câu hỏi quan hệ người (con/vợ/chồng/chủ tịch), sinh hop_chain với "
    "relation chuẩn; object '?' nghĩa là thứ cần tìm. "
    "Trường không có giá trị thì để chuỗi rỗng hoặc mảng rỗng."
)


class LLMError(RuntimeError):
    """Lỗi gọi/validate LLM. Người gọi luôn fallback về kết quả rule, không raise lên API."""


_lock = threading.Lock()
_client: httpx.Client | None = None


def model() -> str:
    return os.getenv("LLM_ONLINE_MODEL", "google/gemini-3.5-flash-lite")


def enabled() -> bool:
    """LLM_PROVIDER=none tắt mọi LLM; ngoài ra cần OPENROUTER_API_KEY."""
    return os.getenv("LLM_PROVIDER", "none").lower() != "none" and bool(
        os.getenv("OPENROUTER_API_KEY", "").strip()
    )


def _http() -> httpx.Client:
    # Một client dùng chung: giữ kết nối TLS, bớt ~100-200 ms mỗi lần gọi.
    global _client
    with _lock:
        if _client is None:
            _client = httpx.Client(timeout=httpx.Timeout(HARD_TIMEOUT_S, connect=3))
        return _client


def payload(query: str, candidates: list[str]) -> dict:
    return {
        "model": model(),
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "QueryParse", "strict": True, "schema": SCHEMA},
        },
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Query: {query}\nỨng viên thực thể: "
                + json.dumps(candidates, ensure_ascii=False),
            },
        ],
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "reasoning": {"effort": os.getenv("LLM_PARSE_REASONING", "minimal")},
        "usage": {"include": True},
    }


def log_event(event: dict) -> None:
    event = {"ts": round(time.time(), 3), **event}
    with _lock, (data_dir() / "llm_router_usage.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def call_json(
    body: dict,
    schema_model: type[BaseModel],
    *,
    kind: str = "call",
    cache_prefix: str = "llmparse:",
) -> dict:
    """POST chat/completions qua OpenRouter, validate bằng `schema_model`, cache + log.

    Trả dict đã validate + `cached`. Lỗi -> LLMError. `kind` tách log parse ("call") với rerank.
    """
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise LLMError("OPENROUTER_API_KEY is not configured")
    digest = hashlib.sha256(
        json.dumps([PROMPT_VERSION, body], ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    found = cache_get(cache_prefix + digest)
    if found is not None:
        return {**found, "cached": True}
    base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    started = time.perf_counter()
    event: dict = {"kind": kind, "model": body["model"], "request_hash": digest}
    try:
        response = _http().post(
            base + "/chat/completions",
            json=body,
            headers={
                "Authorization": "Bearer " + key,
                "HTTP-Referer": "http://127.0.0.1:8000",
                "X-Title": "heritage-image-retrieval search",
            },
        )
        event["ms"] = round((time.perf_counter() - started) * 1000)
        if not response.is_success:
            raise LLMError(f"OpenRouter HTTP {response.status_code}")
        data = response.json()
        usage = data.get("usage") or {}
        event.update(
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            cost=usage.get("cost"),
        )
        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise LLMError("output truncated")
        content = (choice.get("message") or {}).get("content") or ""
        try:
            parsed = schema_model.model_validate_json(content).model_dump()
        except ValidationError as exc:
            raise LLMError(f"schema: {exc.errors()[0]['msg']}") from None
    except httpx.HTTPError as exc:
        event["ms"] = round((time.perf_counter() - started) * 1000)
        event["error"] = type(exc).__name__
        log_event(event)
        raise LLMError(f"OpenRouter {type(exc).__name__}") from None
    except LLMError as exc:
        event["error"] = str(exc)
        log_event(event)
        raise
    log_event({**event, "ok": True})
    cache_put(cache_prefix + digest, parsed)
    return {**parsed, "cached": False}


def parse(query: str, candidates: list[str]) -> dict:
    """QueryParse đã validate (dict) + `cached`. Lỗi -> LLMError."""
    return call_json(payload(query, candidates), QueryParse)


def usage_summary(path=None) -> dict:
    """Tỉ lệ dùng LLM / rule, timeout, độ trễ và chi phí từ llm_router_usage.jsonl."""
    path = path or data_dir() / "llm_router_usage.jsonl"
    calls, outcomes = [], {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            event = json.loads(line)
            if event.get("kind") == "call":
                calls.append(event)
            elif event.get("kind") == "outcome":
                outcomes[event["outcome"]] = outcomes.get(event["outcome"], 0) + 1
    ok = [c for c in calls if c.get("ok")]
    ms = sorted(c["ms"] for c in ok if c.get("ms") is not None)
    cost = [c["cost"] for c in ok if c.get("cost") is not None]
    searches = sum(outcomes.values())
    return {
        "searches": searches,
        "outcomes": outcomes,
        "share": {k: round(v / searches, 4) for k, v in outcomes.items()} if searches else {},
        "calls": len(calls),
        "call_errors": len(calls) - len(ok),
        "call_ms_p50": ms[len(ms) // 2] if ms else None,
        "call_ms_p95": ms[min(len(ms) - 1, int(0.95 * len(ms)))] if ms else None,
        "usd_total": round(sum(cost), 6),
        "usd_per_call": round(sum(cost) / len(cost), 6) if cost else None,
    }
