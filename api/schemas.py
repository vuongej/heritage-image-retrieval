from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, examples=["Quần thể Tràng An"])
    top_k: int = Field(10, ge=1, le=100)
    filters: dict | None = None


class SearchHitOut(BaseModel):
    image_id: str
    image_url: str
    score: float
    entity_id: str | None = None
    entity_slug: str | None = None
    leaf_label: str | None = None
    query_type: str | None = None
    parent_class: str | None = None
    description: str | None = None
    matched_subqueries: list[str] = Field(default_factory=list)
    relevance: float | None = None
    quality: dict = Field(default_factory=dict)


class SearchResponseOut(BaseModel):
    request_id: str
    intent_type: str
    parser: str
    hits: list[SearchHitOut]
    facets: dict
    timings_ms: dict
    total_ms: int
    warnings: list[str] = Field(default_factory=list)
    sub_queries: list[dict] = Field(default_factory=list)
    parse_confidence: str | None = None
    pipeline_version: str | None = None
    resolution: dict | None = None


class EmbedRequest(BaseModel):
    texts: list[str] | None = None
    image_urls: list[str] | None = None


class EmbedResponseOut(BaseModel):
    model: str
    dim: int
    vectors: list[list[float]]
    latency_ms: int


class RerankRequest(BaseModel):
    query: str
    candidates: list[dict]
    keep: int = Field(10, ge=1, le=100)


class RerankResponseOut(BaseModel):
    hits: list[dict]
    latency_ms: int
