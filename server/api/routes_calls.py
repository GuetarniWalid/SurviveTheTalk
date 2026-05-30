"""APIRouter for the call-session endpoints.

Introduced by Story 4.5 to replace the PoC `/connect` endpoint with an
authenticated, persisted call-initiation flow. `/connect` is deliberately
kept alive alongside this router (legacy compatibility) but no client
ships against it anymore. Story 6.1 added the `scenario_id` body param.
Story 6.5 added `POST /calls/{call_id}/end` for voluntary call end +
extended the Popen rollback with explicit LiveKit room cleanup.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime
from uuid import uuid4

import aiosqlite
import yaml
from fastapi import APIRouter, HTTPException, Request
from livekit import api as livekit_api
from loguru import logger
from pipecat.runner.livekit import generate_token, generate_token_with_agent

from api.middleware import AUTH_DEPENDENCY
from api.responses import now_iso, ok
from api.usage import compute_call_usage
from config import Settings
from db.database import get_connection
from db.queries import (
    count_user_gifts_today,
    end_call_session,
    get_call_session,
    get_user_by_id,
    insert_call_session,
)
from models.schemas import EndCallIn, EndCallOut, InitiateCallIn, InitiateCallOut
from pipeline.scenarios import load_scenario_metadata, load_scenario_prompt

# Story 6.5 review (P19) — bound the LiveKit cleanup so a hung DNS
# / TLS handshake on the Popen-rollback path cannot block the request
# worker indefinitely. 5 s is generous for a healthy LiveKit Cloud
# round-trip (~50-200 ms typical) but well under any request-timeout
# the client would impose.
_LIVEKIT_DELETE_TIMEOUT_SECONDS = 5.0

# Story 6.5 Déviation #27 — "free gifts" anti-frustration system.
# A user gets up to `_GIFTS_PER_DAY` `/end` calls per UTC day where
# the cap counter is NOT consumed, on reasons that are not the user's
# explicit choice. Eligibility:
#   - reason == 'network_lost'                       → always eligible
#   - reason in ('character_hung_up', 'inappropriate_content')
#         AND duration_sec < _GIFT_SHORT_THRESHOLD_SECONDS  → eligible
#   - else                                                       → NOT eligible
# Past the daily quota, an otherwise-eligible call counts normally
# (cap consumed) — anti-abuse on the "fake airplane mode at 4 min 50 s"
# pattern. The 3-per-day budget caps the cheater's free-call value at
# ~3 × ~30 ¢ ≈ 1 € of LLM/STT/TTS spend per day per user.
_GIFTS_PER_DAY = 3
_GIFT_SHORT_THRESHOLD_SECONDS = 30
# Reasons where the threshold gate applies. `'network_lost'` skips
# the gate (any duration is eligible — connection loss is genuinely
# external to the user). `'user_hung_up'` and `'survived'` are never
# eligible regardless of duration (clear user intent).
_GIFT_SHORT_THRESHOLD_REASONS = frozenset(
    {"character_hung_up", "inappropriate_content"}
)
# Story 6.11 (Deviation #3) — `'noisy_environment'` joins `'network_lost'`
# as an any-duration gift: the user can't control a parasitic background
# voice any more than they can control losing signal, so it's ALWAYS
# eligible (no `<30 s` gate). The spec's AC6 phrased this as a
# `_compute_gifted()` helper returning `True` unconditionally, but the
# existing `/end` route never grew that helper — it uses these frozensets
# inline. Adding the reason here satisfies "no duration gate" AND keeps it
# under the shared 3-per-day `within_quota` ceiling that bounds every
# gifted reason. That ceiling is exactly the "annoying enough to be self-
# limiting" backstop the story's Dev Notes call for against a user who'd
# play a video near their phone every call — an unbounded `return True`
# would remove it.
_GIFT_ANY_DURATION_REASONS = frozenset({"network_lost", "noisy_environment"})


def _today_utc_iso() -> str:
    """Today's UTC midnight as a `Z`-suffixed ISO 8601 string.

    Used to build the `since` cutoff for `count_user_gifts_today`. Lex
    comparison against the `started_at` column behaves temporally per
    the data-shape convention (see architecture.md line 550).
    """
    return (
        datetime.now(UTC)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


router = APIRouter(prefix="/calls", tags=["calls"], dependencies=[AUTH_DEPENDENCY])

settings = Settings()


async def livekit_delete_room(settings: Settings, room_name: str) -> None:
    """Explicitly delete a LiveKit room (Popen-rollback cleanup path).

    Story 6.5 Deviation #5 — verified import shape:
    `livekit.api.LiveKitAPI(url, api_key, api_secret).room.delete_room(
        DeleteRoomRequest(room=room_name))`. The SDK ships as a transitive
    dep of `pipecat-ai` (no new dependency required).

    Caller MUST wrap in `try/except` so a LiveKit-side failure does not
    mask the original failure (e.g. `BOT_SPAWN_FAILED`). This helper does
    NOT swallow its own exceptions — the caller decides the policy.

    `aclose()` releases the underlying `aiohttp.ClientSession` so we do
    not leak a TCP connection per Popen-rollback. The session is created
    per call rather than reused; the rollback path is cold enough that a
    per-call session is fine.

    Story 6.5 review (P26): constructor is wrapped so that a DNS / SSL
    failure during `LiveKitAPI(...)` itself does NOT leak an aiohttp
    session. If the constructor raises, there is nothing to close —
    propagate the exception untouched. Only on a successful construct
    do we enter the try/finally that guarantees `aclose()`.
    """
    lk = livekit_api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        await lk.room.delete_room(livekit_api.DeleteRoomRequest(room=room_name))
    finally:
        await lk.aclose()


async def _safe_livekit_delete_room(settings: Settings, room_name: str) -> None:
    """Best-effort LiveKit room cleanup with a hard timeout.

    Wraps `livekit_delete_room` in `asyncio.wait_for` so a hung remote
    cannot block the calling request worker indefinitely. All errors
    (timeout, network, LiveKit-side rejection, asyncio cancellation
    inside the helper itself) are caught and logged — the caller MUST
    NOT rely on this helper for correctness, only for cost hygiene.

    Story 6.5 review (P7, P19): consolidates the rollback-path cleanup
    so all callers share the same timeout + shielding behaviour.
    """
    try:
        await asyncio.wait_for(
            asyncio.shield(livekit_delete_room(settings, room_name)),
            timeout=_LIVEKIT_DELETE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            f"livekit_delete_room timed out for {room_name} "
            f"after {_LIVEKIT_DELETE_TIMEOUT_SECONDS}s; relying on "
            f"LiveKit's idle-room TTL"
        )
    except BaseException:
        # BaseException covers asyncio.CancelledError too — a cancelled
        # rollback must STILL log so we know cleanup never ran. We do
        # not re-raise: this helper's whole purpose is to be safe to
        # call from any cleanup path, including ones that are
        # themselves unwinding from a cancellation.
        logger.warning(
            f"livekit_delete_room failed for {room_name}",
            exc_info=True,
        )


@router.post("/initiate")
async def initiate_call(request: Request, payload: InitiateCallIn) -> dict:
    """Start a scenario call: persist a row + spawn a bot + return room creds.

    Contract:
      - `scenario_id` arrives in the request body (Story 6.1 widened
        `InitiateCallIn` from empty to `{scenario_id: str}`); resolved to a
        YAML in `pipeline/scenarios/` via `load_scenario_prompt`.
      - Auth required (JWT via `AUTH_DEPENDENCY`).
      - Cap-check (FR21 via `compute_call_usage`) runs BEFORE token mint,
        BEFORE INSERT, BEFORE bot spawn — a blocked call leaves zero
        side-effects (no row, no process, no token consumed).
      - Inserts `call_sessions(user_id, scenario_id, started_at=now_iso())`.
      - Spawns `python -m pipeline.bot` with the composed scenario prompt
        passed via the `SYSTEM_PROMPT` env var (bot reads it in `run_bot`).
      - Returns the `{data, meta}` envelope with `call_id`, `room_name`,
        user `token`, and `livekit_url` so the client can join the room.
    """
    user_id: int = request.state.user_id
    scenario_id = payload.scenario_id
    room_name = f"call-{uuid4()}"

    try:
        async with get_connection() as db:
            # 1. Cap-check (DB).
            user = await get_user_by_id(db, user_id)
            if user is None:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "code": "AUTH_UNAUTHORIZED",
                        "message": "Missing or invalid token.",
                    },
                )
            usage = await compute_call_usage(db, user_id, user["tier"])
            if usage["calls_remaining"] == 0:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "CALL_LIMIT_REACHED",
                        "message": "You've used all your calls for now.",
                    },
                )

            # 2. Scenario prompt + metadata (file IO, no DB) — fail fast on
            # bad YAML. Story 6.3 added `metadata.rive_character` plumbing so
            # the spawned bot can build character-aware classifier prompts.
            try:
                system_prompt = load_scenario_prompt(scenario_id)
                scenario_metadata = load_scenario_metadata(scenario_id)
            except (
                FileNotFoundError,
                RuntimeError,
                ValueError,
                KeyError,
                yaml.YAMLError,
            ) as exc:
                logger.exception(f"Failed to load scenario prompt for {scenario_id!r}")
                raise HTTPException(
                    status_code=500,
                    detail={
                        "code": "SCENARIO_LOAD_FAILED",
                        "message": "Could not prepare the scenario.",
                    },
                ) from exc
            rive_character = str(scenario_metadata.get("rive_character") or "waiter")

            # 3. LiveKit tokens (no DB).
            try:
                agent_token = generate_token_with_agent(
                    room_name=room_name,
                    participant_name="tina-bot",
                    api_key=settings.livekit_api_key,
                    api_secret=settings.livekit_api_secret,
                )
                user_token = generate_token(
                    room_name=room_name,
                    participant_name=f"user-{user_id}",
                    api_key=settings.livekit_api_key,
                    api_secret=settings.livekit_api_secret,
                )
            except Exception as exc:
                logger.exception("LiveKit token generation failed")
                raise HTTPException(
                    status_code=502,
                    detail={
                        "code": "LIVEKIT_TOKEN_FAILED",
                        "message": "Could not reach the call provider.",
                    },
                ) from exc

            # 4. Persist (DB) — atomic cap-check + INSERT inside BEGIN
            # IMMEDIATE so two concurrent /calls/initiate requests cannot
            # both pass the gate and both INSERT (TOCTOU race fix). The
            # early cap-check above is a fast-fail before token mint; this
            # transactional re-check is the authoritative enforcement,
            # paired with `PRAGMA busy_timeout = 5000` in `get_connection()`
            # so a contending second request blocks until the first commits
            # rather than raising `database is locked`.
            await db.execute("BEGIN IMMEDIATE")
            try:
                final_usage = await compute_call_usage(db, user_id, user["tier"])
                if final_usage["calls_remaining"] == 0:
                    await db.rollback()
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "CALL_LIMIT_REACHED",
                            "message": "You've used all your calls for now.",
                        },
                    )
                call_id = await insert_call_session(
                    db,
                    user_id=user_id,
                    scenario_id=scenario_id,
                    started_at=now_iso(),
                )
                await db.commit()
            except HTTPException:
                # Already rolled back above on cap-hit; bubble untouched.
                raise
            except BaseException:
                await db.rollback()
                raise
    except HTTPException:
        # Already-shaped failures bubble untouched — they carry their own
        # status code + envelope (401 / 403 / 500 / 502).
        raise
    except Exception as exc:
        # Catch-all for unexpected DB / connection-level failures around
        # the hot path (lost lock, disk full, etc.). Surfaces the same
        # envelope as a failed INSERT so clients have one error to branch
        # on for "couldn't record the call".
        logger.exception("Unexpected error during /calls/initiate hot path")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "CALL_PERSIST_FAILED",
                "message": "Could not record the call session.",
            },
        ) from exc

    # Bot spawn is the LAST side-effect so a failure only needs to rollback
    # the DB row, not also try to kill an in-flight process. The rollback
    # opens a fresh connection because the hot-path connection closed when
    # `async with` exited above.
    bot_env = {
        **os.environ,
        "SYSTEM_PROMPT": system_prompt,
        "SCENARIO_CHARACTER": rive_character,
        "SCENARIO_ID": scenario_id,
    }
    try:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pipeline.bot",
                "--url",
                settings.livekit_url,
                "--room",
                room_name,
                "--token",
                agent_token,
            ],
            env=bot_env,
        )
    except OSError as exc:
        logger.exception(f"Failed to spawn pipeline bot for room {room_name}")
        # Story 6.5 review (D3): flip the row to `'failed'` rather than
        # hard-DELETE. The `count_user_call_sessions_*` filter excludes
        # `'failed'` rows so the cap counter is freed immediately
        # (same UX as the original DELETE), but the audit trail is
        # preserved — operators can grep `'failed'` rows to monitor
        # Popen failure rates. Symmetric with the janitor sweep, which
        # also FLIPs abandoned `'pending'` rows to `'failed'`.
        async with get_connection() as db:
            await db.execute(
                "UPDATE call_sessions SET status = 'failed' WHERE id = ?",
                (call_id,),
            )
            await db.commit()
        # Story 6.5: explicit LiveKit cleanup so the minted-but-unused
        # room does not idle for ~5 min on the billing side. Wrapped in
        # the safe helper (timeout + shield + log-only) so a LiveKit-side
        # failure does NOT mask the BOT_SPAWN_FAILED envelope — the
        # user's experience is identical.
        await _safe_livekit_delete_room(settings, room_name)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "BOT_SPAWN_FAILED",
                "message": "Could not start the conversation agent.",
            },
        ) from exc

    logger.info(f"Spawned tutorial bot for room {room_name} (user {user_id})")

    return ok(
        InitiateCallOut(
            call_id=call_id,
            room_name=room_name,
            token=user_token,
            livekit_url=settings.livekit_url,
        )
    )


@router.post("/{call_id}/end")
async def end_call(
    call_id: int,
    request: Request,
    payload: EndCallIn,
) -> dict:
    """End a call session: flip status → completed, compute duration_sec.

    Idempotent — calling twice on the same `call_id` is a no-op on the
    second call (returns the same envelope; does NOT re-flip the status
    nor recompute `duration_sec` from the second-call "now").

    Cross-user calls return 404 (NOT 403) so the endpoint cannot be used
    to enumerate other users' `call_id`s — same info-leak pattern as the
    scenario-detail endpoint.

    Story 6.5 Deviation #1: `cost_cents` stays NULL — FR46 (operator cost
    tracking) is deferred post-MVP; the per-provider rate sheet has never
    been authored.
    Story 6.5 Deviation #2: debrief generation is stubbed — Story 7.1 owns
    the LLM analyzer and the `debriefs` table.
    Story 6.5 Deviation #3: no explicit `livekit.delete_room` on the happy
    path — LiveKit's idle-room TTL (~5 min) handles cleanup. Explicit
    cleanup ships only on the Popen rollback path (see /initiate).
    """
    user_id: int = request.state.user_id

    async with get_connection() as db:
        # Story 6.5 review (P22): cheap read-only ownership / existence
        # check BEFORE `BEGIN IMMEDIATE`. This keeps a malicious
        # enumerator probing other users' call_ids from acquiring (and
        # holding) the global write lock per probe — they get a 404
        # back fast on a read-only SELECT, no write-side amplification.
        # The authoritative re-check inside BEGIN IMMEDIATE below keeps
        # TOCTOU safety: if the row was deleted (it never is — we
        # FLIP, not DELETE — but the inner SELECT still re-verifies)
        # or status-flipped between the two reads, the inner branch
        # observes the current state.
        pre_row = await get_call_session(db, call_id)
        if pre_row is None or pre_row["user_id"] != user_id:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "CALL_NOT_FOUND",
                    "message": "Call not found.",
                },
            )

        # BEGIN IMMEDIATE serialises the SELECT-then-UPDATE pair against
        # concurrent /end calls so the idempotency check + status flip is
        # atomic (same TOCTOU-safe pattern as /initiate's cap-check).
        # Story 6.5 review (P17): `OperationalError("database is
        # locked")` under sustained contention surfaces as a 503 with
        # Retry-After so the client (or its retry layer) can back off
        # instead of seeing a generic 500 the user-facing surface treats
        # as a permanent failure.
        try:
            await db.execute("BEGIN IMMEDIATE")
        except aiosqlite.OperationalError as exc:
            if "database is locked" in str(exc).lower():
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "DB_BUSY",
                        "message": "Try again in a moment.",
                    },
                    headers={"Retry-After": "1"},
                ) from exc
            raise

        try:
            row = await get_call_session(db, call_id)

            # 404 covers BOTH "no such call_id" AND "call_id belongs to
            # another user" — info-leak prevention. Same envelope shape so
            # a malicious enumerator cannot distinguish the two. The
            # pre-check above caught the cheap case; this re-check
            # protects against a row vanishing between the two reads
            # (defensive — today's code path never deletes).
            if row is None or row["user_id"] != user_id:
                await db.rollback()
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "CALL_NOT_FOUND",
                        "message": "Call not found.",
                    },
                )

            current_status = row["status"]

            if current_status in ("completed", "failed"):
                # Idempotent re-call: return the persisted duration without
                # re-flipping. The first /end's "now" is the authoritative
                # end-time; a second /end must NOT overwrite it.
                await db.commit()
                stored_duration_raw = row["duration_sec"]
                if stored_duration_raw is None:
                    # Story 6.5 review (P6): a terminal row with NULL
                    # duration_sec violates the invariant established
                    # by `end_call_session` (always writes a non-NULL
                    # int) and the migration 008 backfill (legacy rows
                    # get `'completed'` status but their duration is
                    # already NULL — they pre-date the column). Log
                    # loudly so the data-integrity bug surfaces. Don't
                    # crash the request: return 0 so the client's
                    # fire-and-forget path still treats this as
                    # terminal and unsticks the cap counter.
                    logger.error(
                        "call_ended_null_duration "
                        f"call_id={call_id} user_id={user_id} "
                        f"status={current_status} "
                        "— terminal row with NULL duration_sec"
                    )
                stored_duration = (
                    int(stored_duration_raw) if stored_duration_raw is not None else 0
                )
                # Story 6.5 Déviation #27 — idempotent re-call returns
                # the gift flag from the persisted row. The client uses
                # it on retry paths so the gift notice screen still
                # appears even if the original POST's response was
                # lost (e.g. the bloc retried after a queued POST
                # eventually drained but the client missed the first
                # response).
                stored_gifted = bool(row["gifted"])
                gifts_today = await count_user_gifts_today(
                    db, user_id, _today_utc_iso()
                )
                return ok(
                    EndCallOut(
                        call_id=call_id,
                        status=current_status,
                        duration_sec=stored_duration,
                        was_gifted=stored_gifted,
                        gifts_remaining_today=max(0, _GIFTS_PER_DAY - gifts_today),
                    )
                )

            # First /end on a 'pending' row: compute duration_sec from
            # started_at + now(). Clamp to >= 0 defensively — a clock skew
            # or a malformed timestamp must not produce a negative
            # duration that downstream cost-calc would mishandle.
            #
            # Story 6.5 review (P20): defensive parse — `started_at`
            # SHOULD always be a `Z`-suffixed ISO 8601 string set by
            # `responses.now_iso()`, but a NULL value (corrupt row, a
            # future migration that forgot to backfill) or a format
            # drift would otherwise raise AttributeError / ValueError
            # and surface as a 500. We log + use duration_sec=0 so the
            # client still observes a clean terminal state and the cap
            # counter is unstuck; the operator sees the log.
            raw_started_at = row["started_at"]
            try:
                # Python 3.11+ accepts the `Z` suffix natively; older
                # paths fall through `replace`. Keep the replace for
                # belt-and-braces.
                started_at = datetime.fromisoformat(
                    raw_started_at.replace("Z", "+00:00")
                )
                duration_sec = max(
                    0,
                    int((datetime.now(UTC) - started_at).total_seconds()),
                )
            except (AttributeError, TypeError, ValueError):
                logger.exception(
                    "call_ended_bad_started_at "
                    f"call_id={call_id} user_id={user_id} "
                    f"raw_started_at={raw_started_at!r} "
                    "— defaulting duration_sec=0"
                )
                duration_sec = 0

            # Story 6.5 Déviation #27 — decide gift eligibility BEFORE
            # writing terminal state. The gifts_today count is read
            # inside the BEGIN IMMEDIATE so two simultaneous /end
            # requests on the same user can both arrive at the 3-per-day
            # ceiling at most once — past that, even an otherwise-
            # eligible row counts normally. (Strictly speaking the
            # write-lock pattern serialises both reads anyway, so the
            # race is mathematically impossible; defensive reasoning
            # documented for readers who haven't internalised aiosqlite
            # transaction semantics.)
            today_iso = _today_utc_iso()
            gifts_today = await count_user_gifts_today(db, user_id, today_iso)
            eligible_by_rule = payload.reason in _GIFT_ANY_DURATION_REASONS or (
                payload.reason in _GIFT_SHORT_THRESHOLD_REASONS
                and duration_sec < _GIFT_SHORT_THRESHOLD_SECONDS
            )
            within_quota = gifts_today < _GIFTS_PER_DAY
            was_gifted = eligible_by_rule and within_quota
            flipped = await end_call_session(
                db,
                call_id=call_id,
                user_id=user_id,
                duration_sec=duration_sec,
                gifted=was_gifted,
            )
            if not flipped:
                # Race: another /end fired between our SELECT and UPDATE.
                # BEGIN IMMEDIATE should prevent this; defensive rollback
                # + 404 keeps us safe if the contract ever drifts.
                await db.rollback()
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "CALL_NOT_FOUND",
                        "message": "Call not found.",
                    },
                )
            await db.commit()
        except HTTPException:
            raise
        except BaseException:
            await db.rollback()
            raise

    # Optional: livekit.delete_room(room_name) — relying on LiveKit's
    # idle-room TTL (~5 min) for empty-room cleanup. See Story 6.5
    # Deviation #3 in the story file's Implementation Notes.

    # TODO(Story 7.1): trigger debrief generation here.

    logger.info(
        f"call_ended call_id={call_id} user_id={user_id} "
        f"reason={payload.reason} duration_sec={duration_sec} "
        f"gifted={was_gifted}"
    )

    # gifts_remaining is "after this call" — if was_gifted, we just
    # consumed one, so the client sees N-1. If not gifted, count is
    # unchanged. Clamped to 0 defensively.
    gifts_remaining = max(0, _GIFTS_PER_DAY - gifts_today - (1 if was_gifted else 0))
    return ok(
        EndCallOut(
            call_id=call_id,
            status="failed" if was_gifted else "completed",
            duration_sec=duration_sec,
            was_gifted=was_gifted,
            gifts_remaining_today=gifts_remaining,
        )
    )
