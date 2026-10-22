"""Giới hạn tốc độ phía client cho endpoint embedding/rerank (LiteLLM: 100 request/phút/key).

Embedding (`/v1/embeddings`) và rerank (`/v1/rerank`) dùng chung một key nên dùng chung một cửa
sổ trượt 60 s. Khi đã đủ `EMBED_API_RPM` request trong 60 s gần nhất, lời gọi tiếp theo CHỜ thay
vì gửi đi để nhận HTTP 429 rồi retry. `EMBED_API_RPM=0` tắt giới hạn.

Đường truy vấn đặt hạn chờ bằng `with deadline(s):` — hết hạn mà chưa có slot thì raise
QuotaExhausted ngay (caller dùng phương án dự phòng), không chờ 30 s như khi dựng index.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

WINDOW_S = 60.0
_lock = threading.Lock()
_sent: deque[float] = deque()
_deadline: ContextVar[float | None] = ContextVar("ratelimit_deadline", default=None)


class QuotaExhausted(RuntimeError):
    """Hết hạn mức endpoint trong hạn chờ của request."""


@contextmanager
def deadline(seconds: float) -> Iterator[None]:
    token = _deadline.set(time.monotonic() + max(0.0, seconds))
    try:
        yield
    finally:
        _deadline.reset(token)


def rpm() -> int:
    return int(os.getenv("EMBED_API_RPM", "0"))


def acquire(max_wait_s: float = 30.0) -> float:
    """Chờ tới khi được phép gửi 1 request; trả số giây đã chờ.

    Không có hạn chờ: hết `max_wait_s` thì gửi luôn. Trong `deadline(...)`: hết hạn -> QuotaExhausted.
    """
    limit = rpm()
    if limit <= 0:
        return 0.0
    end = _deadline.get()
    strict = end is not None
    if strict:
        max_wait_s = max(0.0, min(max_wait_s, end - time.monotonic()))
    waited = 0.0
    while True:
        with _lock:
            now = time.monotonic()
            while _sent and now - _sent[0] >= WINDOW_S:
                _sent.popleft()
            if len(_sent) < limit:
                _sent.append(now)
                return waited
            if waited >= max_wait_s:
                if strict:
                    raise QuotaExhausted(f"hết hạn mức {limit} request/phút của endpoint")
                _sent.append(now)
                return waited
            delay = WINDOW_S - (now - _sent[0]) + 0.01
            if strict and delay > max_wait_s - waited:  # slot kế tiếp đến sau hạn: báo ngay
                raise QuotaExhausted(f"hết hạn mức {limit} request/phút của endpoint")
        delay = min(delay, max_wait_s - waited)
        time.sleep(max(delay, 0.01))
        waited += max(delay, 0.01)


def reset() -> None:
    with _lock:
        _sent.clear()
