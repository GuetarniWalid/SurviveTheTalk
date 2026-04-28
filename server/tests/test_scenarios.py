"""Tests for the /scenarios endpoints (Story 5.1)."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from auth.jwt_service import issue_token
from tests.conftest import register_user as _register_user


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_list_requires_jwt(client):
    """No Authorization header → 401 AUTH_UNAUTHORIZED."""
    response = client.get("/scenarios")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_detail_requires_jwt(client):
    """No Authorization header → 401 AUTH_UNAUTHORIZED."""
    response = client.get("/scenarios/waiter_easy_01")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_list_returns_five_scenarios_ordered(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Authenticated GET /scenarios returns 5 items in the exact expected order.

    Order contract (AC4): easy bucket first, then medium, then hard; inside
    each bucket, `id` ASC. The full id sequence is asserted so a regression
    to alphabetical (which would still pass a loose `endswith` check) or a
    bucket misorder gets caught.
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.get("/scenarios", headers=_auth_header(token))

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["count"] == 5
    ids = [item["id"] for item in body["data"]]
    assert ids == [
        "waiter_easy_01",
        "girlfriend_medium_01",
        "mugger_medium_01",
        "cop_hard_01",
        "landlord_hard_01",
    ]


def test_list_shape_includes_progression_fields(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Each item has progression fields with expected types for a fresh user."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.get("/scenarios", headers=_auth_header(token))
    items = response.json()["data"]

    for item in items:
        assert item["best_score"] is None
        assert item["attempts"] == 0
        assert isinstance(item["is_free"], bool)
        assert isinstance(item["language_focus"], list)
        # `content_warning` is either null or a string — never missing.
        assert "content_warning" in item


def test_list_includes_free_and_paid_mix(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """3 free scenarios (waiter, mugger, girlfriend) + 2 paid (cop, landlord)."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    items = client.get("/scenarios", headers=_auth_header(token)).json()["data"]

    free_count = sum(1 for item in items if item["is_free"])
    paid_count = sum(1 for item in items if not item["is_free"])
    assert free_count == 3
    assert paid_count == 2


def test_detail_returns_full_shape(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """GET /scenarios/waiter_easy_01 returns the full authoring body."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.get("/scenarios/waiter_easy_01", headers=_auth_header(token))

    assert response.status_code == 200
    data = response.json()["data"]

    briefing = data["briefing"]
    assert isinstance(briefing, dict)
    assert {"vocabulary", "context", "expect"}.issubset(briefing.keys())

    exit_lines = data["exit_lines"]
    assert {"hangup", "completion"}.issubset(exit_lines.keys())

    checkpoints = data["checkpoints"]
    assert isinstance(checkpoints, list)
    assert len(checkpoints) > 0

    assert "Tina" in data["base_prompt"]
    assert data["content_warning"] is None


def test_detail_returns_404_on_unknown_id(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Unknown scenario id → 404 SCENARIO_NOT_FOUND."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.get("/scenarios/nonexistent_id", headers=_auth_header(token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SCENARIO_NOT_FOUND"


def test_list_reflects_user_progress(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """A user_progress row surfaces in the list endpoint via LEFT JOIN."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    conn = sqlite3.connect(test_db_path)
    conn.execute(
        "INSERT INTO user_progress(user_id, scenario_id, best_score, "
        "attempts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            user_id,
            "waiter_easy_01",
            75,
            2,
            "2026-04-24T10:05:00Z",
            "2026-04-24T10:05:00Z",
        ),
    )
    conn.commit()
    conn.close()

    items = client.get("/scenarios", headers=_auth_header(token)).json()["data"]
    by_id = {item["id"]: item for item in items}

    waiter = by_id["waiter_easy_01"]
    assert waiter["best_score"] == 75
    assert waiter["attempts"] == 2

    mugger = by_id["mugger_medium_01"]
    assert mugger["best_score"] is None
    assert mugger["attempts"] == 0


@pytest.mark.parametrize(
    "column",
    [
        "briefing",
        "exit_lines",
        "checkpoints",
        "language_focus",
        "escalation_thresholds",
    ],
)
def test_detail_returns_500_on_corrupt_json_column(
    client: TestClient, mock_resend, test_db_path: str, column: str
) -> None:
    """Manual DB corruption of any JSON-in-TEXT column → 500 SCENARIO_CORRUPT.

    Covers all 5 JSON-in-TEXT columns on the scenarios table. Schema enforces
    NOT NULL on 4 of them (escalation_thresholds is nullable, but a corrupt
    non-null value must still fail loud). The handler MUST surface
    SCENARIO_CORRUPT, not FastAPI's default 500.
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    conn = sqlite3.connect(test_db_path)
    conn.execute(
        f"UPDATE scenarios SET {column} = ? WHERE id = ?",
        ("not-valid-json{", "waiter_easy_01"),
    )
    conn.commit()
    conn.close()

    response = client.get("/scenarios/waiter_easy_01", headers=_auth_header(token))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "SCENARIO_CORRUPT"


def test_detail_returns_500_on_shape_mismatch_json_column(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Valid JSON of the wrong Pydantic shape → 500 SCENARIO_CORRUPT.

    `_safe_json_load` only catches parse errors. When a JSON-in-TEXT column
    holds *valid* JSON that violates the Pydantic schema (e.g. briefing is a
    list instead of a dict), the route must still surface SCENARIO_CORRUPT
    instead of leaking a generic FastAPI 500.
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    conn = sqlite3.connect(test_db_path)
    # `briefing` must be an object per ADR 001 — we store a list instead.
    conn.execute(
        "UPDATE scenarios SET briefing = ? WHERE id = ?",
        ('["wrong", "shape"]', "waiter_easy_01"),
    )
    conn.commit()
    conn.close()

    response = client.get("/scenarios/waiter_easy_01", headers=_auth_header(token))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "SCENARIO_CORRUPT"


def test_envelope_shape(client: TestClient, mock_resend, test_db_path: str) -> None:
    """The list envelope carries `data` + `meta.count` + ISO-Z `meta.timestamp`.

    Story 5.3 widened `meta` with the call-usage policy block — the four
    `tier` / `calls_remaining` / `calls_per_period` / `period` keys are
    asserted present here so a future regression that drops the fold-in
    fails this test instead of slipping past the dedicated usage tests.
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    body = client.get("/scenarios", headers=_auth_header(token)).json()

    assert "data" in body
    assert "meta" in body
    assert isinstance(body["meta"]["count"], int)
    assert body["meta"]["timestamp"].endswith("Z")
    # Story 5.3 — call-usage policy folded into meta.
    for key in ("tier", "calls_remaining", "calls_per_period", "period"):
        assert key in body["meta"], f"missing meta.{key} (Story 5.3)"


def test_meta_includes_usage_for_free_user(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Fresh free user → meta.tier='free', period='lifetime', remaining=3, cap=3."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    body = client.get("/scenarios", headers=_auth_header(token)).json()

    assert body["meta"]["tier"] == "free"
    assert body["meta"]["period"] == "lifetime"
    assert body["meta"]["calls_remaining"] == 3
    assert body["meta"]["calls_per_period"] == 3


@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token")
@patch("api.routes_calls.generate_token", return_value="user-token")
def test_meta_calls_remaining_decrements_after_initiate(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """One successful /calls/initiate → meta.calls_remaining drops 3 → 2."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    init = client.post("/calls/initiate", json={}, headers=_auth_header(token))
    assert init.status_code == 200

    body = client.get("/scenarios", headers=_auth_header(token)).json()
    assert body["meta"]["calls_remaining"] == 2


def test_meta_period_is_day_for_paid_user(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Promoting tier to 'paid' flips period='day' and resets remaining=3 (no sessions today)."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    conn = sqlite3.connect(test_db_path)
    conn.execute("UPDATE users SET tier = 'paid' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    body = client.get("/scenarios", headers=_auth_header(token)).json()
    assert body["meta"]["tier"] == "paid"
    assert body["meta"]["period"] == "day"
    # No call_sessions exist for this user today → cap untouched.
    assert body["meta"]["calls_remaining"] == 3


def test_meta_count_and_timestamp_still_present(
    client: TestClient, mock_resend, test_db_path: str
) -> None:
    """Regression guard: pre-5.3 keys (`count`, `timestamp`) survive the meta widening."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    meta = client.get("/scenarios", headers=_auth_header(token)).json()["meta"]

    assert meta["count"] == 5
    assert meta["timestamp"].endswith("Z")
