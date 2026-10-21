"""Reporting checklist (skill_06): risk-coverage, AURC, ECE, entity level, cross-tabs."""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

COVERAGE_ALPHAS = (0.05, 0.10, 0.15, 0.20, 0.30)


def ece(y, p, bins: int = 10) -> float:
    """Binary-probability ECE: |mean(y) - mean(p)| weighted by bin size."""
    y, p = np.asarray(y, float), np.asarray(p, float)
    if not len(y):
        return float("nan")
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            total += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(total)


def confidence_ece(correct, conf, bins: int = 10) -> float:
    """ECE of a decision's confidence: |accuracy - confidence| per bin."""
    return ece(correct, conf, bins)


def risk_coverage(correct, conf) -> dict:
    """Keep the most confident (1-alpha) share; report accuracy there; AURC over all coverages."""
    correct = np.asarray(correct, float)
    order = np.argsort(-np.asarray(conf, float), kind="stable")
    c = correct[order]
    n = len(c)
    if not n:
        return {"points": [], "aurc": None}
    cum_acc = np.cumsum(c) / np.arange(1, n + 1)
    points = [{"alpha": 0.0, "coverage": 1.0, "acc_keep": round(float(cum_acc[-1]), 4)}]
    for a in COVERAGE_ALPHAS:
        k = max(1, int(round((1 - a) * n)))
        points.append(
            {"alpha": a, "coverage": round(k / n, 4), "acc_keep": round(float(cum_acc[k - 1]), 4)}
        )
    return {"points": points, "aurc": round(float(np.mean(1 - cum_acc)), 4)}


def entity_level(groups, final_labels) -> dict:
    yes = defaultdict(int)
    for g, lab in zip(groups, final_labels, strict=True):
        yes[g] += lab == "yes"
    counts = list(yes.values())
    if not counts:
        return {}
    return {
        "entities": len(counts),
        "share_ge3_yes": round(sum(c >= 3 for c in counts) / len(counts), 4),
        "share_ge5_yes": round(sum(c >= 5 for c in counts) / len(counts), 4),
        "median_yes": float(np.median(counts)),
    }


def crosstab(keys, y_true, y_pred, top: int = 12) -> list[dict]:
    rows = defaultdict(lambda: [0, 0, 0])
    for k, t, p in zip(keys, y_true, y_pred, strict=True):
        r = rows[k]
        r[0] += 1
        r[1] += t == "yes"
        r[2] += t == p
    most = Counter({k: v[0] for k, v in rows.items()}).most_common(top)
    return [
        {
            "key": k,
            "n": n,
            "yes_rate": round(rows[k][1] / n, 3),
            "agreement": round(rows[k][2] / n, 3),
        }
        for k, n in most
    ]
