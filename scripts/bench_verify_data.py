"""Dữ liệu dùng chung cho benchmark router Phần A (bench_verify_collect / bench_verify_router).

Tái dựng đúng tập của scripts.eval_verify_human từ cache trong VERIFY_DIR (không tải, không encode
lại): nhãn người, split theo nhóm tên (seed 42), kết quả gate / tải, embedding SigLIP2, 14 feature.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pipeline.verify import features, gate, split
from pipeline.verify.common import read_jsonl, row_key, run_dir
from scripts.eval_verify_human import (
    DEFAULT_VERIFY_DIR,
    embed_cached,
    guard,
    load_rows,
    use_verify_dir,
)

__all__ = ["DEFAULT_VERIFY_DIR", "use_verify_dir"]

SPLIT_SEED = 42
VLM_BATCH_FILE = "vlm_batch.jsonl"  # judge_batch (tầng T5) cho mọi ảnh VAL + TEST
BOOT_FILE = "boot_single.jsonl"  # label_single (bootstrap S3) cho mẫu TRAIN + VAL
BOOT_PICKED_FILE = "boot_picked.json"  # đúng danh sách ảnh của mẫu phân tầng


@dataclass
class Dataset:
    rows: list[dict]  # mọi dòng có nhãn (kể cả bị rule loại)
    side_of: dict[str, str]  # image_url -> train/val/test
    group_of: dict[str, str]  # image_url -> nhóm tên
    rule_of: dict[int, str]  # id(row) -> lý do rule loại (gate / dead / too_small / dup_sha256)
    fetch: dict[str, dict]  # key -> bản ghi fetch.jsonl
    ok: list[dict]  # ảnh qua được rule, theo đúng thứ tự hàng của X
    X: np.ndarray  # (n_ok, 768 + 14): embedding ảnh + scalar, như head production
    scalars: np.ndarray  # (n_ok, 14)
    emb: dict[str, np.ndarray]  # img / name / desc, float32
    y: np.ndarray  # 1 = người duyệt yes
    side: np.ndarray  # train/val/test theo hàng của X
    groups: np.ndarray
    entity: np.ndarray
    extra: dict = field(default_factory=dict)


def load(csv_path: str = "data/test.csv") -> Dataset:
    guard()
    rows = load_rows(csv_path)
    sp = split.split(rows, seed=SPLIT_SEED)
    side_of, group_of = sp["assignment"], sp["group_of_url"]
    live, report = gate.run(rows, noext_policy="download")
    gate_code = {r["line"]: r["gate"] for r in report["rejected"]}
    live_ids = {id(r) for r in live}
    state = {r["key"]: r for r in read_jsonl(run_dir() / "fetch.jsonl")}
    # Trùng nội dung trong cùng entity: giữ dòng đầu, như fetch.mark_sha_duplicates.
    seen: set[tuple[str, str]] = set()
    rule_of: dict[int, str] = {}
    ok = []
    for r in rows:
        if id(r) not in live_ids:
            rule_of[id(r)] = gate_code.get(r["line"], "gate")
            continue
        rec = state.get(row_key(r), {})
        status = rec.get("status", "missing")
        if status == "ok":
            k = (r["entity_id"], rec["sha256"])
            if k in seen:
                status = "dup_sha256"
            else:
                seen.add(k)
        if status != "ok":
            rule_of[id(r)] = status
            continue
        ok.append(r)
    emb, _ = embed_cached(ok, lambda _m: None)
    groups = [group_of[r["image_url"]] for r in ok]
    X, _ = features.build(ok, [state[row_key(r)] for r in ok], emb, groups, features.priors(live))
    return Dataset(
        rows=rows,
        side_of=side_of,
        group_of=group_of,
        rule_of=rule_of,
        fetch=state,
        ok=ok,
        X=X.astype(np.float32),
        scalars=X[:, -len(features.SCALAR_NAMES):].astype(np.float32),
        emb={k: v.astype(np.float32) for k, v in emb.items()},
        y=np.array([r["human"] == "yes" for r in ok], int),
        side=np.array([side_of[r["image_url"]] for r in ok]),
        groups=np.array(groups),
        entity=np.array([r["entity_id"] for r in ok]),
    )


def read_cache(name: str) -> dict[str, dict]:
    path = run_dir() / name
    return {d["key"]: d for d in read_jsonl(path) if "error" not in d} if path.exists() else {}


def append(name: str, records: list[dict]) -> None:
    guard()
    with open(run_dir() / name, "a", encoding="utf-8") as fh:
        for d in records:
            fh.write(json.dumps(d, ensure_ascii=False) + "\n")


def usage_since(offset: int, tags: tuple[str, ...]) -> dict:
    """Token và USD của các request DeepSeek ghi sau dòng `offset` của deepseek_usage.jsonl."""
    from storage.runtime import data_dir

    path = data_dir() / "deepseek_usage.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()[offset:] if path.exists() else []
    events = [json.loads(x) for x in lines]
    events = [e for e in events if e.get("tag", "").startswith(tags)]
    p_in = float(os.getenv("DEEPSEEK_PRICE_INPUT_PER_MTOK", "0.3"))
    p_hit = float(os.getenv("DEEPSEEK_PRICE_CACHE_HIT_PER_MTOK", "0.006"))
    p_out = float(os.getenv("DEEPSEEK_PRICE_OUTPUT_PER_MTOK", "1.2"))
    hit = sum(e["usage"].get("prompt_cache_hit_tokens", 0) for e in events)
    prompt = sum(e["usage"].get("prompt_tokens", 0) for e in events)
    out = sum(e["usage"].get("completion_tokens", 0) for e in events)
    lat = sorted(e.get("latency_ms", 0) for e in events)
    return {
        "requests": len(events),
        "prompt_tokens": prompt,
        "cache_hit_tokens": hit,
        "completion_tokens": out,
        "usd": round(((prompt - hit) * p_in + hit * p_hit + out * p_out) / 1e6, 4),
        "latency_ms_p50": lat[len(lat) // 2] if lat else None,
        "latency_ms_p95": lat[int(len(lat) * 0.95)] if lat else None,
    }


def usage_lines() -> int:
    from storage.runtime import data_dir

    path = data_dir() / "deepseek_usage.jsonl"
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def reports_dir() -> Path:
    path = Path("reports/verify_router")
    path.mkdir(parents=True, exist_ok=True)
    return path
