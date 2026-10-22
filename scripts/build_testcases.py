"""Dựng bộ test case Phần B (evals/testcases/cases.jsonl) — đóng băng, commit kèm repo.

Phương pháp (docs/test-cases.vi.md §2):
  single_entity   30 tên entity lấy mẫu phân tầng theo parent_class (seed 7, entity >= 5 ảnh);
                  relevant = entity đó + entity trùng tên chuẩn hoá. Đo khả năng tìm đúng tên.
  single          16 truy vấn tự nhiên viết tay; relevant = regex trên tên entity (bỏ dấu), viết
                  TRƯỚC khi chạy hệ thống rồi soát trên danh sách tên catalog (pooling theo tên).
  multi_intent    15 truy vấn 2–3 ý; mỗi ý có regex relevant riêng.
  multi_hop       16 truy vấn quan hệ; đích lấy từ kiến thức lịch sử (không từ KG của hệ thống,
                  tránh vòng lặp), relevant = tên công trình đích trong catalog; có ca đích không có
                  trong KG / catalog để chấm việc từ chối trả lời.
  out_of_catalog  5 truy vấn không có ảnh đúng trong catalog (gồm 2 ví dụ của đề) -> kỳ vọng
                  không trả ảnh, hoặc mọi ảnh trả về đều là dương tính giả.
Regex khớp trên tên entity đã bỏ dấu, chữ thường (đ -> d).

python -m scripts.build_testcases   # ghi file + in số entity mỗi regex khớp (soát nhãn)
"""

from __future__ import annotations

import json
import random
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from storage.local import connect

OUT = Path("evals/testcases/cases.jsonl")

SINGLE = [
    ("chợ Bến Thành", [r"^cho ben thanh"]),
    ("Nhà thờ Đức Bà Sài Gòn", [r"duc ba sai gon", r"^nha tho duc ba( \(|$)"]),
    ("Lăng Tự Đức", [r"lang tu duc", r"khiem lang"]),
    ("chùa Thiên Mụ Huế", [r"chua thien mu(?!c)", r"linh mu"]),
    ("phố cổ Hội An về đêm", [r"pho co hoi an", r"hoi an.*(dem|den long)"]),
    ("Chùa Cầu Hội An", [r"chua cau"]),
    ("Thánh địa Mỹ Sơn", [r"thanh dia my son", r"my son (nhom|[a-h]\d)", r"kalan my son", r"thap.*my son"]),
    ("tháp Bà Ponagar Nha Trang", [r"po ?nagar", r"\bthap ba\b"]),
    ("Hồ Gươm", [r"ho guom", r"ho hoan kiem", r"thap rua", r"cau the huc"]),
    ("Đại Nội Huế", [r"dai noi", r"ngo mon", r"kinh thanh hue"]),
    ("ruộng bậc thang", [r"ruong bac thang"]),
    ("Dinh Độc Lập", [r"dinh doc lap", r"hoi truong thong nhat"]),
    ("Văn Miếu Quốc Tử Giám Hà Nội", [r"quoc tu giam", r"van mieu.*ha noi"]),
    ("Lăng Chủ tịch Hồ Chí Minh", [r"lang chu tich ho chi minh"]),
    ("chợ đêm Phú Quốc", [r"cho dem phu quoc"]),
    ("tượng Phật nằm chùa Long Sơn Nha Trang", [r"long son.*nha trang", r"phat nam.*long son"]),
]

LANG_MINH_MANG = [r"lang minh mang", r"hieu lang"]
LANG_THIEU_TRI = [r"lang thieu tri", r"xuong lang"]
LANG_TU_DUC = [r"lang tu duc", r"khiem lang"]
LANG_KHAI_DINH = [r"lang khai dinh", r"ung lang"]
DUC_BA = [r"duc ba sai gon", r"^nha tho duc ba( \(|$)"]
VAN_MIEU_HN = [r"quoc tu giam", r"van mieu.*ha noi"]

MULTI = [
    ("Lăng Minh Mạng và lăng Khải Định", [LANG_MINH_MANG, LANG_KHAI_DINH]),
    ("chợ Bến Thành và nhà thờ Đức Bà Sài Gòn", [[r"^cho ben thanh"], DUC_BA]),
    ("Chùa Cầu và phố cổ Hội An", [[r"chua cau"], [r"pho co hoi an"]]),
    ("chợ đêm và Dinh Cậu ở Phú Quốc", [[r"cho dem phu quoc"], [r"dinh cau"]]),
    ("Hồ Gươm và Văn Miếu Quốc Tử Giám", [[r"ho guom", r"ho hoan kiem", r"cau the huc"], VAN_MIEU_HN]),
    ("Đại Nội Huế và chùa Thiên Mụ", [[r"dai noi", r"ngo mon"], [r"chua thien mu(?!c)"]]),
    ("Thánh địa Mỹ Sơn và tháp Po Nagar", [[r"thanh dia my son", r"my son (nhom|[a-h]\d)", r"kalan my son"],
                                         [r"po ?nagar"]]),
    ("Dinh Độc Lập và chợ Bến Thành", [[r"dinh doc lap", r"hoi truong thong nhat"], [r"^cho ben thanh"]]),
    ("Lăng Tự Đức, lăng Minh Mạng và lăng Khải Định", [LANG_TU_DUC, LANG_MINH_MANG, LANG_KHAI_DINH]),
    ("ruộng bậc thang Tú Lệ và ruộng bậc thang Pù Luông", [[r"ruong bac thang tu le"], [r"pu luong"]]),
    ("chùa Một Cột và Lăng Chủ tịch Hồ Chí Minh", [[r"chua mot cot"], [r"lang chu tich ho chi minh"]]),
    ("Hoàng thành Thăng Long và Văn Miếu", [[r"hoang thanh thang long"], VAN_MIEU_HN]),
    # Sửa 22/10 khi soát kết quả: bản đầu `(cho|pho|cau|cua) dong ba` bỏ sót "Chợ đêm Đông Ba".
    ("chợ đêm Đông Ba và Đại Nội Huế", [[r"(cho|cho dem|pho|cau|cua) dong ba\b"], [r"dai noi"]]),
    ("biệt thự Nam Phương Hoàng hậu và dinh Bảo Đại", [[r"biet thu nam phuong"], [r"dinh bao dai"]]),
    ("tháp Po Nagar, chùa Long Sơn và nhà thờ chính tòa Nha Trang",
     [[r"po ?nagar"], [r"long son.*nha trang", r"phat nam.*long son"], [r"nha tho chinh toa nha trang"]]),
]

# (truy vấn, relevant, trạng thái kỳ vọng của resolver). Đích theo sử liệu, không theo KG hệ thống.
HOP = [
    ("lăng của con trai vua Gia Long", LANG_MINH_MANG, "resolved"),
    ("lăng của cha vua Thiệu Trị", LANG_MINH_MANG, "resolved"),
    ("lăng của con trai vua Minh Mạng", LANG_THIEU_TRI, "resolved"),
    ("lăng của cha vua Tự Đức", LANG_THIEU_TRI, "resolved"),
    ("lăng của con trai vua Thiệu Trị", LANG_TU_DUC, "resolved"),
    ("lăng của con trai vua Đồng Khánh", LANG_KHAI_DINH, "resolved"),
    ("lăng của cha vua Khải Định", [r"lang (mo )?dong khanh", r"tu lang"], "resolved"),
    ("lăng của cha vua Bảo Đại", LANG_KHAI_DINH, "resolved"),
    ("lăng của mẹ vua Tự Đức", [r"xuong tho lang"], "resolved"),
    ("lăng của vợ vua Bảo Đại", [r"lang (hoang hau )?nam phuong"], "resolved"),
    ("mộ của cha Chủ tịch Hồ Chí Minh", [r"\bmo\b.*nguyen sinh sac"], "resolved"),
    ("mộ của mẹ Chủ tịch Hồ Chí Minh", [r"hoang thi loan"], "resolved"),
    ("lăng của cha vua Thành Thái", [r"lang duc duc", r"thanh thai an lang", r"chua an lang"], "resolved"),
    # Có đích trong catalog nhưng KG chưa có cạnh vợ/chồng của Tự Đức: đo độ phủ KG.
    ("lăng của vợ vua Tự Đức", [r"khiem tho lang"], "resolved"),
    # Không có đích hợp lệ: kỳ vọng từ chối (0 ảnh), không suy diễn.
    ("lăng của con trai vua Khải Định", [], "abstain"),  # Bảo Đại an táng tại Paris
    ("ảnh con trai chủ tịch Phạm Nhật Vượng", [], "abstain"),  # ví dụ của đề; ngoài KG / catalog
]

OUT_OF_CATALOG = [
    "bãi biển Nha Trang",  # ví dụ của đề; catalog không có entity bãi biển Nha Trang
    "hồ bơi và công viên nước ở Phú Quốc",  # ví dụ của đề; không có entity hồ bơi / công viên nước
    "tháp Eiffel Paris",
    "ảnh con hổ và con mèo",
    "những con vật sống trong rừng",
]


def plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    return " ".join("".join(c for c in text if unicodedata.category(c) != "Mn").split())


def entities() -> list[tuple[str, str, str, int]]:
    with connect() as conn:
        return conn.execute(
            "SELECT e.entity_id, e.entity_name, e.parent_class, count(i.rownum) FROM entities e "
            "JOIN images i ON i.entity_id = e.entity_id GROUP BY e.entity_id"
        ).fetchall()


def matches(ents, patterns: list[str]) -> list[tuple[str, str]]:
    rx = [re.compile(p) for p in patterns]
    return [(eid, name) for eid, name, _, _ in ents if any(r.search(plain(name)) for r in rx)]


def main() -> None:
    ents = entities()
    cases, problems = [], []

    # single_entity: một entity mỗi parent_class được bốc, rải đều, seed 7.
    by_class = defaultdict(list)
    for eid, name, cls, n in ents:
        if n >= 5:
            by_class[cls].append((eid, name))
    rng = random.Random(7)
    classes = sorted(by_class)
    rng.shuffle(classes)
    same_name = defaultdict(list)
    for eid, name, _, _ in ents:
        same_name[plain(name)].append(eid)
    for i, cls in enumerate(classes[:30]):
        eid, name = rng.choice(sorted(by_class[cls]))
        cases.append({"id": f"SE{i + 1:02d}", "type": "single_entity", "query": name,
                      "source": "auto: tên entity, phân tầng parent_class, seed 7",
                      "relevant_entity_ids": sorted(same_name[plain(name)])})

    def add(cid, ctype, query, source, **extra):
        cases.append({"id": cid, "type": ctype, "query": query, "source": source, **extra})

    for i, (q, pats) in enumerate(SINGLE, 1):
        add(f"S{i:02d}", "single", q, "manual: regex tên entity, soát trên catalog", relevant=pats)
    for i, (q, subs) in enumerate(MULTI, 1):
        add(f"M{i:02d}", "multi_intent", q, "manual: regex riêng cho từng ý", sub=subs)
    for i, (q, pats, status) in enumerate(HOP, 1):
        add(f"H{i:02d}", "multi_hop", q, "manual: đích theo sử liệu, regex tên công trình đích",
            relevant=pats, expect=status)
    for i, q in enumerate(OUT_OF_CATALOG, 1):
        add(f"O{i:02d}", "out_of_catalog", q, "manual: không có ảnh đúng trong catalog",
            relevant=[], expect="abstain")

    # Soát nhãn: mỗi regex phải khớp ít nhất một entity (trừ ca kỳ vọng từ chối).
    for c in cases:
        groups = c.get("sub") or ([c["relevant"]] if c.get("relevant") else [])
        for pats in groups:
            found = matches(ents, pats)
            c.setdefault("_matched", []).append(len(found))
            if not found:
                problems.append(f"{c['id']} {c['query']}: regex {pats} không khớp entity nào")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for c in cases:
            fh.write(json.dumps({k: v for k, v in c.items() if not k.startswith("_")},
                                ensure_ascii=False) + "\n")
    counts = defaultdict(int)
    for c in cases:
        counts[c["type"]] += 1
    print(f"[testcases] {OUT}: {len(cases)} ca {dict(counts)}")
    for c in cases:
        if c.get("_matched"):
            print(f"  {c['id']:5} {c['query'][:55]:55} entity khớp {c['_matched']}")
    if problems:
        raise SystemExit("\n".join(problems))


if __name__ == "__main__":
    main()
