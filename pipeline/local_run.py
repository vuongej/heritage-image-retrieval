"""Run every approved-metadata stage locally, with real DeepSeek smoke queries."""

from __future__ import annotations

import csv
import json
import os
import random
import re
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from retrieval.graph import build_from_csv
from retrieval.local_index import build
from retrieval.search import search
from storage.local import connect, import_approved, in_scope
from storage.runtime import data_dir

EVAL_ENTITIES = int(os.getenv("EVAL_ENTITIES", "30"))


def short_class(category: str) -> str:
    """'Chợ truyền thống' from 'Chợ truyền thống — Bắc Bộ (Hà Nội, ...)'."""
    return re.split(r"\s+[—–(]", category, maxsplit=1)[0].strip()


def smoke_queries(conn) -> list[dict]:
    entities = conn.execute("""SELECT e.entity_id, e.entity_name FROM entities e
        JOIN images i USING(entity_id) GROUP BY e.entity_id ORDER BY min(i.rownum) LIMIT 3""").fetchall()
    queries = [
        {"query": e["entity_name"], "expected": [e["entity_id"]], "kind": "single_entity"}
        for e in entities
    ]
    if len(entities) >= 2:
        queries.append(
            {
                "query": entities[0]["entity_name"] + " và " + entities[1]["entity_name"],
                "expected": [entities[0]["entity_id"], entities[1]["entity_id"]],
                "kind": "multi_intent",
            }
        )
    # Set query from the largest category whose short name is not a bare region label.
    classes = Counter()
    for (category,) in conn.execute(
        "SELECT parent_class FROM images JOIN entities USING(entity_id)"
    ):
        if category:
            classes[short_class(category)] += 1
    for name, _ in classes.most_common():
        if 2 <= len(name.split()) <= 5:
            queries.append(
                {"query": "các " + name.lower(), "expected": [], "kind": "set_query", "class": name}
            )
            break
    return queries


def eval_cases(conn, size: int, seed: int = 42) -> list[dict]:
    """Deterministic entity sample spread over categories; labels = CSV entity membership."""
    entities = conn.execute(
        "SELECT entity_id, entity_name, parent_class FROM entities ORDER BY entity_id"
    ).fetchall()
    rng = random.Random(seed)
    by_class: dict[str, list] = {}
    for e in entities:
        by_class.setdefault(e["parent_class"] or "", []).append(e)
    classes = sorted(by_class)
    rng.shuffle(classes)
    picked = [rng.choice(by_class[c]) for c in classes[:size]]
    cases = []
    for entity in picked:
        relevant = [
            r[0]
            for r in conn.execute(
                "SELECT image_id FROM images WHERE entity_id=? ORDER BY rownum",
                (entity["entity_id"],),
            )
        ]
        cases.append(
            {
                "query": entity["entity_name"],
                "intent_type": "single",
                "relevant": relevant,
                "label_source": "approved_csv_entity_membership",
            }
        )
    return cases


def run(
    csv_path: str,
    out: str,
    *,
    smoke: bool = True,
    usernames: list[str] | None = None,
    audit_sample: int = 0,
) -> dict:
    started = time.perf_counter()
    stage_seconds: dict[str, float] = {}
    destination = Path(out)
    destination.mkdir(parents=True, exist_ok=True)
    source_rows = scoped_rows = 0
    quarantine = []
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as stream:
        for line_no, row in enumerate(csv.DictReader(stream), 2):
            source_rows += 1
            if not in_scope(row, usernames):
                continue
            scoped_rows += 1
            if row.get("flag", "").lower() != "approved" or not row.get(
                "image_url", ""
            ).strip().startswith(("http://", "https://")):
                quarantine.append(
                    {
                        "line": line_no,
                        "entity_id": row.get("entity_id"),
                        "canonical_name": row.get("canonical_name"),
                        "image_url": row.get("image_url"),
                        "reason": "not_approved_or_non_http_image_url",
                    }
                )
    if usernames and not scoped_rows:
        raise ValueError(f"No CSV rows for usernames {usernames}")
    (destination / "quarantine.json").write_text(
        json.dumps(quarantine, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    stage_seconds["validate"] = time.perf_counter() - started

    t = time.perf_counter()
    catalog = import_approved(csv_path, usernames)
    stage_seconds["import"] = time.perf_counter() - t
    print("[pipeline] catalog:", catalog, flush=True)
    t = time.perf_counter()
    graph = asdict(build_from_csv(csv_path))
    stage_seconds["graph"] = time.perf_counter() - t
    print("[pipeline] graph:", graph, flush=True)
    t = time.perf_counter()
    index = build()
    stage_seconds["index"] = time.perf_counter() - t
    import numpy as np

    vectors = np.load(data_dir() / "vectors.npy", mmap_mode="r")
    finite = True
    norm_min, norm_max = float("inf"), 0.0
    for offset in range(0, len(vectors), 10000):
        batch = vectors[offset : offset + 10000]
        finite = finite and bool(np.isfinite(batch).all())
        norms = np.linalg.norm(batch, axis=1)
        norm_min, norm_max = min(norm_min, float(norms.min())), max(norm_max, float(norms.max()))
    integrity = {
        "rows": len(vectors),
        "dim": vectors.shape[1],
        "all_finite": finite,
        "norm_min": norm_min,
        "norm_max": norm_max,
    }
    del vectors
    if not finite or norm_min < 0.999 or norm_max > 1.001 or integrity["rows"] != catalog["images"]:
        raise RuntimeError("Vector index integrity validation failed")
    report = {
        "source_csv": str(Path(csv_path).resolve()),
        "source_rows": source_rows,
        "usernames": usernames,
        "scoped_rows": scoped_rows,
        "catalog": catalog,
        "quarantined_rows": len(quarantine),
        "graph": graph,
        "index": index,
        "vector_integrity": integrity,
        "provider": os.getenv("LLM_PROVIDER", "none"),
        "model": os.getenv("DEEPSEEK_MODEL"),
        "mode": "approved_metadata",
        "image_downloads": 0,
        "image_moderation": "skipped_as_authorized",
        "storage": str(data_dir()),
        "deployment": "not_run",
        "queries": [],
    }
    if audit_sample:
        from pipeline import audit

        t = time.perf_counter()
        print(f"[audit] Stage 1 + Stage 3 on a {audit_sample}-image sample", flush=True)
        report["audit"] = audit.run(audit_sample, destination)
        report["image_downloads"] = report["audit"]["sample_size"]
        report["image_moderation"] = "sampled_audit_only; approved catalog unchanged"
        stage_seconds["audit"] = time.perf_counter() - t
        print("[audit]", json.dumps(report["audit"], ensure_ascii=False), flush=True)
    if smoke:
        t = time.perf_counter()
        with connect() as conn:
            queries = smoke_queries(conn)
            cases = eval_cases(conn, EVAL_ENTITIES)
        for spec in queries:
            query, expected = spec["query"], spec["expected"]
            print("[search]", query, flush=True)
            result = search(query, top_k=10)
            body = asdict(result)
            body["query"] = query
            body["kind"] = spec["kind"]
            body["expected_entity_ids"] = expected
            found = {h.entity_id for h in result.hits}
            body["expected_entities_found"] = (
                all(eid in found for eid in expected) if expected else None
            )
            if spec.get("class"):
                body["expected_class"] = spec["class"]
                body["class_precision"] = (
                    sum(short_class(h.parent_class or "") == spec["class"] for h in result.hits)
                    / len(result.hits)
                    if result.hits
                    else 0.0
                )
            body["returned_hits"] = len(result.hits)
            report["queries"].append(body)
            (destination / "search_results.json").write_text(
                json.dumps(report["queries"], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(
                f"[search] {len(result.hits)} hits | {result.parser} | {result.total_ms}ms",
                flush=True,
            )
        report["smoke_passed"] = all(
            q["returned_hits"] and q["expected_entities_found"] is not False
            for q in report["queries"]
        )
        report["evaluation_scope"] = (
            "entity-label smoke checks; not an independent relevance goldset"
        )
        # Real image ids derived from CSV entity labels; explicitly a smoke set, not human gold.
        (destination / "entity_smoke.jsonl").write_text(
            "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n",
            encoding="utf-8",
        )
        report["eval_cases_written"] = len(cases)
        stage_seconds["smoke"] = time.perf_counter() - t
    report["stage_seconds"] = {k: round(v, 3) for k, v in stage_seconds.items()}
    report["total_seconds"] = round(time.perf_counter() - started, 3)
    usage = data_dir() / "deepseek_usage.jsonl"
    if usage.exists():
        events = [
            json.loads(line) for line in usage.read_text(encoding="utf-8").splitlines() if line
        ]
        report["deepseek_usage_cumulative"] = {
            "requests": len(events),
            "prompt_tokens": sum(e["usage"].get("prompt_tokens", 0) for e in events),
            "completion_tokens": sum(e["usage"].get("completion_tokens", 0) for e in events),
        }
    (destination / "pipeline_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if smoke and not report["smoke_passed"]:
        raise RuntimeError(
            "Pipeline completed indexing but smoke checks failed; inspect pipeline_report.json"
        )
    print("[pipeline] complete:", destination / "pipeline_report.json", flush=True)
    return report
