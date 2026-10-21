"""Phase 2: tải 1 lần toàn bộ ảnh của CSV 80k (thumbnail 512px + kích thước gốc + sha256).

Dùng lại `pipeline.verify.fetch` của Phần A (resumable, retry_later 3 vòng), cùng thư mục
`data/verify/` nên 3.151 ảnh pilot không tải lại. Kết quả phục vụ:
- 2.1 width/height gốc (đọc từ fetch.jsonl, không cần dò header riêng);
- 2.2 caption ảnh thiếu mô tả (thumbnail);
- 2.3 vector ảnh SigLIP2 (thumbnail).

python -X utf8 -m scripts.fetch_all_images [--csv ...] [--workers 32]
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter

from pipeline.verify import fetch, gate
from pipeline.verify.common import DEFAULT_CSV, read_csv, row_key, run_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default=DEFAULT_CSV)
    parser.add_argument("--workers", type=int, default=32)
    args = parser.parse_args()
    started = time.perf_counter()
    rows, seen = [], set()
    skipped: Counter = Counter()
    for row in read_csv(args.csv):
        url = row["image_url"].strip()
        reason = gate.gate(
            url, noext_policy="download"
        )  # noext giữ lại (đo ở Phần A: 92,5% là ảnh)
        if reason:
            skipped[reason] += 1
            continue
        if url in seen:
            skipped["duplicate_url"] += 1
            continue
        seen.add(url)
        rows.append(row)
    print(f"[fetch-all] {len(rows):,} URL cần tải; bỏ qua {dict(skipped)}", flush=True)
    state = fetch.run(rows, workers=args.workers, log=lambda m: print(m, flush=True))
    status = Counter(state[row_key(r)]["status"] for r in rows if row_key(r) in state)
    summary = {
        "csv": args.csv,
        "rows": len(rows),
        "skipped": dict(skipped),
        "status": dict(status),
        "seconds": round(time.perf_counter() - started, 1),
    }
    (run_dir() / "fetch_all_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print("[fetch-all]", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
