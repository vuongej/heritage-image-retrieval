"""Nạp CSV nhóm 1 lên S3 + Postgres + index.

python -m scripts.seed_from_csv --csv data/bo_sung_anh_cho_entities_nhom_1_Vuong_ent1-500.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_CSV = "data/bo_sung_anh_cho_entities_nhom_1_Vuong_ent1-500.csv"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--skip-s3", action="store_true")
    args = ap.parse_args()

    path = Path(args.csv)
    if not path.exists():
        raise SystemExit(f"Không thấy CSV: {path}")

    from storage.s3 import bronze_key_entities

    print(f"[seed] csv = {path}")
    print(f"[seed] s3 key dự kiến = {bronze_key_entities('nhom_1', path.name)}")
    print("[seed] TODO(impl):")
    print("  1) upload CSV -> bronze/raw/entities/nhom_1/")
    print("  2) db.seed_entities_from_csv.upsert  -> 500 entity / 3.226 ảnh")
    print("  3) queue backfill cho 242 entity 0 ảnh + 478 entity < 5 ảnh")
    print("  4) pipeline Stage1 -> Stage2 -> (Stage3) -> gold/")
    print("  5) build index (Qdrant) + graph")


if __name__ == "__main__":
    main()
