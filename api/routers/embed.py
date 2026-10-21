from __future__ import annotations

import time

from fastapi import APIRouter

from api.schemas import EmbedRequest, EmbedResponseOut
from retrieval.embed import EMBED_DIM, EMBED_MODEL, embed_images, embed_text
from retrieval.query_guard import ensure_allowed

router = APIRouter()


@router.post("/embed", response_model=EmbedResponseOut)
def embed(req: EmbedRequest) -> EmbedResponseOut:
    """CHỈ embedding. Tách riêng để auto test đo chất lượng embed độc lập với rerank."""
    ensure_allowed(*(req.texts or []))
    t0 = time.perf_counter()
    vectors: list[list[float]] = []
    if req.texts:
        vectors += embed_text(req.texts)
    if req.image_urls:
        from storage.images import FetchError

        try:
            vectors += embed_images(req.image_urls)
        except FetchError as exc:
            raise ValueError(f"Could not fetch image: {exc}") from None
    return EmbedResponseOut(
        model=EMBED_MODEL,
        dim=EMBED_DIM,
        vectors=vectors,
        latency_ms=int((time.perf_counter() - t0) * 1000),
    )
