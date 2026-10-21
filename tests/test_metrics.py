from evals.harness import hit_at_k, mrr, ndcg_at_k, recall_at_k


def test_recall_perfect():
    assert recall_at_k(["a", "b", "c"], {"a", "b"}, 10) == 1.0


def test_recall_partial():
    assert recall_at_k(["a", "x", "y"], {"a", "b"}, 10) == 0.5


def test_hit_at_10():
    assert hit_at_k(["x", "y", "a"], {"a"}, 10) == 1
    assert hit_at_k(["x", "y", "z"], {"a"}, 10) == 0


def test_mrr_position():
    assert mrr(["x", "a"], {"a"}) == 0.5
    assert mrr(["a"], {"a"}) == 1.0


def test_ndcg_bounded():
    v = ndcg_at_k(["a", "x", "b"], {"a", "b"}, 10)
    assert 0.0 < v <= 1.0


def test_recall_empty_relevant():
    assert recall_at_k(["a"], set(), 10) == 0.0
