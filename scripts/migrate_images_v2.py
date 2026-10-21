"""Phase 2.1: điền verify / width / height / has_watermark / fetch_status cho bảng images.

Nguồn (khớp theo image_url; key Phần A = sha256(url)):
- verify       <- reports/verify/*_verified.csv (cột verify yes/no của pipeline Phần A)
- width/height <- data/verify/fetch.jsonl (kích thước ảnh gốc khi tải; thay cho dò header)
- has_watermark<- data/verify/labels_boot.jsonl (scores.watermark >= 0,5) và vlm_results.jsonl
- fetch_status <- fetch.jsonl (ok | too_small | dead | dup_sha256)

Không ghi đè bằng NULL: dòng không có nguồn giữ NULL, báo cáo đếm theo lý do.
python -X utf8 -m scripts.migrate_images_v2 [--out reports/phase2/migrate_v2.json]
"""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
from collections import Counter
from pathlib import Path

from storage.local import connect

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "data" / "verify"


def key(url: str) -> str:
    return hashlib.sha256(url.strip().encode()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


def migrate(
    verify_dir: Path = VERIFY, verified_glob: str | None = None, human_csv: str | None = None
) -> dict:
    """`human_csv`: bộ dữ liệu người dùng đã verify tay 100% -> verify=yes, verify_source=human,
    ưu tiên hơn nhãn VLM pilot của Phần A."""
    verified_glob = verified_glob or str(ROOT / "reports" / "verify" / "*_verified.csv")
    verify: dict[str, str] = {}
    source: dict[str, str] = {}
    verified_rows = 0
    for path in sorted(glob.glob(verified_glob)):
        for row in csv.DictReader(open(path, encoding="utf-8-sig", newline="")):
            verified_rows += 1
            if row.get("verify") in {"yes", "no"}:
                verify[key(row["image_url"])] = row["verify"]
                source[key(row["image_url"])] = "vlm_pilot"
    human_rows = 0
    if human_csv:
        for row in csv.DictReader(open(human_csv, encoding="utf-8-sig", newline="")):
            if row.get("flag", "").strip().lower() == "approved":
                verify[key(row["image_url"])] = "yes"
                source[key(row["image_url"])] = "human"
                human_rows += 1
    fetched = {r["key"]: r for r in read_jsonl(verify_dir / "fetch.jsonl")}
    watermark: dict[str, int] = {}
    for r in read_jsonl(verify_dir / "labels_boot.jsonl"):
        score = (r.get("scores") or {}).get("watermark")
        if score is not None:
            watermark[r["key"]] = int(score >= 0.5)
    for r in read_jsonl(verify_dir / "vlm_results.jsonl"):  # chấm 2 lượt: watermark nếu 1 lượt thấy
        runs = [r.get(k) for k in ("run1", "run2") if isinstance(r.get(k), dict)]
        if runs:
            watermark[r["key"]] = int(any(run.get("watermark") for run in runs))

    report: Counter = Counter()
    with connect() as conn:
        rows = conn.execute("SELECT rownum, image_url FROM images").fetchall()
        updates = []
        for rownum, url in rows:
            k = key(url)
            rec = fetched.get(k, {})
            v = verify.get(k)
            w, h = (rec.get("w"), rec.get("h")) if rec.get("w") else (None, None)
            wm = watermark.get(k)
            status = rec.get("status")
            report["verify=" + (f"{v}({source[k]})" if v else "NULL(không có nguồn)")] += 1
            report["size=" + ("có" if w else f"NULL(fetch {status or 'chưa tải'})")] += 1
            report["watermark=" + ("NULL(chưa chấm VLM)" if wm is None else str(wm))] += 1
            report["fetch_status=" + (status or "NULL")] += 1
            updates.append((v, source.get(k), w, h, wm, status, rownum))
        conn.executemany(
            "UPDATE images SET verify=?, verify_source=?, width=?, height=?, has_watermark=?,"
            " fetch_status=? WHERE rownum=?",
            updates,
        )
        known = conn.execute("SELECT count(*) FROM images WHERE width IS NOT NULL").fetchone()[0]
        conn.execute(
            "INSERT OR REPLACE INTO metadata VALUES ('dimensions_known', ?)", (str(known),)
        )
    summary = {
        "images": len(rows),
        "verified_csv_rows": verified_rows,
        "human_verified_rows": human_rows,
        "verified_matched": sum(1 for r in rows if key(r[1]) in verify),
        "fetch_records": len(fetched),
        "watermark_labels": len(watermark),
        "breakdown": dict(sorted(report.items())),
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/phase2/migrate_v2.json")
    args = parser.parse_args()
    from storage.runtime import source_csv

    # Bộ nguồn được người dùng xác nhận verify tay 100% (2026-10-21).
    summary = migrate(human_csv=str(ROOT / source_csv()))
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
