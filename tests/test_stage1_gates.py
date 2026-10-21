from PIL import Image

from pipeline.stage1_heuristics import run


def test_reject_too_small():
    img = Image.new("RGB", (400, 300))
    res = run(img)
    assert res.passed is False
    assert any("width" in r for r in res.reasons)


def test_pass_large_enough():
    img = Image.new("RGB", (1200, 800))
    res = run(img)
    assert res.width == 1200 and res.height == 800


def test_expected_reject_share_matches_csv():
    """318/3226 ảnh < 600px trong CSV nhóm 1."""
    from pipeline.stage1_heuristics import expected_reject_share

    assert abs(expected_reject_share() - 0.0986) < 0.001
