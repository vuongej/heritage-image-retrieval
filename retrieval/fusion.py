"""RRF + quota — cho multi-intent và multi-entity.

score(d) = sum_i w_i / (k + rank_i(d)), k = 60
"""

from __future__ import annotations

RRF_K = 60


def rrf(rank_lists: list[list[str]], weights: list[float] | None = None) -> list[tuple[str, float]]:
    w = weights or [1.0] * len(rank_lists)
    acc: dict[str, float] = {}
    for lst, wi in zip(rank_lists, w, strict=True):
        for rank, doc in enumerate(lst):
            acc[doc] = acc.get(doc, 0.0) + wi / (RRF_K + rank)
    return sorted(acc.items(), key=lambda kv: kv[1], reverse=True)


def with_quota(groups: dict[str, list[str]], keep: int = 10, min_per_group: int = 2) -> list[str]:
    """Mỗi sub-query được bảo đảm >= min_per_group slot, phần còn lại theo RRF.

    Dùng cho: 'ảnh con hổ và con mèo' -> 5 hổ + 5 mèo (quota 5/5).
    """
    out: list[str] = []
    seen: set[str] = set()
    for docs in groups.values():
        for d in docs[:min_per_group]:
            if d not in seen:
                seen.add(d)
                out.append(d)
    merged = rrf(list(groups.values()))
    for doc, _ in merged:
        if len(out) >= keep:
            break
        if doc not in seen:
            seen.add(doc)
            out.append(doc)
    return out[:keep]


def dedup_by_phash(hits: list[dict], hamming_max: int = 6) -> list[dict]:
    """TODO(impl): bỏ ảnh trùng gần (pHash Hamming <= 6) để đa dạng kết quả."""
    raise NotImplementedError
