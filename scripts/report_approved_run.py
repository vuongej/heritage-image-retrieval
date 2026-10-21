"""Standalone HTML view of the actual local run and returned image URLs."""

from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path


def audit_section(folder: Path) -> str:
    path = folder / "audit.json"
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    s = data["summary"]
    flagged = [
        r
        for r in data["images"]
        if r["status"] == "analyzed"
        and (not r["stage1_passed"] or r.get("stage3_decision") == "reject")
    ]
    figures = "".join(
        f'<figure><a href="{escape(r["image_url"], quote=True)}" target="_blank" rel="noopener">'
        f'<img loading="lazy" src="{escape(r["image_url"], quote=True)}" alt=""></a>'
        f"<figcaption>{escape(r['entity_name'])}<br>Stage 1: "
        f"{escape('; '.join(r['stage1_reasons']) or 'pass')}<br>Stage 3: "
        f"{escape(str(r.get('stage3_decision')))} — {escape(r.get('stage3_reason', ''))}"
        f"</figcaption></figure>"
        for r in flagged[:40]
    )
    return (
        f"<section><h2>Audit Phần A (mẫu {s['sample_size']} ảnh)</h2>"
        f"<p>Tải được {s['status'].get('analyzed', 0)} · Stage 1 pass {s['stage1_pass']} · "
        f"Stage 3 accept {s['stage3_accept']}/{s['stage3_judged']} · "
        f"token/ảnh {escape(str(s['stage3_tokens_per_image']))}</p>"
        f'<p>Ảnh bị Stage 1 hoặc Stage 3 gắn cờ:</p><div class="grid">{figures}</div></section>'
    )


def main():
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else "reports/approved_run")
    report = json.loads((folder / "pipeline_report.json").read_text(encoding="utf-8"))
    cards = []
    for query in report["queries"]:
        images = "".join(
            f'<figure><a href="{escape(h["image_url"], quote=True)}" target="_blank" rel="noopener">'
            f'<img loading="lazy" src="{escape(h["image_url"], quote=True)}" alt="{escape(h["leaf_label"])}"></a>'
            f"<figcaption>{escape(h['leaf_label'])}<br>score {h['score']:.3f}</figcaption></figure>"
            for h in query["hits"]
        )
        cards.append(
            f"<section><h2>{escape(query['query'])}</h2><p>{escape(query['intent_type'])} · "
            f"{escape(query['parser'])} · {query['returned_hits']} ảnh · {query['total_ms']} ms</p>"
            f'<div class="grid">{images}</div></section>'
        )
    text = f"""<!doctype html><html lang="vi"><meta charset="utf-8"><title>Approved pipeline — kết quả thực</title>
<style>body{{font:16px system-ui;max-width:1200px;margin:32px auto;padding:0 20px;color:#202b38;background:#f4f6f8}}
section{{background:white;padding:24px;margin:24px 0;border-radius:12px}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}}
figure{{margin:0}}img{{width:100%;height:150px;object-fit:cover;background:#ddd}}figcaption{{padding:8px;font-size:14px}}code{{background:#e7edf2}}</style>
<h1>Pipeline approved: kết quả thực</h1><p>{report["source_rows"]:,} dòng CSV ·
username: {escape(", ".join(report.get("usernames") or ["(tất cả)"]))} ({report.get("scoped_rows", report["source_rows"]):,} dòng) ·
{report["catalog"]["images"]:,} ảnh hợp lệ ·
{report["catalog"]["entities"]:,} thực thể · {report["quarantined_rows"]} URL cách ly.</p>
<p>DeepSeek: <code>{escape(str(report["model"]))}</code>. Embedding metadata 384 chiều; không tải hay kiểm duyệt lại ảnh.
Ảnh dưới đây tải từ URL nguồn khi mở báo cáo. Kiểm tra nhãn thực thể chỉ là smoke test, chưa phải goldset độc lập.</p>
<p>Graph: {report["graph"]["n_nodes"]:,} node, {report["graph"]["n_edges"]:,} cạnh.
Index hoàn thành: {report["index"]["complete"]}. Deploy: không chạy.</p>{audit_section(folder)}{"".join(cards)}</html>"""
    (folder / "report.html").write_text(text, encoding="utf-8")
    print(folder / "report.html")


if __name__ == "__main__":
    main()
