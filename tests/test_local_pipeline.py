import csv
import json

import numpy as np
import pytest

from pipeline.stage2_classifier import route
from retrieval.rule_parser import parse
from storage.local import connect, import_approved


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    path = tmp_path / "approved.csv"
    rows = [
        {
            "entity_id": "e1",
            "canonical_name": "Bích Động",
            "slug": "bich-dong",
            "category": "Hang động",
            "image_url": "https://example.org/1.jpg",
            "flag": "approved",
            "description": "Hang động ở Ninh Bình",
        },
        {
            "entity_id": "e2",
            "canonical_name": "Cầu Maspéro",
            "slug": "cau-maspero",
            "category": "Cầu",
            "image_url": "https://example.org/2.jpg",
            "flag": "approved",
            "description": "Cầu ở Sóc Trăng",
        },
        {
            "entity_id": "e2",
            "canonical_name": "Cầu Maspéro",
            "slug": "cau-maspero",
            "category": "Cầu",
            "image_url": "https://example.org/3.jpg",
            "flag": "approved",
            "description": "Cầu ban đêm",
        },
        {
            "entity_id": "e3",
            "canonical_name": "Unavailable",
            "slug": "unavailable",
            "category": "Other",
            "image_url": "x-raw-image:///missing",
            "flag": "approved",
            "description": "",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_import_is_idempotent_and_excludes_non_http(catalog):
    first = import_approved(catalog)
    second = import_approved(catalog)
    assert first["images"] == second["images"] == 3
    assert first["entities"] == 2
    assert first["skipped_rows"] == 1
    assert second["reused"] is True
    with connect() as conn:
        assert conn.execute("SELECT count(DISTINCT image_id) FROM images").fetchone()[0] == 3


def test_failed_import_preserves_previous_catalog(catalog):
    import_approved(catalog)
    catalog.write_text("bad,columns\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Missing CSV columns"):
        import_approved(catalog)
    with connect() as conn:
        assert conn.execute("SELECT count(*) FROM images").fetchone()[0] == 3


def test_index_resumes_only_flushed_batches(catalog, monkeypatch):
    from retrieval import local_index
    from storage.runtime import data_dir

    import_approved(catalog)
    monkeypatch.setenv("INDEX_CHUNK_SIZE", "2")
    monkeypatch.setattr(local_index, "EMBED_DIM", 2)
    calls = 0

    def encode(texts):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("interrupted")
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(local_index, "embed_text", encode)
    with pytest.raises(RuntimeError, match="interrupted"):
        local_index.build()
    assert local_index.manifest()["indexed_count"] == 2
    monkeypatch.setattr(local_index, "embed_text", lambda texts: [[0.0, 1.0] for _ in texts])
    assert local_index.build()["complete"]
    vectors = np.load(data_dir() / "vectors.npy")
    np.testing.assert_allclose(vectors, [[1, 0], [1, 0], [0, 1]])
    assert local_index.search_vector([0, 1], 1)[0][0] == 3
    local_index._load.cache_clear()


def test_unsafe_score_overrides_high_relevance():
    assert route({"relevance": 0.99, "nsfw": 0.6}) == "reject"


def test_hop_keywords_require_whole_words():
    assert parse("danh sách di sản").intent_type == "set_query"
    assert parse("bãi biển xanh").intent_type == "single"


def test_llm_rerank_rejects_invented_ids(catalog, monkeypatch):
    from retrieval import llm_router
    from retrieval.rerank import rerank

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(
        llm_router, "call_json", lambda *a, **kw: {"scores": [{"id": 9, "score": 0.9}]}
    )
    with pytest.raises(ValueError, match="every candidate"):
        rerank("Bích Động", [{"image_id": "a"}], keep=1)


def test_llm_rerank_calls_gemini_via_openrouter(monkeypatch):
    from retrieval import llm_router
    from retrieval.rerank import rerank

    seen = {}

    def call_json(body, schema_model, **kwargs):
        seen.update(body=body, **kwargs)
        return {"scores": [{"id": 0, "score": 0.2}, {"id": 1, "score": 0.9}], "cached": False}

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setattr(llm_router, "call_json", call_json)
    hits = rerank("Bích Động", [{"image_id": "a"}, {"image_id": "b"}], keep=2)
    assert [h.image_id for h in hits] == ["b", "a"]
    assert hits[0].reason == "llm_metadata_rerank"
    assert seen["body"]["model"] == "google/gemini-3.5-flash-lite"
    assert seen["body"]["response_format"]["json_schema"]["strict"] is True
    assert seen["kind"] == "rerank_call"


def test_cors_preflight_with_key_enforcement(monkeypatch):
    from fastapi.testclient import TestClient

    from api.main import app

    monkeypatch.setenv("API_KEY_ENFORCE", "true")
    with TestClient(app) as client:
        response = client.options(
            "/v1/search",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-api-key",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"


def test_multihop_does_not_invent_relations(catalog):
    from retrieval.search import search

    import_approved(catalog)
    response = search("con trai của chủ tịch X")
    assert response.hits == []
    assert response.warnings


def test_multi_intent_preserves_both_subjects(catalog, monkeypatch):
    from retrieval import llm_router, local_index, local_search
    from retrieval.search import search

    with catalog.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    extra = {**rows[0], "image_url": "https://example.org/4.jpg"}
    with catalog.open("a", encoding="utf-8", newline="") as stream:
        csv.DictWriter(stream, fieldnames=extra.keys()).writerow(extra)
    import_approved(catalog)
    monkeypatch.setattr(local_index, "EMBED_DIM", 2)
    monkeypatch.setattr(local_index, "embed_text", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(local_search, "embed_query", lambda texts: [[1.0, 0.0] for _ in texts])
    local_index.build()
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    def call_json(body, schema_model, kind="call", **kwargs):
        if kind != "rerank_call":
            raise llm_router.LLMError("parse not mocked")
        candidates = json.loads(body["messages"][1]["content"])["candidates"]
        return {
            "scores": [
                {"id": c["id"], "score": 0.99 if c["entity"] == "Bích Động" else 0.7}
                for c in candidates
            ]
        }

    monkeypatch.setattr(llm_router, "call_json", call_json)
    result = search("Bích Động và Cầu Maspéro", top_k=2)
    assert {h.entity_id for h in result.hits} == {"e1", "e2"}
    local_index._load.cache_clear()
