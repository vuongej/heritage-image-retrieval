"""Phase 2.2: caption ảnh không có mô tả, 10 ảnh / request, thumbnail 256px.

Model online `google/gemini-3.5-flash-lite` qua chat/completions. Biến thể `:batch` (giá 1/2)
KHÔNG gọi được ở endpoint này (HTTP 404, đo 2026-10-20): nó đi qua /api/v1/batches, chỉ nhận
URL ảnh công khai (nhiều host ảnh chặn tải từ xa — xem Phần A) và có thể mất tới 96 giờ.

Prompt không đưa tên thực thể: caption chỉ mô tả cái nhìn thấy, không "xác nhận" metadata.

  python -X utf8 -m scripts.caption_missing --pilot 50          # ghi cột caption + trang review
  python -X utf8 -m scripts.caption_missing --all               # toàn bộ ảnh thiếu mô tả
  python -X utf8 -m scripts.caption_missing --apply             # nối caption vào metadata_text
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

from pipeline.verify.fetch import thumb_path
from storage.local import connect
from storage.runtime import load_env

load_env()

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "phase2"
SOURCE = "gemini3.5fl"
GROUP = 10
SIDE = 256
PROMPT = (
    "Mô tả 1–2 câu tiếng Việt: đối tượng chính, địa điểm (nếu biết), đặc điểm thị giác "
    "(màu mái, thời điểm trong ngày, góc chụp, cảnh quan xung quanh). "
    "Không suy đoán tên người cụ thể."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "captions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "caption": {"type": "string"}},
                "required": ["id", "caption"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["captions"],
    "additionalProperties": False,
}


def key(url: str) -> str:
    return hashlib.sha256(url.strip().encode()).hexdigest()


def data_url(path: Path) -> str:
    img = Image.open(path).convert("RGB")
    img.thumbnail((SIDE, SIDE), Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def candidates() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT rownum, image_url FROM images WHERE coalesce(description,'')=''"
            " AND caption IS NULL ORDER BY rownum"
        ).fetchall()
    out = []
    for rownum, url in rows:
        path = thumb_path(key(url))
        if path.exists():
            out.append({"rownum": rownum, "path": path})
    return out


def caption_group(group: list[dict], model: str, api_key: str) -> dict:
    content: list = [
        {
            "type": "text",
            "text": PROMPT + f" Có {len(group)} ảnh, đánh số id 0..{len(group) - 1} theo thứ tự. "
            "Trả JSON {captions:[{id, caption}]}, mỗi ảnh đúng một caption.",
        }
    ]
    for i, item in enumerate(group):
        content.append({"type": "text", "text": f"id {i}:"})
        content.append({"type": "image_url", "image_url": {"url": data_url(item["path"])}})
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "Captions", "strict": True, "schema": SCHEMA},
        },
        "max_tokens": 200 * len(group) + 400,
        "temperature": 0,
        "reasoning": {"effort": "minimal"},
        "usage": {"include": True},
    }
    last = "unknown"
    for attempt in range(3):
        started = time.perf_counter()
        try:
            response = httpx.post(
                os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
                + "/chat/completions",
                json=body,
                headers={"Authorization": "Bearer " + api_key},
                timeout=120,
            )
            if not response.is_success:
                raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
            data = response.json()
            parsed = json.loads(data["choices"][0]["message"]["content"])
            captions = {c["id"]: c["caption"].strip() for c in parsed["captions"]}
            if set(captions) != set(range(len(group))) or not all(captions.values()):
                raise ValueError(f"thiếu caption: có id {sorted(captions)}")
            usage = data.get("usage") or {}
            return {
                "ok": True,
                "captions": [captions[i] for i in range(len(group))],
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "cost": usage.get("cost"),
                "ms": round((time.perf_counter() - started) * 1000),
            }
        except (httpx.HTTPError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(2 * (attempt + 1))
    return {"ok": False, "error": last}


def run(items: list[dict], model: str, workers: int) -> dict:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY trống")
    groups = [items[i : i + GROUP] for i in range(0, len(items), GROUP)]
    done, failures, usage = [], [], []
    with ThreadPoolExecutor(workers) as pool:
        for group, result in zip(
            groups, pool.map(lambda g: caption_group(g, model, api_key), groups), strict=True
        ):
            if not result["ok"]:
                failures.append({"rownums": [g["rownum"] for g in group], "error": result["error"]})
                continue
            usage.append(result)
            done += [(c, g["rownum"]) for g, c in zip(group, result["captions"], strict=True)]
            with connect() as conn:
                conn.executemany(
                    "UPDATE images SET caption=?, caption_source=? WHERE rownum=?",
                    [(c, SOURCE, r) for c, r in done[-len(group) :]],
                )
            if len(usage) % 50 == 0:
                print(f"[caption] {len(done):,}/{len(items):,}", flush=True)
    if failures:
        with (OUT / "caption_failures.jsonl").open("a", encoding="utf-8") as stream:
            for f in failures:
                stream.write(json.dumps(f) + "\n")
    cost = sum(u["cost"] or 0 for u in usage)
    return {
        "model": model,
        "images": len(items),
        "captioned": len(done),
        "failed_images": sum(len(f["rownums"]) for f in failures),
        "requests": len(usage),
        "prompt_tokens": sum(u["prompt_tokens"] or 0 for u in usage),
        "completion_tokens": sum(u["completion_tokens"] or 0 for u in usage),
        "usd": round(cost, 6),
        "usd_per_image": round(cost / max(1, len(done)), 6),
        "completion_tokens_per_image": round(
            sum(u["completion_tokens"] or 0 for u in usage) / max(1, len(done)), 1
        ),
        "ms_per_request_p50": sorted(u["ms"] for u in usage)[len(usage) // 2] if usage else None,
        "rownums": [r for _, r in done],
    }


def review_page(rownums: list[int], path: Path) -> None:
    with connect() as conn:
        marks = ",".join("?" * len(rownums))
        rows = conn.execute(
            f"SELECT i.rownum, i.image_url, i.caption, e.entity_name, e.parent_class FROM images i"
            f" JOIN entities e USING(entity_id) WHERE i.rownum IN ({marks}) ORDER BY i.rownum",
            rownums,
        ).fetchall()
    cards = "".join(
        f'<figure><img src="{data_url(thumb_path(key(r[1])))}" alt=""><figcaption>'
        f"<p>{html.escape(r[2] or '')}</p><small>Thực thể: {html.escape(r[3])} · "
        f"{html.escape(r[4] or '')} · rownum {r[0]}</small></figcaption></figure>"
        for r in rows
    )
    path.write_text(
        "<!doctype html><meta charset=utf-8><title>Caption pilot</title><style>"
        "body{font:15px system-ui;margin:16px;background:#fafafa;color:#222}"
        "main{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}"
        "figure{margin:0;background:#fff;border:1px solid #ddd;border-radius:8px;overflow:hidden}"
        "img{width:100%;height:200px;object-fit:cover}figcaption{padding:8px}"
        "small{color:#666}</style><h1>Caption pilot — "
        f"{len(rows)} ảnh</h1><p>Caption sinh KHÔNG biết tên thực thể; dòng nhỏ là metadata gốc để "
        f"đối chiếu.</p><main>{cards}</main>",
        encoding="utf-8",
    )


def apply() -> int:
    """Nối caption vào metadata_text (giữ nguyên dữ liệu cũ) + cập nhật FTS. Cần build lại index."""
    from storage.local import plain

    with connect() as conn:
        rows = conn.execute(
            "SELECT rownum, metadata_text, caption FROM images WHERE caption IS NOT NULL"
            " AND instr(metadata_text, caption) = 0"
        ).fetchall()
        for rownum, text, caption in rows:
            merged = f"{text}. {caption}"
            conn.execute("UPDATE images SET metadata_text=? WHERE rownum=?", (merged, rownum))
            conn.execute("UPDATE image_fts SET text=? WHERE rowid=?", (plain(merged), rownum))
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pilot", type=int)
    mode.add_argument("--all", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--model", default=os.getenv("LLM_ONLINE_MODEL", "google/gemini-3.5-flash-lite")
    )
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.apply:
        print(json.dumps({"applied": apply()}))
        return
    items = candidates()
    print(f"[caption] {len(items):,} ảnh thiếu mô tả đã có thumbnail", flush=True)
    if args.pilot:
        items = random.Random(42).sample(items, min(args.pilot, len(items)))
    summary = run(items, args.model, args.workers)
    name = "caption_pilot" if args.pilot else "caption_all"
    if args.pilot:
        review_page(summary["rownums"], OUT / f"{name}.html")
    summary.pop("rownums")
    (OUT / f"{name}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
