"""Story 6.15 — unit tests for the scenario validation engine LOGIC.

These run in the default `pytest` gate (AC6): they exercise the engine's pure
logic + the simulator/golden runner driven with FAKE LLMs — NO network, NO API
key, NO cost, deterministic. The live-LLM paths (real Groq judge + character)
are gated out of pytest by file location (only `scripts/calibrate_scenario.py`
invokes them), exactly like `benchmark_classifier.py`.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import scripts.calibration_engine as engine

# ============================================================
# Helpers + fakes (no network)
# ============================================================


def _run(coro):
    """Drive a coroutine to completion (project idiom — no pytest-asyncio)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class FakeChat:
    """A `ChatLLM` that returns a canned line (optionally cycling a script)."""

    def __init__(self, lines: list[str] | None = None) -> None:
        self._lines = lines or ["(canned character/learner line)"]
        self._i = 0

    async def chat(self, messages, *, system, temperature, max_tokens) -> str:
        line = self._lines[self._i % len(self._lines)]
        self._i += 1
        return line


class FakeJudge:
    """A `JudgeLLM` whose verdict is computed by an injected function of
    `(user_text, goal_ids)` → dict. Defaults to all-unmet."""

    def __init__(self, fn=None) -> None:
        self._fn = fn or (lambda user_text, goal_ids: {g: False for g in goal_ids})
        self.calls: list[dict] = []

    async def classify_multi(
        self, *, user_text, last_character_line, pending_goals, scenario_description
    ):
        goal_ids = [g["id"] for g in pending_goals]
        self.calls.append({"user_text": user_text, "goal_ids": goal_ids})
        return self._fn(user_text, goal_ids)


def _scenario_data(
    *, checkpoints, difficulty="easy", patience=None, title="Test", briefing=None
) -> engine._ScenarioData:
    return engine._ScenarioData(
        scenario_id="fake_test_01",
        title=title,
        difficulty=difficulty,
        base_prompt="You are a test character.",
        checkpoints=checkpoints,
        briefing=briefing or {},
        patience=patience
        or {
            "initial_patience": 30,
            "fail_penalty": -15,
            "recovery_bonus": 5,
        },
    )


def _cp(cid: str) -> dict:
    return {
        "id": cid,
        "hint_text": f"hint {cid}",
        "prompt_segment": f"Pursue {cid}.",
        "success_criteria": f"User accomplishes {cid}.",
    }


# ============================================================
# Band logic (AC9 / AC12)
# ============================================================


def test_classify_band_in_band_and_warnings():
    band = (60, 80)
    assert engine.classify_band(70, band) == "in_band"
    assert engine.classify_band(60, band) == "in_band"
    assert engine.classify_band(80, band) == "in_band"
    # within ±5 of an edge → warning (still passes)
    assert engine.classify_band(57, band) == "warning_low"
    assert engine.classify_band(83, band) == "warning_high"
    # beyond the margin → hard verdicts
    assert engine.classify_band(40, band) == "too_hard"
    assert engine.classify_band(95, band) == "too_easy"


def test_band_for_difficulty_and_override():
    assert engine.band_for_difficulty("easy") == (60, 80)
    assert engine.band_for_difficulty("medium") == (35, 55)
    assert engine.band_for_difficulty("hard") == (15, 35)
    assert engine.band_for_difficulty("hard", override=(10, 20)) == (10, 20)
    with pytest.raises(ValueError):
        engine.band_for_difficulty("impossible")


# ============================================================
# Calibration gate (AC4 / AC9)
# ============================================================


def _conv(outcome: str) -> engine.ConversationResult:
    return engine.ConversationResult(
        scenario_id="fake_test_01",
        strategy="cooperative",
        outcome=outcome,
        final_patience=0 if outcome == "character_hung_up" else 50,
        goals_met_count=3 if outcome == "survived" else 1,
        total_goals=3,
        turns=[],
    )


def test_evaluate_calibration_in_band_passes():
    coop = [_conv("survived")] * 7 + [_conv("character_hung_up")] * 3  # 70%
    offt = [_conv("character_hung_up")] * 10  # 0% survived
    result = engine.evaluate_calibration(
        scenario_id="fake_test_01",
        difficulty="easy",
        cooperative_runs=coop,
        offtopic_runs=offt,
    )
    assert result.cooperative_rate == 70.0
    assert result.band_verdict == "in_band"
    assert result.guardrail_ok is True
    assert result.passed is True


def test_evaluate_calibration_too_easy_fails():
    coop = [_conv("survived")] * 10  # 100% — well above easy band
    offt = [_conv("character_hung_up")] * 10
    result = engine.evaluate_calibration(
        scenario_id="fake_test_01",
        difficulty="easy",
        cooperative_runs=coop,
        offtopic_runs=offt,
    )
    assert result.band_verdict == "too_easy"
    assert result.passed is False


def test_evaluate_calibration_offtopic_breach_fails():
    coop = [_conv("survived")] * 7 + [_conv("character_hung_up")] * 3  # 70% in band
    offt = [_conv("survived")] * 1 + [_conv("character_hung_up")] * 9  # 10% survived!
    result = engine.evaluate_calibration(
        scenario_id="fake_test_01",
        difficulty="easy",
        cooperative_runs=coop,
        offtopic_runs=offt,
    )
    assert result.band_verdict == "in_band"
    assert result.guardrail_ok is False
    assert result.passed is False


# ============================================================
# Staleness hash + ledger (AC10)
# ============================================================


def test_scenario_hash_ignores_cosmetic_changes(monkeypatch):
    base = {
        "metadata": {"id": "x", "difficulty": "easy", "tts_voice_id": "voice-a"},
        "base_prompt": "You are Tina.",
        "checkpoints": [
            {"id": "greet", "prompt_segment": "Greet.", "success_criteria": "Greets."}
        ],
        "briefing": {"context": "ordering"},
        "exit_lines": {"hangup": "bye"},
    }

    def fake_raw(_sid):
        return base

    monkeypatch.setattr(engine, "_load_raw_scenario", fake_raw)
    h1 = engine.compute_scenario_hash("x")

    # Cosmetic change (TTS voice) → SAME hash (no needless revalidation).
    base["metadata"]["tts_voice_id"] = "voice-b"
    base["metadata"]["rive_character"] = "waiter"
    assert engine.compute_scenario_hash("x") == h1


def test_scenario_hash_changes_on_behaviour_edit(monkeypatch):
    base = {
        "metadata": {"id": "x", "difficulty": "easy"},
        "base_prompt": "You are Tina.",
        "checkpoints": [
            {"id": "greet", "prompt_segment": "Greet.", "success_criteria": "Greets."}
        ],
        "briefing": {},
        "exit_lines": {},
    }
    monkeypatch.setattr(engine, "_load_raw_scenario", lambda _sid: base)
    h1 = engine.compute_scenario_hash("x")
    base["checkpoints"][0]["success_criteria"] = "Greets AND asks to order."
    assert engine.compute_scenario_hash("x") != h1


def test_ledger_roundtrip_and_cached_pass(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    verdict = engine.ScenarioVerdict(
        scenario_id="x",
        passed=True,
        golden=None,
        calibration=None,
        scenario_hash="HASH_A",
    )
    ledger = engine.record_verdict({}, verdict, report_path="r.json")
    engine.save_ledger(ledger, path=ledger_path)

    reloaded = engine.load_ledger(path=ledger_path)
    assert reloaded["x"]["verdict"] == "PASS"
    assert reloaded["x"]["engine_version"] == engine.ENGINE_VERSION

    # cached iff PASS + same hash + same engine_version
    assert engine.is_cached_pass(reloaded, "x", "HASH_A") is True
    assert engine.is_cached_pass(reloaded, "x", "HASH_B") is False  # content changed
    assert engine.is_cached_pass(reloaded, "missing", "HASH_A") is False


def test_cached_pass_false_when_engine_version_bumped(tmp_path):
    reloaded = {
        "x": {
            "verdict": "PASS",
            "scenario_hash": "HASH_A",
            "engine_version": engine.ENGINE_VERSION - 1,
        }
    }
    # Rules changed since last validation → must revalidate.
    assert engine.is_cached_pass(reloaded, "x", "HASH_A") is False


def test_cached_pass_false_when_prior_verdict_failed():
    ledger = {
        "x": {
            "verdict": "FAIL",
            "scenario_hash": "HASH_A",
            "engine_version": engine.ENGINE_VERSION,
        }
    }
    assert engine.is_cached_pass(ledger, "x", "HASH_A") is False


# ============================================================
# Learner prompt (AC3)
# ============================================================


def test_learner_prompt_includes_briefing_not_success_criteria():
    prompt = engine.build_learner_system_prompt(
        strategy="cooperative",
        character_title="The Waiter",
        briefing={"context": "ordering food", "expect": "she is impatient"},
    )
    assert "The Waiter" in prompt
    assert "ordering food" in prompt
    assert "impatient" in prompt
    # The learner must NOT be handed the judge's answer key.
    assert "success_criteria" not in prompt


def test_learner_prompt_rejects_unknown_strategy():
    with pytest.raises(ValueError):
        engine.build_learner_system_prompt(
            strategy="cheater", character_title="X", briefing={}
        )


def test_all_strategies_build():
    for strat in engine._LEARNER_STRATEGIES:
        assert engine.build_learner_system_prompt(
            strategy=strat, character_title="X", briefing={}
        )


# ============================================================
# Golden gate (AC2 / AC9 / AC12)
# ============================================================


def _case_result(kind, verdict, *, source="seed", cid="greet"):
    case = engine.GoldenCase(
        checkpoint_id=cid, kind=kind, source=source, character_line="", user_text="x"
    )
    return engine.GoldenCaseResult(
        case=case, verdict=verdict, status=engine._golden_status(case, verdict)
    )


def test_golden_negative_met_is_hard_fail():
    results = [_case_result("negative", True)]  # off-topic accepted → the bug
    g = engine.evaluate_golden_results(
        "x", results, reviewed_fixture=False, fixture_present=False
    )
    assert g.passed is False
    assert len(g.negative_failures) == 1


def test_golden_negative_unsure_is_warning_not_fail():
    results = [_case_result("negative", None)]
    g = engine.evaluate_golden_results(
        "x", results, reviewed_fixture=False, fixture_present=False
    )
    assert g.passed is True
    assert len(g.negative_warnings) == 1
    assert len(g.negative_failures) == 0


def test_golden_positive_gate_requires_90pct_when_reviewed():
    # 8/10 positives met = 80% < 90% → fail
    results = [_case_result("positive", True, source="fixture") for _ in range(8)]
    results += [_case_result("positive", False, source="fixture") for _ in range(2)]
    g = engine.evaluate_golden_results(
        "x", results, reviewed_fixture=True, fixture_present=True
    )
    assert g.positive_total == 10
    assert g.passed is False


def test_golden_unreviewed_fixture_positives_do_not_gate():
    # Same misses, but fixture is NOT reviewed → positives are not gating.
    results = [_case_result("positive", False, source="fixture") for _ in range(5)]
    results += [_case_result("negative", False, source="seed")]
    g = engine.evaluate_golden_results(
        "x", results, reviewed_fixture=False, fixture_present=True
    )
    assert g.positive_total == 0  # not gated
    assert g.passed is True  # only the seed negative gates, and it passed


def test_run_golden_lenient_judge_fails_the_net(tmp_path):
    """AC2 proof: a deliberately over-lenient judge (everything 'met') FAILS the
    golden net on the universal off-topic seed — i.e. the net actually catches
    the 2026-05-30 'judge passes everything' bug it exists for."""
    data = _scenario_data(checkpoints=[_cp("greet"), _cp("order")])
    lenient = FakeJudge(lambda user_text, goal_ids: {g: True for g in goal_ids})
    g = _run(
        engine.run_golden(
            scenario_id="fake_test_01", judge=lenient, data=data, fixture_dir=tmp_path
        )
    )
    assert g.passed is False
    assert len(g.negative_failures) > 0  # seed off-topic lines were accepted


def test_run_golden_correct_judge_passes_the_seed(tmp_path):
    data = _scenario_data(checkpoints=[_cp("greet"), _cp("order")])
    # Correct judge: off-topic seed → unmet (False).
    strict = FakeJudge(lambda user_text, goal_ids: {g: False for g in goal_ids})
    g = _run(
        engine.run_golden(
            scenario_id="fake_test_01", judge=strict, data=data, fixture_dir=tmp_path
        )
    )
    assert g.passed is True
    assert g.negative_total == 2 * len(engine._UNIVERSAL_OFFTOPIC_UTTERANCES)


# ============================================================
# Story 6.23 — reactive-gating: golden assertion + harness parity + hash
# ============================================================


def _cp_req(cid: str, requires: str) -> dict:
    cp = _cp(cid)
    cp["requires"] = requires
    return cp


def test_requires_gating_failures_clean_on_valid_edges():
    """The pure premature-credit assertion returns no failures for a valid
    reactive edge (it's a contract guard over `judgeable_goals`)."""
    checkpoints = [_cp("trigger"), _cp_req("reactive", "trigger")]
    assert engine.requires_gating_failures(checkpoints) == []


def test_requires_gating_failures_clean_on_shipped_cop_scenario():
    """The shipped cop scenario's 7 edges all satisfy the gate contract."""
    from pipeline.scenarios import load_scenario_checkpoints

    checkpoints = load_scenario_checkpoints("cop_interrogation_01")
    assert engine.requires_gating_failures(checkpoints) == []


def test_requires_gating_failures_detects_a_broken_gate(monkeypatch):
    """If `judgeable_goals` were changed to IGNORE `requires` (the exact
    regression this story prevents), the assertion catches it — proving the
    golden net would FAIL a reactive-but-ungated gate."""

    def _broken_gate(checkpoints, goals_state):
        # Returns every pending beat, ignoring `requires` entirely.
        return [cp for cp in checkpoints if goals_state.get(cp["id"]) == "pending"]

    monkeypatch.setattr(engine, "judgeable_goals", _broken_gate)
    checkpoints = [_cp("trigger"), _cp_req("reactive", "trigger")]
    failures = engine.requires_gating_failures(checkpoints)
    assert any("judgeable before its required beat" in f for f in failures)


def test_run_golden_fails_when_gate_is_broken(tmp_path, monkeypatch):
    """AC6 — a broken gate makes the golden net FAIL even with a correct judge,
    and `--golden-only` (which rides on `run_golden`) catches it."""

    def _broken_gate(checkpoints, goals_state):
        return [cp for cp in checkpoints if goals_state.get(cp["id"]) == "pending"]

    monkeypatch.setattr(engine, "judgeable_goals", _broken_gate)
    data = _scenario_data(checkpoints=[_cp("trigger"), _cp_req("reactive", "trigger")])
    strict = FakeJudge(lambda user_text, goal_ids: {g: False for g in goal_ids})
    g = _run(
        engine.run_golden(
            scenario_id="fake_test_01", judge=strict, data=data, fixture_dir=tmp_path
        )
    )
    assert g.passed is False
    assert g.requires_gating_failures  # populated with the diagnostic


def test_harness_gates_reactive_beat_same_as_prod():
    """AC4 — the golden==prod coupling. `simulate_conversation` must judge the
    GATED set (the same `judgeable_goals` prod uses), so a reactive beat is NOT
    offered to the judge until its trigger is met."""
    data = _scenario_data(
        checkpoints=[_cp("alibi"), _cp("lock_times"), _cp_req("correct", "lock_times")]
    )
    # Over-eager judge credits everything it's ASKED about.
    judge = FakeJudge(lambda user_text, goal_ids: {g: True for g in goal_ids})
    result = _run(
        engine.simulate_conversation(
            scenario_id="fake_test_01",
            strategy="cooperative",
            character_llm=FakeChat(["..."]),
            learner_llm=FakeChat(["I was at the diner at half past eight."]),
            judge=judge,
            data=data,
            max_turns=5,
        )
    )
    # Turn 1's judge payload must EXCLUDE the gated reactive beat.
    assert "correct" not in judge.calls[0]["goal_ids"]
    assert set(judge.calls[0]["goal_ids"]) == {"alibi", "lock_times"}
    # Once the trigger is met, the reactive beat enters the payload (turn 2).
    assert "correct" in judge.calls[1]["goal_ids"]
    assert result.outcome == "survived"


def test_scenario_hash_changes_on_requires_edit(monkeypatch):
    """Adding/removing a `requires` edge is behaviour-affecting → new hash."""
    base = {
        "metadata": {"id": "x", "difficulty": "easy"},
        "base_prompt": "You are Tina.",
        "checkpoints": [
            {"id": "a", "prompt_segment": "A.", "success_criteria": "Does a."},
            {"id": "b", "prompt_segment": "B.", "success_criteria": "Does b."},
        ],
        "briefing": {},
        "exit_lines": {},
    }
    monkeypatch.setattr(engine, "_load_raw_scenario", lambda _sid: base)
    h1 = engine.compute_scenario_hash("x")
    base["checkpoints"][1]["requires"] = "a"
    assert engine.compute_scenario_hash("x") != h1


# ============================================================
# Story 6.27 — `implies` back-fill: golden assertion + harness parity + hash
# ============================================================


def _cp_imp(cid: str, implies: str) -> dict:
    cp = _cp(cid)
    cp["implies"] = implies
    return cp


def test_implies_backfill_failures_clean_on_valid_edges():
    """The pure back-fill assertion returns no failures for a valid `implies`
    edge (it's a contract guard over the REAL shared `advance_goals`)."""
    checkpoints = [_cp("first"), _cp_imp("later", "first")]
    assert engine.implies_backfill_failures(checkpoints) == []


def test_implies_backfill_failures_clean_on_shipped_scenarios():
    """Every shipped scenario's `implies` edges satisfy the back-fill contract
    — guards the Story 6.27 T3 data edits against drift."""
    from pipeline.scenarios import _SCENARIO_INDEX, load_scenario_checkpoints

    for sid in sorted(_SCENARIO_INDEX):
        checkpoints = load_scenario_checkpoints(sid)
        assert engine.implies_backfill_failures(checkpoints) == [], sid


def test_implies_backfill_failures_detects_a_broken_backfill(monkeypatch):
    """If `advance_goals` were reverted to the pre-6.27 rule (no back-fill —
    the exact regression this assertion exists to catch), the golden net
    flags every `implies` edge as wired wrong."""
    from types import SimpleNamespace

    def _no_backfill(goals_state, verdicts, *, checkpoints):
        flipped = [
            gid
            for gid, verdict in verdicts.items()
            if verdict is True and goals_state.get(gid) == "pending"
        ]
        new_goals = dict(goals_state)
        for gid in flipped:
            new_goals[gid] = "met"
        return SimpleNamespace(new_goals=new_goals, flipped_ids=flipped)

    monkeypatch.setattr(engine, "advance_goals", _no_backfill)
    checkpoints = [_cp("first"), _cp_imp("later", "first")]
    failures = engine.implies_backfill_failures(checkpoints)
    assert any("does NOT back-fill" in f for f in failures)


def test_run_golden_fails_when_backfill_is_broken(tmp_path, monkeypatch):
    """AC2 — a broken back-fill makes the golden net FAIL even with a correct
    judge, and `--golden-only` (which rides on `run_golden`) catches it."""
    from types import SimpleNamespace

    def _no_backfill(goals_state, verdicts, *, checkpoints):
        flipped = [
            gid
            for gid, verdict in verdicts.items()
            if verdict is True and goals_state.get(gid) == "pending"
        ]
        new_goals = dict(goals_state)
        for gid in flipped:
            new_goals[gid] = "met"
        return SimpleNamespace(new_goals=new_goals, flipped_ids=flipped)

    monkeypatch.setattr(engine, "advance_goals", _no_backfill)
    data = _scenario_data(checkpoints=[_cp("first"), _cp_imp("later", "first")])
    strict = FakeJudge(lambda user_text, goal_ids: {g: False for g in goal_ids})
    g = _run(
        engine.run_golden(
            scenario_id="fake_test_01", judge=strict, data=data, fixture_dir=tmp_path
        )
    )
    assert g.passed is False
    assert g.implies_backfill_failures  # populated with the diagnostic


def test_harness_backfills_implied_beat_same_as_prod():
    """AC2 — the golden==prod coupling for the back-fill. `simulate_conversation`
    threads `checkpoints=` into the REAL `advance_goals`, so a judge that
    credits ONLY the narrower later beat still completes the scenario (the
    implied earlier beat is back-filled, exactly as prod does)."""
    data = _scenario_data(checkpoints=[_cp("first"), _cp_imp("later", "first")])
    # The call-266 judge behaviour: credits the narrower beat, declines the
    # broader earlier one on the same text.
    judge = FakeJudge(lambda user_text, goal_ids: {g: (g == "later") for g in goal_ids})
    result = _run(
        engine.simulate_conversation(
            scenario_id="fake_test_01",
            strategy="cooperative",
            character_llm=FakeChat(["..."]),
            learner_llm=FakeChat(["I do the later thing."]),
            judge=judge,
            data=data,
            max_turns=5,
        )
    )
    assert result.outcome == "survived"
    assert result.goals_met_count == 2


def test_scenario_hash_changes_on_implies_edit(monkeypatch):
    """Adding/removing an `implies` edge is behaviour-affecting → new hash."""
    base = {
        "metadata": {"id": "x", "difficulty": "easy"},
        "base_prompt": "You are Tina.",
        "checkpoints": [
            {"id": "a", "prompt_segment": "A.", "success_criteria": "Does a."},
            {"id": "b", "prompt_segment": "B.", "success_criteria": "Does b."},
        ],
        "briefing": {},
        "exit_lines": {},
    }
    monkeypatch.setattr(engine, "_load_raw_scenario", lambda _sid: base)
    h1 = engine.compute_scenario_hash("x")
    base["checkpoints"][1]["implies"] = "a"
    assert engine.compute_scenario_hash("x") != h1


def test_engine_version_bumped_for_backfill_rule():
    """The Story 6.27 flip-rule change must force ledger revalidation on the
    next sweep."""
    assert engine.ENGINE_VERSION == 4


# ============================================================
# Simulator (AC1) — faithful prod-path replay with fakes
# ============================================================


def test_simulate_survives_when_all_goals_met():
    data = _scenario_data(checkpoints=[_cp("greet")])
    judge = FakeJudge(lambda user_text, goal_ids: {g: True for g in goal_ids})
    result = _run(
        engine.simulate_conversation(
            scenario_id="fake_test_01",
            strategy="cooperative",
            character_llm=FakeChat(["What can I get you?"]),
            learner_llm=FakeChat(["I want to order."]),
            judge=judge,
            data=data,
            max_turns=5,
        )
    )
    assert result.outcome == "survived"
    assert result.goals_met_count == 1


def test_simulate_hangs_up_when_patience_drains():
    # 2 goals, never met; patience 30, fail -15 → 30→15→0 → hang up on turn 2.
    data = _scenario_data(checkpoints=[_cp("a"), _cp("b")])
    judge = FakeJudge(lambda user_text, goal_ids: {g: False for g in goal_ids})
    result = _run(
        engine.simulate_conversation(
            scenario_id="fake_test_01",
            strategy="off_topic",
            character_llm=FakeChat(["..."]),
            learner_llm=FakeChat(["nice weather"]),
            judge=judge,
            data=data,
            max_turns=10,
        )
    )
    assert result.outcome == "character_hung_up"
    assert result.final_patience == 0
    assert len(result.turns) == 2


def test_simulate_in_progress_on_max_turns():
    data = _scenario_data(checkpoints=[_cp("a"), _cp("b")])
    # all-unsure → neutral, never drains, never completes
    judge = FakeJudge(lambda user_text, goal_ids: {g: None for g in goal_ids})
    result = _run(
        engine.simulate_conversation(
            scenario_id="fake_test_01",
            strategy="minimal",
            character_llm=FakeChat(["ok"]),
            learner_llm=FakeChat(["uh"]),
            judge=judge,
            data=data,
            max_turns=3,
        )
    )
    assert result.outcome == "in_progress"
    assert len(result.turns) == 3


def test_simulate_handles_infra_none_as_neutral():
    data = _scenario_data(checkpoints=[_cp("a")])
    judge = FakeJudge(lambda user_text, goal_ids: None)  # whole-None = infra
    result = _run(
        engine.simulate_conversation(
            scenario_id="fake_test_01",
            strategy="cooperative",
            character_llm=FakeChat(["x"]),
            learner_llm=FakeChat(["y"]),
            judge=judge,
            data=data,
            max_turns=2,
        )
    )
    # infra failure never drains nor completes
    assert result.outcome == "in_progress"
    assert result.final_patience == 30


# ============================================================
# Report + failure diagnostic (AC11)
# ============================================================


def test_build_report_has_expected_keys():
    verdict = engine.ScenarioVerdict(
        scenario_id="x",
        passed=True,
        golden=engine.GoldenResult(
            scenario_id="x",
            passed=True,
            reviewed_fixture=True,
            fixture_present=True,
            negative_total=10,
            negative_failures=[],
            negative_warnings=[],
            positive_total=6,
            positive_met=6,
            positive_misses=[],
            all_results=[],
        ),
        calibration=engine.CalibrationResult(
            scenario_id="x",
            difficulty="easy",
            band=(60, 80),
            n=10,
            cooperative_rate=70.0,
            offtopic_rate=0.0,
            band_verdict="in_band",
            guardrail_ok=True,
            passed=True,
        ),
        scenario_hash="HASH",
    )
    report = engine.build_report(verdict)
    assert report["verdict"] == "PASS"
    assert report["scenario_hash"] == "HASH"
    assert report["calibration"]["cooperative_rate"] == 70.0
    # serializable
    json.dumps(report)


def test_failure_report_is_actionable_markdown():
    fail_case = _case_result("negative", True, source="seed", cid="greet")
    golden = engine.GoldenResult(
        scenario_id="waiter_easy_01",
        passed=False,
        reviewed_fixture=True,
        fixture_present=True,
        negative_total=1,
        negative_failures=[fail_case],
        negative_warnings=[],
        positive_total=0,
        positive_met=0,
        positive_misses=[],
        all_results=[fail_case],
    )
    verdict = engine.ScenarioVerdict(
        scenario_id="waiter_easy_01",
        passed=False,
        golden=golden,
        calibration=None,
        scenario_hash="HASH",
    )
    md = engine.format_failure_report(verdict, report_path="r.json")
    assert "waiter_easy_01" in md
    assert "calibrate_scenario.py" in md  # reproduction command
    assert "success_criteria" in md  # names the YAML field to edit
    # real scenario id → indexed field path
    assert "checkpoints[0].success_criteria" in md


# ============================================================
# Catalogue + committed fixture shape (AC13 / AC2)
# ============================================================


def test_list_scenarios_returns_catalogue():
    ids = engine.list_scenarios()
    # The 5 originals must always be present; Story 6.16 (scenario builder) and
    # future authoring can add more, so assert membership + a floor, not an exact
    # count.
    for expected in (
        "waiter_easy_01",
        "mugger_medium_01",
        "girlfriend_medium_01",
        "cop_hard_01",
        "landlord_hard_01",
    ):
        assert expected in ids
    assert len(ids) >= 5


def test_engine_reuses_prod_symbols_not_reimplementation():
    """AC1 guard: the engine must drive the SAME prod decision functions, not a
    fork. If a refactor accidentally re-implements the advance/patience/prompt
    rule in the harness, these identities break."""
    from pipeline import (
        checkpoint_manager,
        exchange_classifier,
        patience_tracker,
        prompts,
    )

    assert engine.advance_goals is checkpoint_manager.advance_goals
    assert engine.step_patience is patience_tracker.step_patience
    assert (
        engine.compose_goal_system_instruction
        is checkpoint_manager.compose_goal_system_instruction
    )
    assert engine.COHERENCE_CHARTER is prompts.COHERENCE_CHARTER
    assert engine.ExchangeClassifier is exchange_classifier.ExchangeClassifier


def test_load_llm_settings_reads_key_only(monkeypatch):
    # conftest seeds GROQ_API_KEY; the dev tools must NOT require the rest of the
    # prod env (Soniox / LiveKit / JWT) — only the LLM key.
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("CLASSIFIER_MODEL", raising=False)
    s = engine.load_llm_settings()
    assert s.groq_api_key == "test-groq-key"
    assert s.classifier_model == "meta-llama/llama-4-scout-17b-16e-instruct"
    assert s.character_model == "llama-3.3-70b-versatile"
    assert s.llm_base_url == "https://api.groq.com/openai/v1"


def test_load_llm_settings_raises_without_any_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        engine.load_llm_settings()


def test_resilient_judge_retries_then_succeeds():
    class _Flaky:
        def __init__(self):
            self.calls = 0

        async def classify_multi(self, **kwargs):
            self.calls += 1
            return None if self.calls < 3 else {"g": True}

    inner = _Flaky()
    rj = engine.ResilientJudge(inner, min_interval_s=0.0, max_retries=2, backoff_s=0.0)
    out = _run(
        rj.classify_multi(
            user_text="x",
            last_character_line="",
            pending_goals=[],
            scenario_description="s",
        )
    )
    assert out == {"g": True}
    assert inner.calls == 3


def test_resilient_judge_returns_none_after_exhausting_retries():
    class _Dead:
        async def classify_multi(self, **kwargs):
            return None

    rj = engine.ResilientJudge(
        _Dead(), min_interval_s=0.0, max_retries=2, backoff_s=0.0
    )
    out = _run(
        rj.classify_multi(
            user_text="x",
            last_character_line="",
            pending_goals=[],
            scenario_description="s",
        )
    )
    assert out is None


def test_resilient_chat_retries_then_succeeds():
    class _FlakyChat:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, *, system, temperature, max_tokens):
            self.calls += 1
            if self.calls < 2:
                raise RuntimeError("429 rate limit")
            return "ok"

    inner = _FlakyChat()
    rc = engine.ResilientChat(inner, min_interval_s=0.0, max_retries=3, backoff_s=0.0)
    out = _run(rc.chat([], system="s", temperature=0.7, max_tokens=10))
    assert out == "ok"
    assert inner.calls == 2


def test_resilient_chat_reraises_after_exhausting_retries():
    class _DeadChat:
        async def chat(self, messages, *, system, temperature, max_tokens):
            raise RuntimeError("429 forever")

    rc = engine.ResilientChat(
        _DeadChat(), min_interval_s=0.0, max_retries=2, backoff_s=0.0
    )
    with pytest.raises(RuntimeError):
        _run(rc.chat([], system="s", temperature=0.7, max_tokens=10))


def test_is_rate_limit_detection():
    from scripts.calibrate_scenario import _is_rate_limit

    assert _is_rate_limit(
        Exception("Rate limit reached ... tokens per day (TPD): Limit 100000")
    )
    assert _is_rate_limit(Exception("rate_limit_exceeded"))
    assert not _is_rate_limit(Exception("connection refused"))


def test_build_live_clients_from_llm_settings():
    settings = engine.LlmSettings(groq_api_key="k", classifier_model="scout-x")
    chat_llm, judge = engine.build_live_clients(settings)
    assert isinstance(chat_llm, engine.OpenAIChatLLM)
    assert judge._model == "scout-x"  # classifier model wired through


def test_waiter_golden_fixture_is_valid():
    fixture = engine.load_golden_fixture("waiter_easy_01")
    assert fixture is not None
    assert fixture["reviewed"] is True
    valid_ids = {
        cp["id"] for cp in engine.scenarios.load_scenario_checkpoints("waiter_easy_01")
    }
    for case in fixture["cases"]:
        assert case["kind"] in ("positive", "negative")
        assert case["user_text"].strip()
        assert case["checkpoint_id"] in valid_ids


# ============================================================
# Review 2026-06-02 — regression nets for the patched findings
# ============================================================


def test_cli_amain_records_verdict_with_correct_arity(monkeypatch, tmp_path):
    """Regression: the CLI must call `engine.record_verdict(ledger, verdict, ...)`,
    NOT `record_verdict(verdict, ...)`. The live calibrate path is gated out of
    pytest (AC6), so this wiring bug crashed the primary `calibrate_scenario <id>`
    command with a TypeError AFTER the (paid) calibration, with zero coverage.
    Drives `_amain` end-to-end with faked engine I/O but keeps `combine_verdict`
    + `record_verdict` REAL, so a wrong call site fails the test.
    """
    import argparse
    import types

    import scripts.calibrate_scenario as cli

    class _FakeClient:
        async def aclose(self):  # chat_llm teardown
            pass

        async def close(self):  # judge teardown
            pass

    golden = types.SimpleNamespace(
        passed=True,
        reviewed_fixture=False,
        negative_total=5,
        negative_failures=[],
        negative_warnings=[],
        positive_total=0,
        positive_met=0,
        requires_gating_failures=[],
        implies_backfill_failures=[],
    )
    calibration = types.SimpleNamespace(
        passed=True,
        difficulty="easy",
        band=(60, 80),
        n=1,
        cooperative_rate=70.0,
        offtopic_rate=0.0,
        band_verdict="in_band",
        guardrail_ok=True,
    )

    async def _fake_run_golden(**kwargs):
        return golden

    async def _fake_run_calibration(**kwargs):
        return calibration

    saved: dict = {}
    monkeypatch.setattr(engine, "load_llm_settings", lambda: object())
    monkeypatch.setattr(engine, "list_scenarios", lambda: ["fake_test_01"])
    monkeypatch.setattr(
        engine, "build_live_clients", lambda settings: (_FakeClient(), _FakeClient())
    )
    monkeypatch.setattr(engine, "ResilientJudge", lambda inner, **kw: inner)
    monkeypatch.setattr(engine, "ResilientChat", lambda inner, **kw: inner)
    monkeypatch.setattr(engine, "load_ledger", lambda: {})
    monkeypatch.setattr(engine, "compute_scenario_hash", lambda sid: "hash123")
    monkeypatch.setattr(
        engine,
        "load_scenario_data",
        lambda sid: _scenario_data(checkpoints=[_cp("greet")]),
    )
    monkeypatch.setattr(engine, "run_golden", _fake_run_golden)
    monkeypatch.setattr(engine, "run_calibration", _fake_run_calibration)
    monkeypatch.setattr(engine, "write_report", lambda verdict: tmp_path / "r.json")
    monkeypatch.setattr(
        engine, "save_ledger", lambda ledger, **kw: saved.update(led=ledger)
    )
    # combine_verdict + record_verdict stay REAL — they are what the bug hit.

    args = argparse.Namespace(
        scenario_id="fake_test_01",
        scenarios="",
        force=False,
        golden_only=False,
        generate_golden=False,
        n=1,
        max_turns=12,
        no_ledger=False,
        throttle_ms=0,
        retries=0,
    )

    rc = _run(cli._amain(args))

    assert rc == 0
    assert "fake_test_01" in saved["led"]
    assert saved["led"]["fake_test_01"]["verdict"] == "PASS"


def test_golden_inconclusive_flags_rate_limited_judge():
    """Regression (review 2026-06-02): an all-unsure golden run (rate-limited judge)
    must read as INCONCLUSIVE, not a PASS — the build_scenario --validate CLI path
    uses this shared guard (the wizard already had its own)."""
    import types

    all_unsure = types.SimpleNamespace(negative_warnings=[1, 2, 3, 4], negative_total=4)
    one_warning = types.SimpleNamespace(negative_warnings=[1], negative_total=4)
    no_warning = types.SimpleNamespace(negative_warnings=[], negative_total=4)
    assert engine.golden_inconclusive(all_unsure) is True
    assert engine.golden_inconclusive(one_warning) is False
    assert engine.golden_inconclusive(no_warning) is False


def test_load_golden_fixture_raises_on_corrupt_json(tmp_path):
    """Regression: a corrupt fixture must fail LOUD, not be silently treated as
    absent (which would drop gating coverage → false PASS)."""
    (tmp_path / "broken_01.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        engine.load_golden_fixture("broken_01", fixture_dir=tmp_path)


def test_fixture_cases_raises_on_missing_required_key():
    """Regression: a partial fixture case must raise a clear error, not a bare
    KeyError mid-run."""
    fixture = {"cases": [{"kind": "positive", "user_text": "hi"}]}  # no checkpoint_id
    with pytest.raises(ValueError, match="missing required field"):
        engine._fixture_cases(fixture)
