"""Phase 2.3: nạp 2 collection Qdrant + self-test recall ANN.

  text   — vectors.npy (MiniLM 384d của metadata_text, rownum 1..N) -> img_text
  visual — SigLIP2 768d từ thumbnail đã tải (scripts.fetch_all_images); dùng lại vector của
           data/verify/emb.npz (Phần A) khi đã có, encode bổ sung phần còn lại bằng chính
           encoder của Phần A -> data/local/visual.npy + visual_rows.npy -> img_visual

python -X utf8 -m scripts.build_vector_store text|visual|both [--no-upload]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from retrieval import vector_store
from retrieval.local_index import manifest
from storage.local import connect
from storage.runtime import data_dir

ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "data" / "verify"
REPORT = ROOT / "reports" / "phase2" / "vector_store.json"


def _report(section: str, value: dict) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(REPORT.read_text(encoding="utf-8")) if REPORT.exists() else {}
    data[section] = value
    REPORT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{section}]", json.dumps(value, ensure_ascii=False), flush=True)


def build_text(upload: bool) -> None:
    state = manifest()
    if not state.get("complete"):
        raise RuntimeError("vectors.npy chưa đầy đủ: chạy local_index.build() trước")
    vectors = np.load(data_dir() / "vectors.npy", mmap_mode="r")
    ids = np.arange(1, len(vectors) + 1)
    started = time.perf_counter()
    if upload:
        vector_store.upload(vector_store.TEXT, ids, vectors)
    _report(
        "img_text",
        {
            "points": len(ids),
            "dim": int(vectors.shape[1]),
            "upload_seconds": round(time.perf_counter() - started, 1),
            "self_test": vector_store.self_test(vector_store.TEXT, ids, vectors)
            if upload
            else None,
        },
    )


def build_visual(upload: bool) -> None:
    from pipeline.verify.encoder import ENCODER, embed_images
    from pipeline.verify.fetch import thumb_path

    fetched = {}
    for line in (VERIFY / "fetch.jsonl").open(encoding="utf-8"):
        rec = json.loads(line)
        fetched[rec["key"]] = rec
    with connect() as conn:
        rows = conn.execute("SELECT rownum, image_url FROM images ORDER BY rownum").fetchall()
    known = {}
    old = VERIFY / "emb.npz"
    if old.exists():
        z = np.load(old, allow_pickle=True)
        if str(z["encoder"]) == ENCODER:
            known = {str(k): i for i, k in enumerate(z["keys"])}
            old_img = z["img"].astype(np.float32)
    ids, reused, todo_ids, todo_paths = [], [], [], []
    missing = {"not_fetched": 0, "no_thumbnail": 0}
    for rownum, url in rows:
        key = hashlib.sha256(url.strip().encode()).hexdigest()
        status = fetched.get(key, {}).get("status")
        path = thumb_path(key)
        if status is None:
            missing["not_fetched"] += 1
            continue
        if not path.exists():  # dead / too_small (không lưu thumbnail)
            missing["no_thumbnail"] += 1
            continue
        if key in known:
            reused.append((rownum, known[key]))
        else:
            todo_ids.append(rownum)
            todo_paths.append(path)
    started = time.perf_counter()
    encoded = embed_images(todo_paths) if todo_paths else np.zeros((0, 768), np.float32)
    seconds = time.perf_counter() - started
    vectors = np.concatenate(
        [old_img[[i for _, i in reused]] if reused else np.zeros((0, encoded.shape[1])), encoded]
    ).astype(np.float32)
    ids = np.asarray([r for r, _ in reused] + todo_ids, dtype=np.int64)
    order = np.argsort(ids)
    ids, vectors = ids[order], vectors[order]
    if not np.isfinite(vectors).all() or len(np.unique(ids)) != len(ids):
        raise ValueError("vector ảnh không hợp lệ hoặc trùng rownum")
    np.save(data_dir() / "visual.npy", vectors)
    np.save(data_dir() / "visual_rows.npy", ids)
    info = {
        "complete": True,
        "encoder": ENCODER,
        "dim": int(vectors.shape[1]),
        "points": len(ids),
        "catalog_images": len(rows),
        "coverage": round(len(ids) / max(1, len(rows)), 4),
        "missing": missing,
        "reused_from_emb_npz": len(reused),
        "encoded_now": len(todo_ids),
        "encode_seconds": round(seconds, 1),
        "images_per_second": round(len(todo_ids) / seconds, 1) if todo_ids else None,
        "csv_sha256": manifest().get("csv_sha256"),
    }
    if upload:
        vector_store.upload(vector_store.VISUAL, ids, vectors)
        info["self_test"] = vector_store.self_test(vector_store.VISUAL, ids, vectors)
    # Manifest ghi SAU CÙNG: server đang chạy chỉ bật nhánh ảnh khi collection đã nạp đủ.
    (data_dir() / "visual_index.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    _report("img_visual", info)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("what", choices=["text", "visual", "both"])
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()
    if args.what in {"text", "both"}:
        build_text(not args.no_upload)
    if args.what in {"visual", "both"}:
        build_visual(not args.no_upload)


if __name__ == "__main__":
    main()
