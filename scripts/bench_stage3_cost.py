"""Đo giá thật của Stage 3 khi có GEMINI_API_KEY (thay cho ước lượng).

python -m scripts.bench_stage3_cost --n 1000
"""

from __future__ import annotations

import argparse
import os


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=1000)
    args = ap.parse_args()

    if not os.getenv("GEMINI_API_KEY"):
        print("Không có GEMINI_API_KEY -> bỏ qua. Dùng bảng ước lượng trong docs/data-pipeline.md.")
        return

    print(f"[bench] n={args.n} ảnh, model={os.getenv('GEMINI_MODEL')}")
    print("[bench] TODO(impl): đo token thực tế -> USD/ảnh -> ngoại suy 10M/100M")


if __name__ == "__main__":
    main()
