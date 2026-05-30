"""Story 6.11 — Tests for EnvironmentMonitor FrameProcessor (AC2, AC3)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from pipecat.frames.frames import (
    Frame,
    OutputTransportMessageFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from pipeline.environment_monitor import EnvironmentMonitor, _speaker_token_counts


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_monitor() -> tuple[EnvironmentMonitor, MagicMock]:
    """Return a monitor + the mock PatienceTracker it calls on detection."""
    tracker = MagicMock()
    return EnvironmentMonitor(patience_tracker=tracker), tracker


def _capture_pushed(monitor: EnvironmentMonitor) -> list[Frame]:
    captured: list[Frame] = []

    async def _recorder(frame: Frame, direction: FrameDirection) -> None:
        captured.append(frame)

    monitor.push_frame = _recorder  # type: ignore[assignment]
    return captured


def _turn(
    speaker_counts: dict[str, int] | None,
    *,
    finalized: bool = True,
    with_speaker: bool = True,
) -> TranscriptionFrame:
    """Build a finalized user TranscriptionFrame whose `result` carries the
    given per-speaker token counts (mirrors Soniox's diarized token list).

    `speaker_counts=None` → no `result` at all (no diarization data).
    `with_speaker=False` → tokens present but WITHOUT a `speaker` key
    (diarization disabled / field absent).
    """
    if speaker_counts is None:
        result = None
    else:
        result = []
        for speaker, count in speaker_counts.items():
            for _ in range(count):
                token = {"text": "x", "is_final": True}
                if with_speaker:
                    token["speaker"] = speaker
                result.append(token)
    return TranscriptionFrame(
        text="some words here",
        user_id="user",
        timestamp="2026-05-30T12:00:00Z",
        result=result,
        finalized=finalized,
    )


def _env_warnings(captured: list[Frame]) -> list[OutputTransportMessageFrame]:
    return [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "env_warning"
    ]


# ---------- pass-through ----------


def test_pass_through_forwards_every_frame() -> None:
    monitor, _ = _make_monitor()
    captured = _capture_pushed(monitor)
    frame = _turn({"1": 5})
    _run(monitor.process_frame(frame, FrameDirection.DOWNSTREAM))
    assert frame in captured, "observed TranscriptionFrame must be forwarded"


def test_non_transcription_frame_passes_through_without_detection() -> None:
    monitor, tracker = _make_monitor()
    captured = _capture_pushed(monitor)
    other = OutputTransportMessageFrame(message={"unrelated": True})
    _run(monitor.process_frame(other, FrameDirection.DOWNSTREAM))
    assert other in captured
    tracker.schedule_noisy_environment_exit.assert_not_called()


def test_interim_transcription_ignored() -> None:
    """A non-finalized TF is never counted toward detection."""
    monitor, tracker = _make_monitor()
    _capture_pushed(monitor)
    # Two interim turns each with a strong 2nd speaker — would trigger if
    # finalized, but interim frames must be ignored.
    for _ in range(2):
        _run(
            monitor.process_frame(
                _turn({"1": 5, "2": 5}, finalized=False),
                FrameDirection.DOWNSTREAM,
            )
        )
    tracker.schedule_noisy_environment_exit.assert_not_called()


# ---------- detection thresholds (Deviation #2 — grace period) ----------


def test_single_parasitic_turn_does_not_trigger() -> None:
    """One 2-speaker turn is not enough — early-warning grace period."""
    monitor, tracker = _make_monitor()
    _capture_pushed(monitor)
    _run(monitor.process_frame(_turn({"1": 6, "2": 4}), FrameDirection.DOWNSTREAM))
    tracker.schedule_noisy_environment_exit.assert_not_called()


def test_two_parasitic_turns_trigger() -> None:
    """≥2 of the last 4 turns with a non-primary speaker (≥3 tokens) fires."""
    monitor, tracker = _make_monitor()
    captured = _capture_pushed(monitor)
    _run(monitor.process_frame(_turn({"1": 6, "2": 4}), FrameDirection.DOWNSTREAM))
    _run(monitor.process_frame(_turn({"1": 6, "2": 4}), FrameDirection.DOWNSTREAM))
    tracker.schedule_noisy_environment_exit.assert_called_once()
    assert len(_env_warnings(captured)) == 1


def test_second_speaker_below_token_threshold_does_not_trigger() -> None:
    """A 2nd speaker contributing only 2 tokens/turn is below the ≥3 floor."""
    monitor, tracker = _make_monitor()
    _capture_pushed(monitor)
    for _ in range(4):
        _run(monitor.process_frame(_turn({"1": 8, "2": 2}), FrameDirection.DOWNSTREAM))
    tracker.schedule_noisy_environment_exit.assert_not_called()


def test_sliding_window_expires_spaced_out_parasitic_turns() -> None:
    """Parasitic turns spaced apart never co-exist in the 4-turn window."""
    monitor, tracker = _make_monitor()
    _capture_pushed(monitor)
    # P, C, C, C, P — at no point do 2 parasitic turns sit in the window.
    sequence = [
        {"1": 6, "2": 4},  # P
        {"1": 8},  # C
        {"1": 8},  # C
        {"1": 8},  # C
        {"1": 6, "2": 4},  # P (the first P has slid out of the 4-window)
    ]
    for counts in sequence:
        _run(monitor.process_frame(_turn(counts), FrameDirection.DOWNSTREAM))
    tracker.schedule_noisy_environment_exit.assert_not_called()


# ---------- idempotency ----------


def test_fires_only_once_per_call() -> None:
    monitor, tracker = _make_monitor()
    captured = _capture_pushed(monitor)
    for _ in range(5):
        _run(monitor.process_frame(_turn({"1": 6, "2": 4}), FrameDirection.DOWNSTREAM))
    tracker.schedule_noisy_environment_exit.assert_called_once()
    assert len(_env_warnings(captured)) == 1


# ---------- missing diarization metadata ----------


def test_missing_result_field_no_detection() -> None:
    """No `result` at all (diarization absent) → never detect."""
    monitor, tracker = _make_monitor()
    _capture_pushed(monitor)
    for _ in range(4):
        _run(monitor.process_frame(_turn(None), FrameDirection.DOWNSTREAM))
    tracker.schedule_noisy_environment_exit.assert_not_called()


def test_tokens_without_speaker_key_no_detection() -> None:
    """Tokens present but no `speaker` key (diarization off) → no detect."""
    monitor, tracker = _make_monitor()
    _capture_pushed(monitor)
    for _ in range(4):
        _run(
            monitor.process_frame(
                _turn({"1": 6, "2": 4}, with_speaker=False),
                FrameDirection.DOWNSTREAM,
            )
        )
    tracker.schedule_noisy_environment_exit.assert_not_called()


# ---------- envelope shape (AC3) ----------


def test_detection_arms_the_input_gate() -> None:
    """Story 6.11 fix (call_id=205) — on detection the monitor ARMS the
    InputGate so the loud parasite can't interrupt the exit line. Arming
    must happen exactly once, alongside the schedule_noisy_environment_exit
    call."""
    tracker = MagicMock()
    gate = MagicMock()
    monitor = EnvironmentMonitor(patience_tracker=tracker, input_gate=gate)
    _capture_pushed(monitor)
    for _ in range(2):
        _run(monitor.process_frame(_turn({"1": 6, "2": 4}), FrameDirection.DOWNSTREAM))
    gate.arm.assert_called_once()
    tracker.schedule_noisy_environment_exit.assert_called_once()


def test_no_input_gate_is_tolerated() -> None:
    """input_gate is optional (unit tests / future callers may omit it) —
    detection must still fire without one."""
    tracker = MagicMock()
    monitor = EnvironmentMonitor(patience_tracker=tracker)  # no gate
    _capture_pushed(monitor)
    for _ in range(2):
        _run(monitor.process_frame(_turn({"1": 6, "2": 4}), FrameDirection.DOWNSTREAM))
    tracker.schedule_noisy_environment_exit.assert_called_once()


def test_env_warning_envelope_shape() -> None:
    monitor, _ = _make_monitor()
    captured = _capture_pushed(monitor)
    _run(monitor.process_frame(_turn({"1": 6, "2": 4}), FrameDirection.DOWNSTREAM))
    _run(monitor.process_frame(_turn({"1": 6, "2": 4}), FrameDirection.DOWNSTREAM))
    warnings = _env_warnings(captured)
    assert len(warnings) == 1
    msg = warnings[0].message
    assert msg["type"] == "env_warning"
    assert msg["data"]["reason"] == "background_voice"
    # user (speaker 1) + parasite (speaker 2) = 2 distinct speakers.
    assert msg["data"]["detected_speakers"] == 2


# ---------- helper unit ----------


def test_speaker_token_counts_helper() -> None:
    assert _speaker_token_counts(None) is None
    assert _speaker_token_counts("not a list") is None
    assert _speaker_token_counts([{"text": "a"}]) is None  # no speaker keys
    counts = _speaker_token_counts(
        [
            {"text": "a", "speaker": "1"},
            {"text": "b", "speaker": 2},  # int speaker normalised to str
            {"text": "c", "speaker": 2},
        ]
    )
    assert counts == {"1": 1, "2": 2}
