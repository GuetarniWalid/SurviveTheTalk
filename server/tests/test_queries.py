"""Unit tests for the raw-SQL query layer in `db/queries.py`.

Today's coverage is focused on `insert_call_session` + `get_call_session`
(added for Story 4.5 `/calls/initiate`). The auth-side queries are exercised
end-to-end through `test_auth.py`, which is why they are not re-tested here.

Tests wrap async code in `asyncio.run(...)` because the project uses plain
`pytest` (no `pytest-asyncio`), matching the style of `test_auth.py`.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from db.database import get_connection, run_migrations
from db.queries import get_call_session, insert_call_session, insert_user


@pytest.fixture
def migrated_db(test_db_path):
    """Run migrations against the per-test sqlite file, return its path."""
    asyncio.run(run_migrations())
    return test_db_path


def test_migration_creates_call_sessions_table(migrated_db):
    """002_calls.sql creates the call_sessions table + index."""
    conn = sqlite3.connect(migrated_db)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    conn.close()

    assert "call_sessions" in tables
    assert "idx_call_sessions_user_id" in indexes


def test_migration_recorded_in_schema_migrations(migrated_db):
    """Migration runner inserts '002_calls' into schema_migrations."""
    conn = sqlite3.connect(migrated_db)
    versions = {
        row[0]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    conn.close()

    assert "001_init" in versions
    assert "002_calls" in versions


def test_insert_call_session_returns_id_and_persists(migrated_db):
    async def _run() -> int:
        async with get_connection() as db:
            user_id = await insert_user(db, "walid@example.com", "2026-04-23T10:00:00Z")
            return await insert_call_session(
                db,
                user_id=user_id,
                scenario_id="waiter_easy_01",
                started_at="2026-04-23T10:05:00Z",
            )

    call_id = asyncio.run(_run())

    assert isinstance(call_id, int)
    assert call_id >= 1

    conn = sqlite3.connect(migrated_db)
    row = conn.execute(
        "SELECT user_id, scenario_id, started_at, duration_sec, cost_cents "
        "FROM call_sessions WHERE id = ?",
        (call_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] >= 1  # user_id
    assert row[1] == "waiter_easy_01"
    assert row[2] == "2026-04-23T10:05:00Z"
    # duration_sec + cost_cents are NULL until /calls/{id}/end runs (Story 6.4).
    assert row[3] is None
    assert row[4] is None


def test_get_call_session_returns_row_or_none(migrated_db):
    async def _run() -> tuple:
        async with get_connection() as db:
            user_id = await insert_user(db, "walid@example.com", "2026-04-23T10:00:00Z")
            call_id = await insert_call_session(
                db,
                user_id=user_id,
                scenario_id="waiter_easy_01",
                started_at="2026-04-23T10:05:00Z",
            )
            row = await get_call_session(db, call_id)
            missing = await get_call_session(db, 9999)
            return (user_id, row, missing)

    user_id, row, missing = asyncio.run(_run())

    assert row is not None
    assert row["user_id"] == user_id
    assert row["scenario_id"] == "waiter_easy_01"
    assert missing is None
