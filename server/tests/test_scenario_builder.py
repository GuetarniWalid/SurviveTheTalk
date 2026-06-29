"""Story 6.16 — unit tests for the Scenario Builder LOGIC (no network).

Runs in the default `pytest` gate (AC8): pure assembly/validation/heuristics +
the full build pipeline driven by a FAKE LLM. Live generation (real Groq) is
gated out by file location (only `scripts/build_scenario.py` invokes it).
"""

from __future__ import annotations

import asyncio
import json

import httpx
import yaml

import scripts.calibration_engine as engine
import scripts.scenario_builder as builder


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ScriptedLLM:
    """A `ChatLLM` that returns canned responses in call order (expand, draft,
    critique...)."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self._i = 0

    async def chat(self, messages, *, system, temperature, max_tokens) -> str:
        r = self._responses[min(self._i, len(self._responses) - 1)]
        self._i += 1
        return r


def _brief(n: int = 3) -> dict:
    return {
        "title": "The Suspect",
        "character_name": "Officer Dale",
        "character_persona": "A suspicious detective who thinks you're lying.",
        "setting": "A phone call about a crime scene.",
        "user_objective": "Convince the officer your story holds.",
        "win_condition": "No flaw found.",
        "lose_condition": "Caught in a contradiction.",
        "canonical_facts": [
            "Fingerprints were found at the scene.",
            "The crime was at 8:30pm.",
        ],
        "language_focus": "alibi, justification, past tense",
        "content_warning": None,
        "vocabulary": "I was..., because..., last night",
        "context": "A detective calls you about a crime scene.",
        "expect": "He is suspicious — stay consistent.",
        "exit_completion": "Fine. You're clean. For now.",
        "exit_hangup": "Your story doesn't add up. We'll be in touch.",
        "exit_patience_warning": "I'm losing patience. Last chance.",
        "arc": [f"beat {i}" for i in range(1, n + 1)],
    }


def _checkpoints(n: int = 3) -> list[dict]:
    return [
        {
            "id": f"beat_{i}",
            "hint_text": f"Do step {i}.",
            "prompt_segment": f"Ask about topic {i}.",
            "success_criteria": f"User specifically addresses distinct topic number {i}.",
        }
        for i in range(1, n + 1)
    ]


# ============================================================
# Pure helpers
# ============================================================


def test_slugify():
    assert builder.slugify("State your alibi (time!)") == "state_your_alibi_time"
    assert builder.slugify("") == "beat"


def test_sanitize_dedupes_ids_and_strips_extra_keys():
    raw = [
        {
            "id": "x",
            "hint_text": " h ",
            "prompt_segment": "p",
            "success_criteria": "s",
            "junk": 1,
        },
        {
            "id": "x",
            "hint_text": "h2",
            "prompt_segment": "p2",
            "success_criteria": "s2",
        },
    ]
    out = builder.sanitize_checkpoints(raw)
    assert [c["id"] for c in out] == ["x", "x_2"]
    assert out[0]["hint_text"] == "h"
    assert "junk" not in out[0]


# ============================================================
# Story 6.23 — builder preserves the reactive-gating `requires` edge
# ============================================================


def test_sanitize_preserves_requires_edge():
    """The load-bearing builder edit: `requires` is NO LONGER dropped by the
    whitelist, and is slugified to match the target's sanitized id."""
    raw = [
        {
            "id": "trigger",
            "hint_text": "h",
            "prompt_segment": "p",
            "success_criteria": "s",
        },
        {
            "id": "reactive",
            "requires": "Trigger",  # mixed-case → slugified to match `trigger`
            "hint_text": "h",
            "prompt_segment": "p",
            "success_criteria": "s",
        },
    ]
    out = builder.sanitize_checkpoints(raw)
    assert out[1]["requires"] == "trigger"


def test_sanitize_drops_blank_requires():
    """A blank/non-string `requires` is omitted (treated as proactive)."""
    raw = [
        {
            "id": "a",
            "requires": "   ",
            "hint_text": "h",
            "prompt_segment": "p",
            "success_criteria": "s",
        }
    ]
    out = builder.sanitize_checkpoints(raw)
    assert "requires" not in out[0]


def test_sanitize_keeps_malformed_nonstring_requires_as_fail_loud_sentinel():
    """Story 6.23 review (f8) — a PRESENT but non-string `requires` (e.g. a list
    the draft LLM emitted instead of a single id) is an INTENDED-but-malformed
    reactive edge. It must NOT be silently dropped (which would demote the beat
    to proactive with no signal — the exact silent-drop class the `requires`
    preservation was added to kill); it becomes an unmatchable sentinel so the
    loader / `validate_structure` 'unknown id' guard surfaces it to the human."""
    raw = [
        {"id": "a", "hint_text": "h", "prompt_segment": "p", "success_criteria": "s"},
        {
            "id": "b",
            "requires": ["a", "c"],  # malformed: a list, not a single id string
            "hint_text": "h",
            "prompt_segment": "p",
            "success_criteria": "s",
        },
    ]
    out = builder.sanitize_checkpoints(raw)
    assert "requires" in out[1], "malformed reactive edge must not be silently dropped"
    assert out[1]["requires"].startswith("__malformed_requires__")
    # the sentinel cannot match any real checkpoint id → fails validation loud
    assert out[1]["requires"] not in {c["id"] for c in out}


def test_validate_structure_accepts_valid_requires_edge():
    good = builder.assemble_scenario(
        scenario_id="x",
        title="X",
        rive_character="cop",
        base_prompt="You are X.",
        checkpoints=_checkpoints(3),
        brief=_brief(3),
    )
    cps = good["checkpoints"]
    cps[2]["requires"] = cps[0]["id"]  # point at an earlier beat
    scenario = {**good, "checkpoints": cps}
    assert builder.validate_structure(scenario) == []


def test_validate_structure_rejects_bad_requires_edges():
    good = builder.assemble_scenario(
        scenario_id="x",
        title="X",
        rive_character="cop",
        base_prompt="You are X.",
        checkpoints=_checkpoints(3),
        brief=_brief(3),
    )
    cps = [dict(c) for c in good["checkpoints"]]

    unknown = [dict(c) for c in cps]
    unknown[1]["requires"] = "does_not_exist"
    assert any(
        "unknown id" in p
        for p in builder.validate_structure({**good, "checkpoints": unknown})
    )

    forward = [dict(c) for c in cps]
    forward[0]["requires"] = cps[2]["id"]  # points at a LATER beat
    assert any(
        "EARLIER" in p
        for p in builder.validate_structure({**good, "checkpoints": forward})
    )


def test_assemble_and_yaml_roundtrip_preserves_requires():
    scenario = builder.assemble_scenario(
        scenario_id="cop_interrogation_01",
        title="The Suspect",
        rive_character="cop",
        base_prompt="You are Officer Dale.",
        checkpoints=builder.sanitize_checkpoints(
            [
                {
                    "id": "trigger",
                    "hint_text": "h",
                    "prompt_segment": "p",
                    "success_criteria": "s",
                },
                {
                    "id": "reactive",
                    "requires": "trigger",
                    "hint_text": "h",
                    "prompt_segment": "p",
                    "success_criteria": "s",
                },
            ]
        ),
        brief=_brief(2),
    )
    reloaded = yaml.safe_load(builder.scenario_to_yaml(scenario))
    assert builder.validate_structure(reloaded) == []
    assert reloaded["checkpoints"][1]["requires"] == "trigger"


def test_checkpoints_and_critique_prompts_document_requires():
    """The DRAFT prompt instructs emitting `requires` for reactive beats, and the
    CRITIQUE prompt exempts reactive beats from its any-order pass + preserves
    the field."""
    assert "requires" in builder.CHECKPOINTS_PROMPT
    assert "REACTIVE" in builder.CHECKPOINTS_PROMPT
    assert "requires" in builder.CRITIQUE_PROMPT
    # The circularity pass must not strip a legitimate reactive dependency.
    assert "PRESERVE" in builder.CRITIQUE_PROMPT


# ============================================================
# Story 6.27 — builder preserves + validates the `implies` back-fill edge
# ============================================================


def test_sanitize_preserves_implies_edge():
    """`implies` survives the whitelist (mirror of the `requires` preservation)
    and is slugified to match the target's sanitized id."""
    raw = [
        {
            "id": "greet",
            "hint_text": "h",
            "prompt_segment": "p",
            "success_criteria": "s",
        },
        {
            "id": "main_course",
            "implies": "Greet",  # mixed-case → slugified to match `greet`
            "hint_text": "h",
            "prompt_segment": "p",
            "success_criteria": "s",
        },
    ]
    out = builder.sanitize_checkpoints(raw)
    assert out[1]["implies"] == "greet"


def test_sanitize_drops_blank_implies_and_keeps_malformed_as_sentinel():
    """A blank `implies` is omitted; a PRESENT but non-string one (a list the
    draft LLM emitted) becomes the fail-loud sentinel so `validate_structure`'s
    'unknown id' guard surfaces it instead of silently dropping the edge."""
    raw = [
        {
            "id": "a",
            "implies": "   ",
            "hint_text": "h",
            "prompt_segment": "p",
            "success_criteria": "s",
        },
        {
            "id": "b",
            "implies": ["a", "c"],  # malformed: a list, not a single id string
            "hint_text": "h",
            "prompt_segment": "p",
            "success_criteria": "s",
        },
    ]
    out = builder.sanitize_checkpoints(raw)
    assert "implies" not in out[0]
    assert "implies" in out[1], "malformed back-fill edge must not be dropped"
    assert out[1]["implies"].startswith("__malformed_implies__")
    assert out[1]["implies"] not in {c["id"] for c in out}


def test_validate_structure_accepts_valid_implies_edge():
    good = builder.assemble_scenario(
        scenario_id="x",
        title="X",
        rive_character="cop",
        base_prompt="You are X.",
        checkpoints=_checkpoints(3),
        brief=_brief(3),
    )
    cps = good["checkpoints"]
    cps[2]["implies"] = cps[0]["id"]  # point at an earlier beat
    scenario = {**good, "checkpoints": cps}
    assert builder.validate_structure(scenario) == []


def test_validate_structure_rejects_bad_implies_edges():
    """The 4 loader rules, mirrored: non-string/empty, unknown id, non-earlier
    target, and a target that itself carries `requires`."""
    good = builder.assemble_scenario(
        scenario_id="x",
        title="X",
        rive_character="cop",
        base_prompt="You are X.",
        checkpoints=_checkpoints(3),
        brief=_brief(3),
    )
    cps = [dict(c) for c in good["checkpoints"]]

    nonstring = [dict(c) for c in cps]
    nonstring[1]["implies"] = "   "
    assert any(
        "non-string/empty 'implies'" in p
        for p in builder.validate_structure({**good, "checkpoints": nonstring})
    )

    unknown = [dict(c) for c in cps]
    unknown[1]["implies"] = "does_not_exist"
    assert any(
        "'implies' points at unknown id" in p
        for p in builder.validate_structure({**good, "checkpoints": unknown})
    )

    forward = [dict(c) for c in cps]
    forward[0]["implies"] = cps[2]["id"]  # points at a LATER beat
    assert any(
        "'implies'" in p and "EARLIER" in p
        for p in builder.validate_structure({**good, "checkpoints": forward})
    )

    onto_reactive = [dict(c) for c in cps]
    onto_reactive[1]["requires"] = cps[0]["id"]  # beat 1 is a reactive trap
    onto_reactive[2]["implies"] = cps[1]["id"]  # back-filling it is forbidden
    assert any(
        "must never be auto-credited" in p
        for p in builder.validate_structure({**good, "checkpoints": onto_reactive})
    )

    # 6.27 review — rule 5: implies == own requires is a provably dead edge
    # (the gate means the target is always met before the carrier is
    # judgeable, so the back-fill can never fire).
    dead_edge = [dict(c) for c in cps]
    dead_edge[2]["requires"] = cps[0]["id"]
    dead_edge[2]["implies"] = cps[0]["id"]
    assert any(
        "dead edge" in p
        for p in builder.validate_structure({**good, "checkpoints": dead_edge})
    )


def test_checkpoints_and_critique_prompts_document_implies():
    """D1-C — both LLM passes teach the superset rule: the DRAFT prompt
    documents the `implies` field, the CRITIQUE prompt's overlap pass knows the
    directional SUPERSET special case + preserves existing edges."""
    assert "implies" in builder.CHECKPOINTS_PROMPT
    assert "SUPERSET" in builder.CHECKPOINTS_PROMPT
    assert "implies" in builder.CRITIQUE_PROMPT
    assert "SUPERSET" in builder.CRITIQUE_PROMPT


def test_lexical_overlap_flags_near_duplicates():
    cps = [
        {
            "id": "a",
            "success_criteria": "User states their alibi for last night at the bar.",
        },
        {
            "id": "b",
            "success_criteria": "User states their alibi for last night at the bar.",
        },
        {"id": "c", "success_criteria": "User denies belonging to any criminal gang."},
    ]
    pairs = builder.lexical_overlap_pairs(cps)
    flagged = {(a, b) for a, b, _ in pairs}
    assert ("a", "b") in flagged
    assert ("a", "c") not in flagged


def test_hint_prompt_drift_flags_mismatched_pairs():
    """Story 6.20 AC4 — a checkpoint whose hint_text and prompt_segment talk
    about different things (low salient-token overlap) is flagged; an aligned
    pair is not."""
    cps = [
        {
            # Aligned: hint + prompt share "alibi"/"bar"/"night" content tokens.
            "id": "aligned",
            "hint_text": "Give your alibi for last night at the bar.",
            "prompt_segment": "Ask them to account for their alibi for last "
            "night — where were they, were they really at the bar?",
            "success_criteria": "User provides an alibi.",
        },
        {
            # Drifted: hint is about a receipt, prompt is about a phone call.
            "id": "drifted",
            "hint_text": "Show the cashier your receipt for the purchase.",
            "prompt_segment": "Demand to know who they telephoned during the "
            "evening and why nobody answered.",
            "success_criteria": "User explains the call.",
        },
    ]
    flagged = {cid for cid, _ in builder.hint_prompt_drift_pairs(cps)}
    assert "drifted" in flagged
    assert "aligned" not in flagged


def test_hint_prompt_drift_skips_empty_hint_tokens():
    """A hint with no salient tokens (all stopwords) is skipped — nothing to
    measure, not a drift."""
    cps = [
        {
            "id": "stopwords_only",
            "hint_text": "Tell them what you want.",
            "prompt_segment": "Interrogate the suspect about the missing files.",
            "success_criteria": "...",
        }
    ]
    assert builder.hint_prompt_drift_pairs(cps) == []


def test_suggest_patience_start_scales_with_length():
    """Story 6.28 — single-arg, anchored on the medium preset constants
    (scenarios carry no authored difficulty; the meter must be playable at
    every global level)."""
    short = builder.suggest_patience_start(6)
    long = builder.suggest_patience_start(20)
    assert long > short  # longer scenario gets more headroom
    assert short == 80  # medium anchor: fail 20 × 4 absorbable misses
    assert long % 5 == 0  # rounded to the nearest 5


def test_build_base_prompt_has_facts_and_no_speak_first():
    bp = builder.build_base_prompt(_brief())
    assert "Officer Dale" in bp
    assert "Fingerprints were found at the scene." in bp
    assert builder._SPEAK_FIRST_GUARD not in bp
    # Story 6.19 — the per-difficulty behavior block is composed at LOAD time
    # (scenarios._DIFFICULTY_PROMPTS), never woven into the generated base_prompt;
    # the builder must emit a base_prompt the loader's new guard accepts.
    assert builder._DIFFICULTY_BLOCK_GUARD not in bp


# ============================================================
# Assembly + structural validation
# ============================================================


def test_assemble_scenario_matches_schema():
    scenario = builder.assemble_scenario(
        scenario_id="cop_interrogation_01",
        title="The Suspect",
        rive_character="cop",
        base_prompt="You are Officer Dale.",
        checkpoints=_checkpoints(3),
        brief=_brief(3),
    )
    md = scenario["metadata"]
    assert md["id"] == "cop_interrogation_01"
    # Story 6.28 — the builder emits NO difficulty key; display_order is a
    # null placeholder (sorts last) the operator may set later.
    assert "difficulty" not in md
    assert md["display_order"] is None
    assert md["rive_character"] == "cop"
    assert md["is_free"] is False
    # all 8 nullable patience override keys present
    for key in (
        "patience_start",
        "fail_penalty",
        "silence_penalty",
        "recovery_bonus",
        "silence_prompt_seconds",
        "silence_hangup_seconds",
        "ladder_impatience_seconds",
        "escalation_thresholds",
    ):
        assert key in md
    assert md["patience_start"] > 0  # sized, not null
    assert set(scenario["exit_lines"]) == {"hangup", "completion", "patience_warning"}
    assert set(scenario["briefing"]) == {"vocabulary", "context", "expect"}


def test_validate_structure_rejects_difficulty_coded_persona():
    """Story 6.19 follow-up — the builder mirrors the loader's difficulty-neutral
    guard: a base_prompt that freezes a difficulty stance into its prose is
    flagged, so the builder can never WRITE a persona the loader would reject."""
    scenario = builder.assemble_scenario(
        scenario_id="x",
        title="X",
        rive_character="cop",
        base_prompt=(
            "You are Officer Dale. If they make grammar mistakes, squint at them."
        ),
        checkpoints=_checkpoints(2),
        brief=_brief(2),
    )
    problems = builder.validate_structure(scenario)
    assert any("difficulty-coded" in p for p in problems), problems


def test_validate_structure_rejects_permissive_criteria():
    """Story 10.7 (Bug A, R8) — the builder mirrors the loader's blanket-permissive
    guard: a success_criteria granting a catch-all pass ("any … counts") is
    flagged, so the builder can never WRITE the call_id=340 self-playing scenario."""
    good = builder.assemble_scenario(
        scenario_id="x",
        title="X",
        rive_character="cop",
        base_prompt="You are X.",
        checkpoints=_checkpoints(3),
        brief=_brief(3),
    )
    cps = [dict(c) for c in good["checkpoints"]]
    cps[1]["success_criteria"] = (
        "User responds. Any acknowledgement of the request counts."
    )
    problems = builder.validate_structure({**good, "checkpoints": cps})
    assert any("blanket-permissive" in p or "R8" in p for p in problems), problems


def test_validate_structure_accepts_good_scenario():
    scenario = builder.assemble_scenario(
        scenario_id="cop_interrogation_01",
        title="The Suspect",
        rive_character="cop",
        base_prompt="You are Officer Dale.",
        checkpoints=_checkpoints(3),
        brief=_brief(3),
    )
    assert builder.validate_structure(scenario) == []


def test_validate_structure_rejects_bad_inputs():
    good = builder.assemble_scenario(
        scenario_id="x",
        title="X",
        rive_character="cop",
        base_prompt="You are X.",
        checkpoints=_checkpoints(2),
        brief=_brief(2),
    )

    bad_char = {**good, "metadata": {**good["metadata"], "rive_character": "dragon"}}
    assert any("rive_character" in p for p in builder.validate_structure(bad_char))

    speak_first = {
        **good,
        "base_prompt": "Intro. " + builder._SPEAK_FIRST_GUARD + " now.",
    }
    assert any("speak-first" in p for p in builder.validate_structure(speak_first))

    dup = {
        **good,
        "checkpoints": [
            {
                "id": "z",
                "hint_text": "h",
                "prompt_segment": "p",
                "success_criteria": "s",
            },
            {
                "id": "z",
                "hint_text": "h",
                "prompt_segment": "p",
                "success_criteria": "s",
            },
        ],
    }
    assert any("duplicate" in p for p in builder.validate_structure(dup))

    missing = {
        **good,
        "checkpoints": [
            {"id": "z", "hint_text": "", "prompt_segment": "p", "success_criteria": "s"}
        ],
    }
    assert any("hint_text" in p for p in builder.validate_structure(missing))

    empty = {**good, "checkpoints": []}
    assert any("non-empty list" in p for p in builder.validate_structure(empty))


def test_scenario_yaml_is_loadable_and_passes_structure():
    scenario = builder.assemble_scenario(
        scenario_id="cop_interrogation_01",
        title="The Suspect",
        rive_character="cop",
        base_prompt="You are Officer Dale.\n\nBe suspicious.",
        checkpoints=_checkpoints(20),
        brief=_brief(20),
    )
    text = builder.scenario_to_yaml(scenario)
    reloaded = yaml.safe_load(text)
    assert builder.validate_structure(reloaded) == []
    assert len(reloaded["checkpoints"]) == 20
    assert reloaded["metadata"]["id"] == "cop_interrogation_01"


# ============================================================
# JSON parsing tolerance
# ============================================================


def test_parse_json_object_tolerates_fences():
    assert builder.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert builder.parse_json_object('noise {"a": 2} trailing') == {"a": 2}
    assert builder.parse_json_object("not json") is None


def test_parse_json_array_handles_array_and_wrapper():
    assert builder.parse_json_array('[{"id":"a"}]') == [{"id": "a"}]
    assert builder.parse_json_array('{"checkpoints":[{"id":"b"}]}') == [{"id": "b"}]
    assert builder.parse_json_array("nope") is None


# ============================================================
# Pure finalize + full pipeline with a fake LLM
# ============================================================


def test_select_voice_keeps_default_when_no_gender_match():
    """Regression (review 2026-06-02): if no catalog voice matches required_gender,
    keep the DEFAULT voice (AC2 — a female puppet must not get a male voice)
    instead of silently widening to the full catalog."""
    voices = [
        {
            "id": "v1",
            "name": "Bob",
            "gender": "masculine",
            "country": "US",
            "description": "deep",
        }
    ]
    vid, reason = _run(
        builder.select_voice(
            brief=_brief(),
            voices=voices,
            llm=ScriptedLLM(
                ["{}"]
            ),  # never reached — empty feminine pool returns first
            required_gender="feminine",
        )
    )
    assert vid is None
    assert "feminine" in reason


def test_finalize_build_produces_valid_loadable_scenario():
    result = builder.finalize_build(
        brief=_brief(20),
        checkpoints=_checkpoints(20),
        scenario_id="cop_interrogation_01",
        title="The Suspect",
        rive_character="cop",
    )
    assert result.structural_problems == []
    assert len(result.checkpoints) == 20


def test_finalize_build_flags_checkpoint_count_mismatch():
    """Regression (review 2026-06-02): AC3 requires EXACTLY N checkpoints. A
    short/long generation must surface as a structural problem (which blocks the
    write in build_scenario.py), not ship silently."""
    result = builder.finalize_build(
        brief=_brief(2),
        checkpoints=_checkpoints(2),  # generator produced 2...
        scenario_id="cop_interrogation_01",
        title="The Suspect",
        rive_character="cop",
        expected_checkpoints=20,  # ...but 20 were requested
    )
    assert any("expected exactly 20" in p for p in result.structural_problems)


def test_finalize_build_no_count_problem_when_count_matches():
    """The AC3 count check must not false-positive when the count is right."""
    result = builder.finalize_build(
        brief=_brief(20),
        checkpoints=_checkpoints(20),
        scenario_id="cop_interrogation_01",
        title="The Suspect",
        rive_character="cop",
        expected_checkpoints=20,
    )
    assert result.structural_problems == []
    reloaded = yaml.safe_load(result.yaml_text)
    assert builder.validate_structure(reloaded) == []


def test_build_scenario_pipeline_with_fake_llm():
    import json

    n = 3
    responses = [
        json.dumps(_brief(n)),  # expand_brief
        json.dumps(_checkpoints(n)),  # draft_checkpoints
        json.dumps(_checkpoints(n)),  # critique_and_repair (1 round)
    ]
    llm = ScriptedLLM(responses)
    result = _run(
        builder.build_scenario(
            "A cop calls about your fingerprints at a crime scene.",
            scenario_id="cop_interrogation_01",
            rive_character="cop",
            n_checkpoints=n,
            llm=llm,
        )
    )
    assert result.structural_problems == []
    assert len(result.checkpoints) == n
    assert result.scenario["metadata"]["rive_character"] == "cop"
    assert llm._i == 3  # expand + draft + 1 critique round


# ============================================================
# Voice selection (Story 6.17)
# ============================================================


class _VoiceLLM:
    def __init__(self, response: str) -> None:
        self._r = response

    async def chat(self, messages, *, system, temperature, max_tokens) -> str:
        return self._r


_VOICES = [
    {
        "id": "en1",
        "name": "Ron",
        "gender": "masculine",
        "country": "US",
        "description": "deep intense male",
    },
    {
        "id": "en2",
        "name": "Gem",
        "gender": "feminine",
        "country": "GB",
        "description": "British female",
    },
]


def test_select_voice_picks_valid_id():
    llm = _VoiceLLM('{"voice_id": "en1", "reason": "fits a detective"}')
    vid, reason = _run(builder.select_voice(brief=_brief(), voices=_VOICES, llm=llm))
    assert vid == "en1"
    assert "detective" in reason


def test_select_voice_rejects_id_not_in_catalog():
    llm = _VoiceLLM('{"voice_id": "made-up-id"}')
    vid, _ = _run(builder.select_voice(brief=_brief(), voices=_VOICES, llm=llm))
    assert vid is None


def test_select_voice_empty_catalog():
    vid, _ = _run(builder.select_voice(brief=_brief(), voices=[], llm=_VoiceLLM("{}")))
    assert vid is None


def test_character_profiles_cover_all_puppets():
    assert set(builder.RIVE_CHARACTERS) == set(builder.CHARACTER_PROFILES)
    for prof in builder.CHARACTER_PROFILES.values():
        assert prof["gender"] in ("masculine", "feminine")
        assert prof["look"].strip()
        assert prof["voice_hint"].strip()


def test_select_voice_respects_required_gender():
    voices = [
        {
            "id": "m1",
            "name": "Man",
            "gender": "masculine",
            "country": "US",
            "description": "deep male",
        },
        {
            "id": "f1",
            "name": "Woman",
            "gender": "feminine",
            "country": "US",
            "description": "warm female",
        },
    ]
    # The LLM tries to pick the feminine voice, but the puppet is masculine →
    # f1 is filtered out of the pool, so it's rejected (falls back to default).
    llm_bad = _VoiceLLM('{"voice_id": "f1"}')
    vid, _ = _run(
        builder.select_voice(
            brief=_brief(), voices=voices, llm=llm_bad, required_gender="masculine"
        )
    )
    assert vid is None
    # Picking the masculine voice is accepted.
    llm_ok = _VoiceLLM('{"voice_id": "m1", "reason": "deep male fits"}')
    vid2, _ = _run(
        builder.select_voice(
            brief=_brief(), voices=voices, llm=llm_ok, required_gender="masculine"
        )
    )
    assert vid2 == "m1"


def test_fetch_cartesia_voices_filters_to_english(monkeypatch):
    body = {
        "data": [
            {
                "id": "en1",
                "name": "A",
                "gender": "masculine",
                "language": "en",
                "country": "US",
                "description": "x",
            },
            {
                "id": "es1",
                "name": "B",
                "gender": "feminine",
                "language": "es",
                "country": "MX",
                "description": "y",
            },
        ],
        "has_more": False,
        "next_page": None,
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    orig = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: orig(transport=httpx.MockTransport(handler)),
    )
    voices = _run(builder.fetch_cartesia_voices("fake-key"))
    assert [v["id"] for v in voices] == ["en1"]  # spanish filtered out
    assert voices[0]["country"] == "US"


def test_assemble_threads_opening_line_and_base_prompt_notes_it():
    brief = _brief(2)
    brief["opening_line"] = "This is Detective Mercer. Answer my questions."
    bp = builder.build_base_prompt(brief)
    sc = builder.assemble_scenario(
        scenario_id="x",
        title="X",
        rive_character="cop",
        base_prompt=bp,
        checkpoints=_checkpoints(2),
        brief=brief,
    )
    # Story 6.17 — the per-scenario opening line is in metadata (bot.py plays it)
    # and the base_prompt tells the character it has already been spoken.
    assert (
        sc["metadata"]["opening_line"]
        == "This is Detective Mercer. Answer my questions."
    )
    assert "OPEN the call by saying" in bp
    assert "Detective Mercer" in bp


def test_assemble_scenario_threads_voice_id():
    sc = builder.assemble_scenario(
        scenario_id="x",
        title="X",
        rive_character="cop",
        base_prompt="You are X.",
        checkpoints=_checkpoints(2),
        brief=_brief(2),
        tts_voice_id="voice-xyz",
    )
    assert sc["metadata"]["tts_voice_id"] == "voice-xyz"


def test_build_scenario_without_cartesia_key_leaves_voice_null():
    import json

    n = 3
    llm = ScriptedLLM(
        [
            json.dumps(_brief(n)),
            json.dumps(_checkpoints(n)),
            json.dumps(_checkpoints(n)),
        ]
    )
    result = _run(
        builder.build_scenario(
            "a premise",
            scenario_id="cop_x_01",
            rive_character="cop",
            n_checkpoints=n,
            cartesia_api_key=None,
            llm=llm,
        )
    )
    assert result.voice_id is None
    assert result.scenario["metadata"]["tts_voice_id"] is None
    assert "Cartesia" in result.voice_reason


def test_build_scenario_with_cartesia_key_picks_voice(monkeypatch):
    import json

    body = {
        "data": [
            {
                "id": "en1",
                "name": "Ron",
                "gender": "masculine",
                "language": "en",
                "country": "US",
                "description": "deep intense male",
            },
        ],
        "has_more": False,
        "next_page": None,
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    orig = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: orig(transport=httpx.MockTransport(handler))
    )

    n = 3
    # responses in call order: expand, draft, critique, voice-select
    llm = ScriptedLLM(
        [
            json.dumps(_brief(n)),
            json.dumps(_checkpoints(n)),
            json.dumps(_checkpoints(n)),
            '{"voice_id": "en1", "reason": "deep male fits the detective"}',
        ]
    )
    result = _run(
        builder.build_scenario(
            "a premise",
            scenario_id="cop_x_01",
            rive_character="cop",
            n_checkpoints=n,
            cartesia_api_key="fake-key",
            llm=llm,
        )
    )
    assert result.voice_id == "en1"
    assert result.scenario["metadata"]["tts_voice_id"] == "en1"


def test_format_build_summary_is_readable():
    result = builder.finalize_build(
        brief=_brief(20),
        checkpoints=_checkpoints(20),
        scenario_id="cop_x_01",
        title="The Suspect",
        rive_character="cop",
        voice_id="vid-1",
        voice_reason="deep male fits the detective",
    )
    s = builder.format_build_summary(result)
    assert "The Suspect" in s
    assert "cop" in s
    assert "vid-1" in s
    assert "Les 20 étapes" in s
    assert "Do step 1." in s
    assert "Do step 20." in s
    # persona + briefing surfaced
    assert "suspicious detective" in s
    assert "Contexte :" in s


# ============================================================
# Auto build → validate → repair loop (Story 6.17)
# ============================================================


class _StrictAwareJudge:
    """A `JudgeLLM` that ACCEPTS (met=True) when a goal's success_criteria is
    lenient (lacks 'STRICT'), and REJECTS (met=False) once it contains 'STRICT'.
    So an off-topic seed case wrongly passes until the criteria are tightened."""

    async def classify_multi(
        self, *, user_text, last_character_line, pending_goals, scenario_description
    ):
        return {
            g["id"]: ("STRICT" not in g.get("success_criteria", ""))
            for g in pending_goals
        }


def _repair_llm(n: int, *, strict: bool):
    body = json.dumps(
        [
            {
                "id": f"beat_{i}",
                "hint_text": f"h{i}",
                "prompt_segment": f"p{i}",
                "success_criteria": (
                    f"STRICT accomplish {i}" if strict else f"lenient {i}"
                ),
            }
            for i in range(1, n + 1)
        ]
    )

    class _LLM:
        async def chat(self, messages, *, system, temperature, max_tokens) -> str:
            return body

    return _LLM()


def test_repair_checkpoints_targets_failures():
    cps = _checkpoints(2)
    case = engine.GoldenCase(
        checkpoint_id="beat_1",
        kind="negative",
        source="seed",
        character_line="",
        user_text="nice weather",
    )
    cr = engine.GoldenCaseResult(case=case, verdict=True, status="fail")
    golden = engine.GoldenResult(
        scenario_id="x",
        passed=False,
        reviewed_fixture=False,
        fixture_present=False,
        negative_total=1,
        negative_failures=[cr],
        negative_warnings=[],
        positive_total=0,
        positive_met=0,
        positive_misses=[],
        all_results=[cr],
    )
    out = _run(
        builder.repair_checkpoints_from_golden(
            cps, golden, _brief(2), llm=_repair_llm(2, strict=True)
        )
    )
    assert any("STRICT" in c["success_criteria"] for c in out)


def test_validate_and_repair_fixes_then_passes():
    n = 2
    result = builder.finalize_build(
        brief=_brief(n),
        checkpoints=_checkpoints(n),
        scenario_id="fake_test_01",
        title="T",
        rive_character="cop",
    )
    v = _run(
        builder.validate_and_repair(
            result,
            scenario_id="fake_test_01",
            rive_character="cop",
            llm=_repair_llm(n, strict=True),
            judge=_StrictAwareJudge(),
            max_repair_rounds=2,
        )
    )
    assert v.passed is True
    assert v.repair_rounds == 1
    assert all("STRICT" in cp["success_criteria"] for cp in v.result.checkpoints)


def test_validate_and_repair_gives_up_after_max_rounds():
    n = 2
    result = builder.finalize_build(
        brief=_brief(n),
        checkpoints=_checkpoints(n),
        scenario_id="fake_test_01",
        title="T",
        rive_character="cop",
    )
    v = _run(
        builder.validate_and_repair(
            result,
            scenario_id="fake_test_01",
            rive_character="cop",
            llm=_repair_llm(n, strict=False),
            judge=_StrictAwareJudge(),
            max_repair_rounds=1,
        )
    )
    assert v.passed is False
    assert v.repair_rounds == 1
    assert len(v.golden.negative_failures) > 0


def test_build_scenario_rejects_bad_character():
    llm = ScriptedLLM(["{}"])
    try:
        _run(
            builder.build_scenario(
                "x",
                scenario_id="x",
                rive_character="dragon",
                n_checkpoints=3,
                llm=llm,
            )
        )
        raised = False
    except ValueError:
        raised = True
    assert raised
