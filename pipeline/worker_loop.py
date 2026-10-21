"""Worker: đọc job từ queue -> Stage1 -> Stage2 -> (Stage3) -> gold + index."""

from __future__ import annotations

import logging
import os
import time

log = logging.getLogger("worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def process_one(job: dict) -> dict:
    """TODO(impl):
    1. tải bytes từ S3 bronze/
    2. Stage 1 (CPU)  -> fail: ghi silver/verdict=reject/stage=1
    3. Stage 2 (GPU)  -> accept/reject/uncertain
    4. uncertain & Stage 3 bật -> VLM; tắt -> human review queue
    5. accept -> gold/ + add vector vào Qdrant + upsert manifest
    """
    raise NotImplementedError


def run_forever() -> None:
    provider = os.getenv("LLM_PROVIDER", "none").lower()
    log.info(
        "worker khởi động | LLM_PROVIDER=%s | stage3=%s", provider, provider in {"gemini", "local"}
    )
    while True:
        try:
            # TODO(impl): pop job từ Redis stream
            time.sleep(1)
        except KeyboardInterrupt:
            log.info("dừng worker")
            break


if __name__ == "__main__":
    run_forever()
