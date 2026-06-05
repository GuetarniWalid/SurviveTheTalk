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
    BotStoppedSpeakingFrame,
    Frame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from pipeline.checkpoint_manager import CheckpointManager
from pipeline.exchange_classifier import ExchangeClassifier
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
) -> tuple[CheckpointManager, ExchangeClassifier, MagicMock, _StubLLM, LLMContext]:
    """Build a fully-mocked manager. The classifier's `classify_multi`
    is replaced with an async stub.

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
    # NON-terminal turns only — the default `_make_manager` MagicMock
    # tracker's `is_hanging_up` is a truthy Mock, so `not pt.is_hanging_up`
    # is False and `is_terminal_turn` short-circuits to False, keeping
    # this on the normal pass-through path. Terminal-turn suppression is
    # covered by the Deviation #7 tests below.
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
