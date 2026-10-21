import csv

import numpy as np
import pytest
from PIL import Image

from pipeline import stage1_heuristics, stage3_vlm
from retrieval.rule_parser import extract_filters, parse
from storage.local import catalog_scope, connect, import_approved


@pytest.fixture
def two_users(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    path = tmp_path / "approved.csv"
    base = {"category": "Chùa", "flag": "approved", "description": "", "slug": "s"}
    rows = [
        {
            **base,
            "username": "a",
            "entity_id": "e1",
            "canonical_name": "Chùa Một Cột",
            "image_url": "https://example.org/1.jpg",
        },
        {
            **base,
            "username": "a",
            "entity_id": "e1",
            "canonical_name": "Chùa Một Cột",
            "image_url": "https://example.org/2.jpg",
        },
        {
            **base,
            "username": "b",
            "entity_id": "e2",
            "canonical_name": "Chùa Hương",
            "image_url": "https://example.org/3.jpg",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_username_scope_imports_only_that_user(two_users):
    scoped = import_approved(two_users, ["a"])
    assert (scoped["images"], scoped["entities"], scoped["out_of_scope_rows"]) == (2, 1, 1)
    assert catalog_scope()["usernames"] == ["a"]
    full = import_approved(two_users)
    # Different scope -> different fingerprint -> a full re-import, never a stale reuse.
    assert full["csv_sha256"] != scoped["csv_sha256"]
    assert full["reused"] is False and full["images"] == 3


def test_username_scope_requires_username_column(two_users, tmp_path):
    bare = tmp_path / "bare.csv"
    with (
        two_users.open(encoding="utf-8") as src,
        bare.open("w", encoding="utf-8", newline="") as dst,
    ):
        rows = list(csv.DictReader(src))
        writer = csv.DictWriter(dst, fieldnames=[k for k in rows[0] if k != "username"])
        writer.writeheader()
        writer.writerows({k: v for k, v in r.items() if k != "username"} for r in rows)
    with pytest.raises(ValueError, match="username"):
        import_approved(bare, ["a"])


def _noise(w=900, h=600, seed=0):
    rng = np.random.default_rng(seed)
    smooth = rng.integers(0, 255, (h // 30, w // 30, 3), dtype=np.uint8)
    return Image.fromarray(smooth).resize((w, h), Image.Resampling.NEAREST)


def test_stage1_rejects_flat_and_blurry_images():
    flat = stage1_heuristics.run(Image.new("RGB", (900, 600), "gray"))
    assert not flat.passed
    assert any(r.startswith("blur") for r in flat.reasons)
    assert any(r.startswith("entropy") for r in flat.reasons)


def test_stage1_passes_natural_image_and_flags_near_duplicate():
    seen: set[int] = set()
    first = stage1_heuristics.run(_noise(), seen_hashes=seen)
    assert first.passed, first.reasons
    dup = stage1_heuristics.run(_noise().resize((880, 590)), seen_hashes=seen)
    assert any(r.startswith("near_duplicate") for r in dup.reasons)


def test_stage1_flags_dense_corner_text():
    img = _noise()
    corner = np.asarray(img).copy()
    corner[:90, :135] = 255
    corner[:90:4, :135] = 0  # tight stripes ~ overlaid text/logo
    flagged = stage1_heuristics.run(Image.fromarray(corner))
    assert any(r.startswith("watermark_zone") for r in flagged.reasons)


def test_stage3_never_accepts_unsafe_scores():
    result = stage3_vlm._validated(
        {
            "relevance": 0.9,
            "watermark": 0.8,
            "nsfw": 0,
            "violence": 0,
            "politics": 0,
            "decision": "accept",
        },
        "m",
    )
    assert result.decision == "reject"
    with pytest.raises(ValueError):
        stage3_vlm._validated({"relevance": 2, "decision": "accept"}, "m")


def test_stage3_majority_vote():
    def r(decision):
        return stage3_vlm.Stage3Result(
            decision, dict.fromkeys(stage3_vlm.SCORE_KEYS, 0.5), decision, "m"
        )

    assert stage3_vlm.voting([r("accept"), r("reject"), r("accept")]).decision == "accept"
    assert stage3_vlm.voting([r("reject"), r("reject"), r("accept")]).decision == "reject"


def test_orientation_filter_ignores_place_names():
    assert extract_filters(parse("Đèo Ngang").normalized) == {}
    assert extract_filters(parse("nhà dọc sông Hương").normalized) == {}
    assert extract_filters(parse("ảnh ngang chùa Một Cột").normalized) == {
        "orientation": "landscape"
    }


def test_search_degrades_when_llm_fails(two_users, monkeypatch):
    from retrieval import llm_router, local_index, local_search
    from retrieval.search import search

    import_approved(two_users)
    monkeypatch.setattr(local_index, "EMBED_DIM", 2)
    monkeypatch.setattr(local_index, "embed_text", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(local_search, "embed_query", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(
        "retrieval.rerank.score_pairs",
        lambda q, c: [0.9 if "Hương" in x["metadata_text"] else 0.1 for x in c],
    )
    local_index.build()
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    def down(*args, **kwargs):
        raise llm_router.LLMError("OpenRouter ConnectError")

    def parse_down(query, candidates):
        raise llm_router.LLMError("OpenRouter ConnectError")

    monkeypatch.setattr(llm_router, "call_json", down)
    monkeypatch.setattr(llm_router, "parse", parse_down)
    monkeypatch.setenv("LLM_PARSE_MODE", "always")  # "Chùa Hương" là tên chính xác (rule high)
    result = search("ảnh ngang Chùa Hương", top_k=2)
    assert result.hits and result.hits[0].entity_id == "e2"
    assert any(w.startswith("llm_parse_failed") for w in result.warnings)
    assert any(w.startswith("llm_rerank_failed") for w in result.warnings)
    assert any("orientation ignored" in w for w in result.warnings)
    with connect() as conn:  # degraded answers are not cached
        assert not conn.execute(
            "SELECT count(*) FROM llm_cache WHERE key LIKE 'search:%'"
        ).fetchone()[0]
    local_index._load.cache_clear()


def test_partial_name_matches_are_interleaved(tmp_path, monkeypatch):
    """'Văn Miếu' must not let the first matching entity fill the whole rerank pool."""
    from retrieval import local_index, local_search
    from retrieval.search import search

    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("RERANK_TOP_K", "4")
    path = tmp_path / "vm.csv"
    base = {"category": "Văn Miếu", "flag": "approved", "description": "", "slug": "s"}
    rows = [
        {
            **base,
            "entity_id": eid,
            "canonical_name": name,
            "image_url": f"https://e.org/{eid}{i}.jpg",
        }
        for eid, name in (("a", "Văn Miếu Huế"), ("b", "Văn Miếu Bắc Ninh"))
        for i in range(6)
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
    result = search("Văn Miếu", top_k=4)
    assert {h.entity_id for h in result.hits} == {"a", "b"}
    local_index._load.cache_clear()
