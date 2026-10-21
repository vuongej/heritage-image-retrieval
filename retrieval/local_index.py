"""Resumable exact cosine index over all approved image metadata."""

from __future__ import annotations

import json
import os
import time
from functools import lru_cache

import numpy as np

from retrieval.embed import EMBED_BACKEND, EMBED_DIM, EMBED_MAX_SEQ, EMBED_MODEL, embed_text
from storage.local import connect
from storage.runtime import data_dir

# Định dạng vectors.npy + index.json. Tăng khi đổi schema index (Phase 2).
INDEX_VERSION = 1


def manifest() -> dict:
    path = data_dir() / "index.json"
    if not path.exists():
        return {}
    state = json.loads(path.read_text(encoding="utf-8"))
    # Initial local checkpoints predate the optional ONNX backend and are all torch.
    state.setdefault("backend", "torch")
    state.setdefault("index_version", 1)
    return state


def build() -> dict:
    started = time.perf_counter()
    with connect() as conn:
        count = conn.execute("SELECT count(*) FROM images").fetchone()[0]
        row = conn.execute("SELECT value FROM metadata WHERE key='csv_sha256'").fetchone()
    if not count or row is None:
        raise RuntimeError("Import the approved CSV before building its index")
    identity = {
        "count": count,
        "csv_sha256": row[0],
        "model": EMBED_MODEL,
        "dim": EMBED_DIM,
        "embedding_source": "approved_csv_metadata",
        "max_seq_length": EMBED_MAX_SEQ,
        "backend": EMBED_BACKEND,
        "index_version": INDEX_VERSION,
    }
    old = manifest()
    reusable = all(old.get(k) == v for k, v in identity.items())
    path = data_dir() / "vectors.npy"
    if reusable and old.get("complete") and path.exists():
        return {**old, "reused": True}
    start = int(old.get("indexed_count", 0)) if reusable and path.exists() else 0
    vectors = np.lib.format.open_memmap(
        path, mode="r+" if start else "w+", dtype="float32", shape=(count, EMBED_DIM)
    )
    # Identical metadata has identical semantic input; encode it only once without
    # merging image identities or omitting any image from the resulting index.
    known: dict[str, int] = {}
    with connect() as conn:
        for item in conn.execute(
            "SELECT rownum, metadata_text FROM images WHERE rownum<=? ORDER BY rownum", (start,)
        ):
            known.setdefault(item[1], item[0] - 1)
    for begin in range(start, count, int(os.getenv("INDEX_CHUNK_SIZE", "512"))):
        with connect() as conn:
            rows = conn.execute(
                "SELECT metadata_text FROM images WHERE rownum>? ORDER BY rownum LIMIT ?",
                (begin, min(int(os.getenv("INDEX_CHUNK_SIZE", "512")), count - begin)),
            ).fetchall()
        new_texts, positions, duplicates = [], [], []
        for offset, item in enumerate(rows):
            position = begin + offset
            if item[0] in known:
                duplicates.append((position, known[item[0]]))
            else:
                known[item[0]] = position
                positions.append(position)
                new_texts.append(item[0])
        if new_texts:
            encoded = np.asarray(embed_text(new_texts), dtype="float32")
            if encoded.shape != (len(new_texts), EMBED_DIM) or not np.isfinite(encoded).all():
                raise ValueError("Invalid embedding batch; checkpoint was not advanced")
            vectors[positions] = encoded
        for position, source in duplicates:
            vectors[position] = vectors[source]
        end = begin + len(rows)
        vectors.flush()
        state = {
            **identity,
            "indexed_count": end,
            "complete": end == count,
            "unique_metadata_seen": len(known),
            "build_seconds": round(time.perf_counter() - started, 3),
        }
        temp = data_dir() / "index.json.tmp"
        temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temp.replace(data_dir() / "index.json")
        print(
            f"[index] {end:,}/{count:,} ({end / count:.1%}) | {state['build_seconds']:.1f}s",
            flush=True,
        )
    del vectors
    _load.cache_clear()
    return manifest()


@lru_cache(maxsize=1)
def _load(stamp: int):
    state = manifest()
    if not state.get("complete"):
        raise RuntimeError("Local index is incomplete; run python -m pipeline first")
    if (
        state.get("model") != EMBED_MODEL
        or state.get("dim") != EMBED_DIM
        or state.get("backend") != EMBED_BACKEND
    ):
        raise RuntimeError("Index/model mismatch; rebuild the index")
    with connect() as conn:
        digest = conn.execute("SELECT value FROM metadata WHERE key='csv_sha256'").fetchone()
    if not digest or digest[0] != state["csv_sha256"]:
        raise RuntimeError("Catalog changed; rebuild the index")
    return np.load(data_dir() / "vectors.npy", mmap_mode="r")


def search_vector(vec: list[float], top_k: int = 100) -> list[tuple[int, float]]:
    if top_k <= 0:
        return []
    path = data_dir() / "index.json"
    if not path.exists():
        raise RuntimeError("No local index; run python -m pipeline first")
    vectors = _load(path.stat().st_mtime_ns)
    query = np.asarray(vec, dtype="float32")
    if query.shape != (EMBED_DIM,) or not np.isfinite(query).all():
        raise ValueError("Invalid query vector")
    scores = vectors @ query
    count = min(top_k, len(scores))
    indices = np.argpartition(-scores, count - 1)[:count]
    indices = indices[np.argsort(-scores[indices], kind="stable")]
    return [(int(i) + 1, float(scores[i])) for i in indices]
