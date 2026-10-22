"""Backend embedding qua endpoint OpenAI-compatible (qwen3-embedding-4b); không gọi mạng thật."""

import httpx
import pytest

from retrieval import embed


class FakeClient:
    def __init__(self, dim=4, fail=0, status=500):
        self.dim, self.fail, self.status = dim, fail, status
        self.inputs: list[list[str]] = []

    def post(self, url, json=None, headers=None):
        self.inputs.append(json["input"])
        if self.fail:
            self.fail -= 1
            return httpx.Response(self.status, json={})
        data = [
            {"index": i, "embedding": [float(len(t)), 1.0] + [0.0] * (self.dim - 2)}
            for i, t in reversed(list(enumerate(json["input"])))  # thứ tự trả về bị đảo
        ]
        return httpx.Response(200, json={"data": data})


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(embed, "EMBED_BACKEND", "api")
    monkeypatch.setattr(embed, "EMBED_DIM", 4)
    monkeypatch.setattr(embed, "EMBED_MODEL", "qwen3-embedding-4b")
    monkeypatch.setattr(embed, "QUERY_INSTRUCTION", "find photos")
    monkeypatch.setattr(embed.time, "sleep", lambda s: None)
    monkeypatch.setenv("EMBED_API_BASE", "https://embed.example/v1")
    monkeypatch.setenv("EMBED_API_KEY", "sk-test")
    client = FakeClient()
    monkeypatch.setattr(embed, "_http", lambda: client)
    return client


def test_documents_are_sent_verbatim_and_normalized_in_order(api):
    vectors = embed.embed_text(["ab", "abcd"])
    assert api.inputs == [["ab", "abcd"]]
    assert vectors[0][0] < vectors[1][0]  # đúng thứ tự dù endpoint trả đảo
    assert all(abs(sum(x * x for x in v) - 1) < 1e-5 for v in vectors)


def test_queries_get_the_instruction_prefix(api):
    embed.embed_query(["chùa cổ"])
    assert api.inputs == [["Instruct: find photos\nQuery: chùa cổ"]]


def test_large_inputs_are_split_into_batches(api, monkeypatch):
    monkeypatch.setenv("EMBED_API_BATCH", "3")
    vectors = embed.embed_text([str(i) * (i + 1) for i in range(7)])
    assert sorted(len(b) for b in api.inputs) == [1, 3, 3]
    assert [round(v[0] / v[1]) for v in vectors] == list(range(1, 8))  # căn hàng đúng


def test_transient_errors_are_retried(api):
    api.fail = 2
    assert len(embed.embed_text(["x"])) == 1


@pytest.mark.parametrize(("status", "calls"), [(401, 1), (400, 1), (503, 3)])
def test_failures_raise_embedding_unavailable(api, status, calls):
    api.fail, api.status = 5, status
    with pytest.raises(embed.EmbeddingUnavailable):
        embed.embed_text(["x"])
    assert len(api.inputs) == calls


def test_wrong_dimension_is_rejected(api):
    api.dim = 8
    with pytest.raises(embed.EmbeddingUnavailable, match="4d"):
        embed.embed_text(["x"])


def test_search_degrades_when_embedding_endpoint_is_down(tmp_path, monkeypatch):
    import csv

    from retrieval import local_index, local_search
    from retrieval.search import search
    from storage.local import connect, import_approved

    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    path = tmp_path / "a.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, ["entity_id", "canonical_name", "slug", "category", "image_url", "flag"]
        )
        writer.writeheader()
        for i, name in enumerate(["Chùa Hương", "Bích Động"]):
            writer.writerow(
                {"entity_id": f"e{i}", "canonical_name": name, "slug": "s", "category": "Di tích",
                 "image_url": f"https://e.org/{i}.jpg", "flag": "approved"}
            )  # fmt: skip
    import_approved(path)
    monkeypatch.setattr(local_index, "EMBED_DIM", 2)
    monkeypatch.setattr(local_index, "embed_text", lambda texts: [[1.0, 0.0] for _ in texts])
    local_index.build()

    def down(texts):
        raise embed.EmbeddingUnavailable("embedding endpoint lỗi sau 3 lần (ConnectError)")

    monkeypatch.setattr(local_search, "embed_query", down)
    monkeypatch.setattr("retrieval.rerank.score_pairs", lambda q, c: [0.5] * len(c))
    result = search("Chùa Hương", top_k=2)
    assert result.hits and result.hits[0].entity_id == "e0"  # FTS + khớp tên vẫn chạy
    assert any(w.startswith("embedding_failed") for w in result.warnings)
    with connect() as conn:  # câu trả lời suy giảm không được cache
        assert not conn.execute(
            "SELECT count(*) FROM llm_cache WHERE key LIKE 'search:%'"
        ).fetchone()[0]
    local_index._load.cache_clear()


# ---------------------------------------------------------------- rerank cross-encoder qua API


class FakeRerank:
    def __init__(self, scores=None, status=200):
        self.scores, self.status, self.bodies = scores, status, []

    def post(self, url, json=None, headers=None, timeout=None):
        self.bodies.append(json)
        if self.status != 200:
            return httpx.Response(self.status, json={})
        results = [{"index": i, "relevance_score": s} for i, s in enumerate(self.scores)]
        return httpx.Response(
            200, json={"results": sorted(results, key=lambda r: -r["relevance_score"])}
        )


@pytest.fixture
def rerank_api(monkeypatch):
    from retrieval import rerank

    monkeypatch.setenv("RERANK_BACKEND", "api")
    monkeypatch.setenv("EMBED_API_BASE", "https://embed.example/v1")
    monkeypatch.setenv("EMBED_API_KEY", "sk-test")
    return rerank


def test_api_rerank_orders_by_cross_encoder_score(rerank_api, monkeypatch):
    fake = FakeRerank([0.1, 0.9, 0.5])
    monkeypatch.setattr(rerank_api, "_api_client", fake)
    pool = [
        {
            "image_id": "a",
            "entity_name": "Chùa A",
            "parent_class": "Chùa",
            "description": "x" * 900,
        },
        {"image_id": "b", "entity_name": "Đền B"},
        {"image_id": "c", "entity_name": "Đình C"},
    ]
    assert rerank_api.backend() == "api" and rerank_api.model_name() == "jina-reranker-v2"
    hits = rerank_api.rerank("đền", pool, keep=3)
    assert [h.image_id for h in hits] == ["b", "c", "a"]
    assert hits[0].reason == "api_cross_encoder_rerank"
    body = fake.bodies[0]
    assert body["model"] == "jina-reranker-v2" and body["query"] == "đền"
    assert body["documents"][0] == "Chùa A. Chùa. " + "x" * 500  # mô tả cắt 500 ký tự


@pytest.mark.parametrize("fake", [FakeRerank(status=503), FakeRerank([0.5])])
def test_api_rerank_errors_raise(rerank_api, monkeypatch, fake):
    monkeypatch.setattr(rerank_api, "_api_client", fake)
    with pytest.raises((RuntimeError, ValueError)):
        rerank_api.rerank("đền", [{"image_id": "a"}, {"image_id": "b"}], keep=2)


def test_llm_backend_without_key_falls_back_to_embedding(monkeypatch):
    from retrieval import rerank

    monkeypatch.setenv("RERANK_BACKEND", "llm")
    assert rerank.backend() == "embedding"  # conftest: OPENROUTER_API_KEY rỗng


def test_search_survives_when_rerank_and_fallback_both_fail(tmp_path, monkeypatch):
    import csv

    from retrieval import local_index, local_search
    from retrieval import rerank as reranking
    from retrieval.search import search
    from storage.local import import_approved

    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    path = tmp_path / "a.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, ["entity_id", "canonical_name", "slug", "category", "image_url", "flag"]
        )
        writer.writeheader()
        for i in range(3):
            writer.writerow(
                {"entity_id": "e0", "canonical_name": "Chùa Hương", "slug": "s", "category": "Chùa",
                 "image_url": f"https://e.org/{i}.jpg", "flag": "approved"}
            )  # fmt: skip
    import_approved(path)
    monkeypatch.setattr(local_index, "EMBED_DIM", 2)
    monkeypatch.setattr(local_index, "embed_text", lambda texts: [[1.0, 0.0] for _ in texts])
    local_index.build()
    monkeypatch.setattr(local_search, "embed_query", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setenv("RERANK_BACKEND", "api")

    def limited(*args, **kwargs):
        raise embed.EmbeddingUnavailable("embedding endpoint lỗi sau 3 lần (HTTP 429)")

    monkeypatch.setattr(reranking, "api_scores", limited)
    monkeypatch.setattr(reranking, "score_pairs", limited)
    result = search("Chùa Hương", top_k=3)
    assert len(result.hits) == 3
    assert any(w.startswith("rerank_failed") for w in result.warnings)
    local_index._load.cache_clear()


def test_rate_limiter_waits_instead_of_bursting(monkeypatch):
    from retrieval import ratelimit

    ratelimit.reset()
    monkeypatch.setenv("EMBED_API_RPM", "2")
    monkeypatch.setattr(ratelimit, "WINDOW_S", 0.3)
    assert ratelimit.acquire() == 0 and ratelimit.acquire() == 0
    assert ratelimit.acquire() > 0  # request thứ 3 trong cửa sổ phải chờ
    monkeypatch.setenv("EMBED_API_RPM", "0")
    assert ratelimit.acquire() == 0  # tắt
    ratelimit.reset()
