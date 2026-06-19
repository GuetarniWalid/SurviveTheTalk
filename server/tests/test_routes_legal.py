"""Tests for the public legal routes (Story 10.1, Task 3/6).

`GET /legal/privacy` and `GET /legal/terms` are the ONLY browser-facing routes:
raw HTML, NO auth, deliberately outside the `{data, meta}` envelope. These tests
lock the public-contract (200 + text/html, no token needed), the load-bearing
factual strings (so a future edit can't silently drop the AI disclosure / a
sub-processor name / the subscription terms), and the 404 negative path.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_privacy_page_is_public_html(client: TestClient) -> None:
    """No Authorization header → 200 + HTML (public route, no envelope)."""
    response = client.get("/legal/privacy")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    # Not the JSON envelope.
    assert response.text.lstrip().startswith("<!DOCTYPE html>")


def test_privacy_page_contains_ai_disclosure_and_subprocessors(
    client: TestClient,
) -> None:
    """AC2/AC3 — the AI disclosure + at least one REAL current sub-processor."""
    body = client.get("/legal/privacy").text
    assert "AI-generated" in body
    # Real current sub-processors (not the stale Cartesia-only / OpenRouter list).
    assert "Soniox" in body
    assert "Groq" in body
    # The process-and-discard / no-biometric assertions (AC5/NFR10).
    assert "never stored" in body
    assert "biometric" in body


def test_terms_page_is_public_html(client: TestClient) -> None:
    response = client.get("/legal/terms")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.lstrip().startswith("<!DOCTYPE html>")


def test_terms_page_contains_subscription_terms(client: TestClient) -> None:
    """AC4 — build-accurate subscription terms (price, auto-renew, age)."""
    body = client.get("/legal/terms").text
    assert "$1.99" in body
    assert "auto-renew" in body.lower()  # "auto-renewable"
    assert "stt_weekly_199" in body
    assert "13" in body  # age restriction


def test_legal_pages_reachable_without_auth(client: TestClient) -> None:
    """Both pages answer 200 with NO Authorization header at all."""
    assert client.get("/legal/privacy").status_code == 200
    assert client.get("/legal/terms").status_code == 200


def test_unknown_legal_path_returns_404(client: TestClient) -> None:
    """Negative path — an unknown /legal/<x> is a clean 404, not a 500/blank 200.

    An unmatched route is resolved by Starlette's router default (a plain 404),
    not our raised-HTTPException envelope handler — so we assert the status only,
    which is exactly what the store/smoke-gate cares about.
    """
    response = client.get("/legal/does-not-exist")
    assert response.status_code == 404
