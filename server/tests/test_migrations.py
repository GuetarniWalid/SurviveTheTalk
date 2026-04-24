"""Generic migration-safety tests against a real production snapshot.

Story 5.1 retro lesson: empty `test_db` hides entire bug classes (FK refs,
CHECK violations on rebuild, integrity errors after table-rebuilds with
referencing rows). The fix is structural — every pytest run replays the
full migration + lifespan against `tests/fixtures/prod_snapshot.sqlite`,
which is a sanitised copy of the live VPS DB (refresh via
`scripts/refresh_prod_snapshot.py`).

Any future migration that crashes against the real prod shape, leaves
orphan rows, breaks an index, or otherwise corrupts state will fail
these tests in CI BEFORE it ships. This is the active enforcement layer
for the rule "test against the state the code will see in production"
(see CLAUDE.md → Critical Rules).
"""

from __future__ import annotations

import asyncio
import sqlite3

from fastapi.testclient import TestClient

from db.database import run_migrations


def _row_counts(db_path: str) -> dict[str, int]:
    """Return {table_name: row_count} for every user-defined table."""
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables
        }
    finally:
        conn.close()


def test_migrations_apply_against_prod_snapshot_with_no_violations(prod_db):
    """Running migrations against the real prod shape MUST leave the DB
    consistent: no FK violations, integrity check ok.

    This is the gate that would have caught Story 5.1's tier-rename
    crash *before* the deploy: when the snapshot has 3 call_sessions
    referencing user(id=1), `DROP TABLE users` (without PRAGMA
    foreign_keys=OFF) raises IntegrityError. The test fails locally,
    Walid never deploys the bug.
    """
    asyncio.run(run_migrations())

    conn = sqlite3.connect(prod_db)
    try:
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert violations == [], f"FK violations after migration: {violations}"

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        assert integrity == "ok", f"Integrity check failed: {integrity}"
    finally:
        conn.close()


def test_full_lifespan_starts_against_prod_snapshot(prod_db):
    """Full FastAPI startup (migrations + seed_scenarios) MUST succeed
    against the real prod shape AND preserve user data.

    Catches:
      - Migration crashes against populated tables (Story 5.1 class).
      - Seeder crashes (e.g. a YAML deserialization regression).
      - Silent data loss — if a future migration accidentally truncates a
        table, this test fails because the row count drops.

    The `scenarios` table is the only legitimate growth target (the seeder
    upserts every YAML on each startup), so we assert `>=` for it and `==`
    for everything else.
    """
    pre_counts = _row_counts(prod_db)

    # TestClient(app) triggers the lifespan: run_migrations() + seed_scenarios().
    from api.app import app

    with TestClient(app):
        pass  # entering the context is enough to drive lifespan

    post_counts = _row_counts(prod_db)

    # New tables added by future migrations are allowed (post may have keys
    # pre doesn't). Existing tables must not lose rows.
    for table, pre in pre_counts.items():
        post = post_counts.get(table)
        assert post is not None, (
            f"Table {table!r} disappeared after lifespan — likely a buggy migration."
        )
        if table == "scenarios":
            assert post >= pre, f"scenarios shrunk: {pre} → {post}"
        else:
            assert post == pre, (
                f"Row count drift in {table!r}: {pre} → {post}. "
                "Migrations must preserve user data; seeder must only touch scenarios."
            )

    # Re-check integrity post-lifespan.
    conn = sqlite3.connect(prod_db)
    try:
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert violations == [], f"FK violations after full lifespan: {violations}"
    finally:
        conn.close()


def test_prod_snapshot_self_consistency(prod_db):
    """The committed snapshot itself must be valid — guards against a
    refresh that accidentally checked in a corrupt file."""
    conn = sqlite3.connect(prod_db)
    try:
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert violations == [], (
            f"Committed snapshot has FK violations — re-run "
            f"scripts/refresh_prod_snapshot.py: {violations}"
        )
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        assert integrity == "ok", f"Snapshot integrity bad: {integrity}"

        # PII sanity: the refresher MUST have anonymised emails. If a real
        # email landed in the committed fixture, the refresh script regressed.
        emails = [r[0] for r in conn.execute("SELECT email FROM users")]
        assert all(e.endswith("@example.invalid") for e in emails), (
            f"Real email leaked into snapshot: {emails!r}"
        )
    finally:
        conn.close()
