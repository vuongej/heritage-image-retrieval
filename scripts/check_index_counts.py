"""A2: kiểm tra số lượng index end-to-end — CSV ↔ SQLite ↔ Qdrant, ID parity, quarantine.

Không bao giờ báo "đạt 80k" chỉ vì CSV có 80.000 dòng: số được báo là số ảnh THỰC SỰ query được.
Exit code 1 khi `--require N` lớn hơn số ảnh indexed hoặc có lệch ID giữa SQLite và Qdrant.

python -X utf8 -m scripts.check_index_counts [--require 80000] [--out reports/v2/index_counts.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from retrieval.local_index import manifest
from storage.local import connect
from storage.runtime import source_csv

ROOT = Path(__file__).resolve().parents[1]


def csv_audit(path: Path) -> dict:
    rows = invalid = 0
    quarantine = []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for line, row in enumerate(csv.DictReader(stream), start=2):
            rows += 1
            url = row["image_url"].strip()
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.netloc:
                invalid += 1
                quarantine.append(
                    {
                        "csv_line": line,
                        "entity_id": row["entity_id"],
                        "canonical_name": row["canonical_name"],
                        "image_url_prefix": url[:40],
                        "reason": "non_http_scheme",
                        "resolution": "excluded; no replacement image supplied",
                    }
                )
    return {"csv_rows": rows, "csv_valid_rows": rows - invalid, "quarantine": quarantine}


def qdrant_ids(collection: str) -> set[int] | None:
    from retrieval import vector_store

    if vector_store.backend() != "qdrant":
        return None
    client = vector_store.client()
    if not client.collection_exists(collection):
        return set()
    ids, offset = set(), None
    while True:
        points, offset = client.scroll(
            collection, limit=10_000, offset=offset, with_payload=False, with_vectors=False
        )
        ids.update(int(p.id) for p in points)
        if offset is None:
            return ids


def check(csv_path: Path, require: int) -> dict:
    report = csv_audit(csv_path)
    with connect() as conn:
        sqlite_ids = {r[0] for r in conn.execute("SELECT rownum FROM images")}
    state = manifest()
    report["sqlite_images"] = len(sqlite_ids)
    report["vectors_npy_rows"] = state.get("indexed_count")
    report["index_complete"] = bool(state.get("complete"))
    ids = qdrant_ids("img_text")
    if ids is not None:
        report["qdrant_img_text"] = len(ids)
        report["orphan_vectors"] = len(ids - sqlite_ids)  # vector không có dòng SQLite
        report["missing_vectors"] = len(sqlite_ids - ids)  # dòng SQLite không có vector
    indexed = min(
        v
        for v in (
            report["sqlite_images"],
            report["vectors_npy_rows"] or 0,
            report.get("qdrant_img_text"),
        )
        if v is not None
    )
    report["indexed_images"] = indexed
    report["require"] = require
    problems = []
    if require and indexed < require:
        problems.append(f"indexed {indexed} < required {require}")
    if report.get("orphan_vectors") or report.get("missing_vectors"):
        problems.append("ID parity SQLite/Qdrant failed")
    report["ok"] = not problems
    report["problems"] = problems
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=source_csv())
    parser.add_argument("--require", type=int, default=0)
    parser.add_argument("--out", default="reports/v2/index_counts.json")
    args = parser.parse_args()
    report = check(ROOT / args.csv, args.require)
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
