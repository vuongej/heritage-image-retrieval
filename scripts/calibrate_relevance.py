"""Hiệu chỉnh ngưỡng liên quan RERANK_MIN_RELEVANCE trên điểm gốc cross-encoder (`hit.relevance`).

Chạy search THẬT (cache /v1/search tắt, cổng liên quan tắt) rồi mô phỏng từng ngưỡng trên top-10:
  trong phạm vi (nhãn silver từ catalog, như scripts/eval_quality.py)
    entity    100 tên thực thể (seed 42)          đúng = ảnh của thực thể
    set       20 "các <nhóm>"                      đúng = ảnh cùng nhóm rút gọn
    multi     20 "<A> và <B>"                      đúng = ảnh của A hoặc B
    describe  40 câu mô tả (bỏ tên thực thể)       đúng = ảnh cùng nhóm rút gọn với thực thể nguồn
  ngoài phạm vi
    ood       truy vấn viết tay chắc chắn không có trong catalog di sản Việt Nam -> mọi ảnh đều sai

Mô phỏng bỏ qua miễn trừ "khớp đúng tên thực thể" nên ước lượng mất recall là BI QUAN.
python -X utf8 -m scripts.calibrate_relevance [--out reports/v2/relevance_calibration.json]
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS = (0.001, 0.003, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3)

OOD = [
    # chuỗi vô nghĩa
    "asdkjh qweoiu zzxcv", "xyzqw blorf kraznik", "lorem ipsum dolor sit amet", "qwerty uiop",
    "zxcvbnm asdf", "aaaa bbbb cccc", "123456 789", "kjhgf poiuy", "blah blah blah", "test test",
    # công nghệ
    "iphone 15 pro max giá rẻ", "hướng dẫn cài đặt Windows 11", "lỗi màn hình xanh máy tính",
    "cách viết hàm đệ quy python", "so sánh RAM DDR4 và DDR5", "card đồ họa RTX 4090",
    "cấu hình router wifi", "docker compose up lỗi port", "cách reset mật khẩu gmail",
    "bàn phím cơ switch đỏ",
    # toán, khoa học
    "công thức tính đạo hàm", "định lý Pythagore chứng minh", "phương trình bậc hai nghiệm kép",
    "cấu trúc phân tử ADN", "định luật bảo toàn năng lượng", "tích phân từng phần",
    "bảng tuần hoàn hóa học", "thuyết tương đối hẹp Einstein",
    # tài chính, kinh doanh
    "giá bitcoin hôm nay", "lãi suất vay mua nhà", "báo cáo tài chính quý 3", "cách mở tài khoản chứng khoán",
    "hợp đồng lao động thử việc", "mẫu hóa đơn giá trị gia tăng",
    # nước ngoài, giải trí, sản phẩm
    "máy bay chiến đấu F-35", "tàu vũ trụ SpaceX Starship", "siêu xe Lamborghini Aventador",
    "đội bóng Real Madrid", "phim Harry Potter", "trò chơi Minecraft", "ban nhạc BTS biểu diễn",
    "giày Nike Air Jordan",
    # y tế
    "triệu chứng tiểu đường type 2", "thuốc hạ sốt cho trẻ em", "cách điều trị đau dạ dày",
    "lịch tiêm vắc xin cho bé", "xét nghiệm máu tổng quát",
    # việc vặt
    "cách giặt áo len không bị co", "mẫu đơn xin nghỉ phép", "lịch thi đấu bóng đá tuần này",
    "dự báo thời tiết ngày mai", "cách đổi bằng lái xe",
    # tiếng Anh
    "how to fix a leaking faucet", "best laptop for gaming 2025", "quantum computing basics",
    "stock market crash 1929", "machine learning tutorial",
]  # fmt: skip


def run(query: str) -> dict:
    from retrieval.search import search

    r = search(query, top_k=10)
    return {
        "query": query,
        "intent": r.intent_type,
        "hits": [
            {
                "image_id": h.image_id,
                "entity_id": h.entity_id,
                "parent_class": h.parent_class,
                "relevance": h.relevance,
            }
            for h in r.hits
        ],
    }


def describe_cases(conn, n: int, rng: random.Random) -> list[dict]:
    from pipeline.local_run import short_class
    from storage.local import plain

    rows = conn.execute(
        "SELECT e.entity_name, e.parent_class, i.description FROM images i"
        " JOIN entities e USING(entity_id) WHERE length(i.description) > 80"
        " ORDER BY i.rownum"
    ).fetchall()
    cases = []
    for row in rng.sample(rows, n * 3):
        name_words = set(plain(row[0]).split())
        words = [w for w in row[2].split() if plain(w).strip(".,;:()") not in name_words]
        query = " ".join(words[:14]).strip(" ,.;:")
        if len(query.split()) >= 6:
            cases.append({"query": query, "group": short_class(row[1] or "")})
        if len(cases) == n:
            break
    return cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/v2/relevance_calibration.json")
    args = parser.parse_args()
    os.environ["RERANK_MIN_RELEVANCE"] = "0"  # đo trên danh sách CHƯA cắt

    from pipeline.local_run import eval_cases, short_class
    from retrieval import local_search
    from storage.local import connect

    original = local_search.cache_get
    local_search.cache_get = lambda key: None if key.startswith("search:") else original(key)

    rng = random.Random(7)
    with connect() as conn:
        entity_cases = eval_cases(conn, 100)
        classes = [
            r[0]
            for r in conn.execute(
                "SELECT parent_class, count(*) n FROM entities WHERE parent_class<>''"
                " GROUP BY parent_class HAVING n >= 5 ORDER BY parent_class"
            )
        ]
        names = {r[0]: r[1] for r in conn.execute("SELECT entity_id, entity_name FROM entities")}
        described = describe_cases(conn, 40, random.Random(11))
    set_classes = rng.sample(classes, 20)
    pairs = [rng.sample(sorted(names), 2) for _ in range(20)]

    rows: list[dict] = []

    def label(row: dict, kind: str, is_rel) -> None:
        for h in row["hits"]:
            h["relevant"] = bool(is_rel(h))
        row["kind"] = kind
        rows.append(row)
        top = max((h["relevance"] or 0 for h in row["hits"]), default=None)
        print(f"{kind:9} {row['query'][:60]!r:64} n={len(row['hits']):2} top={top}", flush=True)

    for q in ("Văn Miếu", "Chùa Hương"):  # khởi động
        run(q)
    for case in entity_cases:
        label(run(case["query"]), "entity", lambda h, r=set(case["relevant"]): h["image_id"] in r)
    for cls in set_classes:
        g = short_class(cls)
        label(
            run("các " + g.lower()), "set", lambda h, g=g: short_class(h["parent_class"] or "") == g
        )
    for a, b in pairs:
        label(run(f"{names[a]} và {names[b]}"), "multi", lambda h, s={a, b}: h["entity_id"] in s)
    for case in described:
        label(
            run(case["query"]),
            "describe",
            lambda h, g=case["group"]: short_class(h["parent_class"] or "") == g,
        )
    for q in OOD:
        label(run(q), "ood", lambda h: False)

    def simulate(t: float) -> dict:
        out: dict = {"threshold": t}
        for kind in ("entity", "set", "multi", "describe", "ood"):
            group = [r for r in rows if r["kind"] == kind]
            hits = [h for r in group for h in r["hits"]]
            scored = [h for h in hits if h["relevance"] is not None]
            keep = lambda h: h["relevance"] is None or h["relevance"] >= t  # noqa: E731
            rel = [h for h in scored if h["relevant"]]
            irr = [h for h in scored if not h["relevant"]]
            had_rel = [r for r in group if any(h["relevant"] for h in r["hits"])]
            out[kind] = {
                "queries": len(group),
                "relevant_kept": round(sum(map(keep, rel)) / len(rel), 4) if rel else None,
                "irrelevant_removed": round(sum(not keep(h) for h in irr) / len(irr), 4)
                if irr
                else None,
                "queries_emptied": sum(not any(keep(h) for h in r["hits"]) for r in group),
                "queries_lost_all_relevant": sum(
                    not any(keep(h) and h["relevant"] for h in r["hits"]) for r in had_rel
                ),
                "precision_after": round(
                    sum(keep(h) for h in rel) / max(1, sum(keep(h) for h in scored)), 4
                ),
            }
        return out

    table = [simulate(t) for t in THRESHOLDS]
    print(
        "\nthreshold | rel kept entity/set/multi/describe | lost-all (queries) | OOD emptied/60 | irrelevant removed (in-domain)"
    )
    for s in table:
        ins = ("entity", "set", "multi", "describe")
        print(
            f"{s['threshold']:<9} | "
            + " ".join(f"{s[k]['relevant_kept']}" for k in ins)
            + " | "
            + " ".join(str(s[k]["queries_lost_all_relevant"]) for k in ins)
            + f" | {s['ood']['queries_emptied']}/{s['ood']['queries']}"
            + " | "
            + " ".join(f"{s[k]['irrelevant_removed']}" for k in ins)
        )
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "label_type": "silver (catalog entity/class) + hand-written out-of-domain queries",
                "note": "simulation ignores the exact-entity-name exemption: recall loss is pessimistic",
                "table": table,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print("wrote", out)


if __name__ == "__main__":
    main()
