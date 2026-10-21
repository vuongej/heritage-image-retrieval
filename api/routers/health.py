from __future__ import annotations

import os

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    from pipeline.stage3_vlm import enabled
    from retrieval import llm_router, vector_store
    from retrieval import rerank as reranking
    from retrieval.local_index import manifest
    from storage.local import catalog_scope, counts

    state = manifest()
    return {
        "status": "ok",
        "llm_provider": os.getenv("LLM_PROVIDER", "none"),
        "stage3_vlm_enabled": enabled(),
        "slo_p95_ms": int(os.getenv("SLO_P95_MS", "1500")),
        "version": "0.1.0",
        "backend": f"local_sqlite + {vector_store.backend()}",
        "catalog": counts(),
        "catalog_scope": catalog_scope(),
        "index_complete": bool(state.get("complete")),
        "embedding_source": "approved_csv_metadata",
        # Model thật của index đang phục vụ (đọc từ manifest, không phải từ .env).
        "embedding": {
            "model": state.get("model"),
            "dim": state.get("dim"),
            "backend": state.get("backend"),
        },
        "visual_index": vector_store.has_visual(),
        "parse_llm": llm_router.model() if llm_router.enabled() else None,
        "rerank": reranking.model_name(),
        "rerank_backend": reranking.backend(),
    }
