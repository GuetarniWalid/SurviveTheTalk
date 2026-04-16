"""GET /health returns the standard envelope and confirms DB reachability."""

from __future__ import annotations


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"status": "ok", "db": "ok"}
    assert "timestamp" in body["meta"]
