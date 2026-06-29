"""Story 7.1 (Decision 1 = Option A) — the bot's call-end debrief persistence.

At teardown the call is fully over, the transcript is collected, and the
checkpoint counts are final — all in-process in the bot subprocess. This module
turns that data into a stored debrief: it runs the (testable) LLM generator,
computes the backend survival %, upserts `user_progress`, assembles the full
client debrief, and writes the `debriefs` row + the `call_sessions` checkpoint
counts directly to the shared sqlite DB. `GET /debriefs/{call_id}` then only
reads.

Keeping this OUT of `bot.py` (which imports pipecat) lets it be unit-tested
against a real test DB with a mocked generator. `persist_debrief` takes plain
data (not the live pipeline objects) for the same reason; the bot extracts the
primitives and calls it inside a try/except so a debrief failure NEVER crashes
teardown.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from loguru import logger
from pydantic import ValidationError

from config import Settings
from db.database import get_connection
from db.queries import (
    get_call_session,
    insert_debrief,
    update_debrief_analysis,
    upsert_user_progress,
)
from models.schemas import DebriefOut
from pipeline.debrief_assembly import assemble_debrief, compute_survival_pct
from pipeline.debrief_generator import degraded_core, generate_debrief
from pipeline.llm_provider import resolve_llm_api_key, resolve_llm_chat_url
from pipeline.prompts import DEBRIEF_PROMPT_VERSION

# When the call ended without the PatienceTracker driving it (the user pressed
# hang-up, or the network dropped), there is no tracker-emitted reason.
DEFAULT_END_REASON = "user_hangup"
# Story 7.5 F2 — a fully-completed call (every checkpoint met) that the user
# ended themselves used to be mislabeled `user_hangup`; this distinct reason
# stops the debrief framing/tone keying on a "they hung up on you" signal.
COMPLETED_END_REASON = "completed"


def resolve_end_reason(
    tracker_reason: str | None, *, met_count: int, total_checkpoints: int
) -> str:
    """Story 7.5 F2 — the call-end reason the debrief should record.

    The PatienceTracker's reason wins when set (`survived`,
    `character_hung_up`, `inappropriate_content`, `noisy_environment`). When it
    is None (user hang-up / network drop), a call that nevertheless met EVERY
    checkpoint is `completed` — NOT the misleading `user_hangup` default the v1
    teardown stamped on a successful run.
    """
    if tracker_reason:
        return tracker_reason
    if total_checkpoints > 0 and met_count >= total_checkpoints:
        return COMPLETED_END_REASON
    return DEFAULT_END_REASON


_NO_THINK_PREFIX = "/no_think"
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_MAX_BRIEF_CHARS = 300


def _now_iso() -> str:
    """UTC ISO-8601 with trailing `Z` — same shape as `api.responses.now_iso`
    (inlined so `pipeline` doesn't import `api`)."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def brief_personality(base_prompt: str) -> str:
    """First 1-2 sentences of the persona (Decision 3 — the LLM user message's
    `Character personality:`). Strips a leading `/no_think` Qwen-ism and caps
    the length so the debrief prompt stays bounded."""
    text = (base_prompt or "").strip()
    if text.startswith(_NO_THINK_PREFIX):
        text = text[len(_NO_THINK_PREFIX) :].strip()
    parts = [p for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]
    return " ".join(parts[:2]).strip()[:_MAX_BRIEF_CHARS]


async def persist_debrief(
    *,
    settings: Settings,
    call_id: int,
    transcript: list[dict],
    reason: str,
    checkpoints_passed: int,
    total_checkpoints: int,
    character_name: str,
    scenario_title: str,
    scenario_id: str,
    brief_personality_description: str,
    hesitations: list[dict],
    checkpoints: list[dict] | None = None,
) -> None:
    """Generate + persist the debrief for a finished call (Option A).

    Idempotent: if teardown already ran for this call (the
    `call_sessions.checkpoints_passed` marker is set), this is a no-op — so a
    future pooled-bot retry (Story 6.26) never double-bumps the attempt count.

    On a first run: writes the server-authoritative checkpoint counts + upserts
    the user's progression (attempts / best_score are progress, independent of
    the debrief text). Then, Story 10.7 (Bug B — PROGRESSIVE debrief), it persists
    the debrief in TWO writes:

      1. BEFORE awaiting the LLM, a SCORE-ONLY row marked `status='pending'`
         (survival %, checkpoints, attempt #, framing — all backend-owned, reusing
         the `degraded_core` shape but NOT flagged `degraded`: this is "analysis
         still coming", not "analysis failed"). `GET /debriefs/{id}` returns it
         200 immediately, so the client renders the scorecard with ~no wait.
      2. The analysis is generated INLINE (the bot CANNOT background past
         `asyncio.run` — the loop closes + cancels pending tasks the moment
         teardown returns), then the SAME row is UPDATEd to `status='ready'`. On
         success the full analysis lands; on a terminal LLM failure within the
         budget the row is marked `ready` + the in-blob `degraded` flag (the
         never-blank fallback — the user still keeps the score, call_id=324
         2026-06-24 / call_id=340 2026-06-29 ReadTimeout).

    This REMOVES the old fragile "race a single deadline → degraded forever"
    failure: the score is unconditional and instant, and the analysis fills in on
    a generous inline budget. The second write is guarded `WHERE status='pending'`
    so a duplicate / late writer can't clobber a `ready` blob. Never persists the
    full transcript.
    """
    survival_pct = compute_survival_pct(checkpoints_passed, total_checkpoints)

    # Cheap existence + idempotency pre-check BEFORE the claim + paid LLM call:
    # bail if the call row was rolled back (Popen-rollback), or if teardown
    # already ran (`checkpoints_passed` is the marker the atomic claim below
    # writes). This is only a COST optimisation — the authoritative guard is the
    # conditional CLAIM in the next transaction, which stays correct under a
    # concurrent / post-crash retry that this earlier, separate-connection read
    # could miss.
    async with get_connection() as db:
        call_row = await get_call_session(db, call_id)
    if call_row is None:
        logger.warning("debrief: no call_sessions row for call_id={}", call_id)
        return
    if call_row["checkpoints_passed"] is not None:
        logger.info(
            "debrief: teardown already ran for call_id={} — skipping (idempotent)",
            call_id,
        )
        return
    user_id = call_row["user_id"]

    now = _now_iso()
    # ONE atomic transaction = the authoritative idempotency guard + the
    # progression bump. The conditional CLAIM flips `checkpoints_passed` from NULL
    # only on the FIRST teardown; a concurrent run or a post-crash retry (Story
    # 6.26 bot pooling) gets rowcount 0 and bails — so `user_progress.attempts` is
    # bumped EXACTLY once even though the cheap pre-check above and this claim can
    # each be reached twice. The marker write and the attempt bump share this
    # transaction, so a crash before commit rolls back BOTH (no half-applied
    # attempt, no orphaned marker). The claim writes the server-authoritative
    # checkpoint counts (AC1/AC9). Story 10.7: the claim now runs BEFORE the LLM,
    # so a duplicate teardown is rejected here and never pays for generation.
    async with get_connection() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            claim = await db.execute(
                "UPDATE call_sessions "
                "SET checkpoints_passed = ?, total_checkpoints = ? "
                "WHERE id = ? AND checkpoints_passed IS NULL",
                (checkpoints_passed, total_checkpoints, call_id),
            )
            if claim.rowcount != 1:
                await db.rollback()
                logger.info(
                    "debrief: teardown already claimed for call_id={} — "
                    "skipping (idempotent)",
                    call_id,
                )
                return
            previous_best, attempt_number = await upsert_user_progress(
                db, user_id, scenario_id, survival_pct, now
            )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise

    def _assemble_json(core: dict, *, degraded: bool) -> str | None:
        """Assemble + WRITE-time validate a debrief blob → JSON string (or None
        on a contract failure). On the non-strict fallback parse path a
        structurally-wrong item could slip through `_normalize_core` (which only
        checks list-ness); storing it would make every future GET a 500. Validate
        against the same `DebriefOut` contract the route enforces and refuse a
        poison blob."""
        debrief = assemble_debrief(
            core=core,
            survival_pct=survival_pct,
            character_name=character_name,
            scenario_title=scenario_title,
            attempt_number=attempt_number,
            previous_best=previous_best,
            hesitations=hesitations,
            checkpoints=checkpoints,
            degraded=degraded,
        )
        try:
            DebriefOut.model_validate(debrief)
        except ValidationError as exc:
            logger.error(
                "debrief: assembled blob failed the DebriefOut contract for "
                "call_id={} (degraded={}) ({})",
                call_id,
                degraded,
                exc,
            )
            return None
        return json.dumps(debrief, ensure_ascii=False)

    # --- PHASE 1: persist the score-only PENDING row BEFORE the LLM ---------
    # `degraded_core` is the all-empty analysis core; assembled WITHOUT the
    # `degraded` flag it is the "score-only, analysis coming" blob. This makes
    # `GET /debriefs/{id}` return the full scorecard + checkpoints with ~no wait.
    pending_json = _assemble_json(degraded_core(reason), degraded=False)
    if pending_json is None:
        # Should be unreachable (degraded_core always validates), but never write
        # an invalid pending row — leave GET serving DEBRIEF_NOT_READY.
        return
    async with get_connection() as db:
        inserted_pending = await insert_debrief(
            db,
            call_session_id=call_id,
            survival_pct=survival_pct,
            checkpoints_passed=checkpoints_passed,
            total_checkpoints=total_checkpoints,
            debrief_json=pending_json,
            prompt_version=DEBRIEF_PROMPT_VERSION,
            created_at=now,
            status="pending",
        )
    logger.info(
        "debrief score-only stored call_id={} survival_pct={} attempt={} "
        "status=pending inserted={}",
        call_id,
        survival_pct,
        attempt_number,
        inserted_pending,
    )

    # --- PHASE 2: generate the analysis INLINE, then UPDATE the SAME row -----
    # Inline (not fire-and-forget): the bot subprocess runs `asyncio.run` and
    # exits the moment teardown returns, so a background task that outlives this
    # would be cancelled. The bot runs teardown to completion with no deadline-
    # kill, so a generous inline budget (debrief_generator p99 + one retry) is
    # safe; pooled bots are single-use so this never starves a worker.
    #
    # The generate→UPDATE pair is wrapped in try/finally so the Phase-1 `pending`
    # row is ALWAYS finalised to `ready` — even if generation is CANCELLED
    # (process shutdown injects `CancelledError`, which `generate_debrief`
    # re-raises; it is a BaseException the bot's `except Exception` teardown guard
    # would miss) or raises unexpectedly. Without this, an exception here would
    # leave the row stuck `pending` forever — the idempotency pre-check bails on
    # any retry, so it never self-heals, and the client polls its whole budget
    # before degrading. A re-raised exception still propagates AFTER the finally,
    # so cancellation semantics are preserved. (A SIGKILL/OOM between the Phase-1
    # commit and here is the one residual — instantaneous + unhandleable; the
    # client still degrades gracefully via its poll-budget fallback.)
    core = None
    try:
        core = await generate_debrief(
            transcript=transcript,
            reason=reason,
            character_name=character_name,
            scenario_title=scenario_title,
            brief_personality_description=brief_personality_description,
            hesitations=hesitations,
            api_key=resolve_llm_api_key(settings),
            model=settings.debrief_model,
            base_url=resolve_llm_chat_url(settings),
        )
    finally:
        analysis_json = None if core is None else _assemble_json(core, degraded=False)
        degraded = analysis_json is None
        if degraded:
            # Never-blank fallback (call_id=324 / call_id=340): no usable core
            # (timeout, terminal HTTP error, a contract-failing blob, or a
            # cancellation). Mark the row `ready` + the in-blob `degraded` flag so
            # the client stops polling and shows 'detailed analysis unavailable' —
            # the user keeps the survival %, checkpoints, and progression.
            logger.warning(
                "debrief: no usable analysis core for call_id={} — finalising the "
                "score-only row as ready+degraded (score + progress already persisted)",
                call_id,
            )
            analysis_json = _assemble_json(degraded_core(reason), degraded=True)
        if analysis_json is not None:
            try:
                async with get_connection() as db:
                    updated = await update_debrief_analysis(
                        db,
                        call_session_id=call_id,
                        debrief_json=analysis_json,
                        status="ready",
                    )
                logger.info(
                    "debrief stored call_id={} survival_pct={} attempt={} "
                    "status=ready degraded={} updated={}",
                    call_id,
                    survival_pct,
                    attempt_number,
                    degraded,
                    updated,
                )
            except Exception as exc:
                # A cleanup-write failure must never MASK the original exception
                # (e.g. the CancelledError we are propagating) — log + swallow it.
                # The row stays `pending`; the client degrades on its poll budget.
                logger.warning(
                    "debrief: failed to finalize pending row for call_id={}: {} ({})",
                    call_id,
                    exc,
                    type(exc).__name__,
                )
