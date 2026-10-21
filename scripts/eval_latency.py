"""Đo độ trễ end-to-end đúng §10.2 của RETRIEVAL_PIPELINE_V2_DATA_DRIVEN_PLAN.

- "warm uncached": model/kết nối đã khởi động, nhưng TẮT cache search + cache parse LLM +
  cache rerank LLM (mọi truy vấn trả giá như lần đầu). Không trộn với cache hit.
- Thứ tự truy vấn xáo ngẫu nhiên (seed), cùng bộ 244 ca của scripts.eval_quality.
- Concurrency 1 và 4 (thread, gọi in-process như API làm).
- Báo p50/p95/p99/max, %<1500 ms, %<3000 ms, lỗi, cảnh báo 429/timeout, theo từng loại truy vấn.
Percentile tổng tính từ từng request, KHÔNG cộng percentile các bước.

python -X utf8 -m scripts.eval_latency [--concurrency 1,4] [--out reports/v2/latency.json]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from retrieval import llm_router, local_search
from retrieval import rerank as reranking
from retrieval.local_index import manifest
from retrieval.search import PIPELINE_VERSION, search
from scripts.eval_rerank_verify import build_cases
from storage import local as storage_local

ROOT = Path(__file__).resolve().parents[1]


def pct(values, q):
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))]) if values else None


def disable_caches() -> None:
    original = storage_local.cache_get

    def no_cache(key):
        if key.startswith(("search:", "llmparse:", "llmrerank:")):
            return None
        return original(key)

    local_search.cache_get = no_cache
    storage_local.cache_get = no_cache
    llm_router.cache_get = no_cache


_pace_lock = __import__("threading").Lock()
_next_start = [0.0]
OFFERED_RPM = [0.0]


def _pace() -> None:
    """Giữ tải gửi vào <= OFFERED_RPM truy vấn/phút (chung mọi worker). 0 = gửi dồn."""
    if OFFERED_RPM[0] <= 0:
        return
    with _pace_lock:
        now = time.monotonic()
        start = max(now, _next_start[0])
        _next_start[0] = start + 60.0 / OFFERED_RPM[0]
    time.sleep(max(0.0, start - now))


def one(case: dict) -> dict:
    _pace()  # thời gian chờ nhịp KHÔNG tính vào độ trễ request
    started = time.perf_counter()
    try:
        result = search(case["query"], top_k=10)
    except Exception as exc:  # đếm lỗi, không dừng lượt đo
        return {"kind": case["kind"], "ms": None, "error": type(exc).__name__}
    return {
        "kind": case["kind"],
        "ms": (time.perf_counter() - started) * 1000,
        "parser": result.parser,
        "warnings": result.warnings,
        "timings": result.timings_ms,
        "n": len(result.hits),
    }


def summarize(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["ms"] is not None]
    ms = [r["ms"] for r in ok]
    warn = [w for r in ok for w in r["warnings"]]
    out = {
        "requests": len(rows),
        "errors": len(rows) - len(ok),
        "p50": pct(ms, 0.5),
        "p95": pct(ms, 0.95),
        "p99": pct(ms, 0.99),
        "max": round(max(ms)) if ms else None,
        "under_1500ms": round(sum(m < 1500 for m in ms) / len(ms), 4) if ms else None,
        "under_3000ms": round(sum(m < 3000 for m in ms) / len(ms), 4) if ms else None,
        "warnings_429": sum("429" in w for w in warn),
        "warnings_degraded": sum(w.startswith(("rerank_", "embedding_", "llm_")) for w in warn),
        "parsers": {
            p: sum(r.get("parser") == p for r in ok) for p in {r.get("parser") for r in ok}
        },
        "stage_p50": {},
        "stage_p95": {},
    }
    for stage in ("parse", "embed_query", "dense", "retrieve", "llm_wait", "rerank"):
        values = [r["timings"].get(stage, 0) for r in ok]
        out["stage_p50"][stage] = pct(values, 0.5)
        out["stage_p95"][stage] = pct(values, 0.95)
    out["by_kind"] = {
        kind: {
            "p50": pct([r["ms"] for r in ok if r["kind"] == kind], 0.5),
            "p95": pct([r["ms"] for r in ok if r["kind"] == kind], 0.95),
        }
        for kind in sorted({r["kind"] for r in ok})
    }
    return out


def environment() -> dict:
    env = {
        "python": platform.python_version(),
        "machine": platform.platform(),
        "pipeline_version": PIPELINE_VERSION,
        "index_model": manifest().get("model"),
        "index_count": manifest().get("indexed_count"),
        "rerank": [reranking.backend(), reranking.model_name()],
        "parse_mode": os.getenv("LLM_PARSE_MODE", "ambiguous_only"),
        "parse_llm": llm_router.model() if llm_router.enabled() else None,
        "vector_backend": os.getenv("VECTOR_BACKEND", "numpy"),
    }
    try:
        import torch

        env["gpu"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except ImportError:
        env["gpu"] = None
    return env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", default="1,4")
    parser.add_argument("--out", default="reports/v2/latency.json")
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument(
        "--offered-rpm",
        type=float,
        default=85,
        help="tải gửi vào (truy vấn/phút); endpoint embedding giới hạn 100 request/phút/key",
    )
    args = parser.parse_args()
    OFFERED_RPM[0] = args.offered_rpm
    disable_caches()
    cases = build_cases()
    for q in ("Văn Miếu", "chùa cổ", "Chùa Hương và Bích Động"):  # khởi động model + kết nối
        search(q, top_k=10)
    report = {
        "environment": environment(),
        "cache_state": "warm_uncached",
        "offered_rpm": args.offered_rpm,
        "endpoint_rate_limit": "100 requests/min/key (LiteLLM), client limiter EMBED_API_RPM",
        "runs": {},
    }
    for level in [int(x) for x in args.concurrency.split(",")]:
        order = cases[:]
        random.Random(args.seed + level).shuffle(order)
        started = time.perf_counter()
        with ThreadPoolExecutor(level) as pool:
            rows = list(pool.map(one, order))
        summary = summarize(rows)
        summary["wall_seconds"] = round(time.perf_counter() - started, 1)
        summary["throughput_qps"] = round(len(rows) / summary["wall_seconds"], 2)
        report["runs"][f"concurrency_{level}"] = summary
        print(f"concurrency {level}:", json.dumps(summary, ensure_ascii=False), flush=True)
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
