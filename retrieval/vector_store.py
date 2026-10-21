"""Hai collection vector (Phase 2.3): `img_text` (MiniLM 384d) và `img_visual` (SigLIP2 768d).

Backend `VECTOR_BACKEND`:
- `qdrant` — HNSW m=16, ef_construct=128, tìm với ef=128 (QDRANT_URL);
- `numpy`  — cosine chính xác trên file .npy (fallback khi không có Qdrant; test offline).

Point id = rownum của bảng images. `img_visual` chỉ chứa ảnh có vector thật (tải + encode được):
không bao giờ có vector rỗng/NULL lẫn trong collection.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

import numpy as np

from storage.runtime import data_dir

TEXT = "img_text"
VISUAL = "img_visual"
HNSW_M = 16
HNSW_EF_CONSTRUCT = 128
SEARCH_EF = int(os.getenv("QDRANT_SEARCH_EF", "128"))


def backend() -> str:
    return os.getenv("VECTOR_BACKEND", "numpy").lower()


@lru_cache(maxsize=1)
def client():
    from qdrant_client import QdrantClient

    return QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"), timeout=10)


def visual_manifest() -> dict:
    path = data_dir() / "visual_index.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@lru_cache(maxsize=2)
def _visual_arrays(stamp: int):
    rows = np.load(data_dir() / "visual_rows.npy")
    vectors = np.load(data_dir() / "visual.npy", mmap_mode="r")
    return rows, vectors


def has_visual() -> bool:
    return bool(visual_manifest().get("complete"))


def search(collection: str, vector, top_k: int = 200) -> list[tuple[int, float]]:
    """[(rownum, cosine)] giảm dần."""
    if top_k <= 0:
        return []
    if backend() == "qdrant":
        from qdrant_client import models

        points = (
            client()
            .query_points(
                collection,
                query=list(map(float, vector)),
                limit=top_k,
                search_params=models.SearchParams(hnsw_ef=max(SEARCH_EF, top_k)),
                with_payload=False,
            )
            .points
        )
        return [(int(p.id), float(p.score)) for p in points]
    if collection == TEXT:
        from retrieval.local_index import search_vector

        return search_vector(vector, top_k)
    path = data_dir() / "visual.npy"
    rows, vectors = _visual_arrays(path.stat().st_mtime_ns)
    scores = vectors @ np.asarray(vector, dtype=vectors.dtype)
    count = min(top_k, len(scores))
    idx = np.argpartition(-scores, count - 1)[:count]
    idx = idx[np.argsort(-scores[idx], kind="stable")]
    return [(int(rows[i]), float(scores[i])) for i in idx]


def recreate(collection: str, dim: int) -> None:
    from qdrant_client import models

    c = client()
    if c.collection_exists(collection):
        c.delete_collection(collection)
    c.create_collection(
        collection,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        hnsw_config=models.HnswConfigDiff(m=HNSW_M, ef_construct=HNSW_EF_CONSTRUCT),
    )


def upload(collection: str, ids: np.ndarray, vectors: np.ndarray, batch: int = 1024, log=print):
    """Ghi lại toàn bộ collection từ mảng (ids = rownum)."""
    if len(ids) != len(vectors) or not np.isfinite(vectors).all():
        raise ValueError(f"{collection}: ids/vectors lệch hoặc có giá trị không hữu hạn")
    recreate(collection, vectors.shape[1])
    c = client()
    for start in range(0, len(ids), batch):
        c.upload_collection(
            collection,
            vectors=np.asarray(vectors[start : start + batch], dtype=np.float32),
            ids=[int(i) for i in ids[start : start + batch]],
            wait=True,
        )
        if (start // batch) % 20 == 0:
            log(f"[qdrant] {collection} {min(start + batch, len(ids)):,}/{len(ids):,}")
    count = c.count(collection, exact=True).count
    if count != len(ids):
        raise RuntimeError(f"{collection}: Qdrant có {count} điểm, cần {len(ids)}")
    return count


def self_test(
    collection: str, ids: np.ndarray, vectors: np.ndarray, sample: int = 500, k: int = 10
):
    """Recall@k của ANN so với tìm chính xác, query = chính vector của ảnh.

    Có nhiều ảnh trùng hẳn vector (cùng metadata), nên kết quả ANN được tính là đúng khi điểm
    của nó >= điểm thứ k của kết quả chính xác (xử lý hoà điểm), thay vì đòi đúng id.
    """
    rng = np.random.default_rng(42)
    picks = rng.choice(len(ids), size=min(sample, len(ids)), replace=False)
    matrix = np.asarray(vectors, dtype=np.float32)
    hits = total = 0
    self_found = 0
    for i in picks:
        exact = np.sort(matrix @ matrix[i])[::-1][:k]
        ann = search(collection, matrix[i], k) if backend() == "qdrant" else None
        if ann is None:
            raise RuntimeError("self_test cần VECTOR_BACKEND=qdrant")
        hits += sum(score >= exact[-1] - 1e-4 for _, score in ann)
        total += k
        self_found += int(ids[i]) in {pid for pid, _ in ann} or ann[0][1] >= 1 - 1e-4
    return {
        "collection": collection,
        "sample": int(len(picks)),
        "k": k,
        "recall_at_k": round(hits / total, 4),
        "self_or_identical_at_1": round(self_found / len(picks), 4),
    }
