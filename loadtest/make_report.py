"""Sinh báo cáo HTML/JSON từ kết quả k6 — reproducible.

python -m loadtest.make_report /reports/raw.json -o /reports/report.html
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TYPES = ["single", "multi_intent", "multi_hop", "set_query", "embed", "rerank"]


def extract(raw: dict) -> dict:
    m = raw.get("metrics", {})
    out = {"thresholds": raw.get("root_group", {}).get("checks", {}), "by_type": {}}
    for t in TYPES:
        d = m.get(f"http_req_duration{{type:{t}}}", {})
        if not d:
            continue
        out["by_type"][t] = {
            "p50": d.get("p(50)"), "p95": d.get("p(95)"), "p99": d.get("p(99)"),
            "avg": d.get("avg"), "max": d.get("max"),
        }
    out["throughput_rps"] = m.get("http_reqs", {}).get("rate")
    out["error_rate"] = m.get("errors", {}).get("rate")
    out["server_p95"] = m.get("server_latency", {}).get("p(95)")
    return out


def render_html(summary: dict, slo_ms: int) -> str:
    rows = []
    for t, v in summary["by_type"].items():
        p95 = v.get("p95") or 0
        verdict = "PASS" if p95 < slo_ms else "FAIL"
        rows.append(
            f"<tr><td>{t}</td><td>{v.get('p50'):.1f}</td><td>{p95:.1f}</td>"
            f"<td>{v.get('p99'):.1f}</td><td>{v.get('max'):.1f}</td>"
            f"<td class='{verdict.lower()}'>{verdict}</td></tr>"
        )
    return f"""<!doctype html><html lang="vi"><meta charset="utf-8">
<title>Performance report</title>
<style>
 body{{font:14px system-ui;margin:40px;color:#1a1a1a}}
 table{{border-collapse:collapse;margin-top:16px}}
 th,td{{border:1px solid #ddd;padding:8px 14px;text-align:right}}
 th:first-child,td:first-child{{text-align:left}}
 .pass{{color:#0a7a34;font-weight:600}} .fail{{color:#c0392b;font-weight:600}}
 code{{background:#f4f4f4;padding:2px 6px;border-radius:4px}}
</style>
<h1>Performance report</h1>
<p>SLO p95 &lt; <b>{slo_ms} ms</b> · throughput <b>{summary.get('throughput_rps') or 0:.1f} req/s</b>
 · error rate <b>{(summary.get('error_rate') or 0)*100:.2f}%</b>
 · server-side p95 <b>{summary.get('server_p95') or 0:.1f} ms</b></p>
<table><thead><tr><th>Scenario</th><th>p50</th><th>p95</th><th>p99</th><th>max</th><th>Kết luận</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p style="margin-top:24px;color:#666">Sinh tự động từ kết quả k6 bằng <code>make report</code>.</p>
</html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("-o", "--out", default="reports/report.html")
    ap.add_argument("--slo-ms", type=int, default=1500)
    args = ap.parse_args()

    raw = json.loads(Path(args.raw).read_text(encoding="utf-8"))
    summary = extract(raw)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(summary, args.slo_ms), encoding="utf-8")

    js = out.with_suffix(".json")
    js.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[report] {out} + {js}")

    worst = max((v.get("p95") or 0) for v in summary["by_type"].values()) if summary["by_type"] else 0
    if worst >= args.slo_ms:
        raise SystemExit(f"FAIL: p95 {worst:.0f} ms >= SLO {args.slo_ms} ms")
    print(f"PASS: p95 cao nhất {worst:.0f} ms < SLO {args.slo_ms} ms")


if __name__ == "__main__":
    main()
