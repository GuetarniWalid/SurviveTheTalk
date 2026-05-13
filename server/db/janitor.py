"""Background maintenance helpers for the DB.

Today's only consumer is `sweep_abandoned_call_sessions`, called from
the FastAPI lifespan's `_janitor_loop` task (`api/app.py`). Lives here
rather than in `api/` because background maintenance is a cross-cutting
concern — future stories may add more sweep helpers, and the API layer
should not own background-task code (Architecture Boundary 4: queries
helpers stay in `db/`).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import aiosqlite

# 1 h is well past the longest possible real call duration. The slowest
# scenario uses `silence_hangup_seconds=10.0` and the PatienceTracker has
# a worst-case ladder under 5 min; doubling that and rounding up to an hour
# leaves a generous safety margin so a legitimate-but-slow call never gets
# janitored mid-conversation.
ABANDONED_AFTER = timedelta(hours=1)

# `julianday()` returns days-since-1900 as a float, format-agnostic for any
# valid ISO 8601 string SQLite accepts (handles both `Z` and `+00:00`
# suffixes uniformly). Subtracting two julianday values yields the gap in
# days; multiplying by 86_400 converts to seconds. We compare in seconds so
# the threshold is human-readable and easy to test.
_ABANDONED_AFTER_SECONDS = ABANDONED_AFTER.total_seconds()


async def sweep_abandoned_call_sessions(
    db: aiosqlite.Connection, *, now: datetime
) -> int:
    """Flip `'pending'` rows older than 1 h to `'failed'`. Return count.

    Why: a FastAPI worker crash (OOM / SIGKILL) between `/calls/initiate`'s
    INSERT and Popen completion leaves a `'pending'` row that burns a free
    user's lifetime quota for a call that never happened. The janitor is
    the eventually-consistent backstop — abandoned rows clear within one
    sweep window (15 min) of crossing the 1 h horizon.

    Idempotent: re-running flips only rows newly crossing the horizon. A
    fresh `'pending'` row younger than 1 h is untouched.

    `now` is injected (not `datetime.now(UTC)`) so unit tests can pin the
    clock without monkey-patching the module. Production caller in
    `api.app._janitor_loop` passes `datetime.now(UTC)` on every tick.

    Story 6.5 review (P23): comparison uses SQLite's `julianday()` rather
    than a lexicographic `started_at < ?` against a hand-formatted ISO
    string. Lex comparison breaks silently if any code path inserts a
    timestamp with `+00:00` offset instead of `Z` suffix — those rows
    would never sweep. `julianday()` parses both shapes uniformly.
    """
    # `now` is formatted as ISO 8601 with `Z` so SQLite's `julianday()`
    # parser accepts it identically to existing column values. We pass
    # the timestamp rather than letting SQLite read its own clock so
    # tests can pin time without monkey-patching the worker thread.
    now_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    cursor = await db.execute(
        "UPDATE call_sessions SET status = 'failed' "
        "WHERE status = 'pending' "
        "AND (julianday(?) - julianday(started_at)) * 86400.0 > ?",
        (now_iso, _ABANDONED_AFTER_SECONDS),
    )
    await db.commit()
    return cursor.rowcount or 0
