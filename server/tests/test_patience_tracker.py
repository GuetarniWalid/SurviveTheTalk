"""Story 6.4 — Tests for PatienceTracker FrameProcessor (AC1, AC7, AC8, AC10)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
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
    full 9-field config shape `resolve_patience_config` returns for
    `waiter_easy_01` so tests cover the production constructor surface
    (Deviation #15 + Story 6.13 AC3 ladder_impatience_seconds).

    `ladder_impatience_seconds` defaults to 0.05 here (NOT the
    production 4.5 s) because every test calls `_shrink_timers(...)`
    which scales the other ladder anchors down to ms-scale; the
    stage-1 anchor must be in the same range or stage 1 never fires
    inside the test window. Tests that exercise the production
    timing pass `ladder_impatience_seconds=4.5` explicitly.
    """
    base = dict(
        initial_patience=100,
        fail_penalty=-15,
        silence_penalty=-10,
        recovery_bonus=5,
        silence_prompt_seconds=6.0,
        ladder_impatience_seconds=0.05,
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
    generously above that floor: stage 3 at 50 ms, etc. Stage 1
    (`ladder_impatience_seconds`) is now a constructor kwarg (Story
    6.13 AC3) so it's scaled via `_easy_kwargs()`'s default of 0.05 s
    rather than monkeypatching a module constant.
    """
    monkeypatch.setattr(pt_mod, "_POST_PROMPT_ANGER_DELAY", 0.05)
    monkeypatch.setattr(pt_mod, "_POST_ANGER_HANGUP_DELAY", 0.05)
    monkeypatch.setattr(pt_mod, "_PROMPT_PLAYBACK_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(pt_mod, "_HANG_UP_PRE_TTS_DELAY", 0.01)
    monkeypatch.setattr(pt_mod, "_HANG_UP_CLIENT_DRAIN_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(pt_mod, "_HANG_UP_TTS_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(pt_mod, "_HANG_UP_TTS_STALL_DETECT_SECONDS", 0.25)
    monkeypatch.setattr(pt_mod, "_HANG_UP_TTS_RETRY_TIMEOUT_SECONDS", 0.3)


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
        # Turn-taking fix (2026-06-08) — the silence relance is SPOKEN but must
        # NOT enter the LLM conversation memory (otherwise it buffers and merges
        # into the next reply). pipecat drops TTS text whose `append_to_context`
        # is False; PatienceTracker sets it here so the relance can never
        # pollute the transcript.
        assert tts_speak[0].append_to_context is False

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
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
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
    # Story 6.20 AC3 — the real met SET ships in call_end (empty here: no flip).
    assert data["goals_met_indices"] == []
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
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
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
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
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
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)

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
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
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


# ---------- Test 14: interim TranscriptionFrame WITH TEXT cancels ladder ----


def test_interim_transcription_with_text_cancels_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turn-taking fix (2026-06-08 smoke gate) — an interim (non-finalized)
    TranscriptionFrame that carries REAL text means the user has STARTED
    speaking, so it MUST cancel the silence ladder. Otherwise the
    "Hello? Are you still there?" prompt fires over a learner who is still
    forming their answer ("uh, uh, in front of..."). Per server/CLAUDE.md
    §1, a stray cancel only defers the silence hangup by one cycle
    (recoverable); a prompt over live speech is the bad UX."""
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
        # Halfway through stage 1: interim transcription WITH TEXT arrives.
        await asyncio.sleep(0.025)
        await tracker.process_frame(interim, FrameDirection.DOWNSTREAM)
        # Wait past stage 1 — impatience MUST NOT fire because the
        # interim-with-text cancelled the ladder.
        await asyncio.sleep(0.10)

        impatience = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
            and f.message["data"]["emotion"] == "impatience"
        ]
        assert len(impatience) == 0, (
            "interim TranscriptionFrame with text must cancel the ladder"
        )

        await _drain(tracker)

    _run(_drive())


# ---------- Test 14b: EMPTY interim TranscriptionFrame does NOT cancel ------


def test_interim_transcription_empty_does_not_cancel_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interim TranscriptionFrame with NO real text (whitespace / noise
    artifact) must NOT cancel the ladder — otherwise ambient noise would
    reset the timer forever and a genuinely silent user would never be
    prompted or hung up on."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_easy_kwargs(silence_prompt_seconds=2.0))
    captured = _capture_pushed(tracker)

    interim_empty = TranscriptionFrame(
        text="   ",
        user_id="user",
        timestamp="2026-05-12T12:00:00Z",
        finalized=False,
    )

    async def _drive() -> None:
        tracker.handle_playback_idle()
        await asyncio.sleep(0.025)
        await tracker.process_frame(interim_empty, FrameDirection.DOWNSTREAM)
        # Past stage 1 — impatience MUST still fire (the empty interim
        # did not cancel).
        await asyncio.sleep(0.10)

        impatience = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
            and f.message["data"]["emotion"] == "impatience"
        ]
        assert len(impatience) == 1, (
            "empty interim TranscriptionFrame must not cancel the ladder"
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


def test_downstream_bot_stopped_speaking_does_not_emit_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pipecat 0.0.108's BaseOutputTransport pushes BSF in BOTH
    directions — the downstream copy goes into the sink (output is
    the last processor; `_next` is None), the upstream copy travels
    back up the pipeline and is what PatienceTracker observes.

    The downstream BSF is a no-op for our purposes. A test harness
    that injects BSF DOWNSTREAM (e.g. a sniffer middleware between
    upstream processors) must NOT cause a spurious envelope.

    See Déviation #28 (2026-05-15) — the original Story 6.4
    implementation had the direction check inverted; this test
    used to assert the symmetric case.
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
    assert bot_speaking_ended == [], (
        "downstream BSF must NOT push bot_speaking_ended envelope"
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


# ---------- Test 19: Déviation #28 contract test — direction parity ----------


def test_BSF_direction_matches_pipecat_emission_routing():
    """Cross-reference contract: PatienceTracker's
    `BotStoppedSpeakingFrame` direction check MUST match the
    direction `pipecat.transports.base_output.BaseOutputTransport`
    actually emits.

    Background: the original Story 6.4 implementation checked
    `direction == FrameDirection.DOWNSTREAM` for BSF. Pipecat 0.0.108
    actually pushes BSF in BOTH directions from
    `_bot_stopped_speaking()` — but the downstream copy goes into
    the sink (output is the last processor, `_next is None`), so
    PatienceTracker only ever sees the UPSTREAM copy as it travels
    back through the pipeline. The check never fired in prod for 2
    days; no escalation log ever surfaced in journalctl. The
    existing unit tests passed because they sent BSF DOWNSTREAM
    directly to `process_frame`, matching the (wrong) impl. Two
    self-consistent layers of wrong silently broke the silence
    ladder.

    This test breaks that self-consistency by reading the SOURCE
    TEXT of pipecat's `_bot_stopped_speaking` AND of
    PatienceTracker, and asserting they agree on direction.
    Either of these going out of sync fires the test before
    deploy:
      - A pipecat upgrade that flips BSF routing.
      - An accidental edit to `patience_tracker.py` that reverts
        Déviation #28 (e.g. a future Story author who reads the
        Story 6.4 spec and "fixes" what looks like a typo).

    Source-text matching is fragile (renames break it) but cheap
    and load-bearing — Déviation #28 documents the load-bearing
    invariant explicitly so future readers know to update both
    sides AND this test when pipecat upgrades.
    """
    import inspect

    from pipecat.transports.base_output import BaseOutputTransport

    # (1) pipecat side — locate the `_bot_stopped_speaking` method
    # in the BaseOutputTransport source and confirm it emits BSF
    # with `FrameDirection.UPSTREAM`. (It also emits a downstream
    # copy that goes into the sink; we don't care about that.)
    pipecat_src = inspect.getsource(BaseOutputTransport)
    fn_marker = "async def _bot_stopped_speaking"
    fn_start = pipecat_src.find(fn_marker)
    assert fn_start != -1, (
        "pipecat 0.0.108 structure changed — `_bot_stopped_speaking` no "
        "longer present on `BaseOutputTransport`. Re-verify the BSF "
        "emission contract (Déviation #28) against the new pipecat "
        "version before this test can be trusted again."
    )
    # The method body is short; 1500 chars is a generous slice that
    # always captures both push_frame calls without bleeding into the
    # next method.
    fn_body = pipecat_src[fn_start : fn_start + 1500]
    assert "BotStoppedSpeakingFrame()" in fn_body, (
        "pipecat changed the BSF emission shape — Déviation #28 needs re-verification."
    )
    assert "FrameDirection.UPSTREAM" in fn_body, (
        "pipecat NO LONGER pushes BSF upstream from "
        "`_bot_stopped_speaking`. PatienceTracker's UPSTREAM check "
        "(Déviation #28) is built on this assumption — it MUST be "
        "updated to match pipecat's new routing before this can ship "
        "to prod."
    )

    # (2) Our side — locate the BSF branch in `patience_tracker.py`
    # and confirm we still gate on UPSTREAM. An accidental flip back
    # to DOWNSTREAM would re-introduce the original silent regression.
    pt_src = inspect.getsource(pt_mod)
    bsf_marker = "isinstance(frame, BotStoppedSpeakingFrame)"
    bsf_start = pt_src.find(bsf_marker)
    assert bsf_start != -1, (
        "PatienceTracker source no longer references "
        "`BotStoppedSpeakingFrame` — the silence-ladder arming path "
        "changed. Re-evaluate this contract test against the new shape."
    )
    # 300 chars is enough to capture the `and direction == ...` clause
    # without bleeding into the body of the if.
    branch = pt_src[bsf_start : bsf_start + 300]
    assert "FrameDirection.UPSTREAM" in branch, (
        "PatienceTracker's BSF check no longer gates on UPSTREAM. This "
        "reverts Déviation #28 — silence escalation will be inert in "
        "prod (the original Story 6.4 regression). Re-apply UPSTREAM "
        "or update this test if pipecat routing genuinely changed."
    )


# ============================================================
# Story 6.6 — apply_exchange_outcome + schedule_completion
# ============================================================


def test_apply_exchange_outcome_True_recovers_meter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """initial=100, recovery=+5, current=80 → meter==85."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_easy_kwargs(initial_patience=100, recovery_bonus=5))
    tracker._patience = 80
    tracker.apply_exchange_outcome(True)
    assert tracker._patience == 85


def test_apply_exchange_outcome_True_bounded_at_initial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """recovery cannot overshoot the initial meter ceiling."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_easy_kwargs(initial_patience=100, recovery_bonus=20))
    tracker._patience = 95
    tracker.apply_exchange_outcome(True)
    assert tracker._patience == 100


def test_apply_exchange_outcome_False_applies_fail_penalty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """initial=100, fail=-15, current=80 → meter==65."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_easy_kwargs(initial_patience=100, fail_penalty=-15))
    tracker._patience = 80
    tracker.apply_exchange_outcome(False)
    assert tracker._patience == 65


def test_apply_exchange_outcome_False_floored_at_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fail_penalty cannot push the meter below zero.

    Note: as of Deviation #6 (2026-05-18), reaching zero ALSO schedules
    a `character_hung_up` hangup — drain the spawned task to keep the
    event loop clean. The meter floor assertion is independent of the
    hangup-on-zero behavior (which has its own dedicated test below).
    """
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_easy_kwargs(initial_patience=100, fail_penalty=-20))
    _capture_pushed(tracker)
    tracker._patience = 10

    async def _drive() -> None:
        tracker.apply_exchange_outcome(False)
        assert tracker._patience == 0
        # Drain the hang-up task scheduled by the meter-zero trigger so
        # we don't leak `coroutine was never awaited` warnings.
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())


def test_apply_exchange_outcome_noops_during_hangup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the hang-up sequence is running, exchange outcomes from a
    stale in-flight classifier MUST NOT mutate the meter — the call is
    ending and the meter is no longer authoritative."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    tracker._hang_up_in_progress = True
    tracker._patience = 50
    tracker.apply_exchange_outcome(True)
    assert tracker._patience == 50
    tracker.apply_exchange_outcome(False)
    assert tracker._patience == 50


def test_schedule_completion_speaks_survived_line_and_emits_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`schedule_completion(survival_pct=100)` runs the hang-up coroutine
    with the survived exit line + `reason='survived'` + `survival_pct=100`
    regardless of the current `_patience` value."""
    _shrink_timers(monkeypatch)
    # Deliberate: low _patience to prove the meter-ratio formula is NOT
    # used on the survived path (Deviation #1).
    tracker = PatienceTracker(
        **_fast_easy(
            initial_patience=100,
            hang_up_line_survived="Goodbye, surviving customer.",
        )
    )
    tracker._patience = 5  # would yield survival_pct=5 under the meter ratio
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        # Story 6.7 review (2026-05-20) — CheckpointManager calls
        # `set_checkpoints_passed(total)` immediately before
        # `schedule_completion` on the terminal path. Mirror it here so
        # the envelope assertion below reflects production wiring. Story
        # 6.20 AC3 — it also mirrors the real met SET via
        # `set_goals_met_indices`.
        tracker.set_checkpoints_passed(6)
        tracker.set_goals_met_indices([0, 1, 2, 3, 4, 5])
        tracker.schedule_completion(survival_pct=100)
        await asyncio.sleep(0.02)
        # Release the exit-line wait.
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    tts_speak = [
        f
        for f in captured
        if isinstance(f, TTSSpeakFrame) and f.text == "Goodbye, surviving customer."
    ]
    assert len(tts_speak) == 1, "must speak the survived exit line"

    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert len(call_end) == 1
    data = call_end[0].message["data"]
    assert data["reason"] == "survived"
    assert data["survival_pct"] == 100, (
        "Deviation #1 — survival_pct on the survived path is 100 by "
        "definition, not the meter ratio"
    )
    assert data["checkpoints_passed"] == 6, (
        "Story 6.7 review — survived path must emit the live count "
        "(set by CheckpointManager.set_checkpoints_passed), not the "
        "legacy hardcoded 0 retired 2026-05-20."
    )
    assert data["total_checkpoints"] == 6
    # Story 6.20 AC3 — the REAL met SET ships alongside the count.
    assert data["goals_met_indices"] == [0, 1, 2, 3, 4, 5]


def test_set_checkpoints_passed_threads_through_character_hung_up_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `character_hung_up` mid-call must carry the live passed count
    in `call_end.checkpoints_passed`. Drives the bug discovered in
    Story 6.7 smoke test 2026-05-20 where the legacy hardcoded `0`
    masked partial progress on every non-survived path."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy(initial_patience=10))
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        # Simulate two checkpoint passes before the meter drains.
        tracker.set_checkpoints_passed(1)
        tracker.set_checkpoints_passed(2)
        # Drain the meter to trigger the character_hung_up path.
        tracker._patience = 0
        tracker._schedule_hang_up("character_hung_up")
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert len(call_end) == 1
    data = call_end[0].message["data"]
    assert data["reason"] == "character_hung_up"
    assert data["checkpoints_passed"] == 2, (
        "character_hung_up path must reflect the live count from "
        "set_checkpoints_passed, not the legacy hardcoded 0."
    )
    assert data["total_checkpoints"] == 6


def test_schedule_completion_idempotent_when_hangup_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second `schedule_completion` call while a hang-up is already
    running is swallowed — exactly ONE EndFrame."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.schedule_completion(survival_pct=100)
        # Second call while the first hang-up coroutine is still running.
        tracker.schedule_completion(survival_pct=100)
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    end_frames = [f for f in captured if isinstance(f, EndFrame)]
    assert len(end_frames) == 1, "second schedule_completion must be a no-op"


def test_schedule_hang_up_rejects_unknown_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A future caller passing a typo for `reason` should fail loud, not
    silently fall through to a wrong exit line."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    with pytest.raises(ValueError, match="unknown reason"):
        tracker._schedule_hang_up("not_a_real_reason")


# ============================================================
# Story 6.6 Deviation #6 — meter-at-zero hangup + warning band
# ============================================================


def test_apply_exchange_outcome_emits_warning_at_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the meter falls into the warning band (≤ 25) on a failed
    exchange, a one-shot TTSSpeakFrame is pushed with the
    `patience_warning_line`."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(
        **_fast_easy(
            initial_patience=100,
            fail_penalty=-20,
            patience_warning_line="Hey, last chance, buddy.",
        )
    )
    tracker._patience = 30  # one fail away from the threshold
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.apply_exchange_outcome(False)
        assert tracker._patience == 10
        # `_warning_emitted` flips to True AFTER the push lands (review
        # patch — pre-spawn was the wrong moment because a failed push
        # would otherwise burn the one-shot). Drain the spawned task
        # before asserting.
        if tracker._warning_task is not None:
            await asyncio.gather(tracker._warning_task, return_exceptions=True)
        assert tracker._warning_emitted is True

    _run(_drive())

    warning_frames = [
        f
        for f in captured
        if isinstance(f, TTSSpeakFrame) and f.text == "Hey, last chance, buddy."
    ]
    assert len(warning_frames) == 1, "warning TTSSpeakFrame must be pushed once"
    # Turn-taking fix (2026-06-08) — the patience warning is spoken but must NOT
    # be recorded in the LLM conversation memory (same rationale as the silence
    # relance: a meta-nudge, never merged into the next reply).
    assert warning_frames[0].append_to_context is False


def test_warning_is_one_shot_within_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two failed exchanges in the warning band → exactly ONE warning
    push. The flag persists for the call lifetime."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy(initial_patience=100, fail_penalty=-10))
    tracker._patience = 30
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.apply_exchange_outcome(False)  # 30 → 20 (enters band)
        await asyncio.sleep(0.02)
        tracker.apply_exchange_outcome(False)  # 20 → 10 (still in band)
        await asyncio.sleep(0.02)

    _run(_drive())

    warning_frames = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(warning_frames) == 1, "warning must fire once, not twice"


def test_recovery_after_warning_does_not_re_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """recovery_bonus pulling the meter back above the threshold does
    NOT clear `_warning_emitted` — a subsequent dip below the threshold
    must NOT re-fire the warning."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(
        **_fast_easy(initial_patience=100, fail_penalty=-10, recovery_bonus=20)
    )
    tracker._patience = 30
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.apply_exchange_outcome(False)  # 30 → 20 — warning fires
        # Drain the warning task so the post-push flag-flip lands.
        if tracker._warning_task is not None:
            await asyncio.gather(tracker._warning_task, return_exceptions=True)
        assert tracker._warning_emitted is True
        tracker.apply_exchange_outcome(True)  # 20 → 40 — back above
        assert tracker._warning_emitted is True, "must NOT clear on recovery"
        tracker.apply_exchange_outcome(False)  # 40 → 30
        tracker.apply_exchange_outcome(False)  # 30 → 20 — back in band
        if tracker._warning_task is not None:
            await asyncio.gather(tracker._warning_task, return_exceptions=True)

    _run(_drive())

    warning_frames = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(warning_frames) == 1, (
        "warning is one-shot per call; recovery must not re-arm it"
    )


def test_apply_exchange_outcome_schedules_hangup_at_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the meter hits zero on a failed exchange, schedule
    character_hung_up with the silence exit line. NO warning fires on
    the same call (the hangup supersedes it)."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(
        **_fast_easy(
            initial_patience=100,
            fail_penalty=-100,  # one shot to zero
            hang_up_line_silence="OK that's it, goodbye.",
            patience_warning_line="Last chance.",
        )
    )
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.apply_exchange_outcome(False)
        assert tracker._patience == 0
        assert tracker._hang_up_in_progress is True
        await asyncio.sleep(0.02)
        # Release the exit-line wait so the hang-up coroutine can
        # finish and emit call_end.
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    # No warning was pushed — the hangup-at-zero branch returned early
    # before the warning band check.
    warning_frames = [
        f for f in captured if isinstance(f, TTSSpeakFrame) and "Last chance" in f.text
    ]
    assert warning_frames == [], "warning must NOT fire when meter zeroes in one step"

    # The hangup spoke the silence exit line, not the survived one.
    exit_frames = [
        f
        for f in captured
        if isinstance(f, TTSSpeakFrame) and f.text == "OK that's it, goodbye."
    ]
    assert len(exit_frames) == 1, "silence exit line must play on meter-zero hangup"

    # call_end envelope with reason character_hung_up.
    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert len(call_end) == 1
    assert call_end[0].message["data"]["reason"] == "character_hung_up"


def test_warning_does_NOT_fire_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful exchange that keeps the meter inside the warning
    band (e.g. user is at 20, recovery=+0) must NOT fire the warning —
    only failures trigger the band check."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy(initial_patience=100, recovery_bonus=0))
    tracker._patience = 20
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.apply_exchange_outcome(True)  # success, meter stays at 20
        await asyncio.sleep(0.02)

    _run(_drive())

    warning_frames = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert warning_frames == [], "warning must not fire on success path"
    assert tracker._warning_emitted is False


def test_meter_zero_hangup_idempotent_with_in_progress_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the meter-zero hangup is scheduled, a second failed
    exchange (e.g. a stale in-flight classifier verdict landing late)
    must be swallowed — `_hang_up_in_progress` guards both the meter
    mutation AND the hangup scheduling."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy(initial_patience=100, fail_penalty=-100))
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.apply_exchange_outcome(False)  # meter → 0, hangup scheduled
        assert tracker._hang_up_in_progress is True
        # Second call while hangup is running — must be a no-op.
        tracker.apply_exchange_outcome(False)
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    end_frames = [f for f in captured if isinstance(f, EndFrame)]
    assert len(end_frames) == 1, "duplicate apply_exchange_outcome must NOT re-trigger"


# ============================================================
# Story 6.6 review patches — added 2026-05-18
# ============================================================


def test_constructor_rejects_bool_fail_penalty() -> None:
    """`isinstance(True, int) is True` in Python — without the explicit
    bool reject, a test or future caller could pass `fail_penalty=False`
    and get silent coercion to `0`. Constructor must `TypeError`."""
    with pytest.raises(TypeError, match="fail_penalty"):
        PatienceTracker(**_easy_kwargs(fail_penalty=False))


def test_constructor_rejects_bool_recovery_bonus() -> None:
    with pytest.raises(TypeError, match="recovery_bonus"):
        PatienceTracker(**_easy_kwargs(recovery_bonus=True))


def test_constructor_rejects_none_fail_penalty() -> None:
    """A None `fail_penalty` would raise `TypeError` mid-call when
    `self._patience + self._fail_penalty` runs in
    `apply_exchange_outcome`. Fail loud at construction instead."""
    with pytest.raises(TypeError, match="fail_penalty"):
        PatienceTracker(**_easy_kwargs(fail_penalty=None))


def test_warning_flag_stays_false_when_push_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the patience-warning push raises (transport mid-teardown,
    TTS service down), `_warning_emitted` must stay False so a later
    failed exchange in the warning band can re-attempt the warning.
    Before the review patch, the flag was set BEFORE the push so a
    failed push permanently disabled warnings for the call."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy(initial_patience=100, fail_penalty=-80))

    async def _failing_push(frame: Frame, direction: FrameDirection) -> None:
        raise RuntimeError("simulated transport failure")

    tracker.push_frame = _failing_push  # type: ignore[assignment]

    async def _drive() -> None:
        # First failed exchange: meter → 20 (in warning band), warning task spawned.
        tracker.apply_exchange_outcome(False)
        # Let the warning task run to completion (it raises, gets caught).
        if tracker._warning_task is not None:
            await asyncio.gather(tracker._warning_task, return_exceptions=True)

    _run(_drive())

    # Push failed → flag MUST stay False so a future failed exchange
    # can retry the warning.
    assert tracker._warning_emitted is False


def test_warning_flag_true_after_successful_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: a successful warning push sets `_warning_emitted=True`
    so a subsequent failed exchange in the same warning band does NOT
    re-emit (one-shot semantics)."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy(initial_patience=100, fail_penalty=-80))
    _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.apply_exchange_outcome(False)
        if tracker._warning_task is not None:
            await asyncio.gather(tracker._warning_task, return_exceptions=True)

    _run(_drive())

    assert tracker._warning_emitted is True


def test_pending_survival_pct_cleared_after_run_hang_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_pending_survival_pct` must be reset to None after `_run_hang_up`
    consumes it on the survived path. Defensive cleanup so a future
    refactor that loosens `_hang_up_in_progress` semantics doesn't read
    stale 100 on a non-survived path."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.schedule_completion(survival_pct=100)
        assert tracker._pending_survival_pct == 100
        # Drive the hang-up sequence to completion.
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    assert tracker._pending_survival_pct is None, (
        "_pending_survival_pct must be cleared after _run_hang_up consumes it"
    )


# ============================================================
# Story 6.13 AC2 — silence ladder pauses on BotStartedSpeakingFrame
# ============================================================


def test_silence_ladder_pauses_on_BotStartedSpeakingFrame_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.13 AC2 (2026-05-26) — replays the call_id=150 T6 case:
    `playback_idle` arms the ladder for the prior turn → bot starts a
    new turn mid-ladder → the ladder MUST be cancelled so stage 1
    impatience never fires while Tina is mid-sentence.

    BSF arrives UPSTREAM (same direction logic as BotStoppedSpeakingFrame
    per pipecat 0.0.108's BaseOutputTransport._bot_started_speaking).
    """
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_easy_kwargs(silence_prompt_seconds=2.0))
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        # 1. Client-confirmed playback_idle for prior turn → ladder armed.
        tracker.handle_playback_idle()
        assert tracker._silence_task is not None
        # 2. Bot starts speaking BEFORE stage 1 anchor fires.
        await asyncio.sleep(0.02)  # halfway through stage 1 (50 ms)
        await tracker.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        # 3. Ladder must be cancelled.
        assert tracker._silence_task is None, (
            "BotStartedSpeakingFrame UPSTREAM must cancel the silence ladder"
        )
        # 4. Wait well past the original stage 1 anchor — no emit fires.
        await asyncio.sleep(0.10)
        emotion = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
        ]
        assert emotion == [], (
            "no impatience emit must fire while the ladder is paused for "
            "bot speech (smoke gate call_id=150 T6 regression)"
        )

        await _drain(tracker)

    _run(_drive())


def test_silence_ladder_re_arms_after_bot_finishes_speaking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.13 AC2 — after BSF cancels the ladder, the NEXT
    `playback_idle` (= bot turn finished, user heard it drain) must
    re-arm the ladder cleanly. Without this, the ladder is gone forever
    after the first bot turn.
    """
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_easy_kwargs(silence_prompt_seconds=2.0))
    _capture_pushed(tracker)

    async def _drive() -> None:
        # Arm + cancel via BSF.
        tracker.handle_playback_idle()
        await tracker.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        assert tracker._silence_task is None
        # Next playback_idle (post-bot-turn drain) re-arms.
        tracker.handle_playback_idle()
        assert tracker._silence_task is not None, (
            "next playback_idle after BSF cancel must re-arm the ladder"
        )

        await _drain(tracker)

    _run(_drive())


def test_BSF_started_direction_matches_pipecat_emission_routing():
    """Story 6.13 AC2 cross-reference contract: PatienceTracker's
    `BotStartedSpeakingFrame` direction check MUST match the direction
    `pipecat.transports.base_output.BaseOutputTransport` actually
    emits.

    Mirror of `test_BSF_direction_matches_pipecat_emission_routing`
    (for BotStoppedSpeakingFrame). Pipecat 0.0.108 pushes BSF (started)
    in BOTH directions from `_bot_started_speaking()` — but the
    downstream copy goes into the sink (output is the last processor,
    `_next is None`), so PatienceTracker only ever sees the UPSTREAM
    copy. If the check flips to DOWNSTREAM, AC2 silently regresses
    (ladder will fire mid-bot-speech in prod) and this contract test
    fires before deploy.
    """
    import inspect

    from pipecat.transports.base_output import BaseOutputTransport

    pipecat_src = inspect.getsource(BaseOutputTransport)
    fn_marker = "async def _bot_started_speaking"
    fn_start = pipecat_src.find(fn_marker)
    assert fn_start != -1, (
        "pipecat 0.0.108 structure changed — `_bot_started_speaking` no "
        "longer present on `BaseOutputTransport`. Re-verify the BSF "
        "(started) emission contract (Story 6.13 AC2) before this test "
        "can be trusted again."
    )
    fn_body = pipecat_src[fn_start : fn_start + 1500]
    assert "BotStartedSpeakingFrame()" in fn_body, (
        "pipecat changed the BotStartedSpeakingFrame emission shape — "
        "Story 6.13 AC2 needs re-verification."
    )
    assert "FrameDirection.UPSTREAM" in fn_body, (
        "pipecat NO LONGER pushes BotStartedSpeakingFrame upstream from "
        "`_bot_started_speaking`. PatienceTracker's UPSTREAM check "
        "(Story 6.13 AC2) is built on this assumption — it MUST be "
        "updated to match pipecat's new routing before this can ship "
        "to prod."
    )

    pt_src = inspect.getsource(pt_mod)
    bsf_marker = "isinstance(frame, BotStartedSpeakingFrame)"
    bsf_start = pt_src.find(bsf_marker)
    assert bsf_start != -1, (
        "PatienceTracker source no longer references "
        "`BotStartedSpeakingFrame` — Story 6.13 AC2's pause-on-bot-speech "
        "path was removed or restructured. Re-evaluate this contract."
    )
    branch = pt_src[bsf_start : bsf_start + 300]
    assert "FrameDirection.UPSTREAM" in branch, (
        "PatienceTracker's BotStartedSpeakingFrame check no longer gates "
        "on UPSTREAM. This reverts Story 6.13 AC2 — the silence ladder "
        "will fire mid-bot-speech in prod again. Re-apply UPSTREAM or "
        "update this test if pipecat routing genuinely changed."
    )


def test_stage2_prompt_BSF_does_not_self_cancel_the_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.13 review (2026-05-27) — CRITICAL regression net.

    When the silence ladder reaches stage 2 it pushes its OWN verbal
    prompt ("Hello? Are you still there?") and sets `_self_speaking`.
    That prompt's audio makes the output transport emit a
    `BotStartedSpeakingFrame` UPSTREAM that arrives right back at
    PatienceTracker. The AC2 pause-on-bot-speech branch MUST NOT cancel
    the ladder in that case (`_self_speaking` guard) — otherwise stages 3
    (anger) + 4 (silence hang-up) never run and the character never hangs
    up on a silent user.

    Without the `_self_speaking` guard this test fails at the
    `_silence_task is not None` assertion (ladder self-cancelled).
    """
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy(silence_prompt_seconds=0.1))
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        # Arm the ladder and let it run through stage 1 + stage 2 so the
        # verbal prompt is pushed and `_self_speaking` is set.
        tracker.handle_playback_idle()
        await asyncio.sleep(0.18)
        assert tracker._self_speaking is True, (
            "precondition: ladder should be at stage 2 awaiting the prompt's "
            "playback_idle with _self_speaking set"
        )
        assert tracker._silence_task is not None

        # The prompt's OWN BotStartedSpeakingFrame round-trips back here.
        await tracker.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        assert tracker._silence_task is not None and not tracker._silence_task.done(), (
            "the stage-2 prompt's own BotStartedSpeakingFrame must NOT cancel "
            "the ladder — stages 3-4 (anger + hang-up) would be killed "
            "(CRITICAL self-cancel regression)"
        )

        # The prompt finishes playing on the client → playback_idle releases
        # the stage-2 wait so stages 3 + 4 run and schedule the hang-up.
        tracker.handle_playback_idle()
        await _drain(tracker)

        call_end = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "call_end"
        ]
        assert call_end, (
            "stages 3-4 must still run after the self-prompt BSF → a "
            "character_hung_up call_end must fire"
        )
        assert call_end[0].message["data"]["reason"] == "character_hung_up"

    _run(_drive())


# ============================================================
# Story 6.13 AC3 — ladder_impatience_seconds per difficulty
# ============================================================


def test_constructor_rejects_non_positive_ladder_impatience_seconds() -> None:
    """A YAML override that resolves to <= 0 would `asyncio.sleep(<=0)`
    in `_run_silence_ladder`, silently skipping stage 1. Constructor
    must raise loud so the misconfiguration surfaces at process start.
    """
    with pytest.raises(ValueError, match="ladder_impatience_seconds"):
        PatienceTracker(**_easy_kwargs(ladder_impatience_seconds=0))
    with pytest.raises(ValueError, match="ladder_impatience_seconds"):
        PatienceTracker(**_easy_kwargs(ladder_impatience_seconds=-1.0))
    # Bool reject — `isinstance(True, int)` is True in Python.
    with pytest.raises(ValueError, match="ladder_impatience_seconds"):
        PatienceTracker(**_easy_kwargs(ladder_impatience_seconds=True))


def test_stage_1_emits_after_constructor_supplied_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stage-1 anchor is now sourced from the constructor kwarg
    (Story 6.13 AC3), not from a module-level constant. A custom
    ladder_impatience_seconds value must drive when stage 1 fires.
    """
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(
        **_easy_kwargs(
            ladder_impatience_seconds=0.15,
            silence_prompt_seconds=2.0,
        )
    )
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.handle_playback_idle()
        # Past the custom 150 ms anchor, well short of stage 2 (2.0 s).
        await asyncio.sleep(0.20)
        impatience = [
            f
            for f in captured
            if isinstance(f, OutputTransportMessageFrame)
            and f.message.get("type") == "emotion"
            and f.message["data"]["emotion"] == "impatience"
        ]
        assert len(impatience) == 1, (
            f"stage 1 must fire at the constructor-supplied anchor; "
            f"got {len(impatience)} impatience emits"
        )

        await _drain(tracker)

    _run(_drive())


def test_ladder_impatience_seconds_threaded_from_yaml_through_resolver() -> None:
    """End-to-end: the easy preset's 4.5 s default reaches the resolved
    `patience_config` dict on a null-override YAML."""
    from pipeline.scenarios import resolve_patience_config

    config = resolve_patience_config("waiter_easy_01")
    assert config["ladder_impatience_seconds"] == 4.5


# ============================================================
# Story 6.11 — schedule_noisy_environment_exit + _VALID_REASONS
# ============================================================


def test_noisy_environment_is_a_valid_reason() -> None:
    """`_VALID_REASONS` widened to include `noisy_environment` (AC4)."""
    assert "noisy_environment" in pt_mod._VALID_REASONS


def test_schedule_noisy_environment_exit_speaks_line_and_emits_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`schedule_noisy_environment_exit()` runs the hang-up coroutine with
    the noisy-environment exit line + `reason='noisy_environment'`, carrying
    the live checkpoint count (AC4)."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(
        **_fast_easy(
            initial_patience=100,
            hang_up_line_noisy_environment="Too noisy. Call back later.",
        )
    )
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.set_checkpoints_passed(1)
        tracker.schedule_noisy_environment_exit()
        # Synchronous guard flips immediately (mirrors schedule_completion).
        assert tracker.is_hanging_up is True
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    tts_speak = [
        f
        for f in captured
        if isinstance(f, TTSSpeakFrame) and f.text == "Too noisy. Call back later."
    ]
    assert len(tts_speak) == 1, "must speak the noisy-environment exit line"

    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert len(call_end) == 1
    data = call_end[0].message["data"]
    assert data["reason"] == "noisy_environment"
    assert data["checkpoints_passed"] == 1
    assert data["total_checkpoints"] == 6


def test_schedule_inappropriate_exit_speaks_line_and_records_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR37 — `schedule_inappropriate_exit()` runs the hang-up with the
    inappropriate exit line + `reason='inappropriate_content'`, and records the
    reason on `call_end_reason` for the teardown debrief (Story 7.1 AC7)."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(
        **_fast_easy(
            initial_patience=100,
            hang_up_line_inappropriate="That's enough. We're done here.",
        )
    )
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.set_checkpoints_passed(2)
        tracker.schedule_inappropriate_exit()
        # Synchronous guard flips immediately (mirrors schedule_completion).
        assert tracker.is_hanging_up is True
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert len(call_end) == 1
    assert call_end[0].message["data"]["reason"] == "inappropriate_content"
    # Story 7.1 — the reason is recorded for the teardown debrief generator.
    assert tracker.call_end_reason == "inappropriate_content"


def test_noisy_environment_interrupts_in_flight_speech_before_exit_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.11 fix (smoke call_id=200) — the noisy_environment path fires
    while the character LLM is mid-reply, so an InterruptionFrame must be
    pushed BEFORE the exit-line TTSSpeakFrame to flush that reply + the TTS
    queue; otherwise the exit line is queued behind it and flushed by the
    parasite's continued-speech interruption (user never hears it)."""
    from pipecat.frames.frames import InterruptionFrame

    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(
        **_fast_easy(hang_up_line_noisy_environment="Too noisy. Call back later.")
    )
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.schedule_noisy_environment_exit()
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    interrupt_idx = next(
        (i for i, f in enumerate(captured) if isinstance(f, InterruptionFrame)),
        None,
    )
    exit_idx = next(
        (
            i
            for i, f in enumerate(captured)
            if isinstance(f, TTSSpeakFrame) and f.text == "Too noisy. Call back later."
        ),
        None,
    )
    assert interrupt_idx is not None, "must push InterruptionFrame on noisy path"
    assert exit_idx is not None, "must speak the noisy-environment exit line"
    assert interrupt_idx < exit_idx, (
        "the interruption must flush in-flight speech BEFORE the exit line"
    )


def test_inappropriate_interrupts_in_flight_speech_before_exit_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FR37 smoke (call_id=261) — like noisy_environment, the inappropriate
    path fires WHILE the character LLM is mid-reply to the abusive turn, so an
    InterruptionFrame must flush that reply BEFORE the exit-line TTSSpeakFrame.
    Without it the (un-scripted, full-length) normal reply queues ahead of the
    exit line and buries it past the 6 s hang-up TTS timeout — the user
    perceives "no hang-up" and bails. Mirrors the noisy_environment guarantee."""
    from pipecat.frames.frames import InterruptionFrame

    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(
        **_fast_easy(hang_up_line_inappropriate="That's enough. We're done here.")
    )
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.schedule_inappropriate_exit()
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    interrupt_idx = next(
        (i for i, f in enumerate(captured) if isinstance(f, InterruptionFrame)),
        None,
    )
    exit_idx = next(
        (
            i
            for i, f in enumerate(captured)
            if isinstance(f, TTSSpeakFrame)
            and f.text == "That's enough. We're done here."
        ),
        None,
    )
    assert interrupt_idx is not None, (
        "must push InterruptionFrame on inappropriate path"
    )
    assert exit_idx is not None, "must speak the inappropriate exit line"
    assert interrupt_idx < exit_idx, (
        "the interruption must flush in-flight speech BEFORE the exit line"
    )


def test_silence_hangup_does_not_push_interruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The interruption is scoped to noisy_environment + inappropriate_content
    (both fire mid-reply) — the proven silence/survived paths (no competing
    in-flight speech) must NOT gain an InterruptionFrame."""
    from pipecat.frames.frames import InterruptionFrame

    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    assert not any(isinstance(f, InterruptionFrame) for f in captured), (
        "silence/character_hung_up path must not push an interruption"
    )


def test_schedule_noisy_environment_exit_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second call while a hang-up is already in progress is swallowed."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.schedule_noisy_environment_exit()
        tracker.schedule_noisy_environment_exit()  # no-op
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert len(call_end) == 1, "idempotent — only one call_end envelope"


# ============================================================
# Story 6.18 — dynamic exit + patience-warning line generation
# ============================================================


def _recording_gen(
    line: str | None,
    record: list[str],
    extra_record: list[str | None] | None = None,
):
    """An injected hang_up_line_generator that records the reason it was
    asked for (and, optionally, the `extra_user_text` it received) and
    returns `line`."""

    async def _gen(reason: str, extra_user_text: str | None = None) -> str | None:
        record.append(reason)
        if extra_record is not None:
            extra_record.append(extra_user_text)
        return line

    return _gen


def _raising_gen():
    async def _gen(reason: str, extra_user_text: str | None = None) -> str | None:
        raise RuntimeError("generation boom")

    return _gen


def test_run_hang_up_speaks_generated_line_when_generator_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC1 — when the generator returns a line, the hang-up speaks THAT line,
    not the canned YAML one."""
    _shrink_timers(monkeypatch)
    record: list[str] = []
    tracker = PatienceTracker(
        **_fast_easy(
            hang_up_line_silence="CANNED silence goodbye.",
            hang_up_line_generator=_recording_gen("Dynamic. Goodbye.", record),
        )
    )
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    tts = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(tts) == 1
    assert tts[0].text == "Dynamic. Goodbye.", "must speak the generated line"
    assert record == ["character_hung_up"], "generator called with the hang-up reason"
    # The canned line must NOT have been spoken.
    assert all(f.text != "CANNED silence goodbye." for f in tts)


def test_run_hang_up_falls_back_to_canned_when_generator_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2 — a None return (generation disabled/slow/empty transcript) falls
    back to the canned YAML line — there is always a final line."""
    _shrink_timers(monkeypatch)
    record: list[str] = []
    tracker = PatienceTracker(
        **_fast_easy(
            hang_up_line_silence="CANNED silence goodbye.",
            hang_up_line_generator=_recording_gen(None, record),
        )
    )
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    tts = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(tts) == 1
    assert tts[0].text == "CANNED silence goodbye."
    assert record == ["character_hung_up"]


def test_run_hang_up_falls_back_to_canned_when_generator_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2 — a generator that raises must NOT crash the hang-up; the canned
    line is spoken and call_end still fires."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(
        **_fast_easy(
            hang_up_line_silence="CANNED silence goodbye.",
            hang_up_line_generator=_raising_gen(),
        )
    )
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    tts = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(tts) == 1
    assert tts[0].text == "CANNED silence goodbye.", "raise → canned fallback"
    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert len(call_end) == 1, "hang-up must complete despite generation error"


def test_run_hang_up_uses_canned_line_when_no_generator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC7 kill-switch — with no generator injected (HANGUP_LINE_GENERATION=0
    path), the canned YAML line is spoken unchanged."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(
        **_fast_easy(hang_up_line_silence="CANNED silence goodbye.")
    )
    assert tracker._hang_up_line_generator is None
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    tts = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(tts) == 1
    assert tts[0].text == "CANNED silence goodbye."


def test_generator_receives_survived_reason_on_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC4 — the completion path generates with reason='survived' and the
    generated line is spoken; survival_pct math (Deviation #1) is unchanged."""
    _shrink_timers(monkeypatch)
    record: list[str] = []
    tracker = PatienceTracker(
        **_fast_easy(
            initial_patience=100,
            hang_up_line_survived="CANNED survived.",
            hang_up_line_generator=_recording_gen("You did it. Take care.", record),
        )
    )
    tracker._patience = 5  # would be survival_pct=5 under the meter ratio
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.set_checkpoints_passed(6)
        tracker.schedule_completion(survival_pct=100)
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    tts = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(tts) == 1
    assert tts[0].text == "You did it. Take care."
    assert record == ["survived"]
    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert call_end[0].message["data"]["survival_pct"] == 100, (
        "Deviation #1 survival_pct math must be unchanged by the dynamic line"
    )


def test_survived_path_threads_winning_user_turn_to_generator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review P0 (Decision #2 / Option A) — the winning user turn passed to
    schedule_completion is threaded to the generator as extra_user_text on the
    survived path, so the closing line can ground on the answer that actually
    won (the turn CheckpointManager suppresses from the LLM context,
    Deviation #7). The pending value is cleared after consumption."""
    _shrink_timers(monkeypatch)
    record: list[str] = []
    extra: list[str | None] = []
    tracker = PatienceTracker(
        **_fast_easy(
            initial_patience=100,
            hang_up_line_survived="CANNED survived.",
            hang_up_line_generator=_recording_gen(
                "Glad we got there. Take care.", record, extra
            ),
        )
    )

    async def _drive() -> None:
        tracker.set_checkpoints_passed(6)
        tracker.schedule_completion(
            survival_pct=100, winning_user_text="Yes, the alibi checks out."
        )
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    assert record == ["survived"]
    assert extra == ["Yes, the alibi checks out."], (
        "the survived path must hand the winning user turn to the generator"
    )
    assert tracker._pending_winning_user_text is None, "cleared after consumption"


def test_non_survived_hang_up_passes_no_extra_user_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review P0 — only the survived path threads a winning turn; a
    character_hung_up (silence/meter-zero) hang-up passes extra_user_text=None
    so no stale winning turn leaks onto another reason."""
    _shrink_timers(monkeypatch)
    record: list[str] = []
    extra: list[str | None] = []
    tracker = PatienceTracker(
        **_fast_easy(
            hang_up_line_silence="CANNED silence goodbye.",
            hang_up_line_generator=_recording_gen("Done talking. Bye.", record, extra),
        )
    )

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    assert record == ["character_hung_up"]
    assert extra == [None]


def test_generator_receives_noisy_reason_and_interruption_precedes_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6 — the noisy_environment InterruptionFrame still precedes the
    (now generated) exit line."""
    from pipecat.frames.frames import InterruptionFrame

    _shrink_timers(monkeypatch)
    record: list[str] = []
    tracker = PatienceTracker(
        **_fast_easy(
            hang_up_line_noisy_environment="CANNED noisy.",
            hang_up_line_generator=_recording_gen("Can't hear you. Bye.", record),
        )
    )
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.schedule_noisy_environment_exit()
        await asyncio.sleep(0.02)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())

    assert record == ["noisy_environment"]
    interrupt_idx = next(
        (i for i, f in enumerate(captured) if isinstance(f, InterruptionFrame)), None
    )
    line_idx = next(
        (
            i
            for i, f in enumerate(captured)
            if isinstance(f, TTSSpeakFrame) and f.text == "Can't hear you. Bye."
        ),
        None,
    )
    assert interrupt_idx is not None and line_idx is not None
    assert interrupt_idx < line_idx, (
        "InterruptionFrame must still flush in-flight speech BEFORE the "
        "generated exit line (AC6)"
    )


def test_patience_warning_speaks_generated_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC4 — the one-shot patience warning is also dynamic, generated with
    reason='patience_warning' and falling back to the canned line otherwise."""
    _shrink_timers(monkeypatch)
    record: list[str] = []
    tracker = PatienceTracker(
        **_fast_easy(
            initial_patience=100,
            fail_penalty=-10,
            patience_warning_line="CANNED warning.",
            hang_up_line_generator=_recording_gen("Last chance — answer me.", record),
        )
    )
    tracker._patience = 30  # one fail → 20 (warning band, > 0)
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.apply_exchange_outcome(False)
        if tracker._warning_task is not None:
            await asyncio.gather(tracker._warning_task, return_exceptions=True)

    _run(_drive())

    warnings = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(warnings) == 1
    assert warnings[0].text == "Last chance — answer me."
    assert record == ["patience_warning"]
    assert tracker._warning_emitted is True


def test_patience_warning_falls_back_to_canned_when_generator_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2 — the warning falls back to the canned line when generation
    returns None."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(
        **_fast_easy(
            initial_patience=100,
            fail_penalty=-10,
            patience_warning_line="CANNED warning.",
            hang_up_line_generator=_recording_gen(None, []),
        )
    )
    tracker._patience = 30
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker.apply_exchange_outcome(False)
        if tracker._warning_task is not None:
            await asyncio.gather(tracker._warning_task, return_exceptions=True)

    _run(_drive())

    warnings = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(warnings) == 1
    assert warnings[0].text == "CANNED warning."


# ============================================================
# Call 277 (2026-06-11) — exit-line silent-TTS-stall single retry
# ============================================================


def test_hangup_tts_silent_stall_requeues_exit_line_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Call 277 — the exit line was dispatched to TTS but zero audio ever
    came back: the hang-up TTS wait expired and the call ended on dead air
    with no audible goodbye. When the stall-detection window expires with
    NO BotStartedSpeakingFrame observed since the exit push, the SAME line
    must be re-queued exactly once (greppable INFO log), and call_end must
    still be pushed strictly AFTER the retry (the retry never races the
    call_end envelope)."""
    from loguru import logger as loguru_logger

    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy(hang_up_line_silence="Bye now. Goodbye."))
    captured = _capture_pushed(tracker)

    logs: list[str] = []
    sink_id = loguru_logger.add(logs.append, level="INFO")

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        # Past the pre-TTS delay (0.01) + the stall-detection window (0.25
        # shrunk) with NO audio and NO BotStoppedSpeakingFrame →
        # silent-stall retry fires. Still inside the retry wait (0.3
        # shrunk, expiring ~0.56).
        await asyncio.sleep(0.35)
        # The retry succeeds: audio starts, then the turn completes.
        await tracker.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    try:
        _run(_drive())
    finally:
        loguru_logger.remove(sink_id)

    tts = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(tts) == 2, "stalled exit line must be re-queued exactly once"
    assert tts[0].text == "Bye now. Goodbye."
    assert tts[1].text == "Bye now. Goodbye.", (
        "the retry must reuse the SAME resolved line (no second generation)"
    )
    # The first push already records the line in the LLM context via its
    # TTSTextFrame; the retry must not double-record it (the Story 7.1
    # teardown debrief reads the transcript).
    assert tts[1].append_to_context is False

    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert len(call_end) == 1, "the hang-up must still complete after the retry"
    idx_retry = next(i for i, f in enumerate(captured) if f is tts[1])
    idx_end = next(i for i, f in enumerate(captured) if f is call_end[0])
    assert idx_retry < idx_end, (
        "the retry TTSSpeakFrame must be pushed BEFORE the call_end envelope"
    )

    assert any("hangup_exit_line_retry" in entry for entry in logs), (
        "the retry must emit a greppable hangup_exit_line_retry INFO line "
        "for smoke gates"
    )


def test_hangup_tts_timeout_with_audio_flowing_never_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If audio DID start (BotStartedSpeakingFrame observed after the exit
    push) but the turn doesn't close within the cap (long line, slow
    playout), the pre-call-277 behavior holds: WARN + proceed to call_end
    with NO second push — a retry here would double-speak the goodbye and
    break the sole-final-utterance invariant (Story 6.25/6.22)."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        # Let the exit-line TTSSpeakFrame go out, then signal audio start
        # WITHOUT ever finishing the turn (no BotStoppedSpeakingFrame).
        await asyncio.sleep(0.05)
        await tracker.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        # Past phase A (stall detect, 0.25 shrunk) AND phase B (completion
        # cap remainder, 0.25) → timeout path with audio observed.
        await asyncio.sleep(0.65)
        await _drain(tracker)

    _run(_drive())

    tts = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(tts) == 1, "audio-started timeout must NOT re-queue the exit line"

    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert len(call_end) == 1, "call_end must still fire on the timeout path"


def test_hangup_tts_double_stall_retries_only_once_then_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both the original synthesis AND the retry stall (zero audio ever):
    exactly TWO TTSSpeakFrames total (never a third), and the call-end
    backstops still run — call_end, then the safety EndFrame — in strict
    order after the retry."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        # Never send any speaking frame: stall-detection window (0.25
        # shrunk) expires → retry → retry wait (0.3 shrunk) expires →
        # call_end → safety EndFrame after the client-drain timeout (0.1
        # shrunk). _drain runs the hang-up task to completion.
        await _drain(tracker)

    _run(_drive())

    tts = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(tts) == 2, "the retry is single-shot — a double stall must not loop"

    call_end = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "call_end"
    ]
    assert len(call_end) == 1
    end_frames = [f for f in captured if isinstance(f, EndFrame)]
    assert len(end_frames) == 1, (
        "the safety EndFrame backstop must survive the retry path"
    )
    idx_first = next(i for i, f in enumerate(captured) if f is tts[0])
    idx_retry = next(i for i, f in enumerate(captured) if f is tts[1])
    idx_end_env = next(i for i, f in enumerate(captured) if f is call_end[0])
    idx_end_frame = next(i for i, f in enumerate(captured) if f is end_frames[0])
    assert idx_first < idx_retry < idx_end_env < idx_end_frame, (
        "strict order: exit line < retry < call_end < EndFrame"
    )


def test_hangup_stall_retry_fires_at_detection_window_not_full_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Call 277 follow-up (Walid: 6 s of dead air before the retry feels
    like a bug) — the silent-stall verdict only needs to know whether the
    line's audio ever STARTED, so the retry must fire at the
    `_HANG_UP_TTS_STALL_DETECT_SECONDS` mark (0.25 shrunk), NOT at the
    full completion cap (`_HANG_UP_TTS_TIMEOUT_SECONDS`, 0.5 shrunk)."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        # Past pre-TTS (0.01) + stall detect (0.25) but well SHORT of the
        # 0.5 completion cap the pre-follow-up code waited for.
        await asyncio.sleep(0.38)
        tts = [f for f in captured if isinstance(f, TTSSpeakFrame)]
        assert len(tts) == 2, (
            "the retry must already be queued at the stall-detection mark "
            "(it used to wait the full completion cap)"
        )
        # Release the retry wait and finish the sequence cleanly.
        await tracker.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await _drain(tracker)

    _run(_drive())


def test_bot_speech_before_exit_push_does_not_mask_the_stall_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A BotStartedSpeakingFrame landing in the hang-up window BEFORE the
    exit-line TTSSpeakFrame is pushed (e.g. the tail of a just-interrupted
    reply on the inappropriate path, during the pre-TTS delay) must NOT
    count as exit-line audio — the gate is `_speaking_done`'s existence,
    created right before the push. Otherwise a stalled exit line would
    silently skip its retry."""
    _shrink_timers(monkeypatch)
    tracker = PatienceTracker(**_fast_easy())
    captured = _capture_pushed(tracker)

    async def _drive() -> None:
        tracker._schedule_hang_up("character_hung_up")
        # The hang-up coroutine hasn't run yet (no await since scheduling):
        # this BotStartedSpeakingFrame precedes the exit-line push.
        await tracker.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        assert tracker._exit_line_audio_started is False, (
            "bot speech before the exit push must not arm the audio flag"
        )
        # Now stall both attempts to completion.
        await _drain(tracker)

    _run(_drive())

    tts = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(tts) == 2, "the silent-stall retry must still fire"
