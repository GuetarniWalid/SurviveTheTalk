"""Story 6.11 fix — tests for InputGate ("stop listening" on noise exit)."""

from __future__ import annotations

import asyncio

from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from pipeline.input_gate import _MUTED_FRAME_TYPES, InputGate

# NOTE: InterruptionFrame / StartFrame are NOT driven through `process_frame`
# directly here — the base FrameProcessor does special interruption/start
# handling that needs a running TaskManager (server/CLAUDE.md §1: don't drive
# system control frames through a bare processor). We assert their membership
# in the muted set structurally instead; the behavioural drop is covered with
# the safe user-speech/audio frames + validated end-to-end on the device gate.


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _capture(gate: InputGate) -> list[Frame]:
    captured: list[Frame] = []

    async def _recorder(frame: Frame, direction: FrameDirection) -> None:
        captured.append(frame)

    gate.push_frame = _recorder  # type: ignore[assignment]
    return captured


def _audio() -> InputAudioRawFrame:
    return InputAudioRawFrame(audio=b"\x00\x00", sample_rate=16000, num_channels=1)


def _transcription() -> TranscriptionFrame:
    return TranscriptionFrame(text="hello", user_id="u", timestamp="t")


def test_interruption_and_user_speech_are_in_the_muted_set() -> None:
    """The frames that drive interruptions / user turns must be muted when
    armed (this is the whole point — no interruptions, no new turns)."""
    for ftype in (
        InputAudioRawFrame,
        InterruptionFrame,
        UserStartedSpeakingFrame,
        TranscriptionFrame,
    ):
        assert ftype in _MUTED_FRAME_TYPES


def test_passes_user_frames_through_when_not_armed() -> None:
    gate = InputGate()
    captured = _capture(gate)
    frames = [_audio(), UserStartedSpeakingFrame(), _transcription()]
    for f in frames:
        _run(gate.process_frame(f, FrameDirection.DOWNSTREAM))
    assert captured == frames, "un-armed gate must pass all frames through"


def test_armed_drops_mic_audio_and_user_speech() -> None:
    gate = InputGate()
    captured = _capture(gate)
    gate.arm()
    for f in [_audio(), UserStartedSpeakingFrame(), _transcription()]:
        _run(gate.process_frame(f, FrameDirection.DOWNSTREAM))
    assert captured == [], "armed gate must drop user-speech/audio/transcription"


def test_armed_still_passes_non_user_frames() -> None:
    """The exit line (TTSSpeakFrame) + data envelopes (call_end) MUST still
    flow when armed — only user-input frames are muted, so the hang-up
    sequence + teardown are unaffected."""
    gate = InputGate()
    captured = _capture(gate)
    gate.arm()
    keep = [
        TTSSpeakFrame(text="I can't hear you — call back when it's quieter."),
        OutputTransportMessageFrame(message={"type": "call_end", "data": {}}),
    ]
    for f in keep:
        _run(gate.process_frame(f, FrameDirection.DOWNSTREAM))
    assert captured == keep, "armed gate must still pass non-user frames"


def test_arm_is_idempotent() -> None:
    gate = InputGate()
    assert gate.is_armed is False
    gate.arm()
    gate.arm()
    assert gate.is_armed is True
