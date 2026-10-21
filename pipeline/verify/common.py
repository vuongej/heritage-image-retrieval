"""Shared helpers for the Jev verify pipeline (docs/CAI_TIEN_PIPELINE_JEV_TYPESAFE_FULL)."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path
from urllib.parse import urlsplit

from storage.runtime import source_csv

DEFAULT_CSV = source_csv()
REQUIRED_COLUMNS = (
    "entity_id",
    "canonical_name",
    "category",
    "image_url",
    "description",
    "from_db",
)


def run_dir() -> Path:
    """All artefacts of one verify run (thumbnails, npy, jsonl, reports)."""
    path = Path(os.getenv("VERIFY_DIR", "data/verify"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def norm(text: str | None) -> str:
    """Group key: no accents, lowercase, alnum + single spaces ('Chùa X (Hà Nội)' -> 'chua x ha noi')."""
    s = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def category_bucket(category: str | None) -> str:
    """'Đền thờ — Đồng bằng sông Hồng (...)' -> 'đền thờ' (479 buckets on the 80k file)."""
    return re.sub(r"\s+", " ", (category or "").split("(")[0].split("—")[0]).strip().lower()


def host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def row_key(row: dict) -> str:
    """Stable per-image id: sha256 of the URL (the CSV sha256 column is 100% empty)."""
    return hashlib.sha256(row["image_url"].strip().encode()).hexdigest()


def read_csv(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = set(REQUIRED_COLUMNS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Missing CSV columns: {sorted(missing)}")
        rows = []
        for line_no, row in enumerate(reader, 2):
            row = {k: (v or "") for k, v in row.items()}
            row["line"] = line_no
            rows.append(row)
        return rows


def write_jsonl(path: Path, items: Iterable[dict]) -> int:
    n = 0
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        for item in items:
            stream.write(json.dumps(item, ensure_ascii=False) + "\n")
            n += 1
    tmp.replace(path)
    return n


def read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
