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
from pipeline.debrief_teardown import (
    COMPLETED_END_REASON,
    DEFAULT_END_REASON,
    brief_personality,
    persist_debrief,
    resolve_end_reason,
)

_NOW = "2026-06-08T12:00:00Z"
_SCENARIO_ID = "mugger_medium_01"

_CORE = {
    "errors": [
        {
            "user_said": "I am agree",
            "correction": "I agree",
            "context": "Responding to the demand",
            "count": 3,
            "explanation": "'agree' stands alone; no 'be'.",
            "examples": ["I agree with you."],
        }
    ],
    "hesitation_contexts": [
        {"hesitation_id": "h1", "context": "After the threat escalated"}
    ],
    "idioms": [],
    "better_phrasings": [],
    "areas": [
        {
            "title": "Negative structure",
            "evidence": 'You said "I am not want"',
            "practice_prompt": "Coach: drill negatives.",
        },
        {
            "title": "Articles",
            "evidence": 'You dropped "a"',
            "practice_prompt": "Coach: drill articles.",
        },
    ],
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
            {
                "id": "h1",
                "duration_sec": 4.2,
                "preceding_character_line": "Talk properly.",
                "resolved": True,
            }
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
    assert stored["debrief_version"] == 2
    assert stored["character_name"] == "The Mugger"
    assert stored["scenario_title"] == "Give me your wallet"
    assert stored["attempt_number"] == 1
    assert stored["previous_best"] is None
    # hesitation duration (backend) merged with the LLM context BY ID (v2).
    assert stored["hesitations"] == [
        {
            "id": "h1",
            "duration_sec": 4.2,
            "context": "After the threat escalated",
            "resolved": True,
            "source": "server",
        }
    ]
    # v2 fields land: rich areas + the back-compat title list derived from them.
    assert stored["areas_to_work_on"] == ["Negative structure", "Articles"]
    assert stored["areas"][0]["is_focus"] is True
    # encouraging_framing present (66 > 40).
    assert "encouraging_framing" in stored

    assert counts["checkpoints_passed"] == 2
    assert counts["total_checkpoints"] == 3
    assert progress["best_score"] == 66
    assert progress["attempts"] == 1


def test_persist_stores_degraded_debrief_when_generation_fails(seeded, monkeypatch):
    """Never-blank fallback (call_id=324): generation returned None (even after
    the non-strict retry) → a DEGRADED score-only debrief is stored so the client
    gets the survival % at once instead of polling a never-arriving report. Empty
    LLM analysis, `degraded` marker, but the backend-owned fields (score, attempt,
    checkpoint breakdown) all land. Counts + progress persist as before."""
    user_id, call_id = seeded
    monkeypatch.setattr("pipeline.debrief_teardown.generate_debrief", _fake_none)
    breakdown = [
        {"id": "greet", "hint": "Greet the mugger", "met": True},
        {"id": "refuse", "hint": "Refuse to comply", "met": False},
    ]

    async def _go():
        await persist_debrief(**_kwargs(call_id, checkpoints=breakdown))
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

    # A degraded row IS stored (score-only), and counts + progress still land.
    assert debrief is not None
    assert debrief["survival_pct"] == 66  # floor(2/3*100)
    stored = json.loads(debrief["debrief_json"])
    assert stored["degraded"] is True
    # LLM analysis is empty (nothing was generated)...
    assert stored["errors"] == []
    assert stored["areas"] == []
    assert stored["areas_to_work_on"] == []
    assert stored["idioms"] == []
    # ...but the backend-owned fields still ground the report.
    assert stored["character_name"] == "The Mugger"
    assert stored["attempt_number"] == 1
    assert stored["checkpoints"] == breakdown
    assert counts["checkpoints_passed"] == 2
    assert progress["attempts"] == 1


def test_persist_normal_debrief_is_not_marked_degraded(seeded, monkeypatch):
    """A successful generation stores NO `degraded` key (byte-identical to the
    pre-fallback happy path — the client defaults absent → False)."""
    _user_id, call_id = seeded
    monkeypatch.setattr("pipeline.debrief_teardown.generate_debrief", _fake_core)

    async def _go():
        await persist_debrief(**_kwargs(call_id))
        async with get_connection() as db:
            return await get_debrief_by_call_id(db, call_id)

    debrief = asyncio.run(_go())
    stored = json.loads(debrief["debrief_json"])
    assert "degraded" not in stored


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


def test_persist_claim_blocks_double_bump_when_precheck_is_defeated(
    seeded, monkeypatch
):
    """The ATOMIC CLAIM — not just the cheap pre-check — prevents a double
    attempt-bump. This is the concurrency / post-crash retry case (Story 6.26):
    two teardowns whose cheap pre-check both read a stale NULL marker. We force
    `get_call_session` to always report the marker unset so the pre-check never
    short-circuits; the conditional `UPDATE ... WHERE checkpoints_passed IS NULL`
    must still let only the FIRST run through.
    """
    user_id, call_id = seeded
    monkeypatch.setattr("pipeline.debrief_teardown.generate_debrief", _fake_core)

    async def _stale_call_row(_db, _call_id):
        # Marker always reported NULL → defeats the pre-check, forcing both runs
        # down to the atomic claim on the REAL row.
        return {"checkpoints_passed": None, "user_id": user_id}

    monkeypatch.setattr("pipeline.debrief_teardown.get_call_session", _stale_call_row)

    async def _go():
        await persist_debrief(**_kwargs(call_id))
        await persist_debrief(**_kwargs(call_id, checkpoints_passed=3))
        async with get_connection() as db:
            async with db.execute(
                "SELECT attempts FROM user_progress "
                "WHERE user_id = ? AND scenario_id = ?",
                (user_id, _SCENARIO_ID),
            ) as cur:
                progress = await cur.fetchone()
            async with db.execute(
                "SELECT checkpoints_passed FROM call_sessions WHERE id = ?",
                (call_id,),
            ) as cur:
                counts = await cur.fetchone()
        return progress, counts

    progress, counts = asyncio.run(_go())
    assert progress["attempts"] == 1  # the claim caught run #2, not the pre-check
    assert counts["checkpoints_passed"] == 2  # first claim's value, not re-run's 3


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


def test_persist_stores_device_sourced_hesitation_from_merge(seeded, monkeypatch):
    """Story 7.6 (AC6/AC9) — the teardown-merge integration test.

    A DEVICE-measured gap, merged with the server observer via the EXACT call
    shape `bot.py` teardown uses (`merge_hesitation_sources(device, server)`),
    flows into `persist_debrief` and lands in the stored debrief tagged
    `source="device"` — and WINS the same-turn resolved server gap. This is the
    permanent assertion closing the 7.5 "merge never called / device source
    dormant" finding: a device gap now survives end-to-end into the persisted
    row.
    """
    from pipeline.device_hesitation_collector import (
        DeviceHesitationCollector,
        merge_hesitation_sources,
    )

    class _FakeTranscript:
        def __init__(self, transcript):
            self.transcript = transcript

    _user_id, call_id = seeded

    # The LLM core echoes a context for the device gap's id (paired by id).
    async def _core_with_device_context(**_kwargs):
        core = dict(_CORE)
        core["hesitation_contexts"] = [
            {"hesitation_id": "d1", "context": "After the demand escalated"}
        ]
        return core

    monkeypatch.setattr(
        "pipeline.debrief_teardown.generate_debrief", _core_with_device_context
    )

    collector = DeviceHesitationCollector(
        collector=_FakeTranscript(
            [{"role": "character", "text": "Give me your wallet."}]
        )
    )
    collector.record(gap_ms=6200, censored=False)  # a real device-measured freeze
    # The server observer ALSO produced a (resolved) gap for the same turn — the
    # device measure must WIN it, proving the merge prefers the device source.
    server = [
        {
            "id": "h1",
            "duration_sec": 6.0,
            "preceding_character_line": "Give me your wallet.",
            "resolved": True,
            "source": "server",
        }
    ]
    merged = merge_hesitation_sources(collector.top_hesitations(), server)

    async def _go():
        await persist_debrief(**_kwargs(call_id, hesitations=merged))
        async with get_connection() as db:
            return await get_debrief_by_call_id(db, call_id)

    debrief = asyncio.run(_go())
    stored = json.loads(debrief["debrief_json"])
    assert stored["hesitations"] == [
        {
            "id": "d1",
            "duration_sec": 6.2,
            "context": "After the demand escalated",
            "resolved": True,
            "source": "device",
        }
    ]


def test_persist_threads_checkpoint_breakdown(seeded, monkeypatch):
    """Story 7.5 B7 / Task 3.2 — the bot's met/missed checkpoint breakdown is
    stored verbatim in the debrief (the factual decomposition of the %)."""
    _user_id, call_id = seeded
    monkeypatch.setattr("pipeline.debrief_teardown.generate_debrief", _fake_core)
    breakdown = [
        {"id": "greet", "hint": "Greet the mugger", "met": True},
        {"id": "refuse", "hint": "Refuse to comply", "met": False},
    ]

    async def _go():
        await persist_debrief(**_kwargs(call_id, checkpoints=breakdown))
        async with get_connection() as db:
            return await get_debrief_by_call_id(db, call_id)

    debrief = asyncio.run(_go())
    stored = json.loads(debrief["debrief_json"])
    assert stored["checkpoints"] == breakdown


def test_resolve_end_reason_prefers_tracker_reason():
    assert (
        resolve_end_reason("survived", met_count=3, total_checkpoints=3) == "survived"
    )
    assert (
        resolve_end_reason("inappropriate_content", met_count=0, total_checkpoints=3)
        == "inappropriate_content"
    )


def test_resolve_end_reason_completed_when_all_met_without_tracker_reason():
    # Story 7.5 F2 — a fully-completed call the USER ended is `completed`, not
    # the misleading `user_hangup` default.
    assert (
        resolve_end_reason(None, met_count=3, total_checkpoints=3)
        == COMPLETED_END_REASON
    )


def test_resolve_end_reason_user_hangup_when_incomplete_or_no_checkpoints():
    assert (
        resolve_end_reason(None, met_count=2, total_checkpoints=3) == DEFAULT_END_REASON
    )
    assert (
        resolve_end_reason(None, met_count=0, total_checkpoints=0) == DEFAULT_END_REASON
    )


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
