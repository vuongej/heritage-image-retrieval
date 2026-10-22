"""Benchmark Phần A trên nhãn NGƯỜI (data/test.csv, cột verify = yes/no).

Pipeline gốc (pipeline/verify) học head từ nhãn VLM thầy nên chỉ đo được "đồng thuận với thầy".
Script này dùng lại đúng các stage của nó nhưng thay nguồn nhãn bằng nhãn người:

  gate (rule URL) -> split theo nhóm tên (seed 42, 30% TEST / 20% VAL) -> tải + thumbnail + kiểm
  kích thước (rule) -> SigLIP2 ảnh/tên/mô tả -> 14 feature -> head logistic (chọn C + isotonic trên
  VAL) -> báo cáo trên TEST, không dùng TEST để chọn tham số hay ngưỡng.

Chạy (cần venv có CUDA cho SigLIP2; CPU vẫn chạy nhưng chậm):
  .venv-gpu/Scripts/python -m scripts.eval_verify_human --csv data/test.csv
Resumable: ảnh đã tải / đã encode được giữ trong VERIFY_DIR (mặc định data/verify_human).
Kết quả: reports/verify_human/report.json, report.md, predictions.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

from pipeline.verify import encoder, features, fetch, gate, head, metrics, split
from pipeline.verify.common import read_jsonl, row_key, run_dir, write_jsonl

DEFAULT_VERIFY_DIR = "data/verify_human"
PILOT_DIR = Path("data/verify")


def use_verify_dir(path: str = DEFAULT_VERIFY_DIR) -> None:
    """Ghi đè VERIFY_DIR lúc chạy. `.env` đặt VERIFY_DIR=data/verify (pilot) và được nạp ngay khi
    import pipeline.verify, nên setdefault ở đầu module không đủ: benchmark sẽ ghi vào pilot."""
    if Path(path).resolve() == PILOT_DIR.resolve():
        raise SystemExit("VERIFY_DIR của benchmark không được là data/verify (thư mục pilot)")
    os.environ["VERIFY_DIR"] = path


def guard() -> None:
    """Chặn mọi lần ghi cache benchmark vào thư mục pilot."""
    if run_dir().resolve() == PILOT_DIR.resolve():
        raise RuntimeError("Benchmark đang trỏ vào data/verify (pilot): gọi use_verify_dir() trước")


# Đơn giá đã đo (docs/verify-benchmark-jev.md §3): DeepSeek VLM 8 ảnh/lần, giờ cao điểm.
VLM_USD_PER_IMAGE = 0.180 / 1000
SCALES = (80_000, 1_000_000, 10_000_000, 100_000_000)
RULE_NO = {"R1_invalid", "R1_blocked", "R1_ws", "R6_dup_url", "dead", "too_small", "dup_sha256"}


def load_rows(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh), start=2):
            label = r["verify"].strip().lower()
            if label not in ("yes", "no"):
                continue
            rows.append(
                {
                    "line": i,
                    "entity_id": r["entity_id"],
                    "canonical_name": r["entity_name"],
                    "category": r["leaf_label"],
                    "image_url": r["image_url"].strip(),
                    "description": r.get("description") or "",
                    "from_db": "0",
                    "human": label,
                    "branch": r.get("branch", ""),
                    "priority": r.get("priority", ""),
                    "query_type": r.get("query_type", ""),
                    "source": r.get("nguon", ""),
                }
            )
    return rows


def seed_cache(rows: list[dict], src: Path) -> int:
    """Tái dùng ảnh pilot đã tải ở data/verify thay vì tải lại (chỉ đọc pilot)."""
    guard()
    manifest = run_dir() / "fetch.jsonl"
    if manifest.exists() or not (src / "fetch.jsonl").exists():
        return 0
    wanted = {row_key(r) for r in rows}
    reused = []
    for rec in read_jsonl(src / "fetch.jsonl"):
        if rec["key"] not in wanted or rec.get("status") not in ("ok", "too_small", "dead"):
            continue
        if rec["status"] == "ok":
            old = src / "thumbs" / rec["key"][:2] / f"{rec['key']}.jpg"
            if not old.exists():
                continue
            new = fetch.thumb_path(rec["key"])
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, new)
        reused.append(rec)
    write_jsonl(manifest, reused)
    return len(reused)


def embed_cached(ok_rows: list[dict], log) -> tuple[dict, dict]:
    guard()
    path = run_dir() / "emb.npz"
    cache: dict[str, tuple] = {}
    if path.exists():
        with np.load(path) as z:  # NpzFile đọc lại cả mảng mỗi lần truy cập: lấy một lần
            keys, img, name, desc = z["keys"], z["img"], z["name"], z["desc"]
        cache = {k: (img[i], name[i], desc[i]) for i, k in enumerate(keys)}
    todo = [r for r in ok_rows if row_key(r) not in cache]
    stats = {"reused": len(ok_rows) - len(todo), "encoded": len(todo)}
    if todo:
        out = encoder.embed(
            [fetch.thumb_path(row_key(r)) for r in todo],
            [r["canonical_name"] for r in todo],
            [r["description"] or r["canonical_name"] for r in todo],
            log=log,
        )
        stats.update(out["stats"])
        for i, r in enumerate(todo):
            cache[row_key(r)] = (out["img"][i], out["name"][i], out["desc"][i])
        keys = list(cache)
        np.savez(
            path,
            keys=np.array(keys),
            img=np.stack([cache[k][0] for k in keys]),
            name=np.stack([cache[k][1] for k in keys]),
            desc=np.stack([cache[k][2] for k in keys]),
        )
    ks = [row_key(r) for r in ok_rows]
    emb = {n: np.stack([cache[k][j] for k in ks]) for j, n in enumerate(("img", "name", "desc"))}
    return emb, stats


def binary(y_true: list[str], y_pred: list[str]) -> dict:
    """Lớp dương = 'no' (ảnh cần loại): recall = tỉ lệ ảnh xấu bị chặn, precision = loại có đúng."""
    c = Counter(zip(y_true, y_pred, strict=True))
    tp, fp, fn, tn = c[("no", "no")], c[("yes", "no")], c[("no", "yes")], c[("yes", "yes")]
    n = tp + fp + fn + tn
    p = tp / max(1, tp + fp)
    r = tp / max(1, tp + fn)
    return {
        "n": n,
        "accuracy": round((tp + tn) / max(1, n), 4),
        "reject_precision": round(p, 4),
        "reject_recall": round(r, 4),
        "reject_f1": round(2 * p * r / max(1e-9, p + r), 4),
        "false_reject_rate": round(fp / max(1, fp + tn), 4),  # ảnh tốt bị loại oan
        "leak_rate": round(fn / max(1, tp + fn), 4),  # ảnh xấu lọt qua
        "confusion": {"no→no": tp, "yes→no": fp, "no→yes": fn, "yes→yes": tn},
    }


def pick_band(p: np.ndarray, y: np.ndarray, target: float) -> tuple[float, float]:
    """Trên VAL: ngưỡng cao nhất cho auto-yes và thấp nhất cho auto-no đạt độ chính xác >= target."""
    hi, lo = 1.01, -0.01
    for t in np.unique(np.round(p, 3))[::-1]:
        m = p >= t
        if m.sum() >= 20 and y[m].mean() >= target:
            hi = float(t)
    for t in np.unique(np.round(p, 3)):
        m = p <= t
        if m.sum() >= 20 and (1 - y[m]).mean() >= target:
            lo = float(t)
    return hi, lo


def run(csv_path: str, out_dir: str, workers: int, seed: int, log=print) -> dict:
    t_all = time.perf_counter()
    rows = load_rows(csv_path)
    log(f"[data] {len(rows)} dòng có nhãn: {dict(Counter(r['human'] for r in rows))}")
    log(f"[cache] tái dùng {seed_cache(rows, Path('data/verify'))} ảnh từ data/verify")

    sp = split.split(rows, seed=seed)
    side_of, group_of = sp["assignment"], sp["group_of_url"]
    live, gate_report = gate.run(rows, noext_policy="download")
    live_keys = {id(r) for r in live}
    gate_code = {r["line"]: r["gate"] for r in gate_report.pop("rejected")}

    t = time.perf_counter()
    state = fetch.run(live, workers=workers, log=log)
    fetch_s = time.perf_counter() - t
    dups = fetch.mark_sha_duplicates(live, state)
    ok = [r for r in live if state.get(row_key(r), {}).get("status") == "ok"]
    log(f"[fetch] ok {len(ok)}/{len(live)} · dup sha256 {dups} · {fetch_s:.0f} s")

    t = time.perf_counter()
    emb, emb_stats = embed_cached(ok, log)
    emb_s = time.perf_counter() - t
    fetched = [state[row_key(r)] for r in ok]
    groups = [group_of[r["image_url"]] for r in ok]
    t = time.perf_counter()
    X, feats = features.build(ok, fetched, emb, groups, features.priors(live))
    side = np.array([side_of[r["image_url"]] for r in ok])
    y = np.array([1 if r["human"] == "yes" else 0 for r in ok])
    h = head.train(X, y, side, np.array(groups))
    head_s = time.perf_counter() - t
    p = h["p_cal"]

    # Quyết định end-to-end: rule chặn trước, head quyết phần còn lại (ngưỡng 0,5).
    p_of = {id(r): float(p[i]) for i, r in enumerate(ok)}
    rule_of: dict[int, str] = {}
    for r in rows:
        if id(r) not in live_keys:
            rule_of[id(r)] = gate_code.get(r["line"], "gate")
        elif id(r) not in p_of:
            rule_of[id(r)] = state.get(row_key(r), {}).get("status", "missing")

    def decide(r) -> str:
        return "no" if id(r) in rule_of else ("yes" if p_of[id(r)] >= 0.5 else "no")

    test = [r for r in rows if side_of[r["image_url"]] == "test"]
    va = side == "val"
    te = side == "test"
    hi, lo = pick_band(p[va], y[va], 0.95)
    auto_yes, auto_no = te & (p >= hi), te & (p <= lo)
    auto = auto_yes | auto_no
    pred_te = np.where(p[te] >= 0.5, 1, 0)
    rc = metrics.risk_coverage(pred_te == y[te], np.abs(p[te] - 0.5))

    by = {}
    for col in ("branch", "priority", "query_type", "source"):
        g = defaultdict(list)
        for r in test:
            g[r[col]].append(r)
        by[col] = {
            k: {**binary([r["human"] for r in v], [decide(r) for r in v]), "human_no_share":
                round(sum(r["human"] == "no" for r in v) / len(v), 4)}
            for k, v in sorted(g.items(), key=lambda kv: -len(kv[1]))
        }

    rule_counts = Counter(rule_of[id(r)] for r in test if id(r) in rule_of)
    rule_human = Counter((rule_of[id(r)], r["human"]) for r in test if id(r) in rule_of)
    auto_share = float(auto.sum() / max(1, te.sum()))
    ok_share = len(ok) / len(rows)
    ips = emb_stats.get("images_per_second")
    report = {
        "csv": csv_path,
        "seed": seed,
        "labels": dict(Counter(r["human"] for r in rows)),
        "split_rows": dict(Counter(side_of[r["image_url"]] for r in rows)),
        "split_groups": sp["report"]["groups"],
        "gate": {k: v for k, v in gate_report.items() if k != "rejected"},
        "fetch": dict(Counter(s.get("status") for s in (state.get(row_key(r), {}) for r in live))),
        "embedding": emb_stats,
        "head": h["report"],
        "test": {
            "baseline_approve_all": binary(
                [r["human"] for r in test], ["yes"] * len(test)
            ),
            "rules_only": {
                "rejected": sum(rule_counts.values()),
                "by_rule": dict(rule_counts),
                "precision_by_rule": {
                    k: round(rule_human[(k, "no")] / n, 4) for k, n in rule_counts.items()
                },
            },
            "head_only_on_fetched": {
                **binary(["yes" if v else "no" for v in y[te]], ["yes" if v else "no" for v in pred_te]),
                "auc": round(float(roc_auc_score(y[te], p[te])), 4),
                "ece": round(metrics.ece(y[te], p[te]), 4),
            },
            "end_to_end": binary([r["human"] for r in test], [decide(r) for r in test]),
            "auto_band_target_95": {
                "thresholds_from_val": {"auto_yes_if_p_ge": hi, "auto_no_if_p_le": lo},
                "auto_share": round(auto_share, 4),
                "auto_yes_precision": round(float(y[auto_yes].mean()), 4) if auto_yes.any() else None,
                "auto_no_precision": round(float(1 - y[auto_no].mean()), 4) if auto_no.any() else None,
                "auto_accuracy": round(float(((p[auto] >= 0.5) == (y[auto] == 1)).mean()), 4)
                if auto.any() else None,
                "routed_share": round(1 - auto_share, 4),
            },
            "risk_coverage": rc,
            "by": by,
        },
        "seconds": {
            "fetch": round(fetch_s, 1),
            "embed": round(emb_s, 1),
            "features_head": round(head_s, 2),
            "total": round(time.perf_counter() - t_all, 1),
        },
    }
    # Ngoại suy: tải là I/O (scale ngang), SigLIP2 theo images/s đo được, phần routed -> VLM batch.
    routed = 1 - auto_share
    report["scale"] = [
        {
            "images": n,
            "gpu_hours_siglip2": round(n * ok_share / ips / 3600, 2) if ips else None,
            "vlm_images": int(n * ok_share * routed),
            "vlm_usd": round(n * ok_share * routed * VLM_USD_PER_IMAGE, 2),
            "vlm_all_usd": round(n * ok_share * VLM_USD_PER_IMAGE, 2),
        }
        for n in SCALES
    ]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    with open(out / "predictions.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["line", "split", "entity_name", "image_url", "human", "pred", "rule", "p_yes"])
        for r in rows:
            w.writerow([
                r["line"], side_of[r["image_url"]], r["canonical_name"], r["image_url"], r["human"],
                decide(r), rule_of.get(id(r), ""), round(p_of[id(r)], 4) if id(r) in p_of else "",
            ])
    (out / "report.md").write_text(render_md(report), "utf-8")
    log(f"[done] {out / 'report.md'}")
    return report


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def render_md(r: dict) -> str:
    t = r["test"]
    rows = [
        ("Duyệt hết (baseline)", t["baseline_approve_all"]),
        ("Head trên ảnh tải được", t["head_only_on_fetched"]),
        ("End-to-end: rule + head", t["end_to_end"]),
    ]
    band = t["auto_band_target_95"]
    lines = [
        "# Benchmark Phần A trên nhãn người",
        "",
        f"Nguồn nhãn: `{r['csv']}` · {sum(r['labels'].values()):,} ảnh · "
        f"yes {r['labels'].get('yes', 0):,} / no {r['labels'].get('no', 0):,}.",
        f"Split theo nhóm tên (seed {r['seed']}): {r['split_rows']}. Head train bằng nhãn người trên "
        "TRAIN, chọn C và hiệu chỉnh trên VAL; mọi số dưới đây đo trên **TEST**.",
        "",
        "Lớp dương = `no` (ảnh phải loại). *Recall loại* = tỉ lệ ảnh xấu bị chặn; *loại oan* = tỉ lệ "
        "ảnh tốt bị chặn nhầm.",
        "",
        "| Cách quyết | n | Accuracy | Precision loại | Recall loại | F1 loại | Loại oan |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, m in rows:
        lines.append(
            f"| {name} | {m['n']:,} | {_pct(m['accuracy'])} | {_pct(m['reject_precision'])} | "
            f"{_pct(m['reject_recall'])} | {_pct(m['reject_f1'])} | {_pct(m['false_reject_rate'])} |"
        )
    ho = t["head_only_on_fetched"]
    lines += [
        "",
        f"Head: AUC **{ho['auc']:.3f}**, ECE {ho['ece']:.3f}, C = {r['head']['C']}.",
        "",
        "## Tự động hóa ở mức chính xác 95%",
        "",
        f"Ngưỡng chọn trên VAL: auto-yes khi p ≥ {band['thresholds_from_val']['auto_yes_if_p_ge']}, "
        f"auto-no khi p ≤ {band['thresholds_from_val']['auto_no_if_p_le']}. Trên TEST:",
        "",
        f"- Tự quyết không cần LLM: **{_pct(band['auto_share'])}** ảnh, accuracy "
        f"{_pct(band['auto_accuracy'])} (auto-yes {_pct(band['auto_yes_precision'])}, "
        f"auto-no {_pct(band['auto_no_precision'])}).",
        f"- Còn lại {_pct(band['routed_share'])} chuyển VLM / người.",
        "",
        "Risk–coverage (giữ phần head tự tin nhất):",
        "",
        "| Coverage | Accuracy phần giữ |",
        "|---:|---:|",
        *[f"| {_pct(pt['coverage'])} | {_pct(pt['acc_keep'])} |" for pt in t["risk_coverage"]["points"]],
        "",
        "## Rule chặn trước head",
        "",
        "| Rule | Số ảnh TEST | Trong đó người cũng nói `no` |",
        "|---|---:|---:|",
        *[
            f"| `{k}` | {n:,} | {_pct(t['rules_only']['precision_by_rule'][k])} |"
            for k, n in sorted(t["rules_only"]["by_rule"].items(), key=lambda kv: -kv[1])
        ],
        "",
        "## Theo nhóm (end-to-end, TEST)",
        "",
    ]
    for col in ("query_type", "branch", "priority", "source"):
        lines += [
            f"**{col}**",
            "",
            "| Nhóm | n | Tỉ lệ `no` | Accuracy | Recall loại | Loại oan |",
            "|---|---:|---:|---:|---:|---:|",
            *[
                f"| {k or '—'} | {m['n']:,} | {_pct(m['human_no_share'])} | {_pct(m['accuracy'])} | "
                f"{_pct(m['reject_recall'])} | {_pct(m['false_reject_rate'])} |"
                for k, m in t["by"][col].items()
            ],
            "",
        ]
    e = r["embedding"]
    s = r["seconds"]
    lines += [
        "## Thông lượng và chi phí",
        "",
        f"- Tải ảnh: {s['fetch']:,} s cho phần chưa có cache (I/O, scale ngang theo số máy/luồng).",
        f"- SigLIP2 ({e.get('device', '?')}): {e.get('images_per_second', '—')} ảnh/s "
        f"({e.get('encoded', 0):,} ảnh mới, {e.get('reused', 0):,} dùng lại cache).",
        f"- Feature + train head: {s['features_head']} s.",
        f"- VLM cho phần routed: ${VLM_USD_PER_IMAGE * 1000:.3f} / 1.000 ảnh (DeepSeek, 8 ảnh/lần, đã đo).",
        "",
        "| Số ảnh | GPU-giờ SigLIP2 | Ảnh qua VLM | Chi phí VLM (cascade) | Nếu mọi ảnh qua VLM |",
        "|---:|---:|---:|---:|---:|",
        *[
            f"| {x['images']:,} | {x['gpu_hours_siglip2']} | {x['vlm_images']:,} | "
            f"${x['vlm_usd']:,.0f} | ${x['vlm_all_usd']:,.0f} |"
            for x in r["scale"]
        ],
        "",
        "Ngoại suy giả định tỉ lệ tải được và phân bố khó/dễ giống tập này.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.eval_verify_human")
    ap.add_argument("--csv", default="data/test.csv")
    ap.add_argument("--out", default="reports/verify_human")
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--verify-dir", default=DEFAULT_VERIFY_DIR)
    args = ap.parse_args()
    use_verify_dir(args.verify_dir)
    run(args.csv, args.out, args.workers, args.seed, log=lambda m: print(m, flush=True))


if __name__ == "__main__":
    main()
