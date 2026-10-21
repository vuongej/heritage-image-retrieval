"""Orchestrates S0..S7 of PIPELINE_WORKFLOW_JEV_TYPESAFE.md. Every stage checkpoints to
data/verify/ so a re-run resumes (downloads, embeddings, VLM and Jev answers are cached).
"""

from __future__ import annotations

import csv
import json
import os
import random
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from pipeline.verify import encoder, features, fetch, gate, head, metrics, router, split, vlm
from pipeline.verify.common import (
    category_bucket,
    read_csv,
    read_jsonl,
    row_key,
    run_dir,
    write_json,
    write_jsonl,
)
from pipeline.verify.jev import INSTRUCTIONS, Jev, JevUnavailable
from retrieval.deepseek import BudgetExhausted
from storage.runtime import data_dir


def log(msg: str) -> None:
    print(msg, flush=True)


# ----------------------------------------------------------------------------- helpers
def pick_pilot(live: list[dict], group_of: dict, n_groups: int, seed: int) -> list[dict]:
    """n_groups name groups, round-robin over category buckets (doc: 400 entities stratified)."""
    if n_groups <= 0:
        return live
    by_bucket: dict[str, set] = defaultdict(set)
    for r in live:
        by_bucket[category_bucket(r["category"])].add(group_of[r["image_url"]])
    rng = random.Random(seed)
    pools = []
    for b in sorted(by_bucket):
        gs = sorted(by_bucket[b])
        rng.shuffle(gs)
        pools.append(gs)
    rng.shuffle(pools)
    chosen: set = set()
    while len(chosen) < n_groups and any(pools):
        for pool in pools:
            while pool and pool[-1] in chosen:
                pool.pop()
            if pool and len(chosen) < n_groups:
                chosen.add(pool.pop())
    return [r for r in live if group_of[r["image_url"]] in chosen]


def usage_since(path: Path, start_line: int) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(x)
        for x in path.read_text(encoding="utf-8").splitlines()[start_line:]
        if x.strip()
    ]


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def thumb(key: str) -> bytes:
    return fetch.thumb_path(key).read_bytes()


def human_labels() -> dict[str, dict]:
    out = {}
    for rec in read_jsonl(run_dir() / "human_labels.jsonl"):
        out[rec["key"]] = rec  # latest wins
    return out


# ----------------------------------------------------------------------------- stages
def stage_embed(ok_rows: list[dict]) -> dict:
    """Embeddings are stored per key (union of every run), so scaling up only encodes new rows."""
    path = run_dir() / "emb.npz"
    parts = ("img", "name", "desc")
    store = {p: np.zeros((0, 0), np.float16) for p in parts}
    index: dict[str, int] = {}
    if path.exists():
        old = np.load(path, allow_pickle=False)
        if str(old["encoder"]) == encoder.ENCODER:
            store = {p: old[p] for p in parts}
            index = {k: i for i, k in enumerate(old["keys"].tolist())}
    keys = [row_key(r) for r in ok_rows]
    missing = [r for r, k in zip(ok_rows, keys, strict=True) if k not in index]
    stats = {"reused": len(keys) - len(missing)}
    if missing:
        new = encoder.embed(
            [fetch.thumb_path(row_key(r)) for r in missing],
            [r["canonical_name"] for r in missing],
            [r["description"] or r["canonical_name"] for r in missing],
            log=log,
        )
        stats.update(new["stats"])
        for p in parts:
            store[p] = new[p] if not index else np.concatenate([store[p], new[p]])
        for r in missing:
            index[row_key(r)] = len(index)
        np.savez(
            path,
            keys=np.array(sorted(index, key=index.get)),
            encoder=np.array(encoder.ENCODER),
            **store,
        )
    take = [index[k] for k in keys]
    return {"emb": {p: store[p][take] for p in parts}, "stats": stats}


def stage_bootstrap(rows: list[dict], workers: int) -> dict[str, dict]:
    path = run_dir() / "labels_boot.jsonl"
    labels = {r["key"]: r for r in read_jsonl(path)}
    todo = [r for r in rows if row_key(r) not in labels]
    log(f"[S3] bootstrap VLM labels: {len(labels)} cached, {len(todo)} to label")
    stop = {"reason": None}

    def one(r):
        if stop["reason"]:
            return None
        try:
            return {"key": row_key(r), **vlm.label_single(r, thumb(row_key(r)))}
        except BudgetExhausted as exc:
            stop["reason"] = str(exc)
        except Exception as exc:  # one bad image never aborts the batch
            return {"key": row_key(r), "label": None, "error": f"{type(exc).__name__}: {exc}"[:200]}
        return None

    done = 0
    with ThreadPoolExecutor(workers) as pool:
        for res in pool.map(one, todo):
            if res and res.get("label"):
                labels[res["key"]] = res
            done += 1
            if done % 200 == 0:
                log(f"[S3] {done}/{len(todo)}")
                write_jsonl(path, labels.values())
    write_jsonl(path, labels.values())
    if stop["reason"]:
        log(f"[S3] stopped softly: {stop['reason']} — remaining rows stay unlabelled")
    return labels


def stage_jev(items: list[tuple[str, str]], workers: int) -> tuple[dict[str, dict], str | None]:
    """items: (key, state). Returns decisions and the reason Jev did not run (if any)."""
    path = run_dir() / "decisions_jev.jsonl"
    decisions = {d["key"]: d for d in read_jsonl(path)}
    client = Jev()
    if not client.enabled:
        return (
            decisions,
            "OPENROUTER_API_KEY trống trong .env — bỏ qua Jev, dùng head đã hiệu chỉnh",
        )
    todo = [(k, s) for k, s in items if k not in decisions]
    log(f"[S4] Jev ({client.model}): {len(decisions)} cached, {len(todo)} to decide")

    def one(item):
        key, state = item
        try:
            return {"key": key, **client.decide(state)}
        except JevUnavailable:
            return None
        except Exception as exc:
            return {"key": key, "verify": "defer", "error": f"{type(exc).__name__}: {exc}"[:200]}

    done = 0
    with ThreadPoolExecutor(workers) as pool:
        for res in pool.map(one, todo):
            if res:
                decisions[res["key"]] = res
            done += 1
            if done % 200 == 0:
                log(f"[S4] {done}/{len(todo)}")
                write_jsonl(path, decisions.values())
    write_jsonl(path, decisions.values())
    return decisions, client.stopped


def stage_vlm_cascade(
    chosen: list[int],
    target: list[dict],
    conf: np.ndarray,
    group_of: dict,
    ok_by_group: dict[str, list[dict]],
    states: dict[str, str],
    workers: int,
    second_share: float,
) -> dict[str, dict]:
    """T5: entity batches of <= 8 images; 2 runs on the most uncertain; disagreement -> Jev judge."""
    path = run_dir() / "vlm_results.jsonl"
    results = {r["key"]: r for r in read_jsonl(path)}
    by_group: dict[str, list[dict]] = defaultdict(list)
    for i in chosen:
        by_group[group_of[target[i]["image_url"]]].append(target[i])

    def batches(rows_by_group, fill: bool):
        out = []
        for g, rows in rows_by_group.items():
            keys = {row_key(r) for r in rows}
            for s in range(0, len(rows), vlm.BATCH_MAX):
                part = rows[s : s + vlm.BATCH_MAX]
                ctx = []
                if fill:  # comparison context: other images of the same entity, up to 4 total
                    ctx = [r for r in ok_by_group[g] if row_key(r) not in keys][
                        : max(0, 4 - len(part))
                    ]
                out.append((part[0], part, ctx))
        return out

    stop = {"reason": None}

    def run_batch(item, temperature):
        entity, part, ctx = item
        if stop["reason"]:
            return {}
        imgs = [(row_key(r), thumb(row_key(r))) for r in [*part, *ctx]]
        try:
            verdicts = vlm.judge_batch(entity, imgs, temperature=temperature)
        except BudgetExhausted as exc:
            stop["reason"] = str(exc)
            return {}
        except Exception as exc:
            return {
                row_key(r): {"label": None, "error": f"{type(exc).__name__}: {exc}"[:200]}
                for r in part
            }
        return {row_key(r): verdicts[row_key(r)] for r in part}

    todo = {
        g: [r for r in rows if not results.get(row_key(r), {}).get("run1", {}).get("label")]
        for g, rows in by_group.items()
    }
    todo = {g: rows for g, rows in todo.items() if rows}
    first = batches(todo, fill=True)
    log(f"[S5] VLM batch: {sum(len(b[1]) for b in first)} images in {len(first)} calls")
    with ThreadPoolExecutor(workers) as pool:
        for out in pool.map(lambda b: run_batch(b, 0), first):
            for k, v in out.items():
                results[k] = {"key": k, "run1": v}
    write_jsonl(path, results.values())

    # Most uncertain share of the target: an independent second run at temperature 0.3.
    k_second = int(round(second_share * len(target)))
    ranked = sorted(chosen, key=lambda i: conf[i])[:k_second]
    need = defaultdict(list)
    for i in ranked:
        r = target[i]
        rec = results.get(row_key(r))
        if rec and rec.get("run1", {}).get("label") and "run2" not in rec:
            need[group_of[r["image_url"]]].append(r)
    second = batches(need, fill=True)
    log(f"[S5] second run for agreement: {sum(len(b[1]) for b in second)} images")
    with ThreadPoolExecutor(workers) as pool:
        for out in pool.map(lambda b: run_batch(b, 0.3), second):
            for k, v in out.items():
                results[k]["run2"] = v
    jev = Jev()
    for rec in results.values():
        r1, r2 = rec.get("run1", {}), rec.get("run2")
        if not r1.get("label"):
            rec.update(label=None, how="vlm_error")
        elif r2 is None or not r2.get("label"):
            rec.update(label=r1["label"], how="vlm_1run")
        elif r1["label"] == r2["label"]:
            rec.update(label=r1["label"], how="vlm_2run_agree")
        else:
            rec.update(label="no", how="vlm_disagree_no_judge")
            if jev.enabled and not jev.stopped:
                question = (
                    states.get(rec["key"], "")
                    + f"\nVLM lần 1: {json.dumps(r1, ensure_ascii=False)}"
                    + f"\nVLM lần 2: {json.dumps(r2, ensure_ascii=False)}"
                    + "\nHai lần chấm không đồng thuận. Theo state này, nếu đủ chắc thì trả yes/no; "
                    "nếu vẫn phân vân thì defer (chuyển cho người)."
                )
                try:
                    d = jev.decide(question, INSTRUCTIONS, tag="judge")
                    if d["verify"] in ("yes", "no"):
                        rec.update(label=d["verify"], how="jev_judge", judge=d)
                    else:
                        rec.update(how="jev_judge_defer_no", judge=d)
                except Exception as exc:
                    rec["judge_error"] = str(exc)[:200]
    write_jsonl(path, results.values())
    if stop["reason"]:
        log(f"[S5] stopped softly: {stop['reason']}")
    return results


def _crossfit_ece(conf: np.ndarray, correct: np.ndarray) -> float | None:
    """Isotonic fitted on one half of VAL, ECE measured on the other half (and swapped)."""
    from sklearn.isotonic import IsotonicRegression

    idx = np.arange(len(conf))
    out = []
    for a, b in ((idx[::2], idx[1::2]), (idx[1::2], idx[::2])):
        if len(a) and len(b):
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(
                conf[a], correct[a]
            )
            out.append(metrics.confidence_ece(correct[b], iso.predict(conf[b])))
    return round(float(np.mean(out)), 4) if out else None


# ----------------------------------------------------------------------------- main run
def bootstrap_sample(ok_rows: list[dict], n: int, seed: int) -> list[dict]:
    """n rows round-robin over category buckets (skill_05: 5.000 stratified). n <= 0 -> all."""
    if n <= 0 or n >= len(ok_rows):
        return ok_rows
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for r in ok_rows:
        by_bucket[category_bucket(r["category"])].append(r)
    rng = random.Random(seed)
    pools = [by_bucket[b] for b in sorted(by_bucket)]
    for pool in pools:
        rng.shuffle(pool)
    picked: list[dict] = []
    while len(picked) < n:
        for pool in pools:
            if pool and len(picked) < n:
                picked.append(pool.pop())
    return picked


def run(
    csv_path: str,
    out: str,
    entities: int,
    budget: float,
    seed: int,
    workers: int,
    noext_policy: str,
    target_split: str,
    second_share: float,
    skip_vlm: bool,
    bootstrap_n: int = 0,
) -> dict:
    t_all = time.perf_counter()
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    timing: dict[str, float] = {}
    t = time.perf_counter()

    # S0 gate
    rows = read_csv(csv_path)
    live, gate_report = gate.run(rows, noext_policy)
    write_json(run_dir() / "gate_report.json", gate_report)
    log(
        f"[S0] gate: {gate_report['live_rows']}/{gate_report['source_rows']} live · {gate_report['by_rule']}"
    )
    timing["S0_gate"] = time.perf_counter() - t

    # S2b split (on ALL live rows, so the pilot is a subset of the real split)
    t = time.perf_counter()
    sp = split.split(live, seed=seed)
    write_json(run_dir() / "split.json", {"report": sp["report"], "assignment": sp["assignment"]})
    side_of, group_of = sp["assignment"], sp["group_of_url"]
    log(f"[S2b] split: {sp['report']['rows']} rows · {sp['report']['groups']} groups")
    timing["S2b_split"] = time.perf_counter() - t

    pilot = pick_pilot(live, group_of, entities, seed)
    log(f"[pilot] {len({group_of[r['image_url']] for r in pilot})} groups · {len(pilot)} rows")

    # S1a download
    t = time.perf_counter()
    state = fetch.run(pilot, workers=max(workers * 4, 32), log=log)
    dups = fetch.mark_sha_duplicates(pilot, state)
    fetch_counts = Counter(state[row_key(r)]["status"] for r in pilot)
    timing["S1_download"] = time.perf_counter() - t
    log(f"[S1] fetch: {dict(fetch_counts)} (sha256 dups {dups})")
    ok_rows = [r for r in pilot if state[row_key(r)]["status"] == "ok"]
    # Cross-split content leakage: identical bytes on two sides -> drop the TEST copy.
    sha_side = defaultdict(set)
    for r in ok_rows:
        sha_side[state[row_key(r)]["sha256"]].add(side_of[r["image_url"]])
    leaked = {s for s, sides in sha_side.items() if len(sides) > 1}
    ok_rows = [
        r
        for r in ok_rows
        if not (state[row_key(r)]["sha256"] in leaked and side_of[r["image_url"]] == "test")
    ]

    # S1b embeddings
    t = time.perf_counter()
    em = stage_embed(ok_rows)
    timing["S1_encode"] = time.perf_counter() - t
    log(f"[S1] embeddings: {em['stats']}")

    # S2 features
    t = time.perf_counter()
    groups = [group_of[r["image_url"]] for r in ok_rows]
    fetched = [state[row_key(r)] for r in ok_rows]
    X, feats = features.build(ok_rows, fetched, em["emb"], groups, features.priors(rows))
    timing["S2_features"] = time.perf_counter() - t

    # S3 bootstrap labels (VLM teacher). Pilot: label every ok row (also TEST, as proxy truth).
    t = time.perf_counter()
    ds_usage = data_dir() / "deepseek_usage.jsonl"
    ds_start = line_count(ds_usage)
    boot = stage_bootstrap(bootstrap_sample(ok_rows, bootstrap_n, seed), workers)
    timing["S3_bootstrap"] = time.perf_counter() - t
    keys = [row_key(r) for r in ok_rows]
    y = np.array([{"yes": 1, "no": 0}.get((boot.get(k) or {}).get("label"), -1) for k in keys])
    side = np.array([side_of[r["image_url"]] for r in ok_rows])
    log(f"[S3] labelled {int((y >= 0).sum())}/{len(y)} · yes rate {y[y >= 0].mean():.3f}")

    # S4a head
    t = time.perf_counter()
    hd = head.train(X, y, side, np.array(groups))
    p_cal = hd["p_cal"]
    log(f"[S4] head: {hd['report']}")
    states = {
        k: features.state_text(r, f, float(p))
        for k, r, f, p in zip(keys, ok_rows, feats, p_cal, strict=True)
    }
    write_jsonl(
        run_dir() / "states.jsonl",
        (
            {"key": k, "split": s, "head_p_yes": round(float(p), 4), "state": states[k]}
            for k, s, p in zip(keys, side, p_cal, strict=True)
        ),
    )
    timing["S4_head"] = time.perf_counter() - t

    # S4b Jev on VAL (calibration) + target
    t = time.perf_counter()
    jev_start = line_count(data_dir() / "jev_usage.jsonl")
    jev_rows = [i for i, s in enumerate(side) if s == "val" or target_split in ("all", s)]
    decisions, jev_skip = stage_jev([(keys[i], states[keys[i]]) for i in jev_rows], workers=16)
    timing["S4_jev"] = time.perf_counter() - t
    if jev_skip:
        log(f"[S4] {jev_skip}")

    # Decision layers: head (always) and jev (when decisions exist)
    head_pred = np.where(p_cal >= 0.5, "yes", "no")
    head_conf = np.maximum(p_cal, 1 - p_cal)
    layers = {"head": (head_pred, head_conf, np.zeros(len(keys), bool))}
    jev_report = None
    have_jev = np.array(
        [
            keys[i] in decisions and decisions[keys[i]].get("verify") in ("yes", "no", "defer")
            for i in range(len(keys))
        ]
    )
    if have_jev[side == "val"].sum() >= 20:
        from sklearn.isotonic import IsotonicRegression

        jpred = head_pred.copy()
        jraw = np.zeros(len(keys))
        jdefer = np.zeros(len(keys), bool)
        src = Counter()
        for i, k in enumerate(keys):
            d = decisions.get(k)
            if not d or d.get("verify") not in ("yes", "no", "defer"):
                continue
            if d["verify"] == "defer":
                jdefer[i] = True
                continue
            jpred[i] = d["verify"]
            c = d.get("conf_logprob")
            src["logprob" if c is not None else "self"] += 1
            jraw[i] = c if c is not None else d.get("conf_self", 0.5)
        va = (side == "val") & (y >= 0) & have_jev & ~jdefer
        correct_va = (jpred[va] == np.where(y[va] == 1, "yes", "no")).astype(float)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(
            jraw[va], correct_va
        )
        jconf = np.where(jdefer | ~have_jev, 0.0, iso.predict(jraw))
        layers["jev"] = (jpred, jconf, jdefer)
        jev_report = {
            "decided": int(have_jev.sum()),
            "defer_share": round(float(jdefer[have_jev].mean()), 4),
            "confidence_source": dict(src),
            "ece_val_raw": round(metrics.confidence_ece(correct_va, jraw[va]), 4),
            "ece_val_calibrated_crossfit": _crossfit_ece(jraw[va], correct_va),
            "agreement_with_head_when_decided": round(
                float((jpred[have_jev & ~jdefer] == head_pred[have_jev & ~jdefer]).mean()), 4
            ),
            "errors": sum("error" in decisions[k] for k in keys if k in decisions),
            "routed_models": dict(
                Counter(decisions[k].get("routed_model") for k in keys if k in decisions)
            ),
        }
    primary = "jev" if "jev" in layers else "head"

    # Evaluation rows: target split, labelled by the teacher
    target_mask = np.array([target_split == "all" or s == target_split for s in side])
    tgt_idx = np.where(target_mask)[0]
    truth = np.where(y == 1, "yes", np.where(y == 0, "no", ""))
    layer_eval = {}
    for name, (pred, conf, _deferred) in layers.items():
        m = tgt_idx[(y[tgt_idx] >= 0)]
        correct = (pred[m] == truth[m]).astype(float)
        layer_eval[name] = {
            "proxy_rows": len(m),
            "proxy_agreement_all": round(float(correct.mean()), 4) if len(m) else None,
            "risk_coverage": metrics.risk_coverage(correct, conf[m]),
            "ece_conf": round(metrics.confidence_ece(correct, conf[m]), 4) if len(m) else None,
        }

    lab_t = tgt_idx[y[tgt_idx] >= 0]
    if len(lab_t):
        hd["report"]["ece_target_raw"] = round(metrics.ece(y[lab_t], hd["p_raw"][lab_t]), 4)
        hd["report"]["ece_target_calibrated"] = round(metrics.ece(y[lab_t], p_cal[lab_t]), 4)

    # T4 router on the primary layer, then T5 VLM
    pred, conf, deferred = layers[primary]
    target = [ok_rows[i] for i in tgt_idx]
    t_groups = [groups[i] for i in tgt_idx]
    chosen_local, route_report = router.select(
        t_groups, list(pred[tgt_idx]), conf[tgt_idx], list(deferred[tgt_idx]), budget
    )
    # conformal check: theta from VAL uncertainty, actual exceedance on TARGET
    val_u = 1 - conf[side == "val"]
    if len(val_u):
        theta = router.conformal_threshold(val_u, budget)
        route_report["conformal_theta_val"] = round(theta, 4)
        route_report["target_share_above_theta"] = round(
            float(((1 - conf[tgt_idx]) > theta).mean()), 4
        )
    log(f"[S4] router ({primary}): {route_report}")
    ok_by_group = defaultdict(list)
    for r, g in zip(ok_rows, groups, strict=True):
        ok_by_group[g].append(r)
    t = time.perf_counter()
    vlm_results = {}
    if not skip_vlm and chosen_local:
        vlm_results = stage_vlm_cascade(
            sorted(chosen_local),
            target,
            conf[tgt_idx],
            group_of,
            ok_by_group,
            states,
            workers,
            second_share,
        )
    timing["S5_vlm"] = time.perf_counter() - t

    # S6 merge
    final = {}
    for j, i in enumerate(tgt_idx):
        k = keys[i]
        note = ""
        lab = pred[i]
        how = primary
        if j in chosen_local:
            v = vlm_results.get(k, {})
            if v.get("label"):
                lab, how = v["label"], v.get("how", "vlm")
                r1 = v.get("run1", {})
                if r1.get("watermark"):
                    note = "CẦN VERIFY TAY: có logo/watermark/chữ chèn"
                elif r1.get("subject") == "partial":
                    note = "CẦN VERIFY TAY: khớp một phần (cùng không gian văn hoá)"
                if how.endswith("_no") or how == "vlm_disagree_no_judge":
                    note = "máy không chắc chắn (VLM bất đồng thuận)"
            else:
                how = f"{primary}_vlm_pending"
        if not note and conf[i] < 0.75:
            note = f"CẦN VERIFY TAY: độ tự tin thấp ({conf[i]:.2f})"
        final[k] = {"verify": lab, "how": how, "note": note, "conf": round(float(conf[i]), 4)}

    # Cascade agreement with the teacher (proxy) on the target
    m = [i for i in tgt_idx if y[i] >= 0]
    cascade_proxy = None
    if m:
        agree = np.array([final[keys[i]]["verify"] == truth[i] for i in m], float)
        routed = np.array([final[keys[i]]["how"].startswith(("vlm", "jev_judge")) for i in m])
        cascade_proxy = {
            "rows": len(m),
            "agreement_all": round(float(agree.mean()), 4),
            "agreement_keep": round(float(agree[~routed].mean()), 4) if (~routed).any() else None,
            "agreement_routed_vlm": round(float(agree[routed].mean()), 4) if routed.any() else None,
            "routed_share": round(float(routed.mean()), 4),
        }

    # CSV flag = the human decision already made: approved -> yes. With an all-approved file
    # only the false-reject side is measurable (accuracy = share predicted yes).
    approved_eval = None
    flag_yes = np.array([ok_rows[i].get("flag", "").lower() == "approved" for i in tgt_idx])
    flag_no = np.array([ok_rows[i].get("flag", "").lower() in ("rejected", "no") for i in tgt_idx])
    if flag_yes.any() or flag_no.any():
        human_flag = np.where(flag_yes, "yes", np.where(flag_no, "no", ""))
        known = human_flag != ""

        def agree(pred_arr):
            return round(float((np.asarray(pred_arr)[known] == human_flag[known]).mean()), 4)

        wm_only = np.array(
            [
                (b := boot.get(keys[i])) is not None
                and b["label"] == "no"
                and b["scores"]["watermark"] >= 0.5
                and b["scores"]["relevance"] >= 0.5
                and max(b["scores"][x] for x in ("nsfw", "violence", "politics")) < 0.5
                for i in tgt_idx
            ]
        )
        teacher = np.array([truth[i] or "no" for i in tgt_idx])
        approved_eval = {
            "rows": int(known.sum()),
            "approved": int(flag_yes.sum()),
            "rejected": int(flag_no.sum()),
            "accuracy_vlm_teacher": agree(teacher),
            "accuracy_vlm_teacher_if_watermark_allowed": agree(np.where(wm_only, "yes", teacher)),
            "accuracy_head": agree(head_pred[tgt_idx]),
            **({"accuracy_jev": agree(layers["jev"][0][tgt_idx])} if "jev" in layers else {}),
            "accuracy_cascade": agree([final[keys[i]]["verify"] for i in tgt_idx]),
            "measurable": "false-reject only" if not flag_no.any() else "both classes",
        }

    # Human labels -> real accuracy (the only number allowed to be called accuracy)
    human = human_labels()
    human_eval = None
    hk = [i for i in tgt_idx if keys[i] in human]
    if hk:
        ht = np.array([human[keys[i]]["label"] for i in hk])
        rnd = np.array([human[keys[i]].get("stratum") == "random" for i in hk])

        def acc(pred_arr, mask=None):
            mm = np.ones(len(hk), bool) if mask is None else mask
            return round(float((pred_arr[mm] == ht[mm]).mean()), 4) if mm.any() else None

        cascade_pred = np.array([final[keys[i]]["verify"] for i in hk])
        teacher = np.array([truth[i] or "?" for i in hk])
        human_eval = {
            "labelled": len(hk),
            "random_stratum": int(rnd.sum()),
            "accuracy_cascade_all": acc(cascade_pred),
            "accuracy_cascade_random_stratum": acc(cascade_pred, rnd),
            "accuracy_vlm_teacher_single": acc(teacher),
            "accuracy_head": acc(head_pred[hk]),
            **({"accuracy_jev": acc(layers["jev"][0][hk])} if "jev" in layers else {}),
        }

    # Audit queue for the human labelling tab: 70% random (unbiased) + 30% hard (conf 0.4-0.8)
    rng = random.Random(seed)
    pool_idx = [i for i in tgt_idx if keys[i] not in human]
    hard = [i for i in pool_idx if 0.4 <= conf[i] <= 0.8]
    rng.shuffle(pool_idx)
    rng.shuffle(hard)
    n_audit = int(os.getenv("VERIFY_AUDIT_SIZE", "300"))
    take_hard = hard[: int(n_audit * 0.3)]
    take_rand = [i for i in pool_idx if i not in set(take_hard)][: n_audit - len(take_hard)]
    write_jsonl(
        run_dir() / "audit_queue.jsonl",
        (
            {
                "key": keys[i],
                "stratum": s,
                "entity": ok_rows[i]["canonical_name"],
                "category": ok_rows[i]["category"],
                "description": ok_rows[i]["description"],
                "image_url": ok_rows[i]["image_url"],
                "source_url": ok_rows[i].get("source_url", ""),
            }
            for s, ids in (("random", take_rand), ("hard", take_hard))
            for i in ids
        ),
    )

    # S7 export: original columns + verify + note (target rows + gate/dead rows of the pilot)
    out_csv = out_dir / f"{Path(csv_path).stem}_{target_split}_verified.csv"
    fields = [c for c in rows[0] if c != "line"] + ["verify", "note"]
    gate_codes = {g["image_url"]: g["gate"] for g in gate_report["rejected"]}
    pilot_groups = {group_of[r["image_url"]] for r in pilot}
    with out_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        w = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            u = r["image_url"]
            if u in gate_codes:
                continue
            if group_of.get(u) not in pilot_groups or (
                target_split != "all" and side_of.get(u) != target_split
            ):
                continue
            k = row_key(r)
            rec = state.get(k, {})
            r = {**r, "sha256": rec.get("sha256") or r.get("sha256", "")}  # real content hash
            if k in final:
                w.writerow({**r, "verify": final[k]["verify"], "note": final[k]["note"]})
            else:
                note = {
                    "dead": "link chết sau 3 lần thử",
                    "too_small": "ảnh < 300x200",
                    "dup_sha256": "trùng nội dung trong thực thể",
                    "ok": "trùng nội dung với ảnh của thực thể khác (tập train)",
                }.get(rec.get("status"), rec.get("status", "chưa tải"))
                w.writerow({**r, "verify": "no", "note": note})

    # Cost
    ds_events = usage_since(ds_usage, ds_start)
    by_tag = defaultdict(
        lambda: {"requests": 0, "prompt_tokens": 0, "cache_hit_tokens": 0, "completion_tokens": 0}
    )
    for e in ds_events:
        b = by_tag[e.get("tag", "other")]
        b["requests"] += 1
        b["prompt_tokens"] += e["usage"].get("prompt_tokens", 0)
        b["cache_hit_tokens"] += e["usage"].get("prompt_cache_hit_tokens", 0)
        b["completion_tokens"] += e["usage"].get("completion_tokens", 0)
    jev_events = usage_since(data_dir() / "jev_usage.jsonl", jev_start)
    price_in = float(os.getenv("DEEPSEEK_PRICE_INPUT_PER_MTOK", "0") or 0)
    price_hit = float(os.getenv("DEEPSEEK_PRICE_CACHE_HIT_PER_MTOK", "0") or 0)
    price_out = float(os.getenv("DEEPSEEK_PRICE_OUTPUT_PER_MTOK", "0") or 0)
    cost = {
        "deepseek_this_run": dict(by_tag),
        "deepseek_usd_estimate": (
            round(
                sum(
                    (b["prompt_tokens"] - b["cache_hit_tokens"]) * price_in
                    + b["cache_hit_tokens"] * price_hit
                    + b["completion_tokens"] * price_out
                    for b in by_tag.values()
                )
                / 1e6,
                4,
            )
            if price_in or price_out
            else "đặt DEEPSEEK_PRICE_*_PER_MTOK trong .env để quy ra USD"
        ),
        "jev_this_run": {
            "requests": len(jev_events),
            "usd": round(sum(e.get("cost") or 0 for e in jev_events), 6),
            "prompt_tokens": sum(e.get("prompt_tokens") or 0 for e in jev_events),
            "mean_ms": round(np.mean([e["ms"] for e in jev_events])) if jev_events else None,
        },
        "cache_note": "VLM/Jev answers are cached; a re-run only pays for new requests",
    }

    timing["total"] = time.perf_counter() - t_all
    final_labels = [final[keys[i]]["verify"] for i in tgt_idx]
    report = {
        "csv": csv_path,
        "seed": seed,
        "pilot_groups": entities,
        "target_split": target_split,
        "budget_alpha": budget,
        "gate": {k: v for k, v in gate_report.items() if k != "rejected"},
        "split": sp["report"],
        "pilot_rows": len(pilot),
        "fetch": dict(fetch_counts),
        "sha256_dups_in_entity": dups,
        "cross_split_content_leaks_dropped": len(leaked),
        "embedding": em["stats"],
        "bootstrap": {
            "labelled": int((y >= 0).sum()),
            "yes_rate": round(float(y[y >= 0].mean()), 4),
        },
        "head": hd["report"],
        "jev": jev_report or {"status": jev_skip or "not enough Jev decisions on VAL"},
        "primary_layer": primary,
        "layers_proxy_eval": layer_eval,
        "router": route_report,
        "vlm": dict(Counter(v.get("how") for v in vlm_results.values())),
        "cascade_proxy": cascade_proxy,
        "approved_flag_eval": approved_eval,
        "human_eval": human_eval
        or {"status": "chưa có nhãn người — gán nhãn ở tab 'Gán nhãn' của giao diện"},
        "entity_level": metrics.entity_level(t_groups, final_labels),
        "by_category": metrics.crosstab(
            [category_bucket(r["category"]) for r in target],
            [truth[i] for i in tgt_idx],
            final_labels,
        ),
        "by_host": metrics.crosstab(
            [f["host"] for f in (feats[i] for i in tgt_idx)],
            [truth[i] for i in tgt_idx],
            final_labels,
        ),
        "cost": cost,
        "seconds": {k: round(v, 2) for k, v in timing.items()},
        "verified_csv": str(out_csv),
        "proxy_warning": "proxy_* / agreement_* = đồng thuận với nhãn VLM bootstrap, KHÔNG phải accuracy (skill_06 bẫy #3)",
    }
    write_json(out_dir / "report.json", report)
    from pipeline.verify.report import write_markdown

    write_markdown(report, out_dir)
    log(f"[done] {out_dir / 'report.json'} · {timing['total']:.1f}s")
    return report
