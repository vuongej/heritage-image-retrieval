import pytest
from fastapi.testclient import TestClient

from api.main import app
from retrieval.query_guard import check

client = TestClient(app)
HEADERS = {"X-API-Key": "gsk_test_dev_only"}


@pytest.mark.parametrize(
    ("query", "category"),
    [
        ("địt mẹ mày", "profanity"),
        ("ĐỤ má", "profanity"),
        ("fuck", "profanity"),
        ("cặc", "profanity"),
        ("khiêu dâm", "sexual"),
        ("phim sex bãi biển", "sexual"),
        ("ảnh nóng", "sexual"),
        ("ảnh khỏa thân", "sexual"),
        ("xxx", "sexual"),
        ("chế tạo bom", "violence"),
        ("việt tân", "political"),
        ("nigger", "hate"),
        # Một từ cấm nằm giữa câu tìm ảnh hợp lệ vẫn bị chặn.
        ("chùa Một Cột và địt", "profanity"),
    ],
)
def test_blocks_by_category(query, category):
    verdict = check(query)
    assert verdict.blocked and verdict.category == category


@pytest.mark.parametrize(
    "query",
    [
        "đụụụụ",  # kéo dài chữ
        "fuuuuck",
        "xxxxxx",
        "d i t m e",  # chữ rời
        "d.i.t.m.e",
        "Đ Ụ",
        "đ_m",
        "V.C.L",
        "l0n",  # leetspeak
        "c4c",
        "sh!t",
        "dit me may",  # không dấu (từ không mơ hồ)
        "Ａｓｓｈｏｌｅ",  # toàn chiều rộng
        "pоrn",  # chữ о là Cyrillic
        "đ​ụ",  # ký tự rộng 0 chèn giữa
    ],
)
def test_blocks_evasion(query):
    assert check(query).blocked


@pytest.mark.parametrize(
    "query",
    [
        # Từ cấm là chuỗi con / bản bỏ dấu của từ thường ngày: KHÔNG được chặn nhầm.
        "Đền Dâm Đàm",
        "du lịch Đà Nẵng",
        "buổi sáng ở Hội An",
        "đeo kính",
        "lon nước",
        "đi chùa",
        "phần đông du khách",
        "Essex",
        "Dickson",
        "sexagenary cycle",
        # Từ vừa là lời chửi vừa là từ thường: phát hiện khi quét 100.806 mô tả ảnh trong catalog.
        "hạt óc chó",
        "thước đo 42 cm",
        # Cụm gồm chữ + số, chữ cái đứng riêng.
        "Quốc lộ 1A",
        "G20 hội nghị",
        "Ô Quan Chưởng",
        "a b c d",
        "Hội An 2024!",
        # Di sản có yếu tố nhạy cảm bề ngoài.
        "linga yoni Mỹ Sơn",
        "Nhà tù Phú Quốc",
        "Địa đạo Củ Chi",
        "con chó",
        # Chính các ví dụ trong đề bài.
        "bãi biển Nha Trang",
        "hồ bơi và công viên nước ở Phú Quốc",
        "ảnh con trai chủ tịch Phạm Nhật Vượng",
    ],
)
def test_allows_legitimate_queries(query):
    assert not check(query).blocked, check(query)


def test_search_blocked_before_pipeline(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("pipeline không được chạy với truy vấn bị chặn")

    monkeypatch.setattr("api.routers.search.run_search", boom)
    r = client.post("/v1/search", json={"query": "phim sex", "top_k": 10}, headers=HEADERS)
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "query_blocked" and body["category"] == "sexual"
    assert "sex" not in body["detail"].lower()  # không lặp lại nội dung người dùng gõ


def test_embed_and_rerank_blocked(monkeypatch):
    monkeypatch.setattr("api.routers.embed.embed_text", lambda texts: pytest.fail("đã embed"))
    monkeypatch.setattr("api.routers.rerank.run_rerank", lambda *a, **kw: pytest.fail("đã rerank"))
    r = client.post("/v1/embed", json={"texts": ["Chùa Một Cột", "địt"]}, headers=HEADERS)
    assert r.status_code == 400 and r.json()["code"] == "query_blocked"
    r = client.post(
        "/v1/rerank", json={"query": "porn", "candidates": [{"image_id": "a"}]}, headers=HEADERS
    )
    assert r.status_code == 400 and r.json()["code"] == "query_blocked"


def test_guard_can_be_disabled(monkeypatch):
    monkeypatch.setenv("QUERY_GUARD", "off")
    from retrieval.query_guard import ensure_allowed

    ensure_allowed("địt")  # không ném
