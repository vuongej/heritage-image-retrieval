"""CLI: python -m pipeline.verify [--entities 400] [--budget 0.15] ...

Default = the doc's cheapest validation run: 400 entity groups stratified by category,
B0 -> B1 -> B3 -> B4 (+ B5 cascade on TEST). --entities 0 runs every live row.
"""

from __future__ import annotations

import argparse

from pipeline.verify.common import DEFAULT_CSV
from storage.runtime import load_env


def main() -> None:
    ap = argparse.ArgumentParser(prog="pipeline.verify")
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--out", default="reports/verify")
    ap.add_argument("--entities", type=int, default=400, help="pilot size in name groups (0 = all)")
    ap.add_argument("--budget", type=float, default=0.15, help="VLM share alpha of the target rows")
    ap.add_argument("--target", choices=["test", "val", "all"], default="test")
    ap.add_argument(
        "--second-share", type=float, default=0.04, help="share re-judged twice (3-5%%)"
    )
    ap.add_argument(
        "--noext",
        choices=["download", "reject"],
        default="download",
        help="R1_noext: 'reject' = doc rule; 'download' = let the download decide (measured)",
    )
    ap.add_argument("--workers", type=int, default=8, help="VLM concurrency")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-vlm", action="store_true", help="stop before paying for T5")
    ap.add_argument(
        "--bootstrap",
        type=int,
        default=0,
        help="VLM bootstrap labels: N rows stratified by category (0 = every downloaded row)",
    )
    args = ap.parse_args()
    if not 0 <= args.budget <= 0.5:
        ap.error("--budget must be in [0, 0.5]")
    load_env()
    from pipeline.verify.run import run

    run(
        args.csv,
        args.out,
        args.entities,
        args.budget,
        args.seed,
        args.workers,
        args.noext,
        args.target,
        args.second_share,
        args.skip_vlm,
        args.bootstrap,
    )


if __name__ == "__main__":
    main()
