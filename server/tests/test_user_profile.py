"""Tests for `GET /user/profile` (Story 8.3, AC5/D5).

The steady-state subscription-status read used by the Manage-Subscription
screen. No store I/O — purely reads `users.tier` + `compute_call_usage` +
the latest valid-purchase expiry. We seed the DB via raw SQL (the auth flow
mints the user; raw INSERTs set the tier + purchase rows).
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from auth.jwt_service import issue_token
from tests.conftest import register_user as _register_user


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _set_tier(db_path: str, user_id: int, tier: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user_id))
    conn.commit()
    conn.close()


def _insert_purchase(
    db_path: str,
    user_id: int,
    *,
    validation_status: str = "valid",
    expires_at: str | None = None,
    verification_token: str = "tok-1",
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO purchases(user_id, platform, product_id, verification_token, "
        "validation_status, expires_at, created_at) "
        "VALUES (?, 'ios', 'stt_weekly_199', ?, ?, ?, '2026-06-18T00:00:00Z')",
        (user_id, verification_token, validation_status, expires_at),
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


def test_profile_requires_jwt(client: TestClient) -> None:
    response = client.get("/user/profile")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_profile_rejects_invalid_jwt(client: TestClient) -> None:
    response = client.get("/user/profile", headers=_auth_header("not.a.jwt"))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


# --------------------------------------------------------------------------
# Happy paths
# --------------------------------------------------------------------------


def test_profile_free_user(client: TestClient, mock_resend, test_db_path) -> None:
    """Free user → tier 'free', full lifetime cap, no expiry."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.get("/user/profile", headers=_auth_header(token))

    assert response.status_code == 200
    body = response.json()
    assert "meta" in body and "timestamp" in body["meta"]
    data = body["data"]
    assert data["tier"] == "free"
    assert data["calls_remaining"] == 3
    assert data["calls_per_period"] == 3
    assert data["period"] == "lifetime"
    assert data["subscription_expires_at"] is None


def test_profile_paid_user_echoes_expiry(
    client: TestClient, mock_resend, test_db_path
) -> None:
    """Paid user with a valid future-dated purchase → tier 'paid', day period,
    expiry echoed from the purchase row."""
    user_id = _register_user(client, test_db_path)
    _set_tier(test_db_path, user_id, "paid")
    _insert_purchase(
        test_db_path,
        user_id,
        validation_status="valid",
        expires_at="2099-07-18T00:00:00Z",
    )
    token = issue_token(user_id)

    response = client.get("/user/profile", headers=_auth_header(token))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["tier"] == "paid"
    assert data["period"] == "day"
    assert data["subscription_expires_at"] == "2099-07-18T00:00:00Z"


def test_profile_paid_user_picks_latest_valid_expiry(
    client: TestClient, mock_resend, test_db_path
) -> None:
    """Multiple valid purchases → the LATEST expiry is returned; an 'invalid'
    row is ignored even if dated later."""
    user_id = _register_user(client, test_db_path)
    _set_tier(test_db_path, user_id, "paid")
    _insert_purchase(
        test_db_path,
        user_id,
        validation_status="valid",
        expires_at="2099-01-01T00:00:00Z",
        verification_token="tok-early",
    )
    _insert_purchase(
        test_db_path,
        user_id,
        validation_status="valid",
        expires_at="2099-07-18T00:00:00Z",
        verification_token="tok-late",
    )
    # An invalid row dated even later must NOT be picked.
    _insert_purchase(
        test_db_path,
        user_id,
        validation_status="invalid",
        expires_at="2099-12-31T00:00:00Z",
        verification_token="tok-invalid",
    )
    token = issue_token(user_id)

    response = client.get("/user/profile", headers=_auth_header(token))

    assert response.json()["data"]["subscription_expires_at"] == "2099-07-18T00:00:00Z"


def test_profile_paid_user_no_expiry_row_is_null(
    client: TestClient, mock_resend, test_db_path
) -> None:
    """A paid user whose only valid purchase has NULL expires_at → null (the
    field is meaningful, never fabricated)."""
    user_id = _register_user(client, test_db_path)
    _set_tier(test_db_path, user_id, "paid")
    _insert_purchase(test_db_path, user_id, validation_status="valid", expires_at=None)
    token = issue_token(user_id)

    response = client.get("/user/profile", headers=_auth_header(token))

    assert response.json()["data"]["subscription_expires_at"] is None
