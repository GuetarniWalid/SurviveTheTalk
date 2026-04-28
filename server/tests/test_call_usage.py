"""Tests for `api.usage.compute_call_usage` — the FR21 policy layer.

Hits a real `aiosqlite` connection (no mocking of the DB) so the contract
"pass me a connection and I'll count rows" is exercised end-to-end. Sessions
are inserted via raw SQL with hand-picked timestamps that straddle the UTC
midnight boundary — the `now` kwarg of `compute_call_usage` is the only
deterministic way to test day boundaries without freezing system time.

Migration 005 added `FK call_sessions.scenario_id → scenarios.id`, so
scenarios MUST be seeded before any `call_sessions` insert. We use the
existing `'waiter_easy_01'` seed row.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime

import pytest

from api.usage import CALLS_PER_PERIOD, compute_call_usage
from db.database import get_connection, run_migrations
from db.seed_scenarios import seed_scenarios


@pytest.fixture
def migrated_db(test_db_path):
    """Run migrations + seed scenarios so call_sessions FK targets exist."""
    asyncio.run(run_migrations())
    asyncio.run(seed_scenarios())
    return test_db_path


def _insert_user(db_path: str, email: str = "walid@example.com") -> int:
    """Insert a free-tier user via raw SQL and return its id."""
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "INSERT INTO users(email, tier, created_at) VALUES (?, 'free', ?)",
        (email, "2026-04-28T00:00:00Z"),
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()
    assert user_id is not None
    return user_id


def _set_tier(db_path: str, user_id: int, tier: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE users SET tier = ? WHERE id = ?", (tier, user_id))
    conn.commit()
    conn.close()


def _insert_call_session(
    db_path: str,
    user_id: int,
    started_at: str,
    scenario_id: str = "waiter_easy_01",
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO call_sessions(user_id, scenario_id, started_at) VALUES (?, ?, ?)",
        (user_id, scenario_id, started_at),
    )
    conn.commit()
    conn.close()


async def _compute(user_id: int, tier: str, *, now: datetime | None = None) -> dict:
    async with get_connection() as db:
        return await compute_call_usage(db, user_id, tier, now=now)


# ---------- Free tier (lifetime cap = 3) ----------


def test_free_zero_sessions_returns_three_remaining_lifetime(migrated_db):
    user_id = _insert_user(migrated_db)

    usage = asyncio.run(_compute(user_id, "free"))

    assert usage == {
        "tier": "free",
        "calls_remaining": CALLS_PER_PERIOD,
        "calls_per_period": CALLS_PER_PERIOD,
        "period": "lifetime",
    }


def test_free_one_session_returns_two_remaining(migrated_db):
    user_id = _insert_user(migrated_db)
    _insert_call_session(migrated_db, user_id, "2026-04-01T08:00:00Z")

    usage = asyncio.run(_compute(user_id, "free"))

    assert usage["calls_remaining"] == 2
    assert usage["period"] == "lifetime"


def test_free_three_sessions_returns_zero_remaining_clamped(migrated_db):
    user_id = _insert_user(migrated_db)
    for ts in (
        "2026-04-01T08:00:00Z",
        "2026-04-02T09:00:00Z",
        "2026-04-03T10:00:00Z",
    ):
        _insert_call_session(migrated_db, user_id, ts)

    usage = asyncio.run(_compute(user_id, "free"))

    assert usage["calls_remaining"] == 0


def test_free_more_than_three_sessions_clamps_to_zero(migrated_db):
    """Five sessions → 0 remaining (max(0, 3 - 5)), never negative."""
    user_id = _insert_user(migrated_db)
    for i in range(5):
        _insert_call_session(migrated_db, user_id, f"2026-04-0{i + 1}T10:00:00Z")

    usage = asyncio.run(_compute(user_id, "free"))

    assert usage["calls_remaining"] == 0


# ---------- Paid tier (per-day cap = 3, UTC reset) ----------


def test_paid_zero_sessions_today_returns_three_remaining_day(migrated_db):
    user_id = _insert_user(migrated_db)
    _set_tier(migrated_db, user_id, "paid")

    now = datetime(2026, 4, 28, 14, 30, tzinfo=UTC)
    usage = asyncio.run(_compute(user_id, "paid", now=now))

    assert usage == {
        "tier": "paid",
        "calls_remaining": CALLS_PER_PERIOD,
        "calls_per_period": CALLS_PER_PERIOD,
        "period": "day",
    }


def test_paid_three_sessions_today_returns_zero_remaining(migrated_db):
    user_id = _insert_user(migrated_db)
    _set_tier(migrated_db, user_id, "paid")
    # All three sessions are today (2026-04-28 UTC).
    for ts in (
        "2026-04-28T01:00:00Z",
        "2026-04-28T08:00:00Z",
        "2026-04-28T20:00:00Z",
    ):
        _insert_call_session(migrated_db, user_id, ts)

    now = datetime(2026, 4, 28, 23, 0, tzinfo=UTC)
    usage = asyncio.run(_compute(user_id, "paid", now=now))

    assert usage["calls_remaining"] == 0
    assert usage["period"] == "day"


def test_paid_three_sessions_today_plus_two_yesterday_still_zero(migrated_db):
    """Yesterday's sessions don't influence today's cap — only today counts."""
    user_id = _insert_user(migrated_db)
    _set_tier(migrated_db, user_id, "paid")
    # Three today + two yesterday.
    for ts in (
        "2026-04-28T01:00:00Z",
        "2026-04-28T08:00:00Z",
        "2026-04-28T20:00:00Z",
        "2026-04-27T10:00:00Z",
        "2026-04-27T22:00:00Z",
    ):
        _insert_call_session(migrated_db, user_id, ts)

    now = datetime(2026, 4, 28, 23, 30, tzinfo=UTC)
    usage = asyncio.run(_compute(user_id, "paid", now=now))

    assert usage["calls_remaining"] == 0


def test_paid_zero_today_with_five_yesterday_clean_slate_three_remaining(migrated_db):
    """Crossing UTC midnight resets the paid-tier counter."""
    user_id = _insert_user(migrated_db)
    _set_tier(migrated_db, user_id, "paid")
    for i in range(5):
        _insert_call_session(
            migrated_db,
            user_id,
            f"2026-04-27T0{i}:00:00Z",
        )

    now = datetime(2026, 4, 28, 0, 0, 30, tzinfo=UTC)  # just past UTC midnight
    usage = asyncio.run(_compute(user_id, "paid", now=now))

    assert usage["calls_remaining"] == CALLS_PER_PERIOD
    assert usage["period"] == "day"


# ---------- Defensive: unknown tier ----------


def test_unknown_tier_raises_value_error(migrated_db):
    user_id = _insert_user(migrated_db)

    with pytest.raises(ValueError, match="Unsupported tier"):
        asyncio.run(_compute(user_id, "garbage"))
