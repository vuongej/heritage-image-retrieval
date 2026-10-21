"""Phase 1.3/1.4: /v1/search không chờ LLM; LLM trễ/lỗi -> rule; LLM khác -> retrieve thêm."""

import csv
import json
import time

import httpx
import pytest

from retrieval import llm_router, speculative
from storage.local import connect, import_approved


def llm_output(intent, subs, place=""):
    return {
        "intent_type": intent,
        "entities": [],
        "sub_queries": subs,
        "hop_chain": [],
        "modifiers": {"place": place, "time": "", "style": ""},
        "cached": False,
    }


@pytest.fixture
def index(tmp_path, monkeypatch):
    from retrieval import local_index, local_search

    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    path = tmp_path / "approved.csv"
    base = {"flag": "approved", "description": "", "slug": "s", "category": "Di tích"}
    names = {
        "e1": "Tượng đài Mẹ Việt Nam Anh hùng (Bình Dương)",
        "e2": "Chùa Hương",
        "e3": "Bích Động",
    }
    rows = [
        {
            **base,
            "entity_id": eid,
            "canonical_name": name,
            "image_url": f"https://e.org/{eid}{i}.jpg",
        }
        for eid, name in names.items()
        for i in range(2)
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    import_approved(path)
    monkeypatch.setattr(local_index, "EMBED_DIM", 2)
    monkeypatch.setattr(local_index, "embed_text", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(local_search, "embed_query", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr("retrieval.rerank.score_pairs", lambda q, c: [0.5] * len(c))
    local_index.build()
    yield
    local_index._load.cache_clear()


def cached_searches() -> int:
    with connect() as conn:
        return conn.execute("SELECT count(*) FROM llm_cache WHERE key LIKE 'search:%'").fetchone()[
            0
        ]


def enable_llm(monkeypatch, parse, mode="always"):
    # Các ca dưới đây dùng tên thực thể chính xác (rule "high"): ở chế độ mặc định ambiguous_only
    # LLM sẽ không được gọi, nên test hành vi LLM chạy với LLM_PARSE_MODE=always.
    monkeypatch.setenv("LLM_PARSE_MODE", mode)
    monkeypatch.setattr(llm_router, "enabled", lambda: True)
    monkeypatch.setattr(llm_router, "parse", parse)
    # Chỉ test parse; rerank giữ cosine (rerank LLM có test riêng).
    monkeypatch.setattr("retrieval.rerank.llm_enabled", lambda: False)


def test_entity_name_with_marker_returns_images(index):
    from retrieval.search import search

    result = search("Tượng đài Mẹ Việt Nam Anh hùng (Bình Dương)", top_k=2)
    assert result.intent_type == "single"
    assert result.parser == "rule"
    assert {h.entity_id for h in result.hits} == {"e1"}


def test_slow_llm_never_blocks_search(index, monkeypatch):
    from retrieval.search import search

    def slow(query, candidates):
        time.sleep(1.5)
        return llm_output("single", [query])

    enable_llm(monkeypatch, slow)
    monkeypatch.setattr(speculative, "LLM_PARSE_TIMEOUT_MS", 50)
    started = time.perf_counter()
    result = search("Chùa Hương", top_k=2)
    assert time.perf_counter() - started < 1.0
    assert result.parser == "rule (llm timeout)"
    assert {h.entity_id for h in result.hits} == {"e2"}
    assert cached_searches() == 0  # lần sau parse LLM sẽ có trong cache


def test_llm_split_is_used_when_it_differs(index, monkeypatch):
    from retrieval.search import search

    candidates_seen = []

    def split(query, candidates):
        candidates_seen.append(candidates)
        return llm_output("multi_intent", ["Chùa Hương", "Bích Động"])

    enable_llm(monkeypatch, split)
    result = search("Chùa Hương Bích Động", top_k=4)
    assert result.parser == "llm"
    assert result.intent_type == "multi_intent"
    assert {h.entity_id for h in result.hits} == {"e2", "e3"}
    assert "Chùa Hương" in candidates_seen[0]  # ứng viên thực thể gửi kèm cho LLM
    assert cached_searches() == 1


def test_llm_error_falls_back_to_rule(index, monkeypatch):
    from retrieval.search import search

    def broken(query, candidates):
        raise llm_router.LLMError("OpenRouter HTTP 503")

    enable_llm(monkeypatch, broken)
    result = search("Chùa Hương", top_k=2)
    assert result.hits and result.parser == "rule (llm error)"
    assert any(w.startswith("llm_parse_failed") for w in result.warnings)
    assert cached_searches() == 0


def test_llm_multi_hop_cannot_empty_a_rule_answer(index, monkeypatch):
    from retrieval.search import search

    enable_llm(monkeypatch, lambda q, c: llm_output("multi_hop", [q]))
    result = search("Tượng đài Mẹ Việt Nam Anh hùng", top_k=2)
    assert result.intent_type == "single" and result.hits
    assert result.parser == "rule+llm"


def test_llm_place_modifier_is_shared_by_sub_queries():
    rule = {"intent_type": "single", "sub_queries": [{"text": "x", "type": "text"}]}
    parsed = speculative.to_parsed(
        llm_output("multi_intent", ["hồ bơi", "công viên nước ở Phú Quốc"], place="Phú Quốc"),
        rule,
    )
    assert [s["text"] for s in parsed["sub_queries"]] == [
        "hồ bơi Phú Quốc",
        "công viên nước ở Phú Quốc",
    ]


def test_outcomes_are_logged(index, monkeypatch):
    from retrieval.search import search

    enable_llm(monkeypatch, lambda q, c: llm_output("single", ["chùa hương"]))
    search("Chùa Hương", top_k=2)
    summary = llm_router.usage_summary()
    assert summary["outcomes"] == {"same": 1}


# ---------------------------------------------------------------- llm_router


def test_enabled_needs_key_and_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    assert not llm_router.enabled()
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert llm_router.enabled()
    monkeypatch.setenv("LLM_PROVIDER", "none")
    assert not llm_router.enabled()


def test_payload_is_strict_schema_text_only():
    body = llm_router.payload("chùa hương", ["Chùa Hương"])
    assert body["model"] == "google/gemini-3.5-flash-lite"
    fmt = body["response_format"]["json_schema"]
    assert fmt["strict"] is True
    schema = fmt["schema"]
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False
    assert body["reasoning"] == {"effort": "minimal"}  # model không cho tắt reasoning
    assert all(isinstance(m["content"], str) for m in body["messages"])  # không gửi ảnh


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post(self, url, json=None, headers=None):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def completion(content):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 400, "completion_tokens": 60, "cost": 0.00027},
        },
    )


@pytest.fixture
def router_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")


def test_parse_validates_caches_and_logs(router_env, monkeypatch):
    good = llm_output("single", ["chùa hương"])
    good.pop("cached")
    client = FakeClient([completion(json.dumps(good, ensure_ascii=False))])
    monkeypatch.setattr(llm_router, "_http", lambda: client)
    first = llm_router.parse("chùa hương", [])
    second = llm_router.parse("chùa hương", [])
    assert first["intent_type"] == "single" and not first["cached"]
    assert second["cached"] and client.calls == 1
    summary = llm_router.usage_summary()
    assert summary["calls"] == 1 and summary["usd_total"] == 0.00027


@pytest.mark.parametrize(
    "response",
    [
        completion('{"intent_type": "guess"}'),
        httpx.Response(503, json={}),
        httpx.ConnectTimeout("slow"),
    ],
)
def test_parse_errors_become_llm_error(router_env, monkeypatch, response):
    monkeypatch.setattr(llm_router, "_http", lambda: FakeClient([response]))
    with pytest.raises(llm_router.LLMError):
        llm_router.parse("chùa hương", [])
    assert llm_router.usage_summary()["call_errors"] == 1
