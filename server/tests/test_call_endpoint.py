"""Tests for the /connect endpoint."""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

ENV_VARS = {
    "SONIOX_API_KEY": "test-soniox",
    "OPENROUTER_API_KEY": "test-openrouter",
    "CARTESIA_API_KEY": "test-cartesia",
    "LIVEKIT_URL": "wss://livekit.example.com",
    "LIVEKIT_API_KEY": "test-lk-key",
    "LIVEKIT_API_SECRET": "test-lk-secret",
}


@pytest.fixture()
def client():
    with patch.dict(os.environ, ENV_VARS, clear=False):
        # Re-import to pick up test env vars
        import importlib

        import api.call_endpoint as mod

        importlib.reload(mod)
        yield TestClient(mod.app)


@patch("api.call_endpoint.subprocess.Popen")
@patch("api.call_endpoint.generate_token_with_agent", return_value="agent-token-123")
@patch("api.call_endpoint.generate_token", return_value="user-token-456")
def test_connect_returns_expected_schema(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    client: TestClient,
) -> None:
    response = client.post("/connect")
    assert response.status_code == 200
    data = response.json()
    assert "room_name" in data
    assert data["room_name"].startswith("room-")
    assert "token" in data
    assert data["token"] == "user-token-456"
    assert "livekit_url" in data


@patch("api.call_endpoint.subprocess.Popen")
@patch("api.call_endpoint.generate_token_with_agent", return_value="agent-token-123")
@patch("api.call_endpoint.generate_token", return_value="user-token-456")
def test_connect_spawns_subprocess(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    client: TestClient,
) -> None:
    client.post("/connect")
    mock_popen.assert_called_once()
    call_args = mock_popen.call_args[0][0]
    assert "pipeline.bot" in " ".join(call_args)
    assert "--url" in call_args
    assert "--room" in call_args
    assert "--token" in call_args
