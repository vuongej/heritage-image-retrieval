"""Hạn chờ trên đường truy vấn: endpoint embedding / rerank chậm không được kéo request vượt SLO."""

from __future__ import annotations

import time

import httpx
import pytest

from retrieval import embed, local_search, ratelimit, rerank


def test_embed_query_deadline_raises_fast(monkeypatch):
    monkeypatch.setattr(embed, "EMBED_BACKEND", "api")
    monkeypatch.setattr(embed, "embed_text", lambda texts: time.sleep(1.5) or [[0.0]])
    monkeypatch.setenv("EMBED_QUERY_DEADLINE_S", "0.2")
    t = time.perf_counter()
    with pytest.raises(embed.EmbeddingUnavailable, match="quá hạn"):
        embed.embed_query(["Văn Miếu"])
    assert time.perf_counter() - t < 1.0


class SlowClient:
    def __init__(self):
        self.calls = 0

    def post(self, *args, timeout=None, **kwargs):
        self.calls += 1
        time.sleep(min(0.4, timeout.read))
        raise httpx.ReadTimeout("slow")


def test_rerank_api_total_deadline(monkeypatch):
    client = SlowClient()
    monkeypatch.setattr(rerank, "_api_client", client)
    monkeypatch.setattr(ratelimit, "acquire", lambda: None)
    monkeypatch.setenv("RERANK_API_BASE", "http://rerank.invalid")
    monkeypatch.setenv("RERANK_API_KEY", "k")
    monkeypatch.setenv("RERANK_API_DEADLINE_S", "0.6")
    monkeypatch.setenv("RERANK_API_RETRIES", "5")
    t = time.perf_counter()
    with pytest.raises(RuntimeError, match="hết hạn chờ"):
        rerank.api_scores("q", [{"image_id": "a", "entity_name": "A"}])
    assert time.perf_counter() - t < 1.2
    assert client.calls <= 2


def test_api_rerank_failure_keeps_fusion_order(monkeypatch):
    def boom(*_a, mode=None, **_k):
        if mode == "embedding":
            raise AssertionError("không được gọi dự phòng embedding khi rerank API lỗi")
        raise RuntimeError("rerank endpoint ReadTimeout")

    monkeypatch.setattr(local_search.reranking, "rerank", boom)
    warnings: list[str] = []
    pool = [{"image_id": "a"}, {"image_id": "b"}, {"image_id": "c"}]
    ranked = local_search._rerank("q", pool, "api", warnings)
    assert [h.image_id for h in ranked] == ["a", "b", "c"]
    assert warnings and warnings[0].startswith("rerank_failed") and "fusion order" in warnings[0]


def test_ratelimit_strict_inside_deadline(monkeypatch):
    monkeypatch.setenv("EMBED_API_RPM", "2")
    ratelimit.reset()
    ratelimit.acquire()
    ratelimit.acquire()
    t = time.perf_counter()
    with pytest.raises(ratelimit.QuotaExhausted), ratelimit.deadline(0.3):
        ratelimit.acquire()
    assert time.perf_counter() - t < 0.8
    ratelimit.reset()


def test_request_budget_caps_query_embedding(monkeypatch):
    from retrieval import budget

    monkeypatch.setattr(embed, "EMBED_BACKEND", "api")
    monkeypatch.setattr(embed, "embed_text", lambda texts: time.sleep(1.5) or [[0.0]])
    monkeypatch.setenv("EMBED_QUERY_DEADLINE_S", "5")
    t = time.perf_counter()
    with pytest.raises(embed.EmbeddingUnavailable), budget.request(1.0):  # 1,0 - 0,6 dự phòng = 0,4 s
        embed.embed_query(["Văn Miếu"])
    assert time.perf_counter() - t < 0.8
    with pytest.raises(embed.EmbeddingUnavailable, match="hết thời gian"), budget.request(0.5):
        embed.embed_query(["Văn Miếu"])  # còn < 0,2 s sau phần dự phòng: không gọi endpoint
