from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter

from api.schemas import SearchRequest, SearchResponseOut
from retrieval.search import search as run_search

router = APIRouter()


@router.post("/search", response_model=SearchResponseOut)
def search(req: SearchRequest) -> SearchResponseOut:
    """Pipeline đầy đủ: parse -> (graph) -> embed -> ANN -> filter -> rerank.

    KHÔNG agent, KHÔNG tool-calling loop. Xem docs/retrieval.md.
    """
    res = run_search(req.query, top_k=req.top_k, filters=req.filters)
    return SearchResponseOut(**asdict(res))
