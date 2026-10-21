"""Speculative parse — rule trả ngay, LLM chạy song song, có hạn chờ (Phase 1.3).

`local_search.run` gọi `start()` trước khi retrieve bằng kết quả rule, rồi `wait()` sau khi
retrieve xong, chờ tối đa phần còn lại của LLM_PARSE_TIMEOUT_MS (tính từ lúc khởi chạy).
- LLM trùng rule -> giữ kết quả đã có.
- LLM khác (loại intent hoặc sub-query) -> retrieve thêm theo LLM rồi gộp, LLM đứng trước.
- LLM trễ / lỗi -> giữ rule. Luồng nền vẫn chạy xong và ghi cache cho lần sau.
p95 của /v1/search không phụ thuộc độ trễ LLM API.

V2 (A4 — RETRIEVAL_PIPELINE_V2_DATA_DRIVEN_PLAN §5.1):
- `LLM_PARSE_MODE` = `ambiguous_only` (mặc định) | `always` | `off`. Ở `ambiguous_only`, truy
  vấn mà rule đã neo chắc vào tên thực thể (`confidence = high`) KHÔNG gọi LLM.
- Bất biến: LLM không được ghi đè rule `high` (trừ khi LLM_PARSE_CAN_OVERRIDE_CONFIDENT_RULE=true),
  không được đổi `set_query` -> `single`, và `multi_hop` của LLM chưa có resolver thì bị bỏ qua.

Dùng thread thay asyncio để giữ nguyên đường gọi đồng bộ
`POST /v1/search -> retrieval.search.search -> retrieval.local_search.run`.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from retrieval import llm_router
from retrieval.catalog import EntityCatalog, tokenize
from retrieval.places import trailing_place
from storage.local import plain

LLM_PARSE_TIMEOUT_MS = int(os.getenv("LLM_PARSE_TIMEOUT_MS", "600"))
CANDIDATES = 20
ANCHOR_COVERAGE = 0.6  # phần token của sub-query (bỏ địa danh đuôi) nằm trong tên thực thể
POLICY_VERSION = "p3-hop-guard"


def mode() -> str:
    value = os.getenv("LLM_PARSE_MODE", "ambiguous_only").lower()
    return value if value in {"ambiguous_only", "always", "off"} else "ambiguous_only"


def anchored(text: str, catalog: EntityCatalog) -> bool:
    """Sub-query có MỘT tên thực thể phủ >= 60% token? Thử trên câu đầy đủ (địa danh có thể là một
    phần của tên: "Lăng Chủ tịch Hồ Chí Minh") và trên câu đã bỏ địa danh ở cuối ("Chùa Một Cột
    Hà Nội"). Hai tên khác nhau ghép lại ("Chùa Hương Bích Động") không tính là một thực thể."""
    place = trailing_place(plain(text))
    variants = [text]
    if place:
        variants.append(text[: len(text) - len(place)].strip())
    for variant in variants:
        words = tokenize(variant)
        if not words:
            continue
        longest = max((s.end - s.start for s in catalog.match_entity_spans(variant)), default=0)
        if longest / len(words) >= ANCHOR_COVERAGE:
            return True
    return False


def confidence(rule: dict, catalog: EntityCatalog) -> str:
    """high: mọi sub-query single/multi_intent neo vào tên thực thể; medium: set_query; low: còn lại."""
    if rule["intent_type"] in {"single", "multi_intent"} and all(
        anchored(s["text"], catalog) for s in rule["sub_queries"]
    ):
        return "high"
    if rule["intent_type"] == "set_query":
        return "medium"
    return "low"


def should_call(conf: str) -> bool:
    current = mode()
    return current == "always" or (current == "ambiguous_only" and conf != "high")


_executor = ThreadPoolExecutor(
    max_workers=int(os.getenv("LLM_PARSE_WORKERS", "4")), thread_name_prefix="llm-parse"
)


def start(query: str, catalog: EntityCatalog) -> tuple[Future, float] | None:
    if not llm_router.enabled():
        return None
    # suggest() chạy trong luồng nền để không tốn thời gian trên đường nóng.
    future = _executor.submit(lambda: llm_router.parse(query, catalog.suggest(query, CANDIDATES)))
    return future, time.perf_counter()


def wait(handle: tuple[Future, float] | None) -> tuple[dict | None, str]:
    """(kết quả LLM hoặc None, trạng thái: disabled | ok | timeout | error: ...)."""
    if handle is None:
        return None, "disabled"
    future, launched = handle
    remaining = LLM_PARSE_TIMEOUT_MS / 1000 - (time.perf_counter() - launched)
    try:
        return future.result(timeout=max(0.0, remaining)), "ok"
    except FutureTimeout:
        return None, "timeout"
    except llm_router.LLMError as exc:
        return None, f"error: {exc}"
    except Exception as exc:  # LLM lỗi không được làm hỏng request
        return None, f"error: {type(exc).__name__}"


def _texts(parsed: dict) -> list[str]:
    return [" ".join(plain(s["text"]).split()) for s in parsed.get("sub_queries", [])]


def to_parsed(llm: dict, rule: dict) -> dict:
    """Đưa output QueryParse về đúng dạng dict của rule parser."""
    subs = [s.strip() for s in llm["sub_queries"] if s.strip()]
    subs = subs or [s["text"] for s in rule["sub_queries"]]
    place = llm["modifiers"]["place"].strip()
    if place and len(subs) > 1:  # modifier địa điểm dùng chung cho mọi sub-query
        subs = [s if plain(place) in plain(s) else f"{s} {place}" for s in subs]
    intent = llm["intent_type"]
    kind = "class" if intent == "set_query" else "text"
    return {
        **rule,
        "intent_type": intent,
        "sub_queries": [{"text": s, "type": kind} for s in subs],
        "needs_graph": intent in {"multi_hop", "set_query"},
        "parser": "llm",
        "hop_relations": llm["hop_chain"],
        "llm_entities": llm["entities"],
        "modifiers": llm["modifiers"],
    }


def is_equivalent(rule_parsed: dict, llm_parsed: dict | None) -> bool:
    if not llm_parsed:
        return True
    return rule_parsed["intent_type"] == llm_parsed["intent_type"] and _texts(
        rule_parsed
    ) == _texts(llm_parsed)


def decide(rule: dict, llm: dict | None, conf: str = "low") -> tuple[dict, str]:
    """(parse dùng để retrieve, hành động). Hành động: same | llm_intent | llm_subqueries |
    guard_confident_rule | guard_set_to_single | llm_multi_hop_ignored."""
    if llm is None:
        return rule, "same"
    candidate = to_parsed(llm, rule)
    if is_equivalent(rule, candidate):
        return rule, "same"
    can_override = os.getenv("LLM_PARSE_CAN_OVERRIDE_CONFIDENT_RULE", "false").lower() == "true"
    if conf == "high" and not can_override:
        return rule, "guard_confident_rule"
    if rule["intent_type"] == "set_query" and candidate["intent_type"] == "single":
        return rule, "guard_set_to_single"  # không có căn cứ một thực thể duy nhất
    if rule["intent_type"] == "multi_hop" and candidate["intent_type"] != "multi_hop":
        return rule, "guard_keep_multi_hop"  # rule đã lập chuỗi quan hệ; LLM không được bỏ
    if candidate["intent_type"] == "multi_hop":
        return rule, "llm_multi_hop_ignored"
    action = "llm_intent" if candidate["intent_type"] != rule["intent_type"] else "llm_subqueries"
    return candidate, action
