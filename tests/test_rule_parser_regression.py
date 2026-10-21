"""Hồi quy Phase 1.1: tên thực thể chứa marker không được xếp multi_hop / tách ý định.

`fixtures/misclassified_entities.csv`: đúng 104 tên mà parser cũ (trước 2026-10-20) xếp
`multi_hop` khi chạy trên catalog `pham_van_vuong` (4.481 thực thể) -> search trả rỗng.
"""

import csv
import sqlite3
from pathlib import Path

import pytest

from retrieval.catalog import EntityCatalog
from retrieval.rule_parser import parse

FIXTURE = Path(__file__).parent / "fixtures" / "misclassified_entities.csv"
ROWS = list(csv.DictReader(FIXTURE.open(encoding="utf-8")))
CATALOG = EntityCatalog.build([(r["entity_id"], r["entity_name"]) for r in ROWS])


def test_fixture_has_exactly_the_104_reported_names():
    assert len(ROWS) == 104
    assert {r["old_intent"] for r in ROWS} == {"multi_hop"}


@pytest.mark.parametrize("row", ROWS, ids=[r["entity_name"][:40] for r in ROWS])
def test_entity_names_get_their_expected_intent(row):
    assert parse(row["entity_name"], CATALOG).intent_type == row["expected_intent"]


@pytest.mark.parametrize(
    "query",
    [
        "Tượng đài Mẹ Việt Nam Anh hùng",  # tên bỏ phần tỉnh
        "Hòn Chồng Nha Trang",  # chỉ là một phần của tên "Biệt thự cổ Bảo Đại Hòn Chồng"
        "Lăng Chủ tịch Hồ Chí Minh",
        "Chùa Diên Phúc Đông Anh",
        "nhà thờ Cha Tam",
        "Đền thánh Đức Mẹ",
        "Phủ Chủ tịch",
    ],
)
def test_partial_names_are_protected(query):
    assert parse(query, CATALOG).intent_type == "single"


@pytest.mark.parametrize(
    "query",
    [
        "ảnh con trai chủ tịch Phạm Nhật Vượng",
        "vợ chủ tịch Hồ Chí Minh",
        "con trai của chủ tịch X",
        "mẹ của Võ Thị Sáu",
    ],
)
def test_real_relation_questions_stay_multi_hop(query):
    parsed = parse(query, CATALOG)
    assert parsed.intent_type == "multi_hop"
    assert parsed.needs_graph and len(parsed.hop_chain) >= 2


@pytest.mark.parametrize(
    ("query", "sub_query"),
    [
        ("Chùa Một Cột, Hà Nội", "chùa một cột hà nội"),
        ("Bãi biển Mỹ Khê, Đà Nẵng", "bãi biển mỹ khê đà nẵng"),
        ("Phố cổ Hội An, Quảng Nam", "phố cổ hội an quảng nam"),
        ("Nhà thờ Đức Bà, TP.HCM", "nhà thờ đức bà tp.hcm"),
        ("Đại Nội, Huế", "đại nội huế"),
        ("Vịnh Hạ Long, Quảng Ninh", "vịnh hạ long quảng ninh"),
        ("Chợ nổi Cái Răng, Cần Thơ", "chợ nổi cái răng cần thơ"),
        ("Tháp Bà Ponagar, Nha Trang", "tháp bà ponagar nha trang"),
        ("Hồ Xuân Hương, Đà Lạt", "hồ xuân hương đà lạt"),
        ("Bãi Sao, Phú Quốc", "bãi sao phú quốc"),
        ("Ruộng bậc thang, Sa Pa", "ruộng bậc thang sa pa"),
        ("Chùa Thiên Mụ, Thừa Thiên Huế", "chùa thiên mụ thừa thiên huế"),
        ("Cầu Rồng, TP Đà Nẵng", "cầu rồng tp đà nẵng"),
        ("Thác Bản Giốc, Cao Bằng", "thác bản giốc cao bằng"),
        ("Dinh Độc Lập, Sài Gòn", "dinh độc lập sài gòn"),
    ],
)
def test_place_after_comma_is_a_modifier(query, sub_query):
    parsed = parse(query, CATALOG)
    assert parsed.intent_type == "single"
    assert [s["text"] for s in parsed.sub_queries] == [sub_query]


@pytest.mark.parametrize(
    ("query", "subs"),
    [
        ("Chùa Một Cột, Hồ Gươm", ["chùa một cột", "hồ gươm"]),
        ("Hội An, Huế, Đà Nẵng", ["hội an", "huế", "đà nẵng"]),
        ("Hội An và Huế", ["hội an", "huế"]),
        ("chùa và nhà thờ ở Huế", ["chùa ở huế", "nhà thờ ở huế"]),
        ("Cầu Rồng, Bà Nà Hills, Đà Nẵng", ["cầu rồng đà nẵng", "bà nà hills đà nẵng"]),
    ],
)
def test_real_multi_intent_still_splits(query, subs):
    parsed = parse(query, CATALOG)
    assert parsed.intent_type == "multi_intent"
    assert [s["text"] for s in parsed.sub_queries] == subs


def test_place_modifier_applies_to_every_sub_query():
    parsed = parse("hồ bơi và công viên nước ở Phú Quốc", CATALOG)
    assert parsed.intent_type == "multi_intent"
    assert [s["text"] for s in parsed.sub_queries] == [
        "hồ bơi ở phú quốc",
        "công viên nước ở phú quốc",
    ]


def test_conjunction_inside_a_name_does_not_split():
    catalog = EntityCatalog.build([("m", "Mộ và đền thờ Nguyễn Đình Chiểu (Bến Tre)")])
    assert parse("Mộ và đền thờ Nguyễn Đình Chiểu", catalog).intent_type == "single"
    assert parse("Mộ và đền thờ", catalog).intent_type == "single"
    assert parse("Hội An và Huế", catalog).intent_type == "multi_intent"


def test_spans_are_longest_first_and_non_overlapping():
    catalog = EntityCatalog.build(
        [("a", "Văn Miếu"), ("b", "Văn Miếu Quốc Tử Giám"), ("c", "Quốc Tử Giám")]
    )
    spans = catalog.match_entity_spans("văn miếu quốc tử giám hà nội")
    assert [(s.matched_text, s.entity_ids) for s in spans] == [("văn miếu quốc tử giám", ["b"])]
    assert catalog.match_entity_spans("van mieu")[0].entity_ids == ["a"]  # không dấu


REAL_CATALOG = Path(__file__).resolve().parents[1] / "data" / "local" / "catalog.sqlite3"


@pytest.mark.skipif(not REAL_CATALOG.exists(), reason="cần catalog local đã import")
def test_no_entity_name_in_real_catalog_is_misparsed():
    with sqlite3.connect(REAL_CATALOG) as conn:
        rows = conn.execute("SELECT entity_id, entity_name FROM entities").fetchall()
    catalog = EntityCatalog.build(rows)
    wrong = [name for _, name in rows if parse(name, catalog).intent_type != "single"]
    assert wrong == []
