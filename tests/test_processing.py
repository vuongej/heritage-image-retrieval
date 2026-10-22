"""Processing service (Pipeline A): đọc CSV, quyết định, chấm nhãn, chạy end-to-end không mạng / GPU."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest

os.environ["PROCESS_DIR"] = tempfile.mkdtemp(prefix="process_test_")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from processing import pipeline  # noqa: E402
from processing.model import model_dir  # noqa: E402

HAS_MODEL = (model_dir() / "model_card.json").exists()


def test_read_csv_aliases_semicolon_bom_and_labels():
    data = "﻿entity_name;url;leaf_label;verify\nChùa Một Cột;https://a/x.jpg;Chùa;approved\n" \
           "Chùa Một Cột;https://a/y.jpg;Chùa;No\nHồ Gươm;https://a/z.jpg;Hồ;\n"
    rows, info = pipeline.read_csv(data.encode())
    assert info["delimiter"] == ";" and info["rows"] == 3 and info["labelled"] == 2
    assert info["mapping"]["canonical_name"] == "entity_name" and info["mapping"]["image_url"] == "url"
    assert [r["label"] for r in rows] == ["yes", "no", ""]
    # Không có entity_id: suy từ tên, cùng tên -> cùng entity.
    assert rows[0]["entity_id"] == rows[1]["entity_id"] != rows[2]["entity_id"]


@pytest.mark.parametrize(
    "data, message",
    [
        (b"foo,bar\n1,2\n", "Thiếu cột bắt buộc"),
        (b"name,image_url\n", "không có dòng"),
        ("name,image_url\nA,u\n".encode("utf-16"), "UTF-8"),
    ],
)
def test_read_csv_rejects(data, message):
    with pytest.raises(pipeline.InvalidCsv, match=message):
        pipeline.read_csv(data)


def test_vlm_label_rules():
    v = {"subject": "dung", "watermark": True, "unsafe": False, "label": "no"}
    assert pipeline.vlm_label(v, "goc") == "no"  # prompt gốc: watermark -> loại
    assert pipeline.vlm_label(v, "bo_watermark") == "yes"
    assert pipeline.vlm_label({**v, "unsafe": True}, "bo_watermark") == "no"  # unsafe luôn loại
    assert pipeline.vlm_label({**v, "subject": "partial", "watermark": False}, "partial_yes") == "yes"
    assert pipeline.vlm_label({**v, "subject": "partial"}, "chi_sai") == "yes"


def test_evaluate_counts_no_as_positive_class():
    m = pipeline.evaluate(["no", "no", "yes", "yes", ""], ["no", "yes", "no", "yes", "no"],
                          ["a", "a", "b", "c", "c"])
    assert m["n"] == 4 and m["confusion"] == {"no→no": 1, "yes→no": 1, "no→yes": 1, "yes→yes": 1}
    assert m["recall_no"] == 0.5 and m["recall_yes"] == 0.5
    assert m["entity_retention"] == 0.5  # b mất ảnh tốt duy nhất, c giữ được
    assert pipeline.evaluate(["yes"], ["yes"], ["a"]) is None  # cần đủ hai lớp


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Thay tải ảnh và SigLIP2 bằng bản giả xác định, để chạy cả luồng không cần mạng / GPU."""
    monkeypatch.setenv("VERIFY_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline, "PROCESS_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "vlm_available", lambda: False)

    def fake_fetch(row):
        key = hashlib.sha256(row["image_url"].strip().encode()).hexdigest()
        if "dead" in row["image_url"]:
            return {"key": key, "status": "error", "error": "HTTP 404"}
        w, h = (120, 90) if "small" in row["image_url"] else (800, 600)
        img = Image.new("RGB", (w, h), (int(key[:2], 16), int(key[2:4], 16), 90))
        buf = BytesIO()
        img.save(buf, format="JPEG")
        rec = {"key": key, "sha256": hashlib.sha256(buf.getvalue()).hexdigest(), "bytes": len(buf.getvalue()),
               "format": "JPEG", "w": w, "h": h, "ms": 5}
        if w < 300:
            return {**rec, "status": "too_small"}
        path = pipeline.fetch.thumb_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.getvalue())
        return {**rec, "status": "ok"}

    def vec(seed: str, n: int = 768) -> np.ndarray:
        v = np.random.default_rng(int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)).normal(size=n)
        return (v / np.linalg.norm(v)).astype(np.float32)

    monkeypatch.setattr(pipeline.fetch, "_fetch_one", fake_fetch)
    monkeypatch.setattr(pipeline.encoder, "loaded", lambda: (None, None, "cpu", None))
    monkeypatch.setattr(pipeline.encoder, "embed_images",
                        lambda paths, **_: np.stack([vec(Path(p).stem) for p in paths]))
    monkeypatch.setattr(pipeline.encoder, "embed_texts", lambda texts: np.stack([vec(t) for t in texts]))
    monkeypatch.setattr(pipeline.time, "sleep", lambda _s: None)  # bỏ backoff lần tải lại
    return tmp_path


CSV = (
    "entity_id,entity_name,category,image_url,verify\n"
    + "".join(f"e1,Chùa Một Cột,Chùa,https://h/{i}.jpg,{'yes' if i % 3 else 'no'}\n" for i in range(8))
    + "e1,Chùa Một Cột,Chùa,https://h/0.jpg,yes\n"  # trùng URL trong entity
    + "e2,Hồ Gươm,Hồ,https://h/dead.jpg,no\n"
    + "e2,Hồ Gươm,Hồ,https://h/small.jpg,no\n"
    + "e2,Hồ Gươm,Hồ,not-a-url,no\n"
)


@pytest.mark.skipif(not HAS_MODEL, reason="chưa có models/verify (scripts.train_verify_model)")
def test_run_end_to_end_offline(offline):
    rows, _ = pipeline.read_csv(CSV.encode())
    events = []
    summary = pipeline.run(rows, pipeline.Options(use_vlm=True), offline,
                           lambda s, d, t: events.append((s, d, t)), lambda: None)
    reasons = summary["by_reason"]
    assert summary["rows"] == 12 and sum(reasons.values()) == 12
    assert reasons["R6_dup_url"] == 1 and reasons["dead"] == 1 and reasons["too_small"] == 1
    assert reasons["R1_invalid"] == 1
    assert reasons.get("classifier_yes", 0) + reasons.get("classifier_no", 0) == 8
    assert summary["routed"] == 0 and summary["vlm"]["skipped"]  # không có key -> không gửi VLM
    assert summary["metrics"]["n"] == 12
    assert {s for s, _, _ in events} >= {"parse", "gate", "fetch", "embed", "classify", "route", "finalize"}
    out = (offline / "results.csv").read_text("utf-8-sig").splitlines()
    assert out[0].startswith("entity_id,entity_name,category,image_url,verify,decision,stage,reason")
    assert len(out) == 13
    # Lần chạy thứ hai dùng lại ảnh và embedding đã có.
    again = pipeline.run(rows, pipeline.Options(use_vlm=False), offline, lambda *a: None, lambda: None)
    assert again["embedding"]["encoded_images"] == 0
    assert again["by_reason"] == reasons


@pytest.mark.skipif(not HAS_MODEL, reason="chưa có models/verify")
def test_api_upload_poll_items_and_csv(offline, monkeypatch):
    monkeypatch.setenv("API_KEY_ENFORCE", "false")
    from processing import jobs as jobs_mod
    from processing import main

    monkeypatch.setattr(main, "manager", jobs_mod.JobManager())
    client = TestClient(main.app)
    assert client.get("/v1/process/health").json()["model"]["name"] == "M1b"
    bad = client.post("/v1/process/jobs", files={"file": ("a.csv", b"x,y\n1,2\n", "text/csv")})
    assert bad.status_code == 422 and "Thiếu cột" in bad.json()["detail"]
    assert client.post("/v1/process/jobs", files={"file": ("a.txt", CSV.encode(), "text/plain")}).status_code == 422
    created = client.post("/v1/process/jobs", files={"file": ("demo.csv", CSV.encode(), "text/csv")},
                          data={"use_vlm": "false"})
    assert created.status_code == 201
    job_id = created.json()["id"]
    for _ in range(100):
        job = client.get(f"/v1/process/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert job["status"] == "done", job["error"]
    assert all(s["status"] in ("done", "skipped") for s in job["stages"])
    items = client.get(f"/v1/process/jobs/{job_id}/items", params={"stage": "rule", "limit": 50}).json()
    assert items["total"] == 4 and all(x["decision"] == "no" for x in items["items"])
    csv = client.get(f"/v1/process/jobs/{job_id}/result.csv")
    assert csv.status_code == 200 and "attachment" in csv.headers["content-disposition"]
    assert client.get("/v1/process/thumbs/../../etc.jpg").status_code == 404
    assert any(j["id"] == job_id for j in client.get("/v1/process/jobs").json()["items"])
