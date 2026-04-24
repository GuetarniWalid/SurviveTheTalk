"""Refresh `tests/fixtures/prod_snapshot.sqlite` from live VPS.

Snapshot-based migration testing (Story 5.1 retro): instead of inventing
"prod-like" data in a Python fixture and watching it drift, we copy the
real production DB, sanitise PII/secrets, and commit the result. The
generic `tests/test_migrations.py` runs migrations against this snapshot
on every pytest run — any future migration that violates FK / CHECK /
integrity against the actual production shape fails CI before it ships.

Usage (from `server/`):

    .venv/Scripts/python scripts/refresh_prod_snapshot.py

Run this:
- After every successful release that touches the DB.
- After any prod data shape change you want represented in tests
  (e.g. a new user tier becomes populated).

Sanitisation rules:
- `users.email`            → `user-{id}@example.invalid`  (PII)
- `users.jwt_hash`         → NULL                         (secret)
- `auth_codes`             → DELETE all rows              (PII + ephemeral)
- everything else          → kept verbatim

Why those rules:
- The snapshot lives in git, so anything reaching git must be safe to
  share with future contributors / open-source the repo.
- We keep `users.id`, `users.tier`, `users.created_at` because the FK
  references on `call_sessions.user_id` and `user_progress.user_id`
  must stay consistent.
- `auth_codes` rows expire fast and are inserted by tests anyway, so
  wiping them costs nothing and removes 6-digit OTP secrets.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

VPS_HOST = "root@167.235.63.129"
VPS_DB_PATH = "/opt/survive-the-talk/data/db.sqlite"

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = REPO_ROOT / "tests" / "fixtures" / "prod_snapshot.sqlite"


def _scp_pull(dest: Path) -> None:
    """Copy the live VPS DB into a local temp file via scp."""
    cmd = ["scp", f"{VPS_HOST}:{VPS_DB_PATH}", str(dest)]
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def _sanitise(db_path: Path) -> None:
    """Strip PII + secrets in-place, leaving structural state intact."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "PRAGMA foreign_keys = OFF"
    )  # we modify users; FK refs stay valid by id
    try:
        # 1. Anonymise user emails + drop jwt hashes.
        rows = conn.execute("SELECT id FROM users").fetchall()
        for (uid,) in rows:
            conn.execute(
                "UPDATE users SET email = ?, jwt_hash = NULL WHERE id = ?",
                (f"user-{uid}@example.invalid", uid),
            )
        # 2. Wipe auth codes — they're short-lived secrets and tests insert their own.
        conn.execute("DELETE FROM auth_codes")
        conn.commit()
        conn.execute("VACUUM")  # reclaim deleted rows so the snapshot stays small
    finally:
        conn.close()


def _summarise(db_path: Path) -> None:
    """Print a one-screen summary so the operator can sanity-check the snapshot."""
    conn = sqlite3.connect(db_path)
    print("\n=== Snapshot summary ===")
    print(f"File: {db_path}  ({db_path.stat().st_size / 1024:.1f} KB)")

    print("\nMigrations applied:")
    for (v,) in conn.execute("SELECT version FROM schema_migrations ORDER BY version"):
        print(f"  - {v}")

    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    print("\nRow counts:")
    for t in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  - {t}: {n}")

    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    print(f"\nForeign key violations: {len(fk)}")
    print(f"Integrity check: {integrity}")
    conn.close()


def main() -> int:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        staging = Path(td) / "snapshot.sqlite"
        _scp_pull(staging)
        _sanitise(staging)
        # Atomic-ish move so the test fixture is never partially written.
        shutil.move(staging, SNAPSHOT_PATH)

    _summarise(SNAPSHOT_PATH)
    print(f"\nDone. Commit {SNAPSHOT_PATH.relative_to(REPO_ROOT)} and re-run pytest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
