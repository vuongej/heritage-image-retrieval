"""Bất biến V2 (docs/RETRIEVAL_PIPELINE_V2_DATA_DRIVEN_PLAN.md §5.1, §5.4, §7, §11.2)."""

import csv

import pytest

from retrieval import llm_router, speculative
from retrieval.catalog import EntityCatalog
from retrieval.local_search import allocate_fair
from retrieval.query_parser import parse
from storage.local import connect, import_approved


def llm_output(intent, subs):
    return {
        "intent_type": intent,
        "entities": [],
        "sub_queries": subs,
        "hop_chain": [],
        "modifiers": {"place": "", "time": "", "style": ""},
        "cached": False,
    }


CATALOG = EntityCatalog.build(
    [
        ("a", "Chùa Hương"),
        ("b", "Bích Động"),
        ("c", "Văn Miếu Quốc Tử Giám"),
        ("d", "Chợ Bến Thành"),
    ]
)


# ---------------------------------------------------------------- parse guard (§5.1)


def test_confidence_levels():
    assert speculative.confidence(parse("Chùa Hương", CATALOG), CATALOG) == "high"
    assert speculative.confidence(parse("Chùa Hương và Bích Động", CATALOG), CATALOG) == "high"
    assert speculative.confidence(parse("Chùa Hương, Hà Nội", CATALOG), CATALOG) == "high"
    assert speculative.confidence(parse("các đền thờ", CATALOG), CATALOG) == "medium"
    assert speculative.confidence(parse("chùa cổ mái ngói rêu phong", CATALOG), CATALOG) == "low"
    # Hai tên khác nhau ghép lại: không phải một thực thể chắc chắn.
    assert speculative.confidence(parse("Chùa Hương Bích Động", CATALOG), CATALOG) == "low"


def test_ambiguous_only_skips_llm_for_confident_rule(monkeypatch):
    monkeypatch.delenv("LLM_PARSE_MODE", raising=False)
    assert not speculative.should_call("high")
    assert speculative.should_call("medium") and speculative.should_call("low")
    monkeypatch.setenv("LLM_PARSE_MODE", "off")
    assert not speculative.should_call("low")
    monkeypatch.setenv("LLM_PARSE_MODE", "always")
    assert speculative.should_call("high")


def test_llm_cannot_override_confident_rule(monkeypatch):
    monkeypatch.delenv("LLM_PARSE_CAN_OVERRIDE_CONFIDENT_RULE", raising=False)
    rule = parse("Chùa Hương và Bích Động", CATALOG)
    parsed, action = speculative.decide(rule, llm_output("single", ["chùa hương"]), "high")
    assert parsed is rule and action == "guard_confident_rule"


def test_llm_cannot_turn_set_query_into_single():
    rule = parse("các chợ truyền thống", CATALOG)
    parsed, action = speculative.decide(rule, llm_output("single", ["chợ truyền thống"]), "medium")
    assert parsed is rule and action == "guard_set_to_single"


def test_llm_may_split_ambiguous_query():
    rule = parse("Chùa Hương Bích Động", CATALOG)
    parsed, action = speculative.decide(
        rule, llm_output("multi_intent", ["Chùa Hương", "Bích Động"]), "low"
    )
    assert parsed["intent_type"] == "multi_intent" and action == "llm_intent"


# ---------------------------------------------------------------- allocator (§5.4)


def test_fair_allocation_never_exceeds_top_k_or_invents_items():
    assert allocate_fair([["a1", "a2", "a3"], ["b1"]], 10) == ["a1", "b1", "a2", "a3"]
    assert allocate_fair([["a1", "a2"], ["b1", "b2"], ["c1"], ["d1"]], 3) == ["a1", "b1", "c1"]
    assert allocate_fair([["x", "a"], ["x", "b"]], 4) == [
        "x",
        "b",
        "a",
    ]  # không trùng ảnh, B không mất lượt
    assert allocate_fair([[], []], 5) == []


# ---------------------------------------------------------------- end-to-end trên catalog nhỏ


@pytest.fixture
def index(tmp_path, monkeypatch):
    from retrieval import local_index, local_search

    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("LLM_PARSE_MODE", "off")
    rows = [("a", "Chùa Hương", 12), ("b", "Bích Động", 3), ("c", "Văn Miếu Quốc Tử Giám", 4)]
    path = tmp_path / "a.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, ["entity_id", "canonical_name", "slug", "category", "image_url", "flag"]
        )
        writer.writeheader()
        for eid, name, n in rows:
            for i in range(n):
                writer.writerow(
                    {"entity_id": eid, "canonical_name": name, "slug": eid, "category": "Di tích",
                     "image_url": f"https://e.org/{eid}{i}.jpg", "flag": "approved"}
                )  # fmt: skip
    import_approved(path)
    monkeypatch.setattr(local_index, "EMBED_DIM", 2)
    monkeypatch.setattr(local_index, "embed_text", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(local_search, "embed_query", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr("retrieval.rerank.score_pairs", lambda q, c: [0.5] * len(c))
    local_index.build()
    yield
    local_index._load.cache_clear()


def test_exact_name_returns_full_topk_if_enough_images(index):
    from retrieval.search import search

    result = search("Chùa Hương", top_k=10)
    assert len(result.hits) == 10 and {h.entity_id for h in result.hits} == {"a"}  # không cap 3


def test_multi_intent_has_no_hallucinated_fill(index):
    from retrieval.search import search

    result = search("Bích Động và Văn Miếu Quốc Tử Giám", top_k=10)
    assert result.intent_type == "multi_intent"
    assert {h.entity_id for h in result.hits} == {"b", "c"}  # không lấp bằng Chùa Hương
    assert len(result.hits) == 7  # 3 + 4: đủ những gì có, không ép đủ 10
    assert [s["coverage"] for s in result.sub_queries] == ["covered", "covered"]
    assert all(h.matched_subqueries for h in result.hits)


def test_multi_intent_top_k_below_subquery_count(index):
    from retrieval.search import search

    result = search("Bích Động và Văn Miếu Quốc Tử Giám", top_k=1)
    assert len(result.hits) == 1
    assert any("not every intent" in w for w in result.warnings)


def test_missing_quality_is_unknown(index):
    from retrieval.search import search

    hit = search("Chùa Hương", top_k=1).hits[0]
    assert hit.quality["verify"] == "unknown" and hit.quality["watermark"] == "unknown"
    assert hit.quality["width"] is None and hit.quality["pixel_checked"] is False


def test_quality_penalty_reads_has_watermark_and_ignores_unknown():
    from retrieval.rerank import PENALTY_WATERMARK, apply_quality_penalty

    assert apply_quality_penalty({"has_watermark": 1}) == PENALTY_WATERMARK
    assert apply_quality_penalty({"has_watermark": None, "verify": None, "width": None}) == 0
    assert apply_quality_penalty({"watermark": 0.9}) == 0  # khoá cũ sai tên không còn được đọc


def test_cache_key_changes_with_parse_policy(index, monkeypatch):
    from retrieval.search import search

    search("Chùa Hương", top_k=2)
    monkeypatch.setattr(speculative, "POLICY_VERSION", "other")
    search("Chùa Hương", top_k=2)
    with connect() as conn:
        assert (
            conn.execute("SELECT count(*) FROM llm_cache WHERE key LIKE 'search:%'").fetchone()[0]
            == 2
        )


def test_indexed_image_count_reports_shortfall(tmp_path, monkeypatch):
    from scripts.check_index_counts import check

    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("VECTOR_BACKEND", "numpy")
    path = tmp_path / "a.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, ["entity_id", "canonical_name", "slug", "category", "image_url", "flag"]
        )
        writer.writeheader()
        for url in ["https://e.org/1.jpg", "x-raw-image:///abc"]:
            writer.writerow(
                {"entity_id": "e", "canonical_name": "Chùa", "slug": "s", "category": "c",
                 "image_url": url, "flag": "approved"}
            )  # fmt: skip
    import_approved(path)
    report = check(path, require=2)
    assert report["csv_rows"] == 2 and report["sqlite_images"] == 1
    assert not report["ok"] and report["quarantine"][0]["reason"] == "non_http_scheme"


def test_llm_router_disabled_in_tests():
    assert not llm_router.enabled()


def test_entity_first_keeps_exact_entity_above_reranker_preference(tmp_path, monkeypatch):
    """Reranker thích thực thể gần tên hơn, nhưng truy vấn neo chắc vào tên -> thực thể đúng trước."""
    from retrieval import local_index, local_search
    from retrieval.search import search

    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("LLM_PARSE_MODE", "off")
    path = tmp_path / "a.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, ["entity_id", "canonical_name", "slug", "category", "image_url", "flag"]
        )
        writer.writeheader()
        for eid, name in (("near", "Chùa Hương Tích"), ("exact", "Chùa Hương")):
            for i in range(3):
                writer.writerow(
                    {"entity_id": eid, "canonical_name": name, "slug": eid, "category": "Chùa",
                     "image_url": f"https://e.org/{eid}{i}.jpg", "flag": "approved"}
                )  # fmt: skip
    import_approved(path)
    monkeypatch.setattr(local_index, "EMBED_DIM", 2)
    monkeypatch.setattr(local_index, "embed_text", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(local_search, "embed_query", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(
        "retrieval.rerank.score_pairs",
        lambda q, c: [0.9 if "Tích" in x["metadata_text"] else 0.1 for x in c],
    )
    local_index.build()
    result = search("Chùa Hương", top_k=6)
    assert result.parse_confidence == "high"
    assert [h.entity_id for h in result.hits[:3]] == ["exact"] * 3
    local_index._load.cache_clear()


def test_place_inside_entity_name_is_not_shared_modifier():
    catalog = EntityCatalog.build([("m", "Chùa Một Cột"), ("l", "Lăng Chủ tịch Hồ Chí Minh")])
    parsed = parse("Chùa Một Cột và Lăng Chủ tịch Hồ Chí Minh", catalog)
    assert [s["text"] for s in parsed["sub_queries"]] == [
        "chùa một cột",
        "lăng chủ tịch hồ chí minh",
    ]
    assert speculative.confidence(parsed, catalog) == "high"
    # Địa danh thật ở cuối vẫn áp cho mọi ý.
    parsed = parse("chùa và nhà thờ ở Huế", catalog)
    assert [s["text"] for s in parsed["sub_queries"]] == ["chùa ở huế", "nhà thờ ở huế"]


def test_human_verified_image_is_not_penalised_for_watermark():
    from retrieval.rerank import PENALTY_WATERMARK, apply_quality_penalty

    assert (
        apply_quality_penalty({"has_watermark": 1, "verify": "yes", "verify_source": "human"}) == 0
    )
    assert (
        apply_quality_penalty({"has_watermark": 1, "verify_source": "vlm_pilot"})
        == PENALTY_WATERMARK
    )
