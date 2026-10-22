"""Chấm Phần B trên bộ test case evals/testcases/cases.jsonl (scripts.build_testcases).

Mỗi ca chạy đúng đường /v1/search (in-process, cấu hình .env) với cache kết quả tìm kiếm TẮT, nên
latency là độ trễ lạnh; cache parse LLM giữ nguyên như khi người dùng thật hỏi lại. Ảnh "đúng" =
ảnh thuộc entity có tên khớp regex của ca (hoặc relevant_entity_ids).

  Hit@10       có ít nhất 1 ảnh đúng trong top 10
  Precision    ảnh đúng / số ảnh trả về (0 khi trả 0 ảnh mà lẽ ra phải có)
  nDCG@10      nhị phân, lý tưởng = min(10, số ảnh đúng trong catalog)
  MRR          1 / hạng của ảnh đúng đầu tiên
  Coverage     multi_intent: tỉ lệ ý có >= 1 ảnh đúng trong top 10; all_covered = mọi ý đều có
  Abstain      multi_hop kỳ vọng từ chối + out_of_catalog: đúng khi trả 0 ảnh

Endpoint embedding/rerank giới hạn 100 request/phút/key (chung), mỗi truy vấn tốn 1 + số ý request:
  --pace 2.5   giãn cách giữa các câu -> đo trong hạn mức (chất lượng + latency đại diện)
  --pace 0     dồn liên tục -> vượt hạn mức, thấy tỉ lệ ca bị suy giảm (dense / rerank bị bỏ)

python -X utf8 -m scripts.eval_testcases [--pace 2.5] [--out reports/testcases]
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import re
import statistics
import time
from collections import defaultdict
from pathlib import Path

from retrieval import local_search
from retrieval.search import PIPELINE_VERSION, search
from scripts.build_testcases import entities, plain

CASES = Path("evals/testcases/cases.jsonl")
TYPES = ["single_entity", "single", "multi_intent", "multi_hop", "out_of_catalog"]


def pct(values: list[float], q: float) -> float | None:
    v = sorted(values)
    return round(v[min(len(v) - 1, int(q * len(v)))]) if v else None


def relevant_ids(ents, patterns: list[str]) -> set[str]:
    rx = [re.compile(p) for p in patterns]
    return {eid for eid, name, _, _ in ents if any(r.search(plain(name)) for r in rx)}


def score(case: dict, hits: list, ents, images_of: dict) -> dict:
    ids = [h.entity_id for h in hits[:10]]
    out: dict = {"returned": len(hits)}
    if case["type"] == "multi_intent":
        subs = [relevant_ids(ents, p) for p in case["sub"]]
        rel = set().union(*subs)
        covered = [any(e in s for e in ids) for s in subs]
        out.update(coverage=sum(covered) / len(subs), all_covered=all(covered))
    elif case.get("relevant_entity_ids"):
        rel = set(case["relevant_entity_ids"])
    else:
        rel = relevant_ids(ents, case.get("relevant", []))
    if not rel:  # kỳ vọng từ chối
        out.update(abstain=len(hits) == 0, false_positives=len(hits))
        return out
    good = [e in rel for e in ids]
    ideal = min(10, sum(images_of[e] for e in rel))
    dcg = sum(1 / math.log2(i + 2) for i, g in enumerate(good) if g)
    idcg = sum(1 / math.log2(i + 2) for i in range(ideal))
    out.update(
        hit10=any(good),
        precision=round(sum(good) / len(good), 4) if good else 0.0,
        ndcg10=round(dcg / idcg, 4) if idcg else 0.0,
        mrr=round(next((1 / (i + 1) for i, g in enumerate(good) if g), 0.0), 4),
        relevant_entities=len(rel),
    )
    return out


def run_case(case: dict, ents, images_of, names) -> dict:
    t = time.perf_counter()
    try:
        r = search(case["query"], top_k=10)
    except Exception as exc:  # một ca lỗi không dừng lượt đo
        return {**case, "error": f"{type(exc).__name__}: {exc}", "ms": None}
    ms = (time.perf_counter() - t) * 1000
    res = {
        **{k: case[k] for k in ("id", "type", "query", "source")},
        "ms": round(ms),
        "intent": r.intent_type,
        "parser": r.parser,
        "resolution": (r.resolution or {}).get("status"),
        "warnings": r.warnings,
        "timings": {k: round(v) for k, v in r.timings_ms.items()},
        "top": [names.get(h.entity_id, h.entity_id) for h in r.hits[:10]],
        "degraded": any(w.startswith(("embedding_", "rerank_")) for w in r.warnings),
        **score(case, r.hits, ents, images_of),
    }
    if case.get("expect") == "resolved":
        res["status_ok"] = res["resolution"] == "resolved"
    return res


def summarize(results: list[dict]) -> dict:
    by = defaultdict(list)
    for r in results:
        by[r["type"]].append(r)
    out = {}
    for t in TYPES:
        rs = [r for r in by[t] if "error" not in r]
        if not rs:
            continue
        lat = [r["ms"] for r in rs]
        s = {"cases": len(by[t]), "errors": len(by[t]) - len(rs),
             "degraded": round(sum(r["degraded"] for r in rs) / len(rs), 4),
             "latency_ms": {"p50": pct(lat, 0.5), "p95": pct(lat, 0.95), "max": max(lat),
                            "under_3000": round(sum(x < 3000 for x in lat) / len(lat), 4)}}
        scored = [r for r in rs if "hit10" in r]
        if scored:
            for m in ("hit10", "precision", "ndcg10", "mrr"):
                s[m] = round(statistics.mean(float(r[m]) for r in scored), 4)
            s["scored_cases"] = len(scored)
        if t == "multi_intent":
            s["coverage"] = round(statistics.mean(r["coverage"] for r in rs), 4)
            s["all_covered"] = round(statistics.mean(float(r["all_covered"]) for r in rs), 4)
            s["parsed_multi"] = round(statistics.mean(float(r["intent"] == "multi_intent") for r in rs), 4)
        if t == "multi_hop":
            s["parsed_multi_hop"] = round(statistics.mean(float(r["intent"] == "multi_hop") for r in rs), 4)
            st = [r for r in rs if "status_ok" in r]
            if st:
                s["resolved_ok"] = round(statistics.mean(float(r["status_ok"]) for r in st), 4)
        abst = [r for r in rs if "abstain" in r]
        if abst:
            s["abstain_cases"] = len(abst)
            s["abstain_ok"] = round(statistics.mean(float(r["abstain"]) for r in abst), 4)
            s["false_positives_mean"] = round(statistics.mean(r["false_positives"] for r in abst), 2)
        out[t] = s
    all_lat = [r["ms"] for r in results if r.get("ms") is not None]
    out["all"] = {"cases": len(results), "latency_ms": {"p50": pct(all_lat, 0.5), "p95": pct(all_lat, 0.95),
                                                        "max": max(all_lat)},
                  "under_3000": round(sum(x < 3000 for x in all_lat) / len(all_lat), 4)}
    return out


def render(report: dict, results: list[dict]) -> str:
    s = report["summary"]
    L = [
        "# Benchmark Phần B trên bộ test case",
        "",
        f"{report['cases']} ca · pipeline `{report['pipeline_version']}` · {report['environment']['when']} · "
        f"cache tìm kiếm tắt (latency lạnh) · giãn cách {report['pace_s']:g} s/câu · "
        f"{report['environment']['config']}",
        "",
        "| Loại | Ca | Hit@10 | Precision | nDCG@10 | MRR | Coverage / đúng loại | Từ chối đúng | p50 ms | p95 ms | < 3 s | Suy giảm |",
        "|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    f = lambda v: "—" if v is None else f"{v * 100:.1f}%"  # noqa: E731
    for t in TYPES:
        if t not in s:
            continue
        x = s[t]
        extra = (f"coverage {f(x.get('coverage'))}, đủ mọi ý {f(x.get('all_covered'))}" if t == "multi_intent"
                 else f"nhận multi_hop {f(x.get('parsed_multi_hop'))}, resolved {f(x.get('resolved_ok'))}"
                 if t == "multi_hop" else "—")
        L.append(f"| {t} | {x['cases']} | {f(x.get('hit10'))} | {f(x.get('precision'))} | {f(x.get('ndcg10'))} | "
                 f"{f(x.get('mrr'))} | {extra} | "
                 f"{f(x.get('abstain_ok')) if 'abstain_ok' in x else '—'} | {x['latency_ms']['p50']:,} | "
                 f"{x['latency_ms']['p95']:,} | {f(x['latency_ms']['under_3000'])} | {f(x['degraded'])} |")
    a = s["all"]
    L += ["", f"Toàn bộ: p50 {a['latency_ms']['p50']:,} ms · p95 {a['latency_ms']['p95']:,} ms · "
              f"max {a['latency_ms']['max']:,} ms · {f(a['under_3000'])} ca dưới 3 s.", "",
          "## Từng ca", "",
          "| ID | Truy vấn | Parse | Kết quả | ms | Top 3 entity |", "|---|---|---|---|---:|---|"]
    for r in results:
        if "error" in r:
            L.append(f"| {r['id']} | {r['query']} | — | LỖI {r['error'][:60]} | — | — |")
            continue
        if "hit10" in r:
            verdict = ("đủ ý" if r.get("all_covered") else f"phủ {r['coverage']:.0%}") if "coverage" in r \
                else ("Hit" if r["hit10"] else "Trượt")
            verdict += f" · P {r['precision']:.0%}"
        else:
            verdict = "từ chối đúng" if r["abstain"] else f"trả {r['false_positives']} ảnh sai"
        if r.get("resolution"):
            verdict += f" · {r['resolution']}"
        top = "; ".join(dict.fromkeys(r["top"]))[:120]
        L.append(f"| {r['id']} | {r['query']} | {r['intent']} | {verdict} | {r['ms']:,} | {top} |")
    return "\n".join(L) + "\n"


def main() -> None:
    import os

    ap = argparse.ArgumentParser(prog="python -m scripts.eval_testcases")
    ap.add_argument("--cases", default=str(CASES))
    ap.add_argument("--out", default="reports/testcases")
    ap.add_argument("--pace", type=float, default=2.5, help="giây tối thiểu giữa hai câu (0 = dồn)")
    args = ap.parse_args()
    cases = [json.loads(x) for x in Path(args.cases).read_text("utf-8").splitlines() if x]
    ents = entities()
    images_of = {eid: n for eid, _, _, n in ents}
    names = {eid: name for eid, name, _, _ in ents}
    original = local_search.cache_get
    local_search.cache_get = lambda key: None if key.startswith("search:") else original(key)
    search("Văn Miếu", top_k=10)  # làm nóng catalog / kết nối, không tính vào kết quả
    results = []
    for c in cases:
        started = time.perf_counter()
        results.append(run_case(c, ents, images_of, names))
        r = results[-1]
        print(f"{r['id']:5} {r.get('ms') or 0:6} ms  {r.get('intent', '-'):13} {r['query'][:50]}", flush=True)
        time.sleep(max(0.0, args.pace - (time.perf_counter() - started)))
    report = {
        "cases": len(cases),
        "pipeline_version": PIPELINE_VERSION,
        "pace_s": args.pace,
        "environment": {
            "when": time.strftime("%Y-%m-%d %H:%M"),
            "machine": platform.platform(),
            "config": ", ".join(f"{k}={os.getenv(k, '-')}" for k in (
                "VECTOR_BACKEND", "RERANK_BACKEND", "EMBED_MODEL", "LLM_PARSE_MODE")),
        },
        "summary": summarize(results),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    with (out / "results.jsonl").open("w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in results)
    (out / "report.md").write_text(render(report, results), "utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
