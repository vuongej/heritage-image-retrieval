"""Tầng VLM của Phần A so với nhãn người, trên mẫu entity của TEST (chạy sau eval_verify_human).

Lấy N entity ngẫu nhiên (seed 7) của TEST, tối đa 8 ảnh/entity, gọi vlm.judge_batch đúng như tầng
T5 của pipeline. Chấm nhiều cách đọc câu trả lời VLM, rồi kết hợp với p_yes của head bằng logistic
(cross-validation theo entity) để đo cascade head + VLM.

  .venv-gpu/Scripts/python -m scripts.eval_verify_human_vlm --entities 100
Kết quả: reports/verify_human/vlm_sample.json (câu trả lời cache ở VERIFY_DIR/vlm_sample.jsonl).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold, cross_val_predict

from pipeline.verify import fetch, split, vlm
from pipeline.verify.common import read_jsonl, row_key, run_dir, write_jsonl
from scripts.eval_verify_human import DEFAULT_VERIFY_DIR, binary, guard, load_rows, use_verify_dir
from storage.runtime import load_env

READINGS = {
    "VLM: đúng chủ thể và sạch (prompt gốc)": lambda d: d["label"],
    "VLM: partial tính là yes": lambda d: "yes"
    if d["subject"] in ("dung", "partial") and not (d["watermark"] or d["unsafe"])
    else "no",
    "VLM: bỏ qua watermark": lambda d: "yes" if d["subject"] == "dung" and not d["unsafe"] else "no",
    "VLM: chỉ loại khi subject = sai": lambda d: "no" if d["subject"] == "sai" else "yes",
}


def run(csv_path: str, out_dir: str, n_entities: int, workers: int, seed: int) -> dict:
    load_env()
    rows = load_rows(csv_path)
    side = split.split(rows, seed=42)["assignment"]
    state = {r["key"]: r for r in read_jsonl(run_dir() / "fetch.jsonl")}
    ents: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if side[r["image_url"]] == "test" and state.get(row_key(r), {}).get("status") == "ok":
            ents[r["entity_id"]].append(r)
    ids = sorted(ents)
    random.Random(seed).shuffle(ids)
    ids = ids[:n_entities]

    guard()
    cache_path = run_dir() / "vlm_sample.jsonl"
    cache = {d["key"]: d for d in read_jsonl(cache_path)} if cache_path.exists() else {}

    def job(eid: str) -> list[dict]:
        rs = ents[eid][: vlm.BATCH_MAX]
        if all(row_key(r) in cache for r in rs):
            return [cache[row_key(r)] for r in rs]
        images = [(row_key(r), fetch.thumb_path(row_key(r)).read_bytes()) for r in rs]
        t = time.perf_counter()
        try:
            res = vlm.judge_batch(rs[0], images)
        except Exception as exc:  # một batch lỗi không làm hỏng cả lượt đo
            return [{"key": row_key(r), "human": r["human"], "error": str(exc)[:200]} for r in rs]
        ms = round((time.perf_counter() - t) * 1000)
        return [
            {"key": row_key(r), "human": r["human"], **res[row_key(r)], "batch_ms": ms}
            for r in rs
        ]

    t0 = time.perf_counter()
    with ThreadPoolExecutor(workers) as pool:
        results = [d for batch in pool.map(job, ids) for d in batch]
    wall = time.perf_counter() - t0
    write_jsonl(cache_path, results)
    ok = [d for d in results if "label" in d]

    preds = {
        r["image_url"]: float(r["p_yes"])
        for r in csv.DictReader(open(Path(out_dir) / "predictions.csv", encoding="utf-8"))
        if r["p_yes"]
    }
    url_of = {row_key(r): r["image_url"] for r in rows}
    entity_of = {row_key(r): r["entity_id"] for r in rows}
    y = np.array([d["human"] == "yes" for d in ok], int)
    hp = np.array([preds[url_of[d["key"]]] for d in ok])
    feats = np.column_stack(
        [hp, [d["subject"] == "dung" for d in ok], [d["subject"] == "sai" for d in ok],
         [d["watermark"] for d in ok]]
    ).astype(float)
    p = cross_val_predict(
        LogisticRegression(), feats, y, groups=[entity_of[d["key"]] for d in ok], cv=GroupKFold(5),
        method="predict_proba",
    )[:, 1]
    order = np.argsort(-np.abs(p - 0.5))
    human = [d["human"] for d in ok]
    report = {
        "entities": len(ids),
        "images": len(results),
        "errors": len(results) - len(ok),
        "human": dict(Counter(human)),
        "wall_seconds": round(wall, 1),
        "images_per_second": round(len(ok) / max(wall, 1e-9), 1),
        "baseline_approve_all": binary(human, ["yes"] * len(ok)),
        "head_only": {
            **binary(human, ["yes" if v >= 0.5 else "no" for v in hp]),
            "auc": round(float(roc_auc_score(y, hp)), 4),
        },
        "vlm_readings": {name: binary(human, [f(d) for d in ok]) for name, f in READINGS.items()},
        "head_plus_vlm": {
            **binary(human, ["yes" if v >= 0.5 else "no" for v in p]),
            "auc": round(float(roc_auc_score(y, p)), 4),
            "risk_coverage": [
                {"coverage": c, "accuracy": round(float(
                    ((p[order[: int(c * len(p))]] >= 0.5) == y[order[: int(c * len(p))]]).mean()), 4)}
                for c in (1.0, 0.8, 0.6, 0.5)
            ],
        },
        "crosstab": {
            "subject": {f"{a}/{b}": n for (a, b), n in sorted(Counter(
                (d["subject"], d["human"]) for d in ok).items())},
            "watermark": {f"{a}/{b}": n for (a, b), n in sorted(Counter(
                (d["watermark"], d["human"]) for d in ok).items())},
            "unsafe": {f"{a}/{b}": n for (a, b), n in sorted(Counter(
                (d["unsafe"], d["human"]) for d in ok).items())},
        },
    }
    out = Path(out_dir) / "vlm_sample.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(f"[done] {out}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.eval_verify_human_vlm")
    ap.add_argument("--csv", default="data/test.csv")
    ap.add_argument("--out", default="reports/verify_human")
    ap.add_argument("--entities", type=int, default=100)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--verify-dir", default=DEFAULT_VERIFY_DIR)
    args = ap.parse_args()
    use_verify_dir(args.verify_dir)
    run(args.csv, args.out, args.entities, args.workers, args.seed)


if __name__ == "__main__":
    main()
