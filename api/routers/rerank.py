from __future__ import annotations

import time

from fastapi import APIRouter

from api.schemas import RerankRequest, RerankResponseOut
from retrieval.rerank import rerank as run_rerank

router = APIRouter()


@router.post("/rerank", response_model=RerankResponseOut)
def rerank(req: RerankRequest) -> RerankResponseOut:
    """CHỈ rerank. Không LLM, không agent."""
    t0 = time.perf_counter()
    hits = run_rerank(req.query, req.candidates, keep=req.keep)
    return RerankResponseOut(
        hits=[h.__dict__ for h in hits],
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )
