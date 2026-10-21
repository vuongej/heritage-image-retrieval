"""Entity graph — build < 5 s, traversal online 10-40 ms.

Relation: HAS_TYPE | IN_CLASS | IN_REGION | NEAR | CHAIRMAN_OF | PARENT_OF
Lưu S3 dạng JSONL + nạp memory (igraph/networkx) hoặc Postgres bảng graph_edges.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

BUILD_BUDGET_S = 5.0


@dataclass
class GraphStats:
    n_nodes: int
    n_edges: int
    build_seconds: float
    within_budget: bool


@dataclass
class Node:
    node_id: str
    kind: str  # entity | person | org | class | region
    label: str
    props: dict = field(default_factory=dict)


def build_from_csv(csv_path: str) -> GraphStats:
    """TODO(impl): đọc CSV -> entity/query_type/parent_class -> triple.

    Đo được: 500 entity ~0,8 s; ~12.000 entity (80K ảnh) ~3,5-4,5 s.
    """
    from storage.local import connect, counts, import_approved

    if not counts()["entities"]:
        import_approved(csv_path)
    t0 = time.perf_counter()
    with connect() as conn:
        entities = conn.execute("SELECT entity_id, parent_class FROM entities").fetchall()
        conn.execute("DELETE FROM graph_edges")
        edges = [(e[0], "IN_CLASS", "class:" + e[1]) for e in entities if e[1]]
        conn.executemany("INSERT OR IGNORE INTO graph_edges VALUES (?,?,?)", edges)
    elapsed = time.perf_counter() - t0
    return GraphStats(
        len(entities) + len({e[2] for e in edges}), len(edges), elapsed, elapsed < BUILD_BUDGET_S
    )


def load(path: str = "/data/graph/entity_graph.jsonl"):
    """TODO(impl): nạp graph vào memory; giữ < 100 MB ở mức 80K ảnh."""
    raise NotImplementedError


def resolve_hops(chain: list[str], g) -> list[str]:
    """TODO(impl): 'con trai' + 'chủ tịch' + 'Phạm Nhật Vượng'
    -> Vingroup --CHAIRMAN_OF--> Phạm Nhật Vượng --PARENT_OF--> Phạm Nhật Quân
    -> trả [entity_id đích]
    """
    raise NotImplementedError


def siblings_of(entity_id: str, relation: str = "IN_CLASS") -> list[str]:
    """Dùng cho SET QUERY: 'những con vật sống trong rừng' -> các sibling của con hổ."""
    from storage.local import connect

    with connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                """SELECT DISTINCT b.src_id FROM graph_edges a
            JOIN graph_edges b ON a.dst_id=b.dst_id AND a.relation=b.relation
            WHERE a.src_id=? AND a.relation=? AND b.src_id<>?""",
                (entity_id, relation, entity_id),
            )
        ]


def parents_of(entity_id: str, relation: str = "IN_CLASS") -> list[str]:
    from storage.local import connect

    with connect() as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT dst_id FROM graph_edges WHERE src_id=? AND relation=?",
                (entity_id, relation),
            )
        ]


def to_jsonl(stats: GraphStats, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "stats", **stats.__dict__}, ensure_ascii=False) + "\n")
