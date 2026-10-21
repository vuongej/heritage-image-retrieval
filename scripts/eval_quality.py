"""Đo chất lượng Phần B trên cấu hình đang chạy (index, embedding, rerank theo .env).

Nhãn sinh tự động từ catalog — không phải goldset người gán:
  entity      100 tên thực thể (rải theo nhóm, seed 42); đúng = ảnh của thực thể đó
  regression  104 tên từng bị parser cũ xếp multi_hop (tests/fixtures)
  set_query   20 truy vấn "các <nhóm>"; đúng = ảnh thuộc nhóm đó (so tên nhóm rút gọn)
  multi       20 truy vấn "<A> và <B>"; đúng = top-10 có ảnh của cả A và B
Truy vấn mô tả / multi-hop KHÔNG có nhãn nên không chấm được ở đây.

Tắt cache /v1/search để đo độ trễ lạnh; cache parse LLM giữ nguyên (như người dùng thật).
python -X utf8 -m scripts.eval_quality [--out reports/quality]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import time
from pathlib import Path

from evals.harness import hit_at_k, mrr, ndcg_at_k, recall_at_k
from pipeline.local_run import eval_cases, short_class
from retrieval import llm_router, local_search
from retrieval.search import search
from storage.local import connect

ROOT = Path(__file__).resolve().parents[1]


def pct(values, q):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))]) if values else None


def run(query: str) -> dict:
    started = time.perf_counter()
    try:
        r = search(query, top_k=10)
    except Exception as exc:  # một ca lỗi không được dừng cả lượt đo
        return {"query": query, "error": f"{type(exc).__name__}: {exc}", "ms": None, "hits": []}
    return {
        "query": query,
        "ms": round((time.perf_counter() - started) * 1000),
        "intent": r.intent_type,
        "parser": r.parser,
        "timings": {k: round(v) for k, v in r.timings_ms.items()},
        "warnings": r.warnings,
        "hits": [
            {
                "image_id": h.image_id,
                "entity_id": h.entity_id,
                "parent_class": h.parent_class,
                "matched": getattr(h, "matched_subqueries", []),
            }
            for h in r.hits
        ],
        "sub_queries": getattr(r, "sub_queries", []),
        "parse_confidence": getattr(r, "parse_confidence", None),
    }


def mean(xs):
    return round(statistics.fmean(xs), 4) if xs else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/quality")
    parser.add_argument(
        "--rule-parse-only",
        action="store_true",
        help="tắt LLM parse (so sánh reranker trên cùng một kết quả parse)",
    )
    args = parser.parse_args()
    if args.rule_parse_only:
        from retrieval import speculative

        speculative.start = lambda query, catalog: None
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    original = local_search.cache_get
    local_search.cache_get = lambda key: None if key.startswith("search:") else original(key)
    usage_before = llm_router.usage_summary()

    with connect() as conn:
        entity_cases = eval_cases(conn, 100)
        classes = [
            r[0]
            for r in conn.execute(
                "SELECT parent_class, count(*) n FROM entities WHERE parent_class<>''"
                " GROUP BY parent_class HAVING n >= 5 ORDER BY parent_class"
            )
        ]
        names = {r[0]: r[1] for r in conn.execute("SELECT entity_id, entity_name FROM entities")}
    rng = random.Random(7)
    set_classes = rng.sample(classes, 20)
    pairs = [rng.sample(sorted(names), 2) for _ in range(20)]
    regression = list(
        csv.DictReader((ROOT / "tests/fixtures/misclassified_entities.csv").open(encoding="utf-8"))
    )

    for q in ("Văn Miếu", "Chùa Hương"):  # khởi động model / kết nối
        search(q, top_k=10)

    results: dict = {"entity": [], "regression": [], "set_query": [], "multi": []}
    for case in entity_cases:
        row = run(case["query"])
        pred = [h["image_id"] for h in row["hits"]]
        rel = set(case["relevant"])
        hits_rel = len(set(pred[:10]) & rel)
        row["metrics"] = {
            "precision@10": hits_rel / len(pred[:10]) if pred else 0.0,
            "recall@10": hits_rel / len(rel),  # recall thật: chia cho TOÀN BỘ ảnh đúng
            "recall@10_capped": recall_at_k(pred, rel),  # công thức V1: chia min(10, |R|)
            "hit@10": hit_at_k(pred, rel),
            "ndcg@10": ndcg_at_k(pred, rel),
            "mrr": mrr(pred, rel),
            "n_relevant": len(rel),
        }
        results["entity"].append(row)
    for case in regression:
        row = run(case["entity_name"])
        ents = [h["entity_id"] for h in row["hits"]]
        row["in_top10"] = case["entity_id"] in ents
        row["top1"] = bool(ents) and ents[0] == case["entity_id"]
        results["regression"].append(row)
    for cls in set_classes:
        label = short_class(cls)
        row = run("các " + label.lower())
        hits = row["hits"]
        row["class"] = cls
        row["precision_exact_class"] = (
            sum(h["parent_class"] == cls for h in hits) / len(hits) if hits else 0.0
        )
        row["precision_same_group"] = (
            sum(short_class(h["parent_class"] or "") == label for h in hits) / len(hits)
            if hits
            else 0.0
        )
        row["distinct_entities"] = len({h["entity_id"] for h in hits})
        results["set_query"].append(row)
    for a, b in pairs:
        row = run(f"{names[a]} và {names[b]}")
        ents = [h["entity_id"] for h in row["hits"]]
        row["has_a"], row["has_b"] = a in ents, b in ents
        row["precision"] = sum(e in {a, b} for e in ents) / len(ents) if ents else 0.0
        results["multi"].append(row)

    all_rows = [r for rows in results.values() for r in rows]
    ok = [r for r in all_rows if r["ms"] is not None]
    stage = lambda k: [r["timings"].get(k, 0) for r in ok]  # noqa: E731
    summary = {
        "label_type": "silver: nhãn tự sinh từ catalog (entity_id / category), KHÔNG phải gold người",
        "config": {
            "pipeline_version": __import__("retrieval.search", fromlist=["x"]).PIPELINE_VERSION,
            "parse_mode": __import__("retrieval.speculative", fromlist=["x"]).mode(),
            "embedding": __import__("retrieval.local_index", fromlist=["x"])
            .manifest()
            .get("model"),
            "rerank": __import__("retrieval.rerank", fromlist=["x"]).model_name(),
            "parse": llm_router.model() if llm_router.enabled() else None,
        },
        "entity": {
            "cases": len(results["entity"]),
            **{
                k: mean([r["metrics"][k] for r in results["entity"] if "metrics" in r])
                for k in (
                    "precision@10",
                    "recall@10",
                    "recall@10_capped",
                    "hit@10",
                    "ndcg@10",
                    "mrr",
                )
            },
            "empty": sum(not r["hits"] for r in results["entity"]),
        },
        "regression_104": {
            "cases": len(results["regression"]),
            "empty": sum(not r["hits"] for r in results["regression"]),
            "in_top10": sum(r.get("in_top10", False) for r in results["regression"]),
            "top1": sum(r.get("top1", False) for r in results["regression"]),
            "intents": {
                i: sum(r.get("intent") == i for r in results["regression"])
                for i in {r.get("intent") for r in results["regression"]}
            },
        },
        "set_query": {
            "cases": len(results["set_query"]),
            "precision_exact_class": mean(
                [r["precision_exact_class"] for r in results["set_query"]]
            ),
            "precision_same_group": mean([r["precision_same_group"] for r in results["set_query"]]),
            "distinct_entities_mean": mean([r["distinct_entities"] for r in results["set_query"]]),
            "intent_set_query": sum(r.get("intent") == "set_query" for r in results["set_query"]),
        },
        "multi_intent": {
            "cases": len(results["multi"]),
            "both_subjects": sum(r["has_a"] and r["has_b"] for r in results["multi"]),
            "precision": mean([r["precision"] for r in results["multi"]]),
            "intent_multi": sum(r.get("intent") == "multi_intent" for r in results["multi"]),
            "all_intents_covered": sum(
                bool(r["sub_queries"])
                and all(s.get("coverage") == "covered" for s in r["sub_queries"])
                for r in results["multi"]
            ),
            "mean_returned": mean([len(r["hits"]) for r in results["multi"]]),
        },
        "parse_confidence": {
            c: sum(r.get("parse_confidence") == c for rows in results.values() for r in rows)
            for c in ("high", "medium", "low")
        },
        "latency_ms": {
            "queries": len(ok),
            "errors": len(all_rows) - len(ok),
            "p50": pct([r["ms"] for r in ok], 0.5),
            "p95": pct([r["ms"] for r in ok], 0.95),
            "max": max(r["ms"] for r in ok) if ok else None,
            "under_1500ms": round(sum(r["ms"] < 1500 for r in ok) / len(ok), 3) if ok else None,
            "stage_p50": {
                k: pct(stage(k), 0.5)
                for k in ("embed_query", "dense", "retrieve", "llm_wait", "rerank")
            },
            "stage_p95": {
                k: pct(stage(k), 0.95)
                for k in ("embed_query", "dense", "retrieve", "llm_wait", "rerank")
            },
        },
        "warnings": sorted({w.split(":")[0] for r in ok for w in r["warnings"]}),
        "short_answers": sum(0 < len(r["hits"]) < 10 for r in ok),
        "llm_usage_before": usage_before,
        "llm_usage_after": llm_router.usage_summary(),
    }
    (out / "eval.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
