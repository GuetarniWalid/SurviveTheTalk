"""GET /health returns the standard envelope and confirms DB reachability."""

from __future__ import annotations


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["status"] == "ok"
    assert body["data"]["db"] == "ok"
    # `git_sha` is read from `server/.git_sha` at import time. In the test
    # environment there is no such file, so the module falls back to
    # "unknown". The key must still be present so the CI workflow's
    # post-restart healthcheck can parse and compare it.
    assert "git_sha" in body["data"]
    assert "timestamp" in body["meta"]
