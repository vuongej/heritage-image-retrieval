"""Đo chất lượng retrieval: Recall@10, Hit@10, nDCG@10, MRR.

Chạy tách theo intent_type VÀ theo LLM_PROVIDER (none | local | gemini).

python -m evals.harness --goldset evals/goldset
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

INTENTS = ["single_intent", "multi_intent", "multi_hop", "set_query"]


def recall_at_k(pred: list[str], rel: set[str], k: int = 10) -> float:
    if not rel:
        return 0.0
    return len(set(pred[:k]) & rel) / min(k, len(rel))


def hit_at_k(pred: list[str], rel: set[str], k: int = 10) -> int:
    """'10 ảnh, 1 ảnh trùng với trust' -> 1 nếu có ít nhất 1 ảnh đúng."""
    return int(len(set(pred[:k]) & rel) >= 1)


def dcg(pred: list[str], rel: set[str], k: int = 10) -> float:
    s = 0.0
    for i, d in enumerate(pred[:k]):
        if d in rel:
            s += 1.0 / math.log2(i + 2)
    return s


def ndcg_at_k(pred: list[str], rel: set[str], k: int = 10) -> float:
    ideal = dcg(sorted(rel)[:k], rel, k)
    return dcg(pred, rel, k) / ideal if ideal else 0.0


def mrr(pred: list[str], rel: set[str]) -> float:
    for i, d in enumerate(pred):
        if d in rel:
            return 1.0 / (i + 1)
    return 0.0


def precision_quality(pred: list[str], quality: dict[str, dict], k: int = 10) -> float:
    ok = sum(1 for d in pred[:k] if quality.get(d, {}).get("passes_quality"))
    return ok / max(1, min(k, len(pred)))


def evaluate_case(pred: list[str], rel: set[str], quality: dict, k: int = 10) -> dict:
    return {
        "recall@10": recall_at_k(pred, rel, k),
        "hit@10": hit_at_k(pred, rel, k),
        "ndcg@10": ndcg_at_k(pred, rel, k),
        "mrr": mrr(pred, rel),
        "precision@10_quality": precision_quality(pred, quality, k),
    }


def aggregate(rows: list[dict]) -> dict:
    if not rows:
        return {}
    keys = rows[0].keys()
    return {k: sum(r[k] for r in rows) / len(rows) for k in keys}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goldset", default="evals/goldset")
    ap.add_argument("--out", default="evals/runs/latest/report.json")
    args = ap.parse_args()

    gold = Path(args.goldset)
    if not gold.exists():
        raise SystemExit(f"Không thấy goldset: {gold}")

    from retrieval.search import search

    files = sorted(gold.glob("*.jsonl")) if gold.is_dir() else [gold]
    cases = [
        json.loads(line)
        for path in files
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not cases or any(
        not c.get("relevant") or any(str(i).startswith("<") for i in c["relevant"]) for c in cases
    ):
        raise SystemExit("Goldset is empty or contains missing/placeholder relevance labels")
    quality_path = gold / "quality.json" if gold.is_dir() else gold.with_name("quality.json")
    quality = json.loads(quality_path.read_text(encoding="utf-8")) if quality_path.exists() else {}
    per_intent = {}
    results = []
    for case in cases:
        response = search(case["query"], top_k=10)
        metrics = evaluate_case([h.image_id for h in response.hits], set(case["relevant"]), quality)
        intent = case.get("intent_type", response.intent_type)
        per_intent.setdefault(intent, []).append(metrics)
        results.append(
            {
                "query": case["query"],
                "intent_type": intent,
                "metrics": metrics,
                "total_ms": response.total_ms,
                "parser": response.parser,
            }
        )
    thresholds = {"recall@10": 0.70, "hit@10": 0.95, "ndcg@10": 0.75, "mrr": 0.80}
    summary = aggregate([r["metrics"] for r in results])
    report = {
        "thresholds": thresholds,
        "per_intent": {i: aggregate(rows) for i, rows in per_intent.items()},
        "aggregate": summary,
        "cases": results,
        "case_count": len(results),
        "quality_labels_available": bool(quality),
        "passed": all(summary[k] >= v for k, v in thresholds.items()),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[eval] ghi {out}")
    if not report["passed"]:
        raise SystemExit("Retrieval evaluation did not meet configured thresholds; inspect report")


if __name__ == "__main__":
    main()
