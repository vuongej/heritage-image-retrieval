"""Phase 2: migrate cột v2, filter kích thước thật, FTS stopword + AND/OR, nhánh dense ảnh."""

import csv
import hashlib
import json

import numpy as np
import pytest

from storage.local import connect, fts_terms, import_approved, lexical_candidates


def key(url):
    return hashlib.sha256(url.encode()).hexdigest()


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    from retrieval import local_index, local_search

    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    rows = [
        ("e1", "Chợ Bến Thành", "chợ truyền thống ở Sài Gòn", 1),
        ("e1", "Chợ Bến Thành", "cổng chợ về đêm", 2),
        ("e2", "Chợ nổi Cái Răng", "ghe bán trái cây trên sông", 3),
        ("e3", "Đền Hùng", "đền thờ trên núi Nghĩa Lĩnh", 4),
    ]
    path = tmp_path / "approved.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "entity_id",
                "canonical_name",
                "slug",
                "category",
                "image_url",
                "flag",
                "description",
            ],
        )
        writer.writeheader()
        for eid, name, desc, i in rows:
            writer.writerow(
                {
                    "entity_id": eid,
                    "canonical_name": name,
                    "slug": eid,
                    "category": "Di tích",
                    "image_url": f"https://e.org/{i}.jpg",
                    "flag": "approved",
                    "description": desc,
                }
            )
    import_approved(path)
    monkeypatch.setattr(local_index, "EMBED_DIM", 2)
    monkeypatch.setattr(local_index, "embed_text", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(local_search, "embed_query", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr("retrieval.rerank.score_pairs", lambda q, c: [0.5] * len(c))
    local_index.build()
    yield tmp_path
    local_index._load.cache_clear()


def write_jsonl(path, rows):
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def migrate(tmp_path):
    from scripts.migrate_images_v2 import migrate as run

    verify_dir = tmp_path / "verify"
    verify_dir.mkdir(exist_ok=True)
    write_jsonl(
        verify_dir / "fetch.jsonl",
        [
            {"key": key("https://e.org/1.jpg"), "status": "ok", "w": 1600, "h": 900},
            {"key": key("https://e.org/2.jpg"), "status": "ok", "w": 600, "h": 900},
            {"key": key("https://e.org/3.jpg"), "status": "dead"},
        ],
    )
    write_jsonl(
        verify_dir / "labels_boot.jsonl",
        [{"key": key("https://e.org/1.jpg"), "scores": {"watermark": 0.8}}],
    )
    verified = tmp_path / "x_verified.csv"
    with verified.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["image_url", "verify"])
        writer.writeheader()
        writer.writerow({"image_url": "https://e.org/2.jpg", "verify": "no"})
    return run(verify_dir, str(tmp_path / "*_verified.csv"))


def test_migrate_fills_known_values_and_keeps_null_with_reason(catalog):
    summary = migrate(catalog)
    with connect() as conn:
        rows = {
            r["image_url"][-5:]: dict(r)
            for r in conn.execute(
                "SELECT image_url, verify, width, height, has_watermark, fetch_status FROM images"
            )
        }
        known = conn.execute("SELECT value FROM metadata WHERE key='dimensions_known'").fetchone()[
            0
        ]
    assert (rows["1.jpg"]["width"], rows["1.jpg"]["height"], rows["1.jpg"]["has_watermark"]) == (
        1600,
        900,
        1,
    )
    assert rows["2.jpg"]["verify"] == "no" and rows["2.jpg"]["width"] == 600
    assert rows["3.jpg"]["width"] is None and rows["3.jpg"]["fetch_status"] == "dead"
    assert rows["4.jpg"]["fetch_status"] is None
    assert known == "2"
    assert summary["breakdown"]["size=NULL(fetch dead)"] == 1
    assert summary["breakdown"]["size=NULL(fetch chưa tải)"] == 1


def test_size_filters_use_real_dimensions(catalog):
    from retrieval.search import search

    no_dims = search("ảnh ngang Chợ Bến Thành", top_k=4)
    assert any("ignored" in w for w in no_dims.warnings)  # chưa migrate: không lọc, có cảnh báo

    migrate(catalog)
    # Filter SUY RA từ câu ("ảnh ngang") = permissive: loại ảnh đã biết là dọc (2.jpg), giữ ảnh
    # chưa biết kích thước (3.jpg dead, 4.jpg chưa tải) và báo số lượng.
    landscape = search("ảnh ngang Chợ Bến Thành", top_k=4)
    assert {h.image_url[-5:] for h in landscape.hits} == {"1.jpg", "3.jpg", "4.jpg"}
    assert any("unknown dimensions kept" in w for w in landscape.warnings)
    # Filter truyền qua API = strict: ảnh chưa biết kích thước bị loại.
    portrait = search("Chợ Bến Thành", top_k=4, filters={"orientation": "portrait"})
    assert [h.image_url[-5:] for h in portrait.hits] == ["2.jpg"]
    assert any("unknown dimensions excluded" in w for w in portrait.warnings)
    wide = search("Chợ Bến Thành", top_k=4, filters={"min_width": 1200})
    assert [h.image_url[-5:] for h in wide.hits] == ["1.jpg"]
    assert all(h.quality["width"] == 1600 for h in wide.hits)


def test_stopwords_are_removed_on_accented_form():
    assert fts_terms("các chợ truyền thống ở Hội An") == ["cho", "truyen", "thong", "hoi", "an"]
    assert fts_terms("cho tôi xem đền thờ") == ["den", "tho"]  # "cho"/"xem" bỏ, "đền" giữ
    assert fts_terms("Chợ nổi Cái Răng") == ["cho", "noi", "cai", "rang"]
    assert fts_terms("và của") == ["va", "cua"]  # toàn hư từ: không bỏ hết


def test_lexical_prefers_all_terms_then_fills_with_any(catalog):
    found = lexical_candidates("chợ trên sông")  # chỉ ảnh 3 có cả "chợ"... và "sông"
    with connect() as conn:
        urls = {r[0]: r[1] for r in conn.execute("SELECT rownum, image_url FROM images")}
    assert urls[found[0]].endswith("3.jpg")
    assert {urls[r][-5:] for r in found} >= {"1.jpg", "2.jpg", "3.jpg"}  # OR bổ sung
    assert lexical_candidates("chua mot cot") == []  # không dấu vẫn chạy (không khớp gì)


def test_visual_branch_joins_fusion(catalog, monkeypatch):
    from retrieval import local_search, vector_store
    from retrieval.search import search
    from storage.runtime import data_dir

    # Không có từ nào khớp FTS/tên; vector text của mọi ảnh như nhau (hoà, giữ thứ tự 1,2,3,4).
    # Vector ảnh: rownum 4 trùng hướng câu truy vấn -> RRF kéo ảnh 4 từ vị trí 4 lên vị trí 2.
    np.save(data_dir() / "visual.npy", np.asarray([[0.0, 1.0], [1.0, 0.0]], dtype=np.float32))
    np.save(data_dir() / "visual_rows.npy", np.asarray([1, 4]))
    (data_dir() / "visual_index.json").write_text(json.dumps({"complete": True, "points": 2}))
    monkeypatch.setattr(
        local_search, "embed_text_visual", lambda texts: [[1.0, 0.0] for _ in texts]
    )
    assert vector_store.has_visual()
    assert [r for r, _ in vector_store.search(vector_store.VISUAL, [1.0, 0.0], 2)] == [4, 1]
    result = search("phong cảnh", top_k=4)
    assert "embed_visual" in result.timings_ms and "dense" in result.timings_ms
    assert [h.image_url[-5:] for h in result.hits] == ["1.jpg", "4.jpg", "2.jpg", "3.jpg"]
