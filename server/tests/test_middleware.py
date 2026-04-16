"""Exercises every branch of `require_auth` against a test-only protected route.

The fixture `protected_client` mounts a single `/_test_protected` route on a
throwaway FastAPI app so the production app stays untouched.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

JWT_SECRET = "0" * 32  # matches conftest.TEST_ENV_VARS


def _make_token(user_id: int = 1, exp_delta: timedelta = timedelta(hours=1)) -> str:
    payload = {"user_id": user_id, "exp": datetime.now(UTC) + exp_delta}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def test_require_auth_missing_header(protected_client):
    response = protected_client.get("/_test_protected")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_require_auth_bad_scheme(protected_client):
    response = protected_client.get(
        "/_test_protected", headers={"Authorization": "Basic xxx"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_require_auth_empty_bearer(protected_client):
    """`Authorization: Bearer ` (empty token) → 401, not 500."""
    response = protected_client.get(
        "/_test_protected", headers={"Authorization": "Bearer "}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_require_auth_bool_user_id_rejected(protected_client):
    """Forged token with `user_id: true` must NOT resolve to user #1."""
    payload = {"user_id": True, "exp": datetime.now(UTC) + timedelta(hours=1)}
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    response = protected_client.get(
        "/_test_protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_require_auth_string_user_id_rejected(protected_client):
    """Token with `user_id: "1"` (string) must 401 — we require int."""
    payload = {"user_id": "1", "exp": datetime.now(UTC) + timedelta(hours=1)}
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    response = protected_client.get(
        "/_test_protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_require_auth_token_without_exp_rejected(protected_client):
    """Token missing the `exp` claim must 401 (we set require=['exp'])."""
    token = jwt.encode({"user_id": 1}, JWT_SECRET, algorithm="HS256")
    response = protected_client.get(
        "/_test_protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_require_auth_tampered(protected_client):
    bad = _make_token() + "tampered"
    response = protected_client.get(
        "/_test_protected", headers={"Authorization": f"Bearer {bad}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_require_auth_expired(protected_client, test_db_path):
    # Insert a real user so the only failure mode left is expiry.
    import sqlite3

    conn = sqlite3.connect(test_db_path)
    conn.execute(
        "INSERT INTO users(email, tier, created_at) VALUES "
        "('walid@example.com', 'free', '2026-04-16T10:00:00Z')"
    )
    conn.commit()
    user_id = conn.execute(
        "SELECT id FROM users WHERE email = 'walid@example.com'"
    ).fetchone()[0]
    conn.close()

    expired = _make_token(user_id=user_id, exp_delta=timedelta(seconds=-10))
    response = protected_client.get(
        "/_test_protected", headers={"Authorization": f"Bearer {expired}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_TOKEN_EXPIRED"


def test_require_auth_user_not_in_db(protected_client):
    """Valid signature but user_id has no row → 401 AUTH_UNAUTHORIZED."""
    token = _make_token(user_id=999_999)
    response = protected_client.get(
        "/_test_protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_require_auth_valid(protected_client, test_db_path):
    import sqlite3

    conn = sqlite3.connect(test_db_path)
    conn.execute(
        "INSERT INTO users(email, tier, created_at) VALUES "
        "('walid@example.com', 'free', '2026-04-16T10:00:00Z')"
    )
    conn.commit()
    user_id = conn.execute(
        "SELECT id FROM users WHERE email = 'walid@example.com'"
    ).fetchone()[0]
    conn.close()

    token = _make_token(user_id=user_id)
    response = protected_client.get(
        "/_test_protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["data"]["user_id"] == user_id
