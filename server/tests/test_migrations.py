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
    #
    # `scenarios` legitimately GROWS (the seeder upserts every YAML on each
    # startup, so a new scenario file adds a row) → asserted `>=`.
    #
    # `schema_migrations` is checked EXACTLY: after a full lifespan every repo
    # migration is recorded, so its row count must equal the number of `.sql`
    # files. An authored-but-not-yet-deployed migration absent from the snapshot
    # legitimately adds its row on replay (Story 7.1 — the snapshot only gains a
    # migration after it ships to prod and the fixture is re-pulled, a
    # deploy-time step). Asserting the exact repo count keeps `==`-grade rigor
    # (NOT a blanket `>=`, which would mask a ledger DELETE) and self-corrects to
    # an exact match once the snapshot is refreshed post-deploy. Every real user
    # table still asserts `==`, and FK/integrity are re-checked below, so the
    # Story 5.1 data-loss class stays caught.
    repo_migration_count = len(list(MIGRATIONS_DIR.glob("*.sql")))
    for table, pre in pre_counts.items():
        post = post_counts.get(table)
        assert post is not None, (
            f"Table {table!r} disappeared after lifespan — likely a buggy migration."
        )
        if table == "schema_migrations":
            assert post == repo_migration_count, (
                f"schema_migrations={post} after lifespan, expected exactly "
                f"{repo_migration_count} (one row per repo .sql migration)."
            )
        elif table == "scenarios":
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


def test_migration_011_debrief_schema(test_db_path):
    """Story 7.1 AC1 — migration 011 creates the `debriefs` table (with a
    UNIQUE index on `call_session_id`) and adds the new nullable columns to
    `call_sessions` + `scenarios`. Asserted against a freshly-migrated empty
    DB so a regression in 011's DDL fails fast.
    """
    asyncio.run(run_migrations())

    conn = sqlite3.connect(test_db_path)
    try:
        debrief_cols = {r[1] for r in conn.execute("PRAGMA table_info(debriefs)")}
        assert {
            "id",
            "call_session_id",
            "survival_pct",
            "checkpoints_passed",
            "total_checkpoints",
            "debrief_json",
            "prompt_version",
            "created_at",
        } <= debrief_cols, f"debriefs missing columns: {debrief_cols}"

        # The UNIQUE(call_session_id) constraint creates an index (origin 'u')
        # — one debrief per call. PRAGMA index_list column 2 is the unique flag.
        indexes = conn.execute("PRAGMA index_list(debriefs)").fetchall()
        assert any(row[2] == 1 for row in indexes), (
            f"debriefs has no UNIQUE index (expected on call_session_id): {indexes}"
        )

        call_cols = {r[1] for r in conn.execute("PRAGMA table_info(call_sessions)")}
        assert {"checkpoints_passed", "total_checkpoints"} <= call_cols, (
            f"call_sessions missing the server-authoritative checkpoint counts: {call_cols}"
        )

        scenario_cols = {r[1] for r in conn.execute("PRAGMA table_info(scenarios)")}
        assert "scenario_title" in scenario_cols, (
            f"scenarios missing scenario_title: {scenario_cols}"
        )
    finally:
        conn.close()


def test_migration_012_scenarios_end_phrases(test_db_path):
    """Story 7.2 AC-S1 — migration 012 adds the nullable `end_phrases`
    JSON-in-TEXT column to `scenarios` (the Call Ended overlay theatrical
    phrases). Asserted against a freshly-migrated empty DB so a regression
    in 012's DDL fails fast; the prod-snapshot replay above covers the
    populated-DB case.
    """
    asyncio.run(run_migrations())

    conn = sqlite3.connect(test_db_path)
    try:
        cols = {
            r[1]: r for r in conn.execute("PRAGMA table_info(scenarios)").fetchall()
        }
        assert "end_phrases" in cols, f"scenarios missing end_phrases: {set(cols)}"
        # PRAGMA table_info row: (cid, name, type, notnull, dflt_value, pk).
        # Must be nullable TEXT — legacy rows pre-date the column.
        assert cols["end_phrases"][2] == "TEXT"
        assert cols["end_phrases"][3] == 0, "end_phrases must be nullable"
    finally:
        conn.close()


def test_migration_014_subscriptions(test_db_path):
    """Story 8.1 AC2/AC3/AC4 — migration 014 adds the nullable
    `users.tier_changed_at` column (D3) and creates the `purchases` audit
    table (with the platform/validation_status CHECK constraints + the
    `idx_purchases_user` index). Asserted against a freshly-migrated empty
    DB so a regression in 014's DDL fails fast; the prod-snapshot replay
    above covers the populated-DB case.
    """
    asyncio.run(run_migrations())

    conn = sqlite3.connect(test_db_path)
    try:
        # users.tier_changed_at — nullable TEXT.
        user_cols = {
            r[1]: r for r in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        assert "tier_changed_at" in user_cols, (
            f"users missing tier_changed_at: {set(user_cols)}"
        )
        assert user_cols["tier_changed_at"][2] == "TEXT"
        assert user_cols["tier_changed_at"][3] == 0, "tier_changed_at must be nullable"

        # purchases — the audit table with every expected column.
        purchase_cols = {r[1] for r in conn.execute("PRAGMA table_info(purchases)")}
        assert {
            "id",
            "user_id",
            "platform",
            "product_id",
            "verification_token",
            "transaction_id",
            "validation_status",
            "expires_at",
            "created_at",
            "validated_at",
        } <= purchase_cols, f"purchases missing columns: {purchase_cols}"

        # The CHECK constraints reject out-of-domain values.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO users(email, tier, created_at) VALUES (?, 'free', ?)",
            ("buyer@example.invalid", "2026-06-16T00:00:00Z"),
        )
        try:
            conn.execute(
                "INSERT INTO purchases(user_id, platform, product_id, "
                "verification_token, created_at) VALUES (1, 'windows', 'x', 't', 'now')"
            )
            raise AssertionError("platform CHECK did not reject 'windows'")
        except sqlite3.IntegrityError:
            pass

        # F25 — the validation_status CHECK rejects an out-of-domain status
        # (the D2 lifecycle gate: pending/valid/invalid only).
        try:
            conn.execute(
                "INSERT INTO purchases(user_id, platform, product_id, "
                "verification_token, validation_status, created_at) "
                "VALUES (1, 'ios', 'x', 't-status', 'bogus', 'now')"
            )
            raise AssertionError("validation_status CHECK did not reject 'bogus'")
        except sqlite3.IntegrityError:
            pass

        # F3/F7 — verification_token is UNIQUE (dedup + cross-account backstop).
        conn.execute(
            "INSERT INTO purchases(user_id, platform, product_id, "
            "verification_token, created_at) VALUES (1, 'ios', 'x', 'dup-tok', 'now')"
        )
        try:
            conn.execute(
                "INSERT INTO purchases(user_id, platform, product_id, "
                "verification_token, created_at) VALUES (1, 'ios', 'x', 'dup-tok', 'now')"
            )
            raise AssertionError("verification_token UNIQUE did not reject a dup")
        except sqlite3.IntegrityError:
            pass

        # F25 — the FK is ON DELETE CASCADE: deleting the user removes their
        # purchases rows (no orphaned audit rows).
        conn.commit()
        before = conn.execute(
            "SELECT COUNT(*) FROM purchases WHERE user_id = 1"
        ).fetchone()[0]
        assert before >= 1
        conn.execute("DELETE FROM users WHERE id = 1")
        conn.commit()
        after = conn.execute(
            "SELECT COUNT(*) FROM purchases WHERE user_id = 1"
        ).fetchone()[0]
        assert after == 0, "ON DELETE CASCADE did not remove the user's purchases"

        # The idx_purchases_user index exists.
        index_names = {
            r[1] for r in conn.execute("PRAGMA index_list(purchases)").fetchall()
        }
        assert "idx_purchases_user" in index_names, (
            f"purchases missing idx_purchases_user: {index_names}"
        )
    finally:
        conn.close()


def test_migration_015_tier_at_call_and_subscription_events(test_db_path):
    """Story 8.3 D2/D3 — migration 015 adds the nullable
    `call_sessions.tier_at_call` column (with the free/paid CHECK) and creates
    the `subscription_events` webhook-dedup table (provider CHECK + UNIQUE
    notification_id). Asserted against a freshly-migrated empty DB so a
    regression in 015's DDL fails fast; the prod-snapshot replay above covers
    the populated-DB case.
    """
    asyncio.run(run_migrations())

    conn = sqlite3.connect(test_db_path)
    try:
        # call_sessions.tier_at_call — nullable TEXT.
        call_cols = {
            r[1]: r for r in conn.execute("PRAGMA table_info(call_sessions)").fetchall()
        }
        assert "tier_at_call" in call_cols, (
            f"call_sessions missing tier_at_call: {set(call_cols)}"
        )
        assert call_cols["tier_at_call"][2] == "TEXT"
        assert call_cols["tier_at_call"][3] == 0, "tier_at_call must be nullable"

        # The tier_at_call CHECK rejects an out-of-domain value but allows NULL.
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO users(email, tier, created_at) VALUES (?, 'free', ?)",
            ("buyer15@example.invalid", "2026-06-18T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO scenarios(id, title, is_free, rive_character, base_prompt, "
            "checkpoints, briefing, exit_lines, language_focus) "
            "VALUES ('s15', 't', 1, 'waiter', 'p', '[]', '{}', '{}', '[]')"
        )
        # NULL tier_at_call is accepted (legacy rows).
        conn.execute(
            "INSERT INTO call_sessions(user_id, scenario_id, started_at) "
            "VALUES (1, 's15', 'now')"
        )
        # A bad tier_at_call is rejected.
        try:
            conn.execute(
                "INSERT INTO call_sessions(user_id, scenario_id, started_at, "
                "tier_at_call) VALUES (1, 's15', 'now', 'platinum')"
            )
            raise AssertionError("tier_at_call CHECK did not reject 'platinum'")
        except sqlite3.IntegrityError:
            pass

        # subscription_events — the webhook-dedup ledger.
        event_cols = {
            r[1] for r in conn.execute("PRAGMA table_info(subscription_events)")
        }
        assert {
            "id",
            "provider",
            "notification_id",
            "notification_type",
            "received_at",
            "processed_at",
        } <= event_cols, f"subscription_events missing columns: {event_cols}"

        # provider CHECK rejects an out-of-domain provider.
        try:
            conn.execute(
                "INSERT INTO subscription_events(provider, notification_id, "
                "received_at) VALUES ('stripe', 'n1', 'now')"
            )
            raise AssertionError("provider CHECK did not reject 'stripe'")
        except sqlite3.IntegrityError:
            pass

        # notification_id is UNIQUE — a replayed notification is a no-op.
        conn.execute(
            "INSERT INTO subscription_events(provider, notification_id, "
            "received_at) VALUES ('apple', 'uuid-dup', 'now')"
        )
        try:
            conn.execute(
                "INSERT INTO subscription_events(provider, notification_id, "
                "received_at) VALUES ('google', 'uuid-dup', 'now')"
            )
            raise AssertionError("notification_id UNIQUE did not reject a dup")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()
