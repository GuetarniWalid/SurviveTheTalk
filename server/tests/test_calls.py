"""Tests for the /calls/initiate endpoint (Story 4.5)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from auth.jwt_service import issue_token
from tests.conftest import register_user as _register_user

# Frozen UTC instant used by paid-tier tests so the seed timestamps and the
# handler's "today" computation can never disagree across UTC midnight (CI runs
# spanning 23:59 → 00:00 used to flap). Paired with `_today_iso(...)` which
# anchors all "today @ hour" timestamps to this instant. The handler reads
# `datetime.now(UTC)` inside `api.usage.compute_call_usage`; tests that need
# the clock pinned monkey-patch `api.usage.datetime.now` to return _FROZEN_NOW.
_FROZEN_NOW = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_initiate_requires_jwt(client):
    """No Authorization header → 401 AUTH_UNAUTHORIZED."""
    response = client.post("/calls/initiate", json={})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_initiate_rejects_invalid_jwt(client):
    """Malformed JWT → 401 AUTH_UNAUTHORIZED."""
    response = client.post(
        "/calls/initiate",
        json={},
        headers=_auth_header("not.a.jwt"),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_happy_path_returns_envelope(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/calls/initiate",
        json={},
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    assert "meta" in body
    assert "timestamp" in body["meta"]

    data = body["data"]
    assert isinstance(data["call_id"], int)
    assert data["call_id"] >= 1
    assert data["room_name"].startswith("call-")
    assert data["token"] == "user-token-xyz"
    assert data["livekit_url"] == "wss://livekit.example.com"


@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_persists_call_session_row(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/calls/initiate",
        json={},
        headers=_auth_header(token),
    )
    call_id = response.json()["data"]["call_id"]

    conn = sqlite3.connect(test_db_path)
    row = conn.execute(
        "SELECT user_id, scenario_id, started_at, duration_sec, cost_cents "
        "FROM call_sessions WHERE id = ?",
        (call_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == user_id
    assert row[1] == "waiter_easy_01"
    assert row[2].endswith("Z")  # ISO 8601 UTC
    assert row[3] is None  # duration_sec — filled by /calls/{id}/end later
    assert row[4] is None  # cost_cents


@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_spawns_bot_with_scenario_prompt(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Popen is called once with the expected argv shape and the SYSTEM_PROMPT
    env var carries a prompt that includes the 'speak first' directive (AC3).
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/calls/initiate",
        json={},
        headers=_auth_header(token),
    )
    assert response.status_code == 200
    room_name = response.json()["data"]["room_name"]

    mock_popen.assert_called_once()
    call_args = mock_popen.call_args
    argv = call_args[0][0]
    assert "pipeline.bot" in " ".join(argv)
    assert "--url" in argv
    assert "--room" in argv
    assert "--token" in argv
    room_index = argv.index("--room")
    assert argv[room_index + 1] == room_name

    # The scenario prompt is passed through env (not argv) — avoids argv
    # length limits on long prompts.
    env = call_args.kwargs.get("env")
    assert env is not None
    assert "SYSTEM_PROMPT" in env
    system_prompt = env["SYSTEM_PROMPT"]
    # Proxy verification for AC3: the composed prompt tells the bot to
    # speak first rather than wait for the user.
    assert "speak first" in system_prompt.lower()
    # The waiter base_prompt is present (sanity-check the YAML loader).
    assert "Tina" in system_prompt
    assert "The Golden Fork" in system_prompt


@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_generates_both_tokens(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """`generate_token` + `generate_token_with_agent` each called exactly once."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    client.post(
        "/calls/initiate",
        json={},
        headers=_auth_header(token),
    )

    mock_gen_token.assert_called_once()
    mock_gen_agent.assert_called_once()


def test_connect_and_initiate_coexist(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Legacy /connect still responds (no regression) while /calls/initiate is live."""
    with (
        patch("api.call_endpoint.subprocess.Popen"),
        patch("api.call_endpoint.generate_token_with_agent", return_value="at"),
        patch("api.call_endpoint.generate_token", return_value="ut"),
    ):
        legacy = client.post("/connect")
    assert legacy.status_code == 200
    assert "room_name" in legacy.json()
    assert legacy.json()["room_name"].startswith("room-")


def test_scenario_loader_rejects_unknown_id():
    """load_scenario_prompt raises ValueError on unknown scenario ids."""
    from pipeline.scenarios import load_scenario_prompt

    with pytest.raises(ValueError):
        load_scenario_prompt("mugger_hard_01")


# ---------- Story 5.3 — daily/lifetime call cap enforcement ----------


def _seed_call_sessions(db_path: str, user_id: int, started_ats: list[str]) -> None:
    """Insert one row per `started_ats` timestamp via raw SQL."""
    conn = sqlite3.connect(db_path)
    for ts in started_ats:
        conn.execute(
            "INSERT INTO call_sessions(user_id, scenario_id, started_at) "
            "VALUES (?, ?, ?)",
            (user_id, "waiter_easy_01", ts),
        )
    conn.commit()
    conn.close()


def _set_tier(db_path: str, user_id: int, tier: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user_id))
    conn.commit()
    conn.close()


def _today_iso(hour: int = 12) -> str:
    """ISO 8601 UTC for `_FROZEN_NOW`'s date at `hour`:00:00.

    Anchored to `_FROZEN_NOW` (not the wall clock) so it cannot disagree with a
    freeze-clock-patched handler across UTC midnight. Use this with
    ``@patch("api.usage.datetime")`` setting ``mock.now.return_value = _FROZEN_NOW``.
    """
    return (
        _FROZEN_NOW.replace(hour=hour, minute=0, second=0, microsecond=0)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_returns_403_call_limit_reached_when_free_user_exhausted(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    user_id = _register_user(client, test_db_path)
    _seed_call_sessions(
        test_db_path,
        user_id,
        [
            "2026-04-01T08:00:00Z",
            "2026-04-02T09:00:00Z",
            "2026-04-03T10:00:00Z",
        ],
    )
    token = issue_token(user_id)

    response = client.post("/calls/initiate", json={}, headers=_auth_header(token))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CALL_LIMIT_REACHED"


@patch("api.usage.datetime")
@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_returns_403_when_paid_user_exhausted_today(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    mock_datetime: MagicMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Paid user with 3 sessions today → 403; yesterday's sessions don't count."""
    mock_datetime.now.return_value = _FROZEN_NOW
    user_id = _register_user(client, test_db_path)
    _set_tier(test_db_path, user_id, "paid")
    _seed_call_sessions(
        test_db_path,
        user_id,
        [_today_iso(0), _today_iso(8), _today_iso(20)],
    )
    token = issue_token(user_id)

    response = client.post("/calls/initiate", json={}, headers=_auth_header(token))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CALL_LIMIT_REACHED"


@patch("api.usage.datetime")
@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_succeeds_when_paid_user_has_calls_yesterday_only(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    mock_datetime: MagicMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Paid user with 3 old sessions (clearly before today) → 200, cap reset."""
    mock_datetime.now.return_value = _FROZEN_NOW
    user_id = _register_user(client, test_db_path)
    _set_tier(test_db_path, user_id, "paid")
    _seed_call_sessions(
        test_db_path,
        user_id,
        [
            "2025-01-01T00:00:00Z",
            "2025-01-01T01:00:00Z",
            "2025-01-01T02:00:00Z",
        ],
    )
    token = issue_token(user_id)

    response = client.post("/calls/initiate", json={}, headers=_auth_header(token))

    assert response.status_code == 200
    assert response.json()["data"]["token"] == "user-token-xyz"


@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_does_not_persist_when_capped(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """A blocked attempt MUST NOT insert a `call_sessions` row."""
    user_id = _register_user(client, test_db_path)
    _seed_call_sessions(
        test_db_path,
        user_id,
        [
            "2026-04-01T08:00:00Z",
            "2026-04-02T09:00:00Z",
            "2026-04-03T10:00:00Z",
        ],
    )
    token = issue_token(user_id)

    response = client.post("/calls/initiate", json={}, headers=_auth_header(token))
    assert response.status_code == 403

    conn = sqlite3.connect(test_db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM call_sessions WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    conn.close()

    # The 3 seeded rows are still there; no fourth row was added.
    assert count == 3


@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_does_not_spawn_bot_when_capped(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """A capped attempt MUST NOT fork the bot subprocess (and MUST NOT mint tokens)."""
    user_id = _register_user(client, test_db_path)
    _seed_call_sessions(
        test_db_path,
        user_id,
        [
            "2026-04-01T08:00:00Z",
            "2026-04-02T09:00:00Z",
            "2026-04-03T10:00:00Z",
        ],
    )
    token = issue_token(user_id)

    response = client.post("/calls/initiate", json={}, headers=_auth_header(token))
    assert response.status_code == 403

    mock_popen.assert_not_called()
    mock_gen_token.assert_not_called()
    mock_gen_agent.assert_not_called()
