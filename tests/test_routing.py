from pipeline.routing import EXPECTED_UNCERTAIN_SHARE, decision_from_stage2, fallback_decision


def test_accept():
    assert decision_from_stage2({"relevance": 0.9, "watermark": 0.01}) == "accept"


def test_reject_unsafe():
    assert decision_from_stage2({"relevance": 0.9, "nsfw": 0.95}) == "reject"


def test_uncertain_band():
    assert decision_from_stage2({"relevance": 0.5, "watermark": 0.01}) == "uncertain"


def test_fallback_without_vlm():
    assert fallback_decision("uncertain", vlm_enabled=False) == "human_review"
    assert fallback_decision("uncertain", vlm_enabled=True) == "uncertain"


def test_uncertain_share_is_small():
    assert EXPECTED_UNCERTAIN_SHARE == 0.08
