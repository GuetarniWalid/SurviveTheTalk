"""Story 6.9 review patch (D3) — tests for `EndpointWatchdog`.

The watchdog observes the post-STT frame stream and synthesises a
`finalized=True` `TranscriptionFrame` after 8 s of continuous interim
activity to unblock the call when Soniox's neural VAD fails to declare
endpoint. Tests run with a small `_WATCHDOG_TIMEOUT_SECONDS` override so
they don't actually wait 8 s.

Story 6.13 follow-up (2026-05-27): interim activity is an
`InterimTranscriptionFrame` (NOT a `TranscriptionFrame` with
`finalized=False`) — Soniox streams those two as separate frame types.
The original tests armed the watchdog with `TranscriptionFrame(
finalized=False)`, which Soniox never emits, so both the code and the
tests agreed on fiction (the `server/CLAUDE.md` §1 trap). These tests
now drive the real frame types.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest
from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
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


def _make_interim(text: str) -> InterimTranscriptionFrame:
    """The frame Soniox actually streams while the user is mid-utterance."""
    return InterimTranscriptionFrame(
        text=text,
        user_id="user",
        timestamp="2026-05-21T12:00:00Z",
    )


def _make_final(text: str) -> TranscriptionFrame:
    """The frame Soniox pushes on a real endpoint (always finalized)."""
    return TranscriptionFrame(
        text=text,
        user_id="user",
        timestamp="2026-05-21T12:00:00Z",
        finalized=True,
    )


# ---------- Test 1: real finalize cancels the watchdog --------------------


def test_real_finalize_cancels_watchdog(monkeypatch: pytest.MonkeyPatch) -> None:
    """When a real (finalized) `TranscriptionFrame` arrives, the watchdog
    must cancel its pending timer and NOT push any synthetic frame."""
    import pipeline.endpoint_watchdog as ew_mod

    monkeypatch.setattr(ew_mod, "_WATCHDOG_TIMEOUT_SECONDS", 0.05)

    w = _make_watchdog()
    captured = _capture_pushed(w)

    async def _drive() -> None:
        # Interim frame arms the watchdog.
        await w.process_frame(_make_interim("hello"), FrameDirection.DOWNSTREAM)
        # Real finalize before timeout cancels.
        await w.process_frame(_make_final("hello world"), FrameDirection.DOWNSTREAM)
        # Wait past the (overridden) timeout to confirm no synthetic.
        await asyncio.sleep(0.1)

    _run(_drive())

    # Exactly the 2 original frames forwarded — no synthetic.
    assert len(captured) == 2
    assert isinstance(captured[0], InterimTranscriptionFrame)
    assert isinstance(captured[1], TranscriptionFrame)
    # The watchdog state must be cleared.
    assert w._last_interim_text == ""
    assert w._watchdog_task is None or w._watchdog_task.done()


# ---------- Test 2: timeout fires synthetic finalize ----------------------


def test_watchdog_fires_synthetic_finalize_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After `_WATCHDOG_TIMEOUT_SECONDS` of continuous interim frames
    without a real finalize, the watchdog MUST synthesise a
    `finalized=True` `TranscriptionFrame` with the last observed interim
    text."""
    import pipeline.endpoint_watchdog as ew_mod

    monkeypatch.setattr(ew_mod, "_WATCHDOG_TIMEOUT_SECONDS", 0.05)

    w = _make_watchdog()
    captured = _capture_pushed(w)

    async def _drive() -> None:
        await w.process_frame(
            _make_interim("user is talking"), FrameDirection.DOWNSTREAM
        )
        # Wait well past the (overridden) timeout.
        await asyncio.sleep(0.15)

    _run(_drive())

    # Expect: the original interim + the synthetic finalize.
    assert len(captured) == 2
    interim, synthetic = captured
    assert isinstance(interim, InterimTranscriptionFrame)
    assert isinstance(synthetic, TranscriptionFrame)
    assert synthetic.text == "user is talking"
    assert getattr(synthetic, "finalized", False) is True


# ---------- Test 3: empty interim text does NOT fire ---------------------


def test_watchdog_does_not_fire_on_empty_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interim frame with empty text MUST NOT arm the watchdog — there's
    nothing to synthesise, and firing with empty text would push a noise
    frame into the pipeline."""
    import pipeline.endpoint_watchdog as ew_mod

    monkeypatch.setattr(ew_mod, "_WATCHDOG_TIMEOUT_SECONDS", 0.05)

    w = _make_watchdog()
    captured = _capture_pushed(w)

    async def _drive() -> None:
        await w.process_frame(_make_interim("   "), FrameDirection.DOWNSTREAM)
        await asyncio.sleep(0.1)

    _run(_drive())

    # Only the original (passthrough) frame; no synthetic.
    assert len(captured) == 1
    assert captured[0].text == "   "
    assert w._watchdog_task is None


# ---------- Test 4: re-arm on subsequent interims (timer refresh) --------


def test_watchdog_refreshes_on_subsequent_interims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The watchdog timer must refresh on every interim frame — a
    continuous stream of interim frames refreshes the timer indefinitely
    until either a real finalize arrives OR the gap between interims
    exceeds the timeout. This test confirms that a steady interim stream
    does NOT keep firing the watchdog at every tick."""
    import pipeline.endpoint_watchdog as ew_mod

    monkeypatch.setattr(ew_mod, "_WATCHDOG_TIMEOUT_SECONDS", 0.1)

    w = _make_watchdog()
    captured = _capture_pushed(w)

    async def _drive() -> None:
        # 3 interim frames with 30ms gaps — each refreshes the timer so
        # the watchdog never fires within this sequence (the gap is
        # < 100ms timeout).
        for i in range(3):
            await w.process_frame(
                _make_interim(f"interim {i}"), FrameDirection.DOWNSTREAM
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
    """The watchdog only reacts to interim / final transcription frames.
    Any other frame type must pass through unchanged without arming or
    cancelling the watchdog."""
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
    """`cleanup()` MUST cancel any in-flight watchdog task so the pipeline
    shutdown isn't blocked waiting for a synthetic finalize that will
    never matter (the call is over)."""
    import pipeline.endpoint_watchdog as ew_mod

    monkeypatch.setattr(ew_mod, "_WATCHDOG_TIMEOUT_SECONDS", 5.0)

    w = _make_watchdog()
    _capture_pushed(w)

    async def _drive() -> None:
        await w.process_frame(
            _make_interim("about to disconnect"), FrameDirection.DOWNSTREAM
        )
        # Watchdog is now armed for 5 s.
        assert w._watchdog_task is not None
        await w.cleanup()
        # Post-cleanup the task must be cancelled / done.
        assert w._watchdog_task is None or w._watchdog_task.done()

    _run(_drive())


# ---------- Test 7: a finalized=False TranscriptionFrame does NOT arm ----


def test_transcription_frame_finalized_false_does_not_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Story 6.13 regression net for the dormant-watchdog bug.

    Soniox emits interim results as `InterimTranscriptionFrame`, NOT as
    `TranscriptionFrame(finalized=False)`. The original watchdog armed on
    the latter — which never occurs — so it was inert. A `TranscriptionFrame`
    (whatever its `finalized` value) must be treated as a finalize/cancel
    and MUST NOT arm the watchdog. If a future refactor reverts to keying
    interim on `TranscriptionFrame.finalized`, this test fails.
    """
    import pipeline.endpoint_watchdog as ew_mod

    monkeypatch.setattr(ew_mod, "_WATCHDOG_TIMEOUT_SECONDS", 0.05)

    w = _make_watchdog()
    captured = _capture_pushed(w)

    async def _drive() -> None:
        tf = TranscriptionFrame(
            text="not an interim",
            user_id="user",
            timestamp="2026-05-27T12:00:00Z",
            finalized=False,
        )
        await w.process_frame(tf, FrameDirection.DOWNSTREAM)
        # The watchdog must NOT be armed by a TranscriptionFrame.
        assert w._watchdog_task is None
        await asyncio.sleep(0.1)

    _run(_drive())

    # Only the original frame forwarded — no synthetic finalize.
    assert len(captured) == 1
    assert w._last_interim_text == ""


# ---------- Test 8: source-text contract with pipecat SonioxSTTService ---


def test_soniox_interim_frame_type_contract() -> None:
    """Story 6.13 cross-reference contract (server/CLAUDE.md §1).

    The watchdog's arm/cancel split depends on Soniox pushing interim
    results as `InterimTranscriptionFrame` and finals as
    `TranscriptionFrame`. Assert that contract against the installed
    pipecat source so a future pipecat upgrade that changes Soniox's
    frame types fails HERE (loudly) rather than silently re-dormanting
    the watchdog in production.
    """
    from pipecat.services.soniox.stt import SonioxSTTService

    src = inspect.getsource(SonioxSTTService)
    assert "InterimTranscriptionFrame(" in src, (
        "pipecat SonioxSTTService no longer pushes InterimTranscriptionFrame "
        "for interim results — EndpointWatchdog's arm condition (Story 6.13) "
        "must be re-verified before it can be trusted again."
    )
    assert "TranscriptionFrame(" in src, (
        "pipecat SonioxSTTService no longer pushes TranscriptionFrame for "
        "final results — EndpointWatchdog's cancel condition needs re-check."
    )
