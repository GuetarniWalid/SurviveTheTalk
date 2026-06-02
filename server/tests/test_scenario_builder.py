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


def test_suggest_patience_start_scales_with_length_and_difficulty():
    short_hard = builder.suggest_patience_start(6, "hard")
    long_hard = builder.suggest_patience_start(20, "hard")
    assert long_hard > short_hard  # longer scenario gets more headroom
    assert builder.suggest_patience_start(6, "easy") > builder.suggest_patience_start(
        6, "hard"
    )
    assert short_hard > 0


def test_build_base_prompt_has_facts_and_no_speak_first():
    bp = builder.build_base_prompt(_brief(), difficulty="hard")
    assert "Officer Dale" in bp
    assert "Fingerprints were found at the scene." in bp
    assert builder._SPEAK_FIRST_GUARD not in bp
    assert "hard" in bp.lower()


# ============================================================
# Assembly + structural validation
# ============================================================


def test_assemble_scenario_matches_schema():
    scenario = builder.assemble_scenario(
        scenario_id="cop_interrogation_01",
        title="The Suspect",
        difficulty="hard",
        rive_character="cop",
        base_prompt="You are Officer Dale.",
        checkpoints=_checkpoints(3),
        brief=_brief(3),
    )
    md = scenario["metadata"]
    assert md["id"] == "cop_interrogation_01"
    assert md["difficulty"] == "hard"
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


def test_validate_structure_accepts_good_scenario():
    scenario = builder.assemble_scenario(
        scenario_id="cop_interrogation_01",
        title="The Suspect",
        difficulty="hard",
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
        difficulty="hard",
        rive_character="cop",
        base_prompt="You are X.",
        checkpoints=_checkpoints(2),
        brief=_brief(2),
    )

    bad_diff = {**good, "metadata": {**good["metadata"], "difficulty": "extreme"}}
    assert any("difficulty" in p for p in builder.validate_structure(bad_diff))

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
        difficulty="hard",
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


def test_finalize_build_produces_valid_loadable_scenario():
    result = builder.finalize_build(
        brief=_brief(20),
        checkpoints=_checkpoints(20),
        scenario_id="cop_interrogation_01",
        title="The Suspect",
        difficulty="hard",
        rive_character="cop",
    )
    assert result.structural_problems == []
    assert len(result.checkpoints) == 20
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
            difficulty="hard",
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


def test_assemble_scenario_threads_voice_id():
    sc = builder.assemble_scenario(
        scenario_id="x",
        title="X",
        difficulty="hard",
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
            difficulty="hard",
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
            difficulty="hard",
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
        difficulty="hard",
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
        difficulty="hard",
        rive_character="cop",
    )
    v = _run(
        builder.validate_and_repair(
            result,
            scenario_id="fake_test_01",
            difficulty="hard",
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
        difficulty="hard",
        rive_character="cop",
    )
    v = _run(
        builder.validate_and_repair(
            result,
            scenario_id="fake_test_01",
            difficulty="hard",
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
                difficulty="hard",
                rive_character="dragon",
                n_checkpoints=3,
                llm=llm,
            )
        )
        raised = False
    except ValueError:
        raised = True
    assert raised
