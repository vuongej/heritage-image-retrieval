"""S1a — download once, real sha256, 512px thumbnail cache, retry_later (skill_01 #5, skill_02).

Raw bytes are hashed and discarded: only a 512px JPEG is kept (enough for the encoder
at 256px and for the VLM at 512px), so 77k images need ~4 GB instead of ~15.6 GB.
A failed download is never a final "no" on the first try: it is retried in later
rounds with backoff, and only marked dead after MAX_ATTEMPTS.
"""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from pipeline.verify.common import read_jsonl, row_key, run_dir, write_jsonl
from storage.images import FetchError, decode, fetch_image

THUMB_SIDE = 512
MIN_W, MIN_H = 300, 200
MAX_ATTEMPTS = 3
BACKOFF_S = (0, 20, 90)


def thumb_path(key: str) -> Path:
    return run_dir() / "thumbs" / key[:2] / f"{key}.jpg"


def _fetch_one(row: dict) -> dict:
    key = row_key(row)
    started = time.perf_counter()
    try:
        data = fetch_image(row["image_url"], timeout=25)
        img = decode(data)
    except FetchError as exc:
        return {"key": key, "status": "error", "error": str(exc)}
    except Exception as exc:  # decoder edge cases (truncated, exotic modes)
        return {"key": key, "status": "error", "error": f"{type(exc).__name__}"}
    w, h = img.size
    record = {
        "key": key,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "format": img.format,
        "w": w,
        "h": h,
        "ms": round((time.perf_counter() - started) * 1000),
    }
    if w < MIN_W or h < MIN_H:
        return {**record, "status": "too_small"}  # R3_too_small_actual: no forward, no API
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.Resampling.LANCZOS)
    path = thumb_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=88, optimize=True)
    path.write_bytes(buf.getvalue())
    return {**record, "status": "ok"}


def run(rows: list[dict], workers: int = 32, log=print) -> dict[str, dict]:
    """Resumable: rows already ok/too_small/dead in fetch.jsonl are not downloaded again."""
    manifest = run_dir() / "fetch.jsonl"
    state = {r["key"]: r for r in read_jsonl(manifest)}
    started = time.perf_counter()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        todo = [
            r
            for r in rows
            if state.get(row_key(r), {}).get("status") in (None, "retry_later")
            and state.get(row_key(r), {}).get("attempts", 0) < attempt
        ]
        if not todo:
            continue
        if attempt > 1:
            log(f"[fetch] retry round {attempt}: {len(todo)} rows after {BACKOFF_S[attempt - 1]}s")
            time.sleep(BACKOFF_S[attempt - 1])
        done = 0
        with ThreadPoolExecutor(workers) as pool:
            for result in pool.map(_fetch_one, todo):
                prev = state.get(result["key"], {})
                if result["status"] == "error":
                    result["status"] = "dead" if attempt >= MAX_ATTEMPTS else "retry_later"
                    result["errors"] = [*prev.get("errors", []), result.pop("error")]
                result["attempts"] = attempt
                state[result["key"]] = result
                done += 1
                if done % 500 == 0:
                    log(f"[fetch] round {attempt}: {done}/{len(todo)}")
                    write_jsonl(manifest, state.values())
        write_jsonl(manifest, state.values())
    log(f"[fetch] done in {time.perf_counter() - started:.1f}s")
    return state


def mark_sha_duplicates(rows: list[dict], state: dict[str, dict]) -> int:
    """R6 on real content: identical bytes inside one entity keep only the first row."""
    seen: set[tuple[str, str]] = set()
    dups = 0
    for row in rows:
        rec = state.get(row_key(row))
        if not rec or rec["status"] != "ok":
            continue
        k = (row["entity_id"], rec["sha256"])
        if k in seen:
            rec["status"] = "dup_sha256"
            dups += 1
        else:
            seen.add(k)
    return dups
