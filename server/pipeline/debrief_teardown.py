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
    set_call_checkpoint_counts,
    upsert_user_progress,
)
from models.schemas import DebriefOut
from pipeline.debrief_assembly import assemble_debrief, compute_survival_pct
from pipeline.debrief_generator import generate_debrief
from pipeline.llm_provider import resolve_llm_api_key, resolve_llm_chat_url
from pipeline.prompts import DEBRIEF_PROMPT_VERSION

# When the call ended without the PatienceTracker driving it (the user pressed
# hang-up, or the network dropped), there is no tracker-emitted reason.
DEFAULT_END_REASON = "user_hangup"

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
) -> None:
    """Generate + persist the debrief for a finished call (Option A).

    Idempotent: if teardown already ran for this call (the
    `call_sessions.checkpoints_passed` marker is set), this is a no-op — so a
    future pooled-bot retry (Story 6.26) never double-bumps the attempt count.

    On a first run: writes the server-authoritative checkpoint counts + upserts
    the user's progression (attempts / best_score are progress, independent of
    the debrief text), then stores a `debriefs` row ONLY when the LLM core
    generated AND the assembled blob passes the `DebriefOut` contract — a
    malformed blob (reachable only on the non-strict-provider fallback parse
    path) is skipped + logged so `GET` serves `DEBRIEF_NOT_READY` instead of a
    permanent 500. Never persists the full transcript.
    """
    survival_pct = compute_survival_pct(checkpoints_passed, total_checkpoints)

    # Cheap existence + idempotency pre-check BEFORE the ~8 s paid LLM call:
    # bail if the call row was rolled back (Popen-rollback), or if teardown
    # already ran (`checkpoints_passed` is the marker `set_call_checkpoint_counts`
    # always writes). Skipping here avoids both a wasted generation and a
    # double user_progress increment on any re-run.
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

    now = _now_iso()
    async with get_connection() as db:
        # Progression + server-side counts land regardless of LLM success.
        previous_best, attempt_number = await upsert_user_progress(
            db, user_id, scenario_id, survival_pct, now
        )
        await set_call_checkpoint_counts(
            db, call_id, checkpoints_passed, total_checkpoints
        )

        if core is None:
            logger.warning(
                "debrief: generation returned None for call_id={} "
                "(counts + progress persisted, no debrief row)",
                call_id,
            )
            return

        debrief = assemble_debrief(
            core=core,
            survival_pct=survival_pct,
            character_name=character_name,
            scenario_title=scenario_title,
            attempt_number=attempt_number,
            previous_best=previous_best,
            hesitations=hesitations,
        )
        # Validate at WRITE time against the same contract the GET route enforces.
        # On the non-strict fallback parse path a structurally-wrong item could
        # slip through `_normalize_core` (which only checks list-ness); storing it
        # would make every future GET a permanent 500 (the insert is idempotent,
        # so the poison blob is never overwritten). Skip → GET serves NOT_READY.
        try:
            DebriefOut.model_validate(debrief)
        except ValidationError as exc:
            logger.error(
                "debrief: assembled blob failed the DebriefOut contract for "
                "call_id={} ({}) — not storing (GET will serve DEBRIEF_NOT_READY)",
                call_id,
                exc,
            )
            return

        inserted = await insert_debrief(
            db,
            call_session_id=call_id,
            survival_pct=survival_pct,
            checkpoints_passed=checkpoints_passed,
            total_checkpoints=total_checkpoints,
            debrief_json=json.dumps(debrief, ensure_ascii=False),
            prompt_version=DEBRIEF_PROMPT_VERSION,
            created_at=now,
        )
        logger.info(
            "debrief stored call_id={} survival_pct={} attempt={} inserted={}",
            call_id,
            survival_pct,
            attempt_number,
            inserted,
        )
