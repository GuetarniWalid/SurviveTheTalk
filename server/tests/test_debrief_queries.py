"""Story 7.1 — tests for the debrief persistence queries (AC6/AC9).

`upsert_user_progress` (the FIRST write path to `user_progress` — composable,
the caller owns the transaction), `insert_debrief` (idempotent via the UNIQUE
call_session_id), and `get_debrief_by_call_id`. Each test runs migrations
against a per-test sqlite file and seeds the FK prerequisites (user, scenarios,
call_session).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from db.database import get_connection, run_migrations
from db.queries import (
    get_debrief_by_call_id,
    insert_call_session,
    insert_debrief,
    update_debrief_analysis,
    upsert_user_progress,
)
from db.seed_scenarios import seed_scenarios

_NOW = "2026-06-08T12:00:00Z"
_SCENARIO_ID = "mugger_medium_01"


@pytest.fixture
def seeded(test_db_path):
    """Migrate + seed a user, the scenario catalog, and one call_session.

    Returns `(user_id, call_id)`.
    """

    async def _setup() -> tuple[int, int]:
        await run_migrations()
        await seed_scenarios()
        async with get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO users(email, tier, created_at) VALUES (?, 'free', ?)",
                ("u@example.invalid", _NOW),
            )
            await db.commit()
            user_id = cursor.lastrowid
            call_id = await insert_call_session(db, user_id, _SCENARIO_ID, _NOW)
        return user_id, call_id

    return asyncio.run(_setup())


# ---------- upsert_user_progress (AC6) ------------------------------------


def test_upsert_first_attempt_returns_none_best_and_attempt_one(seeded):
    user_id, _ = seeded

    async def _go():
        async with get_connection() as db:
            prev, attempt = await upsert_user_progress(
                db, user_id, _SCENARIO_ID, 50, _NOW
            )
            async with db.execute(
                "SELECT best_score, attempts FROM user_progress "
                "WHERE user_id = ? AND scenario_id = ?",
                (user_id, _SCENARIO_ID),
            ) as cur:
                row = await cur.fetchone()
        return prev, attempt, row

    prev, attempt, row = asyncio.run(_go())
    assert prev is None
    assert attempt == 1
    assert row["best_score"] == 50
    assert row["attempts"] == 1


def test_upsert_improvement_lifts_best_and_returns_previous(seeded):
    user_id, _ = seeded

    async def _go():
        async with get_connection() as db:
            await upsert_user_progress(db, user_id, _SCENARIO_ID, 50, _NOW)
            prev, attempt = await upsert_user_progress(
                db, user_id, _SCENARIO_ID, 70, _NOW
            )
            async with db.execute(
                "SELECT best_score, attempts FROM user_progress "
                "WHERE user_id = ? AND scenario_id = ?",
                (user_id, _SCENARIO_ID),
            ) as cur:
                row = await cur.fetchone()
        return prev, attempt, row

    prev, attempt, row = asyncio.run(_go())
    assert prev == 50  # captured pre-update best → debrief previous_best
    assert attempt == 2
    assert row["best_score"] == 70
    assert row["attempts"] == 2


def test_upsert_no_improvement_keeps_best_but_increments_attempts(seeded):
    user_id, _ = seeded

    async def _go():
        async with get_connection() as db:
            await upsert_user_progress(db, user_id, _SCENARIO_ID, 70, _NOW)
            prev, attempt = await upsert_user_progress(
                db, user_id, _SCENARIO_ID, 50, _NOW
            )
            async with db.execute(
                "SELECT best_score, attempts FROM user_progress "
                "WHERE user_id = ? AND scenario_id = ?",
                (user_id, _SCENARIO_ID),
            ) as cur:
                row = await cur.fetchone()
        return prev, attempt, row

    prev, attempt, row = asyncio.run(_go())
    assert prev == 70
    assert attempt == 2
    assert row["best_score"] == 70  # max(70, 50) — not lowered
    assert row["attempts"] == 2


# ---------- insert_debrief + get_debrief_by_call_id (AC9/AC8) -------------


def test_insert_debrief_persists_then_idempotent(seeded):
    _, call_id = seeded
    blob = json.dumps({"survival_pct": 73})

    async def _go():
        async with get_connection() as db:
            first = await insert_debrief(
                db,
                call_session_id=call_id,
                survival_pct=73,
                checkpoints_passed=2,
                total_checkpoints=3,
                debrief_json=blob,
                prompt_version="1.0",
                created_at=_NOW,
            )
            # Second write for the SAME call → ON CONFLICT DO NOTHING.
            second = await insert_debrief(
                db,
                call_session_id=call_id,
                survival_pct=99,
                checkpoints_passed=3,
                total_checkpoints=3,
                debrief_json=json.dumps({"survival_pct": 99}),
                prompt_version="1.0",
                created_at=_NOW,
            )
            row = await get_debrief_by_call_id(db, call_id)
        return first, second, row

    first, second, row = asyncio.run(_go())
    assert first is True
    assert second is False  # not re-inserted
    assert row["survival_pct"] == 73  # original survived
    assert row["prompt_version"] == "1.0"
    assert json.loads(row["debrief_json"])["survival_pct"] == 73


def test_get_debrief_none_when_absent(seeded):
    _, call_id = seeded

    async def _go():
        async with get_connection() as db:
            return await get_debrief_by_call_id(db, call_id)

    assert asyncio.run(_go()) is None


# ---------- Story 10.7 (Bug B) — two-phase progressive debrief ---------------


def test_insert_debrief_defaults_status_ready(seeded):
    """One-shot callers (and pre-10.7 tests) that omit `status` write a `ready`
    row — back-compat with the single-write contract."""
    _, call_id = seeded

    async def _go():
        async with get_connection() as db:
            await insert_debrief(
                db,
                call_session_id=call_id,
                survival_pct=73,
                checkpoints_passed=2,
                total_checkpoints=3,
                debrief_json=json.dumps({"survival_pct": 73}),
                prompt_version="2.2",
                created_at=_NOW,
            )
            return await get_debrief_by_call_id(db, call_id)

    row = asyncio.run(_go())
    assert row["status"] == "ready"


def test_pending_insert_then_update_to_ready(seeded):
    """The two-phase write: a `pending` score-only row, then a guarded UPDATE
    flips it to `ready` with the full blob (analysis filled in)."""
    _, call_id = seeded

    async def _go():
        async with get_connection() as db:
            inserted = await insert_debrief(
                db,
                call_session_id=call_id,
                survival_pct=66,
                checkpoints_passed=2,
                total_checkpoints=3,
                debrief_json=json.dumps({"survival_pct": 66, "errors": []}),
                prompt_version="2.2",
                created_at=_NOW,
                status="pending",
            )
            pending_row = await get_debrief_by_call_id(db, call_id)
            updated = await update_debrief_analysis(
                db,
                call_session_id=call_id,
                debrief_json=json.dumps(
                    {"survival_pct": 66, "errors": [{"user_said": "x"}]}
                ),
                status="ready",
            )
            ready_row = await get_debrief_by_call_id(db, call_id)
        return inserted, pending_row, updated, ready_row

    inserted, pending_row, updated, ready_row = asyncio.run(_go())
    assert inserted is True
    assert pending_row["status"] == "pending"
    assert json.loads(pending_row["debrief_json"])["errors"] == []
    assert updated is True
    assert ready_row["status"] == "ready"
    # The second write replaced the score-only blob with the analysis blob.
    assert json.loads(ready_row["debrief_json"])["errors"] == [{"user_said": "x"}]


def test_update_debrief_analysis_guarded_against_clobbering_ready(seeded):
    """The UPDATE is guarded `WHERE status='pending'`: once a row is `ready`, a
    duplicate/late writer (Popen retry, pooled re-run) affects 0 rows and can
    neither clobber the completed blob nor resurrect a degraded one."""
    _, call_id = seeded

    async def _go():
        async with get_connection() as db:
            await insert_debrief(
                db,
                call_session_id=call_id,
                survival_pct=66,
                checkpoints_passed=2,
                total_checkpoints=3,
                debrief_json=json.dumps({"v": "pending"}),
                prompt_version="2.2",
                created_at=_NOW,
                status="pending",
            )
            first = await update_debrief_analysis(
                db,
                call_session_id=call_id,
                debrief_json=json.dumps({"v": "ready-full"}),
                status="ready",
            )
            # A late writer tries to overwrite the already-ready row.
            second = await update_debrief_analysis(
                db,
                call_session_id=call_id,
                debrief_json=json.dumps({"v": "late-clobber"}),
                status="ready",
            )
            row = await get_debrief_by_call_id(db, call_id)
        return first, second, row

    first, second, row = asyncio.run(_go())
    assert first is True
    assert second is False  # guard blocked the clobber
    assert json.loads(row["debrief_json"])["v"] == "ready-full"


def test_update_debrief_analysis_noop_when_no_row(seeded):
    """An UPDATE with no matching row (no debrief at all) affects 0 rows."""
    _, call_id = seeded

    async def _go():
        async with get_connection() as db:
            return await update_debrief_analysis(
                db,
                call_session_id=call_id,
                debrief_json=json.dumps({"v": "x"}),
                status="ready",
            )

    assert asyncio.run(_go()) is False
