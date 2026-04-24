"""SQLite connection helper and migration runner.

The DB is the single source of truth for the auth and (later) scenarios state.
- `get_connection()` opens a per-request async connection. Always use it as an
  async context manager so the underlying file handle is released promptly.
- `run_migrations()` is called once at app startup (FastAPI lifespan) and is
  idempotent: each .sql file in `db/migrations/` is executed at most once,
  tracked via the `schema_migrations` table.

BEFORE EDITING THIS FILE: read the Story 5.1 deferred-work section in
`_bmad-output/implementation-artifacts/deferred-work.md`. Two known design
issues live here (outer-BEGIN atomicity broken by `executescript`, and the
missing `PRAGMA busy_timeout`) — fix them as a deliberate piece of work, not
accidentally alongside an unrelated change.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import AsyncIterator

import aiosqlite
from loguru import logger

from config import Settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

settings = Settings()


@asynccontextmanager
async def get_connection() -> AsyncIterator[aiosqlite.Connection]:
    """Open a SQLite connection at `settings.database_path`.

    Sets `row_factory = aiosqlite.Row` (column access by name) and enables
    foreign-key enforcement.
    """
    db = await aiosqlite.connect(settings.database_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
    finally:
        await db.close()


async def run_migrations() -> None:
    """Apply every .sql migration in `db/migrations/` exactly once.

    Order is the lexical order of filenames (e.g. `001_init.sql` before
    `002_*.sql`). Each migration is recorded in `schema_migrations` so reruns
    are no-ops. Safe to call on every startup.

    Concurrency: when uvicorn runs with `--workers N`, every worker calls this
    during its lifespan. We rely on SQLite's file-level lock via
    `BEGIN IMMEDIATE` to ensure only one worker applies a given migration;
    the others block until the winner commits, then find the version already
    recorded in `schema_migrations` and skip.
    """
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    async with get_connection() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        await db.commit()

        for migration_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = migration_file.stem
            sql = migration_file.read_text(encoding="utf-8")

            # BEGIN IMMEDIATE grabs the write lock upfront so concurrent
            # workers serialise on the migration step rather than racing to
            # `executescript`. `executescript` auto-commits between
            # statements, which is why we can't wrap the whole thing in one
            # atomic transaction — instead we re-check `schema_migrations`
            # after acquiring the lock so we never re-run a migration that
            # another worker just applied.
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    "SELECT 1 FROM schema_migrations WHERE version = ?",
                    (version,),
                ) as cursor:
                    already_applied = await cursor.fetchone() is not None
                if already_applied:
                    await db.commit()
                    continue

                logger.info("Applying DB migration: {}", version)
                await db.executescript(sql)
                await db.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (
                        version,
                        datetime.now(UTC)
                        .isoformat(timespec="seconds")
                        .replace("+00:00", "Z"),
                    ),
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
