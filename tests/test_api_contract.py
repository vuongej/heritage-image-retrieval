from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)
HEADERS = {"X-API-Key": "gsk_test_dev_only"}


def test_health_no_key_required():
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["slo_p95_ms"] == 1500


def test_search_contract(monkeypatch):
    from retrieval.search import SearchHit, SearchResponse

    monkeypatch.setattr(
        "api.routers.search.run_search",
        lambda *a, **kw: SearchResponse(
            "test-id", "single", "rule", [SearchHit("image-a", "https://example.org/a.jpg", 0.9)]
        ),
    )
    r = client.post("/v1/search", json={"query": "Quần thể Tràng An", "top_k": 10}, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    for k in ("request_id", "intent_type", "hits", "facets", "timings_ms", "total_ms"):
        assert k in body
    assert "X-Response-Time" in r.headers
    assert body["hits"][0]["image_id"] == "image-a"


def test_embed_contract(monkeypatch):
    from retrieval.embed import EMBED_DIM

    monkeypatch.setattr(
        "api.routers.embed.embed_text", lambda texts: [[1.0] * EMBED_DIM for _ in texts]
    )
    r = client.post("/v1/embed", json={"texts": ["Quần thể Tràng An"]}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["dim"] == EMBED_DIM
    assert len(r.json()["vectors"][0]) == EMBED_DIM


def test_rerank_contract(monkeypatch):
    from retrieval.rerank import RerankHit

    monkeypatch.setattr("api.routers.rerank.run_rerank", lambda *a, **kw: [RerankHit("a", 0.9)])
    r = client.post(
        "/v1/rerank",
        json={"query": "Tràng An", "candidates": [{"image_id": "a"}], "keep": 1},
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert "hits" in r.json()


def test_graph_budget_endpoint(monkeypatch):
    from retrieval.graph import GraphStats

    monkeypatch.setattr(
        "retrieval.graph.build_from_csv", lambda *a, **kw: GraphStats(2, 1, 0.01, True)
    )
    r = client.post("/v1/graph", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["budget_s"] == 5.0
