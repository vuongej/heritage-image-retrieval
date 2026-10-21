"""Thử "jina rerank -> Gemini verify" trên bộ 244 ca của scripts.eval_quality.

Mỗi truy vấn (parse chỉ bằng rule, cache search tắt): pool ứng viên như production ->
jina chấm cả pool -> Gemini chấm top-N của jina (gọi thật, đo độ trễ). Lưu điểm từng ảnh, rồi
tính offline các chiến lược trên CÙNG dữ liệu:
  jina        top-10 theo jina
  filter      top-N jina, bỏ ảnh Gemini < ngưỡng, giữ thứ tự jina
  reorder     top-N jina, xếp lại theo điểm Gemini
  blend       top-N jina, xếp theo trung bình hạng jina và hạng Gemini
  cond_*      chỉ verify khi intent là set_query / multi_intent

python -X utf8 -m scripts.eval_rerank_verify [--top-n 10] [--out reports/rerank_verify]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import time
from pathlib import Path

from evals.harness import mrr, ndcg_at_k, recall_at_k
from pipeline.local_run import eval_cases, short_class
from retrieval import local_search, speculative
from retrieval import rerank as reranking
from retrieval.search import search
from storage.local import connect

ROOT = Path(__file__).resolve().parents[1]
THRESHOLD = 0.2


def pct(values, q):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))]) if values else None


def build_cases() -> list[dict]:
    """Đúng các ca của scripts.eval_quality (cùng seed)."""
    with connect() as conn:
        entity = eval_cases(conn, 100)
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
    cases = [{"kind": "entity", "query": c["query"], "relevant": c["relevant"]} for c in entity]
    cases += [
        {"kind": "regression", "query": r["entity_name"], "entity": r["entity_id"]}
        for r in regression
    ]
    cases += [
        {"kind": "set", "query": "các " + short_class(c).lower(), "group": short_class(c)}
        for c in set_classes
    ]
    cases += [
        {"kind": "multi", "query": f"{names[a]} và {names[b]}", "pair": [a, b]} for a, b in pairs
    ]
    return cases


def score_case(case: dict, top: list[dict]) -> dict:
    ids = [c["image_id"] for c in top]
    ents = [c["entity_id"] for c in top]
    if case["kind"] == "entity":
        rel = set(case["relevant"])
        return {
            "recall@10": recall_at_k(ids, rel),
            "ndcg@10": ndcg_at_k(ids, rel),
            "mrr": mrr(ids, rel),
        }
    if case["kind"] == "regression":
        return {"in_top10": float(case["entity"] in ents)}
    if case["kind"] == "set":
        ok = [short_class(c.get("parent_class") or "") == case["group"] for c in top]
        return {"precision_group": sum(ok) / len(ok) if ok else 0.0}
    a, b = case["pair"]
    return {
        "both": float(a in ents and b in ents),
        "precision": sum(e in {a, b} for e in ents) / len(ents) if ents else 0.0,
    }


def strategies(rec: dict, top_n: int) -> dict[str, list[dict]]:
    pool, jina, gem = rec["pool"], rec["jina"], rec["gemini"]
    by_jina = sorted(range(len(pool)), key=lambda i: -jina[i])
    head = by_jina[:top_n]
    g = dict(zip(head, gem, strict=True))
    rank_j = {i: r for r, i in enumerate(head)}
    rank_g = {i: r for r, i in enumerate(sorted(head, key=lambda i: -g[i]))}
    out = {
        "jina": [pool[i] for i in by_jina[:10]],
        "filter": [pool[i] for i in head if g[i] >= THRESHOLD][:10],
        "reorder": [pool[i] for i in sorted(head, key=lambda i: -g[i])][:10],
        "blend": [pool[i] for i in sorted(head, key=lambda i: rank_j[i] + rank_g[i])][:10],
    }
    hard = rec["intent"] in {"set_query", "multi_intent"}
    out["cond_filter"] = out["filter"] if hard else out["jina"]
    out["cond_reorder"] = out["reorder"] if hard else out["jina"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--out", default="reports/rerank_verify")
    args = parser.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    original_get = local_search.cache_get
    local_search.cache_get = lambda key: None if key.startswith("search:") else original_get(key)
    speculative.start = lambda query, catalog: None  # chỉ rule parse: cùng pool cho mọi chiến lược

    captured: dict = {}
    original_rerank = reranking.rerank

    def capture(query, candidates, keep=10, use_llm=None, mode=None):
        pool = candidates[: max(reranking.RERANK_TOP_K, keep)]
        t = time.perf_counter()
        jina = reranking.api_scores(query, pool)
        jina_ms = (time.perf_counter() - t) * 1000
        head = sorted(range(len(pool)), key=lambda i: -jina[i])[: args.top_n]
        t = time.perf_counter()
        gem = reranking.llm_scores(query, [pool[i] for i in head])
        gem_ms = (time.perf_counter() - t) * 1000
        captured.update(
            pool=[
                {k: c.get(k) for k in ("image_id", "entity_id", "parent_class", "entity_name")}
                for c in pool
            ],
            jina=jina,
            gemini=gem,
            jina_ms=round(jina_ms),
            gemini_ms=round(gem_ms),
        )
        return original_rerank(query, candidates, keep=keep, mode="api")

    reranking.rerank = capture
    search("Văn Miếu", top_k=10)  # khởi động

    records = []
    for case in build_cases():
        captured.clear()
        t = time.perf_counter()
        result = search(case["query"], top_k=10)
        total = (time.perf_counter() - t) * 1000
        if not captured:
            continue
        records.append(
            {**case, **captured, "intent": result.intent_type, "search_ms": round(total)}
        )
        print(f"[{len(records)}] {case['kind']:10} gemini {captured['gemini_ms']} ms", flush=True)

    names = ["jina", "filter", "reorder", "blend", "cond_filter", "cond_reorder"]
    table: dict = {}
    for name in names:
        per_kind: dict = {}
        for rec in records:
            top = strategies(rec, args.top_n)[name]
            for k, v in score_case(rec, top).items():
                per_kind.setdefault(rec["kind"], {}).setdefault(k, []).append(v)
            per_kind.setdefault(rec["kind"], {}).setdefault("short", []).append(
                float(len(top) < 10)
            )
        table[name] = {
            kind: {k: round(statistics.fmean(v), 4) for k, v in metrics.items()}
            for kind, metrics in per_kind.items()
        }
    gem_ms = [r["gemini_ms"] for r in records]
    jina_ms = [r["jina_ms"] for r in records]
    hard_ms = [r["gemini_ms"] for r in records if r["intent"] in {"set_query", "multi_intent"}]
    summary = {
        "top_n": args.top_n,
        "threshold": THRESHOLD,
        "cases": len(records),
        "strategies": table,
        "latency_ms": {
            "jina_p50": pct(jina_ms, 0.5),
            "jina_p95": pct(jina_ms, 0.95),
            "gemini_verify_p50": pct(gem_ms, 0.5),
            "gemini_verify_p95": pct(gem_ms, 0.95),
            "search_without_verify_p50": pct([r["search_ms"] for r in records], 0.5),
            "hard_share": round(len(hard_ms) / len(records), 3),
        },
    }
    (out / "records.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
