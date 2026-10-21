from api.routers.backfill import backfill_status


def test_known_backfill_numbers():
    """Số liệu thật từ CSV nhóm 1."""
    s = backfill_status()
    assert s["zero_images"] == 242
    assert s["under_5"] == 478
