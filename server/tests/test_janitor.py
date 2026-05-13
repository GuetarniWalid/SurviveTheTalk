"""Tests for `db.janitor.sweep_abandoned_call_sessions`.

The janitor is the eventually-consistent backstop for FR21: when a
FastAPI worker crashes between `/calls/initiate`'s INSERT and Popen
completion, the orphaned `'pending'` row would burn the user's lifetime
quota for a call that never happened. The sweep flips `'pending'` rows
older than `ABANDONED_AFTER` (1 h) to `'failed'` so the count-queries
stop counting them (per Story 6.5 AC3).

Clock control: `now` is injected per-call (Story 6.5 Deviation #10 —
`freezegun` is not in dev deps, and a kwarg is simpler than monkey-
patching the module's `datetime`). Tests pass synthetic datetimes; the
production `_janitor_loop` in `api.app` passes `datetime.now(UTC)`.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from db.database import get_connection, run_migrations
from db.janitor import sweep_abandoned_call_sessions
from db.seed_scenarios import seed_scenarios


@pytest.fixture
def migrated_db(test_db_path):
    """Run migrations + seed scenarios so call_sessions FK targets exist."""
    asyncio.run(run_migrations())
    asyncio.run(seed_scenarios())
    return test_db_path


def _insert_user(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "INSERT INTO users(email, tier, created_at) VALUES (?, 'free', ?)",
        ("walid@example.com", "2026-04-28T00:00:00Z"),
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    assert user_id is not None
    return user_id


def _insert_call_session(
    db_path: str,
    user_id: int,
    started_at: str,
    status: str,
) -> int:
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "INSERT INTO call_sessions(user_id, scenario_id, started_at, status) "
        "VALUES (?, ?, ?, ?)",
        (user_id, "waiter_easy_01", started_at, status),
    )
    call_id = cursor.lastrowid
    conn.commit()
    conn.close()
    assert call_id is not None
    return call_id


def _get_status(db_path: str, call_id: int) -> str:
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT status FROM call_sessions WHERE id = ?", (call_id,)
    ).fetchone()
    conn.close()
    return row[0]


async def _sweep_once(now: datetime) -> int:
    async with get_connection() as db:
        return await sweep_abandoned_call_sessions(db, now=now)


_NOW = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)


def test_sweep_flips_pending_rows_older_than_one_hour_to_failed(migrated_db):
    """A `'pending'` row with `started_at < now - 1h` → `'failed'`. count == 1."""
    user_id = _insert_user(migrated_db)
    # 2h ago — well past the horizon.
    stale_started = (
        (_NOW - timedelta(hours=2)).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    call_id = _insert_call_session(migrated_db, user_id, stale_started, "pending")

    count = asyncio.run(_sweep_once(_NOW))

    assert count == 1
    assert _get_status(migrated_db, call_id) == "failed"


def test_sweep_does_not_touch_pending_rows_younger_than_one_hour(migrated_db):
    """A fresh `'pending'` row (5 min old) stays `'pending'`."""
    user_id = _insert_user(migrated_db)
    fresh_started = (
        (_NOW - timedelta(minutes=5))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    call_id = _insert_call_session(migrated_db, user_id, fresh_started, "pending")

    count = asyncio.run(_sweep_once(_NOW))

    assert count == 0
    assert _get_status(migrated_db, call_id) == "pending"


def test_sweep_does_not_touch_completed_or_failed_rows(migrated_db):
    """Already-terminal rows are not re-flipped, regardless of age."""
    user_id = _insert_user(migrated_db)
    stale_iso = (
        (_NOW - timedelta(days=7)).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    completed_id = _insert_call_session(migrated_db, user_id, stale_iso, "completed")
    failed_id = _insert_call_session(migrated_db, user_id, stale_iso, "failed")

    count = asyncio.run(_sweep_once(_NOW))

    assert count == 0
    assert _get_status(migrated_db, completed_id) == "completed"
    assert _get_status(migrated_db, failed_id) == "failed"


def test_sweep_is_idempotent_on_repeat_calls(migrated_db):
    """Second sweep over the same DB flips zero additional rows."""
    user_id = _insert_user(migrated_db)
    stale_iso = (
        (_NOW - timedelta(hours=2)).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    _insert_call_session(migrated_db, user_id, stale_iso, "pending")

    first = asyncio.run(_sweep_once(_NOW))
    second = asyncio.run(_sweep_once(_NOW))

    assert first == 1
    assert second == 0


def test_sweep_returns_zero_on_empty_match_set(migrated_db):
    """No `'pending'` rows + no rows at all → 0 returned, no exception."""
    # No users, no call_sessions — empty DB.
    count = asyncio.run(_sweep_once(_NOW))

    assert count == 0


def test_sweep_handles_plus_zero_offset_timestamps(migrated_db):
    """Review P23: a row with `+00:00`-offset `started_at` MUST still sweep.

    The original implementation compared lexicographically against a
    hand-formatted `Z`-suffix string — rows inserted with a `+00:00`
    suffix would silently never sweep (eternal `'pending'`, eternal
    quota burn). The current implementation uses SQLite's
    `julianday()` which parses both formats uniformly.
    """
    user_id = _insert_user(migrated_db)
    # 2 h ago, but rendered with `+00:00` instead of `Z`.
    stale_offset = (
        (_NOW - timedelta(hours=2)).isoformat(timespec="seconds")
        # default Python output already uses `+00:00`; just keep it.
    )
    assert stale_offset.endswith("+00:00"), (
        "Test precondition: this row's started_at uses the +00:00 "
        "format that the lexicographic implementation could not sweep."
    )
    call_id = _insert_call_session(migrated_db, user_id, stale_offset, "pending")

    count = asyncio.run(_sweep_once(_NOW))

    assert count == 1
    assert _get_status(migrated_db, call_id) == "failed"
