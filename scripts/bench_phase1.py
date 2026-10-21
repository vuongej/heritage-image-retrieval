"""Nghiệm thu Phase 1 trên index thật: độ trễ, parse-only, 104 ca hồi quy, chất lượng smoke.

Đo "lạnh" có chủ đích: tắt cache /v1/search và cache rerank LLM (Gemini qua OpenRouter) (nếu không, các truy vấn
smoke cũ trúng cache rerank và cho số đẹp giả). Hai lượt:
  pass 1 — LLM parse chưa có trong cache (lần đầu thấy truy vấn);
  pass 2 — LLM parse đã có trong cache (truy vấn lặp lại).

python -X utf8 -m scripts.bench_phase1 [--out reports/phase1] [--skip-regression]
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from evals.harness import hit_at_k, mrr, ndcg_at_k, recall_at_k
from retrieval import llm_router, local_search
from retrieval.search import search

ROOT = Path(__file__).resolve().parents[1]


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 1)


def stats(values: list[float]) -> dict:
    return {
        "n": len(values),
        "p50": pct(values, 0.5),
        "p95": pct(values, 0.95),
        "max": round(max(values), 1) if values else None,
        "mean": round(statistics.fmean(values), 1) if values else None,
    }


def run_query(query: str) -> dict:
    started = time.perf_counter()
    result = search(query, top_k=10)
    wall = (time.perf_counter() - started) * 1000
    return {
        "query": query,
        "intent": result.intent_type,
        "parser": result.parser,
        "hits": [h.image_id for h in result.hits],
        "entities": [h.entity_id for h in result.hits],
        "wall_ms": round(wall, 1),
        "total_ms": result.total_ms,
        "timings": {k: round(v, 2) for k, v in result.timings_ms.items()},
        "warnings": result.warnings,
        "n_hits": len(result.hits),
    }


def summarize(rows: list[dict]) -> dict:
    t = lambda key: [r["timings"][key] for r in rows if key in r["timings"]]  # noqa: E731
    parsers: dict[str, int] = {}
    for r in rows:
        parsers[r["parser"]] = parsers.get(r["parser"], 0) + 1
    return {
        "total_ms": stats([r["total_ms"] for r in rows]),
        "parse_rule_ms": stats(t("parse")),
        "llm_wait_ms": stats(t("llm_wait")),
        "embed_retrieve_ms": stats(
            [r["timings"].get("embed_query", 0) + r["timings"].get("retrieve", 0) for r in rows]
        ),
        "rerank_ms": stats(t("rerank")),
        "parsers": parsers,
        "empty": sum(1 for r in rows if not r["n_hits"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/phase1")
    parser.add_argument("--skip-regression", action="store_true")
    args = parser.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    original_get = local_search.cache_get
    local_search.cache_get = lambda key: None if key.startswith("search:") else original_get(key)
    original_llm_get = llm_router.cache_get
    llm_router.cache_get = lambda key: (
        None if key.startswith("llmrerank:") else original_llm_get(key)
    )

    smoke = [
        json.loads(line)
        for line in (ROOT / "reports/pham_van_vuong/entity_smoke.jsonl").open(encoding="utf-8")
    ]
    smoke_queries = [c["query"] for c in smoke] + [
        q["query"]
        for q in json.loads(
            (ROOT / "reports/pham_van_vuong/search_results.json").read_text(encoding="utf-8")
        )
    ]
    regression = list(
        csv.DictReader((ROOT / "tests/fixtures/misclassified_entities.csv").open(encoding="utf-8"))
    )

    for query in ("Văn Miếu", "Chùa Hương", "bãi biển Nha Trang"):  # warm-up: nạp model, catalog
        search(query, top_k=10)

    report: dict = {"llm_enabled": llm_router.enabled(), "llm_model": llm_router.model()}
    for name in ("pass1_llm_cold", "pass2_llm_cached"):
        rows = [run_query(q) for q in smoke_queries]
        report[name] = {"summary": summarize(rows), "rows": rows}
        print(name, json.dumps(report[name]["summary"], ensure_ascii=False))

    # Chất lượng trên 30 ca entity smoke (so với trước: Recall@10 0,9933 · MRR 1,0).
    rows = {r["query"]: r for r in report["pass2_llm_cached"]["rows"]}
    metrics = [
        {
            "recall@10": recall_at_k(rows[c["query"]]["hits"], set(c["relevant"])),
            "hit@10": hit_at_k(rows[c["query"]]["hits"], set(c["relevant"])),
            "ndcg@10": ndcg_at_k(rows[c["query"]]["hits"], set(c["relevant"])),
            "mrr": mrr(rows[c["query"]]["hits"], set(c["relevant"])),
        }
        for c in smoke
    ]
    report["entity_smoke_quality"] = {
        k: round(statistics.fmean(m[k] for m in metrics), 4) for k in metrics[0]
    }
    print("quality", report["entity_smoke_quality"])

    if not args.skip_regression:
        reg_rows = []
        for case in regression:
            row = run_query(case["entity_name"])
            row["expected_entity"] = case["entity_id"]
            row["entity_in_top10"] = case["entity_id"] in row["entities"]
            reg_rows.append(row)
        report["regression_104"] = {
            "summary": {
                **summarize(reg_rows),
                "intents": {
                    i: sum(r["intent"] == i for r in reg_rows)
                    for i in {r["intent"] for r in reg_rows}
                },
                "entity_in_top10": sum(r["entity_in_top10"] for r in reg_rows),
                "entity_top1": sum(
                    bool(r["entities"]) and r["entities"][0] == r["expected_entity"]
                    for r in reg_rows
                ),
            },
            "rows": reg_rows,
        }
        print("regression_104", json.dumps(report["regression_104"]["summary"], ensure_ascii=False))

    report["llm_router_usage"] = llm_router.usage_summary()
    print("llm_router", json.dumps(report["llm_router_usage"], ensure_ascii=False))
    (out / "bench.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
