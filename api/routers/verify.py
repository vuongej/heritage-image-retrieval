"""Human audit for the verify pipeline (skill_06/07): blind labelling of the audit queue.

The model's prediction is never sent to the page, so the human label is independent.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from pipeline.verify.common import read_jsonl, run_dir

router = APIRouter()
thumbs = APIRouter()
_lock = threading.Lock()
KEY = re.compile(r"^[0-9a-f]{64}$")
REASONS = {
    "sai_thuc_the",
    "khop_mot_phan",
    "watermark",
    "so_dien_thoai",
    "chat_luong_kem",
    "nhay_cam",
    "khac",
}


class LabelIn(BaseModel):
    key: str = Field(pattern=r"^[0-9a-f]{64}$")
    label: Literal["yes", "no"]
    reasons: list[str] = Field(default_factory=list, max_length=7)
    labeller: str = Field("", max_length=60)


def _labels() -> dict[str, dict]:
    return {r["key"]: r for r in read_jsonl(run_dir() / "human_labels.jsonl")}


@router.get("/verify/audit")
def audit_queue(limit: int = 20, include_done: bool = False) -> dict:
    queue = list(read_jsonl(run_dir() / "audit_queue.jsonl"))
    done = _labels()
    items = [q for q in queue if include_done or q["key"] not in done][: max(1, min(limit, 200))]
    for q in items:
        q["thumb"] = f"/thumbs/{q['key']}.jpg"
        q["human"] = done.get(q["key"], {}).get("label")
    return {
        "total": len(queue),
        "labelled": sum(q["key"] in done for q in queue),
        "by_stratum": {s: sum(q["stratum"] == s for q in queue) for s in ("random", "hard")},
        "items": items,
    }


@router.post("/verify/label")
def save_label(body: LabelIn) -> dict:
    queue = {q["key"]: q for q in read_jsonl(run_dir() / "audit_queue.jsonl")}
    if body.key not in queue:
        raise HTTPException(404, "key is not in the audit queue")
    bad = set(body.reasons) - REASONS
    if bad:
        raise ValueError(f"Unknown reasons: {sorted(bad)}")
    rec = {
        "key": body.key,
        "label": body.label,
        "reasons": sorted(set(body.reasons)),
        "stratum": queue[body.key]["stratum"],
        "labeller": body.labeller,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    with _lock, (run_dir() / "human_labels.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"saved": True, "labelled": len(_labels())}


@router.get("/verify/report")
def report() -> dict:
    from pathlib import Path

    path = Path("reports/verify/report.json")
    if not path.exists():
        raise HTTPException(404, "run python -m pipeline.verify first")
    return json.loads(path.read_text(encoding="utf-8"))


@thumbs.get("/thumbs/{name}", include_in_schema=False)
def thumb(name: str) -> FileResponse:
    key = name.removesuffix(".jpg")
    if not KEY.match(key):
        raise HTTPException(404)
    from pipeline.verify.fetch import thumb_path

    path = thumb_path(key)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})
