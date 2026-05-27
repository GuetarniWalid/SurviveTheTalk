"""Story 6.13 AC1 — Tests for TTSWatchdog FrameProcessor.

Smoke-gate call_id=149 + 151 (2026-05-26) showed CartesiaTTSService
soft-locks ~30 % of the time on multi-frame Tina responses: no
`OutputAudioRawFrame`, no `TTSStoppedFrame`, no WARN. The watchdog
is a mitigation that pushes a synthetic `TTSStoppedFrame` after 5 s
of audio-less silence so the pipeline unblocks.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    Frame,
    OutputAudioRawFrame,
    TextFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection

import pipeline.tts_watchdog as wd_mod
from pipeline.tts_watchdog import TTSWatchdog


def _run(coro: Any) -> Any:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _capture_pushed(watchdog: TTSWatchdog) -> list[Frame]:
    captured: list[Frame] = []

    async def _recorder(frame: Frame, direction: FrameDirection) -> None:
        captured.append(frame)

    watchdog.push_frame = _recorder  # type: ignore[assignment]
    return captured


def _audio_chunk() -> OutputAudioRawFrame:
    """A minimal `OutputAudioRawFrame` — content irrelevant, the
    watchdog only checks `isinstance`."""
    return OutputAudioRawFrame(audio=b"\x00\x00", sample_rate=16000, num_channels=1)


def _shrink_timeout(monkeypatch: pytest.MonkeyPatch, seconds: float = 0.1) -> None:
    """Scale the 5 s production timeout down to ms for tests."""
    monkeypatch.setattr(wd_mod, "_WATCHDOG_TIMEOUT_SECONDS", seconds)


# ============================================================
# AC1 box 3 — synthetic TTSStoppedFrame on stall
# ============================================================


def test_cartesia_watchdog_emits_synthetic_TTSStoppedFrame_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A TTSStartedFrame followed by silence (no OutputAudioRawFrame,
    no TTSStoppedFrame) must trigger a synthetic TTSStoppedFrame
    push from the watchdog after the timeout expires. The synthetic
    frame must carry the arm-time `context_id` so downstream
    aggregators pair it with the original Start.
    """
    _shrink_timeout(monkeypatch)
    watchdog = TTSWatchdog()
    captured = _capture_pushed(watchdog)

    async def _drive() -> None:
        await watchdog.process_frame(
            TTSStartedFrame(context_id="ctx-stall-1"),
            FrameDirection.DOWNSTREAM,
        )
        # No audio, no real stop. Wait past the timeout.
        await asyncio.sleep(0.20)
        await watchdog.cleanup()

    _run(_drive())

    # First captured frame is the forwarded TTSStartedFrame. After
    # that, exactly one synthetic TTSStoppedFrame must appear.
    synth_stops = [
        f
        for f in captured
        if isinstance(f, TTSStoppedFrame) and f.context_id == "ctx-stall-1"
    ]
    assert len(synth_stops) == 1, (
        f"watchdog must emit exactly one synthetic TTSStoppedFrame on stall; "
        f"got {len(synth_stops)}"
    )


# ============================================================
# Box 2 — watchdog inert on happy path
# ============================================================


def test_cartesia_watchdog_inert_when_audio_arrives_in_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When OutputAudioRawFrame arrives before the timeout, the
    watchdog must cancel its timer and emit NO synthetic
    TTSStoppedFrame. The pipeline observes its real TTSStoppedFrame
    only (from the upstream TTS service)."""
    _shrink_timeout(monkeypatch)
    watchdog = TTSWatchdog()
    captured = _capture_pushed(watchdog)

    async def _drive() -> None:
        await watchdog.process_frame(
            TTSStartedFrame(context_id="ctx-happy-1"),
            FrameDirection.DOWNSTREAM,
        )
        # Audio arrives well before the timeout.
        await asyncio.sleep(0.02)
        await watchdog.process_frame(_audio_chunk(), FrameDirection.DOWNSTREAM)
        # Wait past where the timeout WOULD have fired.
        await asyncio.sleep(0.20)
        # Real TTSStoppedFrame from the upstream TTS service.
        await watchdog.process_frame(
            TTSStoppedFrame(context_id="ctx-happy-1"),
            FrameDirection.DOWNSTREAM,
        )
        await watchdog.cleanup()

    _run(_drive())

    # Exactly ONE TTSStoppedFrame should be in the captured list — the
    # one we explicitly pushed (forwarded by pass-through). No synthetic
    # second copy from the watchdog.
    stops = [f for f in captured if isinstance(f, TTSStoppedFrame)]
    assert len(stops) == 1, (
        f"watchdog must NOT emit a synthetic TTSStoppedFrame on the happy path; "
        f"got {len(stops)} stop frames"
    )


# ============================================================
# Pass-through is total
# ============================================================


def test_watchdog_passes_through_all_observed_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every observed frame is forwarded downstream regardless of
    type — the watchdog observes, never consumes. Mirrors the
    Story 6.3 pass-through discipline."""
    _shrink_timeout(monkeypatch)
    watchdog = TTSWatchdog()
    captured = _capture_pushed(watchdog)

    frames: list[Frame] = [
        TTSStartedFrame(context_id="ctx-pt-1"),
        _audio_chunk(),
        TTSStoppedFrame(context_id="ctx-pt-1"),
        TextFrame(text="hello"),  # unrelated frame
        BotStoppedSpeakingFrame(),
    ]

    async def _drive() -> None:
        for f in frames:
            await watchdog.process_frame(f, FrameDirection.DOWNSTREAM)
        await watchdog.cleanup()

    _run(_drive())

    for f in frames:
        assert f in captured, f"frame {type(f).__name__} must be forwarded downstream"


# ============================================================
# Idempotent — watchdog fires max once per turn
# ============================================================


def test_watchdog_fires_at_most_once_per_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the timer fires and emits its synthetic Stop, a SECOND
    TTSStartedFrame would otherwise leave the `_fired_this_turn`
    flag set forever. The flag MUST reset on every new
    TTSStartedFrame so subsequent turns get a fresh chance to fire
    the watchdog if they ALSO stall."""
    _shrink_timeout(monkeypatch)
    watchdog = TTSWatchdog()
    captured = _capture_pushed(watchdog)

    async def _drive() -> None:
        # Turn 1: stall → watchdog fires.
        await watchdog.process_frame(
            TTSStartedFrame(context_id="ctx-t1"), FrameDirection.DOWNSTREAM
        )
        await asyncio.sleep(0.20)
        # Turn 2: also stalls → watchdog must fire AGAIN.
        await watchdog.process_frame(
            TTSStartedFrame(context_id="ctx-t2"), FrameDirection.DOWNSTREAM
        )
        await asyncio.sleep(0.20)
        await watchdog.cleanup()

    _run(_drive())

    synth_stops = [
        f
        for f in captured
        if isinstance(f, TTSStoppedFrame) and f.context_id in {"ctx-t1", "ctx-t2"}
    ]
    assert len(synth_stops) == 2, (
        f"watchdog must fire ONCE per stalled turn (one-shot resets on "
        f"new TTSStartedFrame); got {len(synth_stops)} synthetic stops"
    )


def test_watchdog_cleanup_cancels_outstanding_timer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pipeline shutdown mid-TTS must cancel the watchdog timer so
    asyncio doesn't log `Task was destroyed but it is pending!`
    noise."""
    _shrink_timeout(monkeypatch, seconds=10.0)  # long enough to outlive the test
    watchdog = TTSWatchdog()
    _capture_pushed(watchdog)

    async def _drive() -> None:
        await watchdog.process_frame(
            TTSStartedFrame(context_id="ctx-cleanup"),
            FrameDirection.DOWNSTREAM,
        )
        assert watchdog._timer_task is not None
        await watchdog.cleanup()
        assert watchdog._timer_task is None, "cleanup must drop the timer reference"

    _run(_drive())


def test_watchdog_cancels_timer_on_real_TTSStoppedFrame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real TTSStoppedFrame from the upstream TTS service must
    cancel the watchdog timer. Otherwise a slow Cartesia turn
    (audio took 5+ s legitimately) would race the watchdog and
    emit a SECOND synthetic Stop right after the real one."""
    _shrink_timeout(monkeypatch)
    watchdog = TTSWatchdog()
    captured = _capture_pushed(watchdog)

    async def _drive() -> None:
        await watchdog.process_frame(
            TTSStartedFrame(context_id="ctx-fast"),
            FrameDirection.DOWNSTREAM,
        )
        # No audio observed (e.g. silent line), but the TTS service
        # legitimately emits its own Stop.
        await asyncio.sleep(0.02)
        await watchdog.process_frame(
            TTSStoppedFrame(context_id="ctx-fast"),
            FrameDirection.DOWNSTREAM,
        )
        # Wait well past where the watchdog WOULD fire.
        await asyncio.sleep(0.20)
        await watchdog.cleanup()

    _run(_drive())

    # Only one TTSStoppedFrame — the real one we pushed.
    stops = [f for f in captured if isinstance(f, TTSStoppedFrame)]
    assert len(stops) == 1, (
        f"real TTSStoppedFrame must cancel the watchdog timer; "
        f"got {len(stops)} stop frames (synthetic + real)"
    )
