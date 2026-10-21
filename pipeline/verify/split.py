"""S2b — leakage-safe 70/30 split by normalised name group (skill_06).

Group key = norm(canonical_name without the trailing parenthetical), so the doc's
example "Chùa X" / "Chùa X (Hà Nội)" lands in one group (plain token-Jaccard >= 0.9
would not merge them: their Jaccard is 0.5). Remaining near-identical keys are merged
with token Jaccard >= 0.9 (prefix-filtered, union-find). Groups are stratified by
category bucket; VAL is carved out of TRAIN; TEST is meant to be touched once.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter, defaultdict

from pipeline.verify.common import category_bucket, norm

JACCARD = 0.9


def base_key(name: str) -> str:
    return norm(re.sub(r"\s*\([^)]*\)\s*$", "", name or "")) or norm(name)


def _merge_fuzzy(keys: list[str]) -> dict[str, str]:
    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    tokens = {k: set(k.split()) for k in keys}
    freq = Counter(t for ts in tokens.values() for t in ts)
    index: dict[str, list[str]] = defaultdict(list)
    for k in sorted(keys):
        ordered = sorted(tokens[k], key=lambda t: (freq[t], t))
        prefix = len(ordered) - math.ceil(JACCARD * len(ordered)) + 1
        cands = {c for t in ordered[:prefix] for c in index[t]}
        for c in cands:
            a, b = tokens[k], tokens[c]
            if len(a & b) / len(a | b) >= JACCARD:
                parent[find(k)] = find(c)
        for t in ordered[:prefix]:
            index[t].append(k)
    return {k: find(k) for k in keys}


def split(
    rows: list[dict], test_frac: float = 0.30, val_frac: float = 0.20, seed: int = 42
) -> dict:
    keys = {base_key(r["canonical_name"]) for r in rows}
    merged = _merge_fuzzy(sorted(keys))
    group_of = {id(r): merged[base_key(r["canonical_name"])] for r in rows}
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[group_of[id(r)]].append(r)
    by_bucket: dict[str, list[str]] = defaultdict(list)
    for g, rs in groups.items():
        by_bucket[Counter(category_bucket(r["category"]) for r in rs).most_common(1)[0][0]].append(
            g
        )
    side: dict[str, str] = {}
    for b in sorted(by_bucket):
        gs = sorted(by_bucket[b])
        random.Random(f"{seed}:{b}").shuffle(gs)
        n_test = max(1, round(test_frac * len(gs))) if len(gs) > 1 else 0
        rest = gs[n_test:]
        n_val = max(1, round(val_frac * len(rest))) if len(rest) > 1 else 0
        for g in gs[:n_test]:
            side[g] = "test"
        for g in rest[:n_val]:
            side[g] = "val"
        for g in rest[n_val:]:
            side[g] = "train"
    assignment = {r["image_url"]: side[group_of[id(r)]] for r in rows}
    counts = Counter(assignment.values())
    return {
        "assignment": assignment,
        "group_of_url": {r["image_url"]: group_of[id(r)] for r in rows},
        "report": {
            "rows": dict(counts),
            "groups": dict(Counter(side.values())),
            "name_keys": len(keys),
            "groups_after_fuzzy_merge": len(groups),
            "buckets": len(by_bucket),
            "test_share_rows": round(counts["test"] / max(1, len(rows)), 4),
            "seed": seed,
        },
    }
