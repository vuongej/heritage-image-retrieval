"""Sinh báo cáo HTML + JSON từ summary của k6 (loadtest/loadtest.js) — reproducible.

python -m loadtest.make_report reports/loadtest/raw.json -o reports/loadtest/report.html [--slo-ms 3000]
Thoát mã 1 khi một nhóm (pha, loại) có p95 >= SLO hoặc tỉ lệ lỗi >= 1% (gate cho CI).

Summary của k6 đặt số liệu trong metrics[<tên>]["values"]; nhóm (pha, loại) chỉ xuất hiện khi
có threshold tương ứng — loadtest.js khai báo đủ.
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

GROUP = re.compile(r"^http_req_duration\{phase:(\w+),type:(\w+)\}$")
PHASE_TEXT = {"cold": "lạnh (không cache, trong hạn mức)", "warm": "tải cao (có cache)",
              "burst": "dồn (không cache, vượt hạn mức)"}


def extract(raw: dict) -> dict:
    metrics = raw.get("metrics", {})

    def values(name: str) -> dict:
        m = metrics.get(name) or {}
        return m.get("values", m)  # k6 >= 0.4x: {"type", "contains", "values"}

    groups = []
    for name in metrics:
        hit = GROUP.match(name)
        if not hit:
            continue
        v = values(name)
        if not v.get("count"):
            continue
        groups.append({
            "phase": hit.group(1), "type": hit.group(2), "count": int(v["count"]),
            "p50": v.get("med"), "p90": v.get("p(90)"), "p95": v.get("p(95)"), "p99": v.get("p(99)"),
            "max": v.get("max"), "avg": v.get("avg"),
        })
    groups.sort(key=lambda g: (list(PHASE_TEXT).index(g["phase"]) if g["phase"] in PHASE_TEXT else 9, g["type"]))
    reqs = values("http_reqs")
    duration_s = (raw.get("state") or {}).get("testRunDurationMs", 0) / 1000
    phases = {}
    for g in groups:
        p = phases.setdefault(g["phase"], {"requests": 0})
        p["requests"] += g["count"]
    return {
        "groups": groups,
        "phases": phases,
        "requests": int(reqs.get("count", 0)),
        "throughput_rps": reqs.get("rate"),
        "duration_s": round(duration_s, 1),
        "error_rate": values("errors").get("rate"),
        "degraded_rate": values("degraded").get("rate"),
        "server_p95_ms": values("server_ms").get("p(95)"),
    }


def render_html(s: dict, slo: int) -> str:
    def ms(v):
        return "—" if v is None else f"{v:,.0f}"

    rows = "".join(
        f"<tr><td>{html.escape(PHASE_TEXT.get(g['phase'], g['phase']))}</td><td>{g['type']}</td>"
        f"<td>{g['count']:,}</td><td>{ms(g['p50'])}</td><td>{ms(g['p95'])}</td><td>{ms(g['p99'])}</td>"
        f"<td>{ms(g['max'])}</td><td class='{'pass' if (g['p95'] or 0) < slo else 'fail'}'>"
        f"{'ĐẠT' if (g['p95'] or 0) < slo else 'KHÔNG ĐẠT'}</td></tr>"
        for g in s["groups"]
    )
    pct = lambda v: "—" if v is None else f"{v * 100:.2f}%"  # noqa: E731
    return f"""<!doctype html><html lang="vi"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Load test /v1/search</title>
<style>
 body{{font:14px/1.5 system-ui,sans-serif;margin:32px auto;max-width:960px;padding:0 16px;color:#1a1a1a}}
 table{{border-collapse:collapse;width:100%;margin-top:12px}}
 th,td{{border-bottom:1px solid #e5e7eb;padding:7px 10px;text-align:right}}
 th:nth-child(-n+2),td:nth-child(-n+2){{text-align:left}}
 .pass{{color:#047857;font-weight:600}} .fail{{color:#b91c1c;font-weight:600}}
 .kpi{{display:flex;gap:24px;flex-wrap:wrap}} .kpi div{{min-width:150px}}
 .kpi b{{display:block;font-size:22px}}
</style>
<h1>Load test /v1/search</h1>
<div class="kpi">
 <div><b>{s['requests']:,}</b>request trong {s['duration_s']:,.0f} s</div>
 <div><b>{(s['throughput_rps'] or 0):.2f}</b>request/s trung bình</div>
 <div><b>{pct(s['error_rate'])}</b>lỗi</div>
 <div><b>{pct(s['degraded_rate'])}</b>request suy giảm (hết hạn mức endpoint)</div>
 <div><b>{ms(s['server_p95_ms'])} ms</b>p95 phía server (X-Response-Time)</div>
</div>
<table><thead><tr><th>Pha</th><th>Loại</th><th>Request</th><th>p50 ms</th><th>p95 ms</th><th>p99 ms</th>
<th>max ms</th><th>SLO p95 &lt; {slo:,} ms</th></tr></thead><tbody>{rows}</tbody></table>
<p style="color:#6b7280;margin-top:20px">Sinh tự động bởi <code>loadtest/make_report.py</code> từ summary k6
(<code>loadtest/loadtest.js</code>). Latency đo phía client k6, gồm proxy web.</p>
</html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("-o", "--out", default="reports/loadtest/report.html")
    ap.add_argument("--slo-ms", type=int, default=3000)
    args = ap.parse_args()
    summary = extract(json.loads(Path(args.raw).read_text(encoding="utf-8")))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(summary, args.slo_ms), encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[report] {out} + {out.with_suffix('.json')}")
    bad = [g for g in summary["groups"] if (g["p95"] or 0) >= args.slo_ms]
    if bad or (summary["error_rate"] or 0) >= 0.01:
        raise SystemExit(
            "FAIL: " + "; ".join(f"{g['phase']}/{g['type']} p95 {g['p95']:.0f} ms" for g in bad)
            + (f"; errors {summary['error_rate']:.2%}" if (summary["error_rate"] or 0) >= 0.01 else "")
        )
    worst = max((g["p95"] or 0) for g in summary["groups"]) if summary["groups"] else 0
    print(f"PASS: max group p95 {worst:.0f} ms < SLO {args.slo_ms} ms")  # ASCII: console Windows cp1252


if __name__ == "__main__":
    main()
