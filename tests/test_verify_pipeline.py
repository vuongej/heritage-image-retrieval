"""Offline tests for pipeline/verify (no network, no model download)."""

import json

import numpy as np
import pytest

from pipeline.verify import gate, metrics, router, split
from pipeline.verify.common import category_bucket, norm


def _row(name, url, cat="Đền thờ — Bắc Bộ (Hà Nội)", eid="e1", line=2):
    return {
        "entity_id": eid,
        "canonical_name": name,
        "category": cat,
        "image_url": url,
        "description": "",
        "from_db": "0",
        "line": line,
    }


def test_gate_rules_and_noext_policy():
    assert gate.gate("ftp://x/a.jpg") == "R1_invalid"
    assert gate.gate("https://lookaside.fbsbx.com/a.jpg") == "R1_blocked"
    assert gate.gate("https://x.vn/a b.jpg") == "R1_ws"
    assert gate.gate("https://cdn.vn/_next/image?url=x") == "R1_noext"
    # Measured: ~92% of no-extension URLs are real images, so 'download' keeps them.
    assert gate.gate("https://cdn.vn/_next/image?url=x", noext_policy="download") is None
    assert gate.gate("https://x.vn/a.JPG?w=1") is None


def test_gate_dedupes_url_within_entity_only():
    rows = [
        _row("A", "https://x.vn/1.jpg"),
        _row("A", "https://x.vn/1.jpg"),
        _row("B", "https://x.vn/1.jpg", eid="e2"),
    ]
    live, rep = gate.run(rows)
    assert len(live) == 2 and rep["by_rule"] == {"R6_dup_url": 1}


def test_norm_and_bucket():
    assert norm("Chùa Đậu (Hà Nội)") == "chua dau ha noi"
    assert category_bucket("Đền thờ — Bắc Bộ (Hà Nội, Nam Định)") == "đền thờ"


def test_split_keeps_name_variants_together_and_never_leaks():
    rows = []
    for g in range(60):
        for v, suffix in enumerate(("", " (Hà Nội)")):
            for i in range(3):
                rows.append(
                    _row(f"Chùa Số {g}{suffix}", f"https://x.vn/{g}-{v}-{i}.jpg", eid=f"e{g}-{v}")
                )
    s = split.split(rows)
    sides = {}
    for r in rows:
        sides.setdefault(f"Chùa Số {r['canonical_name'].split()[2]}", set()).add(
            s["assignment"][r["image_url"]]
        )
    assert all(len(v) == 1 for v in sides.values())  # "X" and "X (Hà Nội)" never split apart
    assert 0.2 <= s["report"]["test_share_rows"] <= 0.4


def test_risk_coverage_and_ece():
    correct = np.array([1, 1, 1, 0, 1, 0, 1, 1, 0, 0], float)
    conf = np.array([0.99, 0.95, 0.9, 0.5, 0.85, 0.4, 0.8, 0.75, 0.3, 0.2])
    rc = metrics.risk_coverage(correct, conf)
    assert rc["points"][0]["acc_keep"] == 0.6
    assert rc["points"][-1]["acc_keep"] >= rc["points"][0]["acc_keep"]  # dropping unsure helps
    assert metrics.ece([1, 0], [1.0, 0.0]) == 0.0
    assert metrics.ece([1, 1], [0.0, 0.0]) == 1.0


def test_router_budget_and_entity_rules():
    groups = ["small"] * 3 + ["big"] * 20 + ["full"] * 12
    pred = ["no"] * 3 + ["no"] * 20 + ["yes"] * 12
    conf = np.array([0.5] * 3 + list(np.linspace(0.5, 0.99, 20)) + [0.97] * 12)
    chosen, rep = router.select(groups, pred, conf, [False] * 35, alpha=0.2)
    assert rep["chosen"] == 7 and len(chosen) == 7
    assert not chosen & {0, 1, 2}  # entity with < 5 live images is not rescued with VLM money
    assert all(3 <= i < 23 for i in chosen)  # 'full' already has >= 8 confident yes
    assert min(chosen) == 3  # least confident first


def test_conformal_threshold_bounds_defer_rate():
    u = np.linspace(0, 1, 1001)
    theta = router.conformal_threshold(u, 0.15)
    assert (u > theta).mean() <= 0.15


def test_jev_logprob_confidence_and_schema(monkeypatch, tmp_path):
    from pipeline.verify import jev

    content = '{"verify":"yes","match":"đúng thực thể","ly_do":"ok","confidence":0.9}'
    tokens = [{"token": t, "logprob": -0.01} for t in ['{"', "verify", '":"']]
    tokens.append(
        {
            "token": "yes",
            "logprob": np.log(0.8),
            "top_logprobs": [
                {"token": "yes", "logprob": np.log(0.8)},
                {"token": "no", "logprob": np.log(0.15)},
                {"token": "def", "logprob": np.log(0.05)},
            ],
        }
    )
    tokens.append({"token": content[len('{"verify":"yes') :], "logprob": 0})
    assert jev._verify_logprob(content, {"content": tokens}, "yes") == pytest.approx(0.8, abs=1e-3)
    schema = jev._schema()
    assert schema["additionalProperties"] is False and set(schema["required"]) == {
        "verify",
        "match",
        "ly_do",
        "confidence",
    }

    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(jev, "cache_get", lambda k: None)
    monkeypatch.setattr(jev, "cache_put", lambda k, v: None)
    sent = {}

    class Resp:
        status_code = 200
        is_success = True
        text = ""

        def json(self):
            return {
                "model": "routed/x",
                "usage": {"prompt_tokens": 150, "completion_tokens": 20, "cost": 0.00001},
                "choices": [{"message": {"content": content}, "logprobs": {"content": tokens}}],
            }

    def post(url, json, headers, timeout):
        sent.update(json)
        return Resp()

    monkeypatch.setattr(jev.httpx, "post", post)
    d = jev.Jev().decide("entity: X")
    assert (
        sent["model"] == "typesafe/jev-router" and sent["response_format"]["type"] == "json_schema"
    )
    assert (
        d["verify"] == "yes"
        and d["routed_model"] == "routed/x"
        and d["conf_logprob"] == pytest.approx(0.8, abs=1e-3)
    )
    assert "image" not in json.dumps(sent["messages"])  # Jev only ever sees the text state


def test_jev_soft_stops_on_no_credit(monkeypatch):
    from pipeline.verify import jev

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(jev, "cache_get", lambda k: None)

    class Resp:
        status_code = 402
        is_success = False

    monkeypatch.setattr(jev.httpx, "post", lambda *a, **k: Resp())
    client = jev.Jev()
    with pytest.raises(jev.JevUnavailable):
        client.decide("s")
    with pytest.raises(jev.JevUnavailable):  # no further paid attempts after the first 402
        client.decide("s2")


def test_jev_without_key_is_unavailable(monkeypatch):
    from pipeline.verify import jev

    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    assert not jev.Jev().enabled


def test_vlm_batch_validates_every_image(monkeypatch):
    from pipeline.verify import vlm

    answer = {
        "items": [
            {
                "idx": 1,
                "subject": "dung",
                "watermark": False,
                "unsafe": False,
                "evidence": "mái chùa",
            },
            {
                "idx": 2,
                "subject": "partial",
                "watermark": False,
                "unsafe": False,
                "evidence": "chùa khác",
            },
            {
                "idx": 3,
                "subject": "dung",
                "watermark": True,
                "unsafe": False,
                "evidence": "logo báo",
            },
        ],
        "which_is_wrong": [2],
    }
    monkeypatch.setattr(vlm, "json_chat", lambda *a, **k: answer)
    out = vlm.judge_batch(
        {"canonical_name": "Chùa X", "category": "c"}, [("a", b"1"), ("b", b"2"), ("c", b"3")]
    )
    assert [out[k]["label"] for k in "abc"] == ["yes", "no", "no"]
    monkeypatch.setattr(vlm, "json_chat", lambda *a, **k: {"items": answer["items"][:2]})
    with pytest.raises(ValueError):
        vlm.judge_batch(
            {"canonical_name": "X", "category": "c"}, [("a", b"1"), ("b", b"2"), ("c", b"3")]
        )


def test_label_api_is_blind_and_validated(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from api.main import app

    monkeypatch.setenv("VERIFY_DIR", str(tmp_path))
    key = "a" * 64
    (tmp_path / "audit_queue.jsonl").write_text(
        json.dumps(
            {
                "key": key,
                "stratum": "random",
                "entity": "Chùa X",
                "category": "c",
                "description": "",
                "image_url": "https://x.vn/a.jpg",
                "source_url": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    client = TestClient(app)
    h = {"X-API-Key": "gsk_test_dev_only"}
    q = client.get("/v1/verify/audit", headers=h).json()
    assert q["total"] == 1 and not {"pred", "conf", "verify", "head_p_yes"} & set(q["items"][0])
    assert (
        client.post("/v1/verify/label", json={"key": key, "label": "maybe"}, headers=h).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/verify/label", json={"key": "b" * 64, "label": "yes"}, headers=h
        ).status_code
        == 404
    )
    r = client.post(
        "/v1/verify/label", json={"key": key, "label": "no", "reasons": ["watermark"]}, headers=h
    )
    assert r.status_code == 200 and r.json()["labelled"] == 1
    saved = json.loads((tmp_path / "human_labels.jsonl").read_text(encoding="utf-8"))
    assert saved["stratum"] == "random" and saved["reasons"] == ["watermark"]
    assert client.get("/thumbs/" + "z" * 64 + ".jpg").status_code == 404
