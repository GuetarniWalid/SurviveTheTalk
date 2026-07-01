"""Story 6.6 / 6.10 — Tests for CheckpointManager FrameProcessor.

Story 6.10 rewrote the manager from a linear `_index` state machine into
a goal-tracking engine: `self._goals: dict[id, "pending"|"met"]`, judged
by `ExchangeClassifier.classify_multi`. These tests assert goal-state
changes (`goals_state` / `met_count` / `pending_goals`) instead of the
retired `_index`, plus the new behavioral guarantees (out-of-order
flips, partial credit, multi-flip-per-turn, completion-via-any-order).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

import pipeline.checkpoint_manager as cm_mod
from pipeline import scenarios
from pipeline.checkpoint_manager import (
    CheckpointManager,
    advance_goals,
    compose_goal_system_instruction,
    compose_spike_character_led_instruction,
    judgeable_goals,
)
from pipeline.exchange_classifier import ABUSE_KEY, DISRESPECT_KEY, ExchangeClassifier
from pipeline.patience_tracker import PatienceTracker


# ---------- helpers --------------------------------------------------------


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_checkpoints(n: int = 3) -> list[dict]:
    return [
        dict(
            id=f"cp{i}",
            hint_text=f"hint {i}",
            prompt_segment=f"prompt segment {i}",
            success_criteria=f"User says thing {i}.",
        )
        for i in range(n)
    ]


def _capture_pushed(manager: CheckpointManager) -> list[Frame]:
    captured: list[Frame] = []

    async def _recorder(frame: Frame, direction: FrameDirection) -> None:
        captured.append(frame)

    manager.push_frame = _recorder  # type: ignore[assignment]
    return captured


def _advance_envelopes(captured: list[Frame]) -> list[Frame]:
    # The initial-state envelope is a queued OutputTransportMessageFrame;
    # the mid-turn flip envelopes are URGENT (OutputTransportMessageUrgentFrame,
    # a SystemFrame) so they jump the per-processor queue and reach the client
    # without waiting behind the character LLM's in-flight generation. Story
    # 6.20 AC5 ALSO emits a queued OutputTransportMessageFrame duplicate of
    # each flip (lost-tail self-heal). This helper matches ALL of them — used
    # by initial-state tests (one queued frame, no flip) and the AC5 duplicate
    # assertion. Per-flip count/index assertions use `_flip_envelopes` instead
    # so the AC5 duplicate doesn't double the count.
    return [
        f
        for f in captured
        if isinstance(
            f, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)
        )
        and f.message.get("type") == "checkpoint_advanced"
    ]


def _flip_envelopes(captured: list[Frame]) -> list[Frame]:
    # The per-flip ANIMATION stream only: the URGENT frames. Excludes the
    # Story 6.20 AC5 reliable OutputTransportMessageFrame duplicate (and the
    # initial-state queued frame), so a single flip == exactly one entry here.
    return [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageUrgentFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]


class _StubSettings:
    """Stand-in for `OpenRouterLLMService._settings` exposing
    `system_instruction` as a plain mutable attribute."""

    def __init__(self, system_instruction: str = "") -> None:
        self.system_instruction = system_instruction


class _StubLLM:
    """Stand-in LLM service with a `._settings.system_instruction` field
    that the manager mutates on advance."""

    def __init__(self, system_instruction: str = "initial-prompt") -> None:
        self._settings = _StubSettings(system_instruction=system_instruction)


def _make_manager(
    *,
    checkpoints: list[dict] | None = None,
    base_prompt: str = "BASE PROMPT.",
    scenario_description: str = "The Waiter",
    patience_tracker: Any = None,
    classify_response: bool | None = True,
    classify_responses: list[bool | None] | None = None,
    classify_delay: float = 0.0,
    coherence_charter: str = "CHARTER.",
    multi_response_fn: Callable[[list[dict], int], dict[str, bool | None]]
    | None = None,
    abuse_detection_enabled: bool = True,
    verdict_wait_budget_ms: int = 800,
    spike_character_led: bool = False,
    spike_no_fail_drain: bool = False,
    spike_goal: str | None = None,
    disrespect_budget: int = 2,
) -> tuple[CheckpointManager, ExchangeClassifier, MagicMock, _StubLLM, LLMContext]:
    """Build a fully-mocked manager. The classifier's `classify_multi`
    is replaced with an async stub.

    `verdict_wait_budget_ms` (Story 6.29 D1) defaults to the PROD default
    (800 ms bounded wait). Tests that model the STACKED fast-re-speak path
    (a turn arriving while the prior classify is in flight) pass `0`: with
    the wait on, `process_frame` holds each turn for its own verdict, so
    sequential drives can no longer stack — in prod that path now exists
    only AFTER a budget miss, which `0` (the sanctioned wait-disable /
    pre-6.29 parallel mode) reproduces deterministically.

    Verdict control (most specific wins):
      - `multi_response_fn(pending_goals, call_index)` — full control;
        returns the `{goal_id: bool|None}` dict for the turn.
      - `classify_responses[i]` / `classify_response` — convenience: the
        per-turn value is applied to the FIRST pending goal, all other
        pending goals → None. `True` flips the first pending goal (the
        author-order analog of the old linear advance); `False` makes
        the turn an off-topic miss (no flip, at least one real verdict);
        `None` makes `classify_multi` return `None` — the INFRA-FAILURE
        sentinel (timeout / HTTP / parse failure). A parsed all-"unsure"
        turn (a dict of all-None) is a SEPARATE case driven via
        `multi_response_fn` (it must NOT feed the consecutive-None backstop).
    """
    checkpoints = checkpoints or _make_checkpoints(3)
    classifier = ExchangeClassifier(api_key="test-key")

    call_count = {"n": 0}
    classifier_calls: list[dict] = []

    async def _stub_classify_multi(
        *,
        user_text: str,
        last_character_line: str,
        pending_goals: list[dict],
        scenario_description: str,
    ) -> dict[str, bool | None] | None:
        idx = call_count["n"]
        call_count["n"] += 1
        classifier_calls.append(
            dict(
                user_text=user_text,
                last_character_line=last_character_line,
                pending_goals=pending_goals,
                scenario_description=scenario_description,
            )
        )
        if classify_delay:
            await asyncio.sleep(classify_delay)
        ids = [g["id"] for g in pending_goals]
        if multi_response_fn is not None:
            return multi_response_fn(pending_goals, idx)
        if not ids:
            return {}
        verdict = (
            classify_responses[idx]
            if classify_responses is not None
            else classify_response
        )
        if verdict is None:
            # INFRA-FAILURE sentinel — classify_multi returns None
            # (timeout / HTTP / parse failure), distinct from a parsed
            # all-"unsure" dict.
            return None
        result: dict[str, bool | None] = {gid: None for gid in ids}
        result[ids[0]] = verdict
        return result

    classifier.classify_multi = _stub_classify_multi  # type: ignore[assignment]

    if patience_tracker is None:
        patience_tracker = MagicMock()
        # Story 6.22 — model a real NON-hang-up tracker. `is_hanging_up` MUST
        # be a real bool (False), not a truthy auto-Mock: process_frame's new
        # post-hang-up early-suppress reads it directly, so a truthy Mock would
        # drop every normal turn before the classifier runs. Real int
        # patience/fail_penalty too — with is_hanging_up False the
        # `is_terminal_turn` short-circuit no longer hides the `pt.patience > 0`
        # comparison (a bare Mock there raises TypeError). High patience keeps
        # the default on the normal path; the completion clause still trips on
        # the LAST pending goal, faithful to prod (a 1-goal-left turn IS
        # terminal). Tests needing a hang-up/terminal tracker pass their own.
        patience_tracker.is_hanging_up = False
        patience_tracker.patience = 100
        patience_tracker.fail_penalty = -15

    stub_llm = _StubLLM()
    llm_context = LLMContext()

    manager = CheckpointManager(
        base_prompt=base_prompt,
        checkpoints=checkpoints,
        llm=stub_llm,
        llm_context=llm_context,
        classifier=classifier,
        patience_tracker=patience_tracker,
        scenario_description=scenario_description,
        coherence_charter=coherence_charter,
        abuse_detection_enabled=abuse_detection_enabled,
        verdict_wait_budget_ms=verdict_wait_budget_ms,
        spike_character_led=spike_character_led,
        spike_no_fail_drain=spike_no_fail_drain,
        spike_goal=spike_goal,
        disrespect_budget=disrespect_budget,
    )

    classifier._test_calls = classifier_calls  # type: ignore[attr-defined]
    return manager, classifier, patience_tracker, stub_llm, llm_context


def _make_user_frame(text: str, *, finalized: bool = True) -> TranscriptionFrame:
    return TranscriptionFrame(
        text=text,
        user_id="user",
        timestamp="2026-05-15T12:00:00Z",
        finalized=finalized,
    )


async def _drain(manager: CheckpointManager) -> None:
    task = manager._in_flight
    if task is not None:
        await asyncio.gather(task, return_exceptions=True)


# ---------- Test 1: finalized TranscriptionFrame schedules classifier -----


def test_finalized_transcription_schedules_classify_multi() -> None:
    manager, classifier, _tracker, _llm, _ctx = _make_manager()
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("I want chicken."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    calls = classifier._test_calls  # type: ignore[attr-defined]
    assert len(calls) == 1
    assert calls[0]["user_text"] == "I want chicken."
    assert calls[0]["scenario_description"] == "The Waiter"
    # All 3 goals pending on the first turn → classify_multi receives all 3.
    pending = calls[0]["pending_goals"]
    assert [g["id"] for g in pending] == ["cp0", "cp1", "cp2"]
    assert pending[0]["success_criteria"] == "User says thing 0."


# ---------- Test 2: interim TranscriptionFrame does NOT schedule ---------


def test_interim_transcription_does_not_schedule() -> None:
    manager, classifier, _tracker, _llm, _ctx = _make_manager()
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("I want", finalized=False),
            FrameDirection.DOWNSTREAM,
        )
        await _drain(manager)

    _run(_drive())

    assert classifier._test_calls == []  # type: ignore[attr-defined]


# ---------- Test 3: empty text does NOT schedule -------------------------


def test_empty_text_does_not_schedule() -> None:
    manager, classifier, _tracker, _llm, _ctx = _make_manager()
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(_make_user_frame("   "), FrameDirection.DOWNSTREAM)
        await _drain(manager)

    _run(_drive())

    assert classifier._test_calls == []  # type: ignore[attr-defined]


# ---------- SPIKE (spike/character-led, 2026-06-30) — throwaway behavior -----


def test_spike_compose_drops_steering_and_length_cap_keeps_charter_and_goal() -> None:
    """SPIKE — the holistic composer strips the persona's reply-length cap and
    omits BOTH per-beat steering blocks, while keeping the persona body, the
    goal, the charter, and the trailing mood tag (positional invariants)."""
    base = (
        "You are Tina, a tired waitress.\n"
        "Rules you MUST follow:\n"
        "- Keep every response to 1-3 short sentences, as if talking to a real customer\n"
        "- Speak English only.\n"
        "Menu: grilled chicken, pasta."
    )
    composed = compose_spike_character_led_instruction(
        base_prompt=base,
        coherence_charter="CHARTER-TOKEN.",
        spike_goal="take the whole order and close out the table",
        mood_tag_directive="MOOD-TOKEN.",
    )
    assert "1-3 short sentences" not in composed
    assert "You are Tina, a tired waitress." in composed
    assert "Speak English only." in composed
    assert "Menu: grilled chicken, pasta." in composed
    assert "take the whole order and close out the table" in composed
    assert "as much or as little as a real person would" in composed
    assert "Right now the only objective you may pursue is" not in composed
    assert "Your remaining objectives are listed" not in composed
    # SPIKE Phase 2 (Walid 2026-06-30/07-01) — the GENERAL end-call rule: every
    # character can hang up; it OVERRIDES a "relentless / professional / never give
    # up" persona (the cop never-ends bug), and it is THIN-SKINNED about disrespect
    # — one warning max, then end (the "too lax on insults" tune). Locked so a
    # future edit can't soften either half.
    assert "<end_call>" in composed
    assert "OVERRIDES" in composed and "relentless" in composed
    assert "THIN-SKINNED" in composed and "insulting you" in composed
    assert "CHARTER-TOKEN." in composed
    assert composed.rstrip().endswith("MOOD-TOKEN.")


def test_spike_compose_leaves_difficulty_short_sentence_aid_untouched() -> None:
    """SPIKE — only the reply-COUNT cap ("Keep … sentences") is stripped; the
    difficulty block's per-sentence simplicity aid ("Speak in simple … short
    sentences (about 5-8 words)") starts with "Speak" and must survive."""
    base = (
        "You are a cop.\n"
        "- Keep every response to 1-3 short sentences.\n"
        "Difficulty behavior (easy):\n"
        "- Speak in simple, common words and short sentences (about 5-8 words)."
    )
    composed = compose_spike_character_led_instruction(
        base_prompt=base,
        coherence_charter="C.",
        spike_goal="get a statement",
    )
    assert "1-3 short sentences" not in composed
    assert "short sentences (about 5-8 words)" in composed


def test_spike_character_led_recompose_uses_holistic_instruction() -> None:
    """SPIKE (change 1) — with the flag ON, a successful flip recomposes the LLM
    system instruction via the holistic composer (goal present, per-beat steering
    absent), instead of the prod per-beat steering composition."""
    manager, _classifier, _tracker, stub_llm, _ctx = _make_manager(
        spike_character_led=True,
        spike_goal="GOAL-MARKER take the order",
        classify_response=True,  # first turn flips cp0 → triggers recompose
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("I want chicken."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    composed = stub_llm._settings.system_instruction
    assert "GOAL-MARKER take the order" in composed
    assert "as much or as little as a real person would" in composed
    assert "Right now the only objective you may pursue is" not in composed


def test_spike_no_fail_drain_skips_patience_drain_on_checkpoint_fail() -> None:
    """SPIKE (change 2) — with SPIKE_NO_FAIL_DRAIN on, an off-topic miss does NOT
    call apply_exchange_outcome (an engaged learner is never hung up on a miss)."""
    manager, _classifier, tracker, _llm, _ctx = _make_manager(
        spike_no_fail_drain=True,
        classify_response=False,  # off-topic miss → fail branch
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("nice weather today."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    tracker.apply_exchange_outcome.assert_not_called()


def test_fail_drain_still_fires_when_spike_flag_off() -> None:
    """SPIKE control — flag OFF (default): the SAME off-topic miss drains patience
    exactly as today. Flag-OFF parity regression guard."""
    manager, _classifier, tracker, _llm, _ctx = _make_manager(
        spike_no_fail_drain=False,
        classify_response=False,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("nice weather today."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    tracker.apply_exchange_outcome.assert_called_once_with(success=False)


# ---------- Test 4: pass-through for every frame type --------------------


@pytest.mark.parametrize(
    "frame_factory",
    [
        lambda: _make_user_frame("hello"),
        lambda: TextFrame(text="character speaking"),
        lambda: BotStoppedSpeakingFrame(),
        lambda: OutputTransportMessageFrame(message={"type": "unrelated"}),
    ],
)
def test_pass_through_for_all_frame_types(frame_factory) -> None:
    # NON-terminal turns only — the default `_make_manager` tracker now pins
    # `is_hanging_up=False`, `patience=100`, `fail_penalty=-15` (Story 6.22), so
    # `is_terminal_turn` is False via its INNER clause: one more fail can't zero
    # the meter (`patience + fail_penalty = 85 > 0`) AND this isn't the last
    # pending goal (`met_count + 1 = 1 < len(checkpoints) = 3`). The new
    # post-hang-up early-return is also skipped (is_hanging_up is False). (Before
    # Story 6.22 the default's `is_hanging_up` was a truthy auto-Mock that
    # short-circuited `is_terminal_turn` to False — that rationale is now stale.)
    # Terminal-turn + hang-up suppression are covered by the Deviation #7 +
    # Story 6.22 tests below.
    manager, _classifier, _tracker, _llm, _ctx = _make_manager()
    captured = _capture_pushed(manager)

    frame = frame_factory()

    async def _drive() -> None:
        await manager.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(manager)

    _run(_drive())

    assert frame in captured, f"{type(frame).__name__} must be forwarded downstream"


# ---------- Test 5: a met goal flips, swaps prompt, emits envelope -------


def test_met_goal_flips_recomposes_prompt_emits_envelope() -> None:
    manager, _classifier, tracker, stub_llm, _ctx = _make_manager(
        classify_response=True
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("I want chicken."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    # cp0 flipped pending → met; one goal met now.
    assert manager.goals_state == {"cp0": "met", "cp1": "pending", "cp2": "pending"}
    assert manager.met_count == 1

    # System instruction recomposed: charter once, pending segments 1+2
    # present, the met segment 0 gone.
    si = stub_llm._settings.system_instruction
    assert si.count("CHARTER.") == 1
    assert "prompt segment 1" in si
    assert "prompt segment 2" in si
    assert "prompt segment 0" not in si

    # Envelope reports the goal that JUST flipped (cp0 / index 0) + the
    # full met set (Story 6.20 AC2 dropped the dead `next_hint`).
    envelopes = _flip_envelopes(captured)
    assert len(envelopes) == 1
    data = envelopes[0].message["data"]
    assert data["checkpoint_id"] == "cp0"
    assert data["index"] == 0
    assert data["total"] == 3
    assert "next_hint" not in data
    assert data["goals_met_indices"] == [0]

    tracker.apply_exchange_outcome.assert_called_with(success=True)
    tracker.set_checkpoints_passed.assert_called_with(1)


# ---------- Test 6: no goal matched → fail_penalty, no flip --------------


def test_no_goal_matched_applies_fail_penalty() -> None:
    manager, _classifier, tracker, stub_llm, _ctx = _make_manager(
        classify_response=False
    )
    captured = _capture_pushed(manager)
    initial_prompt = stub_llm._settings.system_instruction

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("nope."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    assert manager.met_count == 0
    assert stub_llm._settings.system_instruction == initial_prompt
    assert _advance_envelopes(captured) == []
    tracker.apply_exchange_outcome.assert_called_with(success=False)


# ---------- Test 7: classifier=all-None is INFRA failure — neutral -------


def test_all_none_does_not_advance_and_does_not_drain_patience() -> None:
    """An all-None turn (HTTP error / timeout / parse failure across every
    pending goal) is OUR infra failing — no flip AND no patience drain
    (Story 6.9 Deviation #5, carried into the goal model)."""
    manager, _classifier, tracker, stub_llm, _ctx = _make_manager(
        classify_response=None
    )
    captured = _capture_pushed(manager)
    initial_prompt = stub_llm._settings.system_instruction
    tracker.apply_exchange_outcome.reset_mock()

    async def _drive() -> None:
        await manager.process_frame(_make_user_frame("..."), FrameDirection.DOWNSTREAM)
        await _drain(manager)

    _run(_drive())

    assert manager.met_count == 0
    assert stub_llm._settings.system_instruction == initial_prompt
    assert _advance_envelopes(captured) == []
    tracker.apply_exchange_outcome.assert_not_called()


def test_consecutive_all_none_turns_force_fail_penalty_after_threshold() -> None:
    """Story 6.9 D1 backstop, goal model — after
    `_MAX_CONSECUTIVE_NONE_VERDICTS` consecutive all-None turns the
    manager forces `apply_exchange_outcome(success=False)` exactly once."""
    from pipeline.checkpoint_manager import _MAX_CONSECUTIVE_NONE_VERDICTS

    manager, _classifier, tracker, _llm, _ctx = _make_manager(classify_response=None)
    tracker.apply_exchange_outcome.reset_mock()

    async def _drive() -> None:
        for i in range(_MAX_CONSECUTIVE_NONE_VERDICTS):
            await manager.process_frame(
                _make_user_frame(f"attempt {i}"), FrameDirection.DOWNSTREAM
            )
            await _drain(manager)

    _run(_drive())

    assert tracker.apply_exchange_outcome.call_count == 1
    tracker.apply_exchange_outcome.assert_called_with(success=False)
    assert manager._consecutive_none_count == 0


def test_consecutive_none_counter_resets_on_real_verdict() -> None:
    """A real verdict (True or False) between bursts of all-None turns
    resets the counter so a transient hiccup doesn't compound."""
    from pipeline.checkpoint_manager import _MAX_CONSECUTIVE_NONE_VERDICTS

    # 4 None, then 1 True (flips a goal), then 4 None.
    classify_responses = (
        [None] * (_MAX_CONSECUTIVE_NONE_VERDICTS - 1)
        + [True]
        + [None] * (_MAX_CONSECUTIVE_NONE_VERDICTS - 1)
    )
    manager, _classifier, tracker, _llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(5),
        classify_responses=classify_responses,
    )
    tracker.apply_exchange_outcome.reset_mock()

    async def _drive() -> None:
        for i in range(len(classify_responses)):
            await manager.process_frame(
                _make_user_frame(f"attempt {i}"), FrameDirection.DOWNSTREAM
            )
            await _drain(manager)

    _run(_drive())

    success_false_calls = [
        c
        for c in tracker.apply_exchange_outcome.call_args_list
        if c.kwargs.get("success") is False
    ]
    assert len(success_false_calls) == 0


def test_parsed_all_unsure_does_not_drain_or_feed_backstop() -> None:
    """Review D3 (2026-05-29) — a PARSED all-"unsure" turn (the classifier
    answered but couldn't decide on every goal: a dict of all-None) is
    genuine model ambiguity, NOT infra failure. It must be patience-neutral
    AND must NOT increment the consecutive-None backstop — so even after
    more than `_MAX_CONSECUTIVE_NONE_VERDICTS` such turns the manager never
    fabricates `apply_exchange_outcome(success=False)` (the false "sustained
    classifier failure" the old all-None-dict conflation used to fire)."""
    from pipeline.checkpoint_manager import _MAX_CONSECUTIVE_NONE_VERDICTS

    def _fn(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        # Parsed response; every goal came back "unsure".
        return {g["id"]: None for g in pending}

    manager, _classifier, tracker, _llm, _ctx = _make_manager(multi_response_fn=_fn)
    tracker.apply_exchange_outcome.reset_mock()

    async def _drive() -> None:
        for i in range(_MAX_CONSECUTIVE_NONE_VERDICTS + 2):
            await manager.process_frame(
                _make_user_frame(f"hmm {i}"), FrameDirection.DOWNSTREAM
            )
            await _drain(manager)

    _run(_drive())

    tracker.apply_exchange_outcome.assert_not_called()
    assert manager._consecutive_none_count == 0
    assert manager.met_count == 0


def test_terminal_turn_classify_blocking_bounded_under_3s() -> None:
    """Story 6.9 review P18 — the terminal-turn preemptive sync path must
    stay bounded ≤3000ms even on a slow classify_multi (Deviation #6
    2.0s budget). Mocks a 1.8s classify_multi on a 1-goal scenario."""
    import time

    checkpoints = _make_checkpoints(1)
    manager, classifier, tracker, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        classify_responses=[True],
    )

    async def _slow_classify_multi(**kwargs: Any) -> dict[str, bool | None]:
        await asyncio.sleep(1.8)
        return {"cp0": True}

    classifier.classify_multi = _slow_classify_multi  # type: ignore[assignment]
    tracker.is_hanging_up = False
    tracker.patience = 100
    tracker.fail_penalty = -15

    async def _drive() -> float:
        start = time.monotonic()
        await manager._run_classifier_blocking("final attempt")
        return time.monotonic() - start

    elapsed = _run(_drive())
    assert elapsed <= 3.0


# ---------- Test 8: all goals met routes to schedule_completion ----------


def test_all_goals_met_routes_to_schedule_completion() -> None:
    """When the LAST pending goal flips, the manager emits the final
    `checkpoint_advanced` envelope (so the stepper fills the last circle)
    AND calls `schedule_completion(survival_pct=100)`."""
    checkpoints = _make_checkpoints(2)
    manager, _classifier, tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        classify_responses=[True, True],
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("first."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        assert manager.met_count == 1
        await manager.process_frame(
            _make_user_frame("second."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    assert manager.met_count == 2
    # Story 6.10 behavior change vs 6.6: the final goal flip DOES emit a
    # checkpoint_advanced envelope (so the client fills the last circle).
    envelopes = _flip_envelopes(captured)
    assert len(envelopes) == 2
    last = envelopes[-1].message["data"]
    assert last["index"] == 1
    assert last["goals_met_indices"] == [0, 1]

    assert tracker.schedule_completion.call_args.kwargs.get("survival_pct") == 100
    tracker.set_checkpoints_passed.assert_any_call(2)


# ---------- Test 9: fast re-speak serialization + generation guard -------


def test_fast_respeak_serializes_prior_classify_no_dropped_goal() -> None:
    """Story 6.20 AC1 — a new finalized turn arriving WHILE the prior turn's
    classify is still in flight must AWAIT the prior classify to completion
    (its flip lands) before judging the new turn. Both turns' goals flip —
    the just-completed one is NOT silently dropped on fast re-speak.

    Before the fix, the non-terminal path `prior.cancel()`-ed the in-flight
    classify, discarding the first turn's genuinely-met goal (breaks_progress).
    """
    manager, _classifier, tracker, _stub_llm, _ctx = _make_manager(
        classify_response=True,
        classify_delay=0.05,
        # Story 6.29 — wait disabled: this test models the STACKED window,
        # which now only exists after a budget miss (see _make_manager doc).
        verdict_wait_budget_ms=0,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("first."), FrameDirection.DOWNSTREAM
        )
        # Re-speak before the first classify resolves (its task is still
        # in flight): the non-terminal path must await it, not cancel it.
        await manager.process_frame(
            _make_user_frame("second."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    # BOTH the first and second turns' goals flipped — nothing dropped.
    assert manager.met_count == 2
    success_calls = [
        c
        for c in tracker.apply_exchange_outcome.call_args_list
        if c.kwargs.get("success") is True
    ]
    assert len(success_calls) == 2


def test_generation_guard_drops_stale_verdict() -> None:
    """The generation guard still suppresses a classify task whose generation
    is stale (a newer turn bumped the counter). Exercised directly so it stays
    covered now that the non-terminal path serializes rather than cancels."""
    manager, _classifier, tracker, _stub_llm, _ctx = _make_manager(
        classify_response=True,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        # Simulate a newer turn having advanced the generation counter, then
        # run a classify task born with an OLD generation number.
        manager._generation = 5
        await manager._classify_and_flip_goals("late verdict.", 3)

    _run(_drive())

    # Stale task's side effects suppressed: no flip, no outcome applied.
    assert manager.met_count == 0
    tracker.apply_exchange_outcome.assert_not_called()


def test_fast_respeak_into_completion_suppresses_second_user_frame() -> None:
    """Story 6.20 review (async-correctness) — regression for the terminal-
    suppression race the AC1 await-not-cancel change could open.

    Turn 1 flips the FINAL pending goals in ONE verdict (→ schedule_completion).
    Turn 2 arrives as a fast re-speak while turn 1's classify is still in flight,
    so its terminal precheck read a STALE (pre-flip) met_count and committed to
    the non-terminal path. After serialization awaits turn 1 (call now
    completing), turn 2's user frame MUST be suppressed — never forwarded to the
    LLM — so the survived exit line stays the sole final utterance (Deviation #7).
    The old cancel-based path avoided this only because the cancelled prior never
    reached schedule_completion.
    """
    checkpoints = _make_checkpoints(2)

    def _fn(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        # Turn 1 ("first.") flips BOTH remaining goals at once → completion.
        if call_index == 0:
            return {g["id"]: True for g in pending}
        return {g["id"]: None for g in pending}

    manager, _classifier, tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        multi_response_fn=_fn,
        classify_delay=0.02,
        # Story 6.29 — wait disabled: stacked-window scenario (post-budget-miss).
        verdict_wait_budget_ms=0,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("first."), FrameDirection.DOWNSTREAM
        )
        # Fast re-speak before turn 1's classify resolves.
        await manager.process_frame(
            _make_user_frame("second."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    assert manager.met_count == 2  # turn 1 completed every goal
    tracker.schedule_completion.assert_called_once()
    # The SECOND user turn must NOT have been forwarded to the LLM (suppressed
    # because the awaited prior turn completed the call); only "first." flows.
    forwarded = [f.text for f in captured if isinstance(f, TranscriptionFrame)]
    assert "second." not in forwarded
    assert "first." in forwarded


def test_fast_respeak_double_fail_drains_once_no_premature_hangup() -> None:
    """Story 6.25 (AC1 + AC2 / D1) — regression for the await-not-cancel
    double-drain + Deviation #7 frame-forward race.

    Setup: a REAL `PatienceTracker` in the DANGER BAND (initial 50, fail
    penalty -25, 6 checkpoints so completion never fires) — one fail is
    survivable (50→25), two are fatal (→0). Two genuine FAIL turns arrive
    back-to-back: turn 1's classify is still in flight (`classify_delay>0`) when
    turn 2 arrives, so turn 2 serializes BEHIND it on the non-terminal path
    (`_serialize_then_classify`), exactly the production fast-re-speak shape.

    Before the fix (await-not-cancel, Story 6.20 AC1): turn 1's awaited fail
    drained 50→25, then turn 2 scheduled its OWN fail → 25→0 → `character_hung_up`
    fired a full turn early, and turn 2's frame was forwarded into the hang-up
    (the LLM reply racing the silence exit line — Deviation #7).

    After D1 (Task 2 coalescing): the rapid pair counts as ONE impatience event
    — the meter drains EXACTLY ONCE (50→25, byte-identical to the old cancel-path
    result), is NEVER zeroed, so NO hang-up fires (AC2) and turn 2 stays
    non-terminal — there is no exit line for its forwarded frame to race (AC1).
    """
    tracker = PatienceTracker(
        initial_patience=50,
        fail_penalty=-25,
        recovery_bonus=0,
        silence_penalty=-10,
        silence_prompt_seconds=6.0,
        ladder_impatience_seconds=4.5,
        silence_hangup_seconds=10.0,
        escalation_thresholds=[25, 0],
        total_checkpoints=6,
    )
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(6),
        patience_tracker=tracker,
        classify_responses=[False, False],
        classify_delay=0.02,
        # Story 6.29 — wait disabled: stacked-window scenario (post-budget-miss).
        verdict_wait_budget_ms=0,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        # Turn 1 returns immediately on the non-terminal path (its classify is
        # NOT awaited there — wait disabled), so turn 2 finds turn 1's task
        # still in flight and serializes behind it — the fast-re-speak window.
        await manager.process_frame(
            _make_user_frame("first."), FrameDirection.DOWNSTREAM
        )
        await manager.process_frame(
            _make_user_frame("second."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        # Hygiene: drain the fire-and-forget warning/hang-up tasks the real
        # tracker may have spawned so the loop closes without pending-task noise.
        for task in (tracker._warning_task, tracker._hang_up_task):
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    _run(_drive())

    # AC2 — the meter drained EXACTLY ONCE (50 → 25), the same value the old
    # cancel-path produced on identical FAIL/FAIL input. NOT 0 (a double drain).
    assert tracker.patience == 25
    # AC2 — the call did NOT hang up: turn 2's coalesced fail never zeroed it.
    assert tracker.is_hanging_up is False
    # AC1 — with no hang-up, turn 2 stays non-terminal and is forwarded normally
    # (there is no exit line for it to race). Both turns reach the LLM.
    forwarded = [f.text for f in captured if isinstance(f, TranscriptionFrame)]
    assert forwarded == ["first.", "second."]


def test_fast_respeak_hangup_during_await_suppresses_second_frame() -> None:
    """Story 6.25 (AC1 / Task 1) — POSITIVE coverage for the post-serialize
    `is_hanging_up` backstop (`checkpoint_suppress_post_serialize_hangup`).

    The primary fix (Task 2 coalescing) makes the hang-up case unreachable on
    the non-terminal path BY CONSTRUCTION, so the sibling
    `test_fast_respeak_double_fail_drains_once_no_premature_hangup` can only
    assert the precondition *vanished* (no hang-up, both frames forwarded) — it
    never exercises the suppression branch itself. This test drives the residual
    path the backstop exists for: the AWAITED PRIOR schedules a hang-up DURING
    turn 2's `_serialize_then_classify` await, so `is_hanging_up` flips True
    AFTER the top-of-frame Story 6.22 guard already let turn 2 through. The
    backstop must then DROP turn 2's frame so the exit line stays the sole final
    utterance (Deviation #7 / AC1).

    A MagicMock tracker is used deliberately: the point is to force
    `is_hanging_up=True` mid-await regardless of the meter arithmetic (the real
    danger-band arithmetic is the sibling test's job). `apply_exchange_outcome(
    success=False)` flips the hang-up, mirroring prod's step_patience → meter 0
    → _schedule_hang_up chain (is_hanging_up set synchronously).
    """
    tracker = MagicMock()
    tracker.is_hanging_up = False
    tracker.patience = 100
    tracker.fail_penalty = -15

    def _schedule_hangup_on_fail(*, success: bool) -> None:
        if not success:
            tracker.is_hanging_up = True

    tracker.apply_exchange_outcome.side_effect = _schedule_hangup_on_fail

    # 6 checkpoints so completion (`met_count >= total`) can NEVER be the reason
    # for suppression — isolating the hang-up backstop from the completion one.
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(6),
        patience_tracker=tracker,
        classify_responses=[False, False],
        classify_delay=0.02,
        # Story 6.29 — wait disabled: stacked-window scenario (post-budget-miss).
        verdict_wait_budget_ms=0,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        # Turn 1: non-terminal (is_hanging_up False, 100-15=85 > 0, not the last
        # goal) → schedules its classify in the background and is forwarded.
        await manager.process_frame(
            _make_user_frame("first."), FrameDirection.DOWNSTREAM
        )
        # Turn 2: a fast re-speak. is_hanging_up is still False at its top (turn
        # 1's classify is in flight), so the Story 6.22 top guard lets it through
        # to the non-terminal serialize path. Awaiting turn 1's classify then
        # flips is_hanging_up True → the post-serialize backstop must drop it.
        await manager.process_frame(
            _make_user_frame("second."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    forwarded = [f.text for f in captured if isinstance(f, TranscriptionFrame)]
    # Turn 1 was forwarded (hang-up not yet scheduled when it was processed)...
    assert "first." in forwarded
    # ...but turn 2 is SUPPRESSED by the post-serialize is_hanging_up backstop
    # (Deviation #7 / AC1) — no parallel LLM reply races the exit line.
    assert "second." not in forwarded
    # The suppression is the HANG-UP backstop, NOT completion: no goal was met
    # and schedule_completion was never called, so the `met_count >= total`
    # suppression cannot have fired — this pins line 817 specifically.
    assert manager.met_count == 0
    tracker.schedule_completion.assert_not_called()
    assert tracker.is_hanging_up is True
    # Coalescing still held: only turn 1 drained the meter; turn 2's stacked fail
    # coalesced (it never called apply_exchange_outcome a second time).
    assert tracker.apply_exchange_outcome.call_count == 1


# ---------- Test 10: last character line read from LLMContext ------------


def test_last_character_line_read_from_llm_context() -> None:
    manager, classifier, _tracker, _stub_llm, ctx = _make_manager()
    _capture_pushed(manager)

    ctx.add_message({"role": "user", "content": "Hello."})
    ctx.add_message({"role": "assistant", "content": "Welcome to The Golden Fork."})

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("Yes, ordering."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    calls = classifier._test_calls  # type: ignore[attr-defined]
    assert calls[0]["last_character_line"] == "Welcome to The Golden Fork."


def test_last_character_line_empty_when_no_assistant_turn_yet() -> None:
    manager, classifier, _tracker, _stub_llm, _ctx = _make_manager()
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("first turn."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    calls = classifier._test_calls  # type: ignore[attr-defined]
    assert calls[0]["last_character_line"] == ""


# ---------- Test 11: cleanup cancels in-flight task ----------------------


def test_cleanup_cancels_inflight_task() -> None:
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        classify_response=True,
        classify_delay=1.0,
        # Story 6.29 — wait disabled so process_frame returns with the slow
        # classify still in flight (the cleanup-cancel scenario under test).
        verdict_wait_budget_ms=0,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("slow."), FrameDirection.DOWNSTREAM
        )
        assert manager._in_flight is not None
        await manager.cleanup()
        assert manager._in_flight is None

    _run(_drive())


# ---------- Test 12: empty checkpoint list rejected at construction ------


def test_constructor_rejects_empty_checkpoints() -> None:
    classifier = ExchangeClassifier(api_key="test-key")
    with pytest.raises(ValueError, match="checkpoints"):
        CheckpointManager(
            base_prompt="BASE.",
            checkpoints=[],
            llm=_StubLLM(),
            llm_context=LLMContext(),
            classifier=classifier,
            patience_tracker=MagicMock(),
            scenario_description="x",
            coherence_charter="CHARTER.",
        )


# ---------- Test 13: init log line emitted ------------------------------


def test_init_logs_smoke_observability_line() -> None:
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(captured.append, level="INFO")
    try:
        _make_manager(checkpoints=_make_checkpoints(4))
    finally:
        loguru_logger.remove(sink_id)

    init_lines = [entry for entry in captured if "CheckpointManager init" in entry]
    assert init_lines, "smoke-gate init log line MUST be emitted on construction"
    line = init_lines[0]
    assert "scenario_description='The Waiter'" in line
    assert "checkpoint_count=4" in line
    assert "first_checkpoint_id=cp0" in line


# ============================================================
# Deviation #7 — preemptive synchronous classify on terminal turns
# ============================================================


def _terminal_mock_tracker(
    *, patience: int, fail_penalty: int = -15, hang_up_after: bool = False
) -> MagicMock:
    tracker = MagicMock()
    tracker.patience = patience
    tracker.fail_penalty = fail_penalty
    tracker.is_hanging_up = False

    if hang_up_after:

        def _flip_on_fail(success: bool) -> None:
            if not success:
                tracker.is_hanging_up = True
                tracker.patience = 0

        tracker.apply_exchange_outcome.side_effect = _flip_on_fail
    return tracker


def _completion_mock_tracker() -> MagicMock:
    tracker = MagicMock()
    tracker.patience = 100
    tracker.fail_penalty = -15
    tracker.is_hanging_up = False

    def _flip_on_completion(**kwargs: Any) -> None:
        tracker.is_hanging_up = True

    tracker.schedule_completion.side_effect = _flip_on_completion
    return tracker


def test_preemptive_hangup_suppresses_user_frame_when_meter_will_zero() -> None:
    """Terminal turn (meter=10, fail_penalty=-15): verdict awaited
    synchronously; an off-topic turn zeroes the meter (mock flips
    is_hanging_up) → the user frame is SUPPRESSED."""
    tracker = _terminal_mock_tracker(patience=10, hang_up_after=True)
    manager, _classifier, _t, _llm, _ctx = _make_manager(
        patience_tracker=tracker,
        classify_response=False,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("Cats are funny."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    tracker.apply_exchange_outcome.assert_called_with(success=False)
    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert forwarded == []


def test_preemptive_path_forwards_frame_on_success_recovery() -> None:
    """Terminal turn (danger zone), but a goal flips: the user recovers,
    the goal advances, AND the frame is forwarded so the LLM responds."""
    tracker = _terminal_mock_tracker(patience=10, hang_up_after=True)
    manager, _classifier, _t, stub_llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(3),
        patience_tracker=tracker,
        classify_response=True,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("I would like the chicken, please."),
            FrameDirection.DOWNSTREAM,
        )
        await _drain(manager)

    _run(_drive())

    assert manager.met_count == 1
    si = stub_llm._settings.system_instruction
    assert si.count("CHARTER.") == 1
    assert "prompt segment 1" in si
    tracker.apply_exchange_outcome.assert_called_with(success=True)
    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert len(forwarded) == 1


def test_preemptive_completion_suppresses_user_frame_on_last_goal() -> None:
    """One goal pending (the rest already met), verdict flips it → all
    met → schedule_completion fires (mock flips is_hanging_up) → user
    frame SUPPRESSED. The final flip still emits its envelope (so the
    stepper fills the last circle)."""
    tracker = _completion_mock_tracker()
    checkpoints = _make_checkpoints(2)
    manager, _classifier, _t, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        patience_tracker=tracker,
        classify_response=True,
    )
    # Pre-meet cp0 so only cp1 remains pending (the terminal "last goal").
    manager._goals["cp0"] = "met"
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("Thank you."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    assert tracker.schedule_completion.call_args.kwargs.get("survival_pct") == 100
    # Story 6.18 review (Decision #2 / Option A) — the winning user turn (the
    # one being suppressed from the LLM context) is threaded to the completion
    # path so the survived exit line can be generated from it.
    assert (
        tracker.schedule_completion.call_args.kwargs.get("winning_user_text")
        == "Thank you."
    )
    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert forwarded == []
    # The last goal's flip emits one envelope with the full met set.
    envelopes = _flip_envelopes(captured)
    assert len(envelopes) == 1
    assert envelopes[0].message["data"]["goals_met_indices"] == [0, 1]


def test_preemptive_path_forwards_frame_on_last_goal_unmet() -> None:
    """One goal pending, verdict is off-topic → completion does NOT fire
    → frame IS forwarded (user gets another try) and patience drains."""
    tracker = _completion_mock_tracker()
    checkpoints = _make_checkpoints(2)
    manager, _classifier, _t, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        patience_tracker=tracker,
        classify_response=False,
    )
    manager._goals["cp0"] = "met"
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("Uh, weather?"), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    tracker.schedule_completion.assert_not_called()
    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert len(forwarded) == 1
    tracker.apply_exchange_outcome.assert_called_with(success=False)


def test_normal_async_path_unchanged_for_high_meter_many_pending() -> None:
    """Meter far from zero AND >1 objective still pending → original
    parallel-async path: frame forwarded immediately, classifier in the
    background."""
    tracker = _terminal_mock_tracker(patience=80, hang_up_after=False)
    manager, _classifier, _t, _llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(5),
        patience_tracker=tracker,
        classify_response=True,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("I would like the chicken."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert len(forwarded) == 1
    assert manager.met_count == 1


def test_preemptive_path_falls_through_on_classifier_exception() -> None:
    """If the preemptive classify_multi raises, the manager logs and
    falls through to push_frame (graceful degradation)."""
    tracker = _terminal_mock_tracker(patience=10, hang_up_after=False)
    failing_classifier = ExchangeClassifier(api_key="test-key")

    async def _explode(**_kwargs: Any) -> dict[str, bool | None]:
        raise RuntimeError("simulated classifier outage")

    failing_classifier.classify_multi = _explode  # type: ignore[assignment]

    manager = CheckpointManager(
        base_prompt="BASE.",
        checkpoints=_make_checkpoints(3),
        llm=_StubLLM(),
        llm_context=LLMContext(),
        classifier=failing_classifier,
        patience_tracker=tracker,
        scenario_description="exception-test",
        coherence_charter="CHARTER.",
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("dangerous turn."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert len(forwarded) == 1


# ============================================================
# Story 6.22 — post-hang-up user-turn suppression (no reply over exit line)
# ============================================================


def _hanging_up_mock_tracker() -> MagicMock:
    """A tracker that is ALREADY hanging up — models the state AFTER the
    triggering terminal turn scheduled the exit line. `patience`/`fail_penalty`
    are real ints for completeness, but the post-hang-up early return fires on
    `is_hanging_up` alone and never reads them."""
    tracker = MagicMock()
    tracker.is_hanging_up = True
    tracker.patience = 0
    tracker.fail_penalty = -15
    return tracker


def test_post_hangup_user_turn_is_suppressed() -> None:
    """Story 6.22 AC1/AC2 — once a hang-up is scheduled (is_hanging_up True), a
    subsequent finalized user turn is DROPPED: not forwarded downstream AND the
    classifier is never scheduled, so no normal reply is generated to play over
    the exit line. Exactly one `checkpoint_post_hangup_suppress` line records
    the drop (AC1's 'single log line')."""
    from loguru import logger as loguru_logger

    tracker = _hanging_up_mock_tracker()
    manager, classifier, _t, _llm, _ctx = _make_manager(patience_tracker=tracker)
    captured = _capture_pushed(manager)

    logs: list[str] = []
    sink_id = loguru_logger.add(logs.append, level="INFO")
    try:

        async def _drive() -> None:
            await manager.process_frame(
                _make_user_frame("Maybe you are someone else."),
                FrameDirection.DOWNSTREAM,
            )
            await _drain(manager)

        _run(_drive())
    finally:
        loguru_logger.remove(sink_id)

    # Not forwarded downstream → no LLMRun → no second utterance over the exit
    # line (AC2).
    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert forwarded == []
    # Classifier never scheduled.
    assert classifier._test_calls == []  # type: ignore[attr-defined]
    assert manager._in_flight is None
    # AC1 — exactly one suppression log line.
    suppress_lines = [e for e in logs if "checkpoint_post_hangup_suppress" in e]
    assert len(suppress_lines) == 1


def test_post_hangup_turn_suppressed_even_while_bot_speaking() -> None:
    """Story 6.22 AC2 — the actual overlap (cop call_id=219): the user keeps
    talking WHILE the exit line is playing (bot speaking). The post-hang-up
    suppression sits BEFORE the echo guard, so it still drops the turn — the
    echo guard alone only skips classification but STILL forwards, which would
    let the over-the-exit-line turn reach the LLM. This is the test that pins
    the placement (a suppression inside the `not _bot_speaking` block would
    regress here)."""
    tracker = _hanging_up_mock_tracker()
    manager, classifier, _t, _llm, _ctx = _make_manager(patience_tracker=tracker)
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        # Bot is mid-exit-line (BSF travels UPSTREAM to this processor).
        await manager.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        await manager.process_frame(
            _make_user_frame("Maybe you are someone else."),
            FrameDirection.DOWNSTREAM,
        )
        await _drain(manager)

    _run(_drive())

    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert forwarded == [], "post-hang-up turn must be suppressed even mid-exit-line"
    assert classifier._test_calls == []  # type: ignore[attr-defined]


def test_post_hangup_interim_turn_passes_through_unchanged() -> None:
    """Story 6.22 D2 — only FINALIZED user turns are suppressed during a
    hang-up; an interim (non-finalized) partial is harmless and follows the
    normal pass-through (it never becomes an LLM turn). Guards the `finalized`
    guard on the new early return."""
    tracker = _hanging_up_mock_tracker()
    manager, classifier, _t, _llm, _ctx = _make_manager(patience_tracker=tracker)
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("Maybe you", finalized=False),
            FrameDirection.DOWNSTREAM,
        )
        await _drain(manager)

    _run(_drive())

    # Interim frame is forwarded (pass-through) and not classified.
    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert len(forwarded) == 1
    assert classifier._test_calls == []  # type: ignore[attr-defined]


def test_triggering_turn_then_post_hangup_turn_distinct_suppress_logs() -> None:
    """Story 6.22 AC3 — end-to-end with a REAL PatienceTracker: the terminal
    TRIGGERING turn is still suppressed via the existing preemptive path
    (`checkpoint_preemptive_suppress`), and a SUBSEQUENT turn arriving after
    `is_hanging_up` flips is suppressed via the NEW post-hang-up path
    (`checkpoint_post_hangup_suppress`). Both frames are dropped, and NO single
    turn logs both lines (no double-suppression) — the happy-path triggering
    turn behaviour is unchanged."""
    from loguru import logger as loguru_logger

    tracker = PatienceTracker(
        initial_patience=15,
        fail_penalty=-15,
        silence_penalty=-10,
        recovery_bonus=0,
        silence_prompt_seconds=6.0,
        ladder_impatience_seconds=4.5,
        silence_hangup_seconds=10.0,
        escalation_thresholds=[10, 0],
        total_checkpoints=3,
    )
    manager, classifier, _t, _llm, _ctx = _make_manager(
        patience_tracker=tracker,
        classify_responses=[False, False],
    )
    captured = _capture_pushed(manager)

    logs: list[str] = []
    sink_id = loguru_logger.add(logs.append, level="INFO")
    try:

        async def _drive() -> None:
            # Turn 1: off-topic at meter=15, fail_penalty=-15 → meter zeroes →
            # character_hung_up scheduled. The triggering turn is suppressed by
            # the existing Deviation #7 preemptive path.
            await manager.process_frame(
                _make_user_frame("...I don't know."), FrameDirection.DOWNSTREAM
            )
            await _drain(manager)
            assert tracker.is_hanging_up is True
            # Turn 2: the user keeps talking AFTER the hang-up is in progress.
            await manager.process_frame(
                _make_user_frame("Maybe you are someone else."),
                FrameDirection.DOWNSTREAM,
            )
            await _drain(manager)
            # Reap the real hang-up task (mirrors the terminal-lock test).
            if tracker._hang_up_task is not None and not tracker._hang_up_task.done():
                tracker._hang_up_task.cancel()
                await asyncio.gather(tracker._hang_up_task, return_exceptions=True)

        _run(_drive())
    finally:
        loguru_logger.remove(sink_id)

    # Both turns suppressed — the exit line is the sole final utterance.
    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert forwarded == []
    # The triggering turn → exactly one preemptive_suppress (unchanged AC3).
    preemptive = [e for e in logs if "checkpoint_preemptive_suppress" in e]
    assert len(preemptive) == 1
    # The follow-up turn → exactly one post_hangup_suppress (new AC1 path).
    post_hangup = [e for e in logs if "checkpoint_post_hangup_suppress" in e]
    assert len(post_hangup) == 1


# ============================================================
# Story 6.6 review patch — fail-loud llm._settings drift detection
# ============================================================


def test_constructor_raises_when_llm_settings_system_instruction_missing() -> None:
    class _BadLLMMissingSettings:
        pass

    class _BadSettingsMissingAttr:
        pass

    class _BadLLMMissingSysInstruction:
        def __init__(self) -> None:
            self._settings = _BadSettingsMissingAttr()

    with pytest.raises(RuntimeError, match="system_instruction"):
        CheckpointManager(
            base_prompt="BASE.",
            checkpoints=_make_checkpoints(2),
            llm=_BadLLMMissingSettings(),
            llm_context=LLMContext(),
            classifier=ExchangeClassifier(api_key="k"),
            patience_tracker=MagicMock(),
            scenario_description="bad-llm-test",
            coherence_charter="CHARTER.",
        )

    with pytest.raises(RuntimeError, match="system_instruction"):
        CheckpointManager(
            base_prompt="BASE.",
            checkpoints=_make_checkpoints(2),
            llm=_BadLLMMissingSysInstruction(),
            llm_context=LLMContext(),
            classifier=ExchangeClassifier(api_key="k"),
            patience_tracker=MagicMock(),
            scenario_description="bad-llm-test",
            coherence_charter="CHARTER.",
        )


# ============================================================
# Story 6.7 — initial-state envelope
# ============================================================


def test_build_initial_envelope_returns_index_zero_frame() -> None:
    checkpoints = _make_checkpoints(6)
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints
    )
    captured = _capture_pushed(manager)

    frame = manager.build_initial_envelope()

    assert captured == []
    assert isinstance(frame, OutputTransportMessageFrame)
    data = frame.message["data"]
    assert frame.message["type"] == "checkpoint_advanced"
    assert data["index"] == 0
    assert data["total"] == 6
    assert data["checkpoint_id"] == "cp0"
    # Story 6.20 AC2 — dead `next_hint` removed from the wire.
    assert "next_hint" not in data
    # Story 6.10 — initial state has zero goals met.
    assert data["goals_met_indices"] == []
    # Story 6.10 UI refonte — every step's hint, author order, so the
    # Flutter HUD can render/animate any step locally.
    assert data["hints"] == ["hint 0", "hint 1", "hint 2", "hint 3", "hint 4", "hint 5"]
    assert manager.met_count == 0


def test_schedule_initial_emit_pushes_envelope_on_first_process_frame() -> None:
    checkpoints = _make_checkpoints(6)
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints
    )
    captured = _capture_pushed(manager)

    manager.schedule_initial_emit()
    assert _advance_envelopes(captured) == []

    async def _drive() -> None:
        await manager.process_frame(
            TextFrame(text="ignored"), FrameDirection.DOWNSTREAM
        )

    _run(_drive())

    envelopes = _advance_envelopes(captured)
    assert len(envelopes) == 1
    data = envelopes[0].message["data"]
    assert data["index"] == 0
    assert data["total"] == 6
    assert data["checkpoint_id"] == "cp0"
    assert data["goals_met_indices"] == []

    async def _drive_again() -> None:
        await manager.process_frame(
            TextFrame(text="ignored2"), FrameDirection.DOWNSTREAM
        )
        await manager.process_frame(
            TextFrame(text="ignored3"), FrameDirection.DOWNSTREAM
        )

    _run(_drive_again())

    assert len(_advance_envelopes(captured)) == 1


def test_emit_initial_state_pushes_index_zero_envelope() -> None:
    checkpoints = _make_checkpoints(6)
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.emit_initial_state()

    _run(_drive())

    envelopes = _advance_envelopes(captured)
    assert len(envelopes) == 1
    data = envelopes[0].message["data"]
    assert data["index"] == 0
    assert data["total"] == 6
    assert data["checkpoint_id"] == "cp0"
    assert "next_hint" not in data
    assert data["goals_met_indices"] == []
    assert manager.met_count == 0


# ============================================================
# Story 6.8 Phase 2 — COHERENCE_CHARTER threaded through every recompose
# ============================================================


def test_coherence_charter_appears_in_every_system_instruction_swap() -> None:
    """The COHERENCE_CHARTER must appear EXACTLY ONCE, BETWEEN base_prompt
    and the objectives block, after every recompose (init + each flip)."""
    checkpoints = _make_checkpoints(4)
    manager, _classifier, _tracker, stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        classify_responses=[True, True, True],
        coherence_charter="CHARTER.",
    )
    _capture_pushed(manager)

    # Init-time composition already set it.
    init_si = stub_llm._settings.system_instruction
    assert init_si.count("CHARTER.") == 1
    assert init_si.index("BASE PROMPT.") < init_si.index("CHARTER.")

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("first."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        si1 = stub_llm._settings.system_instruction
        assert si1.count("CHARTER.") == 1
        base_idx = si1.index("BASE PROMPT.")
        charter_idx = si1.index("CHARTER.")
        seg_idx = si1.index("prompt segment 1")
        assert base_idx < charter_idx < seg_idx

        await manager.process_frame(
            _make_user_frame("second."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        si2 = stub_llm._settings.system_instruction
        assert si2.count("CHARTER.") == 1
        assert "prompt segment 2" in si2

        await manager.process_frame(
            _make_user_frame("third."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        si3 = stub_llm._settings.system_instruction
        assert si3.count("CHARTER.") == 1
        assert "prompt segment 3" in si3

    _run(_drive())


def test_warn_on_duplicate_charter_in_composed_prompt() -> None:
    """If a future refactor embeds the charter inside base_prompt AND the
    recompose adds it again, a WARNING surfaces in journalctl."""
    from loguru import logger as loguru_logger

    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(3),
        base_prompt="BASE PROMPT. Some text including CHARTER. here.",
        coherence_charter="CHARTER.",
        classify_response=True,
    )
    _capture_pushed(manager)

    captured_logs: list[str] = []
    sink_id = loguru_logger.add(captured_logs.append, level="WARNING")

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("trigger advance."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    try:
        _run(_drive())
    finally:
        loguru_logger.remove(sink_id)

    duplicate_warnings = [
        entry for entry in captured_logs if "duplicate COHERENCE_CHARTER" in entry
    ]
    assert duplicate_warnings, (
        f"expected duplicate-charter WARNING; got: {captured_logs}"
    )


def test_terminal_turn_lock_serializes_concurrent_invocations() -> None:
    """D1 review patch — two finalized frames on a terminal turn must both
    complete atomically; the second waits for the first to release the
    lock. Both frames suppressed (first fails → meter zero → hangup;
    second observes hangup-in-progress)."""
    tracker = PatienceTracker(
        initial_patience=15,
        fail_penalty=-15,
        silence_penalty=-10,
        recovery_bonus=0,
        silence_prompt_seconds=6.0,
        ladder_impatience_seconds=4.5,
        silence_hangup_seconds=10.0,
        escalation_thresholds=[10, 0],
        total_checkpoints=3,
    )
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        patience_tracker=tracker,
        classify_responses=[False, False],
        classify_delay=0.02,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        task1 = asyncio.create_task(
            manager.process_frame(_make_user_frame("first."), FrameDirection.DOWNSTREAM)
        )
        await asyncio.sleep(0)
        task2 = asyncio.create_task(
            manager.process_frame(
                _make_user_frame("second."), FrameDirection.DOWNSTREAM
            )
        )
        await asyncio.gather(task1, task2, return_exceptions=True)
        if manager._in_flight is not None:
            await asyncio.gather(manager._in_flight, return_exceptions=True)
        if tracker._hang_up_task is not None and not tracker._hang_up_task.done():
            tracker._hang_up_task.cancel()
            await asyncio.gather(tracker._hang_up_task, return_exceptions=True)

    _run(_drive())

    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert len(forwarded) == 0


# ============================================================
# Story 6.10 — new behavioral tests for goal-based architecture
# ============================================================


def test_two_goals_flip_in_same_turn() -> None:
    """AC6 / smoke box — a turn that meets two objectives at once emits
    TWO envelopes, both carrying the SAME full goals_met_indices."""
    checkpoints = _make_checkpoints(6)

    def _fn(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        # Meet cp2 + cp3 in one turn; leave the rest unjudged (None).
        return {g["id"]: (g["id"] in ("cp2", "cp3")) or None for g in pending}

    manager, _classifier, tracker, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        multi_response_fn=_fn,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("Grilled chicken with a cola, please."),
            FrameDirection.DOWNSTREAM,
        )
        await _drain(manager)

    _run(_drive())

    assert manager.goals_state["cp2"] == "met"
    assert manager.goals_state["cp3"] == "met"
    assert manager.met_count == 2

    envelopes = _flip_envelopes(captured)
    assert len(envelopes) == 2
    indices = {e.message["data"]["index"] for e in envelopes}
    assert indices == {2, 3}
    # Both envelopes carry the SAME full met set.
    for e in envelopes:
        assert e.message["data"]["goals_met_indices"] == [2, 3]
    # One success outcome for the turn (not per-goal).
    tracker.apply_exchange_outcome.assert_called_once_with(success=True)


def test_out_of_order_goal_completion() -> None:
    """AC2 / AC8 — the user fills goal index 3 before index 2; both are
    legit, no patience drain, and eventually all goals met → completion."""
    checkpoints = _make_checkpoints(4)
    ids = [c["id"] for c in checkpoints]
    # Turn order: cp3, cp2, cp0, cp1 (deliberately out of author order).
    order = ["cp3", "cp2", "cp0", "cp1"]

    def _fn(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        target = order[call_index]
        return {g["id"]: (g["id"] == target) or None for g in pending}

    manager, _classifier, tracker, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        multi_response_fn=_fn,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        for i in range(4):
            await manager.process_frame(
                _make_user_frame(f"turn {i}"), FrameDirection.DOWNSTREAM
            )
            await _drain(manager)

    _run(_drive())

    assert manager.met_count == 4
    assert all(state == "met" for state in manager.goals_state.values())
    assert tracker.schedule_completion.call_args.kwargs.get("survival_pct") == 100
    # No off-topic fail along the way (every turn met a goal).
    false_calls = [
        c
        for c in tracker.apply_exchange_outcome.call_args_list
        if c.kwargs.get("success") is False
    ]
    assert false_calls == []
    # ids only referenced to keep the order list honest.
    assert set(order) == set(ids)


def test_off_topic_turn_only_fails_when_no_goal_matched() -> None:
    """AC8 — a fully off-topic turn (every pending goal judged unmet)
    drains patience and flips nothing."""
    checkpoints = _make_checkpoints(3)

    def _fn(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        # Everything actively unmet (off-topic "what's the weather").
        return {g["id"]: False for g in pending}

    manager, _classifier, tracker, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        multi_response_fn=_fn,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("What's the weather today?"), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    assert manager.met_count == 0
    assert _advance_envelopes(captured) == []
    tracker.apply_exchange_outcome.assert_called_once_with(success=False)


def test_partial_credit_does_not_fail() -> None:
    """AC8 — a turn that meets ONE of three pending goals is a success
    (recovery_bonus), NOT a patience deduction."""
    checkpoints = _make_checkpoints(3)

    def _fn(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        # cp1 met, cp0 + cp2 actively unmet — partial credit.
        return {g["id"]: (g["id"] == "cp1") for g in pending}

    manager, _classifier, tracker, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        multi_response_fn=_fn,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("grilled, please"), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    assert manager.goals_state["cp1"] == "met"
    assert manager.met_count == 1
    tracker.apply_exchange_outcome.assert_called_once_with(success=True)


def test_system_instruction_recomposes_after_goal_flip() -> None:
    """AC4 — drive 2 successful turns; the system instruction is rewritten
    each time and each recomposition reflects the shrinking pending set."""
    checkpoints = _make_checkpoints(4)
    manager, _classifier, _tracker, stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        classify_responses=[True, True],
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(_make_user_frame("a"), FrameDirection.DOWNSTREAM)
        await _drain(manager)
        after1 = stub_llm._settings.system_instruction
        # cp0 met → its segment dropped from the remaining block.
        assert "prompt segment 0" not in after1
        assert "prompt segment 1" in after1

        await manager.process_frame(_make_user_frame("b"), FrameDirection.DOWNSTREAM)
        await _drain(manager)
        after2 = stub_llm._settings.system_instruction
        assert "prompt segment 0" not in after2
        assert "prompt segment 1" not in after2
        assert "prompt segment 2" in after2
        assert after1 != after2

    _run(_drive())


def test_completion_fires_when_all_goals_met_via_out_of_order_path() -> None:
    """AC2 — fill goals in the order [0, 2, 1, 4, 3, 5]; once all met,
    completion fires."""
    checkpoints = _make_checkpoints(6)
    order = ["cp0", "cp2", "cp1", "cp4", "cp3", "cp5"]

    def _fn(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        target = order[call_index]
        return {g["id"]: (g["id"] == target) or None for g in pending}

    manager, _classifier, tracker, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        multi_response_fn=_fn,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        for i in range(6):
            await manager.process_frame(
                _make_user_frame(f"turn {i}"), FrameDirection.DOWNSTREAM
            )
            await _drain(manager)

    _run(_drive())

    assert manager.met_count == 6
    assert tracker.schedule_completion.call_args.kwargs.get("survival_pct") == 100


def test_envelope_carries_goals_met_indices() -> None:
    """AC6 — the envelope payload carries the FULL set of met indices
    (author order) after each flip, accumulating across turns."""
    checkpoints = _make_checkpoints(3)
    manager, _classifier, _tracker, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        classify_responses=[True, True],
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(_make_user_frame("a"), FrameDirection.DOWNSTREAM)
        await _drain(manager)
        await manager.process_frame(_make_user_frame("b"), FrameDirection.DOWNSTREAM)
        await _drain(manager)

    _run(_drive())

    envelopes = _flip_envelopes(captured)
    assert len(envelopes) == 2
    assert envelopes[0].message["data"]["goals_met_indices"] == [0]
    assert envelopes[1].message["data"]["goals_met_indices"] == [0, 1]
    # Story 6.10 UI refonte — each flip envelope carries the full hint set.
    assert envelopes[0].message["data"]["hints"] == ["hint 0", "hint 1", "hint 2"]
    assert envelopes[1].message["data"]["hints"] == ["hint 0", "hint 1", "hint 2"]


def test_suggested_focus_is_first_pending_in_author_order() -> None:
    """AC1/AC2 (Story 6.21) — even after an out-of-order flip, the
    suggested-focus block FIRMLY anchors on the author-order-first remaining
    goal, and the credited-ahead goal drops out of the pursued blocks."""
    checkpoints = _make_checkpoints(4)

    def _fn(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        # Meet cp2 first (out of order).
        return {g["id"]: (g["id"] == "cp2") or None for g in pending}

    manager, _classifier, _tracker, stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        multi_response_fn=_fn,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("cooking style is grilled"), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    # cp2 met; pending author-order-first is now cp0.
    assert manager.met_count == 1
    envelopes = _flip_envelopes(captured)
    assert len(envelopes) == 1
    # Story 6.20 AC2 — dead `next_hint` removed; the active step (cp0) is
    # computed client-side from goals_met_indices + hints.
    assert "next_hint" not in envelopes[0].message["data"]
    si = stub_llm._settings.system_instruction
    # Story 6.21 — the focus block firmly names the lowest-unmet objective
    # (cp0) as the only one to pursue next, holding the line until addressed.
    assert "the only objective you may pursue is: prompt segment 0" in si
    assert "do not move on" in si
    # AC2 — cp2 was credited out of order, so it has dropped out of the
    # pursued/remaining blocks: the character will not re-ask it.
    assert "prompt segment 2" not in si


def test_ordered_pursuit_framing_in_every_system_instruction_swap() -> None:
    """Story 6.21 AC1 — every recomposed system instruction (init + each
    flip) carries the FIRM ordered-pursuit framing: work through objectives
    in author order, hold on the lowest-unmet one until addressed, defer
    "do not re-ask" to the charter, stay in-character (not robotic), and
    NAME the current pending_goals[0]."""
    checkpoints = _make_checkpoints(3)
    manager, _classifier, _tracker, stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        classify_responses=[True],
        coherence_charter="CHARTER.",
    )
    _capture_pushed(manager)

    def _assert_ordered_framing(si: str, expected_segment: str) -> None:
        assert "in the exact order" in si  # strict author-order pursuit
        assert "do not move on" in si  # no-advance-until-addressed hold
        # acknowledge-then-redirect, anti-robotic (patience/loop gotcha)
        assert "word-for-word repeated refusal" in si
        # anti-repetition deferred to the charter, not re-implemented here
        assert "already settled" in si
        # smoke-gate hardening (call 221): one ask per turn, no later-objective probes
        assert "EXACTLY ONE ask this turn" in si
        # names the current lowest-unmet objective
        assert f"the only objective you may pursue is: {expected_segment}" in si

    # Init-time composition: lowest unmet is cp0.
    _assert_ordered_framing(stub_llm._settings.system_instruction, "prompt segment 0")

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("first."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        # cp0 met → lowest unmet is now cp1; the framing follows it.
        _assert_ordered_framing(
            stub_llm._settings.system_instruction, "prompt segment 1"
        )

    _run(_drive())


def test_focus_block_already_given_confirms_and_holds_not_advance() -> None:
    """Story 10.8 Stream D (call 336, brief §8.7) — the reconciled "already-given"
    branch must CONFIRM-and-HOLD on the still-pending beat and explicitly forbid
    advancing on the model's own assumption that the beat is done (the proximate
    call-336 strand). The old "keeps the conversation moving" advance license is
    gone; 6.21's firm hold is preserved."""
    from pipeline.checkpoint_manager import format_suggested_focus_block

    block = format_suggested_focus_block({"prompt_segment": "Ask their name."})
    low = block.lower()
    # 6.21 invariants preserved.
    assert "the only objective you may pursue is: ask their name." in low
    assert "do not move on" in low
    assert "exactly one ask this turn" in low
    # The §8.7 reconcile: confirm-and-hold + an explicit ban on jumping ahead on
    # the model's own assumption.
    assert "confirm" in low
    assert "hold here" in low
    assert "jump ahead" in low
    assert "assumption" in low
    # The old advance license MUST be gone (it caused the call-336 strand).
    assert "keeps the conversation moving" not in low


def test_stranded_early_beat_envelope_truthful_and_focus_holds() -> None:
    """Story 10.8 Stream E / AC19 (call 336) — when a LATER beat is credited
    out of order while an EARLY beat stays pending (the stranded shape that
    froze the HUD), the emitted `checkpoint_advanced` envelope carries the
    TRUTHFUL out-of-order met set (no lying about what scored) AND the steering
    HOLDS the lowest-unmet early beat. So the client's lowest-unmet activeIndex
    (computed from `goals_met_indices` = first index not met) lands on the SAME
    beat the character is steered to (`pending_goals[0]`) — they cannot disagree
    by construction. (The freeze was a stranded UNSATISFIABLE beat — fixed by
    Stream D + R9; here we lock that the HUD source-of-truth stays honest.)"""
    checkpoints = _make_checkpoints(4)

    def _fn(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        # Credit cp2 only (out of order); cp0 + cp1 stay pending (stranded early).
        return {g["id"]: (g["id"] == "cp2") or None for g in pending}

    manager, _classifier, _tracker, stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        multi_response_fn=_fn,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("an out-of-order answer"), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    envelopes = _flip_envelopes(captured)
    assert len(envelopes) == 1
    # Truthful out-of-order met set — the client renders EXACTLY what scored,
    # so its `activeIndex` (first index not in [2]) computes to 0.
    assert envelopes[0].message["data"]["goals_met_indices"] == [2]
    # The server steers to the SAME lowest-unmet beat (cp0) the client will show.
    si = stub_llm._settings.system_instruction
    assert "the only objective you may pursue is: prompt segment 0" in si


def test_pending_goals_property_preserves_author_order() -> None:
    """AC1 — `pending_goals` returns remaining checkpoints in original
    author order regardless of which goals were met out of order."""
    checkpoints = _make_checkpoints(4)
    manager, _classifier, _tracker, _llm, _ctx = _make_manager(checkpoints=checkpoints)
    manager._goals["cp1"] = "met"
    manager._goals["cp3"] = "met"

    assert [g["id"] for g in manager.pending_goals] == ["cp0", "cp2"]
    assert manager.met_count == 2
    assert manager.goals_state == {
        "cp0": "pending",
        "cp1": "met",
        "cp2": "pending",
        "cp3": "met",
    }


# ============================================================
# Story 6.20 — AC5 lost-tail self-heal + AC3 call_end met-set
# ============================================================


def test_each_flip_emits_urgent_and_reliable_duplicate() -> None:
    """Story 6.20 AC5 — every flip pushes BOTH an URGENT
    OutputTransportMessageUrgentFrame (the immediate animation) AND a queued
    OutputTransportMessageFrame duplicate carrying the SAME full-state
    payload (the lost-tail self-heal), so a lost final URGENT frame still
    lands on the ordered datachannel. The client dedupes the duplicate."""
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        classify_response=True,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("I want chicken."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    urgent = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageUrgentFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    reliable = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and not isinstance(f, OutputTransportMessageUrgentFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    assert len(urgent) == 1
    assert len(reliable) == 1
    # Identical full-state payload → the client treats the reliable copy as a
    # value-equal no-op (deduped via _animatedMet).
    assert urgent[0].message == reliable[0].message
    assert reliable[0].message["data"]["goals_met_indices"] == [0]


def test_multi_flip_emits_n_reliable_duplicates_matching_urgent() -> None:
    """Story 6.20 AC5 (multi-flip coverage, code-review 2026-06-05) — a turn
    that flips N goals at once must push N URGENT frames AND N queued reliable
    duplicates, each reliable copy value-equal to its URGENT twin. Guards the
    per-flip pairing invariant for N>=2: the single-flip
    `test_each_flip_emits_urgent_and_reliable_duplicate` alone stays green even
    if a regression drops the reliable copy on all-but-the-last mid-turn flip
    (e.g. hoisting the reliable push out of the per-flip loop)."""
    checkpoints = _make_checkpoints(4)

    def _fn(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        # Flip cp2 AND cp3 in the SAME turn (two mid-turn flips, not a
        # completion — only 2 of 4 goals).
        return {g["id"]: (g["id"] in ("cp2", "cp3")) or None for g in pending}

    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        multi_response_fn=_fn,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("Grilled chicken with a cola, please."),
            FrameDirection.DOWNSTREAM,
        )
        await _drain(manager)

    _run(_drive())

    urgent = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageUrgentFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    reliable = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and not isinstance(f, OutputTransportMessageUrgentFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    # Two flips → exactly two URGENT + two reliable duplicates (not 1, not 3).
    assert len(urgent) == 2
    assert len(reliable) == 2

    # Each reliable copy is value-equal to an URGENT twin (same full-state
    # payload), so the multiset of (index, met-set) pairs matches.
    def _payload_key(frame: Frame) -> tuple[int, tuple[int, ...]]:
        data = frame.message["data"]
        return data["index"], tuple(data["goals_met_indices"])

    assert sorted(_payload_key(f) for f in urgent) == sorted(
        _payload_key(f) for f in reliable
    )
    # Both flips carry the SAME full met set [2, 3].
    for f in reliable:
        assert f.message["data"]["goals_met_indices"] == [2, 3]


def test_set_goals_met_indices_synced_to_tracker_on_flip() -> None:
    """Story 6.20 AC3 — on every successful flip the manager mirrors the REAL
    met SET (author-order indices) to the PatienceTracker so the `call_end`
    envelope can carry which goals were met, not just how many. Verified for
    an OUT-OF-ORDER completion (the case the count alone would mislabel)."""
    checkpoints = _make_checkpoints(4)

    def _fn(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        # Meet cp2 first (out of order) — the set must be [2], not [0].
        return {g["id"]: (g["id"] == "cp2") or None for g in pending}

    manager, _classifier, tracker, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        multi_response_fn=_fn,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("grilled, please."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    tracker.set_goals_met_indices.assert_called_with([2])
    tracker.set_checkpoints_passed.assert_called_with(1)


# ============================================================
# Story 6.20 follow-up — echo guard (call_id=225 false greet credit)
# ============================================================


def test_echo_during_bot_speech_is_not_classified() -> None:
    """call_id=225 regression — a finalized user TranscriptionFrame that
    arrives WHILE the bot is speaking (mic echo of the character's own line)
    must NOT be classified (no false checkpoint credit), but MUST still be
    forwarded downstream (pass-through)."""
    manager, classifier, _tracker, _llm, _ctx = _make_manager()
    captured = _capture_pushed(manager)

    async def _drive() -> TranscriptionFrame:
        # Bot starts its opening line (BSF travels UPSTREAM to this processor).
        await manager.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        tf = _make_user_frame("hi")  # 1-word echo blip mid-greeting
        await manager.process_frame(tf, FrameDirection.DOWNSTREAM)
        await _drain(manager)
        return tf

    tf = _run(_drive())

    assert classifier._test_calls == [], "echo must NOT reach the classifier"
    assert manager.met_count == 0
    assert tf in captured, "echo frame must still be forwarded (pass-through)"


def test_classification_resumes_after_bot_stops_speaking() -> None:
    """Once the bot stops (BotStoppedSpeakingFrame UPSTREAM), the guard
    clears and the user's real turn is classified normally — the barge-in /
    normal-reply happy path."""
    manager, classifier, _tracker, _llm, _ctx = _make_manager()
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        await manager.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await manager.process_frame(
            _make_user_frame("I'll have the steak."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    assert len(classifier._test_calls) == 1, "real turn after bot stops is judged"


def test_bot_started_speaking_downstream_does_not_arm_guard() -> None:
    """Direction discipline — the DOWNSTREAM copy of BotStartedSpeakingFrame
    (which goes into the sink in prod) must NOT arm the echo guard; only the
    UPSTREAM copy does. Proves we gate on UPSTREAM, not a mocked direction."""
    manager, classifier, _tracker, _llm, _ctx = _make_manager()
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM
        )
        await manager.process_frame(
            _make_user_frame("I'll have the steak."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    assert len(classifier._test_calls) == 1, "DOWNSTREAM BSF must not arm the guard"


def test_BSF_stopped_direction_matches_pipecat_emission_routing() -> None:
    """Déviation #28 contract test (mirror of PatienceTracker's) — the echo
    guard's `BotStoppedSpeakingFrame` UPSTREAM check MUST match the direction
    pipecat's BaseOutputTransport actually emits. Source-text matched so a
    pipecat upgrade OR an accidental revert to DOWNSTREAM fires before deploy."""
    import inspect

    from pipecat.transports.base_output import BaseOutputTransport

    pipecat_src = inspect.getsource(BaseOutputTransport)
    fn_start = pipecat_src.find("async def _bot_stopped_speaking")
    assert fn_start != -1, (
        "pipecat structure changed — `_bot_stopped_speaking` no longer on "
        "BaseOutputTransport. Re-verify the BSF emission contract."
    )
    fn_body = pipecat_src[fn_start : fn_start + 1500]
    assert "BotStoppedSpeakingFrame()" in fn_body
    assert "FrameDirection.UPSTREAM" in fn_body, (
        "pipecat no longer pushes BSF upstream from `_bot_stopped_speaking` — "
        "the CheckpointManager echo-guard UPSTREAM check must be re-verified."
    )

    cm_src = inspect.getsource(cm_mod)
    marker = "isinstance(frame, BotStoppedSpeakingFrame)"
    start = cm_src.find(marker)
    assert start != -1, (
        "CheckpointManager no longer references BotStoppedSpeakingFrame — "
        "the echo-guard clear path changed; re-evaluate this contract test."
    )
    assert "FrameDirection.UPSTREAM" in cm_src[start : start + 300], (
        "CheckpointManager's BotStoppedSpeakingFrame check no longer gates on "
        "UPSTREAM — this reverts the Déviation #28 invariant (the guard would "
        "never clear). Re-apply UPSTREAM or update this test if pipecat changed."
    )


def test_BSF_started_direction_matches_pipecat_emission_routing() -> None:
    """Déviation #28 contract test — the echo guard's `BotStartedSpeakingFrame`
    UPSTREAM check MUST match pipecat's emission direction (the guard would
    never ARM if this drifted, so echo would slip through silently)."""
    import inspect

    from pipecat.transports.base_output import BaseOutputTransport

    pipecat_src = inspect.getsource(BaseOutputTransport)
    fn_start = pipecat_src.find("async def _bot_started_speaking")
    assert fn_start != -1, (
        "pipecat structure changed — `_bot_started_speaking` no longer on "
        "BaseOutputTransport. Re-verify the BSF emission contract."
    )
    fn_body = pipecat_src[fn_start : fn_start + 1500]
    assert "BotStartedSpeakingFrame()" in fn_body
    assert "FrameDirection.UPSTREAM" in fn_body, (
        "pipecat no longer pushes BSF upstream from `_bot_started_speaking` — "
        "the CheckpointManager echo-guard UPSTREAM check must be re-verified."
    )

    cm_src = inspect.getsource(cm_mod)
    marker = "isinstance(frame, BotStartedSpeakingFrame)"
    start = cm_src.find(marker)
    assert start != -1, (
        "CheckpointManager no longer references BotStartedSpeakingFrame — "
        "the echo-guard arm path changed; re-evaluate this contract test."
    )
    assert "FrameDirection.UPSTREAM" in cm_src[start : start + 300], (
        "CheckpointManager's BotStartedSpeakingFrame check no longer gates on "
        "UPSTREAM — the echo guard would never arm. Re-apply UPSTREAM or update "
        "this test if pipecat routing genuinely changed."
    )


# ============================================================
# Story 6.23 — reactive-checkpoint precondition gating
# ============================================================


def _reactive_checkpoints() -> list[dict]:
    """3 beats: two proactive + one reactive gated on the 2nd (the trigger).

    Mirrors the cop incident shape in miniature:
      - cp0 `alibi`  — proactive (any-order).
      - cp1 `lock_times` — proactive; the TRIGGER.
      - cp2 `correct_misquote` — reactive, `requires: lock_times`.
    """
    return [
        dict(
            id="alibi",
            hint_text="state where you were",
            prompt_segment="ask where they were",
            success_criteria="names a specific place",
        ),
        dict(
            id="lock_times",
            hint_text="give arrival and departure",
            prompt_segment="ask for both clock times",
            success_criteria="gives both an arrival and a departure clock time",
        ),
        dict(
            id="correct_misquote",
            requires="lock_times",
            hint_text="correct the misquoted time",
            prompt_segment="misquote their departure time",
            success_criteria="disputes a wrong time and gives the corrected one",
        ),
    ]


def test_judgeable_goals_gates_reactive_until_trigger_met() -> None:
    """Pure helper (T1): a `requires` beat is excluded while its trigger is
    pending, included once the trigger is met; a no-`requires` beat is always
    judgeable while pending."""
    cps = _reactive_checkpoints()

    all_pending = {
        "alibi": "pending",
        "lock_times": "pending",
        "correct_misquote": "pending",
    }
    ids = [cp["id"] for cp in judgeable_goals(cps, all_pending)]
    assert ids == ["alibi", "lock_times"]  # reactive beat gated

    trigger_met = {
        "alibi": "pending",
        "lock_times": "met",
        "correct_misquote": "pending",
    }
    ids = [cp["id"] for cp in judgeable_goals(cps, trigger_met)]
    assert ids == [
        "alibi",
        "correct_misquote",
    ]  # gate opened (lock_times now met → off pending)

    # A met reactive beat is never re-judged (it's no longer pending).
    all_done = {"alibi": "met", "lock_times": "met", "correct_misquote": "met"}
    assert judgeable_goals(cps, all_done) == []


def test_judgeable_goals_no_requires_is_byte_identical_to_pending() -> None:
    """AC3 — for checkpoints WITHOUT any `requires`, judgeable_goals returns the
    full pending set (no gating), so the change is a no-op for proactive-only
    scenarios."""
    cps = _make_checkpoints(3)  # none carry `requires`
    state = {"cp0": "pending", "cp1": "met", "cp2": "pending"}
    ids = [cp["id"] for cp in judgeable_goals(cps, state)]
    assert ids == ["cp0", "cp2"]


def test_judgeable_goals_multi_level_chain_opens_one_step_at_a_time() -> None:
    """A 3-level reactive chain A→B→C (each beat gated on the previous) opens one
    link at a time — exactly the cop arc's react_to_fingerprint_accusation →
    explain_prints_on_inside_handle → elaborate_through_silence shape."""
    cps = [
        dict(id="A", hint_text="a", prompt_segment="a", success_criteria="a"),
        dict(
            id="B",
            requires="A",
            hint_text="b",
            prompt_segment="b",
            success_criteria="b",
        ),
        dict(
            id="C",
            requires="B",
            hint_text="c",
            prompt_segment="c",
            success_criteria="c",
        ),
    ]
    # Nothing met: only the proactive root A is judgeable.
    assert [
        c["id"]
        for c in judgeable_goals(cps, {"A": "pending", "B": "pending", "C": "pending"})
    ] == ["A"]
    # A met: B opens, C still gated (its trigger B is not met).
    assert [
        c["id"]
        for c in judgeable_goals(cps, {"A": "met", "B": "pending", "C": "pending"})
    ] == ["B"]
    # A+B met: C finally opens.
    assert [
        c["id"] for c in judgeable_goals(cps, {"A": "met", "B": "met", "C": "pending"})
    ] == ["C"]


def test_judgeable_goals_returns_empty_when_every_pending_beat_is_gated() -> None:
    """Direct coverage of the defensive empty-return branch: a contrived state
    where the only pending beat is reactive and its trigger is NOT met yields an
    empty judgeable set. (The loader forbids the dangling/forward edges that
    would let this arise in a REAL conversation — with valid backward-only edges
    the earliest pending beat is always judgeable — but the helper must still be
    correct for the degenerate input.)"""
    cps = [
        dict(id="trigger", hint_text="t", prompt_segment="t", success_criteria="t"),
        dict(
            id="reactive",
            requires="trigger",
            hint_text="r",
            prompt_segment="r",
            success_criteria="r",
        ),
    ]
    # trigger already MET but no longer pending; reactive pending → reactive is
    # judgeable. To force ALL-gated we mark trigger as a non-met, non-pending
    # sentinel so it is neither judged nor satisfies the gate.
    state = {"trigger": "skipped", "reactive": "pending"}
    assert judgeable_goals(cps, state) == []


def test_reactive_beat_absent_from_judge_payload_until_trigger() -> None:
    """AC1 — the gated reactive beat is NEVER in the classify payload while its
    trigger is pending, so it cannot flip even if the judge is over-eager.

    Drives a turn that an over-eager judge would credit on EVERYTHING in the
    payload; asserts the reactive beat is excluded from the payload AND stays
    pending."""

    def _flip_all(pending_goals: list[dict], _idx: int) -> dict[str, bool | None]:
        # Over-eager judge: credit every goal it is asked about.
        return {g["id"]: True for g in pending_goals}

    manager, classifier, _t, _llm, _ctx = _make_manager(
        checkpoints=_reactive_checkpoints(),
        multi_response_fn=_flip_all,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("Actually I left at half past 8, I was at Jos's diner."),
            FrameDirection.DOWNSTREAM,
        )
        await _drain(manager)

    _run(_drive())

    calls = classifier._test_calls  # type: ignore[attr-defined]
    assert len(calls) == 1
    payload_ids = [g["id"] for g in calls[0]["pending_goals"]]
    # The reactive trap is NOT offered to the judge — structural gating.
    assert "correct_misquote" not in payload_ids
    assert payload_ids == ["alibi", "lock_times"]
    # And so it did NOT flip even though the judge said "met" to everything.
    assert manager.goals_state["correct_misquote"] == "pending"
    # The two proactive beats DID flip (over-eager judge credited them).
    assert manager.goals_state["alibi"] == "met"
    assert manager.goals_state["lock_times"] == "met"


def test_reactive_beat_becomes_judgeable_after_trigger_met() -> None:
    """AC2 — once the trigger beat is credited, the reactive beat enters the
    judge payload on the next turn and a genuine attempt credits it."""

    def _flip_first(pending_goals: list[dict], _idx: int) -> dict[str, bool | None]:
        # Credit only the first goal offered (author-order analog).
        out: dict[str, bool | None] = {g["id"]: None for g in pending_goals}
        if pending_goals:
            out[pending_goals[0]["id"]] = True
        return out

    manager, classifier, _t, _llm, _ctx = _make_manager(
        checkpoints=_reactive_checkpoints(),
        multi_response_fn=_flip_first,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        # Turn 1 → flips `alibi`. Reactive beat still gated (lock_times pending).
        await manager.process_frame(
            _make_user_frame("I was at Jos's diner."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        # Turn 2 → flips `lock_times` (the trigger).
        await manager.process_frame(
            _make_user_frame("I got there at 8, left at half past 9."),
            FrameDirection.DOWNSTREAM,
        )
        await _drain(manager)
        # Turn 3 → reactive beat now judgeable; flips it.
        await manager.process_frame(
            _make_user_frame("No, that's wrong — I said half past nine."),
            FrameDirection.DOWNSTREAM,
        )
        await _drain(manager)

    _run(_drive())

    calls = classifier._test_calls  # type: ignore[attr-defined]
    # Turn 1 payload excludes the reactive beat; turn 3 payload includes it.
    assert "correct_misquote" not in [g["id"] for g in calls[0]["pending_goals"]]
    assert "correct_misquote" in [g["id"] for g in calls[2]["pending_goals"]]
    assert manager.goals_state["correct_misquote"] == "met"


def test_reactive_gating_does_not_drain_patience_on_gated_only_attempt() -> None:
    """A turn that an over-eager judge would FAIL on the gated reactive beat
    does not drain patience for that beat — because the beat is never judged.

    Here turn 1 is off-topic (no proactive beat met). The judge returns False
    for the judgeable beats → one patience drain, exactly as a normal off-topic
    miss; the gated reactive beat contributes nothing (it isn't in the payload).
    """

    def _fail_all(pending_goals: list[dict], _idx: int) -> dict[str, bool | None]:
        return {g["id"]: False for g in pending_goals}

    tracker = MagicMock()
    tracker.is_hanging_up = False
    tracker.patience = 100
    tracker.fail_penalty = -15

    manager, classifier, _t, _llm, _ctx = _make_manager(
        checkpoints=_reactive_checkpoints(),
        multi_response_fn=_fail_all,
        patience_tracker=tracker,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("Nice weather today."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    calls = classifier._test_calls  # type: ignore[attr-defined]
    assert "correct_misquote" not in [g["id"] for g in calls[0]["pending_goals"]]
    # Exactly one off-topic miss recorded (the gated beat didn't add a second).
    tracker.apply_exchange_outcome.assert_called_once_with(success=False)


def test_cop_call_222_alibi_does_not_credit_correct_misquoted_time() -> None:
    """AC9 regression — the live cop incident (call_id=222), fake judge, zero
    network. A turn-3-style alibi ('actually at half past 8 … at Jos's diner')
    must NOT credit the far-later trap `correct_misquoted_time`, because that
    beat now `requires: lock_arrival_and_departure` (never met at this point).

    Uses the REAL `cop_interrogation_01` checkpoints so the regression rides on
    the shipped YAML edges, not a fixture. The fake judge is OVER-EAGER (credits
    everything in the payload), so if the trap were in the payload it WOULD flip
    — proving the gate, not the criteria wording, blocks it.
    """
    cop_checkpoints = scenarios.load_scenario_checkpoints("cop_interrogation_01")

    def _flip_all(pending_goals: list[dict], _idx: int) -> dict[str, bool | None]:
        return {g["id"]: True for g in pending_goals}

    manager, classifier, _t, _llm, _ctx = _make_manager(
        checkpoints=cop_checkpoints,
        multi_response_fn=_flip_all,
        scenario_description="The 8:30 Alibi",
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame(
                "Actually at half past 8 I was at Jos's diner on 5th Avenue."
            ),
            FrameDirection.DOWNSTREAM,
        )
        await _drain(manager)

    _run(_drive())

    calls = classifier._test_calls  # type: ignore[attr-defined]
    payload_ids = [g["id"] for g in calls[0]["pending_goals"]]
    # The trap is gated (its trigger lock_arrival_and_departure is not met yet).
    assert "correct_misquoted_time" not in payload_ids
    assert manager.goals_state["correct_misquoted_time"] == "pending"
    # Sanity: the trigger IS gated-out too at this point? No — it's proactive
    # (no requires), so it's offered and (over-eager judge) credited. The point
    # of the test is only that the TRAP stayed pending.
    assert "lock_arrival_and_departure" in payload_ids


# ---------- FR37: abuse → inappropriate-content hang-up --------------------


def test_abuse_flag_schedules_inappropriate_exit() -> None:
    """FR37 — when the SAME classify_multi call flags the turn abusive, the
    manager ends the call in-character (reason=inappropriate_content) and does
    NOT process goals for that turn."""

    def _fn(pending_goals, idx):
        # Clearly abusive turn: no goal met, abuse flag true.
        out = {g["id"]: None for g in pending_goals}
        out[ABUSE_KEY] = True
        return out

    manager, _classifier, tracker, _llm, _ctx = _make_manager(multi_response_fn=_fn)
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("you stupid worthless piece of garbage"),
            FrameDirection.DOWNSTREAM,
        )
        await _drain(manager)

    asyncio.run(_drive())

    tracker.schedule_inappropriate_exit.assert_called_once()
    # The abusive turn is NOT processed as a goal outcome.
    tracker.apply_exchange_outcome.assert_not_called()
    # No goal flipped on the abusive turn.
    assert all(state == "pending" for state in manager.goals_state.values())


def test_no_abuse_does_not_schedule_inappropriate_exit() -> None:
    """A normal turn (abuse flag false) never triggers the inappropriate exit,
    and goals advance as usual."""

    def _fn(pending_goals, idx):
        out = {g["id"]: None for g in pending_goals}
        out[pending_goals[0]["id"]] = True  # first goal met
        out[ABUSE_KEY] = False
        return out

    manager, _classifier, tracker, _llm, _ctx = _make_manager(multi_response_fn=_fn)
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("Hi, I'd like the grilled chicken please"),
            FrameDirection.DOWNSTREAM,
        )
        await _drain(manager)

    asyncio.run(_drive())

    tracker.schedule_inappropriate_exit.assert_not_called()
    assert manager.met_count == 1  # the goal still flipped normally


def test_abuse_false_does_not_pollute_advance_goals() -> None:
    """The reserved abuse key is POPPED before `advance_goals`. A normal
    all-unsure turn with abuse=false must stay patience-NEUTRAL — if the
    `False` leaked into the verdicts it would read as a goal 'unmet' → a
    spurious 'fail' → patience drain on every benign turn."""

    def _fn(pending_goals, idx):
        out = {g["id"]: None for g in pending_goals}  # all unsure
        out[ABUSE_KEY] = False
        return out

    manager, _classifier, tracker, _llm, _ctx = _make_manager(multi_response_fn=_fn)
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("um, I'm not sure"), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    asyncio.run(_drive())

    tracker.schedule_inappropriate_exit.assert_not_called()
    # NEUTRAL (all-unsure) — NOT a fail. The abuse-False did not pollute.
    tracker.apply_exchange_outcome.assert_not_called()


def test_abuse_ignored_when_detection_disabled() -> None:
    """The ABUSE_DETECTION_ENABLED=0 kill-switch: the flag is still popped (so it
    can't pollute goal judging) but the hang-up is NOT triggered."""

    def _fn(pending_goals, idx):
        out = {g["id"]: None for g in pending_goals}
        out[ABUSE_KEY] = True
        return out

    manager, _classifier, tracker, _llm, _ctx = _make_manager(
        multi_response_fn=_fn, abuse_detection_enabled=False
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("you absolute idiot"), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    asyncio.run(_drive())

    tracker.schedule_inappropriate_exit.assert_not_called()
    # Popped, so no spurious goal outcome from the abuse key either.
    tracker.apply_exchange_outcome.assert_not_called()


# ---------- SPIKE PIVOT (2026-07-01): engine-counted disrespect stakes ------


def _disrespect_fn(pending_goals, idx):
    out = {g["id"]: None for g in pending_goals}
    out[ABUSE_KEY] = False
    out[DISRESPECT_KEY] = True
    return out


def test_spike_disrespect_budget_triggers_hangup() -> None:
    """SPIKE PIVOT — the engine counts consecutive judge-scored disrespect turns
    and fires the (existing) inappropriate exit once the per-character budget is
    spent: "two shut-ups to a cop → end" as a hard, engine-enforced rule."""
    manager, _c, tracker, _llm, _ctx = _make_manager(
        multi_response_fn=_disrespect_fn,
        spike_character_led=True,
        spike_no_fail_drain=True,
        disrespect_budget=2,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("shut up"), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        # Turn 1: count=1 < budget → no hang-up yet.
        assert tracker.schedule_inappropriate_exit.call_count == 0
        await manager.process_frame(
            _make_user_frame("shut up"), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    asyncio.run(_drive())

    # Turn 2: count=2 == budget → hang-up fires (reuses the abuse teardown).
    tracker.schedule_inappropriate_exit.assert_called_once()


def test_spike_disrespect_count_resets_when_learner_re_engages() -> None:
    """SPIKE PIVOT — a genuinely engaged turn (a checkpoint credited) REFILLS the
    budget, so a learner who slips once then cooperates is not hung up later."""

    def _fn(pending_goals, idx):
        out = {g["id"]: None for g in pending_goals}
        out[ABUSE_KEY] = False
        if idx == 1:
            # Turn 2 — cooperative: first goal met, not disrespectful.
            out[pending_goals[0]["id"]] = True
            out[DISRESPECT_KEY] = False
        else:
            # Turns 1 and 3 — disrespectful.
            out[DISRESPECT_KEY] = True
        return out

    manager, _c, tracker, _llm, _ctx = _make_manager(
        multi_response_fn=_fn,
        spike_character_led=True,
        spike_no_fail_drain=True,
        disrespect_budget=2,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("shut up"), FrameDirection.DOWNSTREAM
        )  # count 1
        await _drain(manager)
        await manager.process_frame(
            _make_user_frame("I'll have the chicken"), FrameDirection.DOWNSTREAM
        )  # engaged → reset to 0
        await _drain(manager)
        await manager.process_frame(
            _make_user_frame("shut up"), FrameDirection.DOWNSTREAM
        )  # count 1 again — still < budget 2
        await _drain(manager)

    asyncio.run(_drive())

    tracker.schedule_inappropriate_exit.assert_not_called()


def test_spike_disrespect_ignored_when_spike_off() -> None:
    """SPIKE control — with SPIKE_CHARACTER_LED off, the disrespect flag is still
    popped (never pollutes goals) but is never counted or acted on."""
    manager, _c, tracker, _llm, _ctx = _make_manager(
        multi_response_fn=_disrespect_fn,
        disrespect_budget=1,  # spike OFF (spike_character_led defaults False)
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("shut up"), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    asyncio.run(_drive())

    tracker.schedule_inappropriate_exit.assert_not_called()


# ============================================================
# Story 6.27 — `implies` superset back-fill in `advance_goals`
# ============================================================
#
# A later beat may declare `implies: <earlier_id>` (the exact mirror of the
# Story 6.23 `requires` edge): when the later beat flips to met and the
# implied earlier beat is still pending, the engine auto-credits the earlier
# one in code, same turn, no LLM — transitively. Kills the call_id=266 class
# of bug (an earlier beat whose success_criteria is a logical SUPERSET of a
# later beat's gets stranded when the judge credits only the narrower beat).


def _implies_checkpoints(*entries: tuple[str, str | None]) -> list[dict]:
    """Minimal checkpoint dicts for pure `advance_goals` tests: each entry is
    `(id, implies_or_None)`."""
    out: list[dict] = []
    for cid, implies in entries:
        cp = {
            "id": cid,
            "hint_text": cid,
            "prompt_segment": cid,
            "success_criteria": cid,
        }
        if implies is not None:
            cp["implies"] = implies
        out.append(cp)
    return out


def test_backfill_credits_implied_earlier_beat_same_turn() -> None:
    """Direct back-fill: the later beat flips via verdict, the implied earlier
    beat is auto-credited in the SAME GoalAdvance — no LLM verdict needed."""
    checkpoints = _implies_checkpoints(("a", None), ("b", "a"), ("c", None))
    goals = {"a": "pending", "b": "pending", "c": "pending"}

    adv = advance_goals(
        goals, {"a": False, "b": True, "c": False}, checkpoints=checkpoints
    )

    assert adv.new_goals == {"a": "met", "b": "met", "c": "pending"}
    assert adv.met_count == 2
    assert adv.all_met is False
    assert adv.outcome == "success"


def test_backfill_transitive_chain_resolves_in_one_pass() -> None:
    """A←B←C chain: crediting C back-fills B, which back-fills A — all in the
    same turn (edges point strictly earlier, so the pass terminates)."""
    checkpoints = _implies_checkpoints(("a", None), ("b", "a"), ("c", "b"))
    goals = {"a": "pending", "b": "pending", "c": "pending"}

    adv = advance_goals(goals, {"c": True}, checkpoints=checkpoints)

    assert adv.new_goals == {"a": "met", "b": "met", "c": "met"}
    assert adv.flipped_ids == ["c", "b", "a"]
    assert adv.all_met is True


def test_backfill_noop_when_target_already_met() -> None:
    """An `implies` edge whose target is already met changes nothing — the
    back-fill only fires on a still-pending target."""
    checkpoints = _implies_checkpoints(("a", None), ("b", "a"))
    goals = {"a": "met", "b": "pending"}

    adv = advance_goals(goals, {"b": True}, checkpoints=checkpoints)

    assert adv.flipped_ids == ["b"]
    assert adv.new_goals == {"a": "met", "b": "met"}


def test_no_implies_behaviour_is_byte_identical() -> None:
    """A scenario without any `implies` edge behaves exactly as pre-6.27:
    same flips, same outcome classes (success / fail / neutral)."""
    checkpoints = _implies_checkpoints(("a", None), ("b", None))

    success = advance_goals(
        {"a": "pending", "b": "pending"}, {"b": True}, checkpoints=checkpoints
    )
    assert success.new_goals == {"a": "pending", "b": "met"}
    assert success.flipped_ids == ["b"]
    assert success.outcome == "success"

    fail = advance_goals(
        {"a": "pending", "b": "pending"},
        {"a": False, "b": False},
        checkpoints=checkpoints,
    )
    assert fail.flipped_ids == []
    assert fail.outcome == "fail"

    neutral = advance_goals(
        {"a": "pending", "b": "pending"},
        {"a": None, "b": None},
        checkpoints=checkpoints,
    )
    assert neutral.flipped_ids == []
    assert neutral.outcome == "neutral"


def test_backfill_never_fires_without_a_direct_flip() -> None:
    """No direct verdict flip → no back-fill (the queue seeds from the direct
    flips). A fail turn cannot back-fill anything."""
    checkpoints = _implies_checkpoints(("a", None), ("b", "a"))
    goals = {"a": "pending", "b": "pending"}

    adv = advance_goals(goals, {"b": False}, checkpoints=checkpoints)

    assert adv.new_goals == goals
    assert adv.flipped_ids == []
    assert adv.outcome == "fail"


def test_backfilled_ids_append_after_direct_flips() -> None:
    """`flipped_ids` order: the direct verdict flips first (in verdict-dict
    order), then the back-filled ids in discovery order — so the per-flip
    envelope emission order stays stable."""
    checkpoints = _implies_checkpoints(("a", None), ("b", "a"), ("c", None))
    goals = {"a": "pending", "b": "pending", "c": "pending"}

    adv = advance_goals(goals, {"b": True, "c": True}, checkpoints=checkpoints)

    assert adv.flipped_ids == ["b", "c", "a"]


def test_all_met_reachable_via_backfill() -> None:
    """The completion path triggers when the LAST pending beat is credited via
    back-fill (all_met computed AFTER the back-fill)."""
    checkpoints = _implies_checkpoints(("a", None), ("b", "a"))
    goals = {"a": "pending", "b": "pending"}

    adv = advance_goals(goals, {"b": True}, checkpoints=checkpoints)

    assert adv.all_met is True
    assert adv.met_count == 2


def test_call_266_replay_waiter_backfills_greet_to_six_of_six() -> None:
    """Regression net for prod call_id=266 (2026-06-09, `waiter_easy_01`).

    Replays the exact verdict sequence from the call-266 journal through the
    REAL shipped waiter checkpoints (with the Story 6.27 `main_course →
    implies: greet` edge). On the pre-6.27 engine this run ended 5/6 with
    `greet` permanently stranded (the judge credited the narrower
    `main_course` on "grilled chicken" and declined the superset `greet`);
    with the back-fill it must end 6/6.
    """
    checkpoints = scenarios.load_scenario_checkpoints("waiter_easy_01")
    assert [cp["id"] for cp in checkpoints] == [
        "greet",
        "main_course",
        "clarify",
        "drink",
        "confirm",
        "close",
    ]
    goals = {cp["id"]: "pending" for cp in checkpoints}

    # Turn 1 — "Hi, good evening. Could I see the menu, please?" hit a
    # classifier ReadTimeout → verdicts None → `advance_goals` never ran
    # (patience-neutral infra failure). Nothing to replay.

    # Turn 2 — "Hmm, I have the grilled chicken, please." credited
    # main_course + clarify but NOT greet (the superset trap).
    adv = advance_goals(
        goals,
        {
            "greet": False,
            "main_course": True,
            "clarify": True,
            "drink": False,
            "confirm": False,
            "close": False,
        },
        checkpoints=checkpoints,
    )
    goals = adv.new_goals
    # THE FIX — greet is back-filled via main_course's `implies` edge.
    assert goals["greet"] == "met"
    assert adv.met_count == 3

    # Turn 3 — "Grilled." → no flip in the real call.
    adv = advance_goals(
        goals,
        {"drink": False, "confirm": False, "close": False},
        checkpoints=checkpoints,
    )
    goals = adv.new_goals
    assert adv.flipped_ids == []

    # Turn 4 — "Water." → drink.
    adv = advance_goals(
        goals,
        {"drink": True, "confirm": False, "close": False},
        checkpoints=checkpoints,
    )
    goals = adv.new_goals

    # Turn 5 — "No, it's right." → confirm.
    adv = advance_goals(
        goals, {"confirm": True, "close": False}, checkpoints=checkpoints
    )
    goals = adv.new_goals

    # Turn 6 — "Okay." → close → 6/6 (was 5/6 + stranded greet pre-6.27).
    adv = advance_goals(goals, {"close": True}, checkpoints=checkpoints)
    assert adv.all_met is True
    assert adv.met_count == 6


def test_backfill_rides_flipped_ids_into_envelopes_and_journal() -> None:
    """6.27 review — drive the call-266 turn-2 shape through the REAL
    `CheckpointManager` (not just the pure function): the judge credits the
    narrower later beat while judging the implied earlier beat unmet on the
    SAME turn. The back-fill must ride `flipped_ids` into the per-flip
    envelope loop — one URGENT `checkpoint_advanced` per beat (direct flip
    first, the back-fill appended), every envelope carrying the same
    post-flip full met set (the HUD double-tick of smoke call 274) — and the
    journal must mark the back-fill explicitly (`checkpoint_backfilled`),
    since the `checkpoint_verdicts` line on the same turn legitimately shows
    that beat unmet."""
    from loguru import logger as loguru_logger

    checkpoints = _make_checkpoints(3)
    checkpoints[1]["implies"] = "cp0"

    def _fn(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        # The call-266 superset trap: cp1 met, its implied cp0 actively unmet.
        return {"cp0": False, "cp1": True, "cp2": None}

    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        multi_response_fn=_fn,
    )
    captured = _capture_pushed(manager)

    log_lines: list[str] = []
    sink_id = loguru_logger.add(log_lines.append, level="INFO")
    try:

        async def _drive() -> None:
            await manager.process_frame(
                _make_user_frame("I'll have the grilled chicken."),
                FrameDirection.DOWNSTREAM,
            )
            await _drain(manager)

        _run(_drive())
    finally:
        loguru_logger.remove(sink_id)

    flips = _flip_envelopes(captured)
    # Direct flip (cp1, index 1) first, the back-filled cp0 (index 0) appended.
    assert [f.message["data"]["index"] for f in flips] == [1, 0]
    # Every envelope carries the SAME post-flip full met set → HUD ticks both.
    assert all(f.message["data"]["goals_met_indices"] == [0, 1] for f in flips)
    # The journal marks the in-code credit so forensics never mistake it for
    # a judge verdict.
    assert any("checkpoint_backfilled" in line and "cp0" in line for line in log_lines)


# ============================================================
# Story 6.29 — D1 bounded wait-for-verdict (AC7 / AC9)
# ============================================================


def test_verdict_within_budget_lands_before_frame_forwarded() -> None:
    """AC7 core — on the non-terminal path the verdict's side effects (goal
    flip, recompose, checkpoint_advanced envelope, patience outcome) land
    BEFORE the user TranscriptionFrame is forwarded downstream. The captured
    push order proves it: the flip envelopes precede the TF."""
    manager, _classifier, tracker, stub_llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(6),
        classify_response=True,
        classify_delay=0.05,
        verdict_wait_budget_ms=800,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("grilled chicken."), FrameDirection.DOWNSTREAM
        )

    _run(_drive())

    # The verdict landed INSIDE process_frame — no drain needed.
    assert manager.met_count == 1
    tracker.apply_exchange_outcome.assert_called_once_with(success=True)
    # Recompose already happened before the frame forward.
    assert "prompt segment 1" in stub_llm._settings.system_instruction
    # Push ORDER: flip envelope(s) BEFORE the forwarded TranscriptionFrame.
    tf_positions = [
        i for i, f in enumerate(captured) if isinstance(f, TranscriptionFrame)
    ]
    flip_positions = [
        i
        for i, f in enumerate(captured)
        if isinstance(
            f, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)
        )
        and f.message.get("type") == "checkpoint_advanced"
    ]
    assert tf_positions and flip_positions
    assert max(flip_positions) < min(tf_positions), (
        f"verdict side effects must land BEFORE the frame forward; "
        f"got flips at {flip_positions}, TF at {tf_positions}"
    )


def test_budget_miss_forwards_frame_and_verdict_applies_late() -> None:
    """D1(c) budget-miss half — a classify slower than the budget must NOT
    block the turn: the frame forwards with stale steering and the verdict
    applies late (pre-6.29 behavior). Fail-open, never a cancel
    (`asyncio.shield` keeps the task alive through the miss)."""
    manager, _classifier, tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(6),
        classify_response=True,
        classify_delay=0.30,
        verdict_wait_budget_ms=50,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("slow verdict."), FrameDirection.DOWNSTREAM
        )
        # Budget missed → frame already forwarded, verdict still pending.
        assert manager.met_count == 0
        forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
        assert len(forwarded) == 1, "budget miss must forward the frame"
        # The shielded task survives the miss and applies late.
        await _drain(manager)

    _run(_drive())

    assert manager.met_count == 1, "late verdict must still apply (shielded task)"
    tracker.apply_exchange_outcome.assert_called_once_with(success=True)


def test_wait_disabled_with_zero_budget_keeps_parallel_path() -> None:
    """`VERDICT_WAIT_BUDGET_MS=0` is the sanctioned rollback to the pre-6.29
    parallel behavior: process_frame forwards immediately, classify in flight."""
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(6),
        classify_response=True,
        classify_delay=0.10,
        verdict_wait_budget_ms=0,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("parallel turn."), FrameDirection.DOWNSTREAM
        )
        assert manager.met_count == 0, "no wait: verdict must still be in flight"
        assert any(isinstance(f, TranscriptionFrame) for f in captured)
        await _drain(manager)

    _run(_drive())
    assert manager.met_count == 1


def test_verdict_wait_logs_per_turn_duration_line() -> None:
    """AC9 — the greppable `checkpoint_verdict_wait` INFO line carries the
    measured wait + budget + whether the verdict landed (smoke-gate
    observable, sits next to `checkpoint_verdicts` in journalctl)."""
    from loguru import logger as loguru_logger

    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(6),
        classify_response=True,
        classify_delay=0.05,
        verdict_wait_budget_ms=800,
    )
    _capture_pushed(manager)

    log_lines: list[str] = []
    sink_id = loguru_logger.add(log_lines.append, level="INFO")
    try:

        async def _drive() -> None:
            await manager.process_frame(
                _make_user_frame("logged turn."), FrameDirection.DOWNSTREAM
            )

        _run(_drive())
    finally:
        loguru_logger.remove(sink_id)

    wait_lines = [e for e in log_lines if "checkpoint_verdict_wait" in e]
    assert len(wait_lines) == 1
    assert "budget_ms=800" in wait_lines[0]
    assert "verdict_landed=True" in wait_lines[0]


def test_verdict_wait_fail_open_on_crashed_classify_task() -> None:
    """Fail-open invariant — a classify task that DIES (bug, not timeout)
    must never mute the character: the frame still forwards. Review 6.29:
    the AC9 observable must report verdict_landed=False on the crash (no
    verdict side effects landed) — not a deceptive True next to the
    traceback."""
    from loguru import logger as loguru_logger

    manager, classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(6),
        verdict_wait_budget_ms=800,
    )

    async def _boom(**kwargs):
        raise RuntimeError("classifier exploded")

    classifier.classify_multi = _boom  # type: ignore[assignment]
    captured = _capture_pushed(manager)

    logs: list[str] = []
    sink_id = loguru_logger.add(logs.append, level="INFO")
    try:

        async def _drive() -> None:
            await manager.process_frame(
                _make_user_frame("crash turn."), FrameDirection.DOWNSTREAM
            )

        _run(_drive())
    finally:
        loguru_logger.remove(sink_id)

    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert len(forwarded) == 1, "a crashed judge must never mute the character"
    wait_lines = [e for e in logs if "checkpoint_verdict_wait waited_ms=" in e]
    assert len(wait_lines) == 1
    assert "verdict_landed=False" in wait_lines[0]


def test_completion_within_budget_suppresses_frame_via_existing_backstop() -> None:
    """When THIS turn's verdict completes the call inside the budget, the
    existing post-serialize completion check suppresses the frame — the
    survived exit line stays the sole final utterance (Deviation #7), with
    NO new suppression path added by 6.29."""
    # 3 checkpoints, all pending → the precheck is NON-terminal (met_count
    # 0 + 1 < 3, meter high), yet ONE verdict flips everything → completion
    # fires DURING the bounded wait.
    checkpoints3 = _make_checkpoints(3)

    def _fn3(pending: list[dict], call_index: int) -> dict[str, bool | None]:
        return {g["id"]: True for g in pending}

    manager, _classifier, tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints3,
        multi_response_fn=_fn3,
        classify_delay=0.03,
        verdict_wait_budget_ms=800,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("everything at once."), FrameDirection.DOWNSTREAM
        )

    _run(_drive())

    assert manager.met_count == 3
    tracker.schedule_completion.assert_called_once()
    forwarded = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert forwarded == [], (
        "a turn whose own verdict completes the call must be suppressed "
        "(checkpoint_suppress_post_serialize_completion)"
    )


# ============================================================
# Story 6.29 — AC8 mood-tag directive in every composition
# ============================================================


def test_compose_appends_mood_tag_directive_by_default() -> None:
    """AC8 — `compose_goal_system_instruction` appends MOOD_TAG_DIRECTIVE as
    the LAST block by default (boot + every recompose can't forget it), in
    BOTH the pending-goals shape and the all-met wrap-up collapse."""
    from pipeline.prompts import MOOD_TAG_DIRECTIVE

    pending = _make_checkpoints(2)
    composed = compose_goal_system_instruction(
        base_prompt="BASE.",
        coherence_charter="CHARTER.",
        pending_goals=pending,
    )
    assert composed.endswith(MOOD_TAG_DIRECTIVE)
    assert composed.index("CHARTER.") < composed.index("<mood:VALUE>")

    wrap_up = compose_goal_system_instruction(
        base_prompt="BASE.",
        coherence_charter="CHARTER.",
        pending_goals=[],
    )
    assert "Wrap up the conversation naturally." in wrap_up
    assert wrap_up.endswith(MOOD_TAG_DIRECTIVE)

    # Tests may compose without it (empty string opt-out).
    bare = compose_goal_system_instruction(
        base_prompt="BASE.",
        coherence_charter="CHARTER.",
        pending_goals=pending,
        mood_tag_directive="",
    )
    assert "<mood:VALUE>" not in bare


def test_manager_recompose_carries_mood_directive_every_time() -> None:
    """AC8 invariance — the directive survives construction AND every
    recompose (it is composed in by default, exactly like the charter)."""
    manager, _classifier, _tracker, stub_llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(2),
        classify_responses=[True, True],
    )
    _capture_pushed(manager)

    assert stub_llm._settings.system_instruction.count("<mood:VALUE>") == 1

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("first."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        assert stub_llm._settings.system_instruction.count("<mood:VALUE>") == 1
        await manager.process_frame(
            _make_user_frame("second."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    # All-met wrap-up composition still carries it, exactly once.
    final_si = stub_llm._settings.system_instruction
    assert final_si.count("<mood:VALUE>") == 1
    assert "Wrap up the conversation naturally." in final_si


def test_checkpoint_breakdown_reports_met_missed_in_author_order() -> None:
    """Story 7.5 B7 — the teardown breakdown lists every beat in author order
    with its hint + met state (the factual decomposition of the survival %)."""
    manager, *_ = _make_manager(checkpoints=_make_checkpoints(3))
    manager._goals["cp0"] = "met"
    manager._goals["cp2"] = "met"
    assert manager.checkpoint_breakdown == [
        {"id": "cp0", "hint": "hint 0", "met": True},
        {"id": "cp1", "hint": "hint 1", "met": False},
        {"id": "cp2", "hint": "hint 2", "met": True},
    ]
