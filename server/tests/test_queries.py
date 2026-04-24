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
from db.queries import (
    get_all_scenarios_with_progress,
    get_call_session,
    insert_call_session,
    insert_user,
)
from db.seed_scenarios import seed_scenarios


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
    """Migration runner inserts every numbered migration into schema_migrations."""
    conn = sqlite3.connect(migrated_db)
    versions = {
        row[0]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    conn.close()

    assert "001_init" in versions
    assert "002_calls" in versions
    assert "003_tier_rename_full_to_paid" in versions
    assert "004_scenarios_and_user_progress" in versions
    assert "005_call_sessions_scenario_fk" in versions
    assert "006_user_progress_created_at_and_cascade" in versions


def test_migration_creates_scenarios_and_user_progress_tables(migrated_db):
    """004 creates scenarios + user_progress + idx_user_progress_user_id."""
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

    assert "scenarios" in tables
    assert "user_progress" in tables
    assert "idx_user_progress_user_id" in indexes


def test_users_check_constraint_is_free_paid(migrated_db):
    """003 rebuilds users with CHECK(tier IN ('free','paid'))."""
    conn = sqlite3.connect(migrated_db)
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()[0]
    conn.close()

    # Whitespace inside the CHECK clause varies between SQLite versions, so
    # we assert on a normalised version.
    normalised = " ".join(ddl.split())
    assert "CHECK(tier IN ('free','paid'))" in normalised
    assert "'full'" not in ddl


def test_insert_user_then_paid_update_succeeds(migrated_db):
    """`tier='paid'` is a valid value; `tier='full'` is rejected by CHECK."""

    async def _insert() -> int:
        async with get_connection() as db:
            return await insert_user(db, "walid@example.com", "2026-04-24T10:00:00Z")

    user_id = asyncio.run(_insert())

    conn = sqlite3.connect(migrated_db)
    conn.execute("UPDATE users SET tier='paid' WHERE id=?", (user_id,))
    conn.commit()
    tier = conn.execute("SELECT tier FROM users WHERE id=?", (user_id,)).fetchone()[0]
    assert tier == "paid"

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE users SET tier='full' WHERE id=?", (user_id,))
        conn.commit()
    conn.close()


def test_tier_rename_migration_succeeds_with_referencing_call_sessions(
    test_db_path,
):
    """003 rebuilds users when call_sessions FK rows already exist.

    Regression: the first VPS deploy of this story crashed because
    `DROP TABLE users` triggers a `FOREIGN KEY constraint failed` error
    when call_sessions references users(id). The fix is `PRAGMA
    foreign_keys = OFF` around the rebuild — this test guarantees that
    fix stays in place. Mirrors the production pre-state on the day
    Story 5.1 deployed: 1 user + N call_sessions referencing that user.
    """
    from db.database import MIGRATIONS_DIR

    # Apply 001 + 002 only (no 003 yet) and seed FK-referencing data.
    conn = sqlite3.connect(test_db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    for stem in ("001_init", "002_calls"):
        conn.executescript((MIGRATIONS_DIR / f"{stem}.sql").read_text(encoding="utf-8"))
    conn.execute(
        "INSERT INTO users(email, tier, created_at) VALUES (?, 'free', ?)",
        ("walid@example.com", "2026-04-24T10:00:00Z"),
    )
    user_id = conn.execute(
        "SELECT id FROM users WHERE email=?", ("walid@example.com",)
    ).fetchone()[0]
    for _ in range(3):
        conn.execute(
            "INSERT INTO call_sessions(user_id, scenario_id, started_at) "
            "VALUES (?, ?, ?)",
            (user_id, "waiter_easy_01", "2026-04-24T10:05:00Z"),
        )
    conn.commit()

    # Now apply 003 — must NOT raise IntegrityError despite the 3 FK rows.
    sql_003 = (MIGRATIONS_DIR / "003_tier_rename_full_to_paid.sql").read_text(
        encoding="utf-8"
    )
    conn.executescript(sql_003)

    # Post-state: users still has the row, call_sessions intact, CHECK is paid.
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM call_sessions").fetchone()[0] == 3
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()[0]
    assert "'paid'" in ddl
    assert "'full'" not in ddl
    conn.close()


def test_seed_scenarios_populates_five_rows(migrated_db):
    """All 5 authored YAMLs are upserted into the scenarios table."""
    asyncio.run(seed_scenarios())

    conn = sqlite3.connect(migrated_db)
    count = conn.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]
    ids = {row[0] for row in conn.execute("SELECT id FROM scenarios").fetchall()}
    conn.close()

    assert count == 5
    assert ids == {
        "waiter_easy_01",
        "mugger_medium_01",
        "girlfriend_medium_01",
        "cop_hard_01",
        "landlord_hard_01",
    }


def test_seed_scenarios_is_idempotent(migrated_db):
    """Re-running the seeder leaves row counts unchanged (no duplicate-PK error)."""
    asyncio.run(seed_scenarios())
    asyncio.run(seed_scenarios())

    conn = sqlite3.connect(migrated_db)
    count = conn.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]
    conn.close()

    assert count == 5


def test_get_all_scenarios_with_progress_left_joins_correctly(migrated_db):
    """LEFT JOIN populates progression on touched rows, leaves NULL/0 elsewhere."""
    asyncio.run(seed_scenarios())

    async def _bootstrap() -> int:
        async with get_connection() as db:
            uid = await insert_user(db, "walid@example.com", "2026-04-24T10:00:00Z")
            await db.execute(
                "INSERT INTO user_progress(user_id, scenario_id, best_score, "
                "attempts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    uid,
                    "waiter_easy_01",
                    75,
                    2,
                    "2026-04-24T10:05:00Z",
                    "2026-04-24T10:05:00Z",
                ),
            )
            await db.commit()
            return uid

    user_id = asyncio.run(_bootstrap())

    async def _fetch() -> list:
        async with get_connection() as db:
            return await get_all_scenarios_with_progress(db, user_id)

    rows = asyncio.run(_fetch())
    by_id = {row["id"]: row for row in rows}

    waiter = by_id["waiter_easy_01"]
    assert waiter["best_score"] == 75
    assert waiter["attempts"] == 2

    mugger = by_id["mugger_medium_01"]
    assert mugger["best_score"] is None
    assert mugger["attempts"] == 0


def test_scenarios_ordered_easy_medium_hard(migrated_db):
    """List ordering: difficulty bucket (easy<medium<hard) then `id` ASC.

    Asserts BOTH the bucket boundary AND the `id ASC` secondary key (within
    medium: girlfriend < mugger; within hard: cop < landlord). A regression
    that drops the secondary key and falls back to alphabetical would pass
    a bucket-only check — asserting the full id sequence catches that.
    """
    asyncio.run(seed_scenarios())

    async def _fetch() -> list:
        async with get_connection() as db:
            uid = await insert_user(db, "walid@example.com", "2026-04-24T10:00:00Z")
            return await get_all_scenarios_with_progress(db, user_id=uid)

    rows = asyncio.run(_fetch())
    ids = [row["id"] for row in rows]

    # Full ordered id sequence for the seeded 1/2/2 split — proves both
    # bucket ordering AND the id-ASC tiebreak inside each bucket.
    assert ids == [
        "waiter_easy_01",
        "girlfriend_medium_01",
        "mugger_medium_01",
        "cop_hard_01",
        "landlord_hard_01",
    ]


def test_insert_call_session_returns_id_and_persists(migrated_db):
    # Migration 005 added FK call_sessions.scenario_id → scenarios.id, so we
    # MUST seed scenarios before inserting a call_session.
    asyncio.run(seed_scenarios())

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
    asyncio.run(seed_scenarios())  # FK target for call_sessions.scenario_id

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


# ---------------------------------------------------------------------------
# Migration 005 — call_sessions FK to scenarios
# ---------------------------------------------------------------------------


def test_call_sessions_has_fk_to_scenarios(migrated_db):
    """005 rebuilds call_sessions with FK scenario_id → scenarios(id)."""
    conn = sqlite3.connect(migrated_db)
    fks = conn.execute("PRAGMA foreign_key_list(call_sessions)").fetchall()
    conn.close()

    fk_targets = {(row[2], row[3]) for row in fks}  # (table, from_col)
    assert ("scenarios", "scenario_id") in fk_targets
    assert ("users", "user_id") in fk_targets


def test_call_sessions_fk_rejects_unknown_scenario(migrated_db):
    """Inserting a call_session with non-existent scenario_id raises IntegrityError."""
    asyncio.run(seed_scenarios())

    async def _run():
        async with get_connection() as db:
            uid = await insert_user(db, "walid@example.com", "2026-04-24T10:00:00Z")
            with pytest.raises(sqlite3.IntegrityError):
                await insert_call_session(
                    db,
                    user_id=uid,
                    scenario_id="does_not_exist",
                    started_at="2026-04-24T10:05:00Z",
                )

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Migration 006 — user_progress.created_at + ON DELETE CASCADE
# ---------------------------------------------------------------------------


def test_user_progress_has_created_at_column(migrated_db):
    """006 adds the `created_at` TEXT NOT NULL column."""
    conn = sqlite3.connect(migrated_db)
    cols = {row[1]: row for row in conn.execute("PRAGMA table_info(user_progress)")}
    conn.close()

    assert "created_at" in cols
    # Column 3 of table_info is `notnull` (1 = NOT NULL).
    assert cols["created_at"][3] == 1


def test_user_progress_cascade_on_user_delete(migrated_db):
    """Deleting a user wipes their user_progress rows (ON DELETE CASCADE)."""
    asyncio.run(seed_scenarios())

    conn = sqlite3.connect(migrated_db)
    conn.execute("PRAGMA foreign_keys = ON")  # CASCADE only fires when FKs are ON
    conn.execute(
        "INSERT INTO users(email, tier, created_at) VALUES (?, 'free', ?)",
        ("walid@example.com", "2026-04-24T10:00:00Z"),
    )
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    conn.execute(
        "INSERT INTO user_progress(user_id, scenario_id, best_score, attempts, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (uid, "waiter_easy_01", 80, 1, "2026-04-24T10:05:00Z", "2026-04-24T10:05:00Z"),
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM user_progress").fetchone()[0] == 1

    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    conn.commit()
    # CASCADE: deleting the user removes the dependent user_progress row.
    assert conn.execute("SELECT COUNT(*) FROM user_progress").fetchone()[0] == 0
    conn.close()


def test_user_progress_cascade_on_scenario_delete(migrated_db):
    """Deleting a scenario wipes related user_progress rows (ON DELETE CASCADE)."""
    asyncio.run(seed_scenarios())

    conn = sqlite3.connect(migrated_db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO users(email, tier, created_at) VALUES (?, 'free', ?)",
        ("walid@example.com", "2026-04-24T10:00:00Z"),
    )
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    conn.execute(
        "INSERT INTO user_progress(user_id, scenario_id, best_score, attempts, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (uid, "waiter_easy_01", 80, 1, "2026-04-24T10:05:00Z", "2026-04-24T10:05:00Z"),
    )
    conn.commit()

    # Deleting the scenario must NOT fail on the user_progress FK reference;
    # the CASCADE removes those rows transparently. (Real prod scenarios are
    # never deleted today, but the constraint protects future cleanup paths.)
    conn.execute("DELETE FROM scenarios WHERE id = ?", ("waiter_easy_01",))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM user_progress").fetchone()[0] == 0
    conn.close()


# ---------------------------------------------------------------------------
# Seeder safety — duplicate-id detection (#10)
# ---------------------------------------------------------------------------


def test_seed_scenarios_rejects_duplicate_ids(migrated_db, tmp_path, monkeypatch):
    """Two YAMLs with the same metadata.id must fail loudly, not silently UPSERT."""
    import db.seed_scenarios as seed_module

    fake_dir = tmp_path / "scenarios"
    fake_dir.mkdir()
    base_yaml = (
        "metadata:\n"
        "  id: dup_id_01\n"
        "  title: 'A'\n"
        "  difficulty: easy\n"
        "  is_free: true\n"
        "  rive_character: x\n"
        "  language_focus: 'one, two'\n"
        "base_prompt: 'hi'\n"
        "checkpoints: []\n"
        "briefing: {vocabulary: '', context: '', expect: ''}\n"
        "exit_lines: {hangup: '', completion: ''}\n"
    )
    (fake_dir / "a.yaml").write_text(base_yaml, encoding="utf-8")
    (fake_dir / "b.yaml").write_text(base_yaml, encoding="utf-8")  # same id

    monkeypatch.setattr(seed_module, "_SCENARIOS_DIR", fake_dir)
    with pytest.raises(RuntimeError, match="Duplicate scenario id"):
        asyncio.run(seed_module.seed_scenarios())
