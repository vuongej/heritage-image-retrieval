"""Quét false-positive của bộ chặn truy vấn trên dữ liệu catalog thật.

python -m scripts.scan_query_guard [--limit 20]

Kỳ vọng: 0 tên thực thể bị chặn. Mô tả/caption là văn bản tự do nên có thể có vài ca chính đáng
(ví dụ mô tả chứa từ nhạy cảm); xem từng ca và sửa LEXICON hoặc chấp nhận.
"""

from __future__ import annotations

import argparse
import sys

from retrieval.query_guard import check
from storage.local import connect

SOURCES = [
    ("tên thực thể", "SELECT DISTINCT entity_name FROM entities"),
    ("alias KG", "SELECT DISTINCT alias_norm FROM kg_alias"),
    ("mô tả ảnh", "SELECT DISTINCT description FROM images"),
    ("caption", "SELECT DISTINCT caption FROM images WHERE caption IS NOT NULL"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20, help="số ca in ra cho mỗi nguồn")
    args = ap.parse_args()
    entity_hits = 0
    with connect() as conn:
        for label, sql in SOURCES:
            try:
                texts = [r[0] for r in conn.execute(sql) if r[0]]
            except Exception as exc:  # bảng/cột chưa có trong catalog này
                print(f"{label}: bỏ qua ({exc})")
                continue
            hits = [(t, v) for t in texts if (v := check(t)).blocked]
            print(f"{label}: {len(hits)}/{len(texts)} bị chặn")
            for text, verdict in hits[: args.limit]:
                print(f"   [{verdict.category}/{verdict.term}] {text[:110]}")
            if label in {"tên thực thể", "alias KG"}:
                entity_hits += len(hits)
    return 1 if entity_hits else 0


if __name__ == "__main__":
    sys.exit(main())
