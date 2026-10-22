from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Header

from api.schemas import SearchRequest, SearchResponseOut
from retrieval.query_guard import ensure_allowed
from retrieval.search import search as run_search

router = APIRouter()


@router.post("/search", response_model=SearchResponseOut)
def search(req: SearchRequest, cache_control: str | None = Header(None)) -> SearchResponseOut:
    """Pipeline đầy đủ: parse -> (graph) -> embed -> ANN -> filter -> rerank.

    KHÔNG agent, KHÔNG tool-calling loop. Xem docs/retrieval.md.
    """
    ensure_allowed(req.query)  # trước cache/embedding/LLM: truy vấn bị chặn không tốn quota
    # `Cache-Control: no-cache` (load test pha cold): bỏ qua kết quả đã cache, vẫn ghi cache mới.
    fresh = "no-cache" in (cache_control or "").lower()
    res = run_search(req.query, top_k=req.top_k, filters=req.filters, use_cache=not fresh)
    return SearchResponseOut(**asdict(res))
