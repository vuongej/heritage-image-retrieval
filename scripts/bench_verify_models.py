"""Giai đoạn 1–2 của benchmark router Phần A: các classifier thay cho head logistic.

Mọi model chỉ học trên TRAIN (dự đoán TRAIN là out-of-fold theo nhóm tên để stacking không rò rỉ),
hiệu chỉnh isotonic trên VAL, và chưa bao giờ nhìn TEST.

  P0  head production: logistic 782 chiều, học từ nhãn VLM thầy (bootstrap S3)
  M0  cùng head logistic, học từ nhãn người
  M1  LightGBM chỉ trên 14 feature scalar
  M1b LightGBM trên đúng input của head (embedding ảnh 768 + 14 scalar; encoder giữ nguyên)
  M2  MLP trên embedding SigLIP2 đóng băng (ảnh, tên, mô tả, centroid ảnh cùng nhóm) + 14 scalar
  M3  stacking: LightGBM trên 14 scalar + điểm OOF của M0, M1b, M2
"""

from __future__ import annotations

import time

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import GroupKFold, GroupShuffleSplit

from pipeline.verify import head

FOLDS = 5
SEED = 42


def _calibrate(raw: np.ndarray, y: np.ndarray, val: np.ndarray) -> np.ndarray:
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999)
    return iso.fit(raw[val], y[val]).predict(raw)


def _inner_split(groups: np.ndarray, idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Tách 15% nhóm của `idx` làm tập early stopping."""
    fit, stop = next(GroupShuffleSplit(1, test_size=0.15, random_state=SEED).split(idx, groups=groups[idx]))
    return idx[fit], idx[stop]


def _oof(train_fn, predict_fn, n: int, y: np.ndarray, side: np.ndarray, groups: np.ndarray):
    """Điểm thô: OOF cho TRAIN, trung bình các fold cho VAL/TEST. train_fn(fit_idx, stop_idx) -> model."""
    raw = np.zeros(n)
    rest = np.where(side != "train")[0]
    tr = np.where(side == "train")[0]
    for fit_part, hold_part in GroupKFold(FOLDS).split(tr, groups=groups[tr]):
        fit_idx, stop_idx = _inner_split(groups, tr[fit_part])
        model = train_fn(fit_idx, stop_idx)
        raw[tr[hold_part]] = predict_fn(model, tr[hold_part])
        raw[rest] += predict_fn(model, rest) / FOLDS
    return raw


def model_p0(ds, boot: dict[str, dict]) -> dict:
    """Head production đúng như pipeline.verify: nhãn bootstrap của VLM thầy trên TRAIN/VAL."""
    from pipeline.verify.common import row_key

    yb = np.array([
        {"yes": 1, "no": 0}.get(boot.get(row_key(r), {}).get("label"), -1) for r in ds.ok
    ])
    t = time.perf_counter()
    h = head.train(ds.X, yb, ds.side, ds.groups)
    return {"p": h["p_cal"], "raw": h["p_raw"], "train_s": time.perf_counter() - t,
            "labels": "VLM bootstrap", "n_train_labels": int(((ds.side == "train") & (yb >= 0)).sum()),
            "predict": lambda X: h["calibrator"].predict(head._predict(h["model"], X))}


def model_m0(ds) -> dict:
    t = time.perf_counter()
    h = head.train(ds.X, ds.y, ds.side, ds.groups)
    return {"p": h["p_cal"], "raw": h["p_raw"], "train_s": time.perf_counter() - t,
            "labels": "người", "C": h["report"]["C"],
            "predict": lambda X: h["calibrator"].predict(head._predict(h["model"], X))}


LGB_PARAMS = dict(
    objective="binary", learning_rate=0.03, num_leaves=31, min_child_samples=50,
    feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0,
    verbose=-1, seed=SEED,
)


def _lgb(F: np.ndarray, y: np.ndarray):
    import lightgbm as lgb

    def train_fn(fit_idx, stop_idx):
        return lgb.train(
            LGB_PARAMS,
            lgb.Dataset(F[fit_idx], y[fit_idx]),
            num_boost_round=3000,
            valid_sets=[lgb.Dataset(F[stop_idx], y[stop_idx])],
            callbacks=[lgb.early_stopping(100, verbose=False)],
        )

    def predict_fn(model, idx):
        return model.predict(F[idx], num_iteration=model.best_iteration)

    return train_fn, predict_fn


def model_m1(ds) -> dict:
    t = time.perf_counter()
    train_fn, predict_fn = _lgb(ds.scalars, ds.y)
    raw = _oof(train_fn, predict_fn, len(ds.y), ds.y, ds.side, ds.groups)
    return {"p": _calibrate(raw, ds.y, ds.side == "val"), "raw": raw,
            "train_s": time.perf_counter() - t, "labels": "người"}


def model_m1b(ds) -> dict:
    """LightGBM trên đúng input của head production (embedding ảnh 768 + 14 scalar)."""
    t = time.perf_counter()
    train_fn, predict_fn = _lgb(ds.X, ds.y)
    raw = _oof(train_fn, predict_fn, len(ds.y), ds.y, ds.side, ds.groups)
    return {"p": _calibrate(raw, ds.y, ds.side == "val"), "raw": raw,
            "train_s": time.perf_counter() - t, "labels": "người"}


def _centroids(img: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Trung bình ảnh KHÁC cùng nhóm (0 nếu ảnh đứng một mình), giống tín hiệu cos_centroid."""
    out = np.zeros_like(img)
    order = np.argsort(groups, kind="stable")
    g_sorted = groups[order]
    starts = np.r_[0, np.where(g_sorted[1:] != g_sorted[:-1])[0] + 1, len(order)]
    for a, b in zip(starts[:-1], starts[1:], strict=True):
        idx = order[a:b]
        if len(idx) > 1:
            total = img[idx].sum(axis=0)
            out[idx] = (total - img[idx]) / (len(idx) - 1)
    return out


def model_m2(ds, epochs: int = 40, log=print) -> dict:
    import torch
    from torch import nn

    torch.manual_seed(SEED)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    img = torch.tensor(ds.emb["img"], device=dev)
    name = torch.tensor(ds.emb["name"], device=dev)
    desc = torch.tensor(ds.emb["desc"], device=dev)
    cen = torch.tensor(_centroids(ds.emb["img"], ds.groups), device=dev)
    tr = ds.side == "train"
    mu, sd = ds.scalars[tr].mean(0), ds.scalars[tr].std(0) + 1e-6
    sc = torch.tensor((ds.scalars - mu) / sd, device=dev)
    yt = torch.tensor(ds.y, dtype=torch.float32, device=dev)

    def design(idx):
        i = torch.as_tensor(idx, device=dev)
        a = img[i]
        return torch.cat([a, a * name[i], a * desc[i], a * cen[i], a - cen[i], sc[i]], dim=1)

    d_in = 768 * 5 + sc.shape[1]

    def train_fn(fit_idx, stop_idx):
        net = nn.Sequential(
            nn.Linear(d_in, 512), nn.GELU(), nn.Dropout(0.3),
            nn.Linear(512, 128), nn.GELU(), nn.Dropout(0.3), nn.Linear(128, 1),
        ).to(dev)
        opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-2)
        loss_fn = nn.BCEWithLogitsLoss()
        best, best_state, bad = 1e9, None, 0
        x_stop, y_stop = design(stop_idx), yt[torch.as_tensor(stop_idx, device=dev)]
        rng = np.random.default_rng(SEED)
        for _ in range(epochs):
            net.train()
            perm = rng.permutation(fit_idx)
            for s in range(0, len(perm), 256):
                b = perm[s : s + 256]
                opt.zero_grad()
                loss = loss_fn(net(design(b)).squeeze(1), yt[torch.as_tensor(b, device=dev)])
                loss.backward()
                opt.step()
            net.eval()
            with torch.no_grad():
                val = loss_fn(net(x_stop).squeeze(1), y_stop).item()
            if val < best - 1e-4:
                best, bad = val, 0
                best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
            else:
                bad += 1
                if bad >= 4:
                    break
        net.load_state_dict(best_state)
        net.eval()
        return net

    def predict_fn(net, idx):
        out = []
        with torch.no_grad():
            for s in range(0, len(idx), 4096):
                out.append(torch.sigmoid(net(design(idx[s : s + 4096])).squeeze(1)).cpu().numpy())
        return np.concatenate(out)

    t = time.perf_counter()
    raw = _oof(train_fn, predict_fn, len(ds.y), ds.y, ds.side, ds.groups)
    train_s = time.perf_counter() - t
    # Thời gian suy luận / ảnh (một model, GPU) để báo cáo latency.
    net = train_fn(*_inner_split(ds.groups, np.where(tr)[0]))
    idx = np.arange(len(ds.y))
    if dev == "cuda":
        torch.cuda.synchronize()
    t = time.perf_counter()
    predict_fn(net, idx)
    if dev == "cuda":
        torch.cuda.synchronize()
    infer = time.perf_counter() - t
    return {"p": _calibrate(raw, ds.y, ds.side == "val"), "raw": raw, "train_s": train_s,
            "labels": "người", "device": dev, "infer_ms_per_1000": 1000 * infer / len(idx) * 1000}


def model_m3(ds, bases: dict[str, dict]) -> dict:
    """Stacking: điểm OOF của các model nền làm feature thêm cho LightGBM trên 14 scalar.

    Điểm nền của TRAIN là OOF nên LightGBM tầng 2 không học trên dự đoán đã thấy nhãn của nó."""
    t = time.perf_counter()
    clip = lambda p: np.clip(p, 1e-4, 1 - 1e-4)  # noqa: E731
    F = np.column_stack(
        [ds.scalars] + [np.log(clip(m["raw"]) / (1 - clip(m["raw"]))) for m in bases.values()]
    )
    train_fn, predict_fn = _lgb(F, ds.y)
    raw = _oof(train_fn, predict_fn, len(ds.y), ds.y, ds.side, ds.groups)
    return {"p": _calibrate(raw, ds.y, ds.side == "val"), "raw": raw,
            "train_s": time.perf_counter() - t + sum(m["train_s"] for m in bases.values()),
            "labels": "người", "bases": list(bases)}


def time_predict(fn, X: np.ndarray, repeat: int = 3) -> float:
    """ms suy luận cho 1.000 ảnh (CPU), lấy lần nhanh nhất."""
    best = 1e9
    for _ in range(repeat):
        t = time.perf_counter()
        fn(X)
        best = min(best, time.perf_counter() - t)
    return 1000 * best / len(X) * 1000
