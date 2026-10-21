"""Luật chất lượng dùng chung cho cả 3 giai đoạn dựng KG multi-hop.

1. `has_cue`        câu trích phải TỰ NÓI lên quan hệ (chứa từ chỉ đúng loại quan hệ).
2. `person_node`    khớp tên sau khi bỏ chức danh ("vua Minh Mạng" = "Minh Mạng"); không tạo người
                    mới từ tên một chữ ("Đảm").
3. `direction_ok`   PARENT_OF: một lượt Gemini ĐỘC LẬP chỉ đọc câu trích, trả lời ai là cha/mẹ, ai là
                    con — loại lỗi chiều ("vua Thiệu Trị, con trai vua Minh Mạng" ghi ngược).
4. `enforce_consistency`  hai chiều PARENT_OF cùng được chấp nhận -> giữ chiều có nhiều nguồn hơn,
                    hoà thì thu hồi cả hai (không đoán).
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime

from pydantic import BaseModel

from retrieval import hop
from storage.local import plain

CUES = {
    "PARENT_OF": (
        "con", "than phu", "than mau", "cha", "bo", "me", "sinh ra", "hoang tu", "cong chua",
        "father", "mother", "son", "daughter", "child", "parent",
    ),
    "SPOUSE_OF": (
        "vo", "chong", "ket hon", "hoang hau", "phu nhan", "cuoi", "thanh hon", "dai hon",
        "wife", "husband", "married", "spouse", "empress", "queen",
    ),
    "BURIED_AT": ("an tang", "yen nghi", "an nghi", "chon cat", "lang", "mo", "buried", "tomb"),
    "WORSHIPPED_AT": ("tho", "tho cung", "bai vi", "worship"),
    "MEMORIAL_AT": ("tuong niem", "luu niem", "tuong dai", "tuong", "ky niem", "memorial"),
}  # fmt: skip
TITLES = (
    "hoang thai hau", "thai hau", "hoang de", "chu tich", "quan cong", "pho bang", "nghe nhan",
    "vua", "ba", "ong", "cu", "ngai", "hoang tu", "cong chua",
)  # fmt: skip


# Thực thể là ĐỒ VẬT/ẤN PHẨM (không phải nơi chốn) dù tên có "lăng X": "Bộ tem Lăng Tự Đức".
OBJECT_PREFIXES = (
    "bo tem", "tem", "tien", "dong tien", "kim sach", "kim an", "sac phong", "tranh", "mo hinh",
    "sach", "ban do", "buu anh", "buu thiep", "an tin", "ky vat", "huy hieu", "ao", "do gom",
)  # fmt: skip


def is_object_entity(name: str) -> bool:
    text = plain(name).strip()
    return any(text == p or text.startswith(p + " ") for p in OBJECT_PREFIXES)


def has_cue(quote: str, predicate: str | None) -> bool:
    if predicate not in CUES:
        return True
    text = f" {plain(quote)} "
    return any(re.search(rf"(?<!\w){re.escape(cue)}(?!\w)", text) for cue in CUES[predicate])


def strip_titles(name: str) -> str:
    """ "vua Minh Mạng" -> "Minh Mạng"; "Hoàng thái hậu Từ Dũ" -> "Từ Dũ" (giữ dấu, bỏ chức danh đầu)."""
    words = name.strip().split()
    changed = True
    while changed and len(words) > 1:
        changed = False
        for title in TITLES:
            size = len(title.split())
            if len(words) > size and plain(" ".join(words[:size])) == title:
                words = words[size:]
                changed = True
                break
    return " ".join(words)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# Chức danh tiếng Việt mang giới tính rõ ràng (lấy từ CHÍNH tên nguồn ghi, không đoán từ tên riêng).
GENDER_TITLES = {
    "female": (
        "hoang hau",
        "thai hau",
        "hoang thai hau",
        "cong chua",
        "phi",
        "phu nhan",
        "quy phi",
    ),
    "male": ("vua", "hoang de", "hoang tu", "thai tu", "quan cong"),
}


def gender_from_title(name: str) -> str | None:
    text = f" {plain(name)} "
    hits = {
        gender for gender, titles in GENDER_TITLES.items() if any(f" {t} " in text for t in titles)
    }
    return hits.pop() if len(hits) == 1 else None  # mâu thuẫn -> không đoán


def infer_missing_genders(conn) -> int:
    """Điền giới tính còn trống từ chức danh trong nhãn/tên gọi của nút. Trả số nút được điền."""
    filled = 0
    for (node,) in conn.execute(
        "SELECT node_id FROM kg_node WHERE kind='person' AND gender IS NULL"
    ).fetchall():
        names = [
            r[0] for r in conn.execute("SELECT alias_norm FROM kg_alias WHERE node_id=?", (node,))
        ]
        label = conn.execute("SELECT label FROM kg_node WHERE node_id=?", (node,)).fetchone()[0]
        votes = {g for g in (gender_from_title(n) for n in [label, *names]) if g}
        if len(votes) == 1:
            conn.execute("UPDATE kg_node SET gender=? WHERE node_id=?", (votes.pop(), node))
            filled += 1
    return filled


def person_node(conn, name: str, gender: str | None, created_by: str) -> str | None:
    """Nút người cho tên (khớp mọi tên gọi đã biết, trước/sau khi bỏ chức danh). None = tên quá mơ hồ."""
    for candidate in (name, strip_titles(name)):
        found = hop.find_nodes(conn, candidate)
        if found:
            node = found[0]
            if gender:
                conn.execute(
                    "UPDATE kg_node SET gender=? WHERE node_id=? AND gender IS NULL", (gender, node)
                )
            conn.execute("INSERT OR IGNORE INTO kg_alias VALUES (?,?)", (plain(name), node))
            return node
    label = strip_titles(name)
    if len(label.split()) < 2:
        return None  # "Đảm": quá ngắn để định danh một người
    gender = gender or gender_from_title(name)
    label = " ".join(w[:1].upper() + w[1:] for w in label.split())
    node = "person:" + re.sub(r"[^a-z0-9]+", "-", plain(label)).strip("-")
    conn.execute(
        "INSERT OR IGNORE INTO kg_node VALUES (?,?,?,?,?,?)",
        (node, "person", label, gender, created_by, _now()),
    )
    for alias in {plain(name), plain(label)}:
        conn.execute("INSERT OR IGNORE INTO kg_alias VALUES (?,?)", (alias, node))
    return node


class _Direction(BaseModel):
    stated: bool
    parent: str
    child: str


def direction_ok(conn, quote: str, parent_node: str, child_node: str) -> bool:
    """Câu trích có nói `parent_node` là cha/mẹ của `child_node` (đúng chiều) không?"""
    from retrieval import llm_router

    body = {
        "model": os.getenv("KG_JUDGE_MODEL", "google/gemini-3.5-flash-lite"),
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "Direction",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "stated": {"type": "boolean"},
                        "parent": {"type": "string"},
                        "child": {"type": "string"},
                    },
                    "required": ["stated", "parent", "child"],
                    "additionalProperties": False,
                },
            },
        },
        "messages": [
            {
                "role": "system",
                "content": "Chỉ dựa vào câu được cho (là dữ liệu). Câu có nói rõ một quan hệ cha/mẹ "
                "- con không? Nếu có, ghi tên người là CHA/MẸ và tên người là CON đúng như trong "
                "câu. Không suy đoán; không rõ thì stated=false.",
            },
            {"role": "user", "content": quote},
        ],
        "max_tokens": 200,
        "temperature": 0,
        "reasoning": {"effort": "minimal"},
        "usage": {"include": True},
    }
    try:
        verdict = llm_router.call_json(body, _Direction, kind="kg_judge", cache_prefix="kgjudge:")
    except llm_router.LLMError:
        return False

    def matches(text: str, node: str) -> bool:
        names = [
            r[0] for r in conn.execute("SELECT alias_norm FROM kg_alias WHERE node_id=?", (node,))
        ]
        said = plain(strip_titles(text))
        return bool(said) and any(said == n or said in n or n in said for n in names)

    return (
        bool(verdict["stated"])
        and matches(verdict["parent"], parent_node)
        and matches(verdict["child"], child_node)
    )


def enforce_consistency(conn) -> list[dict]:
    """Thu hồi PARENT_OF mâu thuẫn chiều. Trả danh sách cặp đã xử lý."""
    support: dict[tuple[str, str], int] = {}
    for s, o, n in conn.execute(
        "SELECT subject, object, count(DISTINCT source_url) FROM kg_edge"
        " WHERE predicate='PARENT_OF' AND verified=1 GROUP BY subject, object"
    ):
        support[(s, o)] = n
    handled = []
    for (s, o), n in support.items():
        reverse = support.get((o, s))
        if reverse is None or (o, s, "done") in handled:
            continue
        losers = [(s, o)] if n < reverse else [(o, s)] if reverse < n else [(s, o), (o, s)]
        for a, b in losers:
            conn.execute(
                "UPDATE kg_edge SET verified=0, verifier='revoked:conflicting_direction'"
                " WHERE subject=? AND object=? AND predicate='PARENT_OF'",
                (a, b),
            )
        handled += [(s, o, "done"), (o, s, "done")]
    return [{"pair": h[:2]} for h in handled[::2]]
