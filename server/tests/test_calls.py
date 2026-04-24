"""Tests for the /calls/initiate endpoint (Story 4.5)."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from auth.jwt_service import issue_token
from tests.conftest import register_user as _register_user


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
