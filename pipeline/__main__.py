"""CLI: python -m pipeline --csv <path> [--dry-run]"""

from __future__ import annotations

import argparse


def main() -> None:
    ap = argparse.ArgumentParser(prog="pipeline")
    ap.add_argument("--csv", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mode", choices=["approved"], default="approved")
    ap.add_argument("--out", default="reports/approved_run")
    ap.add_argument("--skip-smoke", action="store_true")
    ap.add_argument(
        "--username",
        action="append",
        default=[],
        help="Only import rows submitted by this username (repeatable)",
    )
    ap.add_argument(
        "--audit-sample",
        type=int,
        default=0,
        help="Download N approved images and run Stage 1 + Stage 3 as a quality audit",
    )
    args = ap.parse_args()
    from storage.runtime import load_env

    load_env()
    if args.limit:
        ap.error("Approved mode indexes the full CSV; --limit is not supported")
    if args.dry_run:
        import csv

        from storage.local import in_scope

        with open(args.csv, encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
            print(
                {
                    "columns": reader.fieldnames,
                    "source_rows": len(rows),
                    "scoped_rows": sum(in_scope(r, args.username) for r in rows),
                    "usernames": args.username or None,
                    "mode": args.mode,
                }
            )
        return
    if args.audit_sample < 0:
        ap.error("--audit-sample must be >= 0")
    from pipeline.local_run import run

    run(
        args.csv,
        args.out,
        smoke=not args.skip_smoke,
        usernames=args.username or None,
        audit_sample=args.audit_sample,
    )


if __name__ == "__main__":
    main()
