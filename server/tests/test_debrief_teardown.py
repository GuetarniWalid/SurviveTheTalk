"""Story 7.1 (Option A / AC9) — tests for the bot's teardown persistence.

`persist_debrief` is exercised against a real per-test DB with the LLM
generator mocked (no live Groq). Asserts the Option-A contract: progression +
server-side counts always land; a `debriefs` row lands only when the LLM core
generated. Also covers `brief_personality`.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from config import Settings
from db.database import get_connection, run_migrations
from db.queries import get_debrief_by_call_id, insert_call_session
from db.seed_scenarios import seed_scenarios
from pipeline.debrief_teardown import brief_personality, persist_debrief

_NOW = "2026-06-08T12:00:00Z"
_SCENARIO_ID = "mugger_medium_01"

_CORE = {
    "errors": [
        {
            "user_said": "I am agree",
            "correction": "I agree",
            "context": "Responding to the demand",
            "count": 3,
        }
    ],
    "hesitation_contexts": [{"context": "After the threat escalated"}],
    "idioms": [],
    "areas_to_work_on": ["Negative structure", "Articles"],
    "inappropriate_behavior": None,
}


@pytest.fixture
def seeded(test_db_path):
    async def _setup() -> tuple[int, int]:
        await run_migrations()
        await seed_scenarios()
        async with get_connection() as db:
            cursor = await db.execute(
                "INSERT INTO users(email, tier, created_at) VALUES (?, 'free', ?)",
                ("u@example.invalid", _NOW),
            )
            await db.commit()
            user_id = cursor.lastrowid
            call_id = await insert_call_session(db, user_id, _SCENARIO_ID, _NOW)
        return user_id, call_id

    return asyncio.run(_setup())


def _kwargs(call_id: int, **overrides):
    base = dict(
        settings=Settings(),
        call_id=call_id,
        transcript=[
            {"role": "character", "text": "Give me your wallet.", "timestamp_ms": 0},
            {"role": "user", "text": "I am not want problem.", "timestamp_ms": 1500},
        ],
        reason="character_hung_up",
        checkpoints_passed=2,
        total_checkpoints=3,
        character_name="The Mugger",
        scenario_title="Give me your wallet",
        scenario_id=_SCENARIO_ID,
        brief_personality_description="A mugger.",
        hesitations=[
            {"duration_sec": 4.2, "preceding_character_line": "Talk properly."}
        ],
    )
    base.update(overrides)
    return base


async def _fake_core(**_kwargs):
    return dict(_CORE)


async def _fake_none(**_kwargs):
    return None


def test_persist_writes_debrief_counts_and_progress(seeded, monkeypatch):
    user_id, call_id = seeded
    monkeypatch.setattr("pipeline.debrief_teardown.generate_debrief", _fake_core)

    async def _go():
        await persist_debrief(**_kwargs(call_id))
        async with get_connection() as db:
            debrief = await get_debrief_by_call_id(db, call_id)
            async with db.execute(
                "SELECT checkpoints_passed, total_checkpoints FROM call_sessions "
                "WHERE id = ?",
                (call_id,),
            ) as cur:
                counts = await cur.fetchone()
            async with db.execute(
                "SELECT best_score, attempts FROM user_progress "
                "WHERE user_id = ? AND scenario_id = ?",
                (user_id, _SCENARIO_ID),
            ) as cur:
                progress = await cur.fetchone()
        return debrief, counts, progress

    debrief, counts, progress = asyncio.run(_go())

    # survival = floor(2/3*100) = 66
    assert debrief["survival_pct"] == 66
    stored = json.loads(debrief["debrief_json"])
    assert stored["character_name"] == "The Mugger"
    assert stored["scenario_title"] == "Give me your wallet"
    assert stored["attempt_number"] == 1
    assert stored["previous_best"] is None
    # hesitation duration (backend) merged with LLM context by index.
    assert stored["hesitations"] == [
        {"duration_sec": 4.2, "context": "After the threat escalated"}
    ]
    # encouraging_framing present (66 > 40).
    assert "encouraging_framing" in stored

    assert counts["checkpoints_passed"] == 2
    assert counts["total_checkpoints"] == 3
    assert progress["best_score"] == 66
    assert progress["attempts"] == 1


def test_persist_no_debrief_row_when_generation_fails(seeded, monkeypatch):
    user_id, call_id = seeded
    monkeypatch.setattr("pipeline.debrief_teardown.generate_debrief", _fake_none)

    async def _go():
        await persist_debrief(**_kwargs(call_id))
        async with get_connection() as db:
            debrief = await get_debrief_by_call_id(db, call_id)
            async with db.execute(
                "SELECT checkpoints_passed, total_checkpoints FROM call_sessions "
                "WHERE id = ?",
                (call_id,),
            ) as cur:
                counts = await cur.fetchone()
            async with db.execute(
                "SELECT attempts FROM user_progress "
                "WHERE user_id = ? AND scenario_id = ?",
                (user_id, _SCENARIO_ID),
            ) as cur:
                progress = await cur.fetchone()
        return debrief, counts, progress

    debrief, counts, progress = asyncio.run(_go())

    # No debrief row, but counts + progress still persisted (Option A).
    assert debrief is None
    assert counts["checkpoints_passed"] == 2
    assert progress["attempts"] == 1


def test_persist_missing_call_row_is_noop(seeded, monkeypatch):
    monkeypatch.setattr("pipeline.debrief_teardown.generate_debrief", _fake_core)

    async def _go():
        # call_id that does not exist → logged + return, no crash.
        await persist_debrief(**_kwargs(999999))
        async with get_connection() as db:
            return await get_debrief_by_call_id(db, 999999)

    assert asyncio.run(_go()) is None


def test_persist_is_idempotent_on_double_call(seeded, monkeypatch):
    user_id, call_id = seeded
    monkeypatch.setattr("pipeline.debrief_teardown.generate_debrief", _fake_core)

    async def _go():
        await persist_debrief(**_kwargs(call_id))
        # A second teardown for the SAME call must be a no-op (the checkpoints_passed
        # marker is set) — no double attempt-count bump.
        await persist_debrief(**_kwargs(call_id, checkpoints_passed=3))
        async with get_connection() as db:
            debrief = await get_debrief_by_call_id(db, call_id)
            async with db.execute(
                "SELECT attempts FROM user_progress "
                "WHERE user_id = ? AND scenario_id = ?",
                (user_id, _SCENARIO_ID),
            ) as cur:
                progress = await cur.fetchone()
        return debrief, progress

    debrief, progress = asyncio.run(_go())
    assert progress["attempts"] == 1  # NOT 2 — the re-run skipped
    assert debrief["survival_pct"] == 66  # original (2/3), not the re-run's 3/3=100


async def _fake_malformed_core(**_kwargs):
    # An error item missing required fields (correction/context/count) — the kind
    # of shape that can slip through _normalize_core's list-only check on the
    # non-strict fallback parse path. assemble_debrief embeds it verbatim.
    return {
        "errors": [{"user_said": "x"}],
        "hesitation_contexts": [],
        "idioms": [],
        "areas_to_work_on": ["a", "b"],
        "inappropriate_behavior": None,
    }


def test_persist_skips_storage_when_assembled_blob_fails_contract(seeded, monkeypatch):
    user_id, call_id = seeded
    monkeypatch.setattr(
        "pipeline.debrief_teardown.generate_debrief", _fake_malformed_core
    )

    async def _go():
        await persist_debrief(**_kwargs(call_id))
        async with get_connection() as db:
            debrief = await get_debrief_by_call_id(db, call_id)
            async with db.execute(
                "SELECT attempts FROM user_progress "
                "WHERE user_id = ? AND scenario_id = ?",
                (user_id, _SCENARIO_ID),
            ) as cur:
                progress = await cur.fetchone()
        return debrief, progress

    debrief, progress = asyncio.run(_go())
    # No poison blob stored (GET will serve DEBRIEF_NOT_READY, not a 500)...
    assert debrief is None
    # ...but progression still landed (the attempt happened).
    assert progress["attempts"] == 1


def test_brief_personality_strips_no_think_and_takes_two_sentences():
    base = (
        "/no_think\nYou are Tina, a tired waitress. She has worked 12 hours. "
        "Extra third sentence that must be dropped."
    )
    out = brief_personality(base)
    assert out == "You are Tina, a tired waitress. She has worked 12 hours."


def test_brief_personality_handles_plain_persona():
    out = brief_personality("You are Detective Mercer. A relentless veteran. More.")
    assert out == "You are Detective Mercer. A relentless veteran."
