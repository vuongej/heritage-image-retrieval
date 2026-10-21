"""Cổng liên quan: không trả ảnh "gần nhất" cho truy vấn ngoài phạm vi (scripts/calibrate_relevance.py)."""

from retrieval import local_search
from retrieval.rerank import RerankHit


def _hit(image_id, relevance):
    return RerankHit(image_id, relevance or 0.0, "local_cross_encoder_rerank", relevance=relevance)


def test_floor_drops_low_relevance_but_keeps_entity_name_matches(monkeypatch):
    monkeypatch.setenv("RERANK_MIN_RELEVANCE", "0.2")
    entity = {"a": "e1", "b": "e2", "c": "e3"}.get
    exempt = {"e2"}
    assert local_search._passes(_hit("a", 0.9), exempt, entity)
    assert local_search._passes(_hit("b", 0.001), exempt, entity)  # khớp đúng tên thực thể
    assert not local_search._passes(_hit("c", 0.05), exempt, entity)


def test_uncalibrated_scores_and_disabled_floor_pass(monkeypatch):
    monkeypatch.setenv("RERANK_MIN_RELEVANCE", "0.2")
    assert local_search._passes(RerankHit("x", 0.01, "fusion_order"), set(), lambda _: None)
    monkeypatch.setenv("RERANK_MIN_RELEVANCE", "0")
    assert local_search._passes(_hit("x", 0.0), set(), lambda _: None)


def test_default_floor_is_the_calibrated_value(monkeypatch):
    monkeypatch.delenv("RERANK_MIN_RELEVANCE", raising=False)
    assert local_search.min_relevance() == 0.2
