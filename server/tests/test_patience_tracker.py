"""Story 6.4 — Tests for PatienceTracker FrameProcessor (AC1, AC7, AC8, AC10)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    EndFrame,
    Frame,
    MetricsFrame,
    OutputTransportMessageFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

import pipeline.patience_tracker as pt_mod
from pipeline.patience_tracker import PatienceTracker

# ---------- helpers ----------


def _run(coro):
    """Single-event-loop runner matching the EmotionEmitter test pattern."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _easy_kwargs(**overrides: Any) -> dict[str, Any]:
    """The Waiter / easy-difficulty PatienceTracker kwargs. Mirrors the
    full 8-field config shape `resolve_patience_config` returns for
    `waiter_easy_01` so tests cover the production constructor surface
    (Deviation #15). The 4 dormant fields (`fail_penalty`,
    `recovery_bonus`, `silence_hangup_seconds`, `escalation_thresholds`)
    are stored on the instance but not applied to behavior in Story
    6.4; passing them here exercises the storage path.
    """
    base = dict(
        initial_patience=100,
        fail_penalty=-15,
        silence_penalty=-10,
        recovery_bonus=5,
        silence_prompt_seconds=6.0,
        silence_hangup_seconds=10.0,
        escalation_thresholds=[75, 50, 25, 0],
        total_checkpoints=6,
    )
    base.update(overrides)
    return base


def _capture_pushed(tracker: PatienceTracker) -> list[Frame]:
    captured: list[Frame] = []

    async def _recorder(frame: Frame, direction: FrameDirection) -> None:
        captured.append(frame)

    tracker.push_frame = _recorder  # type: ignore[assignment]
    return captured


def _shrink_timers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shrink ladder anchors + post-emit delays so tests run in ~300 ms.

    Windows asyncio.sleep granularity is ~15 ms, so we scale anchors
    generously above that floor: stage 1 at 50 ms, stage 3 at 150 ms.
    Test sleeps land in 50 ms windows between stages.
    """
    monkeypatch.setattr(pt_mod, "_LADDER_IMPATIENCE_AT", 0.05)
    monkeypatch.setattr(pt_mod, "_POST_PROMPT_ANGER_DELAY", 0.05)
    monkeypatch.setattr(pt_mod, "_POST_ANGER_HANGUP_DELAY", 0.05)
    monkeypatch.setattr(pt_mod, "_PROMPT_PLAYBACK_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(pt_mod, "_HANG_UP_PRE_TTS_DELAY", 0.01)
    monkeypatch.setattr(pt_mod, "_HANG_UP_CLIENT_DRAIN_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(pt_mod, "_HANG_UP_TTS_TIMEOUT_SECONDS", 0.5)


def _fast_easy(**overrides: Any) -> dict[str, Any]:
    """Easy kwargs with ms-scale silence_prompt + silence_hangup."""
    fast = dict(silence_prompt_seconds=0.1)
    fast.update(overrides)
    return _easy_kwargs(**fast)


async def _drain(tracker: PatienceTracker) -> None:
    """Wait for the ladder + hang-up tasks to complete."""
    for _ in range(3):
        await asyncio.sleep(0)
    silence_task = tracker._silence_task
    if silence_task is not None and not silence_task.done():
        await asyncio.gather(silence_task, return_exceptions=True)
    hang_up_task = tracker._hang_up_task
    if hang_up_task is not None and not hang_up_task.done():
        await asyncio.gather(hang_up_task, return_exceptions=True)


def _make_transcription(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(
        text=text,
        user_id="user",
        timestamp="2026-05-12T12:00:00Z",
        finalized=True,
    )


# ---------- Test 1: pass-through is total ----------


def test_process_frame_is_pass_through_for_all_observed_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    frames: list[Frame] = [
        _make_transcription("hello"),
        BotStoppedSpeakingFrame(),
        UserStartedSpeakingFrame(),
        # An irrelevant frame proves the pass-through is total, not
        # branched by frame type.
        MetricsFrame(data=[]),
    ]

    async def _drive() -> None:
        for f in frames:
            await tracker.process_frame(f, FrameDirection.DOWNSTREAM)
        await _drain(tracker)
        await tracker.cleanup()

    _run(_drive())

    for f in frames:
        assert f in captured, f"frame {type(f).__name__} must be forwarded downstream"


# ---------- Test 2: 3-s impatience emit ----------


def test_three_second_impatience_emit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`playback_idle` → after 3 s, ONE impatience@0.5 envelope is
    pushed and no further emission fires before the stage-2 prompt
    window opens.
    """
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_easy_kwargs(silence_prompt_seconds=2.0))
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.handle_playback_idle()
        # Past stage 1 (50 ms) but well short of stage 2 (2.0 s).
        await asyncio.sleep(0.10)
        envelopes = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
        ]
        assert len(envelopes) == 1
        assert envelopes[0].message["data"] == {
            "emotion": "impatience",
            "intensity": 0.5,
        }
        await _drain(tracker)

    _run(_drive())


# ---------- Test 3: 6-s verbal prompt ----------


def test_six_second_verbal_prompt_pushes_tts_and_second_impatience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.handle_playback_idle()
        # Past stage 2 (100 ms scaled) but short of stage 3 (150 ms).
        await asyncio.sleep(0.13)

        tts_speak = [f for f in captured if isinstance(f, TTSSpeakFrame)]
        assert len(tts_speak) == 1
        assert tts_speak[0].text == "Hello? Are you still there?"

        emotion_envelopes = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
        ]
        impatience = [
            e for e in emotion_envelopes if e.message["data"]["emotion"] == "impatience"
        ]
        assert len(impatience) == 2
        intensities = sorted(e.message["data"]["intensity"] for e in impatience)
        assert intensities == [0.5, 0.7]

        await _drain(tracker)

    _run(_drive())


# ---------- Test 4: 8-s anger emit ----------


def test_eight_second_anger_emit(monkeypatch: pytest.MonkeyPatch) -> None:
    _shrink_timers(monkeypatch)
    # Make stage 4 slow so the assertion can land between stage 3
    # (anger emitted) and stage 4 (hang-up not yet).
    monkeypatch.setattr(pt_mod, "_POST_ANGER_HANGUP_DELAY", 2.0)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.handle_playback_idle()
        # Past stage 2 (100 ms scaled prompt anchor) — wait for the
        # ladder to push the prompt TTSSpeakFrame.
        await asyncio.sleep(0.15)
        # Simulate the prompt's client-confirmed playback_idle to
        # release the stage 2 → stage 3 wait.
        tracker.handle_playback_idle()
        # Past stage 3 (50 ms post-prompt delay) but short of stage 4.
        await asyncio.sleep(0.15)

        anger = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
            and f.message["data"]["emotion"] == "anger"
        ]
        assert len(anger) == 1
        assert anger[0].message["data"]["intensity"] == 0.8

        await _drain(tracker)

    _run(_drive())


# ---------- Test 5: 10-s silence hang-up full sequence ----------


def test_ten_second_silence_hang_up_full_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The strict order: hang_up_warning → TTSSpeakFrame → BSF (synthetic)
    → call_end → EndFrame.
    """
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.handle_playback_idle()
        # Stage 2 prompt push happens at ~100 ms (scaled
        # silence_prompt_seconds). The ladder then waits for the
        # prompt's playback_idle before stages 3-4 count down.
        await asyncio.sleep(0.15)
        # Simulate the prompt's client-confirmed playback_idle.
        tracker.handle_playback_idle()
        # Past stages 3 + 4 (50 ms each scaled) — hang-up scheduled.
        await asyncio.sleep(0.20)
        # Synthesise the bot-stopped after the hang-up TTSSpeakFrame so
        # the exit-line wait releases (still routed through the frame
        # path because that's what the hang-up sequence awaits).
        assert tracker._hang_up_in_progress
        await tracker.process_frame(
            BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM
        )
        await _drain(tracker)

    _run(_drive())

    hang_up_warnings = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "hang_up_warning"
    ]
    assert len(hang_up_warnings) == 1
    assert hang_up_warnings[0].message["data"]["seconds_remaining"] == 5

    # The hang-up TTSSpeakFrame uses the silence exit line, not the
    # inappropriate one.
    tts_speak = [
        f for f in captured if isinstance(f, TTSSpeakFrame) and "Goodbye" in f.text
    ]
    assert len(tts_speak) == 1
    assert tts_speak[0].text == "I don't have time for this. Goodbye."

    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert len(call_end) == 1
    data = call_end[0].message["data"]
    assert data["reason"] == "character_hung_up"
    assert data["checkpoints_passed"] == 0
    assert data["total_checkpoints"] == 6
    assert 0 <= data["survival_pct"] <= 100

    end_frames = [f for f in captured if isinstance(f, EndFrame)]
    assert len(end_frames) == 1

    # Order: hang_up_warning < TTSSpeakFrame < (BSF beat — synthesised
    # by the test harness) < call_end < EndFrame. The BSF gate is what
    # releases the `_speaking_done` event so `call_end` can fire; if a
    # refactor accidentally inverted that ordering, the test below
    # would fail loud.
    idx_warning = next(i for i, f in enumerate(captured) if f is hang_up_warnings[0])
    idx_tts = next(i for i, f in enumerate(captured) if f is tts_speak[0])
    idx_end_env = next(i for i, f in enumerate(captured) if f is call_end[0])
    idx_end_frame = next(i for i, f in enumerate(captured) if f is end_frames[0])
    # Find the captured `bot_speaking_ended` envelope pushed when the
    # test injected its synthetic BotStoppedSpeakingFrame.
    bot_speaking_ended = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "bot_speaking_ended"
    ]
    # The BSF beat may not have been captured if the test's synthetic
    # frame was forwarded by pass-through but not re-pushed as envelope
    # by a downstream consumer — at minimum the strict envelope order
    # below MUST hold.
    assert idx_warning < idx_tts < idx_end_env < idx_end_frame
    if bot_speaking_ended:
        idx_bse = next(i for i, f in enumerate(captured) if f is bot_speaking_ended[0])
        assert idx_tts < idx_bse < idx_end_env, (
            "bot_speaking_ended envelope must arrive between the exit-line "
            "TTSSpeakFrame and the call_end envelope (the BSF beat is what "
            "releases the _speaking_done wait so call_end can fire)"
        )


# ---------- Test 6: user speech cancels the timer ----------


def test_user_speech_cancels_silence_timer_no_restart_without_bsf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User speech cancels the ladder. A new BSF is required to restart it."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.handle_playback_idle()
        # Cancel mid-stage-1 (well before the 50 ms anchor).
        await asyncio.sleep(0.005)
        await tracker.process_frame(
            _make_transcription("I am ordering food."),
            FrameDirection.DOWNSTREAM,
        )
        # Wait well past the original stage 4 timing — the cancelled
        # task should not emit anything else.
        await asyncio.sleep(0.30)

        emotion_envelopes = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
        ]
        # The TranscriptionFrame arrived mid-stage-1 (before the 3 ms
        # anchor), so no emit should have fired before cancellation.
        assert emotion_envelopes == []

        tts_speak = [f for f in captured if isinstance(f, TTSSpeakFrame)]
        assert tts_speak == []
        end_frames = [f for f in captured if isinstance(f, EndFrame)]
        assert end_frames == []

        await _drain(tracker)

    _run(_drive())


# ---------- Test 7: abuse classifier triggers `inappropriate_content` ----------


def test_abuse_classifier_triggers_inappropriate_content_hangup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(
        **_fast_easy(abuse_classifier=lambda text: "kill" in text.lower())
    )
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        # No prior BotStoppedSpeakingFrame — abuse can land on the
        # very first user turn.
        await tracker.process_frame(
            _make_transcription("I will kill you."),
            FrameDirection.DOWNSTREAM,
        )
        # Give the hang-up task a beat to push the exit-line TTSSpeakFrame.
        await asyncio.sleep(0.02)
        # Synthesise the bot-stopped to release the exit-line wait.
        await tracker.process_frame(
            BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM
        )
        await _drain(tracker)

    _run(_drive())

    # The exit line is the inappropriate-content variant.
    tts_speak = [
        f
        for f in captured
        if isinstance(f, TTSSpeakFrame) and f.text == "I'm done with this. Goodbye."
    ]
    assert len(tts_speak) == 1

    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert len(call_end) == 1
    assert call_end[0].message["data"]["reason"] == "inappropriate_content"

    end_frames = [f for f in captured if isinstance(f, EndFrame)]
    assert len(end_frames) == 1


# ---------- Test 8: idempotent hang-up ----------


def test_schedule_hang_up_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two _schedule_hang_up calls in quick succession → ONE EndFrame."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        tracker._schedule_hang_up("character_hung_up")
        # Release the exit-line wait.
        await asyncio.sleep(0.02)
        await tracker.process_frame(
            BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM
        )
        await _drain(tracker)

    _run(_drive())

    end_frames = [f for f in captured if isinstance(f, EndFrame)]
    assert len(end_frames) == 1, "second _schedule_hang_up must be a no-op"


# ---------- Test 9: BotStoppedSpeakingFrame pushes bot_speaking_ended ----------


def test_bot_stopped_speaking_pushes_bot_speaking_ended_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`BotStoppedSpeakingFrame` arrival pushes a `bot_speaking_ended`
    envelope downstream so the client can arm its
    `playback_idle`-upstream gate. Without this gate, the client would
    treat any 600 ms intra-utterance Cartesia pause as end-of-turn and
    start the silence ladder prematurely.
    """
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        await tracker.process_frame(
            BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM
        )

    _run(_drive())

    bot_speaking_ended = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "bot_speaking_ended"
    ]
    assert len(bot_speaking_ended) == 1


# ---------- Test 10: handle_playback_idle ignored during hang-up ----------


def test_handle_playback_idle_ignored_during_hang_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client-driven playback_idle during the hang-up sequence MUST NOT
    restart the silence ladder — the call is ending."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    _capture_pushed(tracker)

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        await asyncio.sleep(0.02)
        # Simulate the client sending playback_idle (e.g. it had a
        # silence window from some earlier audio) — should be ignored.
        tracker.handle_playback_idle()
        assert tracker._silence_task is None, (
            "silence ladder must not start during hang-up"
        )
        await tracker.process_frame(
            BotStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM
        )
        await _drain(tracker)

    _run(_drive())


# ---------- Test 10: handle_playback_idle skips on _self_speaking ----------


def test_handle_playback_idle_skips_when_self_speaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When PatienceTracker has just pushed its own stage-2 prompt
    TTSSpeakFrame, the prompt's eventual playback_idle MUST clear
    the flag and release the stage-3 wait — but NOT spawn a fresh
    ladder. The running ladder continues through stages 3-4
    uninterrupted.
    """
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    _capture_pushed(tracker)

    async def _drive() -> None:
        # Drive the ladder through stage 2 organically: send a
        # playback_idle to start the ladder, then wait past the
        # stage-2 anchor so the prompt is pushed and `_self_speaking`
        # is set inside the coroutine.
        tracker.handle_playback_idle()
        await asyncio.sleep(0.13)  # past stage 2 (100 ms scaled)
        assert tracker._self_speaking is True, (
            "stage 2 should have set the self-speaking flag"
        )
        original_task = tracker._silence_task
        assert original_task is not None

        # Now simulate the prompt's client-confirmed playback_idle:
        # clears the flag, releases the stage-3 wait, but does NOT
        # cancel/restart the ladder.
        tracker.handle_playback_idle()

        assert tracker._self_speaking is False
        assert tracker._silence_task is original_task, (
            "original ladder must continue through stages 3-4"
        )

        await _drain(tracker)

    _run(_drive())


# ---------- Test 11: stage 1 re-emits after cancel/restart (regression) -----


def test_stage_1_re_emits_after_ladder_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stage 1 MUST emit on EVERY ladder run (not just the first).
    Regression for the original implementation which carried a
    `_last_emitted_emotion` field across runs and skipped the stage-1
    emit when the previous run's last emit was also `impatience` —
    that caused the user to perceive `satisfaction → anger` directly,
    skipping the intermediate `impatience@0.5` step.
    """
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        # First ladder: fires stage 1.
        tracker.handle_playback_idle()
        await asyncio.sleep(0.10)

        first_impatience = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
            and f.message["data"]["emotion"] == "impatience"
            and f.message["data"]["intensity"] == 0.5
        ]
        assert len(first_impatience) == 1, "first ladder must emit stage 1"

        # User speaks → cancel.
        await tracker.process_frame(
            _make_transcription("I want pasta."), FrameDirection.DOWNSTREAM
        )
        # Drain the cancelled task.
        prior = tracker._silence_task
        if prior is not None:
            await asyncio.gather(prior, return_exceptions=True)

        # Second ladder (next bot turn ended): MUST re-emit stage 1.
        tracker.handle_playback_idle()
        await asyncio.sleep(0.10)

        second_impatience = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
            and f.message["data"]["emotion"] == "impatience"
            and f.message["data"]["intensity"] == 0.5
        ]
        assert len(second_impatience) == 2, (
            "second ladder must also emit stage 1 — debounce must reset"
        )

        await _drain(tracker)

    _run(_drive())


# ---------- Test 13: constructor rejects initial_patience <= 0 (P5) ----------


def test_constructor_rejects_non_positive_initial_patience() -> None:
    """A YAML `patience_start: 0` (or negative) override would silently
    degrade the survival-percent denominator. Constructor must raise
    instead of producing a degenerate tracker."""
    with pytest.raises(ValueError, match="initial_patience"):
        PatienceTracker(**_easy_kwargs(initial_patience=0))
    with pytest.raises(ValueError, match="initial_patience"):
        PatienceTracker(**_easy_kwargs(initial_patience=-1))


# ---------- Test 14: interim TranscriptionFrame does NOT cancel ladder (P6) -


def test_interim_transcription_does_not_cancel_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-finalized TranscriptionFrame (`finalized=False`) is the
    STT's interim partial-result emission. It must NOT cancel the
    silence ladder — only finalized text confirms the user has
    actually completed a turn. Without this gate, every partial
    transcription mid-pause would reset the ladder and the user could
    never trip impatience."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_easy_kwargs(silence_prompt_seconds=2.0))
    captured = _capture_pushed(tracker)

    interim = TranscriptionFrame(
        text="I want",
        user_id="user",
        timestamp="2026-05-12T12:00:00Z",
        finalized=False,
    )

    async def _drive() -> None:
        tracker.handle_playback_idle()
        # Halfway through stage 1: interim transcription arrives.
        await asyncio.sleep(0.025)
        await tracker.process_frame(interim, FrameDirection.DOWNSTREAM)
        # Wait past stage 1 — impatience MUST still fire because the
        # interim didn't cancel the ladder.
        await asyncio.sleep(0.10)

        impatience = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
            and f.message["data"]["emotion"] == "impatience"
        ]
        assert len(impatience) == 1, (
            "interim TranscriptionFrame must not cancel the ladder"
        )

        await _drain(tracker)

    _run(_drive())


# ---------- Test 15: empty-text finalized TranscriptionFrame cancels (P9) ---


def test_empty_text_finalized_transcription_still_cancels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty-text finalized TranscriptionFrame is an STT artifact
    (whitespace-only result, noise burst). It MUST cancel the ladder
    defensively — the user clearly made some sound, even if the STT
    couldn't transcribe it."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.handle_playback_idle()
        await asyncio.sleep(0.005)
        # Empty-text but finalized — must still cancel.
        await tracker.process_frame(
            _make_transcription("   "),  # whitespace-only
            FrameDirection.DOWNSTREAM,
        )
        # Past stage 1 — no impatience emission should have fired
        # because the ladder was cancelled before the anchor.
        await asyncio.sleep(0.10)

        emotion = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
        ]
        assert emotion == [], "empty-text frame must cancel the ladder"
        assert tracker._silence_task is None

        await _drain(tracker)

    _run(_drive())


# ---------- Test 16: abuse_classifier exception is contained (P7) ----------


def test_abuse_classifier_exception_does_not_crash_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.6 will inject an LLM-backed classifier — defensive
    try/except so a transient classifier failure (network, parse
    error) is logged and swallowed, not allowed to propagate into the
    pipeline and kill the call."""
    _shrink_timers(monkeypatch)

    def _raising(_text: str) -> bool:
        raise RuntimeError("simulated classifier outage")

    tracker = PatienceTracker(**_fast_easy(abuse_classifier=_raising))
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        # The classifier raises during the abuse-check — `process_frame`
        # must swallow it and return normally.
        await tracker.process_frame(
            _make_transcription("hello"), FrameDirection.DOWNSTREAM
        )
        await _drain(tracker)

    _run(_drive())

    # No hang-up envelopes should have fired — the classifier exception
    # was contained.
    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert call_end == []


# ---------- Test 17: duplicate playback_idle does not spawn parallel (P3) --


def test_duplicate_playback_idle_does_not_spawn_parallel_ladders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SCTP retransmits / fast back-to-back client emits can deliver
    `playback_idle` twice for the same bot turn. A second call while
    a ladder is already running MUST be ignored — without the guard,
    the cancel-and-restart would briefly run two coroutines on the
    event loop and re-fire stage 1 from zero."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_easy_kwargs(silence_prompt_seconds=2.0))
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.handle_playback_idle()
        first_task = tracker._silence_task
        assert first_task is not None

        # Duplicate envelope mid-stage-1 — must be ignored.
        await asyncio.sleep(0.005)
        tracker.handle_playback_idle()

        assert tracker._silence_task is first_task, (
            "duplicate playback_idle must NOT cancel-restart the ladder"
        )

        # Wait past stage 1 — exactly ONE impatience emit should fire.
        await asyncio.sleep(0.10)
        impatience = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
            and f.message["data"]["emotion"] == "impatience"
            and f.message["data"]["intensity"] == 0.5
        ]
        assert len(impatience) == 1

        await _drain(tracker)

    _run(_drive())


# ---------- Test 18: BSF upstream does NOT emit bot_speaking_ended (P17) ---


def test_upstream_bot_stopped_speaking_does_not_emit_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BSF is canonically downstream. An upstream BSF (e.g. from a
    sniffing test harness or unusual pipecat configuration) must not
    push a spurious `bot_speaking_ended` envelope downstream."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)

    _run(_drive())

    bot_speaking_ended = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "bot_speaking_ended"
    ]
    assert bot_speaking_ended == [], (
        "upstream BSF must NOT push bot_speaking_ended envelope"
    )


# ---------- Test 12: cancel resets self-speaking gate (regression) ----------


def test_cancel_resets_self_speaking_and_prompt_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for the gate-leak bug:
    if the user speaks RIGHT AFTER the stage-2 prompt is pushed (i.e.
    while `_self_speaking` is True and the prompt's playback_idle is
    still in flight), the cancel MUST reset `_self_speaking` AND
    `_prompt_played_event`. Otherwise the next bot turn's playback_idle
    is mis-consumed as 'prompt audio drained' and no new ladder ever
    starts — the user can stay silent forever without seeing impatience
    again.
    """
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    _capture_pushed(tracker)

    async def _drive() -> None:
        # Run the ladder past stage 2 so `_self_speaking` is True.
        tracker.handle_playback_idle()
        await asyncio.sleep(0.13)
        assert tracker._self_speaking is True

        # User speaks → cancel.
        await tracker.process_frame(
            _make_transcription("actually I want pasta."),
            FrameDirection.DOWNSTREAM,
        )
        # Cancel MUST have reset the gate.
        assert tracker._self_speaking is False
        assert tracker._prompt_played_event is None

        # Now the next bot turn ends and the client publishes its
        # playback_idle. This MUST start a fresh ladder (not be
        # routed to the self-speaking branch).
        tracker.handle_playback_idle()
        assert tracker._silence_task is not None

        await _drain(tracker)

    _run(_drive())
