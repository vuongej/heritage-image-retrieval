"""Backfill — đúng yêu cầu 'bổ sung thêm'.

Từ CSV thật: 242 entity 0 ảnh + 478 entity dưới 5 ảnh.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_IMAGES_PER_ENTITY = 5


@dataclass
class BackfillItem:
    entity_id: str
    entity_name: str
    n_current: int
    need: int
    reason: str
    priority: str


def plan_from_db(conn) -> list[BackfillItem]:
    """TODO(impl):
    SELECT e.entity_id, e.entity_name, e.so_anh_pass, e.priority
    FROM entities e WHERE e.so_anh_pass < %s ORDER BY e.priority, e.so_anh_pass
    """
    raise NotImplementedError


def enqueue(items: list[BackfillItem], redis) -> int:
    """TODO(impl): XADD backfill_stream, mỗi item 1 message."""
    raise NotImplementedError
