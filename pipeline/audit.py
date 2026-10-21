"""Sampled Part-A audit of already-approved images: download -> Stage 1 -> Stage 3 (VLM).

The catalog is approved, so this never removes images from the index. It measures how
the Stage 1 gates and the Stage 3 verdict agree with the human approval, and the real
per-image token cost of Stage 3. Stage 2 has no trained classifier in this repo, so
every decodable image goes to Stage 3 (audit mode) instead of only the uncertain band.
"""

from __future__ import annotations

import json
import random
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pipeline import stage1_heuristics, stage3_vlm
from storage.images import FetchError, decode, fetch_image
from storage.local import connect
from storage.runtime import data_dir


def stratified_sample(size: int, seed: int) -> list[dict]:
    """One image per category in random order, cycling until `size` is reached."""
    with connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                """SELECT i.rownum, i.image_id, i.image_url, i.description, i.entity_id,
                e.entity_name, e.parent_class FROM images i JOIN entities e USING(entity_id)
                ORDER BY i.rownum"""
            )
        ]
    rng = random.Random(seed)
    by_class: dict[str, list[dict]] = {}
    for row in rows:
        by_class.setdefault(row["parent_class"] or "", []).append(row)
    pools = list(by_class.values())
    for pool in pools:
        rng.shuffle(pool)
    rng.shuffle(pools)
    picked: list[dict] = []
    while len(picked) < min(size, len(rows)):
        for pool in pools:
            if pool and len(picked) < size:
                picked.append(pool.pop())
    return picked


def _download(row: dict) -> tuple[dict, bytes | str]:
    try:
        return row, fetch_image(row["image_url"])
    except FetchError as exc:
        return row, str(exc)


def _usage_lines() -> int:
    path = data_dir() / "deepseek_usage.jsonl"
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def run(size: int, out: Path, seed: int = 42, workers: int = 16) -> dict:
    started = time.perf_counter()
    sample = stratified_sample(size, seed)
    with ThreadPoolExecutor(workers) as pool:
        downloads = list(pool.map(_download, sample))
    download_seconds = time.perf_counter() - started
    seen: set[int] = set()
    records, decoded = [], []
    for row, data in downloads:
        record = {k: row[k] for k in ("image_id", "image_url", "entity_name", "parent_class")}
        if isinstance(data, str):
            records.append({**record, "status": "download_failed", "error": data})
            continue
        try:
            img = decode(data)
        except FetchError as exc:
            records.append({**record, "status": "decode_failed", "error": str(exc)})
            continue
        s1 = stage1_heuristics.run(img, seen_hashes=seen)
        record.update(
            status="analyzed",
            bytes=len(data),
            width=s1.width,
            height=s1.height,
            stage1_passed=s1.passed,
            stage1_reasons=s1.reasons,
            stage1_metrics={k: round(v, 4) for k, v in s1.metrics.items()},
            phash64=f"{s1.phash64:016x}",
        )
        records.append(record)
        decoded.append((record, data, row))
    stage1_seconds = time.perf_counter() - started - download_seconds

    usage_before = _usage_lines()
    t = time.perf_counter()

    def judge(item):
        record, data, row = item
        context = {
            "entity": row["entity_name"],
            "category": row["parent_class"],
            "description": row["description"],
        }
        try:
            verdict = stage3_vlm.judge(data, context)
            record.update(
                stage3_decision=verdict.decision,
                stage3_scores=verdict.scores,
                stage3_reason=verdict.reason,
            )
        except Exception as exc:  # one bad image must not abort the audit
            record.update(stage3_decision="error", stage3_error=f"{type(exc).__name__}: {exc}")

    if stage3_vlm.enabled():
        with ThreadPoolExecutor(6) as pool:
            list(pool.map(judge, decoded))
    stage3_seconds = time.perf_counter() - t

    usage_path = data_dir() / "deepseek_usage.jsonl"
    events = (
        [json.loads(x) for x in usage_path.read_text(encoding="utf-8").splitlines()[usage_before:]]
        if usage_path.exists()
        else []
    )
    analyzed = [r for r in records if r["status"] == "analyzed"]
    judged = [r for r in analyzed if r.get("stage3_decision") in {"accept", "reject"}]
    reason_kinds = Counter(
        reason.split(" ")[0] for r in analyzed for reason in r.get("stage1_reasons", [])
    )
    cascade = Counter(
        "stage1_reject"
        if not r["stage1_passed"]
        else "stage3_" + r.get("stage3_decision", "skipped")
        for r in analyzed
    )
    prompt_tokens = sum(e["usage"].get("prompt_tokens", 0) for e in events)
    completion_tokens = sum(e["usage"].get("completion_tokens", 0) for e in events)
    summary = {
        "sample_size": len(sample),
        "seed": seed,
        "categories_covered": len({r["parent_class"] for r in sample}),
        "status": dict(Counter(r["status"] for r in records)),
        "download_errors": dict(Counter(r["error"] for r in records if "error" in r)),
        "stage1_pass": sum(r["stage1_passed"] for r in analyzed),
        "stage1_reject_reasons": dict(reason_kinds),
        "stage3_enabled": stage3_vlm.enabled(),
        "stage3_judged": len(judged),
        "stage3_errors": sum(r.get("stage3_decision") == "error" for r in analyzed),
        "stage3_accept": sum(r["stage3_decision"] == "accept" for r in judged),
        "stage3_reject": sum(r["stage3_decision"] == "reject" for r in judged),
        "stage3_accept_given_stage1_pass": _rate(judged, True),
        "stage3_accept_given_stage1_reject": _rate(judged, False),
        "cascade_outcome": dict(cascade),
        "stage3_billed_requests": len(events),
        "stage3_prompt_tokens": prompt_tokens,
        "stage3_completion_tokens": completion_tokens,
        "stage3_tokens_per_image": (
            {
                "prompt": round(prompt_tokens / len(events), 1),
                "completion": round(completion_tokens / len(events), 1),
            }
            if events
            else None
        ),
        "stage3_latency_ms_mean": (
            round(sum(e["latency_ms"] for e in events) / len(events)) if events else None
        ),
        "seconds": {
            "download": round(download_seconds, 2),
            "stage1": round(stage1_seconds, 2),
            "stage3": round(stage3_seconds, 2),
        },
        "note": "Approved images are audited, never removed from the index.",
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(
        json.dumps({"summary": summary, "images": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _rate(judged: list[dict], stage1_passed: bool) -> float | None:
    group = [r for r in judged if r["stage1_passed"] is stage1_passed]
    return (
        round(sum(r["stage3_decision"] == "accept" for r in group) / len(group), 4)
        if group
        else None
    )
