"""Multi-hop có bằng chứng, KHÔNG phụ thuộc Wikidata (RETRIEVAL_PIPELINE_V2 §8).

KG gồm nút người/nơi chốn và cạnh có bằng chứng, dựng theo 3 giai đoạn:
  1. seed thủ công  (scripts.kg_seed)    — người + quan hệ người–người do người viết;
                                           người–nơi chốn tự sinh từ TÊN thực thể catalog.
  2. Gemini offline (scripts.kg_extract) — trích quan hệ từ trang nguồn của các thực thể
                                           lăng/mộ/đền thờ/khu lưu niệm…
  3. online fallback (retrieval.kg_online) — KG thiếu cạnh: tìm web, tải trang, kiểm câu trích.

Resolver CHỈ đi theo cạnh `verified = 1` (câu trích có nguyên văn trong văn bản nguồn mà hệ thống tự
tải, hoặc chính tên thực thể catalog) hoặc `reviewed = 1` (người duyệt). Trạng thái trả về:

  resolved               đi hết chuỗi, đích có ảnh trong catalog
  pending_online_lookup  KG thiếu cạnh, tra cứu online đang chạy nền (lần sau sẽ có kết quả)
  seed_not_linked        không biết người/vật xuất phát
  no_evidence            không có cạnh đã kiểm chứng cho một bước (KHÔNG có nghĩa quan hệ không tồn tại)
  target_not_in_catalog  giải được nhưng đích không có ảnh (vd đích là người: catalog không có ảnh người)
  unsupported_relation   quan hệ chưa hỗ trợ (anh/em/cháu/sáng lập…)

Cạnh chuẩn (lưu một chiều): PARENT_OF (cha/mẹ -> con), SPOUSE_OF (đối xứng), BURIED_AT,
WORSHIPPED_AT, MEMORIAL_AT (người -> nơi chốn trong catalog).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from storage.local import connect, plain

MAX_DEPTH = 4
PREDICATES = ("PARENT_OF", "SPOUSE_OF", "BURIED_AT", "WORSHIPPED_AT", "MEMORIAL_AT")
PLACE_PREDICATES = ("BURIED_AT", "WORSHIPPED_AT", "MEMORIAL_AT")

SCHEMA = """
CREATE TABLE IF NOT EXISTS kg_node (
    node_id TEXT PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL, gender TEXT,
    created_by TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kg_alias (
    alias_norm TEXT NOT NULL, node_id TEXT NOT NULL, PRIMARY KEY (alias_norm, node_id));
CREATE TABLE IF NOT EXISTS kg_edge (
    subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL,
    source_type TEXT NOT NULL, source_url TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0, reviewed INTEGER NOT NULL DEFAULT 0,
    verifier TEXT, confidence REAL, created_at TEXT NOT NULL,
    PRIMARY KEY (subject, predicate, object, source_url));
CREATE INDEX IF NOT EXISTS ix_kg_edge_s ON kg_edge(subject, predicate);
CREATE INDEX IF NOT EXISTS ix_kg_edge_o ON kg_edge(object, predicate);
CREATE TABLE IF NOT EXISTS kg_link (
    node_id TEXT NOT NULL, entity_id TEXT NOT NULL, method TEXT NOT NULL,
    PRIMARY KEY (node_id, entity_id));
CREATE TABLE IF NOT EXISTS kg_lookup (
    lookup_key TEXT PRIMARY KEY, status TEXT NOT NULL, detail TEXT, created_at TEXT NOT NULL);
DROP TABLE IF EXISTS kg_nodes;
DROP TABLE IF EXISTS kg_aliases;
DROP TABLE IF EXISTS kg_relations;
DROP TABLE IF EXISTS kg_entity_links;
"""

# Từ khoá quan hệ -> (vị từ chuẩn, chiều, giới tính nút ĐÍCH). Dài trước ngắn.
#   forward: subject --P--> đích ;  reverse: đích --P--> subject ;  any: cả hai chiều.
RELATIONS = [
    ("con trai", "PARENT_OF", "forward", "male"),
    ("con gái", "PARENT_OF", "forward", "female"),
    ("phụ thân", "PARENT_OF", "reverse", "male"),
    ("thân phụ", "PARENT_OF", "reverse", "male"),
    ("mẫu thân", "PARENT_OF", "reverse", "female"),
    ("thân mẫu", "PARENT_OF", "reverse", "female"),
    ("con", "PARENT_OF", "forward", None),
    ("cha", "PARENT_OF", "reverse", "male"),
    ("bố", "PARENT_OF", "reverse", "male"),
    ("mẹ", "PARENT_OF", "reverse", "female"),
    ("vợ", "SPOUSE_OF", "any", "female"),
    ("hoàng hậu", "SPOUSE_OF", "any", "female"),
    ("chồng", "SPOUSE_OF", "any", "male"),
]
UNSUPPORTED = (
    "anh",
    "em",
    "chị",
    "chủ tịch của",
    "giám đốc",
    "sáng lập",
    "cháu",
    "ông nội",
    "bà nội",
)
TARGETS = [
    ("lăng mộ", "BURIED_AT"),
    ("lăng", "BURIED_AT"),
    ("mộ", "BURIED_AT"),
    ("đền thờ", "WORSHIPPED_AT"),
    ("nơi thờ", "WORSHIPPED_AT"),
    ("khu lưu niệm", "MEMORIAL_AT"),
    ("nhà lưu niệm", "MEMORIAL_AT"),
    ("khu di tích", "MEMORIAL_AT"),
    ("tượng đài", "MEMORIAL_AT"),
]
TITLES = ("vua", "hoàng đế", "chủ tịch", "cụ", "ông", "bà", "ngài", "cố", "đức", "phó bảng")


@dataclass
class Step:
    phrase: str
    predicate: str
    direction: str
    gender: str | None


@dataclass
class HopPlan:
    steps: list[Step] = field(default_factory=list)  # theo thứ tự ÁP DỤNG từ seed ra ngoài
    target: str | None = None  # BURIED_AT / WORSHIPPED_AT / MEMORIAL_AT hoặc None
    seed_text: str = ""
    unsupported: str | None = None


@dataclass
class Resolution:
    status: str
    seed: dict = field(default_factory=dict)
    steps: list[dict] = field(default_factory=list)
    target_nodes: list[dict] = field(default_factory=list)
    mapped_target_entity_ids: list[str] = field(default_factory=list)
    evidence_checked: bool = True
    online: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def ensure_schema(conn) -> None:
    conn.executescript(SCHEMA)


def _eat(text: str, word: str) -> str | None:
    m = re.match(rf"{re.escape(word)}(?!\w)\s*(?:của\s+)?", text)
    return text[m.end() :].strip() if m else None


def plan(normalized: str) -> HopPlan:
    """ "lăng của con trai vua gia long" -> target BURIED_AT, steps [con trai], seed "gia long"."""
    text = normalized.strip()
    result = HopPlan()
    for word, pred in TARGETS:
        rest = _eat(text, word)
        if rest is not None:
            result.target, text = pred, rest
            break
    outer: list[Step] = []
    for _ in range(MAX_DEPTH):
        for word, pred, direction, gender in RELATIONS:
            rest = _eat(text, word)
            if rest is not None:
                outer.append(Step(word, pred, direction, gender))
                text = rest
                break
        else:
            break
    for word in UNSUPPORTED:
        if re.match(rf"{re.escape(word)}(?!\w)", text):
            result.unsupported = word
    while True:  # bỏ chức danh: "vua", "chủ tịch", "cụ phó bảng"...
        for title in TITLES:
            rest = _eat(text, title)
            if rest is not None and rest:
                text = rest
                break
        else:
            break
    result.seed_text = text
    # "con trai của cha của X": áp từ X ra ngoài -> đảo thứ tự đọc.
    result.steps = list(reversed(outer))
    return result


def find_nodes(conn, text: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT node_id FROM kg_alias WHERE alias_norm=?", (plain(text),)
        )
    ]


def node_info(conn, node_id: str) -> dict:
    row = conn.execute(
        "SELECT kind, label, gender FROM kg_node WHERE node_id=?", (node_id,)
    ).fetchone()
    return (
        {"node_id": node_id, "kind": row[0], "label": row[1], "gender": row[2]}
        if row
        else {"node_id": node_id}
    )


TRUSTED = "(verified = 1 OR reviewed = 1)"


def neighbours(conn, node: str, predicate: str, direction: str) -> list[tuple[str, dict]]:
    """[(nút kề, cạnh)] chỉ qua cạnh đã kiểm chứng."""
    out = []
    queries = []
    if direction in {"forward", "any"}:
        queries.append(("subject", "object"))
    if direction in {"reverse", "any"}:
        queries.append(("object", "subject"))
    for here, there in queries:
        for row in conn.execute(
            f"SELECT e.{there}, e.subject, e.predicate, e.object, e.source_type, e.source_url,"
            " e.evidence, e.verifier, s.label, o.label, o.kind FROM kg_edge e"
            " LEFT JOIN kg_node s ON s.node_id = e.subject"
            " LEFT JOIN kg_node o ON o.node_id = e.object"
            f" WHERE e.{here}=? AND e.predicate=? AND {TRUSTED}",
            (node, predicate),
        ):
            out.append(
                (
                    row[0],
                    {
                        "subject": row[1],
                        "subject_label": row[8] or row[1],
                        "predicate": row[2],
                        "object": row[3],
                        "object_label": row[9] or row[3],
                        "object_kind": row[10],
                        "source_type": row[4],
                        "source": row[5],
                        "evidence": row[6],
                        "verifier": row[7],
                    },
                )
            )
    return out


def _gender_ok(conn, node: str, gender: str | None) -> bool:
    if gender is None:
        return True
    row = conn.execute("SELECT gender FROM kg_node WHERE node_id=?", (node,)).fetchone()
    return bool(row) and row[0] == gender  # thiếu giới tính -> không đoán


def resolve(normalized: str, online=None) -> Resolution:
    """`online(conn, node_id, step) -> dict` (giai đoạn 3) được gọi khi một bước không có cạnh."""
    hop = plan(normalized)
    with connect() as conn:
        ensure_schema(conn)
        if hop.unsupported or (not hop.steps and not hop.target):
            return Resolution("unsupported_relation", seed={"text": hop.seed_text})
        seeds = find_nodes(conn, hop.seed_text)
        seed = {"text": hop.seed_text, "nodes": [node_info(conn, n) for n in seeds]}
        if not seeds and online is not None and hop.steps:
            seeds = online(conn, None, hop.seed_text, hop.steps[0]).get("seed_nodes", [])
            seed["nodes"] = [node_info(conn, n) for n in seeds]
        if not seeds:
            return Resolution("seed_not_linked", seed=seed)
        current, trace, online_info = seeds, [], {}
        chain = [
            *hop.steps,
            *([Step("lăng/mộ/đền/khu", hop.target, "forward", None)] if hop.target else []),
        ]
        for step in chain:
            nxt, used = [], []
            for node in current:
                found = [
                    (n, e) for n, e in neighbours(conn, node, step.predicate, step.direction)
                    if _gender_ok(conn, n, step.gender)
                ]  # fmt: skip
                if not found and online is not None and step.predicate not in PLACE_PREDICATES:
                    online_info = online(conn, node, None, step)
                    if online_info.get("status") == "pending":
                        return Resolution("pending_online_lookup", seed, trace, online=online_info)
                    found = [
                        (n, e) for n, e in neighbours(conn, node, step.predicate, step.direction)
                        if _gender_ok(conn, n, step.gender)
                    ]  # fmt: skip
                for n, edge in found:
                    if n not in nxt:
                        nxt.append(n)
                    used.append(edge)
            trace.append({**asdict(step), "edges": used})
            if not nxt:
                return Resolution("no_evidence", seed, trace, online=online_info)
            current = nxt
        targets = [node_info(conn, n) for n in current]
        mapped: list[str] = []
        for n in current:
            for (entity_id,) in conn.execute("SELECT entity_id FROM kg_link WHERE node_id=?", (n,)):
                if entity_id not in mapped:
                    mapped.append(entity_id)
        if mapped:
            return Resolution("resolved", seed, trace, targets, mapped, online=online_info)
        # Đích là người (không có ảnh người trong catalog): gợi ý nơi chốn liên quan, KHÔNG trả ảnh.
        for t in targets:
            t["related_places"] = [
                {"predicate": e["predicate"], "node": node_info(conn, n)}
                for p in PLACE_PREDICATES
                for n, e in neighbours(conn, t["node_id"], p, "forward")
            ][:10]
        return Resolution("target_not_in_catalog", seed, trace, targets, online=online_info)
