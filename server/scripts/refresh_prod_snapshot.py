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
- `sqlite_sequence.auth_codes` → seq = 0  (otherwise leaks total OTPs ever issued)
- `_snapshot_meta`         → records refresh date so operators can spot a stale fixture
- everything else          → kept verbatim

Why those rules:
- The snapshot lives in git, so anything reaching git must be safe to
  share with future contributors / open-source the repo.
- We keep `users.id`, `users.tier`, `users.created_at` because the FK
  references on `call_sessions.user_id` and `user_progress.user_id`
  must stay consistent.
- `auth_codes` rows expire fast and are inserted by tests anyway, so
  wiping them costs nothing and removes 6-digit OTP secrets.

Future-monitoring (NOT yet sanitised — revisit before user count grows past ~10):
- `users.created_at` and `call_sessions.started_at` are real timestamps.
  At 1 user / 3 sessions, fingerprint risk is negligible. With more users
  these patterns enable behavioural fingerprinting — round to day or zero
  the hours.
- `call_sessions.cost_cents` is currently NULL but Story 6.x will populate
  it. Exact LLM/TTS costs leak business-cost structure — bucket it (e.g.
  round to nearest 10¢) before this column gets real values.
- `user_progress.best_score` + `attempts` are empty in prod today. Once
  the write path lands (Story 7.1), they become per-scenario telemetry
  per user — consider whether to keep individual rows or aggregate.
"""

from __future__ import annotations

import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Snapshot is considered stale past this age. _summarise() prints a warning;
# operators should re-run this script. Picked to be longer than a typical
# release cycle but short enough to catch "I haven't refreshed in months".
STALE_AFTER_DAYS = 30

VPS_HOST = "root@167.235.63.129"
VPS_DB_PATH = "/opt/survive-the-talk/data/db.sqlite"
VPS_REMOTE_TMP = "/tmp/refresh-snapshot.sqlite"

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = REPO_ROOT / "tests" / "fixtures" / "prod_snapshot.sqlite"

# Inline Python that uses the SQLite online backup API to take a consistent
# point-in-time copy without locking out pipecat. The VPS ships Python stdlib
# `sqlite3` but NOT the `sqlite3` CLI binary, so we go through python3 -c.
_BACKUP_PY = (
    "import sqlite3, sys; "
    "src = sqlite3.connect(sys.argv[1]); "
    "dst = sqlite3.connect(sys.argv[2]); "
    "src.backup(dst); "
    "src.close(); dst.close()"
)


def _ssh_pull(dest: Path) -> None:
    """Take an atomic SQLite snapshot on the VPS, then scp it locally.

    A raw `scp` of the live `db.sqlite` can capture a torn page if pipecat
    is mid-transaction. The online backup API is the canonical fix — it
    holds a read lock just long enough to copy consistent pages, without
    blocking writers.
    """
    remote_cmd = " ".join(
        shlex.quote(p)
        for p in ["python3", "-c", _BACKUP_PY, VPS_DB_PATH, VPS_REMOTE_TMP]
    )
    print(f"$ ssh {VPS_HOST} {remote_cmd!r}")
    subprocess.run(["ssh", VPS_HOST, remote_cmd], check=True)

    # Pass the destination as a basename + cwd, NOT a full path. On Windows
    # an absolute path like `C:\Users\…` can confuse older OpenSSH-Win32
    # builds: scp parses the leading `C:` as `host:` and treats the path as
    # remote. Forcing scp to see only `dest.name` (no colon, no drive letter)
    # sidesteps the issue cross-platform.
    scp_cmd = ["scp", f"{VPS_HOST}:{VPS_REMOTE_TMP}", dest.name]
    print(f"$ {' '.join(scp_cmd)}  (cwd={dest.parent})")
    try:
        subprocess.run(scp_cmd, cwd=str(dest.parent), check=True)
    finally:
        # Best-effort cleanup — never leak the temp snapshot on the VPS.
        subprocess.run(
            ["ssh", VPS_HOST, f"rm -f {shlex.quote(VPS_REMOTE_TMP)}"],
            check=False,
        )


def _verify_or_die(db_path: Path) -> None:
    """Fail loudly if the freshly-pulled file is corrupt before we sanitise it."""
    conn = sqlite3.connect(db_path)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    if result != "ok":
        raise SystemExit(f"FATAL: pulled snapshot fails integrity_check: {result}")


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
        # 3. Reset the AUTOINCREMENT counter for auth_codes — sqlite_sequence
        # retains the high-water mark even after DELETE, leaking a count of how
        # many OTPs production has ever issued. Other counters (users,
        # call_sessions) reflect IDs of rows we KEEP, so leaving them is fine.
        conn.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'auth_codes'")
        # 4. Stamp the refresh date so test runs / `_summarise()` can detect a
        # stale snapshot and prompt the operator to re-run this script.
        # Underscore-prefixed name marks it as fixture-metadata (not a prod
        # table); migrations don't touch it; tests assert it stays valid.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _snapshot_meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO _snapshot_meta (key, value) VALUES (?, ?)",
            ("refreshed_at", datetime.now(timezone.utc).isoformat()),
        )
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

    # Snapshot age — warn if older than STALE_AFTER_DAYS so the operator knows
    # to refresh before relying on stale prod-shape assumptions in tests. The
    # OperationalError branch covers pre-meta snapshots (no `_snapshot_meta`).
    try:
        refreshed_row = conn.execute(
            "SELECT value FROM _snapshot_meta WHERE key = 'refreshed_at'"
        ).fetchone()
    except sqlite3.OperationalError:
        refreshed_row = None
    if refreshed_row is not None:
        refreshed_at = datetime.fromisoformat(refreshed_row[0])
        age_days = (datetime.now(timezone.utc) - refreshed_at).days
        marker = " [STALE]" if age_days > STALE_AFTER_DAYS else ""
        print(f"Refreshed at: {refreshed_at.isoformat()} ({age_days}d ago){marker}")
    else:
        print("Refreshed at: <unknown — pre-meta snapshot, refresh to populate>")
    conn.close()


def main() -> int:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Stage on the same volume as SNAPSHOT_PATH so the final move is a real
    # rename (atomic on Windows + POSIX). A cross-volume tempdir would silently
    # degrade `shutil.move` to copy+unlink and lose atomicity.
    with tempfile.TemporaryDirectory(dir=SNAPSHOT_PATH.parent) as td:
        staging = Path(td) / "snapshot.sqlite"
        _ssh_pull(staging)
        _verify_or_die(staging)
        _sanitise(staging)
        # Atomic move so the test fixture is never partially written.
        shutil.move(staging, SNAPSHOT_PATH)

    _summarise(SNAPSHOT_PATH)
    print(f"\nDone. Commit {SNAPSHOT_PATH.relative_to(REPO_ROOT)} and re-run pytest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
