"""Human-readable report (Markdown + SVG risk-coverage curve) from report.json."""

from __future__ import annotations

from pathlib import Path


def _svg(layers: dict) -> str:
    w, h, pad = 520, 300, 44
    colors = {"head": "#2563eb", "jev": "#dc2626"}
    pts_all = [p for v in layers.values() for p in v["risk_coverage"]["points"]]
    if not pts_all:
        return ""
    lo = max(0.0, min(p["acc_keep"] for p in pts_all) - 0.05)
    hi = min(1.0, max(p["acc_keep"] for p in pts_all) + 0.02)

    def xy(p):
        x = pad + (p["alpha"] / 0.30) * (w - 2 * pad)
        y = h - pad - (p["acc_keep"] - lo) / max(hi - lo, 1e-9) * (h - 2 * pad)
        return x, y

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="sans-serif" font-size="12">',
        f'<rect width="{w}" height="{h}" fill="#fff"/>',
        f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="#999"/>',
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{h - pad}" stroke="#999"/>',
        f'<text x="{w / 2}" y="{h - 8}" text-anchor="middle">α = tỉ lệ chuyển VLM (ảnh ít tự tin nhất)</text>',
        f'<text x="12" y="{h / 2}" transform="rotate(-90 12 {h / 2})" text-anchor="middle">đồng thuận phần giữ lại</text>',
    ]
    for a in (0, 0.05, 0.10, 0.15, 0.20, 0.30):
        x = pad + a / 0.30 * (w - 2 * pad)
        out.append(
            f'<text x="{x:.0f}" y="{h - pad + 16}" text-anchor="middle">{int(a * 100)}%</text>'
        )
    for v in (lo, (lo + hi) / 2, hi):
        y = h - pad - (v - lo) / max(hi - lo, 1e-9) * (h - 2 * pad)
        out.append(f'<text x="{pad - 6}" y="{y + 4:.0f}" text-anchor="end">{v:.2f}</text>')
    for i, (name, v) in enumerate(layers.items()):
        pts = [xy(p) for p in v["risk_coverage"]["points"]]
        c = colors.get(name, "#16a34a")
        out.append(
            f'<polyline fill="none" stroke="{c}" stroke-width="2" points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}"/>'
        )
        for x, y in pts:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{c}"/>')
        out.append(
            f'<text x="{w - pad - 70}" y="{pad + 14 + 16 * i}" fill="{c}">■ {name} (AURC {v["risk_coverage"]["aurc"]})</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


def _table(rows: list[dict], cols: list[str]) -> str:
    if not rows:
        return "_(trống)_\n"
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |\n" for r in rows)


def write_markdown(r: dict, out_dir: Path) -> None:
    svg = _svg(r["layers_proxy_eval"])
    if svg:
        (out_dir / "risk_coverage.svg").write_text(svg, encoding="utf-8")
    md = [
        "# Báo cáo verify ảnh — Gate → SigLIP2 → head → Jev → router → VLM\n",
        f"> {r['proxy_warning']}\n",
        "## Phạm vi\n",
        f"- CSV `{r['csv']}` · seed {r['seed']} · pilot {r['pilot_groups']} nhóm thực thể · {r['pilot_rows']} dòng",
        f"- Tập đánh giá: **{r['target_split']}** · ngân sách VLM α = {r['budget_alpha']:.0%} · tầng quyết định chính: **{r['primary_layer']}**\n",
        "## S0 Gate (toàn bộ CSV)\n",
        f"- sống {r['gate']['live_rows']:,}/{r['gate']['source_rows']:,} · loại theo rule: `{r['gate']['by_rule']}` · "
        f"noext_policy = `{r['gate']['noext_policy']}`\n",
        "## S2b Split (toàn bộ dòng sống)\n",
        f"- dòng `{r['split']['rows']}` · nhóm `{r['split']['groups']}` · test {r['split']['test_share_rows']:.1%}",
        f"- rò rỉ nội dung (cùng sha256 ở 2 phía) đã bỏ khỏi test: {r['cross_split_content_leaks_dropped']}\n",
        "## S1 Tải + embedding\n",
        f"- fetch: `{r['fetch']}` · trùng sha256 trong thực thể: {r['sha256_dups_in_entity']}",
        f"- encoder: `{r['embedding']}`\n",
        "## S3 Nhãn bootstrap (VLM thầy)\n",
        f"- {r['bootstrap']['labelled']} ảnh · tỉ lệ yes {r['bootstrap']['yes_rate']:.1%}\n",
        "## S4 Head + Jev\n",
        f"- head: `{r['head']}`",
        f"- Jev: `{r['jev']}`\n",
        "### Risk–coverage (proxy, trên tập đánh giá)\n",
        "![risk-coverage](risk_coverage.svg)\n" if svg else "",
    ]
    for name, v in r["layers_proxy_eval"].items():
        md.append(
            f"**{name}** — đồng thuận 100% coverage: {v['proxy_agreement_all']} · ECE confidence {v['ece_conf']} · AURC {v['risk_coverage']['aurc']}\n"
        )
        md.append(_table(v["risk_coverage"]["points"], ["alpha", "coverage", "acc_keep"]))
    md += [
        "\n## T4 Router\n",
        f"`{r['router']}`\n",
        "## T5 VLM batch (≤ 8 ảnh/lần)\n",
        f"`{r['vlm']}`\n",
        "## Kết quả cascade\n",
        f"- proxy: `{r['cascade_proxy']}`",
        f"- **nhãn người từ cột `flag` của CSV (approved = yes)**: `{r.get('approved_flag_eval')}`",
        f"- nhãn người gán thêm trên giao diện: `{r['human_eval']}`",
        f"- cấp thực thể: `{r['entity_level']}`\n",
        "### Theo category\n",
        _table(r["by_category"], ["key", "n", "yes_rate", "agreement"]),
        "\n### Theo host\n",
        _table(r["by_host"], ["key", "n", "yes_rate", "agreement"]),
        "\n## Chi phí\n",
        f"`{r['cost']}`\n",
        "## Thời gian (giây)\n",
        f"`{r['seconds']}`\n",
        f"\nFile giao: `{r['verified_csv']}`\n",
    ]
    (out_dir / "report.md").write_text("\n".join(md), encoding="utf-8")
