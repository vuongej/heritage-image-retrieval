"""Benchmark router Phần A end-to-end trên nhãn người, chọn cấu hình production.

Mỗi ảnh đi qua: rule (gate / tải / kích thước / trùng) -> SigLIP2 -> classifier -> router
(pipeline.verify.router.select, đúng hàm production) -> VLM nếu được chọn. Câu trả lời VLM lấy từ
cache của scripts.bench_verify_collect (đã chấm MỌI ảnh VAL + TEST), nên mọi ngân sách được mô phỏng
chính xác mà không gọi lại API.

Quy trình chống rò rỉ:
  - classifier học trên TRAIN, hiệu chỉnh trên VAL (bench_verify_models);
  - với từng (classifier, ngân sách) chọn ngưỡng quyết định + cách đọc câu trả lời VLM trên VAL;
  - chọn cấu hình production trên VAL; TEST chỉ dùng để báo cáo.

  .venv-gpu/Scripts/python -m scripts.bench_verify_router
Kết quả: reports/verify_router/report.md, report.json, decisions_<cấu hình>.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold, cross_val_predict

from pipeline.verify import metrics, router
from pipeline.verify.common import read_jsonl, row_key, run_dir
from scripts import bench_verify_models as bm
from scripts.bench_verify_data import (
    BOOT_FILE,
    BOOT_PICKED_FILE,
    DEFAULT_VERIFY_DIR,
    VLM_BATCH_FILE,
    load,
    read_cache,
    reports_dir,
    use_verify_dir,
)

BUDGETS = (0.0, 0.05, 0.10, 0.15, 0.20)
# Từ 0,05: P0 (học nhãn VLM thầy, khắt khe hơn người) cần ngưỡng thấp mới giữ đủ ảnh tốt.
T_GRID = np.round(np.arange(0.05, 0.951, 0.025), 3)
FALLBACK_VLM_USD_PER_IMAGE = 0.145 / 1000  # mẫu 582 ảnh (docs/verify-human-benchmark.md)
ENCODE_BATCH = 64

RULES = {
    "goc": lambda v: v["label"],  # prompt production: đúng chủ thể VÀ không watermark/unsafe
    "bo_watermark": lambda v: "yes" if v["subject"] == "dung" and not v["unsafe"] else "no",
    "partial_yes": lambda v: "yes"
    if v["subject"] in ("dung", "partial") and not (v["watermark"] or v["unsafe"])
    else "no",
    "chi_sai": lambda v: "no" if v["subject"] == "sai" or v["unsafe"] else "yes",
}


# ---------------------------------------------------------------- dữ liệu theo split


class View:
    """Mọi dòng của một split (kể cả dòng bị rule loại) + chỉ số hàng X của ảnh qua rule."""

    def __init__(self, ds, name: str):
        pos = {id(r): i for i, r in enumerate(ds.ok)}
        self.rows = [r for r in ds.rows if ds.side_of[r["image_url"]] == name]
        self.n = len(self.rows)
        self.human = np.array([r["human"] for r in self.rows])
        self.entity = np.array([r["entity_id"] for r in self.rows])
        self.rule = np.array([ds.rule_of.get(id(r), "") for r in self.rows])
        self.ok_pos = np.array([i for i, r in enumerate(self.rows) if id(r) in pos])
        self.ok_x = np.array([pos[id(self.rows[i])] for i in self.ok_pos])
        self.ok_groups = [ds.groups[j] for j in self.ok_x]
        self.ok_keys = [row_key(self.rows[i]) for i in self.ok_pos]


def evaluate(view: View, decision: np.ndarray) -> dict:
    """Lớp dương = no. Retention: entity có >= 1 ảnh người duyệt còn >= 1 ảnh tốt được duyệt."""
    h, d = view.human, decision
    tp = int(((h == "no") & (d == "no")).sum())
    fp = int(((h == "yes") & (d == "no")).sum())
    fn = int(((h == "no") & (d == "yes")).sum())
    tn = int(((h == "yes") & (d == "yes")).sum())
    good_ents = set(view.entity[h == "yes"])
    kept = set(view.entity[(h == "yes") & (d == "yes")])
    r_no, r_yes = tp / max(1, tp + fn), tn / max(1, tn + fp)
    p_no, p_yes = tp / max(1, tp + fp), tn / max(1, tn + fn)
    return {
        "n": view.n,
        "accuracy": round((tp + tn) / max(1, view.n), 4),
        "recall_no": round(r_no, 4),
        "precision_no": round(p_no, 4),
        "f1_no": round(2 * p_no * r_no / max(1e-9, p_no + r_no), 4),
        "precision_yes": round(p_yes, 4),
        "recall_yes": round(r_yes, 4),
        "balanced_accuracy": round((r_no + r_yes) / 2, 4),
        "entity_retention": round(len(kept) / max(1, len(good_ents)), 4),
        "approved_share": round(float((d == "yes").mean()), 4),
        "confusion": {"no→no": tp, "yes→no": fp, "no→yes": fn, "yes→yes": tn},
    }


def feasible(m: dict, ry: float, er: float) -> bool:
    return m["recall_yes"] >= ry and m["entity_retention"] >= er


def better(a: dict, b: dict | None, ry: float, er: float) -> bool:
    """Mục tiêu: max recall_no trong vùng khả thi; không khả thi thì ưu tiên gần ràng buộc nhất."""
    if b is None:
        return True
    fa, fb = feasible(a, ry, er), feasible(b, ry, er)
    if fa != fb:
        return fa
    if fa:
        return (a["recall_no"], a["precision_yes"]) > (b["recall_no"], b["precision_yes"])
    return min(a["recall_yes"] - ry, a["entity_retention"] - er) > min(
        b["recall_yes"] - ry, b["entity_retention"] - er
    )


# ---------------------------------------------------------------- mô phỏng router


def route(view: View, p_ok: np.ndarray, t: float, alpha: float) -> tuple[np.ndarray, set[int]]:
    pred = np.where(p_ok >= t, "yes", "no")
    if alpha <= 0:
        return pred, set()
    # conf như production (max(p, 1-p) khi t = 0,5), tổng quát cho ngưỡng t bất kỳ.
    conf = 0.5 + 0.5 * np.abs(p_ok - t) / max(t, 1 - t)
    chosen, _ = router.select(view.ok_groups, list(pred), conf, [False] * len(pred), alpha)
    return pred, chosen


def vlm_features(v: dict, p: float) -> list[float]:
    q = min(max(p, 1e-4), 1 - 1e-4)
    return [np.log(q / (1 - q)), v["subject"] == "dung", v["subject"] == "sai",
            float(v["watermark"]), float(v["unsafe"])]


def decide(view, p_ok, t, alpha, rule, vlm, learned=None):
    """-> (decision, reason, routed) cho mọi dòng của split."""
    decision = np.full(view.n, "no", dtype=object)
    reason = np.array([f"rule:{r}" if r else "" for r in view.rule], dtype=object)
    routed = np.zeros(view.n, bool)
    pred, chosen = route(view, p_ok, t, alpha)
    for j, pos in enumerate(view.ok_pos):
        decision[pos] = pred[j]
        reason[pos] = f"head:{pred[j]}"
    chosen = sorted(chosen)
    usable = [j for j in chosen if view.ok_keys[j] in vlm]
    if learned is not None and usable:
        q = learned.predict_proba([vlm_features(vlm[view.ok_keys[j]], p_ok[j]) for j in usable])[:, 1]
        labels = dict(zip(usable, np.where(q >= t, "yes", "no"), strict=True))
    for j in chosen:
        pos = view.ok_pos[j]
        routed[pos] = True
        v = vlm.get(view.ok_keys[j])
        if v is None:  # VLM lỗi: giữ quyết định classifier
            reason[pos] = f"vlm_missing:{pred[j]}"
            continue
        lab = labels[j] if learned is not None else RULES[rule](v)
        decision[pos] = lab
        tags = [v["subject"]] + (["watermark"] if v["watermark"] else []) + (
            ["unsafe"] if v["unsafe"] else [])
        reason[pos] = f"vlm:{lab}:{'+'.join(tags)}"
    return decision.astype(str), reason.astype(str), routed


def fit_learned(view, p_ok, t, alpha, vlm, cv: bool):
    """Logistic [logit p, subject, watermark, unsafe] trên ảnh được route của VAL."""
    _, chosen = route(view, p_ok, t, alpha)
    js = [j for j in sorted(chosen) if view.ok_keys[j] in vlm]
    if len(js) < 40:
        return None, None
    F = np.array([vlm_features(vlm[view.ok_keys[j]], p_ok[j]) for j in js], float)
    y = np.array([view.human[view.ok_pos[j]] == "yes" for j in js], int)
    if len(set(y)) < 2:
        return None, None
    model = LogisticRegression(max_iter=1000).fit(F, y)
    if not cv:
        return model, None
    groups = [view.entity[view.ok_pos[j]] for j in js]
    q = cross_val_predict(LogisticRegression(max_iter=1000), F, y, groups=groups,
                          cv=GroupKFold(min(5, len(set(groups)))), method="predict_proba")[:, 1]
    return model, dict(zip(js, q, strict=True))


def tune(val: View, p_val, alpha, vlm, ry, er):
    """Chọn (t, rule) trên VAL. 'learned' được chấm bằng dự đoán cross-validation trên VAL."""
    best, best_cfg = None, None
    for t in T_GRID:
        rules = ["head"] if alpha == 0 else [*RULES, "learned"]
        for rule in rules:
            if rule == "learned":
                _, oof = fit_learned(val, p_val, t, alpha, vlm, cv=True)
                if oof is None:
                    continue
                d, _, _ = decide(val, p_val, t, alpha, "goc", vlm)
                for j, q in oof.items():
                    d[val.ok_pos[j]] = "yes" if q >= t else "no"
            else:
                d, _, _ = decide(val, p_val, t, alpha, rule if alpha else "goc", vlm)
            m = evaluate(val, d)
            if better(m, best, ry, er):
                best, best_cfg = m, {"t": float(t), "rule": rule}
    return best_cfg, best


# ---------------------------------------------------------------- chi phí, latency, throughput


def cost_latency(view, routed, p_ok, perf, ds, infer_ms_per_1000):
    vlm_imgs = int(routed.sum())
    ok_share = len(view.ok_pos) / view.n
    usd_vlm = vlm_imgs / view.n * perf["vlm_usd_per_image"] * 1000
    gpu_s = ok_share * 1000 / perf["encode_ips"]
    usd_gpu = gpu_s * perf["gpu_usd_per_hour"] / 3600
    enc_ms = ENCODE_BATCH / perf["encode_ips"] * 1000  # chờ đủ một batch SigLIP2
    head_ms = infer_ms_per_1000 / 1000
    lat = []
    for j, pos in enumerate(view.ok_pos):
        f = ds.fetch.get(view.ok_keys[j], {}).get("ms") or 0
        v = perf["vlm_ms"].get(view.ok_keys[j], 0) if routed[pos] else 0
        lat.append(f + enc_ms + head_ms + v)
    lat = np.array(lat)
    routed_share = vlm_imgs / view.n
    tput = {
        "fetch": perf["fetch_ips"],
        "siglip2_gpu": round(perf["encode_ips"] / max(ok_share, 1e-9), 1),
        "vlm": round(perf["vlm_ips"] / routed_share, 1) if routed_share else None,
    }
    bottleneck = min((v, k) for k, v in tput.items() if v)
    return {
        "vlm_images": vlm_imgs,
        "routed_share": round(routed_share, 4),
        "usd_per_1000": round(usd_vlm + usd_gpu, 4),
        "usd_vlm_per_1000": round(usd_vlm, 4),
        "usd_gpu_per_1000": round(usd_gpu, 5),
        "latency_ms_p50": round(float(np.percentile(lat, 50))),
        "latency_ms_p95": round(float(np.percentile(lat, 95))),
        "throughput_ips_by_stage": tput,
        "throughput_ips": bottleneck[0],
        "bottleneck": bottleneck[1],
    }


def perf_inputs(ds, gpu_usd_per_hour: float) -> dict:
    human = json.loads(Path("reports/verify_human/report.json").read_text("utf-8"))
    collect_path = reports_dir() / "vlm_collect.json"
    collect = json.loads(collect_path.read_text("utf-8")) if collect_path.exists() else {}
    t5 = collect.get("t5_judge_batch", {})
    usd_img = (t5.get("usage", {}).get("usd", 0) / t5["images_called"]) if t5.get(
        "images_called") else FALLBACK_VLM_USD_PER_IMAGE
    vlm = read_cache(VLM_BATCH_FILE)
    # Chỉ ảnh tải mới trong lượt eval_verify_human (ảnh copy từ pilot không được đo giờ).
    pilot = {r["key"] for r in read_jsonl(Path("data/verify/fetch.jsonl"))} if Path(
        "data/verify/fetch.jsonl").exists() else set()
    fetched = sum(1 for k in ds.fetch if k not in pilot)
    return {
        "vlm_usd_per_image": usd_img,
        "vlm_ips": t5.get("images_per_second") or 18.3,
        "vlm_ms": {k: v.get("batch_ms", 0) for k, v in vlm.items()},
        "encode_ips": human["embedding"]["images_per_second"],
        "fetch_ips": round(fetched / human["seconds"]["fetch"], 1) if human["seconds"]["fetch"] else None,
        "gpu_usd_per_hour": gpu_usd_per_hour,
        "bootstrap_usd": collect.get("s3_bootstrap", {}).get("usage", {}).get("usd"),
        "collect": collect,
    }


# ---------------------------------------------------------------- chương trình chính


def train_models(ds, boot, log):
    models = {}
    for name, fn in [
        ("P0", lambda: bm.model_p0(ds, boot)),
        ("M0", lambda: bm.model_m0(ds)),
        ("M1", lambda: bm.model_m1(ds)),
        ("M1b", lambda: bm.model_m1b(ds)),
        ("M2", lambda: bm.model_m2(ds)),
    ]:
        if name == "P0" and not boot:
            log("[models] bỏ P0: chưa có nhãn bootstrap")
            continue
        try:
            models[name] = fn()
        except ValueError as exc:  # P0 khi bootstrap chưa đủ nhãn TRAIN/VAL
            log(f"[models] bỏ {name}: {exc}")
            continue
        log(f"[models] {name} xong ({models[name]['train_s']:.0f} s)")
    models["M3"] = bm.model_m3(ds, {k: models[k] for k in ("M0", "M1b", "M2")})
    # Suy luận: logistic đo trực tiếp; LightGBM đo trên một model huấn luyện một lần.
    for name in ("P0", "M0"):
        if name in models:
            models[name]["infer_ms_per_1000"] = bm.time_predict(models[name]["predict"], ds.X)
    for name, F in (("M1", ds.scalars), ("M1b", ds.X)):
        train_fn, _ = bm._lgb(F, ds.y)
        model = train_fn(*bm._inner_split(ds.groups, np.where(ds.side == "train")[0]))
        models[name]["infer_ms_per_1000"] = bm.time_predict(
            lambda X, m=model: m.predict(X, num_iteration=m.best_iteration), F)
    models["M3"]["infer_ms_per_1000"] = sum(
        models[k]["infer_ms_per_1000"] for k in ("M0", "M1b", "M2")) + models["M1"]["infer_ms_per_1000"]
    return models


def run(csv_path: str, ry: float, er: float, gpu_usd: float, log=print) -> dict:
    t_all = time.perf_counter()
    ds = load(csv_path)
    vlm = read_cache(VLM_BATCH_FILE)
    boot = read_cache(BOOT_FILE)
    picked_path = run_dir() / BOOT_PICKED_FILE
    if picked_path.exists():  # đúng mẫu phân tầng của collect, không lẫn nhãn thừa
        picked = set(json.loads(picked_path.read_text("utf-8")))
        boot = {k: v for k, v in boot.items() if k in picked}
    val, test = View(ds, "val"), View(ds, "test")
    cover = {s: round(sum(k in vlm for k in v.ok_keys) / max(1, len(v.ok_keys)), 4)
             for s, v in (("val", val), ("test", test))}
    log(f"[data] VAL {val.n} · TEST {test.n} · VLM phủ {cover} · bootstrap {len(boot)}")
    models = train_models(ds, boot, log)
    perf = perf_inputs(ds, gpu_usd)

    stage12 = {}
    for name, m in models.items():
        p = m["p"]
        cfg, _ = tune(val, p[val.ok_x], 0.0, vlm, ry, er)
        d, _, _ = decide(test, p[test.ok_x], cfg["t"], 0.0, "head", vlm)
        te = ds.side == "test"
        stage12[name] = {
            "labels": m["labels"],
            "auc_test": round(float(roc_auc_score(ds.y[te], p[te])), 4),
            "ece_test": round(float(metrics.ece(ds.y[te], p[te])), 4),
            "t_from_val": cfg["t"],
            "test": evaluate(test, d),
            "train_seconds": round(m["train_s"], 1),
            "infer_ms_per_1000": round(m["infer_ms_per_1000"], 2),
        }
        log(f"[stage1-2] {name} AUC {stage12[name]['auc_test']} · {stage12[name]['test']['recall_no']}")

    configs = []
    for name, m in models.items():
        p = m["p"]
        for alpha in BUDGETS:
            cfg, vm = tune(val, p[val.ok_x], alpha, vlm, ry, er)
            learned = None
            if cfg["rule"] == "learned":
                learned, _ = fit_learned(val, p[val.ok_x], cfg["t"], alpha, vlm, cv=False)
            d, reason, routed = decide(test, p[test.ok_x], cfg["t"], alpha,
                                       "goc" if cfg["rule"] in ("head", "learned") else cfg["rule"],
                                       vlm, learned)
            configs.append({
                "id": f"{name}@{int(alpha * 100)}%",
                "model": name,
                "alpha": alpha,
                **cfg,
                "val": vm,
                "test": evaluate(test, d),
                "ops": cost_latency(test, routed, p[test.ok_x], perf, ds,
                                    m["infer_ms_per_1000"]),
                "_decision": d, "_reason": reason, "_routed": routed,
            })
            log(f"[router] {configs[-1]['id']} t={cfg['t']} {cfg['rule']} "
                f"VAL R_no {vm['recall_no']} → TEST R_no {configs[-1]['test']['recall_no']}")

    # Production hiện tại, không tinh chỉnh: head từ nhãn VLM thầy, t = 0,5, α = 15%, prompt gốc.
    current = None
    if "P0" in models:
        p = models["P0"]["p"]
        d, reason, routed = decide(test, p[test.ok_x], 0.5, 0.15, "goc", vlm)
        current = {"id": "production hiện tại (P0, t=0.5, α=15%, prompt gốc)", "model": "P0",
                   "alpha": 0.15, "t": 0.5, "rule": "goc", "test": evaluate(test, d),
                   "ops": cost_latency(test, routed, p[test.ok_x], perf, ds,
                                       models["P0"]["infer_ms_per_1000"]),
                   "_decision": d, "_reason": reason, "_routed": routed}
        dv, _, _ = decide(val, p[val.ok_x], 0.5, 0.15, "goc", vlm)
        current["val"] = evaluate(val, dv)

    # Cùng điểm vận hành với production: chỉnh từng model (α = 15%) trên VAL sao cho Recall yes và
    # retention không thấp hơn production trên VAL, rồi so Recall no trên TEST.
    iso = []
    if current:
        ry_c, er_c = current["val"]["recall_yes"], current["val"]["entity_retention"]
        for name in [k for k in models if k != "P0"]:
            p = models[name]["p"]
            cfg, vm = tune(val, p[val.ok_x], 0.15, vlm, ry_c, er_c)
            learned = (fit_learned(val, p[val.ok_x], cfg["t"], 0.15, vlm, cv=False)[0]
                       if cfg["rule"] == "learned" else None)
            d, _, routed = decide(test, p[test.ok_x], cfg["t"], 0.15,
                                  "goc" if cfg["rule"] == "learned" else cfg["rule"], vlm, learned)
            iso.append({"id": f"{name}@15% (iso production)", "model": name, **cfg, "val": vm,
                        "test": evaluate(test, d)})
            log(f"[iso] {name}: TEST R_no {iso[-1]['test']['recall_no']} "
                f"R_yes {iso[-1]['test']['recall_yes']}")

    # Giai đoạn 4: chọn trên VAL (ràng buộc), hòa thì rẻ hơn.
    feas = [c for c in configs if feasible(c["val"], ry, er)]
    pool = feas or configs
    top = max(c["val"]["recall_no"] for c in pool)
    near = [c for c in pool if c["val"]["recall_no"] >= top - 0.005]
    chosen = min(near, key=lambda c: (c["ops"]["usd_per_1000"], -c["val"]["precision_yes"]))
    baselines = {
        "duyet_het": evaluate(test, np.full(test.n, "yes")),
        "chi_rule": evaluate(test, np.where(test.rule != "", "no", "yes")),
    }

    out = reports_dir()
    for c in [chosen] + ([current] if current else []):
        write_decisions(out / f"decisions_{c['model']}_{int(c['alpha'] * 100)}.csv", test, c,
                        models[c["model"]]["p"][test.ok_x], perf, ds, models[c["model"]])
    strip = lambda c: {k: v for k, v in c.items() if not k.startswith("_")}  # noqa: E731
    report = {
        "constraints": {"recall_yes_min": ry, "entity_retention_min": er},
        "vlm_coverage": cover,
        "bootstrap_labels": len(boot),
        "perf_inputs": {k: v for k, v in perf.items() if k not in ("vlm_ms", "collect")},
        "vlm_collect": perf["collect"],
        "stage12": stage12,
        "configs": [strip(c) for c in configs],
        "current_production": strip(current) if current else None,
        "iso_production": iso,
        "chosen": strip(chosen),
        "chosen_feasible_on_val": bool(feas),
        "chosen_reasons_test": dict(Counter(r.split(":")[0] + ":" + r.split(":")[1]
                                            for r in chosen["_reason"])),
        "baselines_test": baselines,
        "seconds": round(time.perf_counter() - t_all, 1),
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    (out / "report.md").write_text(render(report), "utf-8")
    log(f"[done] {out / 'report.md'}")
    return report


def write_decisions(path, view, c, p_ok, perf, ds, model):
    pos_to_j = {pos: j for j, pos in enumerate(view.ok_pos)}
    enc_ms = round(ENCODE_BATCH / perf["encode_ips"] * 1000, 1)
    head_ms = round(model["infer_ms_per_1000"] / 1000, 4)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["line", "entity_name", "image_url", "human", "decision", "decided_by", "reason",
                    "p_yes", "routed", "cost_usd", "fetch_ms", "encode_ms", "head_ms", "vlm_ms",
                    "total_ms"])
        for pos, r in enumerate(view.rows):
            j = pos_to_j.get(pos)
            key = row_key(r)
            reason = c["_reason"][pos]
            routed = bool(c["_routed"][pos])
            fetch_ms = ds.fetch.get(key, {}).get("ms") or 0
            vlm_ms = perf["vlm_ms"].get(key, 0) if routed else 0
            ok = j is not None
            w.writerow([
                r["line"], r["canonical_name"], r["image_url"], r["human"], c["_decision"][pos],
                reason.split(":")[0], reason, round(float(p_ok[j]), 4) if ok else "", int(routed),
                round(perf["vlm_usd_per_image"], 6) if routed else 0, fetch_ms,
                enc_ms if ok else 0, head_ms if ok else 0, vlm_ms,
                round(fetch_ms + (enc_ms + head_ms if ok else 0) + vlm_ms, 1),
            ])


# ---------------------------------------------------------------- báo cáo


def _p(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}"


def render(r: dict) -> str:
    c = r["constraints"]
    s12 = r["stage12"]
    L = [
        "# Benchmark router Phần A end-to-end (nhãn người `data/test.csv`)",
        "",
        f"Ràng buộc chọn cấu hình (trên VAL): Recall yes ≥ {c['recall_yes_min']:.0%}, entity "
        f"retention ≥ {c['entity_retention_min']:.0%}; trong vùng khả thi tối đa Recall no, hòa "
        "(±0,5 điểm) thì rẻ hơn. Mọi số liệu TEST bên dưới **không** được dùng để chọn.",
        "",
        f"VLM phủ ảnh qua rule: VAL {_p(r['vlm_coverage']['val'])}%, TEST "
        f"{_p(r['vlm_coverage']['test'])}%. Nhãn bootstrap cho P0: {r['bootstrap_labels']:,}.",
        "",
        "## Giai đoạn 1–2: classifier (không VLM, ngưỡng chọn trên VAL)",
        "",
        "| Model | Nhãn | AUC | ECE | Recall no | Precision yes | Recall yes | Retention | "
        "Train s | ms/1.000 ảnh |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, m in s12.items():
        t = m["test"]
        L.append(f"| {name} | {m['labels']} | {m['auc_test']:.3f} | {m['ece_test']:.3f} | "
                 f"{_p(t['recall_no'])} | {_p(t['precision_yes'])} | {_p(t['recall_yes'])} | "
                 f"{_p(t['entity_retention'])} | {m['train_seconds']} | {m['infer_ms_per_1000']} |")
    L += [
        "",
        "## Giai đoạn 3: router end-to-end theo ngân sách (cấu hình chọn trên VAL, số đo TEST)",
        "",
        "| Cấu hình | t | Đọc VLM | Gửi VLM | Recall no | Precision yes | Recall yes | Retention | "
        "Accuracy | $/1.000 ảnh | p95 ms |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows = r["configs"] + ([r["current_production"]] if r["current_production"] else [])
    for x in rows:
        t, o = x["test"], x["ops"]
        mark = " **← chọn**" if x.get("id") == r["chosen"]["id"] else ""
        L.append(f"| {x['id']}{mark} | {x['t']} | {x['rule']} | {_p(o['routed_share'])}% | "
                 f"{_p(t['recall_no'])} | {_p(t['precision_yes'])} | {_p(t['recall_yes'])} | "
                 f"{_p(t['entity_retention'])} | {_p(t['accuracy'])} | {o['usd_per_1000']:.3f} | "
                 f"{o['latency_ms_p95']:,} |")
    b = r["baselines_test"]
    L += [
        "",
        f"Baseline TEST: duyệt hết → Recall no 0%, Precision yes {_p(b['duyet_het']['precision_yes'])}%; "
        f"chỉ rule → Recall no {_p(b['chi_rule']['recall_no'])}%, Precision yes "
        f"{_p(b['chi_rule']['precision_yes'])}%, Recall yes {_p(b['chi_rule']['recall_yes'])}%.",
        "",
    ]
    cur = r["current_production"]
    if cur and r["iso_production"]:
        cv, ct = cur["val"], cur["test"]
        L += [
            "### So sánh cùng điểm vận hành với production hiện tại",
            "",
            f"Production hiện tại (P0, t = 0,5, α = 15%, prompt gốc) trên VAL có Recall yes "
            f"{_p(cv['recall_yes'])}%, retention {_p(cv['entity_retention'])}%. Mỗi model mới được "
            "chỉnh trên VAL để **không thấp hơn** hai mức đó, rồi so trên TEST:",
            "",
            "| Cấu hình | t | Đọc VLM | Recall no | Precision yes | Recall yes | Retention | Accuracy |",
            "|---|---:|---|---:|---:|---:|---:|---:|",
            f"| production hiện tại | 0.5 | goc | {_p(ct['recall_no'])} | {_p(ct['precision_yes'])} | "
            f"{_p(ct['recall_yes'])} | {_p(ct['entity_retention'])} | {_p(ct['accuracy'])} |",
            *[f"| {x['id']} | {x['t']} | {x['rule']} | {_p(x['test']['recall_no'])} | "
              f"{_p(x['test']['precision_yes'])} | {_p(x['test']['recall_yes'])} | "
              f"{_p(x['test']['entity_retention'])} | {_p(x['test']['accuracy'])} |"
              for x in r["iso_production"]],
            "",
        ]
    L += ["## Giai đoạn 4: cấu hình production", ""]
    ch = r["chosen"]
    t, o, v = ch["test"], ch["ops"], ch["val"]
    pi = r["perf_inputs"]
    L += [
        f"**{ch['id']}**: ngưỡng t = {ch['t']}, đọc VLM = `{ch['rule']}`"
        + ("" if r["chosen_feasible_on_val"] else " (⚠ không cấu hình nào đạt ràng buộc trên VAL)"),
        "",
        "| Chỉ số | VAL | TEST |",
        "|---|---:|---:|",
        *[f"| {k} | {_p(v[k])} | {_p(t[k])} |" for k in (
            "recall_no", "precision_no", "f1_no", "precision_yes", "recall_yes", "entity_retention",
            "balanced_accuracy", "accuracy", "approved_share")],
        "",
        f"- Gửi VLM: {o['vlm_images']:,} / {t['n']:,} ảnh TEST ({_p(o['routed_share'])}%).",
        f"- Chi phí: **${o['usd_per_1000']:.3f} / 1.000 ảnh** (VLM ${o['usd_vlm_per_1000']:.3f} + "
        f"GPU ${o['usd_gpu_per_1000']:.4f}, giả định GPU ${pi['gpu_usd_per_hour']}/giờ). "
        f"10M ảnh ≈ ${o['usd_per_1000'] * 10_000:,.0f}; 100M ≈ ${o['usd_per_1000'] * 100_000:,.0f}.",
        f"- Latency mỗi ảnh (tải + chờ batch SigLIP2 + classifier + VLM nếu route): p50 "
        f"{o['latency_ms_p50']:,} ms, **p95 {o['latency_ms_p95']:,} ms**.",
        f"- Throughput một máy (48 luồng tải, 1 GPU, 8 luồng VLM): **{o['throughput_ips']} ảnh/s**, "
        f"nút thắt `{o['bottleneck']}`; theo tầng {o['throughput_ips_by_stage']}.",
        "",
        "Ảnh TEST theo tầng quyết định:",
        "",
        "| Tầng:quyết định | Số ảnh |",
        "|---|---:|",
        *[f"| `{k}` | {n:,} |" for k, n in sorted(r["chosen_reasons_test"].items(), key=lambda kv: -kv[1])],
        "",
        "Đơn giá đầu vào: VLM "
        f"${pi['vlm_usd_per_image'] * 1000:.3f} / 1.000 ảnh (đo trong lượt thu), {pi['vlm_ips']} ảnh/s "
        f"(8 luồng); SigLIP2 {pi['encode_ips']} ảnh/s; tải {pi['fetch_ips']} ảnh/s (48 luồng)."
        + (f" Bootstrap P0 (một lần): ${pi['bootstrap_usd']}." if pi.get("bootstrap_usd") else ""),
        "",
    ]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.bench_verify_router")
    ap.add_argument("--csv", default="data/test.csv")
    ap.add_argument("--min-recall-yes", type=float, default=0.85)
    ap.add_argument("--min-entity-retention", type=float, default=0.95)
    ap.add_argument("--gpu-usd-per-hour", type=float, default=0.35)
    ap.add_argument("--verify-dir", default=DEFAULT_VERIFY_DIR)
    args = ap.parse_args()
    use_verify_dir(args.verify_dir)
    run(args.csv, args.min_recall_yes, args.min_entity_retention, args.gpu_usd_per_hour,
        log=lambda m: print(m, flush=True))


if __name__ == "__main__":
    main()
