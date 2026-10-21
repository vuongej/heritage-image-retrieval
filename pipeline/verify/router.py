"""T4 — budget router (skill_05): VLM budget as a knapsack over entities, not one threshold.

Score of sending an image to the VLM = uncertainty (1 - calibrated confidence)
  + bonus if its entity is still short of yes images (one more yes is worth more there)
  + bonus if the decision layer itself said defer.
Rules from the doc: entities with < MIN_LIVE live images are not "rescued" with VLM
money (listed as needing more images instead); entities that already have >= 8
confident yes images are not spent on. Greedy fill up to alpha * N.
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

MIN_LIVE = 5
ENOUGH_YES = 8
CONFIDENT = 0.9


def conformal_threshold(u, alpha: float) -> float:
    """theta with P(u > theta) <= alpha on calibration data (split-conformal, finite-sample)."""
    u = np.sort(np.asarray(u, float))
    n = len(u)
    k = math.ceil((n + 1) * (1 - alpha))
    return float(u[min(k, n) - 1])


def select(
    groups: list[str],
    pred: list[str],
    conf: np.ndarray,
    deferred: list[bool],
    alpha: float,
    skip_small: bool = True,
) -> tuple[set[int], dict]:
    n = len(groups)
    live = defaultdict(int)
    sure_yes = defaultdict(int)
    pred_yes = defaultdict(int)
    for g, p, c in zip(groups, pred, conf, strict=True):
        live[g] += 1
        pred_yes[g] += p == "yes"
        sure_yes[g] += p == "yes" and c >= CONFIDENT
    budget = int(round(alpha * n))
    scored = []
    skipped_small = skipped_full = 0
    for i in range(n):
        g = groups[i]
        if skip_small and live[g] < MIN_LIVE:
            skipped_small += 1
            continue
        if sure_yes[g] >= ENOUGH_YES and not deferred[i]:
            skipped_full += 1
            continue
        score = (
            (1 - conf[i])
            + (0.15 if pred_yes[g] < MIN_LIVE else 0.0)
            + (0.25 if deferred[i] else 0.0)
        )
        scored.append((score, i))
    scored.sort(reverse=True)
    chosen = {i for _, i in scored[:budget]}
    return chosen, {
        "alpha": alpha,
        "budget_images": budget,
        "chosen": len(chosen),
        "defer_rate_actual": round(len(chosen) / max(1, n), 4),
        "decision_layer_defers": int(sum(deferred)),
        "excluded_small_entity_rows": skipped_small,
        "excluded_entity_already_enough_yes": skipped_full,
        "entities_needing_more_images": sum(1 for v in live.values() if v < MIN_LIVE),
    }
