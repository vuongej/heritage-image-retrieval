from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/entities")
def list_entities(
    q: str | None = None,
    branch: str | None = None,
    priority: str | None = None,
    limit: int = Query(50, le=500),
) -> dict:
    from storage.local import connect

    if branch or priority:
        raise ValueError("Approved CSV does not contain branch or priority")
    if limit < 1:
        raise ValueError("limit must be positive")
    with connect() as conn:
        predicate = "WHERE entity_name LIKE ?" if q else ""
        params = [f"%{q}%"] if q else []
        total = conn.execute(f"SELECT count(*) FROM entities {predicate}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM entities {predicate} ORDER BY entity_name LIMIT ?", [*params, limit]
        )
        return {"items": [dict(r) for r in rows], "total": total, "filters": {"q": q}}
