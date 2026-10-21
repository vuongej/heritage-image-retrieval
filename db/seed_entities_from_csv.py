"""Nạp CSV entity nhóm 1 vào Postgres.

CSV: STT, entity_stt, entity_id, entity_name, entity_slug, branch, priority, score,
     leaf_label, description, so_anh_pass_master, entity_duoi_5_master, image_order,
     image_url, page_url, page_title, image_source, image_width, image_height,
     query_type, nguon, crawled_at, verify, note, verified_at, assigned_member
"""
from __future__ import annotations

import csv
import hashlib
import uuid
from pathlib import Path

COLUMNS = [
    "STT", "entity_stt", "entity_id", "entity_name", "entity_slug", "branch", "priority",
    "score", "leaf_label", "description", "so_anh_pass_master", "entity_duoi_5_master",
    "image_order", "image_url", "page_url", "page_title", "image_source", "image_width",
    "image_height", "query_type", "nguon", "crawled_at", "verify", "note", "verified_at",
    "assigned_member",
]


def sha256_of_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def parse_rows(csv_path: str | Path):
    with open(csv_path, encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh)


def upsert(conn, csv_path: str | Path) -> dict:
    """TODO(impl): dùng COPY + staging table để nạp 80K dòng nhanh."""
    entities, images, links, backfill = {}, {}, 0, []
    for r in parse_rows(csv_path):
        eid = r["entity_id"]
        entities[eid] = (
            eid, r["entity_stt"] or None, r["entity_name"], r["entity_slug"], r["branch"],
            r["priority"], r["score"] or None, r["leaf_label"], r["description"],
            None, r["so_anh_pass_master"] or 0,
            r["entity_duoi_5_master"] == "yes", r["assigned_member"],
        )
        iid = str(uuid.uuid5(uuid.NAMESPACE_URL, r["image_url"]))
        images[iid] = (
            iid, r["image_url"], sha256_of_url(r["image_url"]), None,
            int(r["image_width"] or 0), int(r["image_height"] or 0), None,
            r["page_url"], r["page_title"], r["image_source"], r["query_type"],
            r["nguon"], r["crawled_at"] or None,
        )
        links += 1
        if int(r["so_anh_pass_master"] or 0) == 0:
            backfill.append((eid, "zero_images", 0, r["priority"]))
        elif r["entity_duoi_5_master"] == "yes":
            backfill.append((eid, "under_5_images", int(r["so_anh_pass_master"] or 0), r["priority"]))

    # TODO(impl): execute_values / COPY cho 3 bảng trên
    return {
        "entities": len(entities),
        "images": len(images),
        "image_entity_links": links,
        "backfill_queued": len({b[0] for b in backfill}),
    }
