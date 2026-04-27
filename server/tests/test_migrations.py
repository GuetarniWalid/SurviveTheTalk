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
from pathlib import Path

from fastapi.testclient import TestClient

from db.database import run_migrations

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"


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
    """Every sanitisation rule in `scripts/refresh_prod_snapshot.py` MUST
    have a matching assertion here — these are the gates that catch a
    silently-regressed refresher BEFORE its output reaches git history.

    Add a sanitisation rule to the refresher → add an assertion here.
    """
    conn = sqlite3.connect(prod_db)
    try:
        # --- structural integrity ---
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert violations == [], (
            f"Committed snapshot has FK violations — re-run "
            f"scripts/refresh_prod_snapshot.py: {violations}"
        )
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        assert integrity == "ok", f"Snapshot integrity bad: {integrity}"

        # --- PII gates (one assertion per refresher rule) ---

        # users.email → user-{id}@example.invalid
        emails = [r[0] for r in conn.execute("SELECT email FROM users")]
        assert all(e.endswith("@example.invalid") for e in emails), (
            f"Real email leaked into snapshot: {emails!r}"
        )

        # users.jwt_hash → NULL
        bad_hashes = conn.execute(
            "SELECT id FROM users WHERE jwt_hash IS NOT NULL"
        ).fetchall()
        assert bad_hashes == [], f"jwt_hash leaked on user rows: {bad_hashes!r}"

        # auth_codes → DELETE all rows
        auth_count = conn.execute("SELECT COUNT(*) FROM auth_codes").fetchone()[0]
        assert auth_count == 0, f"auth_codes not wiped: {auth_count} rows still present"

        # auth_codes AUTOINCREMENT counter → reset to 0 (otherwise the
        # snapshot leaks total count of OTPs ever issued in production).
        seq = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'auth_codes'"
        ).fetchone()
        assert seq is None or seq[0] == 0, (
            f"auth_codes AUTOINCREMENT counter leaks usage volume: seq={seq}"
        )

        # _snapshot_meta.refreshed_at → ISO-8601 timestamp. Catches a refresher
        # that silently dropped the stamping step (operators would lose the
        # staleness signal and run blind against an arbitrarily old snapshot).
        meta_row = conn.execute(
            "SELECT value FROM _snapshot_meta WHERE key = 'refreshed_at'"
        ).fetchone()
        assert meta_row is not None, (
            "_snapshot_meta.refreshed_at missing — refresher did not stamp this snapshot"
        )
        # Parses and is a real ISO timestamp (not e.g. an empty string).
        from datetime import datetime as _dt

        _dt.fromisoformat(meta_row[0])  # raises ValueError on garbage

        # Sweep — any TEXT column anywhere whose value contains '@' but
        # doesn't end in @example.invalid is an unsanitised email-like leak.
        # Catches future columns we forgot to add to _sanitise().
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            for col in cols:
                rows = conn.execute(
                    f"SELECT {col} FROM {table} "
                    f"WHERE typeof({col}) = 'text' "
                    f"AND {col} LIKE '%@%' "
                    f"AND {col} NOT LIKE '%@example.invalid'"
                ).fetchall()
                assert rows == [], (
                    f"Unsanitised email-like value in {table}.{col}: {rows!r}"
                )
    finally:
        conn.close()


def test_snapshot_migrations_match_repo_migrations(prod_db):
    """The snapshot MUST only carry migration versions that exist as .sql
    files in the repo.

    Drift detector: catches the case where someone applies SQL ad-hoc to
    prod outside the migration system, then refreshes — the snapshot
    advertises a phantom version, and `run_migrations()` skips it because
    `schema_migrations` says it's already applied. The next migration that
    depends on the phantom's effects then crashes in prod (Story 5.1
    failure mode all over again).
    """
    repo_versions = {p.stem for p in MIGRATIONS_DIR.glob("*.sql")}
    assert repo_versions, f"No migration .sql files found in {MIGRATIONS_DIR}"

    conn = sqlite3.connect(prod_db)
    try:
        snap_versions = {
            r[0] for r in conn.execute("SELECT version FROM schema_migrations")
        }
    finally:
        conn.close()

    extra = snap_versions - repo_versions
    assert not extra, (
        f"Snapshot advertises migrations missing from repo (drift): {extra}. "
        "Either commit the missing .sql file(s) or refresh the snapshot from "
        "a VPS whose schema_migrations matches the repo."
    )
