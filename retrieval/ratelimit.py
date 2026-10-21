"""Giới hạn tốc độ phía client cho endpoint embedding/rerank (LiteLLM: 100 request/phút/key).

Embedding (`/v1/embeddings`) và rerank (`/v1/rerank`) dùng chung một key nên dùng chung một cửa
sổ trượt 60 s. Khi đã đủ `EMBED_API_RPM` request trong 60 s gần nhất, lời gọi tiếp theo CHỜ thay
vì gửi đi để nhận HTTP 429 rồi retry. `EMBED_API_RPM=0` tắt giới hạn.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

WINDOW_S = 60.0
_lock = threading.Lock()
_sent: deque[float] = deque()


def rpm() -> int:
    return int(os.getenv("EMBED_API_RPM", "0"))


def acquire(max_wait_s: float = 30.0) -> float:
    """Chờ tới khi được phép gửi 1 request; trả số giây đã chờ. Hết `max_wait_s` thì gửi luôn."""
    limit = rpm()
    if limit <= 0:
        return 0.0
    waited = 0.0
    while True:
        with _lock:
            now = time.monotonic()
            while _sent and now - _sent[0] >= WINDOW_S:
                _sent.popleft()
            if len(_sent) < limit or waited >= max_wait_s:
                _sent.append(now)
                return waited
            delay = WINDOW_S - (now - _sent[0]) + 0.01
        delay = min(delay, max_wait_s - waited)
        time.sleep(max(delay, 0.01))
        waited += max(delay, 0.01)


def reset() -> None:
    with _lock:
        _sent.clear()
