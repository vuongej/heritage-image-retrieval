from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)
HEADERS = {"X-API-Key": "gsk_test_dev_only"}


def test_reports_require_key(monkeypatch):
    monkeypatch.setenv("API_KEY_ENFORCE", "true")
    assert client.get("/v1/reports").status_code == 401


def test_unknown_report_is_404_not_a_path():
    for name in ("nope", "..%2F..%2F.env", "latency.json"):
        assert client.get(f"/v1/reports/{name}", headers=HEADERS).status_code == 404


def test_report_listing_and_trimmed_quality(tmp_path, monkeypatch):
    from api.routers import reports

    (tmp_path / "q.json").write_text('{"summary": {"a": 1}, "results": [1, 2]}', encoding="utf-8")
    monkeypatch.setattr(reports, "ROOT", tmp_path)
    monkeypatch.setattr(reports, "REPORTS", {"quality": ("q.json", "Q", ("summary",)),
                                             "missing": ("x.json", "X", None)})  # fmt: skip
    items = client.get("/v1/reports", headers=HEADERS).json()["items"]
    assert [i["available"] for i in items] == [True, False]
    body = client.get("/v1/reports/quality", headers=HEADERS).json()
    assert body["data"] == {"summary": {"a": 1}}
    assert len(body["sha256"]) == 64
    assert client.get("/v1/reports/missing", headers=HEADERS).status_code == 404


def test_stats_reads_current_kg_schema(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api.main import app

    monkeypatch.setenv("LOCAL_DATA_DIR", str(tmp_path / "store"))
    with TestClient(app) as client:
        r = client.get("/v1/stats", headers=HEADERS)
    assert r.status_code == 200
    kg = r.json()["knowledge_graph"]
    assert {"kg_relations", "edges_verified", "persons", "places"} <= set(kg)
