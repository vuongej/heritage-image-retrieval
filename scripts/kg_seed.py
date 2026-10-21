"""Giai đoạn 1 — seed KG thủ công (không Wikidata).

1. Người + tên gọi khác + giới tính:   data/kg/seed_people.csv
2. Người -> nơi chốn TỰ SINH từ tên thực thể catalog: "Lăng Minh Mạng…" -> BURIED_AT,
   "Đền thờ Nguyễn Sinh Sắc…" -> WORSHIPPED_AT, "Khu lưu niệm / Tượng đài … Hồ Chí Minh" ->
   MEMORIAL_AT. Bằng chứng = chính tên thực thể (verified, verifier=catalog_name_pattern).
3. Người <-> người: data/kg/seed_relations.csv nạp dưới dạng KHẲNG ĐỊNH (verified=0, resolver chưa
   dùng). `--verify`: tìm câu trích trên web (Gemini + web search), tải trang nguồn, kiểm câu trích
   nguyên văn -> verified=1 kèm URL + câu trích. Không kiểm được thì giữ 0 và liệt kê trong báo cáo.

python -X utf8 -m scripts.kg_seed [--verify] [--out reports/kg/seed.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from retrieval import hop
from storage.local import connect, plain

ROOT = Path(__file__).resolve().parents[1]
KG = ROOT / "data" / "kg"

# Mẫu tên nơi chốn (trên dạng bỏ dấu): <từ khoá> [chức danh...] <tên người>
PLACE_WORDS = [
    (r"lang mo|lang|mo|lang tam", "BURIED_AT"),
    (r"den tho|phu tho|nha tho ho|noi tho", "WORSHIPPED_AT"),
    (r"khu luu niem|nha luu niem|khu di tich|tuong dai|bao tang|nha tuong niem", "MEMORIAL_AT"),
]
TITLE_WORDS = (
    r"(?:vua|hoang de|hoang hau|chu tich|cu|ong|ba|pho bang|chi si|anh hung|danh nhan|bac)"
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def load_people(conn) -> dict[str, dict]:
    people = {}
    for row in csv.DictReader((KG / "seed_people.csv").open(encoding="utf-8")):
        node = row["node_id"].strip()
        people[node] = row
        conn.execute(
            "INSERT OR REPLACE INTO kg_node VALUES (?,?,?,?,?,?)",
            (node, "person", row["label"].strip(), row["gender"].strip() or None, "seed", _now()),
        )
        names = [row["label"], *row["aliases"].split("|")]
        for name in filter(None, (n.strip() for n in names)):
            conn.execute("INSERT OR IGNORE INTO kg_alias VALUES (?,?)", (plain(name), node))
    return people


def place_edges(conn, people: dict[str, dict]) -> list[dict]:
    """Cạnh người -> nơi chốn từ tên thực thể catalog. Mỗi entity_id là một nút nơi chốn."""
    from retrieval.kg_quality import is_object_entity

    # Sinh lại từ đầu: luật mẫu tên có thể đổi giữa các lần chạy.
    conn.execute("DELETE FROM kg_edge WHERE source_type='catalog_name'")
    entities = [
        (e, n)
        for e, n in conn.execute("SELECT entity_id, entity_name FROM entities").fetchall()
        if not is_object_entity(n)  # "Bộ tem Lăng Tự Đức" không phải nơi chốn
    ]
    for (node,) in conn.execute("SELECT node_id FROM kg_node WHERE kind='place'").fetchall():
        label = conn.execute("SELECT label FROM kg_node WHERE node_id=?", (node,)).fetchone()[0]
        if is_object_entity(label):  # dọn cạnh mọi giai đoạn trỏ tới đồ vật
            conn.execute("DELETE FROM kg_edge WHERE object=? OR subject=?", (node, node))
            conn.execute("DELETE FROM kg_link WHERE node_id=?", (node,))
            conn.execute("DELETE FROM kg_node WHERE node_id=?", (node,))
    made = []
    for node, row in people.items():
        names = sorted(
            {plain(n.strip()) for n in [row["label"], *row["aliases"].split("|")] if n.strip()},
            key=len,
            reverse=True,
        )
        for words, predicate in PLACE_WORDS:
            alternation = "|".join(re.escape(n) for n in names)
            pattern = re.compile(
                rf"(?<!\w)(?:{words})\s+(?:{TITLE_WORDS}\s+)*(?:{alternation})(?!\w)"
            )
            for entity_id, entity_name in entities:
                if not pattern.search(plain(entity_name)):
                    continue
                place = f"place:{entity_id}"
                conn.execute(
                    "INSERT OR IGNORE INTO kg_node VALUES (?,?,?,?,?,?)",
                    (place, "place", entity_name, None, "catalog", _now()),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO kg_link VALUES (?,?,?)",
                    (place, entity_id, "catalog_entity"),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO kg_edge VALUES (?,?,?,?,?,?,1,0,?,?,?)",
                    (node, predicate, place, "catalog_name", f"catalog:entity/{entity_id}",
                     entity_name, "catalog_name_pattern", None, _now()),
                )  # fmt: skip
                made.append({"person": node, "predicate": predicate, "place": entity_name})
    return made


def load_claims(conn) -> list[dict]:
    claims = []
    for row in csv.DictReader((KG / "seed_relations.csv").open(encoding="utf-8")):
        s, p, o = row["subject"].strip(), row["predicate"].strip(), row["object"].strip()
        if p not in hop.PREDICATES:
            raise ValueError(f"predicate không hợp lệ: {p}")
        conn.execute(
            "INSERT OR IGNORE INTO kg_edge VALUES (?,?,?,?,?,?,0,0,?,?,?)",
            (s, p, o, "manual_claim", "", row.get("note") or "", None, None, _now()),
        )
        claims.append({"subject": s, "predicate": p, "object": o})
    return claims


def verify_claims(conn, claims: list[dict]) -> list[dict]:
    from retrieval import kg_online, kg_quality

    # Luật kiểm chứng có thể siết dần: cạnh đã chấp nhận mà câu trích không còn đạt luật hiện hành
    # (vd không chứa từ chỉ quan hệ) bị hạ về chưa kiểm chứng và được tra lại.
    for s, p, o, src, evidence in conn.execute(
        "SELECT subject, predicate, object, source_url, evidence FROM kg_edge"
        " WHERE source_type='manual_claim' AND verified=1"
    ).fetchall():
        if not kg_quality.has_cue(evidence, p):
            conn.execute(
                "UPDATE kg_edge SET verified=0, verifier='revoked:no_relation_cue'"
                " WHERE subject=? AND predicate=? AND object=? AND source_url=?",
                (s, p, o, src),
            )
            print(f"[revoke] {s} {p} {o}: {evidence[:80]}", flush=True)
    conn.commit()
    results = []
    for claim in claims:
        s, p, o = claim["subject"], claim["predicate"], claim["object"]
        done = conn.execute(
            "SELECT 1 FROM kg_edge WHERE subject=? AND predicate=? AND object=? AND verified=1",
            (s, p, o),
        ).fetchone()
        if done:
            results.append({**claim, "verified": True, "cached": True})
            continue
        label_s = hop.node_info(conn, s)["label"]
        label_o = hop.node_info(conn, o)["label"]
        result = kg_online.verify_claim(
            label_s,
            p,
            label_o,
            kg_online.aliases(conn, s, label_s),
            kg_online.aliases(conn, o, label_o),
        )
        if result.get("verified"):
            conn.execute(
                "INSERT OR REPLACE INTO kg_edge VALUES (?,?,?,?,?,?,1,0,?,?,?)",
                (s, p, o, "manual_claim", result["source_url"], result["evidence"],
                 result["verifier"], None, _now()),
            )  # fmt: skip
            conn.commit()
        results.append({**claim, "labels": [label_s, label_o], **result})
        print(f"[verify] {label_s} {p} {label_o}: {result.get('verified')}", flush=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="kiểm chứng khẳng định bằng web")
    parser.add_argument("--out", default="reports/kg/seed.json")
    args = parser.parse_args()
    with connect() as conn:
        hop.ensure_schema(conn)
        people = load_people(conn)
        places = place_edges(conn, people)
        claims = load_claims(conn)
        conn.commit()
        verified = verify_claims(conn, claims) if args.verify else []
        from retrieval.kg_quality import enforce_consistency

        conflicts = enforce_consistency(conn)
        conn.commit()
    by_pred: dict[str, int] = {}
    for edge in places:
        by_pred[edge["predicate"]] = by_pred.get(edge["predicate"], 0) + 1
    report = {
        "people": len(people),
        "place_edges": len(places),
        "place_edges_by_predicate": by_pred,
        "place_edges_sample": places[:25],
        "claims": len(claims),
        "claims_verified": sum(bool(v.get("verified")) for v in verified),
        "claims_unverified": [
            {k: v[k] for k in ("subject", "predicate", "object")}
            for v in verified
            if not v.get("verified")
        ],
        "verify_usd": round(sum(v.get("usd") or 0 for v in verified), 4),
        "direction_conflicts_revoked": conflicts,
        "verified_detail": verified,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"verified_detail", "place_edges_sample"}},
                     ensure_ascii=False, indent=2))  # fmt: skip


if __name__ == "__main__":
    main()
