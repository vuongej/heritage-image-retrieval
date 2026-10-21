"""Whitelist địa danh hành chính dùng để nhận diện modifier địa điểm trong truy vấn.

63 tỉnh/thành trước sáp nhập 2025 (dữ liệu crawl dùng tên cũ) + tên mới sau sáp nhập
+ cách viết tắt phổ biến + một số địa phương du lịch hay xuất hiện sau dấu phẩy
("..., Phú Quốc"). So khớp trên dạng không dấu, lowercase (storage.local.plain).
"""

from __future__ import annotations

import re
from functools import lru_cache

from storage.local import plain

PROVINCES = (
    "An Giang", "Bà Rịa - Vũng Tàu", "Bắc Giang", "Bắc Kạn", "Bạc Liêu", "Bắc Ninh", "Bến Tre",
    "Bình Định", "Bình Dương", "Bình Phước", "Bình Thuận", "Cà Mau", "Cần Thơ", "Cao Bằng",
    "Đà Nẵng", "Đắk Lắk", "Đắk Nông", "Điện Biên", "Đồng Nai", "Đồng Tháp", "Gia Lai",
    "Hà Giang", "Hà Nam", "Hà Nội", "Hà Tĩnh", "Hải Dương", "Hải Phòng", "Hậu Giang",
    "Hòa Bình", "Hưng Yên", "Khánh Hòa", "Kiên Giang", "Kon Tum", "Lai Châu", "Lâm Đồng",
    "Lạng Sơn", "Lào Cai", "Long An", "Nam Định", "Nghệ An", "Ninh Bình", "Ninh Thuận",
    "Phú Thọ", "Phú Yên", "Quảng Bình", "Quảng Nam", "Quảng Ngãi", "Quảng Ninh", "Quảng Trị",
    "Sóc Trăng", "Sơn La", "Tây Ninh", "Thái Bình", "Thái Nguyên", "Thanh Hóa",
    "Thừa Thiên Huế", "Tiền Giang", "Hồ Chí Minh", "Trà Vinh", "Tuyên Quang", "Vĩnh Long",
    "Vĩnh Phúc", "Yên Bái",
)  # fmt: skip

# Tên mới sau sáp nhập 2025 không trùng tên cũ, và cách viết thường gặp.
ALIASES = (
    "Huế", "TP.HCM", "TP HCM", "TPHCM", "HCM", "Sài Gòn", "Thành phố Hồ Chí Minh",
    "Vũng Tàu", "Bà Rịa", "BR-VT", "Thanh Hoá", "Khánh Hoà", "Hoà Bình", "Daklak",
)  # fmt: skip

# Địa phương du lịch (cấp huyện/thành phố) hay đóng vai modifier sau dấu phẩy.
LOCALITIES = (
    "Phú Quốc", "Nha Trang", "Đà Lạt", "Hội An", "Sa Pa", "Sapa", "Hạ Long", "Mũi Né",
    "Côn Đảo", "Quy Nhơn", "Phan Thiết", "Buôn Ma Thuột", "Pleiku", "Mộc Châu", "Mai Châu",
    "Tam Đảo", "Cát Bà", "Lý Sơn", "Cù Lao Chàm", "Phong Nha", "Mỹ Tho", "Châu Đốc",
    "Hà Tiên", "Đồng Văn", "Hà Đông", "Chợ Lớn", "Cần Giờ", "Bảo Lộc", "Tam Cốc",
)  # fmt: skip

_PREFIX = re.compile(r"^(?:o|tai|tinh|thanh pho|tp|quan|huyen|thi xa|xa)\s+")


def _key(text: str) -> str:
    return " ".join(re.findall(r"\w+", plain(text)))


@lru_cache(maxsize=1)
def place_keys() -> frozenset[str]:
    return frozenset(_key(p) for p in (*PROVINCES, *ALIASES, *LOCALITIES))


def is_place(text: str) -> bool:
    """True nếu cả cụm chỉ là một địa danh (cho phép tiền tố 'ở', 'tại', 'tỉnh', 'TP'...)."""
    key = _key(text)
    while True:
        stripped = _PREFIX.sub("", key)
        if stripped == key:
            break
        key = stripped
    return bool(key) and key in place_keys()


def trailing_place(text: str) -> str | None:
    """Phần đuôi là địa danh (kèm 'ở'/'tại' nếu có), khi phía trước còn nội dung khác.

    "công viên nước ở phú quốc" -> "ở phú quốc"; "huế" -> None (cả cụm là địa danh).
    """
    words = text.split()
    for size in range(min(5, len(words) - 1), 0, -1):
        tail = words[-size:]
        if not is_place(" ".join(tail)):
            continue
        head = words[:-size]
        if head and plain(head[-1]) in {"o", "tai"}:
            tail, head = [head[-1], *tail], head[:-1]
        return " ".join(tail) if head else None
    return None
