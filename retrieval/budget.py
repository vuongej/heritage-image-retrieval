"""Hạn chờ tổng của một request /v1/search (SEARCH_DEADLINE_S, mặc định 2,7 s < SLO 3 s).

local_search.run đặt hạn; các lời gọi endpoint (embedding truy vấn, rerank) lấy phần thời gian còn
lại thay vì mỗi tầng một hạn riêng cộng dồn. Hết thời gian thì tầng đó dùng phương án dự phòng
(bỏ nhánh dense / giữ thứ tự RRF) và response mang warning, không bị cache.
Biến ngữ cảnh không tự sang thread khác: submit vào pool qua contextvars.copy_context().run.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_end: ContextVar[float | None] = ContextVar("search_deadline", default=None)


def seconds() -> float:
    return float(os.getenv("SEARCH_DEADLINE_S", "2.7"))


@contextmanager
def request(total: float | None = None) -> Iterator[None]:
    token = _end.set(time.monotonic() + (seconds() if total is None else total))
    try:
        yield
    finally:
        _end.reset(token)


def remaining(cap: float, reserve: float = 0.0) -> float:
    """Thời gian còn được dùng: không quá `cap`, chừa `reserve` cho các tầng sau."""
    end = _end.get()
    if end is None:
        return cap
    return max(0.0, min(cap, end - time.monotonic() - reserve))
