"""Pipeline /v1/search — DAG tất định, KHÔNG agent, KHÔNG tool-calling loop."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

ANN_TOP_K = 200
SLO_P95_MS = int(os.getenv("SLO_P95_MS", "1500"))
# Tăng khi đổi logic parse/retrieve/rerank: cache /v1/search cũ tự hết hiệu lực.
PIPELINE_VERSION = "b5-relevance-floor"


@dataclass
class SearchHit:
    image_id: str
    image_url: str
    score: float
    entity_id: str | None = None
    entity_slug: str | None = None
    leaf_label: str | None = None
    query_type: str | None = None
    parent_class: str | None = None
    facet_group: str | None = None  # để UI render chip bấm lại được
    description: str | None = None
    matched_subqueries: list[str] = field(default_factory=list)  # sub-query mà ảnh có bằng chứng
    relevance: float | None = (
        None  # điểm gốc cross-encoder (0..1); None khi rerank không hiệu chỉnh
    )
    quality: dict = field(default_factory=dict)  # width/height/verify/watermark; "unknown" khi NULL


@dataclass
class SearchResponse:
    request_id: str
    intent_type: str
    parser: str
    hits: list[SearchHit] = field(default_factory=list)
    facets: dict = field(default_factory=dict)
    timings_ms: dict = field(default_factory=dict)
    total_ms: int = 0
    warnings: list[str] = field(default_factory=list)
    sub_queries: list[dict] = field(default_factory=list)  # id, text, coverage, returned, evidence
    parse_confidence: str | None = None  # high | medium | low
    pipeline_version: str | None = None
    resolution: dict | None = None  # multi-hop: status, seed, steps (có nguồn), target entity ids


def ann_search(vec: list[float], top_k: int = ANN_TOP_K, filters: dict | None = None):
    """Local backend uses exact cosine similarity."""
    from retrieval.local_index import search_vector

    return search_vector(vec, top_k)


def search(
    query: str, top_k: int = 10, filters: dict | None = None, use_cache: bool = True
) -> SearchResponse:
    from retrieval.local_search import run

    return run(query, top_k, filters, use_cache=use_cache)


def build_facets(hits: list[SearchHit]) -> dict:
    """Facet để 'output cũng search được query đấy' — chip bấm lại được trên UI."""
    ent, cls, qt = {}, {}, {}
    for h in hits:
        if h.entity_slug:
            ent[h.entity_slug] = h.leaf_label or h.entity_slug
        if h.parent_class:
            cls[h.parent_class] = cls.get(h.parent_class, 0) + 1
        if h.query_type:
            qt[h.query_type] = qt.get(h.query_type, 0) + 1
    return {"entities": ent, "classes": cls, "query_types": qt}
