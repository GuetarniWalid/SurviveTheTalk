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


# Scenario rows are stored as JSON-in-TEXT (`briefing`, `exit_lines`,
# `checkpoints`, `language_focus`, `escalation_thresholds`). This layer returns
# the raw `aiosqlite.Row` objects untouched — the route handler in
# `api/routes_scenarios.py` owns the `json.loads` step. Keeping decoding out of
# `queries.py` preserves Architecture Boundary 4 (raw-SQL only here).

# `CASE s.difficulty WHEN 'easy' THEN 1 ...` keeps ordering inside SQLite.
# A plain `ORDER BY difficulty` would sort the TEXT column alphabetically,
# producing easy/hard/medium — the wrong UX bucket order.
_SELECT_LIST_WITH_PROGRESS = """
SELECT
    s.*,
    up.best_score,
    COALESCE(up.attempts, 0) AS attempts
FROM scenarios s
LEFT JOIN user_progress up
    ON up.scenario_id = s.id
    AND up.user_id = :user_id
ORDER BY
    CASE s.difficulty
        WHEN 'easy' THEN 1
        WHEN 'medium' THEN 2
        WHEN 'hard' THEN 3
    END ASC,
    s.id ASC
"""

_SELECT_DETAIL_WITH_PROGRESS = """
SELECT
    s.*,
    up.best_score,
    COALESCE(up.attempts, 0) AS attempts
FROM scenarios s
LEFT JOIN user_progress up
    ON up.scenario_id = s.id
    AND up.user_id = :user_id
WHERE s.id = :scenario_id
"""


async def get_all_scenarios_with_progress(
    db: aiosqlite.Connection, user_id: int
) -> list[aiosqlite.Row]:
    """Return every scenario row LEFT-JOINed with the caller's progression.

    Ordering: difficulty bucket (easy < medium < hard), then `id` ASC as the
    stable secondary key. `best_score` is NULL and `attempts` is 0 for
    scenarios the user has never attempted.
    """
    async with db.execute(_SELECT_LIST_WITH_PROGRESS, {"user_id": user_id}) as cursor:
        return list(await cursor.fetchall())


async def get_scenario_by_id_with_progress(
    db: aiosqlite.Connection, user_id: int, scenario_id: str
) -> aiosqlite.Row | None:
    """Return a single scenario row + the caller's progression, or None."""
    async with db.execute(
        _SELECT_DETAIL_WITH_PROGRESS,
        {"user_id": user_id, "scenario_id": scenario_id},
    ) as cursor:
        return await cursor.fetchone()


_UPSERT_SCENARIO_SQL = """
INSERT INTO scenarios (
    id, title, difficulty, is_free, rive_character,
    base_prompt, checkpoints, briefing, exit_lines, language_focus,
    content_warning,
    patience_start, fail_penalty, silence_penalty, recovery_bonus,
    silence_prompt_seconds, silence_hangup_seconds,
    escalation_thresholds,
    tts_voice_id, tts_speed, scoring_model
) VALUES (
    :id, :title, :difficulty, :is_free, :rive_character,
    :base_prompt, :checkpoints, :briefing, :exit_lines, :language_focus,
    :content_warning,
    :patience_start, :fail_penalty, :silence_penalty, :recovery_bonus,
    :silence_prompt_seconds, :silence_hangup_seconds,
    :escalation_thresholds,
    :tts_voice_id, :tts_speed, :scoring_model
)
ON CONFLICT(id) DO UPDATE SET
    title=excluded.title,
    difficulty=excluded.difficulty,
    is_free=excluded.is_free,
    rive_character=excluded.rive_character,
    base_prompt=excluded.base_prompt,
    checkpoints=excluded.checkpoints,
    briefing=excluded.briefing,
    exit_lines=excluded.exit_lines,
    language_focus=excluded.language_focus,
    content_warning=excluded.content_warning,
    patience_start=excluded.patience_start,
    fail_penalty=excluded.fail_penalty,
    silence_penalty=excluded.silence_penalty,
    recovery_bonus=excluded.recovery_bonus,
    silence_prompt_seconds=excluded.silence_prompt_seconds,
    silence_hangup_seconds=excluded.silence_hangup_seconds,
    escalation_thresholds=excluded.escalation_thresholds,
    tts_voice_id=excluded.tts_voice_id,
    tts_speed=excluded.tts_speed,
    scoring_model=excluded.scoring_model
"""


async def upsert_scenario(db: aiosqlite.Connection, row: dict) -> None:
    """Insert or update a scenario row by primary key.

    Used by the YAML seeder (`db/seed_scenarios.py`). Does NOT commit — the
    seeder owns the transaction so a mid-batch failure rolls the whole catalog
    back instead of leaving half-seeded rows.
    """
    await db.execute(_UPSERT_SCENARIO_SQL, row)


async def count_user_call_sessions_total(db: aiosqlite.Connection, user_id: int) -> int:
    """Lifetime call_sessions count for a user (used by free-tier policy)."""
    async with db.execute(
        "SELECT COUNT(*) FROM call_sessions WHERE user_id = ?",
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def count_user_call_sessions_since(
    db: aiosqlite.Connection, user_id: int, since_iso: str
) -> int:
    """call_sessions count for a user since `since_iso` (used by paid-tier policy).

    `started_at` is stored as ISO 8601 UTC (per Architecture line 550), so a
    lexicographic `>=` comparison against a same-format `since_iso` is
    equivalent to a temporal comparison. Cheaper than parsing per-row.
    """
    async with db.execute(
        "SELECT COUNT(*) FROM call_sessions WHERE user_id = ? AND started_at >= ?",
        (user_id, since_iso),
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0
