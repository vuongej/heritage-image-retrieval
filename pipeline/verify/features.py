"""S2 — features + compact text state for Jev (skill_03).

Siblings are grouped by the split's name group (not entity_id), as the doc requires.
Priors (host, category bucket) are counted on the FULL CSV: they are label-free.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

import numpy as np

from pipeline.verify.common import category_bucket, host

SCALAR_NAMES = [
    "cos_centroid",
    "cos_nn",
    "n_sib_log",
    "cos_name",
    "cos_desc",
    "host_prior",
    "category_prior",
    "has_desc",
    "desc_len_norm",
    "from_db",
    "log_w",
    "log_h",
    "log_aspect",
    "log_kb",
]


def priors(all_rows: list[dict]) -> dict:
    return {
        "host": Counter(host(r["image_url"]) for r in all_rows),
        "bucket": Counter(category_bucket(r["category"]) for r in all_rows),
    }


def build(
    rows: list[dict], fetched: list[dict], emb: dict, groups: list[str], pri: dict
) -> tuple[np.ndarray, list[dict]]:
    """rows/fetched/groups aligned with emb rows. Returns X (n, d+k) and per-row scalar dicts."""
    img = emb["img"].astype(np.float32)
    name = emb["name"].astype(np.float32)
    desc = emb["desc"].astype(np.float32)
    members: dict[str, list[int]] = defaultdict(list)
    for i, g in enumerate(groups):
        members[g].append(i)
    feats = []
    for i, (r, f) in enumerate(zip(rows, fetched, strict=True)):
        sib = [j for j in members[groups[i]] if j != i]
        if sib:
            sims = img[sib] @ img[i]
            cen = img[sib].mean(axis=0)
            cos_cen = float(cen @ img[i] / max(np.linalg.norm(cen), 1e-9))
            cos_nn = float(sims.max())
        else:  # lone image: no consensus signal (skill_03), flagged via n_sib = 0
            cos_cen, cos_nn = 1.0, 1.0
        has_desc = bool(r["description"].strip())
        w, h = f["w"], f["h"]
        feats.append(
            {
                "cos_centroid": round(cos_cen, 4),
                "cos_nn": round(cos_nn, 4),
                "n_sib": len(sib),
                "n_sib_log": math.log1p(len(sib)),
                "cos_name": round(float(img[i] @ name[i]), 4),
                "cos_desc": round(float(img[i] @ desc[i]), 4) if has_desc else 0.0,
                "host": host(r["image_url"]),
                "host_n": pri["host"][host(r["image_url"])],
                "host_prior": math.log1p(pri["host"][host(r["image_url"])]),
                "category_prior": math.log1p(pri["bucket"][category_bucket(r["category"])]),
                "has_desc": float(has_desc),
                "desc_len_norm": min(len(r["description"]), 600) / 600,
                "from_db": 1.0 if r["from_db"] == "1" else 0.0,
                "w": w,
                "h": h,
                "log_w": math.log(w),
                "log_h": math.log(h),
                "log_aspect": math.log(w / h),
                "log_kb": math.log1p(f["bytes"] / 1024),
            }
        )
    scalars = np.array([[d[k] for k in SCALAR_NAMES] for d in feats], dtype=np.float32)
    return np.concatenate([img, scalars], axis=1), feats


def state_text(row: dict, feat: dict, head_p: float) -> str:
    """Compact state (~120-160 tokens). Numbers rounded, empty fields dropped (skill_03 #4)."""
    lines = [
        f"entity: {row['canonical_name']} | category: {category_bucket(row['category'])}",
        f"head_p_yes: {head_p:.2f} | cos_centroid: {feat['cos_centroid']:.2f} | cos_nn: {feat['cos_nn']:.2f}"
        f" | n_sib: {feat['n_sib']}",
        f"cos_name: {feat['cos_name']:.3f}"
        + (f" | cos_desc: {feat['cos_desc']:.3f}" if feat["has_desc"] else " | has_desc: 0"),
        f"host: {feat['host']} (host_n {feat['host_n']}) | size: {feat['w']}x{feat['h']}"
        f" | aspect: {feat['w'] / feat['h']:.2f} | from_db: {int(feat['from_db'])}",
    ]
    return "\n".join(lines)
