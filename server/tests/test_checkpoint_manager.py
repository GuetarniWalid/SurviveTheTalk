"""Story 6.6 — Tests for CheckpointManager FrameProcessor (AC2, AC5, AC9 #2)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    Frame,
    OutputTransportMessageFrame,
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
    base = [
        dict(
            id=f"cp{i}",
            hint_text=f"hint {i}",
            prompt_segment=f"prompt segment {i}",
            success_criteria=f"User says thing {i}.",
        )
        for i in range(n)
    ]
    return base


def _capture_pushed(manager: CheckpointManager) -> list[Frame]:
    captured: list[Frame] = []

    async def _recorder(frame: Frame, direction: FrameDirection) -> None:
        captured.append(frame)

    manager.push_frame = _recorder  # type: ignore[assignment]
    return captured


class _StubSettings:
    """Stand-in for `OpenRouterLLMService._settings` exposing
    `system_instruction` as a plain mutable attribute."""

    def __init__(self, system_instruction: str = "") -> None:
        self.system_instruction = system_instruction


class _StubLLM:
    """Stand-in LLM service with a `._settings.system_instruction`
    field that the manager mutates on advance."""

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
) -> tuple[CheckpointManager, MagicMock, MagicMock, _StubLLM, LLMContext]:
    """Build a fully-mocked manager for testing.

    Returns (manager, classifier_mock, patience_tracker_mock, stub_llm,
    llm_context). The classifier's `classify` method is replaced with
    an async function that returns either a single value or a sequence
    (one per call, raising IndexError past the end).
    """
    checkpoints = checkpoints or _make_checkpoints(3)
    classifier = ExchangeClassifier(openrouter_api_key="test-key")

    call_count = {"n": 0}

    async def _stub_classify(**kwargs: Any) -> bool | None:
        idx = call_count["n"]
        call_count["n"] += 1
        if classify_delay:
            await asyncio.sleep(classify_delay)
        if classify_responses is not None:
            return classify_responses[idx]
        return classify_response

    classifier.classify = _stub_classify  # type: ignore[assignment]
    # Wrap with a MagicMock for call inspection — but route through the
    # stub so the async behavior is preserved.
    classifier_calls: list[dict] = []

    real_classify = classifier.classify

    async def _tracked_classify(**kwargs: Any) -> bool | None:
        classifier_calls.append(kwargs)
        return await real_classify(**kwargs)

    classifier.classify = _tracked_classify  # type: ignore[assignment]

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

    # Attach the captured-calls list to the classifier for inspection.
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


def test_finalized_transcription_schedules_classifier() -> None:
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
    assert calls[0]["success_criteria"] == "User says thing 0."
    assert calls[0]["scenario_description"] == "The Waiter"


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
    # Review patch caveat — this test ONLY proves pass-through for
    # NON-terminal turns. The default `_make_manager` uses a
    # `MagicMock()` patience tracker whose `is_hanging_up`
    # attribute returns a truthy Mock by default, but Story 6.6
    # Deviation #7's `is_terminal_turn` predicate requires
    # `not pt.is_hanging_up` AND a meter-zeroing penalty (or last
    # checkpoint). With a fresh MagicMock the meter math returns
    # Mock objects that don't compare with ints — the predicate
    # short-circuits to False, keeping this test on the normal
    # async path where pass-through IS mandatory. The terminal-
    # turn carve-out (frame INTENTIONALLY suppressed) is covered
    # by `test_preemptive_hangup_suppresses_user_frame_when_meter_will_zero`
    # and `test_preemptive_completion_suppresses_user_frame_on_last_checkpoint`.
    manager, _classifier, _tracker, _llm, _ctx = _make_manager()
    captured = _capture_pushed(manager)

    frame = frame_factory()

    async def _drive() -> None:
        await manager.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(manager)

    _run(_drive())

    assert frame in captured, f"{type(frame).__name__} must be forwarded downstream"


# ---------- Test 5: met=true advances index, swaps prompt, emits envelope -


def test_met_true_advances_index_swaps_prompt_emits_envelope() -> None:
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

    # Index advanced 0 → 1.
    assert manager._index == 1

    # System prompt was swapped in-place on _settings. Story 6.8 Phase 2:
    # the COHERENCE_CHARTER sits BETWEEN base_prompt and prompt_segment
    # so its position never moves regardless of which checkpoint is
    # active.
    assert stub_llm._settings.system_instruction == (
        "BASE PROMPT.\n\nCHARTER.\n\nprompt segment 1"
    )

    # Envelope was pushed.
    envelopes = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    assert len(envelopes) == 1
    data = envelopes[0].message["data"]
    assert data["checkpoint_id"] == "cp1"
    assert data["index"] == 1
    assert data["total"] == 3
    assert data["next_hint"] == "hint 1"

    # PatienceTracker.apply_exchange_outcome(True) was called.
    tracker.apply_exchange_outcome.assert_called_with(success=True)

    # Story 6.7 review (2026-05-20) — CheckpointManager must push the
    # live passed-count to PatienceTracker on every advance so the
    # `call_end` envelope reflects partial progress on non-survived
    # exit paths (character_hung_up / inappropriate). Index 1 here
    # = "one checkpoint passed (cp0)".
    tracker.set_checkpoints_passed.assert_called_with(1)


# ---------- Test 6: met=false does NOT advance, applies fail_penalty -----


def test_met_false_does_not_advance_applies_fail_penalty() -> None:
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

    assert manager._index == 0
    assert stub_llm._settings.system_instruction == initial_prompt
    envelopes = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    assert envelopes == []
    tracker.apply_exchange_outcome.assert_called_with(success=False)


# ---------- Test 7: classifier=None is INFRA failure — patience neutral --


def test_classifier_None_does_not_advance_and_does_not_drain_patience() -> None:
    """Story 6.9 reliability patch (2026-05-21) — a None verdict (HTTP
    error, classifier timeout, parse failure) is OUR infrastructure
    failing, not a user mistake. The checkpoint MUST NOT advance
    (no free progression) AND the patience meter MUST NOT drain
    (don't punish the user for our infra).

    Pre-patch this test asserted `apply_exchange_outcome(success=False)`
    was called → drained -15 patience per inconclusive verdict. The
    Story 6.9 smoke test (call 138, "Pasta. Pasta. Pasta.") proved this
    was wrong: a single HTTP timeout against OpenRouter cost the user
    15 patience for a turn they delivered perfectly. Post-patch the
    classifier failure is silent on the patience side.
    """
    manager, _classifier, tracker, stub_llm, _ctx = _make_manager(
        classify_response=None
    )
    captured = _capture_pushed(manager)
    initial_prompt = stub_llm._settings.system_instruction

    # Story 6.9 review patch — reset the mock BEFORE driving so the
    # assertion that `apply_exchange_outcome` was never called can't
    # pass for the wrong reason (e.g. if `_make_manager` setup ever
    # incidentally touches the tracker mock during construction).
    tracker.apply_exchange_outcome.reset_mock()

    async def _drive() -> None:
        await manager.process_frame(_make_user_frame("..."), FrameDirection.DOWNSTREAM)
        await _drain(manager)

    _run(_drive())

    # Checkpoint still NOT advanced (conservative no-free-progression).
    assert manager._index == 0
    assert stub_llm._settings.system_instruction == initial_prompt
    envelopes = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    assert envelopes == []
    # Patience MUST NOT have been touched. The infra failure is invisible
    # to the meter — the next user turn gets another classification chance.
    tracker.apply_exchange_outcome.assert_not_called()


def test_consecutive_None_verdicts_force_fail_penalty_after_threshold() -> None:
    """Story 6.9 review patch P16 (from D1) — `verdict=None` is
    patience-neutral (Deviation #5) to avoid punishing the user for
    OpenRouter hiccups. But unbounded neutrality opens a soft-lock
    window: sustained classifier failure → user keeps talking, no
    checkpoint advance, no patience drain, no hangup. After
    `_MAX_CONSECUTIVE_NONE_VERDICTS` consecutive `None` verdicts the
    manager MUST force `apply_exchange_outcome(success=False)` so the
    call surfaces the degradation as normal patience drain instead of
    spinning forever.

    Drives 5 user frames against a stuck classifier; asserts
    `apply_exchange_outcome` was called exactly once (on the 5th).
    """
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

    # After exactly N consecutive None verdicts, apply_exchange_outcome
    # MUST have been called exactly once (on the Nth).
    assert tracker.apply_exchange_outcome.call_count == 1, (
        f"sustained classifier failure must trigger fail_penalty exactly "
        f"once after {_MAX_CONSECUTIVE_NONE_VERDICTS} consecutive None "
        f"verdicts; got {tracker.apply_exchange_outcome.call_count} calls"
    )
    # And it MUST have been called with success=False (the drain path).
    tracker.apply_exchange_outcome.assert_called_with(success=False)
    # Counter must reset after the forced drain so a 2nd burst of
    # failures gets the same fresh N-attempt grace.
    assert manager._consecutive_none_count == 0


def test_consecutive_None_counter_resets_on_real_verdict() -> None:
    """Story 6.9 review patch P16 — a transient classifier hiccup
    must NOT compound across a long call. Counter resets to 0 on any
    True or False verdict so 4 Nones followed by a True followed by 4
    more Nones does NOT trigger the force (would otherwise reach the
    5-Nones threshold on the cumulative count).
    """
    from pipeline.checkpoint_manager import _MAX_CONSECUTIVE_NONE_VERDICTS

    # 4 Nones, then 1 True, then 4 more Nones.
    classify_responses = (
        [None] * (_MAX_CONSECUTIVE_NONE_VERDICTS - 1)
        + [True]
        + [None] * (_MAX_CONSECUTIVE_NONE_VERDICTS - 1)
    )
    # Enough checkpoints to absorb the True without overflowing.
    checkpoints = _make_checkpoints(5)
    manager, _classifier, tracker, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
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

    # The True verdict at index 4 calls `apply_exchange_outcome(
    # success=True)` as part of checkpoint advance — that's expected
    # and unrelated to the consecutive-None backstop. What MUST NOT
    # happen is a `success=False` call from the force-drain: neither
    # burst (4 then 4) crossed the threshold because the True verdict
    # reset the counter in between.
    success_false_calls = [
        c
        for c in tracker.apply_exchange_outcome.call_args_list
        if c.kwargs.get("success") is False
    ]
    assert len(success_false_calls) == 0, (
        f"transient hiccup followed by a real verdict must NOT trigger "
        f"the force-drain (success=False); got {len(success_false_calls)} "
        f"such calls. All calls: {tracker.apply_exchange_outcome.call_args_list}"
    )


def test_terminal_turn_classifier_blocking_bounded_under_3s() -> None:
    """Story 6.9 review patch P18 (from D2) — Deviation #6 widened the
    classifier budget to 2.0s; on the terminal-turn preemptive sync
    path (Deviation #7 from 6.6), the elapsed wall-clock for
    `_run_classifier_blocking` MUST stay bounded ≤3000ms even on a
    slow classifier. Without this regression net, a future widening
    of `_CLASSIFIER_TIMEOUT_SECONDS` (e.g. to 5s) would silently push
    terminal-turn latency well past the PRD ceiling.

    Mocks a deliberately slow classifier (sleeps 1.8s) and drives a
    terminal turn; asserts the total `_run_classifier_blocking`
    elapsed is under the documented 3000ms bound.
    """
    import time

    # 1-checkpoint scenario (already terminal). Real classifier sleeps
    # 1.8 s before returning True.
    checkpoints = _make_checkpoints(1)

    async def _slow_classify(**kwargs: Any) -> bool:
        await asyncio.sleep(1.8)
        return True

    # Use the regular _make_manager but swap the classifier's classify.
    manager, classifier, tracker, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        classify_responses=[True],
    )
    classifier.classify = _slow_classify  # type: ignore[method-assign]
    # Tracker reports we ARE on the terminal turn (last checkpoint OR
    # next-fail-zeros-meter). For a 1-checkpoint scenario the
    # last-checkpoint branch handles it via self._index + 1 >= len.
    tracker.is_hanging_up = False
    tracker.patience = 100
    tracker.fail_penalty = -15

    async def _drive() -> float:
        start = time.monotonic()
        await manager._run_classifier_blocking("final attempt")
        return time.monotonic() - start

    elapsed = _run(_drive())

    assert elapsed <= 3.0, (
        f"terminal-turn _run_classifier_blocking elapsed {elapsed:.2f}s "
        f"exceeds the 3.0s bound (Deviation #6 documented in spec). "
        "Story 6.8 AC5 p95 ≤2000ms is explicitly retracted for the "
        "terminal-turn path; this is the new ceiling."
    )


# ---------- Test 8: last checkpoint passing routes to schedule_completion -


def test_last_checkpoint_passed_routes_to_schedule_completion() -> None:
    """When the FINAL checkpoint passes, the manager calls
    `patience_tracker.schedule_completion(survival_pct=100)` and does
    NOT advance the index out of bounds, NOT emit a checkpoint_advanced
    envelope (Story 6.7 will own any "all complete" UI envelope)."""
    # 2-checkpoint scenario: 0 → 1 → done.
    checkpoints = _make_checkpoints(2)
    manager, _classifier, tracker, stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        classify_responses=[True, True],
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        # Pass checkpoint 0 → advance to 1.
        await manager.process_frame(
            _make_user_frame("first."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        assert manager._index == 1

        # Pass checkpoint 1 (the final one) → schedule_completion.
        await manager.process_frame(
            _make_user_frame("second."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    # Index stayed at the last index — no out-of-bounds advance.
    assert manager._index == 1

    # Exactly ONE checkpoint_advanced envelope (for the 0 → 1 advance).
    # The final pass does NOT emit one.
    envelopes = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    assert len(envelopes) == 1
    assert envelopes[0].message["data"]["index"] == 1

    # schedule_completion was called with survival_pct=100.
    tracker.schedule_completion.assert_called_with(survival_pct=100)

    # Story 6.7 review (2026-05-20) — on terminal completion the
    # passed count must equal len(checkpoints) so `call_end.checkpoints_passed`
    # reflects full survival. CheckpointManager pushes `set_checkpoints_passed`
    # BEFORE `schedule_completion` (the order matters because both end
    # up in PatienceTracker._run_hang_up which reads the stored count).
    tracker.set_checkpoints_passed.assert_any_call(len(checkpoints))
    # The order matters: set_checkpoints_passed(N) before schedule_completion.
    call_order = [call[0] for call in tracker.method_calls]
    assert call_order.index("set_checkpoints_passed") < call_order.index(
        "schedule_completion"
    ), (
        "set_checkpoints_passed must be called BEFORE schedule_completion "
        "so PatienceTracker._run_hang_up reads the live count on the "
        "survived path."
    )


# ---------- Test 9: stale verdict suppressed by generation guard ---------


def test_stale_verdict_dropped_by_generation_guard() -> None:
    """Two finalized TranscriptionFrames back-to-back: the older
    classifier task's verdict must NOT advance the checkpoint after the
    newer task has already won.

    The cancel + create_task sequence in `_schedule_classification`
    has two redundant defenses against the older task's emit:
      1. `prior.cancel()` raises CancelledError into the in-flight
         classify call (interrupting `asyncio.sleep` mid-classify).
      2. Generation guard in `_classify_and_advance` catches any
         stale task that DID complete its classify before the cancel
         propagated (race window between create_task and the first
         await yield).

    Either defense alone suffices; together they're belt-and-braces.
    The assertion here is the user-visible invariant: exactly ONE
    advance + ONE apply_exchange_outcome lands, regardless of which
    defense fired."""
    manager, _classifier, tracker, _stub_llm, _ctx = _make_manager(
        classify_response=True,
        classify_delay=0.05,
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        # Fire two frames back-to-back; the first task is in-flight when
        # the second arrives. The second task's cancel + create_task
        # sequence must drop the first task's would-be emit.
        await manager.process_frame(
            _make_user_frame("first."), FrameDirection.DOWNSTREAM
        )
        await manager.process_frame(
            _make_user_frame("second."), FrameDirection.DOWNSTREAM
        )
        # Wait for the surviving task to finish.
        if manager._in_flight is not None:
            await asyncio.gather(manager._in_flight, return_exceptions=True)

    _run(_drive())

    # Only ONE successful advance landed (the second task's).
    assert manager._index == 1
    # apply_exchange_outcome was called at most once with success=True
    # (the first task got cancelled and never reached the outcome line).
    success_calls = [
        c
        for c in tracker.apply_exchange_outcome.call_args_list
        if c.kwargs.get("success") is True
    ]
    assert len(success_calls) == 1


# ---------- Test 10: last character line read from LLMContext ------------


def test_last_character_line_read_from_llm_context() -> None:
    """The classifier's `last_character_line` is sourced from the
    latest `role='assistant'` message in the shared LLMContext. The
    spec's frame-observation approach can't work (LLM emits TextFrame
    DOWNSTREAM, CheckpointManager sits UPSTREAM of LLM) — reading the
    context is the robust mechanism (Deviation #2 / module docstring)."""
    manager, classifier, _tracker, _stub_llm, ctx = _make_manager()
    _capture_pushed(manager)

    # Simulate the aggregator pair having added user + assistant turns.
    ctx.add_message({"role": "user", "content": "Hello."})
    ctx.add_message({"role": "assistant", "content": "Welcome to The Golden Fork."})

    async def _drive() -> None:
        await manager.process_frame(
            _make_user_frame("Yes, ordering."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)

    _run(_drive())

    calls = classifier._test_calls  # type: ignore[attr-defined]
    assert len(calls) == 1
    assert calls[0]["last_character_line"] == "Welcome to The Golden Fork."


def test_last_character_line_empty_when_no_assistant_turn_yet() -> None:
    """First user turn: no assistant message in the context — empty
    string is the classifier-prompt-safe sentinel."""
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
    """Pipeline shutdown must cancel + drain any pending classifier
    task, otherwise `Task was destroyed but it is pending!` log noise
    surfaces in journalctl on every clean teardown."""
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
    """A bug that loads an empty checkpoint list MUST fail at
    construction (call init), not later mid-call with an IndexError."""
    classifier = ExchangeClassifier(openrouter_api_key="test-key")
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
    """The smoke gate observes `CheckpointManager init scenario_description=...
    checkpoint_count=N first_checkpoint_id=...` on every call start —
    pairs with `PatienceTracker config initial_patience=...` to prove
    both processors are alive in the pipeline."""
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
# Story 6.6 Deviation #7 — preemptive synchronous classify on
# terminal turns (meter-zero hangup OR last checkpoint completion)
# ============================================================


def _terminal_mock_tracker(
    *, patience: int, fail_penalty: int = -15, hang_up_after: bool = False
) -> MagicMock:
    """Mock PatienceTracker that exposes the public properties Deviation #7
    reads (`patience`, `fail_penalty`, `is_hanging_up`), with optional
    simulation of `is_hanging_up` flipping after
    `apply_exchange_outcome(False)` (mirrors the real tracker's
    meter-zero auto-hangup behaviour from Deviation #6)."""
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
    """Mock that simulates schedule_completion flipping `is_hanging_up`
    (mirrors the real tracker's behaviour)."""
    tracker = MagicMock()
    tracker.patience = 100
    tracker.fail_penalty = -15
    tracker.is_hanging_up = False

    def _flip_on_completion(**kwargs: Any) -> None:
        tracker.is_hanging_up = True

    tracker.schedule_completion.side_effect = _flip_on_completion
    return tracker


def test_preemptive_hangup_suppresses_user_frame_when_meter_will_zero() -> None:
    """Terminal turn (meter=10, fail_penalty=-15): the classifier verdict
    is awaited synchronously; verdict=False zeroes the meter (mock
    flips _hang_up_in_progress); the user frame is SUPPRESSED so the
    LLM doesn't produce a parallel response that would land before the
    exit line."""
    tracker = _terminal_mock_tracker(patience=10, hang_up_after=True)
    manager, _classifier, _t, _llm, _ctx = _make_manager(
        patience_tracker=tracker,
        classify_response=False,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        frame = _make_user_frame("Cats are funny.")
        await manager.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(manager)

    _run(_drive())

    tracker.apply_exchange_outcome.assert_called_with(success=False)
    forwarded_user_frames = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert forwarded_user_frames == [], (
        "Deviation #7: terminal-turn user frame must be SUPPRESSED so "
        "the LLM never produces a parallel response before the exit line"
    )


def test_preemptive_path_forwards_frame_on_success_recovery() -> None:
    """Terminal turn (danger zone), but classifier returns True: the
    user recovers, the checkpoint advances, AND the frame is forwarded
    so the LLM can respond normally."""
    tracker = _terminal_mock_tracker(patience=10, hang_up_after=True)
    manager, _classifier, _t, stub_llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(3),
        patience_tracker=tracker,
        classify_response=True,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        frame = _make_user_frame("I would like the chicken, please.")
        await manager.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(manager)

    _run(_drive())

    assert manager._index == 1
    # Story 6.8 Phase 2 — charter slotted between base_prompt and segment.
    assert stub_llm._settings.system_instruction == (
        "BASE PROMPT.\n\nCHARTER.\n\nprompt segment 1"
    )
    tracker.apply_exchange_outcome.assert_called_with(success=True)
    forwarded_user_frames = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert len(forwarded_user_frames) == 1


def test_preemptive_completion_suppresses_user_frame_on_last_checkpoint() -> None:
    """Last checkpoint, classifier returns True → schedule_completion
    fires (mock flips _hang_up_in_progress) → user frame SUPPRESSED so
    the LLM doesn't produce an in-between response that lands before
    the survived exit line."""
    tracker = _completion_mock_tracker()
    checkpoints = _make_checkpoints(2)
    manager, _classifier, _t, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        patience_tracker=tracker,
        classify_response=True,
    )
    manager._index = 1  # already on the last checkpoint
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        frame = _make_user_frame("Thank you.")
        await manager.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(manager)

    _run(_drive())

    tracker.schedule_completion.assert_called_with(survival_pct=100)
    forwarded_user_frames = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert forwarded_user_frames == [], (
        "Deviation #7: terminal-turn (last checkpoint) user frame must "
        "be SUPPRESSED so the LLM doesn't land an in-between response "
        "before the survived exit line"
    )
    advance_envelopes = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    assert advance_envelopes == []


def test_preemptive_path_forwards_frame_on_last_checkpoint_unmet() -> None:
    """Last checkpoint, classifier returns False → completion does NOT
    fire (no flip), so the frame IS forwarded — the user gets another
    try and the LLM responds normally."""
    tracker = _completion_mock_tracker()  # only flips on completion
    checkpoints = _make_checkpoints(2)
    manager, _classifier, _t, _llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        patience_tracker=tracker,
        classify_response=False,
    )
    manager._index = 1
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        frame = _make_user_frame("Uh, weather?")
        await manager.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(manager)

    _run(_drive())

    tracker.schedule_completion.assert_not_called()
    forwarded_user_frames = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert len(forwarded_user_frames) == 1
    tracker.apply_exchange_outcome.assert_called_with(success=False)


def test_normal_async_path_unchanged_for_high_meter_non_last_checkpoint() -> None:
    """When the meter is far from zero AND we are not on the last
    checkpoint, the original parallel-async path runs: frame is
    forwarded immediately, classifier runs in the background."""
    tracker = _terminal_mock_tracker(patience=80, hang_up_after=False)
    manager, _classifier, _t, _llm, _ctx = _make_manager(
        checkpoints=_make_checkpoints(5),
        patience_tracker=tracker,
        classify_response=True,
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        frame = _make_user_frame("I would like the chicken.")
        await manager.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(manager)

    _run(_drive())

    forwarded_user_frames = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert len(forwarded_user_frames) == 1
    assert manager._index == 1


def test_preemptive_path_falls_through_on_classifier_exception() -> None:
    """If the preemptive classifier call raises, the manager logs and
    falls through to push_frame so the LLM still gets a chance to
    respond — graceful degradation rather than wedging the call."""
    tracker = _terminal_mock_tracker(patience=10, hang_up_after=False)

    # Set up a classifier that raises a runtime error on classify().
    failing_classifier = ExchangeClassifier(openrouter_api_key="test-key")

    async def _explode(**_kwargs: Any) -> bool | None:
        raise RuntimeError("simulated classifier outage")

    failing_classifier.classify = _explode  # type: ignore[assignment]

    stub_llm = _StubLLM()
    manager = CheckpointManager(
        base_prompt="BASE.",
        checkpoints=_make_checkpoints(3),
        llm=stub_llm,
        llm_context=LLMContext(),
        classifier=failing_classifier,
        patience_tracker=tracker,
        scenario_description="exception-test",
        coherence_charter="CHARTER.",
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        frame = _make_user_frame("dangerous turn.")
        await manager.process_frame(frame, FrameDirection.DOWNSTREAM)
        await _drain(manager)

    _run(_drive())

    # Frame IS forwarded — fall-through path.
    forwarded_user_frames = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert len(forwarded_user_frames) == 1, (
        "on classifier exception in preemptive path, frame must be forwarded "
        "so the LLM can respond (graceful degradation)"
    )


# ============================================================
# Story 6.6 review patches — added 2026-05-18
# ============================================================


def test_constructor_raises_when_llm_settings_system_instruction_missing() -> None:
    """D5 review patch — pipecat API drift must surface at construction
    time, not silently mid-call. The advance path mutates
    `llm._settings.system_instruction` directly; a future pipecat
    rename of `_settings` would otherwise produce no error but stop the
    swap from taking effect (the LLM would keep the original prompt
    forever, every checkpoint would appear stuck)."""

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
            classifier=ExchangeClassifier(openrouter_api_key="k"),
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
            classifier=ExchangeClassifier(openrouter_api_key="k"),
            patience_tracker=MagicMock(),
            scenario_description="bad-llm-test",
            coherence_charter="CHARTER.",
        )


# ============================================================
# Story 6.7 — AC1: emit_initial_state() method
# ============================================================


def test_build_initial_envelope_returns_index_zero_frame() -> None:
    """Story 6.7 AC1 + Phase 2 retouche #4 — `build_initial_envelope`
    returns ONE `OutputTransportMessageFrame` describing the FIRST
    checkpoint (`index=0`, `total=N`, `checkpoint_id=<first>`,
    `next_hint=<first>`). Pure builder — no `push_frame` side effect,
    no `self._index` mutation. The caller (bot.py) queues it via
    `task.queue_frames(...)` to avoid the StartFrame propagation race.
    """
    checkpoints = _make_checkpoints(6)
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints
    )
    captured = _capture_pushed(manager)

    frame = manager.build_initial_envelope()

    # Pure builder — must NOT have pushed anything.
    assert captured == []
    assert isinstance(frame, OutputTransportMessageFrame)
    data = frame.message["data"]
    assert frame.message["type"] == "checkpoint_advanced"
    assert data["index"] == 0
    assert data["total"] == 6
    assert data["checkpoint_id"] == "cp0"
    assert data["next_hint"] == "hint 0"
    # Index MUST stay at 0 — informational, not an advance.
    assert manager._index == 0


def test_schedule_initial_emit_pushes_envelope_on_first_process_frame() -> None:
    """Story 6.7 Phase 2 retouche #5 — `schedule_initial_emit` flags
    the initial-state envelope for emission. The actual `push_frame`
    runs inside `process_frame` on the FIRST frame seen after the
    flag is set (by which time `super().process_frame(...)` has
    flipped `_started=True`, so the push is valid).

    Before the first `process_frame` tick: no envelope pushed.
    After the first tick: exactly one `checkpoint_advanced(index=0)`
    envelope was pushed, and the flag was cleared (idempotent —
    subsequent ticks don't re-emit).
    """
    checkpoints = _make_checkpoints(6)
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints
    )
    captured = _capture_pushed(manager)

    # Schedule the emit BUT don't drive any frame yet.
    manager.schedule_initial_emit()
    initial_envelopes = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    assert initial_envelopes == [], (
        "schedule_initial_emit must only set a flag — no push yet"
    )

    # Drive any frame (e.g. an unrelated TextFrame) to trigger the
    # deferred emit.
    async def _drive() -> None:
        await manager.process_frame(
            TextFrame(text="ignored"), FrameDirection.DOWNSTREAM
        )

    _run(_drive())

    envelopes = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    assert len(envelopes) == 1, (
        f"expected exactly one initial envelope after first tick, got {len(envelopes)}"
    )
    data = envelopes[0].message["data"]
    assert data["index"] == 0
    assert data["total"] == 6
    assert data["checkpoint_id"] == "cp0"

    # Idempotent — driving more frames must NOT re-emit.

    async def _drive_again() -> None:
        await manager.process_frame(
            TextFrame(text="ignored2"), FrameDirection.DOWNSTREAM
        )
        await manager.process_frame(
            TextFrame(text="ignored3"), FrameDirection.DOWNSTREAM
        )

    _run(_drive_again())

    envelopes_after = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    assert len(envelopes_after) == 1, (
        "initial emit must be a one-shot — further ticks must not re-emit"
    )


def test_emit_initial_state_pushes_index_zero_envelope() -> None:
    """Story 6.7 AC1 (legacy push path — retained for coverage). The
    production wiring uses `build_initial_envelope` + `task.queue_frames`
    (see bot.py), but this test guards the push-side mechanism in
    isolation in case a future refactor needs to revive it. Calling
    `emit_initial_state()` from `on_first_participant_joined` directly
    is incorrect (the StartFrame hasn't propagated → pipecat
    `_check_started` rejects the push with an ERROR log) — see
    `build_initial_envelope`'s docstring for the full rationale.
    """
    checkpoints = _make_checkpoints(6)
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        await manager.emit_initial_state()

    _run(_drive())

    envelopes = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "checkpoint_advanced"
    ]
    assert len(envelopes) == 1
    data = envelopes[0].message["data"]
    assert data["index"] == 0
    assert data["total"] == 6
    assert data["checkpoint_id"] == "cp0"
    assert data["next_hint"] == "hint 0"
    # Index MUST stay at 0 — this is an informational push, not an advance.
    assert manager._index == 0


# ============================================================
# Story 6.6 review patches — added 2026-05-18
# ============================================================


# ============================================================
# Story 6.8 Phase 2 — COHERENCE_CHARTER threaded through every swap
# (AC6 + AC7 + AC8)
# ============================================================


def test_coherence_charter_appears_in_every_system_instruction_swap() -> None:
    """Story 6.8 Phase 2 AC8 — the COHERENCE_CHARTER must appear:
      - in the composed system_instruction after EVERY checkpoint advance
      - EXACTLY ONCE per swap (no accidental duplication on subsequent advances)
      - BETWEEN `base_prompt` and `prompt_segment` (positional ordering matters)

    The init-time charter injection is owned by `bot.py` (the manager
    only writes to `_settings.system_instruction` on the FIRST advance),
    so the "after init" assertion is left to the bot-wiring test below.
    """
    # 4-checkpoint scenario → 3 advances available.
    checkpoints = _make_checkpoints(4)
    manager, _classifier, _tracker, stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints,
        classify_responses=[True, True, True],
        coherence_charter="CHARTER.",
    )
    _capture_pushed(manager)

    async def _drive() -> None:
        # Advance 1: cp0 → cp1.
        await manager.process_frame(
            _make_user_frame("first."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        post_advance_1 = stub_llm._settings.system_instruction
        assert "CHARTER." in post_advance_1
        assert post_advance_1.count("CHARTER.") == 1
        # Positional ordering — charter sits between base and segment.
        base_idx = post_advance_1.index("BASE PROMPT.")
        charter_idx = post_advance_1.index("CHARTER.")
        segment_idx = post_advance_1.index("prompt segment 1")
        assert base_idx < charter_idx < segment_idx, (
            f"charter must sit BETWEEN base_prompt and prompt_segment; "
            f"got base@{base_idx} charter@{charter_idx} segment@{segment_idx}"
        )

        # Advance 2: cp1 → cp2.
        await manager.process_frame(
            _make_user_frame("second."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        post_advance_2 = stub_llm._settings.system_instruction
        assert "CHARTER." in post_advance_2
        assert post_advance_2.count("CHARTER.") == 1, (
            "charter must appear EXACTLY ONCE per swap — accidental "
            "duplication would bloat the prompt by ~200 tokens per turn"
        )
        assert "prompt segment 2" in post_advance_2

        # Advance 3: cp2 → cp3.
        await manager.process_frame(
            _make_user_frame("third."), FrameDirection.DOWNSTREAM
        )
        await _drain(manager)
        post_advance_3 = stub_llm._settings.system_instruction
        assert "CHARTER." in post_advance_3
        assert post_advance_3.count("CHARTER.") == 1
        assert "prompt segment 3" in post_advance_3

    _run(_drive())


def test_warn_on_duplicate_charter_in_composed_prompt() -> None:
    """Story 6.8 Phase 2 AC15 box 3 — if a future refactor accidentally
    causes the charter to appear twice in the composed prompt (e.g. by
    pre-pending it inside `base_prompt` AND letting the swap add it
    again), the smoke-gate operator should see a `WARNING: prompt
    contains duplicate COHERENCE_CHARTER` log line in journalctl.

    Forge the duplication by pre-embedding the charter into base_prompt;
    on the first advance, the swap appends another copy → guard fires.
    """
    from loguru import logger as loguru_logger

    checkpoints = _make_checkpoints(3)
    # Pre-embed charter in base_prompt → duplication after swap.
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        checkpoints=checkpoints,
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
        "expected WARNING log line for duplicate COHERENCE_CHARTER; "
        f"got: {captured_logs}"
    )


def test_terminal_turn_lock_serializes_concurrent_invocations() -> None:
    """D1 review patch — the terminal-turn preemptive path serializes
    via `_terminal_turn_lock`. Two finalized TranscriptionFrames
    arriving back-to-back on a terminal turn must both complete their
    classifier verdict + meter update atomically; the second invocation
    must wait for the first to release the lock.

    This protects against the race where the second invocation's
    `_schedule_classification` would cancel the first task's awaited
    gather, swallow the `CancelledError`, and leave `pt.is_hanging_up=False`
    — silently breaking the Dev#7 suppression contract."""
    # Build a real PatienceTracker so `is_hanging_up`, `patience`, and
    # `fail_penalty` properties return real values (a MagicMock would
    # make `is_terminal_turn` evaluate to False because the meter math
    # returns Mock objects).
    tracker = PatienceTracker(
        initial_patience=15,
        fail_penalty=-15,  # one fail zeroes the meter → terminal turn
        silence_penalty=-10,
        recovery_bonus=0,
        silence_prompt_seconds=6.0,
        silence_hangup_seconds=10.0,
        escalation_thresholds=[10, 0],
        total_checkpoints=3,
    )

    # First turn: classifier returns False → meter to 0, hangup scheduled.
    # Second turn: should observe hangup-in-progress and suppress.
    manager, _classifier, _tracker, _stub_llm, _ctx = _make_manager(
        patience_tracker=tracker,
        classify_responses=[False, False],
        classify_delay=0.02,  # give the second frame time to arrive mid-await
    )
    captured = _capture_pushed(manager)

    async def _drive() -> None:
        # Fire two terminal-turn frames almost simultaneously. Without
        # the lock, the second's `_schedule_classification` would cancel
        # the first task before its `apply_exchange_outcome(False)`
        # could fire, and `is_hanging_up` would stay False.
        task1 = asyncio.create_task(
            manager.process_frame(_make_user_frame("first."), FrameDirection.DOWNSTREAM)
        )
        await asyncio.sleep(0)  # yield once so task1 starts
        task2 = asyncio.create_task(
            manager.process_frame(
                _make_user_frame("second."), FrameDirection.DOWNSTREAM
            )
        )
        await asyncio.gather(task1, task2, return_exceptions=True)
        # Drain any remaining classifier task.
        if manager._in_flight is not None:
            await asyncio.gather(manager._in_flight, return_exceptions=True)
        # Drain the tracker's hangup task too — otherwise pytest sees
        # "Task was destroyed but it is pending!" warnings.
        if tracker._hang_up_task is not None and not tracker._hang_up_task.done():
            tracker._hang_up_task.cancel()
            await asyncio.gather(tracker._hang_up_task, return_exceptions=True)

    _run(_drive())

    # User-visible invariant: NEITHER user `TranscriptionFrame` should
    # reach downstream. The first turn's verdict zeroes the meter
    # (hangup scheduled mid-apply_outcome). The lock then forces the
    # second turn to wait; on lock acquire it re-checks `is_hanging_up`,
    # finds True, and suppresses without classifying. Without the lock,
    # the first frame leaks (its task cancelled before apply_outcome
    # could fire) and the LLM produces a parallel response that lands
    # between the user's last turn and the hangup exit line — the
    # disjointed UX Dev#7 was meant to eliminate.
    #
    # NOTE — `tracker.is_hanging_up` is NOT asserted here because
    # `_run_hang_up`'s `finally` block clears the flag after the
    # safety EndFrame is pushed (the call is over, the flag's lifetime
    # is bounded by the hangup task). By the time the test drains the
    # task, the flag has rolled back to False. The captured-frames
    # assertion is the durable, user-visible invariant.
    forwarded_user_frames = [f for f in captured if isinstance(f, TranscriptionFrame)]
    assert len(forwarded_user_frames) == 0, (
        f"Terminal-turn lock failed: expected ZERO user TranscriptionFrames "
        f"forwarded downstream (both should be suppressed per Dev#7), got "
        f"{len(forwarded_user_frames)}. Without the lock, the first turn's "
        f"task is cancelled by the second's _schedule_classification before "
        f"its apply_exchange_outcome runs, so the first frame leaks to the "
        f"LLM and produces a parallel response that lands between the user's "
        f"last turn and the hangup exit line."
    )
