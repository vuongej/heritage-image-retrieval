"""Check the doc's key claim (§1.4): pHash cannot tell 'same entity' from 'other entity',
SigLIP2 cosine can. Uses the pilot's thumbnails + emb.npz; prints AUC and Hamming stats.

python -X utf8 -m scripts.verify_phash_vs_embedding
"""

from __future__ import annotations

import json
import random
from collections import defaultdict

import numpy as np
from PIL import Image

from pipeline.stage1_heuristics import hamming, phash64
from pipeline.verify.common import read_jsonl, run_dir, write_json
from pipeline.verify.fetch import thumb_path


def auc(pos, neg) -> float:
    """P(score_pos > score_neg) with ties = 0.5 (Mann-Whitney)."""
    from scipy.stats import rankdata

    ranks = rankdata(np.concatenate([pos, neg]))  # average ranks for ties
    return float((ranks[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def main(max_pairs: int = 20000, seed: int = 42) -> None:
    emb = np.load(run_dir() / "emb.npz")
    index = {k: i for i, k in enumerate(emb["keys"].tolist())}
    img = emb["img"].astype(np.float32)
    split = json.loads((run_dir() / "split.json").read_text(encoding="utf-8"))
    states = {s["key"]: s for s in read_jsonl(run_dir() / "states.jsonl")}
    # group = entity name line of the state
    group_of = {k: s["state"].split("\n")[0] for k, s in states.items() if k in index}
    keys = sorted(group_of)
    members = defaultdict(list)
    for k in keys:
        members[group_of[k]].append(k)
    rng = random.Random(seed)
    intra = [(a, b) for ks in members.values() for i, a in enumerate(ks) for b in ks[i + 1 :]]
    rng.shuffle(intra)
    intra = intra[:max_pairs]
    cross = []
    while len(cross) < len(intra):
        a, b = rng.sample(keys, 2)
        if group_of[a] != group_of[b]:
            cross.append((a, b))
    ph = {k: phash64(Image.open(thumb_path(k))) for k in {x for p in intra + cross for x in p}}

    def scores(pairs):
        cos = np.array([img[index[a]] @ img[index[b]] for a, b in pairs])
        ham = np.array([hamming(ph[a], ph[b]) for a, b in pairs])
        return cos, ham

    ci, hi = scores(intra)
    cc, hc = scores(cross)
    out = {
        "pairs_intra": len(intra),
        "pairs_cross": len(cross),
        "images": len(ph),
        "split_seed": split["report"]["seed"],
        "phash_hamming_median_intra": float(np.median(hi)),
        "phash_hamming_median_cross": float(np.median(hc)),
        "phash_auc_same_entity": round(auc(64 - hi, 64 - hc), 4),
        "phash_rule_R4_hits_intra_le6": round(float((hi <= 6).mean()), 4),
        "phash_rule_R4_hits_cross_le6": round(float((hc <= 6).mean()), 4),
        "siglip2_cos_median_intra": round(float(np.median(ci)), 4),
        "siglip2_cos_median_cross": round(float(np.median(cc)), 4),
        "siglip2_auc_same_entity": round(auc(ci, cc), 4),
        "near_dup_cos_ge_0.97_intra": int((ci >= 0.97).sum()),
    }
    write_json(run_dir() / "phash_vs_embedding.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
