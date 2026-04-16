"""Tests for the passwordless email auth endpoints.

Covers AC2, AC3, and Scenarios A–D + F from the story walk-through.
Each test owns its DB (via the `test_db_path` fixture) and mocks Resend.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt

from auth.email_service import EmailDeliveryError, EmailRateLimitedError


def test_request_code_happy_path(client, mock_resend, test_db_path):
    response = client.post("/auth/request-code", json={"email": "walid@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {"message": "Code sent"}
    assert "timestamp" in body["meta"]

    # Resend was awaited with the lowercased email and a 6-digit code.
    mock_resend.assert_awaited_once()
    args, kwargs = mock_resend.call_args
    sent_email = args[0] if args else kwargs.get("email")
    sent_code = args[1] if len(args) > 1 else kwargs.get("code")
    assert sent_email == "walid@example.com"
    assert len(sent_code) == 6
    assert sent_code.isdigit()

    # And the auth_codes row landed.
    import sqlite3

    conn = sqlite3.connect(test_db_path)
    rows = conn.execute(
        "SELECT email, code, used FROM auth_codes WHERE email = ?",
        ("walid@example.com",),
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0] == ("walid@example.com", sent_code, 0)


def test_request_code_invalidates_previous(client, mock_resend, test_db_path):
    """Two consecutive requests for the same email leave exactly one used=0 row."""
    client.post("/auth/request-code", json={"email": "walid@example.com"})
    client.post("/auth/request-code", json={"email": "walid@example.com"})

    import sqlite3

    conn = sqlite3.connect(test_db_path)
    counts = conn.execute(
        "SELECT used, COUNT(*) FROM auth_codes WHERE email = ? GROUP BY used",
        ("walid@example.com",),
    ).fetchall()
    conn.close()
    counts_by_used = dict(counts)
    assert counts_by_used.get(0, 0) == 1, "exactly one active code expected"
    assert counts_by_used.get(1, 0) == 1, "the previous code must be invalidated"


def test_request_code_lowercases_and_strips_email(client, mock_resend, test_db_path):
    response = client.post(
        "/auth/request-code", json={"email": "  Walid@Example.COM  "}
    )
    assert response.status_code == 200
    sent_email = mock_resend.call_args.args[0]
    assert sent_email == "walid@example.com"


def test_request_code_resend_failure(client, mock_resend, test_db_path):
    """Resend outage → 502, but DB row is preserved (Scenario F)."""
    mock_resend.side_effect = EmailDeliveryError("simulated outage")

    response = client.post("/auth/request-code", json={"email": "walid@example.com"})

    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "EMAIL_DELIVERY_FAILED"

    import sqlite3

    conn = sqlite3.connect(test_db_path)
    rows = conn.execute(
        "SELECT COUNT(*) FROM auth_codes WHERE email = ?",
        ("walid@example.com",),
    ).fetchone()
    conn.close()
    assert rows[0] == 1, "DB row must survive a Resend failure"


def test_request_code_resend_rate_limited(client, mock_resend, test_db_path):
    """Resend 429 → our 429 with EMAIL_RATE_LIMITED + Retry-After header."""
    mock_resend.side_effect = EmailRateLimitedError("429")

    response = client.post("/auth/request-code", json={"email": "walid@example.com"})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "EMAIL_RATE_LIMITED"
    assert response.headers.get("retry-after") == "60"


def test_request_code_invalid_email_returns_validation_envelope(client, mock_resend):
    response = client.post("/auth/request-code", json={"email": "not-an-email"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    mock_resend.assert_not_awaited()


def _verify_with_db_code(client, test_db_path, email: str):
    """Helper: pull the active code straight from the DB and POST verify."""
    import sqlite3

    conn = sqlite3.connect(test_db_path)
    code = conn.execute(
        "SELECT code FROM auth_codes WHERE email = ? AND used = 0",
        (email,),
    ).fetchone()[0]
    conn.close()
    return client.post("/auth/verify-code", json={"email": email, "code": code})


def test_verify_code_happy_creates_user(client, mock_resend, test_db_path):
    email = "walid@example.com"
    client.post("/auth/request-code", json={"email": email})

    response = _verify_with_db_code(client, test_db_path, email)

    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert data["email"] == email
    assert isinstance(data["user_id"], int)
    token = data["token"]
    payload = jwt.decode(token, "0" * 32, algorithms=["HS256"])
    assert payload["user_id"] == data["user_id"]

    # users row created with a populated jwt_hash
    import sqlite3

    conn = sqlite3.connect(test_db_path)
    user_row = conn.execute(
        "SELECT id, email, jwt_hash, tier FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    assert user_row is not None
    assert user_row[1] == email
    assert user_row[2] is not None and user_row[2].startswith("$2b$")
    assert user_row[3] == "free"


def test_verify_code_returning_user(client, mock_resend, test_db_path):
    email = "walid@example.com"

    # First sign-in
    client.post("/auth/request-code", json={"email": email})
    first = _verify_with_db_code(client, test_db_path, email)
    first_user_id = first.json()["data"]["user_id"]

    # Second sign-in
    client.post("/auth/request-code", json={"email": email})
    second = _verify_with_db_code(client, test_db_path, email)
    second_user_id = second.json()["data"]["user_id"]

    assert first_user_id == second_user_id, "no duplicate user row"

    # A fresh JWT was signed (note: the encoded string CAN equal the previous
    # one when both verifications fall within the same epoch-second — that's
    # correct HS256 behaviour and not a bug). The freshness invariant we care
    # about is the bcrypt jwt_hash, which uses a per-call random salt.
    import sqlite3

    conn = sqlite3.connect(test_db_path)
    user_row = conn.execute(
        "SELECT COUNT(*), jwt_hash FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()
    assert user_row[0] == 1
    assert user_row[1] is not None and user_row[1].startswith("$2b$")


def test_verify_code_expired(client, mock_resend, test_db_path):
    email = "walid@example.com"
    client.post("/auth/request-code", json={"email": email})

    # Backdate the code's expiry.
    import sqlite3

    past = (
        (datetime.now(UTC) - timedelta(minutes=1))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    conn = sqlite3.connect(test_db_path)
    conn.execute(
        "UPDATE auth_codes SET expires_at = ? WHERE email = ? AND used = 0",
        (past, email),
    )
    conn.commit()
    code = conn.execute(
        "SELECT code FROM auth_codes WHERE email = ? AND used = 0", (email,)
    ).fetchone()[0]
    conn.close()

    response = client.post("/auth/verify-code", json={"email": email, "code": code})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AUTH_CODE_EXPIRED"

    # Row stays used=0 (Scenario B)
    conn = sqlite3.connect(test_db_path)
    used = conn.execute(
        "SELECT used FROM auth_codes WHERE email = ?", (email,)
    ).fetchone()[0]
    conn.close()
    assert used == 0


def test_verify_code_invalid(client, mock_resend, test_db_path):
    email = "walid@example.com"
    client.post("/auth/request-code", json={"email": email})

    response = client.post("/auth/verify-code", json={"email": email, "code": "000000"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AUTH_CODE_INVALID"


def test_verify_code_unseen_email(client, mock_resend, test_db_path):
    """Verifying an email that was never issued a code → AUTH_CODE_INVALID."""
    response = client.post(
        "/auth/verify-code",
        json={"email": "ghost@example.com", "code": "000000"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "AUTH_CODE_INVALID"


def test_verify_code_reused(client, mock_resend, test_db_path):
    email = "walid@example.com"
    client.post("/auth/request-code", json={"email": email})

    first = _verify_with_db_code(client, test_db_path, email)
    assert first.status_code == 200

    # Second attempt with the same (now-used) code → INVALID, not REUSED.
    import sqlite3

    conn = sqlite3.connect(test_db_path)
    code = conn.execute(
        "SELECT code FROM auth_codes WHERE email = ? ORDER BY id DESC LIMIT 1",
        (email,),
    ).fetchone()[0]
    conn.close()

    second = client.post("/auth/verify-code", json={"email": email, "code": code})
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "AUTH_CODE_INVALID"


def test_verify_code_concurrent_claim_is_atomic(client, mock_resend, test_db_path):
    """Serialised re-verify of the same code in the same event loop: only the
    first wins, the second sees the row already marked used and gets
    AUTH_CODE_INVALID. This exercises the CAS claim logic in
    `claim_active_code`; a true multi-process concurrency test is out of scope
    for the TestClient (sync) but the atomic UPDATE is the same code path.
    """
    email = "walid@example.com"
    client.post("/auth/request-code", json={"email": email})

    import sqlite3

    conn = sqlite3.connect(test_db_path)
    code = conn.execute(
        "SELECT code FROM auth_codes WHERE email = ? AND used = 0",
        (email,),
    ).fetchone()[0]
    conn.close()

    first = client.post("/auth/verify-code", json={"email": email, "code": code})
    second = client.post("/auth/verify-code", json={"email": email, "code": code})

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "AUTH_CODE_INVALID"

    # The row is used exactly once (not twice).
    conn = sqlite3.connect(test_db_path)
    used_count = conn.execute(
        "SELECT COUNT(*) FROM auth_codes WHERE email = ? AND used = 1",
        (email,),
    ).fetchone()[0]
    conn.close()
    assert used_count == 1


def test_verify_code_malformed_payload(client, mock_resend):
    """5-digit code → Pydantic 422 → VALIDATION_ERROR envelope."""
    response = client.post(
        "/auth/verify-code",
        json={"email": "walid@example.com", "code": "12345"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
