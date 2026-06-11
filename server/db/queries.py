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
    """Insert a new call_sessions row in `'pending'` state, returning the new id.

    `duration_sec` and `cost_cents` are left NULL here — `duration_sec` is
    filled in by `POST /calls/{id}/end` (Story 6.5), `cost_cents` stays NULL
    per Story 6.5 Deviation #1 (FR46 deferred post-MVP).

    `status` is set explicitly to `'pending'`, overriding the column's
    DEFAULT `'completed'`. The default exists only to backfill historical
    rows on the migration 008 path — every NEW row written via this helper
    is in-flight and must count toward the cap (Story 6.5 AC3) until
    `/end` flips it OR the janitor sweeps it to `'failed'`.
    """
    cursor = await db.execute(
        "INSERT INTO call_sessions(user_id, scenario_id, started_at, status) "
        "VALUES (?, ?, ?, 'pending')",
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


async def end_call_session(
    db: aiosqlite.Connection,
    call_id: int,
    user_id: int,
    duration_sec: int,
    *,
    gifted: bool = False,
) -> bool:
    """Flip a `'pending'` row to terminal state with the computed duration.

    Returns True if the row was flipped (first call), False if no row was
    affected — which happens when the row was already `'completed'`/
    `'failed'` (idempotent re-call) OR when the row doesn't exist OR when
    `user_id` doesn't match (cross-user). The caller disambiguates via
    `get_call_session` so the 404 / idempotent paths split correctly.

    Caller MUST be inside `BEGIN IMMEDIATE` so the SELECT-then-UPDATE pair
    is TOCTOU-safe against concurrent /end calls — same shape as the
    `/calls/initiate` cap-check transaction (see routes_calls.py:134).

    Story 6.5 Déviation #27 — when `gifted=True`, status flips to
    `'failed'` instead of `'completed'` (so the cap-counter filter
    `status IN ('pending', 'completed')` excludes it) AND `gifted=1`
    is recorded so `count_user_gifts_today` can enforce the 3-per-day
    quota. `duration_sec` is still recorded — gifted is about
    cap-counter accounting, not data loss.
    """
    terminal_status = "failed" if gifted else "completed"
    cursor = await db.execute(
        "UPDATE call_sessions SET status = ?, duration_sec = ?, gifted = ? "
        "WHERE id = ? AND user_id = ? AND status = 'pending'",
        (terminal_status, duration_sec, 1 if gifted else 0, call_id, user_id),
    )
    return cursor.rowcount == 1


# Scenario rows are stored as JSON-in-TEXT (`briefing`, `exit_lines`,
# `checkpoints`, `language_focus`, `escalation_thresholds`). This layer returns
# the raw `aiosqlite.Row` objects untouched — the route handler in
# `api/routes_scenarios.py` owns the `json.loads` step. Keeping decoding out of
# `queries.py` preserves Architecture Boundary 4 (raw-SQL only here).

# Story 6.28 — hub ordering is the explicit authored `display_order` (YAML
# `metadata.display_order`, server-side concern, never exposed on the API).
# NULLs sort LAST via the COALESCE sentinel so a future daily scenario seeded
# without an order appends at the end instead of jumping to the top; `id` is
# the stable tiebreaker.
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
    COALESCE(s.display_order, 999999999) ASC,
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

    Ordering: authored `display_order` ASC (NULLs last), then `id` ASC as
    the stable secondary key. `best_score` is NULL and `attempts` is 0 for
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
    id, title, scenario_title, display_order, is_free, rive_character,
    base_prompt, checkpoints, briefing, exit_lines, language_focus,
    content_warning,
    patience_start, fail_penalty, silence_penalty, recovery_bonus,
    silence_prompt_seconds, silence_hangup_seconds,
    ladder_impatience_seconds,
    escalation_thresholds,
    tts_voice_id, tts_speed, scoring_model,
    end_phrases
) VALUES (
    :id, :title, :scenario_title, :display_order, :is_free, :rive_character,
    :base_prompt, :checkpoints, :briefing, :exit_lines, :language_focus,
    :content_warning,
    :patience_start, :fail_penalty, :silence_penalty, :recovery_bonus,
    :silence_prompt_seconds, :silence_hangup_seconds,
    :ladder_impatience_seconds,
    :escalation_thresholds,
    :tts_voice_id, :tts_speed, :scoring_model,
    :end_phrases
)
ON CONFLICT(id) DO UPDATE SET
    title=excluded.title,
    scenario_title=excluded.scenario_title,
    display_order=excluded.display_order,
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
    ladder_impatience_seconds=excluded.ladder_impatience_seconds,
    escalation_thresholds=excluded.escalation_thresholds,
    tts_voice_id=excluded.tts_voice_id,
    tts_speed=excluded.tts_speed,
    scoring_model=excluded.scoring_model,
    end_phrases=excluded.end_phrases
"""


async def upsert_scenario(db: aiosqlite.Connection, row: dict) -> None:
    """Insert or update a scenario row by primary key.

    Used by the YAML seeder (`db/seed_scenarios.py`). Does NOT commit — the
    seeder owns the transaction so a mid-batch failure rolls the whole catalog
    back instead of leaving half-seeded rows.
    """
    await db.execute(_UPSERT_SCENARIO_SQL, row)


async def count_user_call_sessions_total(db: aiosqlite.Connection, user_id: int) -> int:
    """Lifetime cap-eligible call_sessions count (used by free-tier policy).

    Story 6.5 added the `status` filter: only `'pending'` (in-flight) and
    `'completed'` rows count toward the cap. `'failed'` rows — set by the
    janitor sweep when a `'pending'` row goes orphan past 1 h, or by the
    `/calls/initiate` Popen-rollback path — do NOT count, so the user
    eventually gets their quota back from a server-side failure.

    `'pending'` MUST count: otherwise a malicious client could POST
    /calls/initiate in a tight loop without ever calling /end and bypass
    FR21 entirely. The janitor frees abandoned `'pending'` rows after 1 h
    so the cap-counter is eventually consistent.
    """
    async with db.execute(
        "SELECT COUNT(*) FROM call_sessions "
        "WHERE user_id = ? AND status IN ('pending', 'completed')",
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def count_user_gifts_today(
    db: aiosqlite.Connection, user_id: int, since_iso: str
) -> int:
    """Count `gifted=1` call_sessions rows for the user since `since_iso`.

    Story 6.5 Déviation #27 — the "free gifts" anti-frustration system
    awards up to 3 gifted call_sessions per user per UTC day. Reasons
    that can be gifted: `network_lost` (always eligible), and
    `character_hung_up` / `inappropriate_content` when `duration_sec
    < 30`. Past the 3-per-day quota the row is counted normally (cap
    consumed) even if it would otherwise be eligible.

    `since_iso` should be today's UTC midnight as ISO 8601 with `Z`
    suffix — same shape as `started_at` for the lex comparison to
    behave temporally.
    """
    async with db.execute(
        "SELECT COUNT(*) FROM call_sessions "
        "WHERE user_id = ? AND started_at >= ? AND gifted = 1",
        (user_id, since_iso),
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def count_user_call_sessions_since(
    db: aiosqlite.Connection, user_id: int, since_iso: str
) -> int:
    """Cap-eligible call_sessions count since `since_iso` (paid-tier policy).

    `started_at` is stored as ISO 8601 UTC (per Architecture line 550), so a
    lexicographic `>=` comparison against a same-format `since_iso` is
    equivalent to a temporal comparison. Cheaper than parsing per-row.

    Story 6.5 added the `status IN ('pending', 'completed')` filter — same
    rationale as `count_user_call_sessions_total` above (`'failed'` rows
    don't count; `'pending'` rows do).
    """
    async with db.execute(
        "SELECT COUNT(*) FROM call_sessions "
        "WHERE user_id = ? AND started_at >= ? "
        "AND status IN ('pending', 'completed')",
        (user_id, since_iso),
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


# --- Story 7.1: post-call debrief persistence -------------------------------


async def upsert_user_progress(
    db: aiosqlite.Connection,
    user_id: int,
    scenario_id: str,
    survival_pct: int,
    now_iso: str,
) -> tuple[int | None, int]:
    """Record a finished attempt against `(user_id, scenario_id)` (AC6).

    Increments `attempts` by 1 and lifts `best_score` to
    `max(existing, survival_pct)`. Returns `(previous_best, attempt_number)`:
      - `previous_best` — the best_score BEFORE this attempt (None on the
        FIRST attempt) → the debrief's `previous_best`.
      - `attempt_number` — the post-increment `attempts` (1 on first attempt)
        → the debrief's `attempt_number`.

    This is the FIRST write path to `user_progress` (until 7.1 it was
    read-only via `get_*_with_progress`).

    Does NOT open or commit a transaction — the CALLER owns it. `persist_debrief`
    wraps this in a single `BEGIN IMMEDIATE` together with the idempotency CLAIM
    on `call_sessions.checkpoints_passed`, so the marker write and this attempt
    bump are one atomic unit (a crash between them can't double-count `attempts`,
    and a concurrent/retry teardown that lost the claim never reaches here). A
    direct caller must own a transaction and `commit()` for the write to persist.
    """
    async with db.execute(
        "SELECT best_score, attempts FROM user_progress "
        "WHERE user_id = ? AND scenario_id = ?",
        (user_id, scenario_id),
    ) as cursor:
        row = await cursor.fetchone()

    if row is None:
        previous_best = None
        attempt_number = 1
        await db.execute(
            "INSERT INTO user_progress "
            "(user_id, scenario_id, best_score, attempts, created_at, updated_at) "
            "VALUES (?, ?, ?, 1, ?, ?)",
            (user_id, scenario_id, survival_pct, now_iso, now_iso),
        )
    else:
        previous_best = row["best_score"]
        attempt_number = int(row["attempts"]) + 1
        new_best = (
            survival_pct
            if previous_best is None
            else max(int(previous_best), survival_pct)
        )
        await db.execute(
            "UPDATE user_progress "
            "SET best_score = ?, attempts = ?, updated_at = ? "
            "WHERE user_id = ? AND scenario_id = ?",
            (new_best, attempt_number, now_iso, user_id, scenario_id),
        )
    return previous_best, attempt_number


async def insert_debrief(
    db: aiosqlite.Connection,
    *,
    call_session_id: int,
    survival_pct: int,
    checkpoints_passed: int | None,
    total_checkpoints: int | None,
    debrief_json: str,
    prompt_version: str,
    created_at: str,
) -> bool:
    """Persist the distilled debrief for a call (one per call).

    `debrief_json` is the FULLY-ASSEMBLED client debrief (LLM core + backend
    fields + encouraging_framing) as a JSON string — the FULL transcript is
    never stored (privacy). The `call_session_id` UNIQUE constraint makes this
    idempotent: a re-run at teardown does nothing (ON CONFLICT DO NOTHING).
    Returns True if a row was inserted, False if a debrief already existed.
    """
    cursor = await db.execute(
        "INSERT INTO debriefs "
        "(call_session_id, survival_pct, checkpoints_passed, total_checkpoints, "
        "debrief_json, prompt_version, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(call_session_id) DO NOTHING",
        (
            call_session_id,
            survival_pct,
            checkpoints_passed,
            total_checkpoints,
            debrief_json,
            prompt_version,
            created_at,
        ),
    )
    await db.commit()
    return cursor.rowcount == 1


async def get_debrief_by_call_id(
    db: aiosqlite.Connection, call_id: int
) -> aiosqlite.Row | None:
    """Return the debriefs row for `call_id` (by `call_session_id`), or None."""
    async with db.execute(
        "SELECT * FROM debriefs WHERE call_session_id = ?", (call_id,)
    ) as cursor:
        return await cursor.fetchone()
