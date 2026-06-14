"""Story 7.1 — unit tests for the pure debrief assembly functions.

`compute_survival_pct` (AC4), `compute_encouraging_framing` (FR15b / AC5), and
`assemble_debrief` (AC5) are I/O-free, so they test directly without any DB or
LLM. The hesitation index-merge and the `encouraging_framing` omission rule
are the load-bearing behaviours covered here.
"""

from __future__ import annotations

from pipeline.debrief_assembly import (
    assemble_debrief,
    compute_encouraging_framing,
    compute_survival_pct,
)


# ---------- compute_survival_pct (AC4) ------------------------------------


def test_survival_pct_uses_floor_not_round():
    # 2/3 = 66.6 → 66 (floor, never 67) so a green 100% only on full completion.
    assert compute_survival_pct(2, 3) == 66
    assert compute_survival_pct(5, 7) == 71  # 71.4 → 71
    assert compute_survival_pct(1, 3) == 33


def test_survival_pct_full_completion_is_100():
    assert compute_survival_pct(4, 4) == 100


def test_survival_pct_zero_total_is_zero_no_division_error():
    assert compute_survival_pct(0, 0) == 0
    assert compute_survival_pct(3, 0) == 0


def test_survival_pct_zero_passed_is_zero():
    assert compute_survival_pct(0, 5) == 0


def test_survival_pct_clamps_overflow_to_100():
    # Defensive: a malformed (passed > total) count can't violate the CHECK.
    assert compute_survival_pct(7, 5) == 100


# ---------- compute_encouraging_framing (FR15b / AC5) ---------------------


def test_framing_omitted_at_or_below_40():
    assert compute_encouraging_framing(40, None, "The Mugger") is None
    assert compute_encouraging_framing(10, 5, "The Mugger") is None


def test_framing_present_above_40():
    framing = compute_encouraging_framing(41, None, "The Mugger")
    assert framing is not None
    assert "proximity" in framing


def test_framing_proximity_is_gap_to_full_survival():
    framing = compute_encouraging_framing(73, 67, "The Mugger")
    assert framing["proximity"] == "27% away from surviving The Mugger"
    assert framing["improvement"] == "+6% since last attempt"


def test_framing_improvement_omitted_on_first_attempt():
    framing = compute_encouraging_framing(73, None, "The Mugger")
    assert "improvement" not in framing


def test_framing_improvement_omitted_when_not_improved():
    framing = compute_encouraging_framing(73, 80, "The Mugger")
    assert "improvement" not in framing  # 73 <= 80 → no encouraging delta


def test_framing_proximity_at_full_survival():
    framing = compute_encouraging_framing(100, 90, "The Mugger")
    assert framing["proximity"] == "You survived The Mugger"
    assert framing["improvement"] == "+10% since last attempt"


# ---------- assemble_debrief (AC5) ----------------------------------------


def _core(**overrides):
    base = {
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
            {"hesitation_id": "h1", "context": "After the threat escalated"},
            {"hesitation_id": "h2", "context": "When asked to empty pockets"},
        ],
        "idioms": [
            {
                "expression": "Pull the other one",
                "meaning": "I don't believe you",
                "context": "When you claimed to have no wallet",
            }
        ],
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
    base.update(overrides)
    return base


def test_assemble_merges_core_and_backend_fields():
    out = assemble_debrief(
        core=_core(),
        survival_pct=73,
        character_name="The Mugger",
        scenario_title="Give me your wallet",
        attempt_number=3,
        previous_best=67,
        hesitations=[
            {"id": "h1", "duration_sec": 4.23, "preceding_character_line": "x"},
            {"id": "h2", "duration_sec": 3.51, "preceding_character_line": "y"},
        ],
    )
    assert out["debrief_version"] == 2
    assert out["survival_pct"] == 73
    assert out["character_name"] == "The Mugger"
    assert out["scenario_title"] == "Give me your wallet"
    assert out["attempt_number"] == 3
    assert out["previous_best"] == 67
    assert out["errors"] == _core()["errors"]
    assert out["idioms"] == _core()["idioms"]
    assert out["better_phrasings"] == []
    assert out["checkpoints"] == []
    # rich areas with the BACKEND-pinned focus marker on #0.
    assert out["areas"][0]["is_focus"] is True
    assert out["areas"][1]["is_focus"] is False
    assert out["areas"][0]["title"] == "Negative structure"
    # back-compat flat list DERIVED from the area titles.
    assert out["areas_to_work_on"] == ["Negative structure", "Articles"]
    assert out["inappropriate_behavior"] is None


def test_assemble_merges_hesitation_duration_and_context_by_id():
    # Gaps arrive OUT OF ORDER vs the contexts; id-pairing must still align them
    # (the v1 by-index merge would mis-pair here).
    out = assemble_debrief(
        core=_core(),
        survival_pct=73,
        character_name="The Mugger",
        scenario_title="Give me your wallet",
        attempt_number=1,
        previous_best=None,
        hesitations=[
            {
                "id": "h2",
                "duration_sec": 3.51,
                "preceding_character_line": "Empty your pockets",
                "resolved": True,
            },
            {
                "id": "h1",
                "duration_sec": 4.23,
                "preceding_character_line": "Talk properly",
                "resolved": False,
            },
        ],
    )
    assert out["hesitations"] == [
        {
            "id": "h2",
            "duration_sec": 3.5,
            "context": "When asked to empty pockets",
            "resolved": True,
            "source": "server",
        },
        {
            "id": "h1",
            "duration_sec": 4.2,
            "context": "After the threat escalated",
            "resolved": False,
            "source": "server",
        },
    ]
    assert "hesitation_contexts" not in out


def test_assemble_hesitation_merge_tolerates_missing_contexts():
    # 2 measured gaps but the LLM returned only 1 context → the unmatched gap
    # keeps its duration with an empty context (never dropped).
    out = assemble_debrief(
        core=_core(
            hesitation_contexts=[{"hesitation_id": "h1", "context": "Only one"}]
        ),
        survival_pct=50,
        character_name="The Waiter",
        scenario_title="Order your dinner",
        attempt_number=1,
        previous_best=None,
        hesitations=[
            {"id": "h1", "duration_sec": 5.0, "preceding_character_line": "a"},
            {"id": "h2", "duration_sec": 4.0, "preceding_character_line": "b"},
        ],
    )
    assert out["hesitations"] == [
        {
            "id": "h1",
            "duration_sec": 5.0,
            "context": "Only one",
            "resolved": True,
            "source": "server",
        },
        {
            "id": "h2",
            "duration_sec": 4.0,
            "context": "",
            "resolved": True,
            "source": "server",
        },
    ]


def test_assemble_threads_checkpoints_and_device_source():
    out = assemble_debrief(
        core=_core(hesitation_contexts=[{"hesitation_id": "h1", "context": "c"}]),
        survival_pct=66,
        character_name="The Mugger",
        scenario_title="Give me your wallet",
        attempt_number=1,
        previous_best=None,
        hesitations=[
            {
                "id": "h1",
                "duration_sec": 6.0,
                "preceding_character_line": "a",
                "resolved": True,
                "source": "device",
            }
        ],
        checkpoints=[
            {"id": "greet", "hint": "Greet the mugger", "met": True},
            {"id": "refuse", "hint": "Refuse", "met": False},
        ],
    )
    assert out["checkpoints"][0]["met"] is True
    assert out["checkpoints"][1]["met"] is False
    # a device-measured gap keeps its source tag through the merge.
    assert out["hesitations"][0]["source"] == "device"


def test_assemble_includes_framing_above_40():
    out = assemble_debrief(
        core=_core(),
        survival_pct=73,
        character_name="The Mugger",
        scenario_title="Give me your wallet",
        attempt_number=3,
        previous_best=67,
        hesitations=[],
    )
    assert "encouraging_framing" in out
    assert out["encouraging_framing"]["improvement"] == "+6% since last attempt"


def test_assemble_omits_framing_at_or_below_40():
    out = assemble_debrief(
        core=_core(),
        survival_pct=40,
        character_name="The Mugger",
        scenario_title="Give me your wallet",
        attempt_number=1,
        previous_best=None,
        hesitations=[],
    )
    assert "encouraging_framing" not in out  # omitted entirely (not null)


def test_assemble_empty_hesitations_yields_empty_list():
    out = assemble_debrief(
        core=_core(hesitation_contexts=[]),
        survival_pct=45,
        character_name="The Waiter",
        scenario_title="Order your dinner",
        attempt_number=1,
        previous_best=None,
        hesitations=[],
    )
    assert out["hesitations"] == []
