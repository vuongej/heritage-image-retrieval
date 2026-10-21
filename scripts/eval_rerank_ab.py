"""E1: A/B reranker trên POOL ỨNG VIÊN ĐÓNG BĂNG — chỉ đổi đúng một biến là reranker.

1) Đóng băng: chạy 244 ca (cùng ca với scripts.eval_quality) bằng rule parse, chụp pool 24 ứng
   viên trước rerank -> reports/v2/frozen_pools.json (dùng lại nếu đã có).
2) Chấm mỗi pool bằng từng backend, đo thời gian riêng lời gọi rerank, top-10 theo điểm
   (hoà điểm giữ thứ tự fusion), tính metric silver (nhãn tự sinh từ catalog, KHÔNG phải gold).

python -X utf8 -m scripts.eval_rerank_ab [--backends fusion,jina,bge,qwen06,gemini] [--refreeze]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

from evals.harness import mrr, ndcg_at_k
from retrieval import local_search, speculative
from retrieval import rerank as reranking
from retrieval.search import search
from scripts.eval_rerank_verify import build_cases

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "v2"
FIELDS = (
    "image_id", "entity_id", "entity_name", "parent_class", "description", "metadata_text",
    "verify", "width", "height", "has_watermark",
)  # fmt: skip
BACKENDS = {
    "fusion": ("none", None),
    "jina": ("api", None),
    "bge": ("local_ce", "BAAI/bge-reranker-v2-m3"),
    "qwen06": ("local_ce", "Qwen/Qwen3-Reranker-0.6B"),
    "gemini": ("llm", None),
}


def pct(values, q):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 1) if values else None


def freeze() -> list[dict]:
    path = OUT / "frozen_pools.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    original_get = local_search.cache_get
    local_search.cache_get = lambda key: None if key.startswith("search:") else original_get(key)
    speculative.start = lambda query, catalog: None
    captured: dict = {}
    original = reranking.rerank

    def capture(query, candidates, keep=10, use_llm=None, mode=None):
        captured["pool"] = [{k: c.get(k) for k in FIELDS} for c in candidates]
        return [
            reranking.RerankHit(c["image_id"], 1 - i / len(candidates), "fusion_order")
            for i, c in enumerate(candidates)
        ]

    reranking.rerank = capture
    records = []
    for case in build_cases():
        captured.clear()
        result = search(case["query"], top_k=10)
        records.append({**case, "intent": result.intent_type, "pool": captured.get("pool", [])})
    reranking.rerank = original
    OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return records


def metrics(case: dict, top: list[dict]) -> dict:
    ids = [c["image_id"] for c in top]
    ents = [c["entity_id"] for c in top]
    if case["kind"] == "entity":
        rel = set(case["relevant"])
        hits = len(set(ids) & rel)
        return {
            "precision@10": hits / len(ids) if ids else 0.0,
            "recall@10": hits / len(rel),  # recall thật: |đúng ∩ top10| / |đúng|
            "recall@10_capped": hits / min(10, len(rel)),  # công thức V1 (chia min(10,|R|))
            "ndcg@10": ndcg_at_k(ids, rel),
            "mrr": mrr(ids, rel),
            "hit@10": float(hits > 0),
        }
    if case["kind"] == "regression":
        return {
            "in_top10": float(case["entity"] in ents),
            "top1": float(ents[:1] == [case["entity"]]),
        }
    if case["kind"] == "set":
        from pipeline.local_run import short_class

        ok = [short_class(c.get("parent_class") or "") == case["group"] for c in top]
        return {
            "group_precision@10": sum(ok) / len(ok) if ok else 0.0,
            "distinct_entity@10": len(set(ents)),
        }
    a, b = case["pair"]
    return {
        "both_covered": float(a in ents and b in ents),
        "precision_A_or_B@10": sum(e in {a, b} for e in ents) / len(ents) if ents else 0.0,
    }


def run_backend(name: str, records: list[dict]) -> dict:
    mode, model = BACKENDS[name]
    if model:
        os.environ["RERANK_LOCAL_MODEL"] = model
        reranking._load_local(model)  # nạp trước, không tính vào độ trễ
    if mode == "api":
        try:  # endpoint giới hạn 100 request/phút/key; nhịp do retrieval.ratelimit giữ
            reranking.dedup_scores(reranking.api_scores, "khởi động", records[0]["pool"][:2])
        except (RuntimeError, ValueError):
            pass
    per_kind: dict = {}
    timings = []
    errors = 0
    for rec in records:
        pool = rec["pool"]
        if not pool:
            continue
        if mode == "none":
            order = list(range(len(pool)))
        else:
            t = time.perf_counter()
            try:
                hits = reranking.rerank(rec["query"], pool, keep=len(pool), mode=mode)
            except (RuntimeError, ValueError):
                errors += 1
                continue
            timings.append((time.perf_counter() - t) * 1000)
            position = {c["image_id"]: i for i, c in enumerate(pool)}
            ranked = sorted(hits, key=lambda h: (-h.score, position[h.image_id]))
            order = [position[h.image_id] for h in ranked]
        top = [pool[i] for i in order[:10]]
        for k, v in metrics(rec, top).items():
            per_kind.setdefault(rec["kind"], {}).setdefault(k, []).append(v)
    return {
        "mode": mode,
        "model": model or reranking.model_name(mode)
        if mode != "none"
        else "fusion order (no rerank)",
        "metrics": {
            kind: {k: round(statistics.fmean(v), 4) for k, v in m.items()}
            for kind, m in per_kind.items()
        },
        "rerank_ms": {
            "p50": pct(timings, 0.5),
            "p95": pct(timings, 0.95),
            "max": pct(timings, 1.0),
        },
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backends", default="fusion,bge,qwen06,gemini,jina")
    parser.add_argument("--refreeze", action="store_true")
    args = parser.parse_args()
    if args.refreeze:
        (OUT / "frozen_pools.json").unlink(missing_ok=True)
    records = freeze()
    entity_cases = [r for r in records if r["kind"] == "entity"]
    in_pool = [
        float(bool({c["image_id"] for c in r["pool"]} & set(r["relevant"]))) for r in entity_cases
    ]
    report = {
        "cases": len(records),
        "pool_size_mean": round(statistics.fmean(len(r["pool"]) for r in records), 1),
        "candidate_entity_recall@pool": round(statistics.fmean(in_pool), 4),
        "label_type": "silver (catalog entity_id / category) — not human gold",
        "backends": {},
    }
    for name in args.backends.split(","):
        report["backends"][name] = run_backend(name, records)
        print(name, json.dumps(report["backends"][name], ensure_ascii=False), flush=True)
        (OUT / "rerank_ab.json").write_text(  # ghi sau MỖI backend: lỗi giữa chừng không mất số
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
