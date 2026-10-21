from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

MIN_IMAGES_PER_ENTITY = 5


@router.post("/backfill")
def run_backfill(limit: int = 0) -> dict:
    """Đẩy entity thiếu ảnh vào queue bổ sung.

    Từ CSV nhóm 1: 242 entity 0 ảnh + 478 entity dưới 5 ảnh.
    """
    from retrieval.backfill import plan_from_db

    _ = plan_from_db  # TODO(impl): cắm DB connection thật
    return {
        "queued": 0,
        "limit": limit,
        "known_zero_images": 242,
        "known_under_5": 478,
        "source": "bo_sung_anh_cho_entities_nhom_1_Vuong_ent1-500.csv",
    }


@router.get("/backfill/status")
def backfill_status() -> dict:
    return {"pending": 0, "done": 0, "zero_images": 242, "under_5": 478}
