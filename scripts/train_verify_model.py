"""Huấn luyện và đóng gói classifier production của Pipeline A (cấu hình chọn ở bench_verify_router).

M1b = LightGBM trên embedding ảnh SigLIP2 (768) + 14 feature, học từ nhãn người (data/test.csv):
ensemble 5 model, mỗi model học trên 4/5 nhóm TRAIN (dừng sớm trên 15% nhóm của phần đó) — đúng
cách M1b được chấm trong bench_verify_router — điểm = trung bình, hiệu chỉnh isotonic trên VAL.
Ngưỡng t, ngân sách router và cách đọc VLM lấy từ reports/verify_router/report.json (đã chọn trên
VAL). Artifact được chấm lại trên TEST đúng như khi chạy trong processing service.

  .venv-gpu/Scripts/python -m scripts.train_verify_model
Kết quả: models/verify/m1b_fold{0..4}.txt + model_card.json (processing/model.py nạp hai file này).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from pipeline.verify import encoder, features, gate, metrics
from scripts import bench_verify_models as bm
from scripts import bench_verify_router as br
from scripts.bench_verify_data import (
    DEFAULT_VERIFY_DIR,
    VLM_BATCH_FILE,
    load,
    read_cache,
    use_verify_dir,
)

OUT = Path("models/verify")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.train_verify_model")
    ap.add_argument("--csv", default="data/test.csv")
    ap.add_argument("--verify-dir", default=DEFAULT_VERIFY_DIR)
    ap.add_argument("--router-report", default="reports/verify_router/report.json")
    args = ap.parse_args()
    use_verify_dir(args.verify_dir)

    import lightgbm as lgb

    ds = load(args.csv)
    chosen = json.loads(Path(args.router_report).read_text("utf-8"))["chosen"]
    tr = np.where(ds.side == "train")[0]
    t0 = time.perf_counter()
    boosters = []
    for fold_fit, _ in GroupKFold(bm.FOLDS).split(tr, groups=ds.groups[tr]):
        fit, stop = bm._inner_split(ds.groups, tr[fold_fit])
        boosters.append(lgb.train(
            bm.LGB_PARAMS,
            lgb.Dataset(ds.X[fit], ds.y[fit]),
            num_boost_round=3000,
            valid_sets=[lgb.Dataset(ds.X[stop], ds.y[stop])],
            callbacks=[lgb.early_stopping(100, verbose=False)],
        ))
    train_s = time.perf_counter() - t0
    raw = np.mean([b.predict(ds.X, num_iteration=b.best_iteration) for b in boosters], axis=0)
    va, te = ds.side == "val", ds.side == "test"
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(raw[va], ds.y[va])
    p = iso.predict(raw)

    # Chấm artifact trên TEST với đúng router + VLM đã chọn (câu trả lời VLM lấy từ cache benchmark).
    vlm = read_cache(VLM_BATCH_FILE)
    test = br.View(ds, "test")
    t, alpha, rule = chosen["t"], chosen["alpha"], chosen["rule"]
    head_only, _, _ = br.decide(test, p[test.ok_x], t, 0.0, "goc", vlm)
    with_vlm, _, routed = br.decide(test, p[test.ok_x], t, alpha, rule, vlm)

    live, _ = gate.run(ds.rows, noext_policy="download")
    pri = features.priors(live)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("m1b_*.txt"):
        old.unlink()
    files = []
    for i, b in enumerate(boosters):
        files.append(f"m1b_fold{i}.txt")
        b.save_model(str(OUT / files[-1]), num_iteration=b.best_iteration)
    card = {
        "name": "M1b",
        "description": "LightGBM trên embedding ảnh SigLIP2 + 14 feature, nhãn người, isotonic trên VAL",
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_csv": args.csv,
        "source_csv_sha256": hashlib.sha256(Path(args.csv).read_bytes()).hexdigest(),
        "encoder": encoder.ENCODER,
        "image_dim": int(ds.emb["img"].shape[1]),
        "scalar_features": features.SCALAR_NAMES,
        "model_files": files,
        "train_rows": int(len(tr)),
        "best_iterations": [int(b.best_iteration) for b in boosters],
        "train_seconds": round(train_s, 2),
        "lgb_params": bm.LGB_PARAMS,
        "calibration": {"x": iso.X_thresholds_.tolist(), "y": iso.y_thresholds_.tolist()},
        "decision": {
            "threshold_t": t,
            "router_alpha": alpha,
            "vlm_rule": rule,
            "chosen_on": "VAL (reports/verify_router/report.json)",
        },
        # Prior host / nhóm category của tập huấn luyện: dùng cố định khi suy luận để một lô upload
        # nhỏ không làm lệch feature host_prior / category_prior.
        "priors": {"host": dict(pri["host"].most_common()), "bucket": dict(pri["bucket"].most_common())},
        "test_metrics": {
            "auc": round(float(roc_auc_score(ds.y[te], p[te])), 4),
            "ece": round(float(metrics.ece(ds.y[te], p[te])), 4),
            "head_only": br.evaluate(test, head_only),
            "with_router_vlm": {**br.evaluate(test, with_vlm),
                                "routed_share": round(float(routed.mean()), 4)},
        },
        "label_counts": dict(Counter(r["human"] for r in ds.rows)),
    }
    (OUT / "model_card.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), "utf-8")
    size = sum((OUT / f).stat().st_size for f in files)
    m = card["test_metrics"]
    print(f"[model] {OUT} · {len(boosters)} model, {card['best_iterations']} cây · {size / 1e6:.1f} MB"
          f" · train {train_s:.1f} s")
    print(f"[test] AUC {m['auc']} · head-only R_no {m['head_only']['recall_no']} "
          f"R_yes {m['head_only']['recall_yes']} · +VLM {alpha:.0%} R_no "
          f"{m['with_router_vlm']['recall_no']} R_yes {m['with_router_vlm']['recall_yes']}")


if __name__ == "__main__":
    main()
