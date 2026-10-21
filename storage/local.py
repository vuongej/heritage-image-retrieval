"""SQLite catalog for approved CSV metadata; no implicit image downloads."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
import uuid
from pathlib import Path

from storage.runtime import data_dir


def plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower()).replace("đ", "d")
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(data_dir() / "catalog.sqlite3", timeout=60)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS entities (
            entity_id TEXT PRIMARY KEY, entity_name TEXT, entity_slug TEXT, parent_class TEXT);
        CREATE TABLE IF NOT EXISTS images (
            rownum INTEGER PRIMARY KEY, image_id TEXT UNIQUE NOT NULL, entity_id TEXT NOT NULL,
            image_url TEXT NOT NULL, description TEXT, page_url TEXT,
            metadata_text TEXT NOT NULL, record_json TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS ix_local_images_entity ON images(entity_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS image_fts USING fts5(text);
        CREATE TABLE IF NOT EXISTS graph_edges (
            src_id TEXT, relation TEXT, dst_id TEXT, PRIMARY KEY(src_id, relation, dst_id));
        CREATE TABLE IF NOT EXISTS llm_cache (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    _migrate(conn)
    return conn


# Schema v2 (Phase 2): cột chất lượng / kích thước / caption, điền bởi scripts.migrate_images_v2.
# NULL = chưa biết (báo cáo migrate ghi lý do), không phải "đạt".
IMAGE_COLUMNS_V2 = {
    "verify": "TEXT",  # 'yes' | 'no' | NULL
    "verify_source": "TEXT",  # human | vlm_pilot | NULL
    "width": "INTEGER",
    "height": "INTEGER",
    "has_watermark": "INTEGER",  # 0 | 1 | NULL
    "fetch_status": "TEXT",  # ok | too_small | dead | dup_sha256 | NULL (chưa tải)
    "caption": "TEXT",
    "caption_source": "TEXT",
}
_migrated: set[str] = set()


def _migrate(conn: sqlite3.Connection) -> None:
    path = str(data_dir() / "catalog.sqlite3")
    if path in _migrated:
        return
    have = {row[1] for row in conn.execute("PRAGMA table_info(images)")}
    for column, kind in IMAGE_COLUMNS_V2.items():
        if column not in have:
            conn.execute(f"ALTER TABLE images ADD COLUMN {column} {kind}")
    conn.commit()
    _migrated.add(path)


def fingerprint(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def catalog_fingerprint(source_sha256: str, usernames: list[str] | None) -> str:
    """CSV SHA-256, scoped by the username filter so a subset never reuses a full index."""
    if not usernames:
        return source_sha256
    scope = json.dumps(sorted(set(usernames)), ensure_ascii=False)
    return hashlib.sha256(f"{source_sha256}:{scope}".encode()).hexdigest()


def in_scope(row: dict, usernames: list[str] | None) -> bool:
    return not usernames or row.get("username", "").strip() in usernames


def import_approved(csv_path: str | Path, usernames: list[str] | None = None) -> dict:
    path = Path(csv_path)
    usernames = sorted(set(usernames)) if usernames else None
    source_digest = fingerprint(path)
    digest = catalog_fingerprint(source_digest, usernames)
    scope = {"usernames": usernames, "source_csv_sha256": source_digest}
    with connect() as conn:
        old = conn.execute("SELECT value FROM metadata WHERE key='csv_sha256'").fetchone()
        if old and old[0] == digest:
            return {**counts(conn), "csv_sha256": digest, **scope, "reused": True}
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"entity_id", "canonical_name", "slug", "category", "image_url", "flag"}
            if usernames:
                required.add("username")
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"Missing CSV columns: {sorted(missing)}")
            for table in ("images", "entities", "image_fts", "graph_edges"):
                conn.execute(f"DELETE FROM {table}")
            seen = set()
            skipped = out_of_scope = 0
            for row in reader:
                if not in_scope(row, usernames):
                    out_of_scope += 1
                    continue
                url = row["image_url"].strip()
                if row["flag"].strip().lower() != "approved" or not url.startswith(
                    ("http://", "https://")
                ):
                    skipped += 1
                    continue
                if url in seen:
                    continue
                seen.add(url)
                eid = row["entity_id"].strip()
                if not eid or not row["canonical_name"].strip():
                    raise ValueError(f"Missing entity identity at CSV line {reader.line_num}")
                conn.execute(
                    "INSERT OR IGNORE INTO entities VALUES (?,?,?,?)",
                    (eid, row["canonical_name"], row["slug"], row["category"]),
                )
                text = ". ".join(
                    filter(
                        None, [row["canonical_name"], row["category"], row.get("description", "")]
                    )
                )
                ordinal = len(seen)
                conn.execute(
                    "INSERT INTO images (rownum, image_id, entity_id, image_url, description,"
                    " page_url, metadata_text, record_json) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        ordinal,
                        str(uuid.uuid5(uuid.NAMESPACE_URL, url)),
                        eid,
                        url,
                        row.get("description", ""),
                        row.get("source_url", ""),
                        text,
                        json.dumps(row, ensure_ascii=False),
                    ),
                )
                conn.execute(
                    "INSERT INTO image_fts(rowid,text) VALUES (?,?)", (ordinal, plain(text))
                )
                if ordinal % 10000 == 0:
                    print(f"[import] {ordinal:,} approved images", flush=True)
        conn.execute("INSERT OR REPLACE INTO metadata VALUES ('csv_sha256',?)", (digest,))
        conn.execute(
            "INSERT OR REPLACE INTO metadata VALUES ('source_csv',?)", (str(path.resolve()),)
        )
        conn.execute("INSERT OR REPLACE INTO metadata VALUES ('skipped_rows',?)", (str(skipped),))
        conn.execute(
            "INSERT OR REPLACE INTO metadata VALUES ('source_csv_sha256',?)", (source_digest,)
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata VALUES ('usernames',?)", (json.dumps(usernames),)
        )
        return {
            **counts(conn),
            "csv_sha256": digest,
            **scope,
            "reused": False,
            "skipped_rows": skipped,
            "out_of_scope_rows": out_of_scope,
        }


def catalog_scope() -> dict:
    with connect() as conn:
        rows = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
    return {
        "source_csv": rows.get("source_csv"),
        "usernames": json.loads(rows.get("usernames") or "null"),
    }


def counts(conn=None) -> dict:
    if conn is None:
        with connect() as db:
            return counts(db)
    return {
        "images": conn.execute("SELECT count(*) FROM images").fetchone()[0],
        "entities": conn.execute("SELECT count(*) FROM entities").fetchone()[0],
    }


def image_rows(ordinals: list[int]) -> list[dict]:
    if not ordinals:
        return []
    with connect() as conn:
        marks = ",".join("?" for _ in ordinals)
        rows = conn.execute(
            f"""SELECT i.*, e.entity_name, e.entity_slug, e.parent_class
            FROM images i JOIN entities e USING(entity_id) WHERE i.rownum IN ({marks})""",
            ordinals,
        ).fetchall()
    by_id = {row["rownum"]: dict(row) for row in rows}
    return [by_id[n] for n in ordinals if n in by_id]


# Hư từ tiếng Việt bỏ khỏi truy vấn FTS (Phase 2.4). So khớp trên dạng CÒN DẤU: bỏ "cho" (giới từ)
# nhưng giữ "chợ", bỏ "đến" nhưng giữ "đền", bỏ "có" nhưng giữ "cổ" — FTS lưu văn bản không dấu.
# Không có hư từ tiếng Anh ("an" là Hội An, Long An) và không có "cái" (Cái Răng, Cái Bè).
VI_STOPWORDS = frozenset(
    """và của ở tại các những một mọi này kia đó ấy được bị bởi cho từ đến với cùng trong trên
    dưới về theo sau trước giữa ngoài bên phía là thì mà nhưng hoặc hay hoặc nếu khi để vì nên
    có không chưa đã đang sẽ vẫn cũng rất quá lắm nhiều ít thêm nữa chỉ đều luôn còn hãy xin
    ảnh hình chụp tìm xem cho tôi mình bạn chúng ta nào gì đâu sao thế vậy ra vào lên xuống
    chiếc con nơi chỗ việc sự điều như nhau thật thực đúng rồi vừa mới""".split()
)


def fts_terms(query: str) -> list[str]:
    words = re.findall(r"\w+", unicodedata.normalize("NFC", query.lower()))
    kept = [plain(w) for w in words if w not in VI_STOPWORDS]
    return list(dict.fromkeys(kept or [plain(w) for w in words]))


def lexical_candidates(query: str, limit: int = 100) -> list[int]:
    """BM25: mọi từ (AND) trước, rồi bổ sung bằng OR cho đủ `limit`."""
    terms = fts_terms(query)
    if not terms:
        return []
    found: list[int] = []
    with connect() as conn:
        for joiner in (" AND ", " OR ") if len(terms) > 1 else (" OR ",):
            expression = joiner.join(f'"{term}"' for term in terms)
            for (rowid,) in conn.execute(
                "SELECT rowid FROM image_fts WHERE image_fts MATCH ? ORDER BY rank LIMIT ?",
                (expression, limit),
            ):
                if rowid not in found:
                    found.append(rowid)
            if len(found) >= limit:
                break
    return found[:limit]


def cache_get(key: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM llm_cache WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_put(key: str, value: dict) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO llm_cache VALUES (?,?)",
            (key, json.dumps(value, ensure_ascii=False)),
        )
