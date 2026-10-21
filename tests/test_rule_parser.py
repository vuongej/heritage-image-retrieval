from retrieval.rule_parser import parse


def test_single():
    p = parse("bãi biển Nha Trang")
    assert p.intent_type == "single"
    assert p.sub_queries[0]["text"] == "bãi biển nha trang"


def test_multi_intent():
    p = parse("hồ bơi và công viên nước ở Phú Quốc")
    assert p.intent_type == "multi_intent"
    assert len(p.sub_queries) == 2


def test_multi_hop():
    p = parse("ảnh con trai chủ tịch Phạm Nhật Vượng")
    assert p.intent_type == "multi_hop"
    assert p.needs_graph is True
    assert len(p.hop_chain) >= 2


def test_set_query():
    p = parse("những con vật sống trong rừng")
    assert p.intent_type == "set_query"
    assert p.needs_graph is True


def test_strip_prefix():
    p = parse("cho tôi ảnh Quần thể Tràng An")
    assert "quần thể tràng an" in p.normalized


def test_classifier_con_is_not_a_relation():
    # "con"/"mẹ"/"chồng" là loại từ hoặc nghĩa thường: không được thành multi_hop (0 ảnh + tra web).
    for q in (
        "con mèo đang ngủ trên bàn phím",
        "Con trâu cày ruộng",
        "con thuyền trên sông",
        "mẹ con cá voi",
        "chồng chén bát",
        "em bé đang cười",
        "cha đẻ của tiếng Việt",
    ):
        assert parse(q).intent_type != "multi_hop", q


def test_relation_to_a_person_stays_multi_hop():
    for q in (
        "con của vua Gia Long",
        "vợ vua khải định",
        "mộ mẹ của Hồ Chí Minh",
        "ảnh con trai chủ tịch Phạm Nhật Vượng",
        "vợ Võ Nguyên Giáp",
    ):
        assert parse(q).intent_type == "multi_hop", q
