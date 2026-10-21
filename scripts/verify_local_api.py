"""Exercise real local API routes after a completed approved-data run."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from storage.local import connect


def main():
    with connect() as conn:
        # First image of the first two distinct entities, so the rerank check is unambiguous.
        rows = conn.execute("""SELECT i.*, e.entity_name, e.parent_class FROM images i
            JOIN entities e USING(entity_id)
            WHERE i.rownum IN (SELECT min(rownum) FROM images GROUP BY entity_id)
            ORDER BY rownum LIMIT 2""").fetchall()
    if len(rows) < 2:
        raise RuntimeError("Import and index the CSV first")
    headers = {"X-API-Key": os.environ["TEST_API_KEY"]}
    results = []
    with TestClient(app) as client:
        checks = [
            ("health", "GET", "/v1/health", None),
            ("search", "POST", "/v1/search", {"query": rows[0]["entity_name"], "top_k": 10}),
            ("embed", "POST", "/v1/embed", {"texts": [rows[0]["entity_name"]]}),
            (
                "rerank",
                "POST",
                "/v1/rerank",
                {
                    "query": rows[0]["entity_name"],
                    "candidates": [dict(row) for row in rows],
                    "keep": 1,
                },
            ),
            ("entities", "GET", "/v1/entities?limit=2", None),
            ("graph", "GET", "/v1/graph?entity_id=" + rows[0]["entity_id"], None),
        ]
        if os.getenv("VERIFY_IMAGE_EMBED", "true").lower() == "true":
            checks.append(
                ("embed_image", "POST", "/v1/embed", {"image_urls": [rows[0]["image_url"]]})
            )
        for name, method, url, payload in checks:
            response = client.request(method, url, json=payload, headers=headers)
            body = response.json()
            if response.status_code != 200:
                raise RuntimeError(f"{name} returned HTTP {response.status_code}: {body}")
            if name == "health" and not body["index_complete"]:
                raise RuntimeError("API reports incomplete index")
            if name == "search" and (
                not body["hits"]
                or not body["parser"].startswith(("rule", "llm"))
                or body["hits"][0]["entity_id"] != rows[0]["entity_id"]
            ):
                raise RuntimeError("Search did not return the queried entity")
            if name in {"embed", "embed_image"} and (
                len(body["vectors"]) != 1 or len(body["vectors"][0]) != body["dim"]
            ):
                raise RuntimeError("Invalid embedding dimensions")
            if name == "rerank" and (
                not body["hits"] or body["hits"][0]["image_id"] != rows[0]["image_id"]
            ):
                raise RuntimeError("Rerank selected the wrong entity")
            results.append(
                {
                    "endpoint": name,
                    "status": response.status_code,
                    "passed": True,
                    "server_ms": response.headers.get("X-Response-Time"),
                }
            )
        preflight = client.options(
            "/v1/search",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-api-key",
            },
        )
        assert preflight.status_code == 200
        results.append({"endpoint": "CORS preflight", "status": 200, "passed": True})
        if os.getenv("API_KEY_ENFORCE", "true").lower() == "true":
            assert client.post("/v1/search", json={"query": "test"}).status_code == 401
            results.append({"endpoint": "authentication", "status": 401, "passed": True})
    path = Path("reports/approved_run/api_checks.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
