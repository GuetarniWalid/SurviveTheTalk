"""Tests for `DELETE /user/me` + `GET /user/data-export` (Story 10.1, Task 5/6).

The GDPR Art 17 (erase) / Art 20 (export) endpoints. We seed a user that owns a
row in EVERY personal table (call_sessions, debriefs, user_progress, purchases,
plus the auth_codes the login flow creates) and assert deletion removes them ALL
in one transaction with no FK/integrity error — the bug class the empty-DB test
would miss (Story 5.1 lesson).
"""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from auth.jwt_service import issue_token
from tests.conftest import register_user as _register_user

_EMAIL = "walid@example.com"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_owned_rows(db_path: str, user_id: int) -> int:
    """Give the user a row in every owned table; return the call_session id.

    `scenario_id` is read from the seeded catalog so the call_sessions /
    user_progress FKs to `scenarios(id)` are satisfied.
    """
    conn = sqlite3.connect(db_path)
    try:
        scenario_id = conn.execute("SELECT id FROM scenarios LIMIT 1").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO call_sessions(user_id, scenario_id, started_at, status, "
            "tier_at_call) VALUES (?, ?, '2026-06-19T00:00:00Z', 'completed', 'free')",
            (user_id, scenario_id),
        )
        call_id = cur.lastrowid
        conn.execute(
            "INSERT INTO debriefs(call_session_id, survival_pct, debrief_json, "
            "prompt_version, created_at) VALUES (?, 80, '{}', 'v1', "
            "'2026-06-19T00:00:00Z')",
            (call_id,),
        )
        conn.execute(
            "INSERT INTO user_progress(user_id, scenario_id, best_score, attempts, "
            "created_at, updated_at) VALUES (?, ?, 80, 1, '2026-06-19T00:00:00Z', "
            "'2026-06-19T00:00:00Z')",
            (user_id, scenario_id),
        )
        conn.execute(
            "INSERT INTO purchases(user_id, platform, product_id, "
            "verification_token, created_at) VALUES (?, 'ios', 'stt_weekly_199', "
            "?, '2026-06-19T00:00:00Z')",
            (user_id, f"tok-del-{user_id}"),
        )
        conn.commit()
        return call_id
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


def test_delete_requires_jwt(client: TestClient) -> None:
    response = client.delete("/user/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_export_requires_jwt(client: TestClient) -> None:
    response = client.get("/user/data-export")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


# --------------------------------------------------------------------------
# Deletion
# --------------------------------------------------------------------------


def test_delete_removes_all_owned_rows(
    client: TestClient, mock_resend, test_db_path
) -> None:
    user_id = _register_user(client, test_db_path)
    call_id = _seed_owned_rows(test_db_path, user_id)
    token = issue_token(user_id)

    response = client.delete("/user/me", headers=_auth(token))

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["deleted"] is True
    assert "meta" in body and "timestamp" in body["meta"]

    conn = sqlite3.connect(test_db_path)
    try:
        assert _count(conn, "users", "id = ?", user_id) == 0
        assert _count(conn, "call_sessions", "user_id = ?", user_id) == 0
        # debriefs are keyed by call_session_id (no user_id column).
        assert _count(conn, "debriefs", "call_session_id = ?", call_id) == 0
        assert _count(conn, "user_progress", "user_id = ?", user_id) == 0
        assert _count(conn, "purchases", "user_id = ?", user_id) == 0
        # auth_codes are keyed by email.
        assert _count(conn, "auth_codes", "email = ?", _EMAIL) == 0
    finally:
        conn.close()


def test_delete_does_not_touch_other_users(
    client: TestClient, mock_resend, test_db_path
) -> None:
    """Only the caller's rows are removed — a second user is untouched."""
    victim = _register_user(client, test_db_path, email="victim@example.com")
    _seed_owned_rows(test_db_path, victim)
    caller = _register_user(client, test_db_path, email="caller@example.com")
    _seed_owned_rows(test_db_path, caller)

    response = client.delete("/user/me", headers=_auth(issue_token(caller)))
    assert response.status_code == 200

    conn = sqlite3.connect(test_db_path)
    try:
        assert _count(conn, "users", "id = ?", caller) == 0
        assert _count(conn, "users", "id = ?", victim) == 1
        assert _count(conn, "call_sessions", "user_id = ?", victim) == 1
        assert _count(conn, "purchases", "user_id = ?", victim) == 1
    finally:
        conn.close()


def test_second_delete_is_unauthorized(
    client: TestClient, mock_resend, test_db_path
) -> None:
    """Once the row is gone the JWT resolves to no user → 401 (idempotent shape)."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    assert client.delete("/user/me", headers=_auth(token)).status_code == 200
    second = client.delete("/user/me", headers=_auth(token))
    assert second.status_code == 401
    assert second.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


def test_data_export_shape_and_excludes_credentials(
    client: TestClient, mock_resend, test_db_path
) -> None:
    user_id = _register_user(client, test_db_path)
    _seed_owned_rows(test_db_path, user_id)
    token = issue_token(user_id)

    response = client.get("/user/data-export", headers=_auth(token))

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account"]["email"] == _EMAIL
    # Internal session credential excluded from the export.
    assert "jwt_hash" not in data["account"]
    assert len(data["call_sessions"]) == 1
    assert len(data["debriefs"]) == 1
    assert len(data["progress"]) == 1
    assert len(data["purchases"]) == 1
    # Replayable store artifact excluded from the export.
    assert "verification_token" not in data["purchases"][0]


def _count(conn: sqlite3.Connection, table: str, where: str, value) -> int:
    return conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {where}", (value,)
    ).fetchone()[0]
