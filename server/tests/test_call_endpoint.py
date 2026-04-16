"""Tests for the legacy /connect endpoint (now an APIRouter mounted on api.app)."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def call_client():
    # Env vars are set globally in conftest.py; import api.app once.
    from api.app import app

    yield TestClient(app)


@patch("api.call_endpoint.subprocess.Popen")
@patch("api.call_endpoint.generate_token_with_agent", return_value="agent-token-123")
@patch("api.call_endpoint.generate_token", return_value="user-token-456")
def test_connect_returns_expected_schema(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    call_client: TestClient,
) -> None:
    response = call_client.post("/connect")
    assert response.status_code == 200
    data = response.json()
    # The /connect endpoint intentionally keeps its legacy flat shape (NOT
    # wrapped in {data, meta}) — Story 6.1 will redesign it.
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
    call_client: TestClient,
) -> None:
    call_client.post("/connect")
    mock_popen.assert_called_once()
    call_args = mock_popen.call_args[0][0]
    assert "pipeline.bot" in " ".join(call_args)
    assert "--url" in call_args
    assert "--room" in call_args
    assert "--token" in call_args
