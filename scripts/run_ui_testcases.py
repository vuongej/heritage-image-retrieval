"""Run evals/ui_testcases.json against the API (18 case kiểm thử API, trước nằm ở web/local).

python -m scripts.run_ui_testcases                         # in-process (TestClient)
python -m scripts.run_ui_testcases --base http://127.0.0.1:8000   # against a running server
python -m scripts.run_ui_testcases --only TC03 TC04
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from storage.local import plain

CASES = Path(__file__).resolve().parents[1] / "evals" / "ui_testcases.json"


def _ratio(hits: list[dict], predicate) -> float:
    return sum(1 for h in hits if predicate(h)) / len(hits) if hits else 0.0


def _get(body, dotted: str):
    for part in dotted.split("."):
        body = body[int(part)] if isinstance(body, list) else body.get(part)
    return body


def evaluate(checks: dict, status: int, body, elapsed_ms: int) -> list[tuple[str, bool, str]]:
    """Return (check, passed, observed) for every check. Mirrors checkCase() in index.html."""
    out = []
    expected_status = checks.get("status", 200)
    out.append(("status", status == expected_status, f"{status} (cần {expected_status})"))
    if status != 200 or not isinstance(body, dict):
        return out
    hits = body.get("hits") or []
    labels = [h.get("leaf_label") or "" for h in hits]
    warnings = body.get("warnings") or []
    if "min_hits" in checks:
        out.append(("min_hits", len(hits) >= checks["min_hits"], f"{len(hits)} ảnh"))
    if "max_hits" in checks:
        out.append(("max_hits", len(hits) <= checks["max_hits"], f"{len(hits)} ảnh"))
    if "top1_entity" in checks:
        got = labels[0] if labels else None
        out.append(("top1_entity", got == checks["top1_entity"], str(got)))
    if "top1_entity_contains" in checks:
        got = labels[0] if labels else ""
        ok = plain(checks["top1_entity_contains"]) in plain(got)
        out.append(("top1_entity_contains", ok, got))
    for spec in (
        checks["label_contains"]
        if isinstance(checks.get("label_contains"), list)
        else [checks["label_contains"]]
        if "label_contains" in checks
        else []
    ):
        text = plain(spec["text"])
        r = _ratio(hits, lambda h, t=text: t in plain(h.get("leaf_label") or ""))
        out.append(
            (
                f"label ∋ '{spec['text']}'",
                r >= spec["min_ratio"],
                f"{r:.0%} (cần ≥ {spec['min_ratio']:.0%})",
            )
        )
    if "class_prefix" in checks:
        spec = checks["class_prefix"]
        r = _ratio(hits, lambda h: (h.get("parent_class") or "").startswith(spec["text"]))
        out.append(
            (
                f"class '{spec['text']}'",
                r >= spec["min_ratio"],
                f"{r:.0%} (cần ≥ {spec['min_ratio']:.0%})",
            )
        )
    if "entities_include" in checks:
        missing = [e for e in checks["entities_include"] if e not in labels]
        out.append(
            ("entities_include", not missing, "thiếu " + ", ".join(missing) if missing else "đủ")
        )
    if "min_distinct_entities" in checks:
        n = len({h.get("entity_id") for h in hits})
        out.append(("min_distinct_entities", n >= checks["min_distinct_entities"], f"{n} thực thể"))
    if "intent" in checks:
        out.append(
            ("intent", body.get("intent_type") == checks["intent"], str(body.get("intent_type")))
        )
    if "warning_contains" in checks:
        ok = any(checks["warning_contains"].lower() in w.lower() for w in warnings)
        out.append(("warning_contains", ok, "; ".join(warnings) or "không có cảnh báo"))
    if "no_warning_contains" in checks:
        ok = not any(checks["no_warning_contains"].lower() in w.lower() for w in warnings)
        out.append(("no_warning_contains", ok, "; ".join(warnings) or "không có cảnh báo"))
    if "max_total_ms" in checks:
        total = body.get("total_ms", elapsed_ms)
        out.append(("max_total_ms", total <= checks["max_total_ms"], f"{total} ms"))
    if "timing_key" in checks:
        keys = list((body.get("timings_ms") or {}).keys())
        out.append(("timing_key", checks["timing_key"] in keys, ", ".join(keys)))
    for key, minimum in (checks.get("body_min") or {}).items():
        got = _get(body, key)
        out.append((f"{key} ≥ {minimum}", got is not None and got >= minimum, str(got)))
    for key, expected in (checks.get("body_equals") or {}).items():
        try:
            got = _get(body, key)
        except (KeyError, IndexError, TypeError, AttributeError):
            got = None
        out.append((f"{key} = {expected}", got == expected, str(got)))
    return out


def request_for(case: dict) -> tuple[str, str, dict | None, bool]:
    if case["group"] == "search":
        body = {"query": case["query"], "top_k": case.get("top_k", 10)}
        return "POST", "/v1/search", body, True
    req = case["request"]
    return req["method"], req["path"], req.get("body"), req.get("auth", True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="URL of a running server; default runs in-process")
    ap.add_argument("--only", nargs="*", help="Case ids to run")
    ap.add_argument("--out", default="reports/pham_van_vuong/ui_testcases.json")
    args = ap.parse_args()
    from storage.runtime import load_env

    load_env()
    key = os.environ.get("TEST_API_KEY", "gsk_test_dev_only")
    if args.base:
        import httpx

        client = httpx.Client(base_url=args.base, timeout=120)
    else:
        from fastapi.testclient import TestClient

        from api.main import app

        client = TestClient(app)
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] in set(args.only)]
    report, failed = [], 0
    for case in cases:
        method, path, payload, auth = request_for(case)
        headers = {"X-API-Key": key} if auth else {}
        for _ in range(2 if case.get("run_twice") else 1):
            t = time.perf_counter()
            response = client.request(method, path, json=payload, headers=headers)
            elapsed = int((time.perf_counter() - t) * 1000)
        try:
            body = response.json()
        except ValueError:
            body = None
        results = evaluate(case["checks"], response.status_code, body, elapsed)
        passed = all(ok for _, ok, _ in results)
        failed += not passed
        print(f"{'PASS' if passed else 'FAIL'}  {case['id']}  {case['title']}  ({elapsed} ms)")
        for name, ok, observed in results:
            print(f"        {'✓' if ok else '✗'} {name}: {observed}")
        report.append(
            {
                "id": case["id"],
                "title": case["title"],
                "passed": passed,
                "elapsed_ms": elapsed,
                "checks": [{"check": n, "passed": ok, "observed": o} for n, ok, o in results],
                "top_labels": [h.get("leaf_label") for h in (body or {}).get("hits", [])][:10]
                if isinstance(body, dict)
                else None,
            }
        )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(cases) - failed}/{len(cases)} pass · ghi {out}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
