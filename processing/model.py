"""Classifier production của Pipeline A: ensemble LightGBM M1b + hiệu chỉnh isotonic.

Artifact sinh bởi scripts.train_verify_model (models/verify/): các file m1b_fold*.txt và
model_card.json (ngưỡng, ngân sách router, cách đọc VLM, prior host/category, số đo TEST).
"""

from __future__ import annotations

import json
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def model_dir() -> Path:
    return Path(os.getenv("VERIFY_MODEL_DIR", str(ROOT / "models" / "verify")))


class VerifyModel:
    def __init__(self, path: Path):
        import lightgbm as lgb

        self.card = json.loads((path / "model_card.json").read_text("utf-8"))
        self.boosters = [lgb.Booster(model_file=str(path / f)) for f in self.card["model_files"]]
        cal = self.card["calibration"]
        self._cal_x, self._cal_y = np.asarray(cal["x"]), np.asarray(cal["y"])
        d = self.card["decision"]
        self.threshold = float(d["threshold_t"])
        self.alpha = float(d["router_alpha"])
        self.vlm_rule = d["vlm_rule"]
        self.priors = {k: Counter(v) for k, v in self.card["priors"].items()}

    def predict(self, X: np.ndarray) -> np.ndarray:
        """P(người duyệt yes), đã hiệu chỉnh. X = [embedding ảnh, 14 scalar] như lúc train."""
        expected = self.card["image_dim"] + len(self.card["scalar_features"])
        if X.shape[1] != expected:
            raise ValueError(f"Feature width {X.shape[1]} != {expected} của model")
        raw = np.mean([b.predict(X) for b in self.boosters], axis=0)
        # IsotonicRegression(out_of_bounds="clip").predict == nội suy tuyến tính giữa các ngưỡng.
        return np.interp(raw, self._cal_x, self._cal_y)

    def summary(self) -> dict:
        m = self.card["test_metrics"]
        return {
            "name": self.card["name"],
            "description": self.card["description"],
            "encoder": self.card["encoder"],
            "created": self.card["created"],
            "threshold_t": self.threshold,
            "router_alpha": self.alpha,
            "vlm_rule": self.vlm_rule,
            "test_auc": m["auc"],
            "test_head_only": {k: m["head_only"][k] for k in (
                "recall_no", "precision_yes", "recall_yes", "entity_retention")},
            "test_with_router_vlm": {k: m["with_router_vlm"][k] for k in (
                "recall_no", "precision_yes", "recall_yes", "entity_retention", "routed_share")},
        }


@lru_cache(maxsize=1)
def load() -> VerifyModel:
    path = model_dir()
    if not (path / "model_card.json").exists():
        raise RuntimeError(
            f"Chưa có model tại {path}: chạy `python -m scripts.train_verify_model` trước"
        )
    return VerifyModel(path)
