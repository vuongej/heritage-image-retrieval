"""Thu câu trả lời VLM một lần, để mô phỏng mọi cấu hình router offline (bench_verify_router).

1. T5 `vlm.judge_batch` cho MỌI ảnh VAL + TEST qua được rule, theo lô <= 8 ảnh cùng entity.
   Router chỉ chọn ảnh nào được gửi; có sẵn câu trả lời của mọi ảnh thì mọi ngân sách / ngưỡng
   đều mô phỏng chính xác mà không gọi lại API.
2. S3 `vlm.label_single` (prompt bootstrap của pipeline) cho mẫu phân tầng 3.000 TRAIN + 1.000 VAL:
   nhãn thầy để dựng lại head production (học từ nhãn VLM, không từ nhãn người).

Resumable (cache VERIFY_DIR/vlm_batch.jsonl, boot_single.jsonl); chi phí đo từ deepseek_usage.jsonl.
  .venv-gpu/Scripts/python -m scripts.bench_verify_collect
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from pipeline.verify import fetch, vlm
from pipeline.verify.common import row_key, run_dir
from pipeline.verify.run import bootstrap_sample
from scripts.bench_verify_data import (
    BOOT_FILE,
    BOOT_PICKED_FILE,
    DEFAULT_VERIFY_DIR,
    VLM_BATCH_FILE,
    append,
    load,
    read_cache,
    reports_dir,
    usage_lines,
    usage_since,
    use_verify_dir,
)
from storage.runtime import load_env


def collect_batches(ds, workers: int, log) -> dict:
    # Tái dùng mẫu 100 entity đã chấm (cùng cách chia lô: 8 ảnh đầu của entity).
    cache = read_cache(VLM_BATCH_FILE)
    if not cache and (run_dir() / "vlm_sample.jsonl").exists():
        old = [d for d in read_cache("vlm_sample.jsonl").values() if "label" in d]
        append(VLM_BATCH_FILE, [{**d, "batch_size": None} for d in old])
        cache = read_cache(VLM_BATCH_FILE)
    by_entity: dict[str, list[dict]] = defaultdict(list)
    for r in ds.ok:
        if ds.side_of[r["image_url"]] in ("val", "test"):
            by_entity[r["entity_id"]].append(r)
    batches = [
        rs[s : s + vlm.BATCH_MAX]
        for _, rs in sorted(by_entity.items())
        for s in range(0, len(rs), vlm.BATCH_MAX)
    ]
    todo = [b for b in batches if not all(row_key(r) in cache for r in b)]
    log(f"[T5] {len(batches)} lô / {sum(map(len, batches))} ảnh · cần gọi {len(todo)} lô")

    def job(part):
        t = time.perf_counter()
        try:
            res = vlm.judge_batch(
                part[0], [(row_key(r), fetch.thumb_path(row_key(r)).read_bytes()) for r in part]
            )
        except Exception as exc:  # lô lỗi được gọi lại ở lần chạy sau
            return [], f"{type(exc).__name__}: {str(exc)[:120]}"
        ms = round((time.perf_counter() - t) * 1000)
        return [
            {"key": row_key(r), "human": r["human"], **res[row_key(r)], "batch_ms": ms,
             "batch_size": len(part)}
            for r in part
        ], None

    offset, t0, errors, done = usage_lines(), time.perf_counter(), [], 0
    with ThreadPoolExecutor(workers) as pool:
        for recs, err in pool.map(job, todo):
            if err:
                errors.append(err)
            else:
                append(VLM_BATCH_FILE, recs)
            done += 1
            if done % 100 == 0:
                log(f"[T5] {done}/{len(todo)} lô · lỗi {len(errors)}")
    wall = time.perf_counter() - t0
    images = sum(len(b) for b in todo)
    return {
        "batches_called": len(todo),
        "images_called": images,
        "errors": len(errors),
        "error_samples": errors[:5],
        "wall_seconds": round(wall, 1),
        "images_per_second": round(images / wall, 2) if wall and images else None,
        "workers": workers,
        "usage": usage_since(offset, ("vlm_batch",)),
    }


def collect_boot(ds, n_train: int, n_val: int, workers: int, log) -> dict:
    cache = read_cache(BOOT_FILE)
    picked = []
    for split_name, n in (("train", n_train), ("val", n_val)):
        pool = [r for r in ds.ok if ds.side_of[r["image_url"]] == split_name]
        picked += bootstrap_sample(pool, n, seed=42)
    (run_dir() / BOOT_PICKED_FILE).write_text(json.dumps([row_key(r) for r in picked]), "utf-8")
    todo = [r for r in picked if row_key(r) not in cache]
    log(f"[S3] bootstrap {len(picked)} ảnh · cần gọi {len(todo)}")

    def job(r):
        t = time.perf_counter()
        try:
            v = vlm.label_single(r, fetch.thumb_path(row_key(r)).read_bytes())
        except Exception as exc:
            return None, f"{type(exc).__name__}: {str(exc)[:120]}"
        return {"key": row_key(r), "human": r["human"], **v,
                "ms": round((time.perf_counter() - t) * 1000)}, None

    offset, t0, errors, done = usage_lines(), time.perf_counter(), [], 0
    with ThreadPoolExecutor(workers) as pool:
        for rec, err in pool.map(job, todo):
            if err:
                errors.append(err)
            else:
                append(BOOT_FILE, [rec])
            done += 1
            if done % 500 == 0:
                log(f"[S3] {done}/{len(todo)} · lỗi {len(errors)}")
    wall = time.perf_counter() - t0
    return {
        "picked": len(picked),
        "called": len(todo),
        "errors": len(errors),
        "error_samples": errors[:5],
        "wall_seconds": round(wall, 1),
        "images_per_second": round(len(todo) / wall, 2) if wall and todo else None,
        "usage": usage_since(offset, ("bootstrap",)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.bench_verify_collect")
    ap.add_argument("--csv", default="data/test.csv")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--boot-train", type=int, default=3000)
    ap.add_argument("--boot-val", type=int, default=1000)
    ap.add_argument("--verify-dir", default=DEFAULT_VERIFY_DIR)
    args = ap.parse_args()
    use_verify_dir(args.verify_dir)
    load_env()

    def log(m):
        print(m, flush=True)

    ds = load(args.csv)
    log(f"[data] ok {len(ds.ok)} ảnh · rule loại {len(ds.rule_of)}")
    out = reports_dir() / "vlm_collect.json"
    prev = json.loads(out.read_text("utf-8")) if out.exists() else {}
    report = {
        "t5_judge_batch": collect_batches(ds, args.workers, log),
        "s3_bootstrap": collect_boot(ds, args.boot_train, args.boot_val, args.workers, log),
    }
    # Giữ số đo của lần gọi thật lớn nhất (lần chạy lại chỉ đọc cache, không đo được gì).
    for k, v in prev.items():
        if v.get("images_called", v.get("called", 0)) > report[k].get(
            "images_called", report[k].get("called", 0)
        ):
            report[k] = v
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    log(f"[done] {out}: {json.dumps(report, ensure_ascii=False)[:600]}")


if __name__ == "__main__":
    main()
