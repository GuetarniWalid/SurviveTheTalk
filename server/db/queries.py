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
    *,
    tier_at_call: str | None = None,
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

    Story 8.3 (D2) — `tier_at_call` STAMPS the user's tier at initiate time
    (migration 015). The free lifetime cap counts only `tier_at_call='free'`
    calls, so a churned paid->free user "returns where they were" (paid-era
    calls never burned a free credit). Optional / `None` (legacy callers and
    the empty default) writes NULL, which the count treats as `'free'` via
    `COALESCE(tier_at_call,'free')`.
    """
    cursor = await db.execute(
        "INSERT INTO call_sessions(user_id, scenario_id, started_at, status, "
        "tier_at_call) VALUES (?, ?, ?, 'pending', ?)",
        (user_id, scenario_id, started_at, tier_at_call),
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


async def count_user_call_sessions_total(
    db: aiosqlite.Connection, user_id: int, *, tier_at_call: str | None = None
) -> int:
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

    Story 8.3 (D2) — when `tier_at_call` is given, also filter on
    `COALESCE(tier_at_call,'free') = ?` so the free lifetime cap counts only
    free-era calls (legacy NULL rows count as free). Omitted / `None` counts
    every cap-eligible row (the pre-8.3 behaviour, preserved for any caller
    that doesn't care about the tier split).
    """
    sql = (
        "SELECT COUNT(*) FROM call_sessions "
        "WHERE user_id = ? AND status IN ('pending', 'completed')"
    )
    params: list = [user_id]
    if tier_at_call is not None:
        sql += " AND COALESCE(tier_at_call, 'free') = ?"
        params.append(tier_at_call)
    async with db.execute(sql, params) as cursor:
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
    db: aiosqlite.Connection,
    user_id: int,
    since_iso: str,
    *,
    tier_at_call: str | None = None,
) -> int:
    """Cap-eligible call_sessions count since `since_iso` (paid-tier policy).

    `started_at` is stored as ISO 8601 UTC (per Architecture line 550), so a
    lexicographic `>=` comparison against a same-format `since_iso` is
    equivalent to a temporal comparison. Cheaper than parsing per-row.

    Story 6.5 added the `status IN ('pending', 'completed')` filter — same
    rationale as `count_user_call_sessions_total` above (`'failed'` rows
    don't count; `'pending'` rows do).

    Story 8.3 (D2) — when `tier_at_call` is given, also filter on
    `COALESCE(tier_at_call,'free') = ?` so the paid daily cap counts only
    today's paid-era calls (a fresh upgrader gets a clean 3 even if they made
    a free call earlier today). Omitted / `None` counts every cap-eligible
    row in the window (the pre-8.3 behaviour).
    """
    sql = (
        "SELECT COUNT(*) FROM call_sessions "
        "WHERE user_id = ? AND started_at >= ? "
        "AND status IN ('pending', 'completed')"
    )
    params: list = [user_id, since_iso]
    if tier_at_call is not None:
        sql += " AND COALESCE(tier_at_call, 'free') = ?"
        params.append(tier_at_call)
    async with db.execute(sql, params) as cursor:
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


# --- Story 8.1: subscription / purchase persistence ------------------------


async def update_user_tier(
    db: aiosqlite.Connection,
    user_id: int,
    tier: str,
    *,
    tier_changed_at: str,
    commit: bool = True,
) -> None:
    """Flip the user's tier and STAMP `tier_changed_at` (Story 8.1, D3).

    Mutate-and-commit template — same shape as `update_user_jwt_hash`. The
    `tier_changed_at` stamp is mandatory on EVERY flip (free->paid and the
    revert paid->free): Story 8.3 owns the free-tier lifetime call-count
    rework that reads this column (deferred-work.md:401-403), but the column
    must already carry an accurate timestamp by the time 8.3 ships, so we
    stamp it from the first flip in 8.1.

    `commit=False` lets a caller fold this write into a surrounding
    `BEGIN IMMEDIATE` (the verify route's tier-flip + audit-stamp, and the
    revalidation sweep's mark-invalid + conditional-downgrade) so the pair is
    atomic — code-review 8.1 F2/F3. The caller then owns the single commit.
    """
    await db.execute(
        "UPDATE users SET tier = ?, tier_changed_at = ? WHERE id = ?",
        (tier, tier_changed_at, user_id),
    )
    if commit:
        await db.commit()


async def insert_purchase(
    db: aiosqlite.Connection,
    *,
    user_id: int,
    platform: str,
    product_id: str,
    verification_token: str,
    created_at: str,
    commit: bool = True,
) -> int:
    """Insert a `'pending'` purchases audit row and return its id.

    `verification_token` is a STORE VERIFICATION ARTIFACT (iOS JWS / Android
    purchaseToken), never payment data (NFR11). `validation_status` defaults
    to `'pending'` via the column DEFAULT — the route flips it to
    `'valid'`/`'invalid'` once Apple/Google answer (`update_purchase_validation`).

    `commit=False` lets the verify route fold the insert into its idempotency
    `BEGIN IMMEDIATE` (SELECT-then-INSERT atomic; code-review 8.1 F3). The
    `verification_token` column is UNIQUE (migration 014), so a concurrent
    duplicate that races past the in-app guard raises `aiosqlite.IntegrityError`
    — the caller treats that as an idempotent re-entry.

    Asserts `lastrowid` like `insert_user`/`insert_call_session`: a single
    `INSERT ... VALUES` on an integer-PK table always yields a rowid, so a
    `None` here means something is badly wrong — fail fast. (`lastrowid` is set
    by `execute`, before any commit, so it is valid even with `commit=False`.)
    """
    cursor = await db.execute(
        "INSERT INTO purchases"
        "(user_id, platform, product_id, verification_token, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, platform, product_id, verification_token, created_at),
    )
    if commit:
        await db.commit()
    purchase_id = cursor.lastrowid
    if purchase_id is None:
        raise RuntimeError("insert_purchase: sqlite returned no lastrowid")
    return purchase_id


async def update_purchase_validation(
    db: aiosqlite.Connection,
    purchase_id: int,
    *,
    validation_status: str,
    transaction_id: str | None,
    expires_at: str | None,
    validated_at: str,
    original_transaction_id: str | None = None,
    commit: bool = True,
) -> None:
    """Record the outcome of validating a purchase against Apple/Google.

    `validation_status` is `'valid'` or `'invalid'` (a `'pending'` row that
    the D2 optimistic-fallback path left un-flipped stays `'pending'` until
    the background re-check resolves it — see `routes_subscription`).

    Story 8.3 (F3) — `original_transaction_id` is the Apple renewal-stable key
    (None for Google / legacy callers). It is written via
    `COALESCE(?, original_transaction_id)` so passing None PRESERVES an
    already-stored value (the id is constant for a subscription's lifetime — a
    later re-validation/renew stamp must never wipe it), while a non-None value
    sets it.

    `commit=False` lets a caller fold the stamp into a surrounding
    `BEGIN IMMEDIATE` alongside the tier flip (code-review 8.1 F2/F3).
    """
    await db.execute(
        "UPDATE purchases SET validation_status = ?, transaction_id = ?, "
        "expires_at = ?, validated_at = ?, "
        "original_transaction_id = COALESCE(?, original_transaction_id) "
        "WHERE id = ?",
        (
            validation_status,
            transaction_id,
            expires_at,
            validated_at,
            original_transaction_id,
            purchase_id,
        ),
    )
    if commit:
        await db.commit()


async def count_user_valid_purchases(db: aiosqlite.Connection, user_id: int) -> int:
    """Count the user's `'valid'` purchases (Story 8.1, code-review F2).

    The background revalidation sweep uses this to make the paid->free
    downgrade CONDITIONAL: a single stale `'pending'` row re-validating
    `'invalid'` must NOT clobber a user who is still entitled via another
    confirmed (`'valid'`) purchase. 8.1 has no expiry-based tier model
    (expires_at is stored but never read for entitlement — that is 8.3's
    F11 follow-up), so a `'valid'` row means currently entitled here.
    """
    async with db.execute(
        "SELECT COUNT(*) FROM purchases "
        "WHERE user_id = ? AND validation_status = 'valid'",
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def user_has_active_entitlement(
    db: aiosqlite.Connection,
    user_id: int,
    now_iso: str,
    *,
    exclude_purchase_id: int | None = None,
) -> bool:
    """True when the user holds a `'valid'` purchase still entitling them now.

    Story 8.3 (code-review F4) — the EXPIRY-AWARE sibling of
    `count_user_valid_purchases` (which ignores `expires_at`). Mirrors the
    `NOT EXISTS` clause in `get_users_with_expired_entitlement`: a `'valid'`
    purchase with NULL expiry (defensive non-expiring), or `expires_at` strictly
    after `now_iso`, still entitles. `expires_at` is a `Z`-suffixed ISO string so
    the `> ?` compare is temporal.

    `exclude_purchase_id` skips one row — the Apple downgrade webhook passes the
    LAPSING purchase's id so the question becomes "is the user entitled via
    ANOTHER purchase?" (a new-device re-subscribe). This is robust even when the
    lapsing row's own stored `expires_at` is stale/future (an EXPIRED signal is
    authoritative regardless of what our row says), and it can't be clobbered by
    the lapsing row counting itself.
    """
    if exclude_purchase_id is None:
        async with db.execute(
            "SELECT 1 FROM purchases "
            "WHERE user_id = ? AND validation_status = 'valid' "
            "AND (expires_at IS NULL OR expires_at > ?) LIMIT 1",
            (user_id, now_iso),
        ) as cursor:
            return await cursor.fetchone() is not None
    async with db.execute(
        "SELECT 1 FROM purchases "
        "WHERE user_id = ? AND id != ? AND validation_status = 'valid' "
        "AND (expires_at IS NULL OR expires_at > ?) LIMIT 1",
        (user_id, exclude_purchase_id, now_iso),
    ) as cursor:
        return await cursor.fetchone() is not None


async def get_latest_purchase_by_token(
    db: aiosqlite.Connection, verification_token: str
) -> aiosqlite.Row | None:
    """Return the most-recent purchases row for `verification_token`, or None.

    Idempotency guard for `POST /subscription/verify`: a client retry that
    re-POSTs the same store artifact must not double-insert or double-flip.
    The route reads this first and short-circuits when the artifact is
    already recorded `'valid'`.
    """
    async with db.execute(
        "SELECT * FROM purchases WHERE verification_token = ? ORDER BY id DESC LIMIT 1",
        (verification_token,),
    ) as cursor:
        return await cursor.fetchone()


async def get_active_entitlement_expiry(
    db: aiosqlite.Connection, user_id: int
) -> str | None:
    """Return the latest `expires_at` among the user's `'valid'` purchases, or None.

    Story 8.3 (Task 2) — the steady-state source for `GET /user/profile`'s
    `subscription_expires_at` (the Manage-Subscription screen's renewal/expiry
    date, which no other endpoint exposes). `expires_at` is stored as a
    `Z`-suffixed ISO 8601 string, so `ORDER BY expires_at DESC` is chronological
    (same lexicographic-==-temporal convention as `started_at`). NULL when the
    user has no `'valid'` purchase carrying an expiry (free users, legacy rows).
    """
    async with db.execute(
        "SELECT expires_at FROM purchases "
        "WHERE user_id = ? AND validation_status = 'valid' "
        "AND expires_at IS NOT NULL "
        "ORDER BY expires_at DESC LIMIT 1",
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()
        return row["expires_at"] if row else None


async def get_users_with_expired_entitlement(
    db: aiosqlite.Connection, now_iso: str
) -> list[aiosqlite.Row]:
    """Return `'paid'` users whose entitlement has lapsed (Story 8.3 Task 4).

    A user is expired when they are `tier='paid'` but hold NO `'valid'` purchase
    with `expires_at > now`. This is the expiry-downgrade backstop's worklist:
    `downgrade_expired_entitlements` flips each to `'free'`. `expires_at` is a
    `Z`-suffixed ISO string so the `> now_iso` comparison is chronological.

    A `'valid'` purchase with NULL `expires_at` is treated as NON-expiring
    (it does not appear as a lapse) — defensive, though every subscription
    validation records an expiry. The NOT EXISTS keeps a user paid as long as
    ANY of their valid purchases is still in the future.
    """
    async with db.execute(
        "SELECT * FROM users u WHERE u.tier = 'paid' AND NOT EXISTS ("
        "  SELECT 1 FROM purchases p "
        "  WHERE p.user_id = u.id AND p.validation_status = 'valid' "
        "  AND (p.expires_at IS NULL OR p.expires_at > ?)"
        ")",
        (now_iso,),
    ) as cursor:
        return list(await cursor.fetchall())


async def get_purchase_by_transaction_id(
    db: aiosqlite.Connection, transaction_id: str
) -> aiosqlite.Row | None:
    """Return the most-recent purchases row for `transaction_id`, or None.

    Story 8.3 (Task 5) — the LEGACY/fallback resolver for the Apple webhook.
    Most-recent (`id DESC`) so a re-verified subscription's latest audit row
    wins. NOTE (F3): Apple mints a NEW `transactionId` per auto-renewal, so this
    lookup MISSES a renewal — the webhook now resolves by the renewal-stable
    `original_transaction_id` first (`get_purchase_by_original_transaction_id`)
    and only falls back here for legacy rows predating that column. The expiry
    sweep does NOT cover a missed renewal (it only DOWNGRADES, never re-grants),
    which is exactly why the original-id resolver was added.
    """
    async with db.execute(
        "SELECT * FROM purchases WHERE transaction_id = ? ORDER BY id DESC LIMIT 1",
        (transaction_id,),
    ) as cursor:
        return await cursor.fetchone()


async def get_purchase_by_original_transaction_id(
    db: aiosqlite.Connection, original_transaction_id: str
) -> aiosqlite.Row | None:
    """Return the most-recent purchases row for an Apple `originalTransactionId`.

    Story 8.3 (code-review F3) — the renewal-STABLE resolver. A DID_RENEW /
    EXPIRED / REFUND / REVOKE notification carries a per-period `transactionId`
    that changes every auto-renewal, but the SAME `originalTransactionId`, so the
    webhook resolves the user by THIS key (falling back to `transaction_id` only
    for legacy rows that predate the column). Most-recent (`id DESC`) so the
    latest audit row for the subscription wins.
    """
    async with db.execute(
        "SELECT * FROM purchases WHERE original_transaction_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (original_transaction_id,),
    ) as cursor:
        return await cursor.fetchone()


async def record_subscription_event(
    db: aiosqlite.Connection,
    *,
    provider: str,
    notification_id: str,
    notification_type: str | None,
    received_at: str,
) -> str:
    """Insert a webhook event into `subscription_events`; dedup on UNIQUE.

    Story 8.3 (Task 5/D3) — the idempotency ledger behind "ack + dedup on
    replay". Returns one of:

    - ``"new"``                — the row was NEWLY inserted; process the event.
    - ``"replay_unprocessed"`` — the `notification_id` was already recorded but
      its `processed_at` is still NULL (a PRIOR delivery failed mid-processing,
      code-review F1); the caller must RE-PROCESS so the dropped lifecycle action
      is recovered on the store's retry.
    - ``"replay_processed"``   — already recorded AND processed; a genuine replay
      → no-op.

    Recording on receipt (not after processing) keeps the dedup row durable for
    audit, but `processed_at` is the source of truth for "did the side effect
    actually land" — so a failed event stays re-deliverable rather than being
    permanently suppressed by the UNIQUE collision (the F1 hole). Commits the
    fresh insert; rolls back the collision before the processed_at read.
    """
    try:
        await db.execute(
            "INSERT INTO subscription_events"
            "(provider, notification_id, notification_type, received_at) "
            "VALUES (?, ?, ?, ?)",
            (provider, notification_id, notification_type, received_at),
        )
        await db.commit()
        return "new"
    except aiosqlite.IntegrityError:
        await db.rollback()
        async with db.execute(
            "SELECT processed_at FROM subscription_events WHERE notification_id = ?",
            (notification_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is not None and row["processed_at"] is not None:
            return "replay_processed"
        return "replay_unprocessed"


async def mark_subscription_event_processed(
    db: aiosqlite.Connection, notification_id: str, processed_at: str
) -> None:
    """Stamp `processed_at` on a subscription_events row (audit/observability)."""
    await db.execute(
        "UPDATE subscription_events SET processed_at = ? WHERE notification_id = ?",
        (processed_at, notification_id),
    )
    await db.commit()


# --- Story 10.1: GDPR account deletion (Art 17) + data export (Art 20) --------


async def delete_user_account(
    db: aiosqlite.Connection, user_id: int, email: str
) -> None:
    """Delete the user and ALL their owned rows, in FK-safe order.

    The CALLER owns the transaction (`BEGIN IMMEDIATE` + `commit`) so the whole
    deletion is one atomic unit — this function only issues the DELETEs, never
    commits (same posture as `upsert_scenario` / `upsert_user_progress`).

    FK reality (verified against `db/migrations/`, NOT assumed — Story 10.1 anti-
    pattern):
      - `debriefs.call_session_id → call_sessions(id)` has NO `ON DELETE CASCADE`
        (migration 011), so debriefs MUST be deleted BEFORE call_sessions. They
        are keyed by call_session_id (no `user_id` column), hence the subquery.
      - `call_sessions.user_id → users(id)` has NO cascade (migration 002/005),
        so it must be deleted explicitly BEFORE the user row (else the final
        `DELETE FROM users` fails the FK check — `PRAGMA foreign_keys=ON` in
        `get_connection`).
      - `user_progress.user_id` and `purchases.user_id` DO declare
        `ON DELETE CASCADE` (migrations 006 / 014), but we delete them
        explicitly anyway: deterministic, and correct even if a future migration
        drops the cascade. Belt-and-suspenders, never an orphan row.
      - `auth_codes` has no FK and no `user_id` — it is keyed by `email`.
      - `subscription_events` is a provider-keyed webhook idempotency ledger with
        NO `user_id` column (migration 015) — it holds no per-user personal data,
        so there is nothing user-scoped to delete there.
    """
    # Children of call_sessions first (no cascade on the debriefs FK).
    await db.execute(
        "DELETE FROM debriefs WHERE call_session_id IN "
        "(SELECT id FROM call_sessions WHERE user_id = ?)",
        (user_id,),
    )
    await db.execute("DELETE FROM call_sessions WHERE user_id = ?", (user_id,))
    # CASCADE-backed, deleted explicitly for determinism.
    await db.execute("DELETE FROM user_progress WHERE user_id = ?", (user_id,))
    await db.execute("DELETE FROM purchases WHERE user_id = ?", (user_id,))
    # auth_codes are keyed by email (no FK / no user_id column).
    await db.execute("DELETE FROM auth_codes WHERE email = ?", (email,))
    # Finally the parent row — every referencing child is gone by now.
    await db.execute("DELETE FROM users WHERE id = ?", (user_id,))


async def gather_user_data(db: aiosqlite.Connection, user_id: int, email: str) -> dict:
    """Return all of the user's stored data as plain JSON-serialisable dicts.

    GDPR Art 20 (data portability) — the "gather my rows" query shared by the
    export endpoint. Deliberately OMITS internal security credentials that are
    not user-facing personal data: `users.jwt_hash` (a session-token hash) and
    `purchases.verification_token` (a replayable store artifact) are excluded so
    the export can't leak a reusable credential.
    """
    out: dict = {}

    async with db.execute(
        "SELECT id, email, tier, tier_changed_at, created_at FROM users WHERE id = ?",
        (user_id,),
    ) as cursor:
        user_row = await cursor.fetchone()
    out["account"] = dict(user_row) if user_row is not None else None

    # Explicit column lists (not SELECT *) so the export contract is auditable
    # and a future migration adding an internal/credential column to either
    # table can't silently auto-leak into the user's data dump. These two tables
    # hold no credentials today — every column below is the user's own call data
    # (Art 20). Add a column here when a migration adds a user-facing one.
    async with db.execute(
        "SELECT id, user_id, scenario_id, started_at, duration_sec, cost_cents, "
        "status, checkpoints_passed, total_checkpoints, gifted, tier_at_call "
        "FROM call_sessions WHERE user_id = ? ORDER BY id",
        (user_id,),
    ) as cursor:
        out["call_sessions"] = [dict(r) for r in await cursor.fetchall()]

    async with db.execute(
        "SELECT d.id, d.call_session_id, d.survival_pct, d.checkpoints_passed, "
        "d.total_checkpoints, d.debrief_json, d.prompt_version, d.created_at "
        "FROM debriefs d "
        "JOIN call_sessions c ON d.call_session_id = c.id "
        "WHERE c.user_id = ? ORDER BY d.id",
        (user_id,),
    ) as cursor:
        out["debriefs"] = [dict(r) for r in await cursor.fetchall()]

    async with db.execute(
        "SELECT * FROM user_progress WHERE user_id = ? ORDER BY scenario_id",
        (user_id,),
    ) as cursor:
        out["progress"] = [dict(r) for r in await cursor.fetchall()]

    async with db.execute(
        "SELECT id, platform, product_id, transaction_id, original_transaction_id, "
        "validation_status, expires_at, created_at, validated_at "
        "FROM purchases WHERE user_id = ? ORDER BY id",
        (user_id,),
    ) as cursor:
        out["purchases"] = [dict(r) for r in await cursor.fetchall()]

    return out


async def get_pending_purchases(
    db: aiosqlite.Connection, limit: int = 100
) -> list[aiosqlite.Row]:
    """Return purchases still in `'pending'` validation state (D2 fallback sweep).

    The background re-validation loop (`routes_subscription` / app lifespan)
    reads these and re-checks each against Apple/Google — flipping the user
    back to `'free'` on a definitive `'invalid'` (AC3). Bounded by `limit` so
    a pathological backlog can't load an unbounded result set into memory.
    """
    async with db.execute(
        "SELECT * FROM purchases WHERE validation_status = 'pending' "
        "ORDER BY id ASC LIMIT ?",
        (limit,),
    ) as cursor:
        return list(await cursor.fetchall())
