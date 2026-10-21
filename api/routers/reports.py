"""Read-only evidence for the web UI: live index counts and measured report files.

Only the report IDs listed in REPORTS can be read (no path from the client reaches the
filesystem). Nothing here computes or fills in a metric: a missing file is a 404 and a
missing Qdrant is reported as unavailable, never as zero.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()
ROOT = Path(__file__).resolve().parents[2]

# id -> (path, title, keep only these top-level keys or None for all)
REPORTS: dict[str, tuple[str, str, tuple[str, ...] | None]] = {
    "latency": ("reports/v2/latency.json", "Latency /v1/search (concurrency 1 và 4)", None),
    "quality": ("reports/v2/quality/eval.json", "Chất lượng truy xuất (nhãn silver)", ("summary",)),
    "index_counts": ("reports/v2/index_counts.json", "Đếm index CSV ↔ SQLite ↔ Qdrant", None),
    "rerank_ab": ("reports/v2/rerank_ab.json", "A/B reranker trên pool đóng băng", None),
    "verify": ("reports/verify/report.json", "Phần A — pipeline verify ảnh", None),
}


def _meta(report_id: str) -> dict:
    rel, title, _ = REPORTS[report_id]
    path = ROOT / rel
    if not path.exists():
        return {"id": report_id, "title": title, "path": rel, "available": False}
    stat = path.stat()
    return {
        "id": report_id,
        "title": title,
        "path": rel,
        "available": True,
        "modified_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime)),
        "bytes": stat.st_size,
    }


@router.get("/reports")
def list_reports() -> dict:
    return {"items": [_meta(r) for r in REPORTS]}


@router.get("/reports/{report_id}")
def get_report(report_id: str) -> dict:
    if report_id not in REPORTS:
        raise HTTPException(404, "unknown report id")
    meta = _meta(report_id)
    if not meta["available"]:
        raise HTTPException(404, f"{meta['path']} has not been generated")
    raw = (ROOT / meta["path"]).read_bytes()
    data = json.loads(raw.decode("utf-8"))
    keep = REPORTS[report_id][2]
    if keep is not None and isinstance(data, dict):
        data = {k: data[k] for k in keep if k in data}
    return {**meta, "sha256": hashlib.sha256(raw).hexdigest(), "data": data}


def _qdrant(collection: str) -> dict:
    from retrieval import vector_store

    if vector_store.backend() != "qdrant":
        return {"available": False, "reason": f"VECTOR_BACKEND={vector_store.backend()}"}
    try:
        info = vector_store.client().get_collection(collection)
    except Exception as exc:  # collection missing or Qdrant down: report it, do not guess
        return {"available": False, "reason": type(exc).__name__}
    return {
        "available": True,
        "points": info.points_count,
        "indexed_vectors": info.indexed_vectors_count,
        "status": str(info.status.value if hasattr(info.status, "value") else info.status),
    }


@router.get("/stats")
def stats() -> dict:
    from retrieval import vector_store
    from retrieval.hop import ensure_schema
    from retrieval.local_index import manifest
    from storage.local import connect, counts

    state = manifest()
    with connect() as conn:
        ensure_schema(conn)

        def one(sql: str) -> int:
            return conn.execute(sql).fetchone()[0]

        # Lược đồ KG v2 (retrieval/hop.py): kg_node / kg_edge / kg_link. Chỉ cạnh đã kiểm chứng
        # (verified hoặc reviewed) được resolver dùng; `kg_relations` giữ tên cũ cho UI = số đó.
        verified = one("SELECT count(*) FROM kg_edge WHERE verified=1 OR reviewed=1")
        kg = {
            "kg_relations": verified,
            "edges_verified": verified,
            "edges_total": one("SELECT count(*) FROM kg_edge"),
            "persons": one("SELECT count(*) FROM kg_node WHERE kind='person'"),
            "places": one("SELECT count(*) FROM kg_node WHERE kind='place'"),
            "linked_entities": one("SELECT count(DISTINCT entity_id) FROM kg_link"),
        }
        for source, n in conn.execute(
            "SELECT source_type, count(*) FROM kg_edge WHERE verified=1 OR reviewed=1"
            " GROUP BY source_type"
        ):
            kg[f"verified_from_{source}"] = n
    return {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "catalog": counts(),
        "knowledge_graph": kg,
        "vector_backend": vector_store.backend(),
        "qdrant_url_configured": bool(os.getenv("QDRANT_URL")),
        "img_text": _qdrant(vector_store.TEXT),
        "img_visual": _qdrant(vector_store.VISUAL),
        "manifest": {
            k: state.get(k)
            for k in ("count", "indexed_count", "complete", "model", "dim", "index_version")
        },
        "visual_enabled": vector_store.has_visual(),
        "required_images": 80_000,
    }
