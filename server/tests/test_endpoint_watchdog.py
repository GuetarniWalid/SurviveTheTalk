"""Story 6.9 review patch (D3) — tests for `EndpointWatchdog`.

The watchdog observes the post-STT TranscriptionFrame stream and
synthesises a `finalized=True` frame after 8 s of continuous interim
activity to unblock the call when Soniox's neural VAD fails to declare
endpoint. Tests run with a small `_WATCHDOG_TIMEOUT_SECONDS` override
so they don't actually wait 8 s.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_watchdog():
    """Construct a watchdog with `_started=True` so `push_frame` works."""
    from pipeline.endpoint_watchdog import EndpointWatchdog

    w = EndpointWatchdog()
    # Bypass the StartFrame propagation so we can drive frames directly.
    w._started = True
    return w


def _capture_pushed(watchdog: Any) -> list[Frame]:
    captured: list[Frame] = []

    async def _recorder(frame: Frame, direction: FrameDirection) -> None:
        captured.append(frame)

    watchdog.push_frame = _recorder  # type: ignore[assignment]
    return captured


def _make_tf(text: str, *, finalized: bool) -> TranscriptionFrame:
    return TranscriptionFrame(
        text=text,
        user_id="user",
        timestamp="2026-05-21T12:00:00Z",
        finalized=finalized,
    )


# ---------- Test 1: real finalize cancels the watchdog --------------------


def test_real_finalize_cancels_watchdog(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a real `finalized=True` TF arrives, the watchdog must
    cancel its pending timer and NOT push any synthetic frame."""
    import pipeline.endpoint_watchdog as ew_mod

    monkeypatch.setattr(ew_mod, "_WATCHDOG_TIMEOUT_SECONDS", 0.05)

    w = _make_watchdog()
    captured = _capture_pushed(w)

    async def _drive() -> None:
        # Interim frame arms the watchdog.
        await w.process_frame(
            _make_tf("hello", finalized=False), FrameDirection.DOWNSTREAM
        )
        # Real finalize before timeout cancels.
        await w.process_frame(
            _make_tf("hello world", finalized=True), FrameDirection.DOWNSTREAM
        )
        # Wait past the (overridden) timeout to confirm no synthetic.
        await asyncio.sleep(0.1)

    _run(_drive())

    # Exactly the 2 original frames forwarded — no synthetic.
    assert len(captured) == 2
    assert all(isinstance(f, TranscriptionFrame) for f in captured)
    # The watchdog state must be cleared.
    assert w._last_interim_text == ""
    assert w._watchdog_task is None or w._watchdog_task.done()


# ---------- Test 2: timeout fires synthetic finalize ----------------------


def test_watchdog_fires_synthetic_finalize_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After `_WATCHDOG_TIMEOUT_SECONDS` of continuous interim TFs
    without a real finalize, the watchdog MUST synthesise a
    `finalized=True` frame with the last observed interim text."""
    import pipeline.endpoint_watchdog as ew_mod

    monkeypatch.setattr(ew_mod, "_WATCHDOG_TIMEOUT_SECONDS", 0.05)

    w = _make_watchdog()
    captured = _capture_pushed(w)

    async def _drive() -> None:
        await w.process_frame(
            _make_tf("user is talking", finalized=False),
            FrameDirection.DOWNSTREAM,
        )
        # Wait well past the (overridden) timeout.
        await asyncio.sleep(0.15)

    _run(_drive())

    # Expect: the original interim + the synthetic finalize.
    assert len(captured) == 2
    interim, synthetic = captured
    assert isinstance(synthetic, TranscriptionFrame)
    assert synthetic.text == "user is talking"
    assert getattr(synthetic, "finalized", False) is True


# ---------- Test 3: empty interim text does NOT fire ---------------------


def test_watchdog_does_not_fire_on_empty_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interim TF with empty text MUST NOT arm the watchdog — there's
    nothing to synthesise, and firing with empty text would push a
    noise frame into the pipeline."""
    import pipeline.endpoint_watchdog as ew_mod

    monkeypatch.setattr(ew_mod, "_WATCHDOG_TIMEOUT_SECONDS", 0.05)

    w = _make_watchdog()
    captured = _capture_pushed(w)

    async def _drive() -> None:
        await w.process_frame(
            _make_tf("   ", finalized=False), FrameDirection.DOWNSTREAM
        )
        await asyncio.sleep(0.1)

    _run(_drive())

    # Only the original (passthrough) frame; no synthetic.
    assert len(captured) == 1
    assert captured[0].text == "   "


# ---------- Test 4: re-arm on subsequent interims (timer refresh) --------


def test_watchdog_refreshes_on_subsequent_interims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The watchdog timer must refresh on every interim frame — a
    continuous stream of interim frames refreshes the timer indefinitely
    until either a real finalize arrives OR the gap between interims
    exceeds the timeout. This test confirms that a steady interim
    stream does NOT keep firing the watchdog at every tick."""
    import pipeline.endpoint_watchdog as ew_mod

    monkeypatch.setattr(ew_mod, "_WATCHDOG_TIMEOUT_SECONDS", 0.1)

    w = _make_watchdog()
    captured = _capture_pushed(w)

    async def _drive() -> None:
        # 3 interim frames with 30ms gaps — each refreshes the timer
        # so the watchdog never fires within this sequence (the gap
        # is < 100ms timeout).
        for i in range(3):
            await w.process_frame(
                _make_tf(f"interim {i}", finalized=False),
                FrameDirection.DOWNSTREAM,
            )
            await asyncio.sleep(0.03)
        # Now stop sending — wait past the timeout so the watchdog fires.
        await asyncio.sleep(0.15)

    _run(_drive())

    # 3 interims + 1 synthetic finalize.
    assert len(captured) == 4
    synthetic = captured[-1]
    assert isinstance(synthetic, TranscriptionFrame)
    assert synthetic.text == "interim 2", (
        "synthetic finalize must use the LATEST interim text"
    )


# ---------- Test 5: non-transcription frames pass through untouched ------


def test_non_transcription_frames_pass_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The watchdog only reacts to `TranscriptionFrame`. Any other frame
    type must pass through unchanged without arming or cancelling the
    watchdog."""
    import pipeline.endpoint_watchdog as ew_mod

    monkeypatch.setattr(ew_mod, "_WATCHDOG_TIMEOUT_SECONDS", 1.0)

    w = _make_watchdog()
    captured = _capture_pushed(w)

    other_frame = MagicMock(spec=Frame)

    async def _drive() -> None:
        await w.process_frame(other_frame, FrameDirection.DOWNSTREAM)

    _run(_drive())

    assert captured == [other_frame]
    assert w._watchdog_task is None, "non-TF frame must not arm the watchdog"


# ---------- Test 6: cleanup cancels pending watchdog ---------------------


def test_cleanup_cancels_pending_watchdog(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cleanup()` MUST cancel any in-flight watchdog task so the
    pipeline shutdown isn't blocked waiting for a synthetic finalize
    that will never matter (the call is over)."""
    import pipeline.endpoint_watchdog as ew_mod

    monkeypatch.setattr(ew_mod, "_WATCHDOG_TIMEOUT_SECONDS", 5.0)

    w = _make_watchdog()
    _capture_pushed(w)

    async def _drive() -> None:
        await w.process_frame(
            _make_tf("about to disconnect", finalized=False),
            FrameDirection.DOWNSTREAM,
        )
        # Watchdog is now armed for 5 s.
        assert w._watchdog_task is not None
        await w.cleanup()
        # Post-cleanup the task must be cancelled / done.
        assert w._watchdog_task is None or w._watchdog_task.done()

    _run(_drive())
