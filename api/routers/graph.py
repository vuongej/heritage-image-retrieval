from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/graph")
def get_graph(entity_id: str | None = None, relation: str = "IN_CLASS") -> dict:
    from retrieval.graph import parents_of, siblings_of

    return {
        "entity_id": entity_id,
        "relation": relation,
        "parents": parents_of(entity_id, relation) if entity_id else [],
        "neighbors": siblings_of(entity_id, relation) if entity_id else [],
    }


@router.post("/graph")
def rebuild_graph(incremental: bool = True) -> dict:
    """Rebuild graph. Ngân sách: < 5 s (đo bằng graph.build_from_csv)."""
    from retrieval.graph import BUILD_BUDGET_S, build_from_csv
    from storage.local import catalog_scope

    # Edges come from the imported (possibly username-scoped) catalog, not a fixed CSV path.
    from storage.runtime import source_csv

    stats = build_from_csv(catalog_scope()["source_csv"] or source_csv())
    return {
        "n_nodes": stats.n_nodes,
        "n_edges": stats.n_edges,
        "build_seconds": stats.build_seconds,
        "budget_s": BUILD_BUDGET_S,
        "within_budget": stats.within_budget,
        "incremental": incremental,
    }
