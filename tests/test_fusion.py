from retrieval.fusion import rrf, with_quota


def test_rrf_orders_by_rank():
    merged = rrf([["a", "b", "c"], ["b", "a"]])
    assert merged[0][0] in {"a", "b"}
    assert merged[0][1] >= merged[-1][1]


def test_quota_guarantees_each_group():
    groups = {"ho": ["h1", "h2", "h3", "h4", "h5"], "meo": ["m1", "m2", "m3"]}
    out = with_quota(groups, keep=6, min_per_group=2)
    assert len(out) == 6
    assert any(x.startswith("h") for x in out)
    assert any(x.startswith("m") for x in out)


def test_quota_no_duplicates():
    groups = {"a": ["x", "y"], "b": ["y", "z"]}
    out = with_quota(groups, keep=10, min_per_group=2)
    assert len(out) == len(set(out))
