"""Tests for the /calls/initiate endpoint (Story 4.5 + 6.1 widening)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest
from fastapi.testclient import TestClient

from auth.jwt_service import issue_token
from tests.conftest import register_user as _register_user

# Default request body for the happy-path tests. Story 6.1 made `scenario_id`
# required; the tutorial id keeps these tests aligned with the YAML actually
# present on disk (`server/pipeline/scenarios/the-waiter.yaml`).
_TUTORIAL_BODY = {"scenario_id": "waiter_easy_01"}

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
    response = client.post("/calls/initiate", json=_TUTORIAL_BODY)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_initiate_rejects_invalid_jwt(client):
    """Malformed JWT → 401 AUTH_UNAUTHORIZED."""
    response = client.post(
        "/calls/initiate",
        json=_TUTORIAL_BODY,
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
        json=_TUTORIAL_BODY,
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
        json=_TUTORIAL_BODY,
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
        json=_TUTORIAL_BODY,
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
    # Story 6.3 — SCENARIO_CHARACTER env var carries the YAML
    # `metadata.rive_character` slug so the spawned bot can build
    # character-aware classifier prompts.
    assert env.get("SCENARIO_CHARACTER") == "waiter"
    # Story 6.4 — SCENARIO_ID env var lets the spawned bot resolve the
    # PatienceTracker config via `resolve_patience_config(scenario_id)`.
    assert env.get("SCENARIO_ID") == "waiter_easy_01"


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
        json=_TUTORIAL_BODY,
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
    """load_scenario_prompt raises FileNotFoundError on unknown scenario ids
    (Story 6.1 widened the loader from ValueError → FileNotFoundError so the
    route's existing exception arm at routes_calls.py surfaces it as the
    canonical SCENARIO_LOAD_FAILED envelope).
    """
    from pipeline.scenarios import load_scenario_prompt

    with pytest.raises(FileNotFoundError):
        load_scenario_prompt("does_not_exist")


# ---------- Story 6.1 — `scenario_id` body field ----------


def test_initiate_validates_scenario_id_required(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Empty body → 422 + canonical VALIDATION_ERROR envelope."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/calls/initiate",
        json={},
        headers=_auth_header(token),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "bad_scenario_id",
    [
        "",  # empty string passed Pydantic before P8 — now rejected by min_length
        " " * 5,  # whitespace fails the charset pattern
        "x" * 65,  # over max_length=64
        "../../etc/passwd",  # path-traversal-shaped string fails the charset pattern
        "Waiter-EASY-01",  # uppercase + dash fail the lowercase-snake-case pattern
    ],
)
def test_initiate_rejects_invalid_scenario_id_shapes(
    client: TestClient,
    mock_resend,
    test_db_path: str,
    bad_scenario_id: str,
) -> None:
    """Schema-level rejection of empty / oversized / wrong-charset ids — they
    must surface as VALIDATION_ERROR (422), not SCENARIO_LOAD_FAILED (500),
    so a bad client can't amplify logs by sending unbounded strings (the
    `logger.exception` arm in the route would otherwise write the full id
    to disk per request).
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/calls/initiate",
        json={"scenario_id": bad_scenario_id},
        headers=_auth_header(token),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_rejects_unknown_scenario(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Unknown scenario_id → 500 + SCENARIO_LOAD_FAILED (no DB row, no Popen)."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/calls/initiate",
        json={"scenario_id": "does_not_exist"},
        headers=_auth_header(token),
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "SCENARIO_LOAD_FAILED"

    # No row was inserted, no bot was spawned (the failure happens before
    # both side-effects in the route's hot path).
    conn = sqlite3.connect(test_db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM call_sessions WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    conn.close()
    assert count == 0
    mock_popen.assert_not_called()


@pytest.mark.parametrize(
    "scenario_id",
    ["waiter_easy_01", "cop_hard_01"],
)
@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_persists_requested_scenario_id(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    scenario_id: str,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Parametrised happy path — `call_sessions.scenario_id` matches the body."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/calls/initiate",
        json={"scenario_id": scenario_id},
        headers=_auth_header(token),
    )
    assert response.status_code == 200
    call_id = response.json()["data"]["call_id"]

    conn = sqlite3.connect(test_db_path)
    row = conn.execute(
        "SELECT scenario_id FROM call_sessions WHERE id = ?",
        (call_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == scenario_id


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

    response = client.post(
        "/calls/initiate", json=_TUTORIAL_BODY, headers=_auth_header(token)
    )

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

    response = client.post(
        "/calls/initiate", json=_TUTORIAL_BODY, headers=_auth_header(token)
    )

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

    response = client.post(
        "/calls/initiate", json=_TUTORIAL_BODY, headers=_auth_header(token)
    )

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

    response = client.post(
        "/calls/initiate", json=_TUTORIAL_BODY, headers=_auth_header(token)
    )
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

    response = client.post(
        "/calls/initiate", json=_TUTORIAL_BODY, headers=_auth_header(token)
    )
    assert response.status_code == 403

    mock_popen.assert_not_called()
    mock_gen_token.assert_not_called()
    mock_gen_agent.assert_not_called()


# ---------- Story 6.5 — Popen rollback LiveKit cleanup ----------


@patch("api.routes_calls.livekit_delete_room", new_callable=AsyncMock)
@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_popen_failure_calls_livekit_delete_room(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    mock_livekit_delete: AsyncMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Popen OSError → livekit_delete_room called with the minted room_name.

    Regression net for AC4: minted-but-unused rooms must not linger on
    the LiveKit billing side for the idle TTL window. The original
    BOT_SPAWN_FAILED envelope must still surface — the cleanup is a
    silent side-channel.

    Story 6.5 review D3: rollback now FLIPs the row to `'failed'`
    instead of hard-DELETEing. The audit trail is preserved (operators
    can grep `'failed'` rows for Popen-failure rates) while the cap
    counter is still freed via the `status IN ('pending', 'completed')`
    filter in `count_user_call_sessions_*`.
    """
    mock_popen.side_effect = OSError("no executable found")

    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/calls/initiate",
        json=_TUTORIAL_BODY,
        headers=_auth_header(token),
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "BOT_SPAWN_FAILED"

    # Cleanup ran once with the room_name from the response. The patched
    # mock target is the module-level `livekit_delete_room` helper —
    # `_safe_livekit_delete_room` calls into it through asyncio.shield
    # + wait_for, so the mock still observes exactly one invocation.
    mock_livekit_delete.assert_awaited_once()
    args = mock_livekit_delete.await_args[0]
    # signature: livekit_delete_room(settings, room_name)
    assert len(args) == 2
    assert isinstance(args[1], str) and args[1].startswith("call-")

    # Rollback worked: row is FLIPped to 'failed' (D3), not deleted.
    conn = sqlite3.connect(test_db_path)
    row = conn.execute(
        "SELECT status FROM call_sessions WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    conn.close()
    assert row is not None, (
        "Story 6.5 review D3: rollback must FLIP, not DELETE — the row "
        "must remain visible for the audit trail."
    )
    assert row[0] == "failed", (
        "Rollback path must set status='failed' so the cap counter is "
        "freed (status IN ('pending','completed') filter excludes it) "
        "while the audit row survives."
    )


@patch("api.routes_calls.livekit_delete_room", new_callable=AsyncMock)
@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_popen_failure_swallows_livekit_cleanup_failure(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    mock_livekit_delete: AsyncMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """LiveKit cleanup failure MUST NOT mask the BOT_SPAWN_FAILED envelope.

    The user already saw a call-failure surface; the cleanup is silent
    janitorial work whose failure is `logger.warning`-ed but not raised.
    """
    mock_popen.side_effect = OSError("no executable found")
    # Cleanup itself fails — should be swallowed.
    mock_livekit_delete.side_effect = RuntimeError("LiveKit unreachable")

    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/calls/initiate",
        json=_TUTORIAL_BODY,
        headers=_auth_header(token),
    )

    # Original envelope wins.
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "BOT_SPAWN_FAILED"


# ---------- Story 6.5 — POST /calls/{call_id}/end ----------


def _make_pending_call(
    db_path: str,
    user_id: int,
    *,
    started_at: str = "2026-04-28T11:59:00Z",
    scenario_id: str = "waiter_easy_01",
) -> int:
    """Insert a fresh `'pending'` call_sessions row directly via SQL.

    Skips /calls/initiate's bot-spawn side-effect — the /end tests only
    need a row to flip. Returns the new call_id.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "INSERT INTO call_sessions(user_id, scenario_id, started_at, status) "
        "VALUES (?, ?, ?, 'pending')",
        (user_id, scenario_id, started_at),
    )
    call_id = cursor.lastrowid
    conn.commit()
    conn.close()
    assert call_id is not None
    return call_id


def _get_call_row(db_path: str, call_id: int) -> tuple:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT status, duration_sec FROM call_sessions WHERE id = ?",
        (call_id,),
    ).fetchone()
    conn.close()
    return row


def test_end_call_requires_jwt(client: TestClient) -> None:
    """No Authorization header → 401 AUTH_UNAUTHORIZED."""
    response = client.post("/calls/1/end", json={"reason": "user_hung_up"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_end_call_rejects_invalid_jwt(client: TestClient) -> None:
    """Malformed JWT → 401 AUTH_UNAUTHORIZED."""
    response = client.post(
        "/calls/1/end",
        json={"reason": "user_hung_up"},
        headers=_auth_header("not.a.jwt"),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_UNAUTHORIZED"


def test_end_call_happy_path_flips_status_and_returns_envelope(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Valid /end on a 'pending' row: 200 + envelope; DB row flipped."""
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(test_db_path, user_id)
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "user_hung_up"},
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    assert "meta" in body
    assert "timestamp" in body["meta"]

    data = body["data"]
    assert data["call_id"] == call_id
    assert data["status"] == "completed"
    assert isinstance(data["duration_sec"], int)
    assert data["duration_sec"] >= 0  # clamped >= 0 defensively

    # Story 6.5 review P24: assert `cost_cents` stays NULL after /end
    # (Deviation #1 — FR46 deferred post-MVP). A future regression that
    # wires cost computation by mistake would otherwise sneak past tests
    # that only check status + duration.
    conn = sqlite3.connect(test_db_path)
    row = conn.execute(
        "SELECT status, duration_sec, cost_cents FROM call_sessions WHERE id = ?",
        (call_id,),
    ).fetchone()
    conn.close()
    assert row is not None
    status, duration_sec, cost_cents = row
    assert status == "completed"
    assert duration_sec == data["duration_sec"]
    assert cost_cents is None, (
        "Story 6.5 Deviation #1: cost_cents must stay NULL until the "
        "post-MVP rate sheet lands. Regression check."
    )


@pytest.mark.parametrize(
    "reason",
    [
        "user_hung_up",
        "character_hung_up",
        "inappropriate_content",
        "network_lost",
        # Story 6.5 review D4 — pre-widened for Story 6.6's CheckpointManager.
        "survived",
    ],
)
def test_end_call_accepts_all_four_canonical_reasons(
    client: TestClient,
    mock_resend,
    test_db_path: str,
    reason: str,
) -> None:
    """Whitelist enforcement — all reasons round-trip.

    Story 6.5 Déviation #27: `network_lost` is gifted by default (status
    flips to 'failed'); `character_hung_up` / `inappropriate_content`
    are gifted only when `duration_sec < 30`. The `_make_pending_call`
    helper uses an old `started_at` that produces a multi-minute
    duration, so character/inappropriate land NOT gifted in this test.
    Test asserts ANY valid terminal status — the reason-specific gift
    semantics live in their own dedicated tests.
    """
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(test_db_path, user_id)
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": reason},
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    assert response.json()["data"]["status"] in ("completed", "failed")


def test_end_call_rejects_unknown_reason(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Reason outside the Literal whitelist → 422 VALIDATION_ERROR."""
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(test_db_path, user_id)
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "panic"},
        headers=_auth_header(token),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_end_call_rejects_missing_reason(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Empty body → 422 (Pydantic missing-field validation)."""
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(test_db_path, user_id)
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={},
        headers=_auth_header(token),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_end_call_returns_404_on_unknown_call_id(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Nonexistent call_id → 404 CALL_NOT_FOUND."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/calls/999999/end",
        json={"reason": "user_hung_up"},
        headers=_auth_header(token),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CALL_NOT_FOUND"


def test_end_call_returns_404_on_cross_user_call_id(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """User A's JWT targeting user B's call_id → 404 (NOT 403, info-leak).

    Same envelope shape as the unknown-call_id case so an attacker cannot
    distinguish "no such call" from "someone else's call".
    """
    user_a = _register_user(client, test_db_path, email="alice@example.com")
    user_b = _register_user(client, test_db_path, email="bob@example.com")
    # Bob owns the call; Alice tries to /end it.
    bob_call = _make_pending_call(test_db_path, user_b)
    alice_token = issue_token(user_a)

    response = client.post(
        f"/calls/{bob_call}/end",
        json={"reason": "user_hung_up"},
        headers=_auth_header(alice_token),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CALL_NOT_FOUND"

    # Bob's row is untouched.
    status, duration_sec = _get_call_row(test_db_path, bob_call)
    assert status == "pending"
    assert duration_sec is None


def test_end_call_is_idempotent(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Second /end returns the SAME duration_sec as the first (no re-flip).

    The first /end's "now" is authoritative; a delayed retry must NOT
    overwrite it with a fresh timestamp diff.
    """
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(test_db_path, user_id)
    token = issue_token(user_id)

    first = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "user_hung_up"},
        headers=_auth_header(token),
    )
    assert first.status_code == 200
    first_duration = first.json()["data"]["duration_sec"]

    second = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "user_hung_up"},
        headers=_auth_header(token),
    )
    assert second.status_code == 200
    second_duration = second.json()["data"]["duration_sec"]

    # Both envelopes match exactly — second call read back the stored value.
    assert second_duration == first_duration
    assert second.json()["data"]["status"] == "completed"

    # DB persists the first-call value.
    status, duration_sec = _get_call_row(test_db_path, call_id)
    assert status == "completed"
    assert duration_sec == first_duration


def test_end_call_clamps_duration_to_zero_on_future_started_at(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """A `started_at` slightly in the future (clock skew) → duration_sec == 0.

    Defensive clamp — a future `started_at` would otherwise produce a
    negative `total_seconds()` that downstream cost-calc / debrief logic
    would mishandle.
    """
    user_id = _register_user(client, test_db_path)
    # Review P18: use a plain timedelta for clarity (the prior hard-coded
    # year-difference arithmetic still works but is harder to read).
    future_iso = (
        (datetime.now(UTC).replace(microsecond=0) + timedelta(days=365))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    call_id = _make_pending_call(test_db_path, user_id, started_at=future_iso)
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "user_hung_up"},
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    assert response.json()["data"]["duration_sec"] == 0


# ---------- Story 6.5 review patches ----------


@patch("api.routes_calls.livekit_delete_room", new_callable=AsyncMock)
@patch("api.routes_calls.subprocess.Popen")
@patch("api.routes_calls.generate_token_with_agent", return_value="agent-token-abc")
@patch("api.routes_calls.generate_token", return_value="user-token-xyz")
def test_initiate_popen_failure_db_flip_runs_before_livekit_delete(
    mock_gen_token: MagicMock,
    mock_gen_agent: MagicMock,
    mock_popen: MagicMock,
    mock_livekit_delete: AsyncMock,
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Review P25: DB FLIP must run BEFORE LiveKit cleanup on the rollback path.

    Why ordering matters: the LiveKit `delete_room` round-trip is the
    slow leg (~50-200 ms typical, several seconds on DNS hiccup). Doing
    DB cleanup first means the cap-counter slot is freed the moment the
    Popen error surfaces, not after the LiveKit reach-out. A subtle
    refactor could flip the order with no functional break — the test
    pins the contract by capturing the DB state inside the LiveKit
    mock's coroutine.
    """
    mock_popen.side_effect = OSError("no executable found")

    db_state_during_livekit: dict[str, str | None] = {}

    async def livekit_inspect_db(*args, **kwargs):
        conn = sqlite3.connect(test_db_path)
        row = conn.execute(
            "SELECT status FROM call_sessions ORDER BY id DESC LIMIT 1"
        ).fetchone()
        conn.close()
        db_state_during_livekit["status"] = row[0] if row else None
        return None

    mock_livekit_delete.side_effect = livekit_inspect_db

    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    response = client.post(
        "/calls/initiate",
        json=_TUTORIAL_BODY,
        headers=_auth_header(token),
    )
    assert response.status_code == 500

    # By the time LiveKit cleanup runs, the DB row was already FLIPped.
    assert db_state_during_livekit["status"] == "failed", (
        "Review P25: DB FLIP must happen BEFORE LiveKit cleanup so the "
        "cap counter is freed even if LiveKit hangs."
    )
    mock_livekit_delete.assert_awaited_once()


def test_end_call_handles_malformed_started_at(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Review P20: a malformed `started_at` must not crash /end.

    Production should never produce such a row — `responses.now_iso()`
    always sets a `Z`-suffixed string and the column is NOT NULL via
    the initial migration. But a future migration regression or a
    corrupted row should NOT propagate as a 500 to the client — the
    cap counter must still get unstuck. We use a non-ISO string here
    to exercise the `(AttributeError, TypeError, ValueError)` catch
    path.
    """
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(
        test_db_path,
        user_id,
        started_at="not-a-timestamp",
    )
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "user_hung_up"},
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["duration_sec"] == 0
    assert data["status"] == "completed"

    # Row was still flipped — the cap counter is unstuck even on the
    # malformed-data path.
    status, duration_sec = _get_call_row(test_db_path, call_id)
    assert status == "completed"
    assert duration_sec == 0


def test_end_call_idempotent_on_failed_row_returns_failed_status(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Review P10: idempotent /end on a janitor-failed row returns failed.

    The janitor sweep flips abandoned `'pending'` rows to `'failed'`. If
    the client's POST eventually lands AFTER the sweep, the endpoint
    should NOT re-flip — it returns the current state. The client
    treats both terminal statuses identically (cap counter freed); this
    test pins the contract so `EndCallOut.status` typing reflects
    reality.
    """
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(test_db_path, user_id)
    # Simulate the janitor having swept this row.
    conn = sqlite3.connect(test_db_path)
    conn.execute(
        "UPDATE call_sessions SET status='failed', duration_sec=42 WHERE id=?",
        (call_id,),
    )
    conn.commit()
    conn.close()
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "user_hung_up"},
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "failed"
    assert data["duration_sec"] == 42


def test_end_call_idempotent_completed_null_duration_logs(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Review P6: 'completed' + NULL duration_sec is a data-integrity bug.

    The endpoint must log loudly but still return a clean envelope so
    the client's cap counter unsticks. We capture via a temporary
    loguru sink rather than pytest's `caplog` because loguru does NOT
    propagate to the stdlib logging machinery by default — the standard
    capture fixture sees nothing.
    """
    from loguru import logger as loguru_logger

    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(test_db_path, user_id)
    # Force the pathological state. Production code never produces this;
    # we plant it directly to exercise the defensive log path.
    conn = sqlite3.connect(test_db_path)
    conn.execute(
        "UPDATE call_sessions SET status='completed', duration_sec=NULL WHERE id=?",
        (call_id,),
    )
    conn.commit()
    conn.close()
    token = issue_token(user_id)

    captured: list[str] = []
    sink_id = loguru_logger.add(captured.append, level="ERROR")
    try:
        response = client.post(
            f"/calls/{call_id}/end",
            json={"reason": "user_hung_up"},
            headers=_auth_header(token),
        )
    finally:
        loguru_logger.remove(sink_id)

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "completed"
    assert response.json()["data"]["duration_sec"] == 0
    # Defensive log surfaced. We match loosely on the diagnostic tag to
    # stay robust against future log-string tweaks.
    log_text = "".join(captured)
    assert "call_ended_null_duration" in log_text, (
        "Review P6: NULL duration_sec on a terminal row must log "
        "`call_ended_null_duration` at ERROR. Captured: " + log_text[:200]
    )


def test_end_call_returns_503_when_database_is_locked(
    client: TestClient,
    mock_resend,
    test_db_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review P17: a locked DB on BEGIN IMMEDIATE → 503 with Retry-After.

    Under sustained write contention `BEGIN IMMEDIATE` can time out past
    the `busy_timeout` and surface as `OperationalError`. The client's
    fire-and-forget swallows either way, but a 503 with `Retry-After: 1`
    lets retry layers behave correctly.

    The wrapper preserves `aiosqlite.Connection.execute`'s
    awaitable-AND-context-manager protocol for non-BEGIN-IMMEDIATE
    statements by returning the original's result (which IS the dual
    protocol object). Only the BEGIN IMMEDIATE call site is intercepted
    — and the route awaits it directly (not as a context manager) so
    returning a plain coroutine that raises is enough.
    """
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(test_db_path, user_id)
    token = issue_token(user_id)

    original_execute = aiosqlite.Connection.execute

    async def _raise_locked():
        raise aiosqlite.OperationalError("database is locked")

    def execute_with_lock_on_begin(self, sql, *args, **kwargs):
        if isinstance(sql, str) and sql.strip().upper().startswith("BEGIN IMMEDIATE"):
            return _raise_locked()
        return original_execute(self, sql, *args, **kwargs)

    monkeypatch.setattr(aiosqlite.Connection, "execute", execute_with_lock_on_begin)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "user_hung_up"},
        headers=_auth_header(token),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DB_BUSY"
    assert response.headers.get("Retry-After") == "1"


def test_end_call_ownership_check_runs_before_begin_immediate(
    client: TestClient,
    mock_resend,
    test_db_path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review P22: cross-user 404 must NOT acquire the write lock.

    Holding the global write lock per cross-user probe amplifies a
    user-enumeration attack into a DoS that serializes legitimate
    `/calls/initiate` calls behind every probe. The cheap read-only
    SELECT-then-404 path must short-circuit BEFORE `BEGIN IMMEDIATE`
    is issued.

    The recording wrapper preserves the dual awaitable / context-manager
    protocol by returning the original's result directly (not awaiting
    it inside an `async def`, which would collapse the dual protocol
    into a plain coroutine).
    """
    user_a = _register_user(client, test_db_path, email="alice2@example.com")
    user_b = _register_user(client, test_db_path, email="bob2@example.com")
    bob_call = _make_pending_call(test_db_path, user_b)
    alice_token = issue_token(user_a)

    original_execute = aiosqlite.Connection.execute
    observed_statements: list[str] = []

    def execute_recording(self, sql, *args, **kwargs):
        if isinstance(sql, str):
            observed_statements.append(sql.strip())
        return original_execute(self, sql, *args, **kwargs)

    monkeypatch.setattr(aiosqlite.Connection, "execute", execute_recording)

    response = client.post(
        f"/calls/{bob_call}/end",
        json={"reason": "user_hung_up"},
        headers=_auth_header(alice_token),
    )

    assert response.status_code == 404
    assert not any(
        s.upper().startswith("BEGIN IMMEDIATE") for s in observed_statements
    ), (
        "Review P22: cross-user 404 must short-circuit before "
        "BEGIN IMMEDIATE to avoid holding the write lock per probe."
    )


# ---------- Story 6.5 Déviation #27 — "free gifts" anti-frustration ----------


def _now_iso(offset_seconds: int = 0) -> str:
    """ISO 8601 UTC `Z` string at now + offset. Negative offset = past."""
    return (
        (datetime.now(UTC) + timedelta(seconds=offset_seconds))
        .replace(microsecond=0)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def test_end_call_user_hung_up_never_gifted_even_short(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """`user_hung_up` is the user's deliberate choice — never gifted."""
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(
        test_db_path, user_id, started_at=_now_iso(offset_seconds=-5)
    )
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "user_hung_up"},
        headers=_auth_header(token),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "completed"
    assert data["was_gifted"] is False
    # User hasn't used any gifts this round-trip; full quota remains.
    assert data["gifts_remaining_today"] == 3


def test_end_call_survived_never_gifted_even_short(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """`survived` is a successful completion — never gifted."""
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(
        test_db_path, user_id, started_at=_now_iso(offset_seconds=-5)
    )
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "survived"},
        headers=_auth_header(token),
    )

    assert response.json()["data"]["was_gifted"] is False
    assert response.json()["data"]["status"] == "completed"


def test_end_call_network_lost_always_gifted_short_duration(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """`network_lost` ANY duration is gift-eligible (quota permitting)."""
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(
        test_db_path, user_id, started_at=_now_iso(offset_seconds=-15)
    )
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "network_lost"},
        headers=_auth_header(token),
    )

    data = response.json()["data"]
    assert data["status"] == "failed"  # gifted → excluded from cap
    assert data["was_gifted"] is True
    assert data["gifts_remaining_today"] == 2  # consumed one of three


def test_end_call_network_lost_long_duration_still_gifted(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """`network_lost` is eligible regardless of duration (vs. <30 s gate)."""
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(
        test_db_path, user_id, started_at=_now_iso(offset_seconds=-300)
    )
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "network_lost"},
        headers=_auth_header(token),
    )

    data = response.json()["data"]
    assert data["was_gifted"] is True
    assert data["duration_sec"] >= 300


def test_end_call_character_hung_up_short_is_gifted(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """`character_hung_up` <30 s → gifted (the user had a bad start)."""
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(
        test_db_path, user_id, started_at=_now_iso(offset_seconds=-15)
    )
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "character_hung_up"},
        headers=_auth_header(token),
    )

    data = response.json()["data"]
    assert data["was_gifted"] is True
    assert data["status"] == "failed"


def test_end_call_character_hung_up_long_is_not_gifted(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """`character_hung_up` >=30 s → counted normally (user had their time)."""
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(
        test_db_path, user_id, started_at=_now_iso(offset_seconds=-60)
    )
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "character_hung_up"},
        headers=_auth_header(token),
    )

    data = response.json()["data"]
    assert data["was_gifted"] is False
    assert data["status"] == "completed"


def test_end_call_inappropriate_short_is_gifted(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """`inappropriate_content` <30 s → gifted (give them another chance)."""
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(
        test_db_path, user_id, started_at=_now_iso(offset_seconds=-10)
    )
    token = issue_token(user_id)

    response = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "inappropriate_content"},
        headers=_auth_header(token),
    )

    assert response.json()["data"]["was_gifted"] is True


def test_end_call_quota_exceeded_eligible_rows_are_NOT_gifted(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """4th eligible call in the same UTC day → NOT gifted (3-per-day cap).

    Anti-abuse: a sneaky user who keeps toggling airplane mode at 4m50s
    can only grab 3 free calls per day. Past that, they consume their
    normal daily cap like everybody else.
    """
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    # 3 short network_lost calls — all gifted.
    for _ in range(3):
        call_id = _make_pending_call(
            test_db_path, user_id, started_at=_now_iso(offset_seconds=-5)
        )
        resp = client.post(
            f"/calls/{call_id}/end",
            json={"reason": "network_lost"},
            headers=_auth_header(token),
        )
        assert resp.json()["data"]["was_gifted"] is True

    # 4th — same eligibility rules, but quota is now 0.
    call_id = _make_pending_call(
        test_db_path, user_id, started_at=_now_iso(offset_seconds=-5)
    )
    resp = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "network_lost"},
        headers=_auth_header(token),
    )
    data = resp.json()["data"]
    assert data["was_gifted"] is False, "4th gift in a day must be denied"
    assert data["status"] == "completed", "Denied gift → counted normally"
    assert data["gifts_remaining_today"] == 0


def test_end_call_gifts_are_shared_across_reasons(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """3-per-day quota is GLOBAL across all eligible reasons."""
    user_id = _register_user(client, test_db_path)
    token = issue_token(user_id)

    # 1 network_lost + 1 character_hung_up short + 1 inappropriate short
    # = 3 gifts, all from different reasons.
    for reason in (
        "network_lost",
        "character_hung_up",
        "inappropriate_content",
    ):
        call_id = _make_pending_call(
            test_db_path, user_id, started_at=_now_iso(offset_seconds=-5)
        )
        resp = client.post(
            f"/calls/{call_id}/end",
            json={"reason": reason},
            headers=_auth_header(token),
        )
        assert resp.json()["data"]["was_gifted"] is True

    # 4th — quota exhausted regardless of reason.
    call_id = _make_pending_call(
        test_db_path, user_id, started_at=_now_iso(offset_seconds=-5)
    )
    resp = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "character_hung_up"},
        headers=_auth_header(token),
    )
    assert resp.json()["data"]["was_gifted"] is False


def test_end_call_gift_state_persists_across_idempotent_recalls(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """Idempotent /end returns the SAME `was_gifted` flag as the first call.

    The client's retry path may receive a response a second time (e.g.
    queued POST eventually drained AFTER the bloc retried separately).
    Both responses must report the same gift outcome so the UX stays
    coherent — no "the call was gifted! ...no wait, it wasn't" flip.
    """
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(
        test_db_path, user_id, started_at=_now_iso(offset_seconds=-10)
    )
    token = issue_token(user_id)

    first = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "network_lost"},
        headers=_auth_header(token),
    )
    first_data = first.json()["data"]
    assert first_data["was_gifted"] is True

    second = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "network_lost"},
        headers=_auth_header(token),
    )
    second_data = second.json()["data"]
    assert second_data["was_gifted"] is True
    assert second_data["status"] == first_data["status"]
    assert second_data["duration_sec"] == first_data["duration_sec"]


def test_end_call_gifted_rows_do_not_consume_daily_cap(
    client: TestClient,
    mock_resend,
    test_db_path: str,
) -> None:
    """A gifted row must NOT show up in the cap-counter query.

    The cap counter filters `status IN ('pending', 'completed')`. Gift
    flips status to 'failed', which is excluded. This regression test
    pins the contract by directly querying the cap-eligible rowcount
    after a gifted call.
    """
    user_id = _register_user(client, test_db_path)
    call_id = _make_pending_call(
        test_db_path, user_id, started_at=_now_iso(offset_seconds=-15)
    )
    token = issue_token(user_id)

    resp = client.post(
        f"/calls/{call_id}/end",
        json={"reason": "network_lost"},
        headers=_auth_header(token),
    )
    assert resp.json()["data"]["was_gifted"] is True

    conn = sqlite3.connect(test_db_path)
    cap_eligible = conn.execute(
        "SELECT COUNT(*) FROM call_sessions "
        "WHERE user_id = ? AND status IN ('pending', 'completed')",
        (user_id,),
    ).fetchone()[0]
    conn.close()
    assert cap_eligible == 0, "Gifted row must not count toward cap"
