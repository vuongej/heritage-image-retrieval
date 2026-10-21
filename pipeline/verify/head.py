"""S4a — linear head on [SigLIP2 embedding + scalar features] (skill_04 #1-2).

* C is chosen on VAL log-loss (TEST is never used for any choice).
* TRAIN rows get out-of-fold predictions (GroupKFold by name group) so the head_p_yes
  written into their states is not the head memorising its own training labels.
* Probabilities are isotonic-calibrated on VAL; ECE before/after is reported.
"""

from __future__ import annotations

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

from pipeline.verify.metrics import ece

GRID_C = (0.003, 0.01, 0.03, 0.1, 0.3, 1.0)


def _fit(X, y, C):
    sc = StandardScaler().fit(X)
    clf = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(sc.transform(X), y)
    return sc, clf


def _predict(model, X):
    sc, clf = model
    return clf.predict_proba(sc.transform(X))[:, 1]


def train(X: np.ndarray, y: np.ndarray, side: np.ndarray, groups: np.ndarray) -> dict:
    """y: 1/0 for labelled rows, -1 for unlabelled. side: train/val/test per row."""
    tr = (side == "train") & (y >= 0)
    va = (side == "val") & (y >= 0)
    if tr.sum() < 20 or va.sum() < 10 or len(set(y[tr])) < 2:
        raise ValueError(
            f"Not enough labelled rows for the head (train {tr.sum()}, val {va.sum()})"
        )
    scores = {}
    for C in GRID_C:
        model = _fit(X[tr], y[tr], C)
        scores[C] = log_loss(y[va], np.clip(_predict(model, X[va]), 1e-6, 1 - 1e-6), labels=[0, 1])
    best_c = min(scores, key=scores.get)
    model = _fit(X[tr], y[tr], best_c)
    p_raw = _predict(model, X)
    # Out-of-fold for every TRAIN row (labelled or not) so its state is honest.
    train_idx = np.where(side == "train")[0]
    n_groups = len(set(groups[tr]))
    if n_groups >= 5:
        for fit_idx, hold_idx in GroupKFold(5).split(train_idx, groups=groups[train_idx]):
            f = train_idx[fit_idx]
            f = f[y[f] >= 0]
            if len(set(y[f])) == 2:
                p_raw[train_idx[hold_idx]] = _predict(
                    _fit(X[f], y[f], best_c), X[train_idx[hold_idx]]
                )
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(p_raw[va], y[va])
    p_cal = iso.predict(p_raw)
    # Honest calibrated ECE: fit isotonic on one half of VAL, measure on the other, swap.
    va_idx = np.where(va)[0]
    halves = (va_idx[::2], va_idx[1::2])
    ece_cross = []
    for a, b in (halves, halves[::-1]):
        if len(set(y[a])) == 2 and len(b):
            iso_h = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(
                p_raw[a], y[a]
            )
            ece_cross.append(ece(y[b], iso_h.predict(p_raw[b])))
    return {
        "p_raw": p_raw,
        "p_cal": p_cal,
        "model": model,
        "calibrator": iso,
        "report": {
            "C": best_c,
            "val_logloss_by_C": {str(k): round(v, 4) for k, v in scores.items()},
            "train_labelled": int(tr.sum()),
            "val_labelled": int(va.sum()),
            "train_yes_rate": round(float(y[tr].mean()), 4),
            "ece_val_raw": round(ece(y[va], p_raw[va]), 4),
            "ece_val_calibrated_crossfit": round(float(np.mean(ece_cross)), 4)
            if ece_cross
            else None,
            "features": int(X.shape[1]),
        },
    }
