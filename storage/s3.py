"""S3 round-trip: đẩy lên, lấy về, bổ sung.

Layout:
    bronze/raw/source=<domain>/crawled_at=YYYY-MM-DD/*.jpg
    bronze/raw/entities/<nhom>/<file>.csv
    silver/verdict=<accept|reject>/stage=<1|2>/part-*.parquet
    gold/images/sha256[:2]/<sha256>.jpg
    gold/manifest/entities.parquet
    index/vectors/faiss_hnsw_80k.index
    index/id_map.parquet
    graph/entity_graph.jsonl
    evals/goldset.parquet, evals/runs/<run_id>/report.json
"""

from __future__ import annotations

import os
from dataclasses import dataclass

BRONZE = "bronze"
SILVER = "silver"
GOLD = "gold"
INDEX = "index"
GRAPH = "graph"
EVALS = "evals"


@dataclass
class ObjectRef:
    key: str
    size: int
    etag: str


def bucket() -> str:
    return os.getenv("S3_BUCKET", "heritage-images")


def put_bytes(client, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """bronze là append-only, bất biến."""
    client.put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)
    return key


def bronze_key_image(source_domain: str, crawled_at: str, filename: str) -> str:
    return f"{BRONZE}/raw/source={source_domain}/crawled_at={crawled_at}/{filename}"


def bronze_key_entities(nhom: str, filename: str) -> str:
    return f"{BRONZE}/raw/entities/{nhom}/{filename}"


def gold_key(sha256: str, ext: str = "jpg") -> str:
    return f"{GOLD}/images/sha256={sha256[:2]}/{sha256}.{ext}"


def presign_get(client, key: str, expires: int = 3600) -> str:
    """Presign để trả URL ảnh cho web demo (p95 ~30 ms)."""
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket(), "Key": key}, ExpiresIn=expires
    )


def get_bytes(client, key: str) -> bytes:
    """Lấy data về để verify/rebuild."""
    return client.get_object(Bucket=bucket(), Key=key)["Body"].read()


def sync_down(client, prefix: str, local_dir: str) -> int:
    """TODO(impl): paginator list_objects_v2 + download_file. Dùng để tái lập pipeline."""
    raise NotImplementedError


def write_manifest(client, rows: list[dict], key: str = f"{GOLD}/manifest/entities.parquet") -> str:
    """TODO(impl): pandas -> parquet -> put_bytes. Mỗi dòng = 1 ảnh."""
    raise NotImplementedError
