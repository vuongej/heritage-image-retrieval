"""Multi-hop không phụ thuộc Wikidata: seed thủ công, cạnh có bằng chứng, online fallback (mock)."""

import csv
import time

import pytest

from retrieval import hop, kg_online, kg_sources
from storage.local import connect, import_approved

NOW = "2026-10-21T00:00:00+00:00"


def edge(conn, s, p, o, verified=1, source="catalog:entity/x", evidence="bằng chứng"):
    conn.execute(
        "INSERT INTO kg_edge VALUES (?,?,?,?,?,?,?,0,?,?,?)",
        (s, p, o, "test", source, evidence, verified, "test", None, NOW),
    )


def person(conn, node, label, gender):
    conn.execute(
        "INSERT INTO kg_node VALUES (?,?,?,?,?,?)", (node, "person", label, gender, "seed", NOW)
    )
    conn.execute("INSERT INTO kg_alias VALUES (?,?)", (hop.plain(label), node))


@pytest.fixture
def kg(tmp_path, monkeypatch):
    from retrieval import local_index, local_search

    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("LLM_PARSE_MODE", "off")
    path = tmp_path / "a.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, ["entity_id", "canonical_name", "slug", "category", "image_url", "flag"]
        )
        writer.writeheader()
        for eid, name, n in (
            ("t1", "Lăng Minh Mạng", 3),
            ("t2", "Bia lăng Minh Mạng (Hiếu Lăng)", 2),
            ("x", "Chùa Hương", 2),
        ):
            for i in range(n):
                writer.writerow(
                    {"entity_id": eid, "canonical_name": name, "slug": eid, "category": "Lăng tẩm",
                     "image_url": f"https://e.org/{eid}{i}.jpg", "flag": "approved"}
                )  # fmt: skip
    import_approved(path)
    monkeypatch.setattr(local_index, "EMBED_DIM", 2)
    monkeypatch.setattr(local_index, "embed_text", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(local_search, "embed_query", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr("retrieval.rerank.score_pairs", lambda q, c: [0.5] * len(c))
    local_index.build()
    with connect() as conn:
        hop.ensure_schema(conn)
        person(conn, "p:gl", "Gia Long", "male")
        person(conn, "p:mm", "Minh Mạng", "male")
        person(conn, "p:cc", "Công chúa X", "female")
        person(conn, "p:tt", "Thiệu Trị", "male")
        edge(conn, "p:gl", "PARENT_OF", "p:mm")
        edge(conn, "p:gl", "PARENT_OF", "p:cc")
        edge(conn, "p:mm", "PARENT_OF", "p:tt", verified=0)  # khẳng định CHƯA kiểm chứng
        for eid in ("t1", "t2"):
            conn.execute(
                "INSERT INTO kg_node VALUES (?,?,?,?,?,?)",
                (f"place:{eid}", "place", eid, None, "catalog", NOW),
            )
            conn.execute("INSERT INTO kg_link VALUES (?,?,?)", (f"place:{eid}", eid, "catalog"))
            edge(conn, "p:mm", "BURIED_AT", f"place:{eid}")
    yield
    local_index._load.cache_clear()


def test_plan_reads_target_steps_and_seed():
    plan = hop.plan("lăng của con trai của vua gia long")
    assert plan.target == "BURIED_AT"
    assert [(s.predicate, s.direction, s.gender) for s in plan.steps] == [
        ("PARENT_OF", "forward", "male")
    ]
    assert plan.seed_text == "gia long"
    nested = hop.plan("con trai của cha của minh mạng")
    assert [s.direction for s in nested.steps] == ["reverse", "forward"]  # áp từ seed ra ngoài


def test_two_hop_chain_resolves_with_evidence(kg):
    result = hop.resolve("lăng của con trai vua gia long")
    assert result.status == "resolved"
    assert set(result.mapped_target_entity_ids) == {"t1", "t2"}
    edges = [e for step in result.steps for e in step["edges"]]
    assert [e["predicate"] for e in edges] == ["PARENT_OF", "BURIED_AT", "BURIED_AT"]
    assert all(e["evidence"] for e in edges)
    assert result.steps[0]["edges"][0]["object"] == "p:mm"  # con gái bị loại theo giới tính


def test_reverse_direction_derives_father(kg):
    result = hop.resolve("cha của minh mạng")
    assert result.status == "target_not_in_catalog"  # đích là người: không có ảnh người
    assert [t["label"] for t in result.target_nodes] == ["Gia Long"]


def test_unverified_claims_are_never_used(kg):
    assert hop.resolve("con trai minh mạng").status == "no_evidence"


def test_person_target_lists_related_places_without_images(kg):
    result = hop.resolve("con trai vua gia long")
    assert result.status == "target_not_in_catalog"
    assert result.mapped_target_entity_ids == []
    assert {p["predicate"] for p in result.target_nodes[0]["related_places"]} == {"BURIED_AT"}


def test_unknown_seed_and_unsupported_relation(kg):
    assert hop.resolve("con trai chủ tịch phạm nhật vượng").status == "seed_not_linked"
    assert hop.resolve("anh của vua gia long").status == "unsupported_relation"


def test_online_fallback_pending_then_found(kg, monkeypatch):
    calls = []

    def slow_lookup(node, text, predicate, direction):
        calls.append((node, predicate, direction))
        time.sleep(0.3)
        with connect() as conn:
            edge(conn, "p:mm", "PARENT_OF", "p:tt2", verified=1, source="https://s.vn/a")
            person(conn, "p:tt2", "Thiệu Trị II", "male")
        return {"status": "found", "edges": [1]}

    monkeypatch.setattr(kg_online, "lookup", slow_lookup)
    first = hop.resolve("con trai minh mạng", online=kg_online.callback(budget_ms=50))
    assert first.status == "pending_online_lookup"
    time.sleep(0.5)
    second = hop.resolve("con trai minh mạng", online=kg_online.callback(budget_ms=50))
    assert second.status == "target_not_in_catalog"
    assert [t["label"] for t in second.target_nodes] == ["Thiệu Trị II"]
    assert len(calls) == 1  # kết quả đã ghi KG + cache tra cứu: không gọi lại


def test_online_no_evidence_is_cached(kg, monkeypatch):
    calls = []

    def nothing(node, text, predicate, direction):
        calls.append(1)
        return {"status": "no_evidence", "edges": []}

    monkeypatch.setattr(kg_online, "lookup", nothing)
    for _ in range(2):
        result = hop.resolve("vợ vua gia long", online=kg_online.callback(budget_ms=1000))
        assert result.status == "no_evidence"
    assert len(calls) == 1


def test_verify_quote_requires_source_text_and_both_parties(monkeypatch):
    page = (
        "Hoàng đế Minh Mạng (1791–1841) là con trai thứ tư của Hoàng đế Gia Long và là vua thứ hai."
    )
    monkeypatch.setattr(kg_online, "fetch_text", lambda url: (url, page))
    src = [{"url": "https://s.vn/x", "title": "", "content": ""}]
    parties = [["minh mang", "minh menh"], ["gia long"]]
    good = "Minh Mạng (1791–1841) là con trai thứ tư của Hoàng đế Gia Long"
    assert kg_online.verify_quote(good, parties, src)[2] == "quote_in_fetched_page"
    invented = "Minh Mạng là con trai cả của Hoàng đế Gia Long theo sử sách"
    assert not kg_online.verify_quote(invented, parties, src)
    assert not kg_online.verify_quote(good, [["minh mang"], ["tu duc"]], src)


def test_verify_quote_uses_search_snippet_and_pronoun_context(monkeypatch):
    def blocked(url):
        raise kg_sources.FetchError("http_403")  # vd Wikipedia chặn bot

    monkeypatch.setattr(kg_online, "fetch_text", blocked)
    src = [
        {
            "url": "https://vi.wikipedia.org/wiki/Minh_Mang",
            "title": "Minh Mạng",
            "content": "Minh Mạng ... | Thân phụ | Gia Long | Thân mẫu | Thuận Thiên Cao Hoàng hậu",
        }
    ]
    checked = kg_online.verify_quote("Thân phụ | Gia Long", [["minh mang"], ["gia long"]], src)
    assert checked and checked[2] == "quote_in_search_snippet"
    assert not kg_online.verify_quote("Thân phụ | Gia Long", [["tu duc"], ["gia long"]], src)


def test_quote_matching_tolerates_spacing_case_and_ellipsis():
    text = "Lăng   Minh Mạng\n là nơi an nghỉ của vua Minh Mạng, vị vua thứ hai triều Nguyễn."
    assert kg_sources.quote_in(text, "lăng minh mạng là nơi an nghỉ của vua Minh Mạng")
    assert kg_sources.quote_in(text, "Lăng Minh Mạng là nơi (...) vị vua thứ hai triều Nguyễn")
    assert not kg_sources.quote_in(text, "Lăng Minh Mạng là nơi an nghỉ của vua Gia Long")
    assert not kg_sources.quote_in(text, "Minh Mạng")  # quá ngắn để làm bằng chứng


def test_html_to_text_drops_scripts():
    raw = "<html><head><title>x</title><script>var a=1</script></head><body><p>Lăng &amp; mộ</p></body></html>"
    assert kg_sources.html_to_text(raw) == "Lăng & mộ"


def test_seed_place_edges_come_from_catalog_names(tmp_path, monkeypatch):
    from scripts import kg_seed

    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    path = tmp_path / "a.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, ["entity_id", "canonical_name", "slug", "category", "image_url", "flag"]
        )
        writer.writeheader()
        for i, name in enumerate(
            [
                "Lăng Hoàng hậu Nam Phương (Đà Lạt)",
                "Biệt thự Nam Phương",
                "Bảo tàng Thành phố Hồ Chí Minh",
            ]
        ):
            writer.writerow(
                {"entity_id": f"e{i}", "canonical_name": name, "slug": "s", "category": "c",
                 "image_url": f"https://e.org/{i}.jpg", "flag": "approved"}
            )  # fmt: skip
    import_approved(path)
    people = {
        "person:np": {"label": "Nam Phương", "aliases": "", "gender": "female"},
        "person:hcm": {"label": "Hồ Chí Minh", "aliases": "Bác Hồ", "gender": "male"},
    }
    with connect() as conn:
        hop.ensure_schema(conn)
        made = kg_seed.place_edges(conn, people)
    assert [(m["person"], m["predicate"], m["place"]) for m in made] == [
        ("person:np", "BURIED_AT", "Lăng Hoàng hậu Nam Phương (Đà Lạt)")
    ]  # "Biệt thự" không phải nơi chốn tưởng niệm; "Thành phố Hồ Chí Minh" không khớp


def test_search_returns_target_images_with_resolution(kg):
    from retrieval.search import search

    result = search("ảnh lăng của con trai vua Gia Long", top_k=10)
    assert result.intent_type == "multi_hop"
    assert result.resolution["status"] == "resolved"
    assert {h.entity_id for h in result.hits} == {"t1", "t2"}  # không lẫn Chùa Hương
    assert len(result.hits) == 5


def test_search_unresolved_hop_returns_nothing_with_status(kg):
    from retrieval.search import search

    result = search("con trai chủ tịch Phạm Nhật Vượng", top_k=10)
    assert result.hits == []
    assert result.resolution["status"] == "seed_not_linked"
    assert any("seed_not_linked" in w for w in result.warnings)


def test_quote_must_state_the_relation():
    assert kg_online.has_cue("Ông là con thứ 7 của vua Dục Đức", "PARENT_OF")
    assert kg_online.has_cue("Thân phụ | Nguyễn Thánh Tổ Minh Mạng", "PARENT_OF")
    assert kg_online.has_cue("Năm 15 tuổi bà kết hôn với ông Nguyễn Sinh Sắc.", "SPOUSE_OF")
    # Chỉ có tên, không nói quan hệ -> không phải bằng chứng.
    assert not kg_online.has_cue(
        "Vua Khải Định có tên khai sinh là Nguyễn Phúc Bửu Đảo", "PARENT_OF"
    )
    assert not kg_online.has_cue(
        "Từ Cung Hoàng thái hậu (1890 - 1980), phong hiệu chính", "PARENT_OF"
    )


# ---------------------------------------------------------------- kg_quality


def test_titles_are_stripped_and_names_merged(kg):
    from retrieval import kg_quality

    assert kg_quality.strip_titles("vua Minh Mạng") == "Minh Mạng"
    assert kg_quality.strip_titles("Hoàng thái hậu Từ Dũ") == "Từ Dũ"
    with connect() as conn:
        assert kg_quality.person_node(conn, "vua Minh Mạng", None, "t") == "p:mm"  # không tạo trùng
        assert kg_quality.person_node(conn, "Đảm", None, "t") is None  # một chữ: quá mơ hồ
        new = kg_quality.person_node(conn, "bà Phạm Thị Hằng", "female", "t")
        assert new == "person:pham-thi-hang"


def test_direction_judge_rejects_reversed_parenthood(kg, monkeypatch):
    from retrieval import kg_quality, llm_router

    monkeypatch.setattr(
        llm_router,
        "call_json",
        lambda body, model, **kw: {"stated": True, "parent": "vua Gia Long", "child": "Minh Mạng"},
    )
    with connect() as conn:
        quote = "vua Minh Mạng, con trai vua Gia Long"
        assert kg_quality.direction_ok(conn, quote, "p:gl", "p:mm")
        assert not kg_quality.direction_ok(conn, quote, "p:mm", "p:gl")


def test_conflicting_directions_keep_better_supported_side(kg):
    from retrieval import kg_quality

    with connect() as conn:
        edge(conn, "p:mm", "PARENT_OF", "p:gl", source="https://one.vn")  # chiều sai, 1 nguồn
        edge(conn, "p:gl", "PARENT_OF", "p:mm", source="https://two.vn")  # chiều đúng thêm nguồn
        kg_quality.enforce_consistency(conn)
        wrong = conn.execute(
            "SELECT max(verified) FROM kg_edge WHERE subject='p:mm' AND object='p:gl'"
        ).fetchone()[0]
        right = conn.execute(
            "SELECT max(verified) FROM kg_edge WHERE subject='p:gl' AND object='p:mm'"
        ).fetchone()[0]
    assert (wrong, right) == (0, 1)


def test_relation_structure_is_multi_hop_even_if_words_occur_in_names():
    from retrieval.catalog import EntityCatalog
    from retrieval.rule_parser import parse

    catalog = EntityCatalog.build(
        [("a", "Nhà thờ Cha Tam"), ("b", "Tượng đài Mẹ Việt Nam Anh hùng"), ("c", "Hồ Chí Minh")]
    )
    assert parse("đền thờ cha của Hồ Chí Minh", catalog).intent_type == "multi_hop"
    assert parse("Tượng đài Mẹ Việt Nam Anh hùng", catalog).intent_type == "single"
    assert parse("Nhà thờ Cha Tam", catalog).intent_type == "single"


def test_llm_cannot_drop_multi_hop():
    from retrieval import speculative
    from retrieval.rule_parser import parse

    rule = parse("vợ vua Khải Định").to_dict()
    llm = {
        "intent_type": "single", "entities": [], "sub_queries": ["vua Khải Định"], "hop_chain": [],
        "modifiers": {"place": "", "time": "", "style": ""},
    }  # fmt: skip
    parsed, action = speculative.decide(rule, llm, "low")
    assert parsed is rule and action == "guard_keep_multi_hop"


def test_objects_are_not_places():
    from retrieval.kg_quality import is_object_entity

    assert is_object_entity("Bộ tem Lăng Tự Đức - Huế VNCH")
    assert is_object_entity("Kim sách Bảo Đại tấn phong Hoàng hậu Nam Phương (1934)")
    assert not is_object_entity("Lăng Tự Đức")
    assert not is_object_entity("Tượng voi đá lăng Gia Long")  # tượng tại lăng: vẫn là nơi chốn


def test_place_relation_needs_place_named_near_quote():
    from scripts.kg_extract import place_named_near

    roundup = (
        "a " * 300 + "Nơi an nghỉ cuối cùng của Minh Mạng nằm sau cánh cổng bị khóa." + " b" * 300
    )
    quote = "nơi an nghỉ cuối cùng của minh mạng nằm sau cánh cổng bị khóa"
    assert not place_named_near(roundup, quote, "Lăng Gia Long - Huế")  # trang tổng hợp nhiều lăng
    assert place_named_near(roundup, quote, "Lăng Minh Mạng")
    statue = "Tượng voi đá ở lăng Gia Long. Đây là nơi an táng vua Gia Long và hoàng hậu."
    assert place_named_near(
        statue, "Đây là nơi an táng vua Gia Long và hoàng hậu", "Tượng voi đá lăng Gia Long"
    )


def test_gender_from_title_only_when_unambiguous():
    from retrieval.kg_quality import gender_from_title

    assert gender_from_title("Thuận Thiên Cao Hoàng Hậu") == "female"
    assert gender_from_title("vua Minh Mạng") == "male"
    assert gender_from_title("Nguyễn Hữu Hào") is None  # tên riêng không nói giới tính
