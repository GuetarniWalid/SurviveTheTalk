"""Sanity checks for the uniform `{data, meta}` / `{error}` JSON envelope."""

from __future__ import annotations


def test_response_envelope_on_validation_error(client, mock_resend):
    response = client.post("/auth/request-code", json={"email": "not-an-email"})
    assert response.status_code == 422
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "message" in body["error"]
    # Pydantic detail is exposed for debugging.
    assert "errors" in body["error"]["detail"]


def test_success_envelope_shape(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"data", "meta"}
    assert "timestamp" in body["meta"]
    # Trailing-Z, no microseconds, no offset.
    ts = body["meta"]["timestamp"]
    assert ts.endswith("Z")
    assert "." not in ts
    assert "+" not in ts
