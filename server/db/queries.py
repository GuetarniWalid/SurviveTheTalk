"""Raw-SQL query layer.

All persistence operations go through these async functions — route handlers
must NEVER construct SQL strings directly. This is Architecture Boundary 4.
Each function takes an open `aiosqlite.Connection` and one statement; mutating
functions commit before returning.
"""

from __future__ import annotations

import aiosqlite


async def get_user_by_email(
    db: aiosqlite.Connection, email: str
) -> aiosqlite.Row | None:
    """Return the users row for `email`, or None."""
    async with db.execute("SELECT * FROM users WHERE email = ?", (email,)) as cursor:
        return await cursor.fetchone()


async def get_user_by_id(
    db: aiosqlite.Connection, user_id: int
) -> aiosqlite.Row | None:
    """Return the users row for `user_id`, or None."""
    async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
        return await cursor.fetchone()


async def insert_user(db: aiosqlite.Connection, email: str, created_at: str) -> int:
    """Insert a new user with tier='free' and return the new id.

    `cursor.lastrowid` is typed as `int | None` by aiosqlite because the
    underlying sqlite3 driver can return None after statements that don't
    allocate a rowid (e.g. bulk inserts, triggers). A single `INSERT ... VALUES`
    on a table with an integer PK ALWAYS yields a rowid; we assert it here so
    an unexpected None raises fast instead of corrupting downstream code.
    """
    cursor = await db.execute(
        "INSERT INTO users(email, tier, created_at) VALUES (?, 'free', ?)",
        (email, created_at),
    )
    await db.commit()
    user_id = cursor.lastrowid
    if user_id is None:
        raise RuntimeError("insert_user: sqlite returned no lastrowid")
    return user_id


async def update_user_jwt_hash(
    db: aiosqlite.Connection, user_id: int, jwt_hash: str
) -> None:
    """Persist the bcrypt hash of the most-recent JWT for the user.

    Forward-compat hook for a future "log out all devices" feature; not read
    on subsequent requests today.
    """
    await db.execute("UPDATE users SET jwt_hash = ? WHERE id = ?", (jwt_hash, user_id))
    await db.commit()


async def insert_auth_code(
    db: aiosqlite.Connection, email: str, code: str, expires_at: str
) -> None:
    """Insert a fresh auth code row (used=0)."""
    await db.execute(
        "INSERT INTO auth_codes(email, code, expires_at, used) VALUES (?, ?, ?, 0)",
        (email, code, expires_at),
    )
    await db.commit()


async def invalidate_previous_codes(db: aiosqlite.Connection, email: str) -> None:
    """Mark every still-active code for this email as used (one active at a time)."""
    await db.execute(
        "UPDATE auth_codes SET used = 1 WHERE email = ? AND used = 0", (email,)
    )
    await db.commit()


async def fetch_active_code(
    db: aiosqlite.Connection, email: str, code: str
) -> aiosqlite.Row | None:
    """Return the most-recent active (used=0) auth code matching email+code."""
    async with db.execute(
        "SELECT * FROM auth_codes WHERE email = ? AND code = ? AND used = 0 "
        "ORDER BY expires_at DESC LIMIT 1",
        (email, code),
    ) as cursor:
        return await cursor.fetchone()


class ClaimOutcome:
    """Enum-ish result of `claim_active_code` (plain class to stay stdlib-only)."""

    CLAIMED = "claimed"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"
    ALREADY_USED = "already_used"


async def claim_active_code(
    db: aiosqlite.Connection, email: str, code: str, now_iso: str
) -> tuple[str, aiosqlite.Row | None]:
    """Atomically claim a still-active, non-expired code.

    Closes the TOCTOU window between `fetch_active_code` and `mark_code_used`
    by flipping `used=0 → 1` inside a single UPDATE with a `used = 0` guard,
    then inspecting `cursor.rowcount`:

      rowcount == 1 → we just claimed a fresh row: return (CLAIMED, row)
      rowcount == 0 → either no matching row exists, or the most recent one is
                      expired, or another request already claimed it. We
                      disambiguate by reading the row (if any) to give callers
                      a precise error code.

    Returned row (when not None) is the just-claimed row for CLAIMED, or the
    most recent matching row otherwise (so callers can still use metadata for
    logging).
    """
    cursor = await db.execute(
        "UPDATE auth_codes SET used = 1 "
        "WHERE email = ? AND code = ? AND used = 0 AND expires_at >= ?",
        (email, code, now_iso),
    )
    claimed = cursor.rowcount == 1
    await db.commit()

    async with db.execute(
        "SELECT * FROM auth_codes WHERE email = ? AND code = ? "
        "ORDER BY expires_at DESC LIMIT 1",
        (email, code),
    ) as select_cursor:
        row = await select_cursor.fetchone()

    if claimed:
        return (ClaimOutcome.CLAIMED, row)
    if row is None:
        return (ClaimOutcome.NOT_FOUND, None)
    if row["used"] == 1:
        return (ClaimOutcome.ALREADY_USED, row)
    # Row exists, used=0, but we didn't claim: it must be expired.
    return (ClaimOutcome.EXPIRED, row)


async def mark_code_used(db: aiosqlite.Connection, code_id: int) -> None:
    """Mark a single auth_codes row as used."""
    await db.execute("UPDATE auth_codes SET used = 1 WHERE id = ?", (code_id,))
    await db.commit()


async def insert_call_session(
    db: aiosqlite.Connection,
    user_id: int,
    scenario_id: str,
    started_at: str,
) -> int:
    """Insert a new call_sessions row, returning the new id.

    `duration_sec` and `cost_cents` are left NULL here — they are filled in
    later by `POST /calls/{id}/end` (Story 6.4 / 7.1).
    """
    cursor = await db.execute(
        "INSERT INTO call_sessions(user_id, scenario_id, started_at) VALUES (?, ?, ?)",
        (user_id, scenario_id, started_at),
    )
    await db.commit()
    call_id = cursor.lastrowid
    if call_id is None:
        raise RuntimeError("insert_call_session: sqlite returned no lastrowid")
    return call_id


async def get_call_session(
    db: aiosqlite.Connection, call_id: int
) -> aiosqlite.Row | None:
    """Return the call_sessions row for `call_id`, or None."""
    async with db.execute(
        "SELECT * FROM call_sessions WHERE id = ?", (call_id,)
    ) as cursor:
        return await cursor.fetchone()
