"""Tests for the subscription lifecycle webhooks (Story 8.3, Task 5/D3).

Both store verifiers are mocked — pytest never crafts a real signed JWS nor
hits Google. We patch where each is USED:
`api.routes_subscription_webhooks.verify_apple_notification` /
`...validate_google`. The Google secret token is monkeypatched onto the
module-level `settings`. Idempotency + always-200-on-handled-error are asserted.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from billing import AppleNotification
from billing.models import ValidationResult


def _user_row(db_path: str, user_id: int) -> sqlite3.Row:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()


def _seed_paid_user_with_purchase(
    db_path: str,
    *,
    email: str,
    transaction_id: str = "txn-1",
    verification_token: str = "gtok-1",
    expires_at: str = "2099-01-01T00:00:00Z",
    original_transaction_id: str | None = None,
) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.execute(
        "INSERT INTO users(email, tier, created_at) "
        "VALUES (?, 'paid', '2026-06-18T00:00:00Z')",
        (email,),
    )
    user_id = cur.lastrowid
    conn.execute(
        "INSERT INTO purchases(user_id, platform, product_id, verification_token, "
        "transaction_id, original_transaction_id, validation_status, expires_at, "
        "created_at) "
        "VALUES (?, 'ios', 'stt_weekly_199', ?, ?, ?, 'valid', ?, "
        "'2026-06-18T00:00:00Z')",
        (
            user_id,
            verification_token,
            transaction_id,
            original_transaction_id,
            expires_at,
        ),
    )
    conn.commit()
    conn.close()
    assert user_id is not None
    return user_id


def _add_purchase(
    db_path: str,
    *,
    user_id: int,
    transaction_id: str,
    verification_token: str,
    expires_at: str,
    original_transaction_id: str | None = None,
    validation_status: str = "valid",
) -> None:
    """Add a SECOND purchase row to an existing user (multi-purchase F4 cases)."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO purchases(user_id, platform, product_id, verification_token, "
        "transaction_id, original_transaction_id, validation_status, expires_at, "
        "created_at) "
        "VALUES (?, 'ios', 'stt_weekly_199', ?, ?, ?, ?, ?, '2026-06-18T00:00:00Z')",
        (
            user_id,
            verification_token,
            transaction_id,
            original_transaction_id,
            validation_status,
            expires_at,
        ),
    )
    conn.commit()
    conn.close()


def _event_processed_at(db_path: str, notification_id: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT processed_at FROM subscription_events WHERE notification_id = ?",
            (notification_id,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _purchase_expiry(db_path: str, verification_token: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT expires_at FROM purchases WHERE verification_token = ?",
            (verification_token,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _event_count(db_path: str, notification_id: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM subscription_events WHERE notification_id = ?",
            (notification_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def _apple_notif(**kw) -> AppleNotification:
    base = dict(
        notification_type="EXPIRED",
        subtype=None,
        notification_uuid="uuid-1",
        transaction_id="txn-1",
        original_transaction_id=None,
        product_id="stt_weekly_199",
        expires_at=None,
        environment="Production",
    )
    base.update(kw)
    return AppleNotification(**base)


# ==========================================================================
# Apple
# ==========================================================================


@patch(
    "api.routes_subscription_webhooks.verify_apple_notification", new_callable=AsyncMock
)
def test_apple_expired_downgrades_user(
    mock_verify: AsyncMock, client: TestClient, test_db_path
) -> None:
    user_id = _seed_paid_user_with_purchase(test_db_path, email="exp@example.invalid")
    mock_verify.return_value = _apple_notif(
        notification_type="EXPIRED",
        notification_uuid="uuid-exp",
        transaction_id="txn-1",
    )

    resp = client.post("/subscription/webhook/apple", json={"signedPayload": "x.y.z"})

    assert resp.status_code == 200
    assert _user_row(test_db_path, user_id)["tier"] == "free"
    assert _event_count(test_db_path, "uuid-exp") == 1


@patch(
    "api.routes_subscription_webhooks.verify_apple_notification", new_callable=AsyncMock
)
def test_apple_did_renew_keeps_paid_and_refreshes_expiry(
    mock_verify: AsyncMock, client: TestClient, test_db_path
) -> None:
    user_id = _seed_paid_user_with_purchase(
        test_db_path, email="renew@example.invalid", expires_at="2026-01-01T00:00:00Z"
    )
    mock_verify.return_value = _apple_notif(
        notification_type="DID_RENEW",
        notification_uuid="uuid-renew",
        transaction_id="txn-1",
        expires_at="2099-07-18T00:00:00Z",
    )

    resp = client.post("/subscription/webhook/apple", json={"signedPayload": "x"})

    assert resp.status_code == 200
    assert _user_row(test_db_path, user_id)["tier"] == "paid"
    assert _purchase_expiry(test_db_path, "gtok-1") == "2099-07-18T00:00:00Z"


@patch(
    "api.routes_subscription_webhooks.verify_apple_notification", new_callable=AsyncMock
)
def test_apple_renewal_status_change_keeps_paid(
    mock_verify: AsyncMock, client: TestClient, test_db_path
) -> None:
    user_id = _seed_paid_user_with_purchase(
        test_db_path, email="cancel@example.invalid"
    )
    mock_verify.return_value = _apple_notif(
        notification_type="DID_CHANGE_RENEWAL_STATUS",
        subtype="AUTO_RENEW_DISABLED",
        notification_uuid="uuid-cancel",
        transaction_id="txn-1",
    )

    resp = client.post("/subscription/webhook/apple", json={"signedPayload": "x"})

    assert resp.status_code == 200
    # Cancellation intent — stays paid until expiry.
    assert _user_row(test_db_path, user_id)["tier"] == "paid"


@patch(
    "api.routes_subscription_webhooks.verify_apple_notification", new_callable=AsyncMock
)
def test_apple_forged_jws_rejected_no_tier_change(
    mock_verify: AsyncMock, client: TestClient, test_db_path
) -> None:
    from billing import AppleNotificationError

    user_id = _seed_paid_user_with_purchase(
        test_db_path, email="forged@example.invalid"
    )
    mock_verify.side_effect = AppleNotificationError("verification_failed")

    resp = client.post("/subscription/webhook/apple", json={"signedPayload": "forged"})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "WEBHOOK_INVALID"
    assert _user_row(test_db_path, user_id)["tier"] == "paid"  # untouched


@patch(
    "api.routes_subscription_webhooks.verify_apple_notification", new_callable=AsyncMock
)
def test_apple_config_absent_returns_503(
    mock_verify: AsyncMock, client: TestClient, test_db_path
) -> None:
    from billing import BillingConfigError

    mock_verify.side_effect = BillingConfigError("APPLE_BUNDLE_ID not set")

    resp = client.post("/subscription/webhook/apple", json={"signedPayload": "x"})

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SUBSCRIPTION_UNAVAILABLE"


@patch(
    "api.routes_subscription_webhooks.verify_apple_notification", new_callable=AsyncMock
)
def test_apple_replay_is_noop(
    mock_verify: AsyncMock, client: TestClient, test_db_path
) -> None:
    """Re-posting the same notificationUUID is a no-op (dedup ledger)."""
    user_id = _seed_paid_user_with_purchase(
        test_db_path, email="replay@example.invalid"
    )
    mock_verify.return_value = _apple_notif(
        notification_type="EXPIRED",
        notification_uuid="uuid-replay",
        transaction_id="txn-1",
    )

    first = client.post("/subscription/webhook/apple", json={"signedPayload": "x"})
    assert first.status_code == 200
    assert _user_row(test_db_path, user_id)["tier"] == "free"

    # Re-grant paid out-of-band, then replay the SAME notification.
    conn = sqlite3.connect(test_db_path)
    conn.execute("UPDATE users SET tier = 'paid' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    second = client.post("/subscription/webhook/apple", json={"signedPayload": "x"})
    assert second.status_code == 200
    # The replay did NOT re-process → tier stays paid (not re-downgraded).
    assert _user_row(test_db_path, user_id)["tier"] == "paid"
    assert _event_count(test_db_path, "uuid-replay") == 1


@patch(
    "api.routes_subscription_webhooks.verify_apple_notification", new_callable=AsyncMock
)
def test_apple_unknown_transaction_acks_200(
    mock_verify: AsyncMock, client: TestClient, test_db_path
) -> None:
    mock_verify.return_value = _apple_notif(
        notification_type="EXPIRED",
        notification_uuid="uuid-unknown",
        transaction_id="txn-NOT-IN-DB",
    )

    resp = client.post("/subscription/webhook/apple", json={"signedPayload": "x"})

    assert resp.status_code == 200  # ack, not an error


# ==========================================================================
# Google
# ==========================================================================

_GOOGLE_SECRET = "s3cret-pubsub-token"


def _google_envelope(
    notification_type: int, purchase_token: str, message_id: str
) -> dict:
    inner = {
        "packageName": "com.surviveTheTalk.client",
        "subscriptionNotification": {
            "notificationType": notification_type,
            "purchaseToken": purchase_token,
            "subscriptionId": "stt_weekly_199",
        },
    }
    data_b64 = base64.b64encode(json.dumps(inner).encode()).decode()
    return {"message": {"data": data_b64, "messageId": message_id}}


@pytest.fixture
def google_secret(monkeypatch):
    """Configure the Google webhook secret token on the module-level settings."""
    import api.routes_subscription_webhooks as mod

    monkeypatch.setattr(
        mod.settings, "google_pubsub_verification_token", _GOOGLE_SECRET
    )
    return _GOOGLE_SECRET


def test_google_unconfigured_token_returns_503(
    client: TestClient, test_db_path
) -> None:
    """No secret configured → 503 (refuse unauthenticated push)."""
    resp = client.post(
        "/subscription/webhook/google",
        json=_google_envelope(13, "gtok-1", "msg-1"),
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "SUBSCRIPTION_UNAVAILABLE"


def test_google_bad_token_returns_403(
    client: TestClient, test_db_path, google_secret
) -> None:
    resp = client.post(
        "/subscription/webhook/google?token=wrong",
        json=_google_envelope(13, "gtok-1", "msg-bad"),
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "WEBHOOK_FORBIDDEN"


def test_google_missing_token_returns_403(
    client: TestClient, test_db_path, google_secret
) -> None:
    resp = client.post(
        "/subscription/webhook/google",
        json=_google_envelope(13, "gtok-1", "msg-none"),
    )
    assert resp.status_code == 403


@patch("api.routes_subscription_webhooks.validate_google", new_callable=AsyncMock)
def test_google_expired_downgrades(
    mock_validate: AsyncMock, client: TestClient, test_db_path, google_secret
) -> None:
    user_id = _seed_paid_user_with_purchase(
        test_db_path, email="gexp@example.invalid", verification_token="gtok-exp"
    )
    mock_validate.return_value = ValidationResult(
        valid=False, status="invalid", reason="expired"
    )

    resp = client.post(
        f"/subscription/webhook/google?token={_GOOGLE_SECRET}",
        json=_google_envelope(13, "gtok-exp", "msg-exp"),
    )

    assert resp.status_code == 200
    assert _user_row(test_db_path, user_id)["tier"] == "free"
    mock_validate.assert_awaited_once()


@patch("api.routes_subscription_webhooks.validate_google", new_callable=AsyncMock)
def test_google_renewed_keeps_paid_and_refreshes_expiry(
    mock_validate: AsyncMock, client: TestClient, test_db_path, google_secret
) -> None:
    user_id = _seed_paid_user_with_purchase(
        test_db_path,
        email="gren@example.invalid",
        verification_token="gtok-ren",
        expires_at="2026-01-01T00:00:00Z",
    )
    mock_validate.return_value = ValidationResult(
        valid=True,
        status="valid",
        transaction_id="GPA.9",
        expires_at="2099-09-09T00:00:00Z",
    )

    resp = client.post(
        f"/subscription/webhook/google?token={_GOOGLE_SECRET}",
        json=_google_envelope(2, "gtok-ren", "msg-ren"),
    )

    assert resp.status_code == 200
    assert _user_row(test_db_path, user_id)["tier"] == "paid"
    assert _purchase_expiry(test_db_path, "gtok-ren") == "2099-09-09T00:00:00Z"


@patch("api.routes_subscription_webhooks.validate_google", new_callable=AsyncMock)
def test_google_duplicate_message_id_is_noop(
    mock_validate: AsyncMock, client: TestClient, test_db_path, google_secret
) -> None:
    user_id = _seed_paid_user_with_purchase(
        test_db_path, email="gdup@example.invalid", verification_token="gtok-dup"
    )
    mock_validate.return_value = ValidationResult(
        valid=False, status="invalid", reason="expired"
    )

    first = client.post(
        f"/subscription/webhook/google?token={_GOOGLE_SECRET}",
        json=_google_envelope(13, "gtok-dup", "msg-dup"),
    )
    assert first.status_code == 200
    assert _user_row(test_db_path, user_id)["tier"] == "free"

    # Re-grant paid, replay SAME messageId → no re-process.
    conn = sqlite3.connect(test_db_path)
    conn.execute("UPDATE users SET tier = 'paid' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    mock_validate.reset_mock()

    second = client.post(
        f"/subscription/webhook/google?token={_GOOGLE_SECRET}",
        json=_google_envelope(13, "gtok-dup", "msg-dup"),
    )
    assert second.status_code == 200
    assert _user_row(test_db_path, user_id)["tier"] == "paid"
    mock_validate.assert_not_awaited()  # dedup short-circuited before re-validate


@patch("api.routes_subscription_webhooks.validate_google", new_callable=AsyncMock)
def test_google_unknown_token_acks_without_validating(
    mock_validate: AsyncMock, client: TestClient, test_db_path, google_secret
) -> None:
    resp = client.post(
        f"/subscription/webhook/google?token={_GOOGLE_SECRET}",
        json=_google_envelope(13, "gtok-NOT-IN-DB", "msg-unknown"),
    )
    assert resp.status_code == 200
    mock_validate.assert_not_awaited()  # returned before re-validating


@patch("api.routes_subscription_webhooks.validate_google", new_callable=AsyncMock)
def test_google_processing_error_retries_and_redrives(
    mock_validate: AsyncMock, client: TestClient, test_db_path, google_secret
) -> None:
    """F1 — a transient processing failure must NOT be permanently swallowed.

    First delivery raises mid-processing → the route returns 500 (so Pub/Sub
    retries) and the dedup row is left UNPROCESSED (processed_at NULL), tier
    unchanged. A retry of the SAME messageId then RE-PROCESSES (re-drives) and
    applies the downgrade — proving the failed event is recoverable, not lost.
    """
    user_id = _seed_paid_user_with_purchase(
        test_db_path, email="gerr@example.invalid", verification_token="gtok-err"
    )
    mock_validate.side_effect = RuntimeError("boom")

    first = client.post(
        f"/subscription/webhook/google?token={_GOOGLE_SECRET}",
        json=_google_envelope(13, "gtok-err", "msg-err"),
    )
    assert first.status_code == 500
    assert first.json()["error"]["code"] == "WEBHOOK_PROCESSING_FAILED"
    assert _user_row(test_db_path, user_id)["tier"] == "paid"  # unchanged
    assert _event_count(test_db_path, "msg-err") == 1  # recorded for audit
    assert _event_processed_at(test_db_path, "msg-err") is None  # NOT processed

    # Pub/Sub retries the SAME messageId; this time validation succeeds.
    mock_validate.side_effect = None
    mock_validate.return_value = ValidationResult(
        valid=False, status="invalid", reason="expired"
    )
    second = client.post(
        f"/subscription/webhook/google?token={_GOOGLE_SECRET}",
        json=_google_envelope(13, "gtok-err", "msg-err"),
    )
    assert second.status_code == 200
    # Re-drive happened: the downgrade was applied and the event is now processed.
    assert _user_row(test_db_path, user_id)["tier"] == "free"
    assert _event_processed_at(test_db_path, "msg-err") is not None


@patch(
    "api.routes_subscription_webhooks.verify_apple_notification", new_callable=AsyncMock
)
def test_apple_processing_error_returns_500_and_leaves_event_unprocessed(
    mock_verify: AsyncMock, client: TestClient, test_db_path
) -> None:
    """F1 (Apple side) — a processing failure returns 500 (store retries) and the
    dedup row stays unprocessed so a retry can re-drive it."""
    user_id = _seed_paid_user_with_purchase(test_db_path, email="aerr@example.invalid")
    mock_verify.return_value = _apple_notif(
        notification_type="DID_RENEW",
        notification_uuid="uuid-aerr",
        transaction_id="txn-1",
        expires_at="2099-12-31T00:00:00Z",
    )

    with patch(
        "api.routes_subscription_webhooks.update_user_tier",
        new_callable=AsyncMock,
        side_effect=RuntimeError("db hiccup"),
    ):
        resp = client.post("/subscription/webhook/apple", json={"signedPayload": "x"})

    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "WEBHOOK_PROCESSING_FAILED"
    assert _event_count(test_db_path, "uuid-aerr") == 1
    assert _event_processed_at(test_db_path, "uuid-aerr") is None
    # user untouched (the BEGIN IMMEDIATE rolled back)
    assert _user_row(test_db_path, user_id)["tier"] == "paid"


# --- F3: Apple resolves renewals by the renewal-STABLE originalTransactionId ---


@patch(
    "api.routes_subscription_webhooks.verify_apple_notification", new_callable=AsyncMock
)
def test_apple_did_renew_resolves_by_original_txn_id(
    mock_verify: AsyncMock, client: TestClient, test_db_path
) -> None:
    """A real auto-renewal carries a NEW transactionId but the SAME
    originalTransactionId. Resolving by the stable id must find the purchase,
    refresh the expiry, and keep the user paid (without it, the sweep would later
    downgrade a paying subscriber)."""
    user_id = _seed_paid_user_with_purchase(
        test_db_path,
        email="renewstable@example.invalid",
        transaction_id="txn-orig",
        original_transaction_id="orig-1",
        expires_at="2026-01-01T00:00:00Z",
    )
    mock_verify.return_value = _apple_notif(
        notification_type="DID_RENEW",
        notification_uuid="uuid-renew-new",
        transaction_id="txn-RENEWAL-2",  # NEW per-period id, not in the DB
        original_transaction_id="orig-1",  # stable across renewals
        expires_at="2099-07-18T00:00:00Z",
    )

    resp = client.post("/subscription/webhook/apple", json={"signedPayload": "x"})

    assert resp.status_code == 200
    assert _user_row(test_db_path, user_id)["tier"] == "paid"
    assert _purchase_expiry(test_db_path, "gtok-1") == "2099-07-18T00:00:00Z"


@patch(
    "api.routes_subscription_webhooks.verify_apple_notification", new_callable=AsyncMock
)
def test_apple_refund_on_renewed_sub_resolves_by_original_txn_id(
    mock_verify: AsyncMock, client: TestClient, test_db_path
) -> None:
    """A REFUND/REVOKE on a renewed sub carries the renewal's NEW transactionId;
    resolving by originalTransactionId must still find + downgrade the user."""
    user_id = _seed_paid_user_with_purchase(
        test_db_path,
        email="refundstable@example.invalid",
        transaction_id="txn-orig",
        original_transaction_id="orig-2",
    )
    mock_verify.return_value = _apple_notif(
        notification_type="REVOKE",
        notification_uuid="uuid-revoke-new",
        transaction_id="txn-RENEWAL-9",
        original_transaction_id="orig-2",
    )

    resp = client.post("/subscription/webhook/apple", json={"signedPayload": "x"})

    assert resp.status_code == 200
    assert _user_row(test_db_path, user_id)["tier"] == "free"


# --- F4: a downgrade must not clobber a user entitled via ANOTHER purchase -----


@patch(
    "api.routes_subscription_webhooks.verify_apple_notification", new_callable=AsyncMock
)
def test_apple_expired_keeps_paid_when_other_valid_purchase_exists(
    mock_verify: AsyncMock, client: TestClient, test_db_path
) -> None:
    """A user who re-subscribed on a new device holds a SECOND valid+future
    purchase. An EXPIRED notification for the OLD subscription must NOT downgrade
    them — they are still entitled via the new one (mirror the Google path)."""
    user_id = _seed_paid_user_with_purchase(
        test_db_path,
        email="multi@example.invalid",
        transaction_id="txn-old",
        verification_token="gtok-old",
        original_transaction_id="orig-old",
        expires_at="2026-01-01T00:00:00Z",  # the lapsing one
    )
    _add_purchase(
        test_db_path,
        user_id=user_id,
        transaction_id="txn-new",
        verification_token="gtok-new",
        original_transaction_id="orig-new",
        expires_at="2099-09-09T00:00:00Z",  # still active
    )
    mock_verify.return_value = _apple_notif(
        notification_type="EXPIRED",
        notification_uuid="uuid-old-exp",
        transaction_id="txn-old",
        original_transaction_id="orig-old",
    )

    resp = client.post("/subscription/webhook/apple", json={"signedPayload": "x"})

    assert resp.status_code == 200
    # Still entitled via the new-device purchase → stays paid.
    assert _user_row(test_db_path, user_id)["tier"] == "paid"
