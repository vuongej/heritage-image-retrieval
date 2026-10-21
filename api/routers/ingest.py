from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("/ingest")
def ingest(payload: dict) -> dict:
    """Nạp batch ảnh mới: bronze/raw -> Stage1-3 -> gold/ + index incremental."""
    raise RuntimeError(
        "Local approved-CSV mode: import with python -m pipeline --csv <path> --mode approved"
    )


@router.get("/ingest/status")
def ingest_status(job_id: str | None = None) -> dict:
    from storage.local import counts

    return {"job_id": job_id, "state": "local_catalog", "processed": counts()["images"]}
