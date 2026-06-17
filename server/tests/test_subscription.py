"""Tests for POST /subscription/verify + the D2 background re-validation.

The outbound Apple/Google validators are ALWAYS mocked — pytest never hits a
real store. We patch the validator functions where they are USED:
`api.routes_subscription.validate_{apple,google}` for the route,
`billing.revalidation.validate_{apple,google}` for the sweep.
"""

from __future__ import annotations

import asyncio
import sqlite3
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from auth.jwt_service import issue_token
from billing.models import BillingConfigError, ValidationResult
from config import Settings
from db.database import get_connection
from tests.conftest import register_user as _register_user

_IOS_BODY = {
    "platform": "ios",
    "product_id": "stt_weekly_199",
    "verification_data": "signed.jws.token",
}
_ANDROID_BODY = {
    "platform": "android",
    "product_id": "stt_weekly_199",
    "verification_data": "google-purchase-token-abc",
}


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _user_row(test_db_path: str, user_id: int) -> sqlite3.Row:
    conn = sqlite3.connect(test_db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()


def _purchase_rows(test_db_path: str) -> list[sqlite3.Row]:
    conn = sqlite3.connect(test_db_path)
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute("SELECT * FROM purchases ORDER BY id").fetchall())
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


def test_verify_requires_jwt(client: TestClient) -> None:
    """No Authorization header → 401 AUTH_UNAUTHORIZED (canonical shape)."""
    response = client.post("/subscription/verify", json=_IOS_BODY)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_verify_rejects_invalid_jwt(client: TestClient) -> None:
    response = client.post(
        "/subscription/verify", json=_IOS_BODY, headers=_auth_header("not.a.jwt")
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_verify_rejects_bad_body(client: TestClient, mock_resend, test_db_path) -> None:
    """A missing/garbage field → 422 (schema boundary), tier untouched."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)
    response = client.post(
        "/subscription/verify",
        json={"platform": "windows", "product_id": "x", "verification_data": "y"},
        headers=_auth_header(token),
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------
# Happy paths
# --------------------------------------------------------------------------


@patch("api.routes_subscription.validate_apple", new_callable=AsyncMock)
def test_verify_valid_ios_flips_to_paid(
    mock_validate: AsyncMock, client: TestClient, mock_resend, test_db_path
) -> None:
    mock_validate.return_value = ValidationResult(
        valid=True,
        status="valid",
        transaction_id="tx-123",
        expires_at="2026-06-23T00:00:00Z",
    )
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/subscription/verify", json=_IOS_BODY, headers=_auth_header(token)
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["tier"] == "paid"
    assert data["status"] == "valid"
    assert data["product_id"] == "stt_weekly_199"
    assert data["expires_at"] == "2026-06-23T00:00:00Z"

    user = _user_row(test_db_path, user_id)
    assert user["tier"] == "paid"
    assert user["tier_changed_at"] is not None

    rows = _purchase_rows(test_db_path)
    assert len(rows) == 1
    assert rows[0]["platform"] == "ios"
    assert rows[0]["validation_status"] == "valid"
    assert rows[0]["transaction_id"] == "tx-123"


@patch("api.routes_subscription.validate_google", new_callable=AsyncMock)
def test_verify_valid_android_flips_to_paid(
    mock_validate: AsyncMock, client: TestClient, mock_resend, test_db_path
) -> None:
    mock_validate.return_value = ValidationResult(
        valid=True, status="valid", transaction_id="GPA.1", expires_at=None
    )
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/subscription/verify", json=_ANDROID_BODY, headers=_auth_header(token)
    )

    assert response.status_code == 200
    assert response.json()["data"]["tier"] == "paid"
    assert _user_row(test_db_path, user_id)["tier"] == "paid"
    mock_validate.assert_awaited_once()


# --------------------------------------------------------------------------
# Failure / fallback paths
# --------------------------------------------------------------------------


@patch("api.routes_subscription.validate_apple", new_callable=AsyncMock)
def test_verify_invalid_keeps_free_and_402(
    mock_validate: AsyncMock, client: TestClient, mock_resend, test_db_path
) -> None:
    mock_validate.return_value = ValidationResult(
        valid=False, status="invalid", reason="verification_failed"
    )
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/subscription/verify", json=_IOS_BODY, headers=_auth_header(token)
    )

    assert response.status_code == 402
    assert response.json()["error"]["code"] == "PURCHASE_INVALID"
    # Tier untouched; the purchase is recorded as invalid for audit.
    assert _user_row(test_db_path, user_id)["tier"] == "free"
    rows = _purchase_rows(test_db_path)
    assert len(rows) == 1
    assert rows[0]["validation_status"] == "invalid"


@patch("api.routes_subscription.validate_google", new_callable=AsyncMock)
def test_verify_unreachable_optimistic_grant(
    mock_validate: AsyncMock, client: TestClient, mock_resend, test_db_path
) -> None:
    """D2 fallback — store unreachable → optimistic paid, purchase 'pending'."""
    mock_validate.return_value = ValidationResult(
        valid=False, status="unreachable", reason="api_5xx"
    )
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/subscription/verify", json=_ANDROID_BODY, headers=_auth_header(token)
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["tier"] == "paid"
    assert data["status"] == "pending"
    assert _user_row(test_db_path, user_id)["tier"] == "paid"
    rows = _purchase_rows(test_db_path)
    assert len(rows) == 1
    assert rows[0]["validation_status"] == "pending"


@patch("api.routes_subscription.validate_apple", new_callable=AsyncMock)
def test_verify_config_absent_returns_503(
    mock_validate: AsyncMock, client: TestClient, mock_resend, test_db_path
) -> None:
    """Missing store config = 503 SUBSCRIPTION_UNAVAILABLE — NOT an optimistic
    grant, NOT a 402. Tier untouched."""
    mock_validate.side_effect = BillingConfigError("APPLE_BUNDLE_ID not set")
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/subscription/verify", json=_IOS_BODY, headers=_auth_header(token)
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SUBSCRIPTION_UNAVAILABLE"
    assert _user_row(test_db_path, user_id)["tier"] == "free"


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


@patch("api.routes_subscription.validate_apple", new_callable=AsyncMock)
def test_verify_idempotent_no_double_flip(
    mock_validate: AsyncMock, client: TestClient, mock_resend, test_db_path
) -> None:
    """Re-POSTing the same valid artifact validates once, never double-inserts."""
    mock_validate.return_value = ValidationResult(
        valid=True, status="valid", transaction_id="tx-1", expires_at=None
    )
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    first = client.post(
        "/subscription/verify", json=_IOS_BODY, headers=_auth_header(token)
    )
    second = client.post(
        "/subscription/verify", json=_IOS_BODY, headers=_auth_header(token)
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["tier"] == "paid"
    assert second.json()["data"]["status"] == "valid"
    # Validated exactly once; the second hit the idempotency guard.
    mock_validate.assert_awaited_once()
    # Exactly one purchase row for the token — no duplicate 'valid' rows.
    rows = _purchase_rows(test_db_path)
    assert len(rows) == 1


# --------------------------------------------------------------------------
# D2 background re-validation (AC3)
# --------------------------------------------------------------------------


@patch("billing.revalidation.validate_google", new_callable=AsyncMock)
@patch("api.routes_subscription.validate_google", new_callable=AsyncMock)
def test_pending_revalidated_invalid_reverts_to_free(
    mock_route_validate: AsyncMock,
    mock_sweep_validate: AsyncMock,
    client: TestClient,
    mock_resend,
    test_db_path,
) -> None:
    """A 'pending' (optimistically-granted) purchase that later re-validates
    invalid reverts the user to 'free' and marks the purchase 'invalid' (AC3)."""
    from billing.revalidation import revalidate_pending_purchases

    # 1. Verify-time: store unreachable → optimistic paid + pending purchase.
    mock_route_validate.return_value = ValidationResult(
        valid=False, status="unreachable", reason="api_5xx"
    )
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)
    resp = client.post(
        "/subscription/verify", json=_ANDROID_BODY, headers=_auth_header(token)
    )
    assert resp.json()["data"]["status"] == "pending"
    assert _user_row(test_db_path, user_id)["tier"] == "paid"

    # 2. Background sweep re-validates the token as definitively invalid.
    mock_sweep_validate.return_value = ValidationResult(
        valid=False, status="invalid", reason="state:SUBSCRIPTION_STATE_EXPIRED"
    )

    async def _run() -> int:
        async with get_connection() as db:
            return await revalidate_pending_purchases(db, settings=Settings())

    resolved = asyncio.run(_run())

    assert resolved == 1
    reverted = _user_row(test_db_path, user_id)
    assert reverted["tier"] == "free"
    # F25/D3 — the paid->free revert MUST re-stamp tier_changed_at (Story 8.3's
    # free-tier lifetime call-count rework reads it).
    assert reverted["tier_changed_at"] is not None
    rows = _purchase_rows(test_db_path)
    assert rows[-1]["validation_status"] == "invalid"


@patch("billing.revalidation.validate_google", new_callable=AsyncMock)
@patch("api.routes_subscription.validate_google", new_callable=AsyncMock)
def test_pending_revalidated_unreachable_stays_pending(
    mock_route_validate: AsyncMock,
    mock_sweep_validate: AsyncMock,
    client: TestClient,
    mock_resend,
    test_db_path,
) -> None:
    """Still-unreachable on the sweep → purchase stays 'pending', tier stays
    paid (never spin a permanently-broken store)."""
    from billing.revalidation import revalidate_pending_purchases

    mock_route_validate.return_value = ValidationResult(
        valid=False, status="unreachable", reason="api_5xx"
    )
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)
    client.post("/subscription/verify", json=_ANDROID_BODY, headers=_auth_header(token))

    mock_sweep_validate.return_value = ValidationResult(
        valid=False, status="unreachable", reason="api_5xx"
    )

    async def _run() -> int:
        async with get_connection() as db:
            return await revalidate_pending_purchases(db, settings=Settings())

    resolved = asyncio.run(_run())

    assert resolved == 0
    assert _user_row(test_db_path, user_id)["tier"] == "paid"
    assert _purchase_rows(test_db_path)[-1]["validation_status"] == "pending"


@patch("billing.revalidation.validate_google", new_callable=AsyncMock)
@patch("api.routes_subscription.validate_google", new_callable=AsyncMock)
def test_pending_revalidated_valid_stays_paid(
    mock_route_validate: AsyncMock,
    mock_sweep_validate: AsyncMock,
    client: TestClient,
    mock_resend,
    test_db_path,
) -> None:
    """F22 — the sweep's pending→VALID arm: an optimistic grant the store later
    confirms is marked 'valid' and the user stays paid (resolved += 1)."""
    from billing.revalidation import revalidate_pending_purchases

    mock_route_validate.return_value = ValidationResult(
        valid=False, status="unreachable", reason="api_5xx"
    )
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)
    client.post("/subscription/verify", json=_ANDROID_BODY, headers=_auth_header(token))

    mock_sweep_validate.return_value = ValidationResult(
        valid=True, status="valid", transaction_id="GPA.9", expires_at=None
    )

    async def _run() -> int:
        async with get_connection() as db:
            return await revalidate_pending_purchases(db, settings=Settings())

    resolved = asyncio.run(_run())

    assert resolved == 1
    assert _user_row(test_db_path, user_id)["tier"] == "paid"
    assert _purchase_rows(test_db_path)[-1]["validation_status"] == "valid"


@patch("billing.revalidation.validate_google", new_callable=AsyncMock)
@patch("api.routes_subscription.validate_google", new_callable=AsyncMock)
def test_pending_invalid_keeps_paid_when_other_valid_purchase_exists(
    mock_route_validate: AsyncMock,
    mock_sweep_validate: AsyncMock,
    client: TestClient,
    mock_resend,
    test_db_path,
) -> None:
    """F2 — the sweep must NOT clobber a separately-entitled user. A stale
    'pending' row re-validating invalid keeps the user paid when they hold
    another 'valid' purchase; only that row is marked invalid."""
    from billing.revalidation import revalidate_pending_purchases

    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    # Purchase #1 — optimistic 'pending' grant (store unreachable at verify).
    mock_route_validate.return_value = ValidationResult(
        valid=False, status="unreachable", reason="api_5xx"
    )
    client.post(
        "/subscription/verify",
        json={**_ANDROID_BODY, "verification_data": "token-pending-1"},
        headers=_auth_header(token),
    )
    # Purchase #2 — a genuine confirmed 'valid' purchase (different artifact).
    mock_route_validate.return_value = ValidationResult(
        valid=True, status="valid", transaction_id="GPA.OK", expires_at=None
    )
    client.post(
        "/subscription/verify",
        json={**_ANDROID_BODY, "verification_data": "token-valid-2"},
        headers=_auth_header(token),
    )
    assert _user_row(test_db_path, user_id)["tier"] == "paid"

    # Sweep re-validates the pending #1 as definitively invalid.
    mock_sweep_validate.return_value = ValidationResult(
        valid=False, status="invalid", reason="state:SUBSCRIPTION_STATE_EXPIRED"
    )

    async def _run() -> int:
        async with get_connection() as db:
            return await revalidate_pending_purchases(db, settings=Settings())

    asyncio.run(_run())

    # The user KEEPS paid (purchase #2 still valid); only #1 is marked invalid.
    assert _user_row(test_db_path, user_id)["tier"] == "paid"
    rows = _purchase_rows(test_db_path)
    by_token = {r["verification_token"]: r["validation_status"] for r in rows}
    assert by_token["token-pending-1"] == "invalid"
    assert by_token["token-valid-2"] == "valid"


# --------------------------------------------------------------------------
# Cross-user replay + idempotency guard semantics (code-review 8.1 F6/F7)
# --------------------------------------------------------------------------


@patch("api.routes_subscription.validate_apple", new_callable=AsyncMock)
def test_verify_cross_user_token_replay_is_409(
    mock_validate: AsyncMock, client: TestClient, mock_resend, test_db_path
) -> None:
    """F7 — a token already recorded for user A must NOT entitle user B who
    replays it: 409 PURCHASE_CONFLICT, B stays free, no re-validation."""
    mock_validate.return_value = ValidationResult(
        valid=True, status="valid", transaction_id="tx-A", expires_at=None
    )
    user_a = _register_user(client, test_db_path, email="a@example.com")
    user_b = _register_user(client, test_db_path, email="b@example.com")

    # A buys.
    first = client.post(
        "/subscription/verify",
        json=_IOS_BODY,
        headers=_auth_header(issue_token(user_a)),
    )
    assert first.status_code == 200
    mock_validate.reset_mock()

    # B replays A's artifact.
    second = client.post(
        "/subscription/verify",
        json=_IOS_BODY,
        headers=_auth_header(issue_token(user_b)),
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "PURCHASE_CONFLICT"
    assert _user_row(test_db_path, user_b)["tier"] == "free"
    mock_validate.assert_not_awaited()  # short-circuited before re-validating


@patch("api.routes_subscription.validate_google", new_callable=AsyncMock)
def test_verify_pending_re_post_returns_pending_without_revalidating(
    mock_validate: AsyncMock, client: TestClient, mock_resend, test_db_path
) -> None:
    """F6 — re-POSTing a token still 'pending' (optimistic grant) returns the
    pending state WITHOUT a second insert or a second validator round-trip."""
    mock_validate.return_value = ValidationResult(
        valid=False, status="unreachable", reason="api_5xx"
    )
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    client.post("/subscription/verify", json=_ANDROID_BODY, headers=_auth_header(token))
    mock_validate.reset_mock()
    second = client.post(
        "/subscription/verify", json=_ANDROID_BODY, headers=_auth_header(token)
    )

    assert second.status_code == 200
    assert second.json()["data"]["status"] == "pending"
    mock_validate.assert_not_awaited()
    assert len(_purchase_rows(test_db_path)) == 1  # no duplicate row


@patch("api.routes_subscription.validate_apple", new_callable=AsyncMock)
def test_verify_invalid_re_post_is_402_without_revalidating(
    mock_validate: AsyncMock, client: TestClient, mock_resend, test_db_path
) -> None:
    """F6 — re-POSTing a token already recorded 'invalid' 402s WITHOUT a fresh
    validator call (stops unbounded re-POST validator amplification)."""
    mock_validate.return_value = ValidationResult(
        valid=False, status="invalid", reason="verification_failed"
    )
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    client.post("/subscription/verify", json=_IOS_BODY, headers=_auth_header(token))
    mock_validate.reset_mock()
    second = client.post(
        "/subscription/verify", json=_IOS_BODY, headers=_auth_header(token)
    )

    assert second.status_code == 402
    assert second.json()["error"]["code"] == "PURCHASE_INVALID"
    mock_validate.assert_not_awaited()
    assert len(_purchase_rows(test_db_path)) == 1
