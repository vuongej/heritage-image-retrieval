"""Query understanding — rule parser (luôn chạy, entity-first) + bộ lọc.

LLM không được gọi ở đây: nó chạy song song có timeout trong retrieval/speculative.py
(Gemini 3.5 Flash Lite qua OpenRouter, retrieval/llm_router.py).
"""

from __future__ import annotations

from retrieval import rule_parser
from retrieval.catalog import EntityCatalog


def parse(query: str, catalog: EntityCatalog | None = None) -> dict:
    """Kết quả rule-based ngay (vài ms), kèm filter nhận diện từ câu truy vấn."""
    base = rule_parser.parse(query, catalog)
    base.filters.update(rule_parser.extract_filters(base.normalized))
    return base.to_dict()
