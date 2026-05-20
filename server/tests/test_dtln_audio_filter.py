"""Story 6.9 — Tests for `DTLNAudioFilter` (the BaseAudioFilter wrapper).

The underlying `DTLNNoiseSuppressor` is heavy (instantiates 2 ONNX sessions,
~4 MB model weights, ~100-500 ms cold start). We exercise it once in a
real-init test to prove the import chain works end-to-end (Pipecat
`BaseAudioFilter` → our wrapper → `livekit.plugins.dtln.DTLNNoiseSuppressor`
→ ONNX runtime), then use the lighter `enabled=False` / start-failure paths
for the rest of the suite so the test suite stays fast.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from pipeline.dtln_audio_filter import DTLNAudioFilter


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _silence_bytes(samples: int = 480) -> bytes:
    """480 samples at 48 kHz mono int16 = 10 ms of digital silence."""
    return b"\x00\x00" * samples


# ---------- Test 1: end-to-end init + filter round-trip -----------------


def test_filter_round_trip_returns_bytes_of_same_length() -> None:
    """Real ONNX init: prove the wrapper composes cleanly with
    `livekit.plugins.dtln.DTLNNoiseSuppressor`. The output `bytes` should
    have the same length as the input — the suppressor returns
    passthrough during startup latency (~24 ms = ~1152 samples at 48 kHz)
    and steady-state denoised audio after. Either way the length must
    match so downstream Pipecat processors don't see a chunk-size shift.
    """
    f = DTLNAudioFilter(strength=0.5)
    audio = _silence_bytes(samples=480)  # 10 ms at 48 kHz

    async def _drive() -> bytes:
        await f.start(sample_rate=48_000)
        try:
            return await f.filter(audio)
        finally:
            await f.stop()

    out = _run(_drive())
    assert isinstance(out, bytes)
    assert len(out) == len(audio), (
        f"filter must preserve chunk length; got {len(out)} bytes for "
        f"{len(audio)} bytes of input"
    )


# ---------- Test 2: enabled=False is a passthrough ----------------------


def test_disabled_filter_returns_input_unchanged() -> None:
    """When `enabled=False` the filter MUST short-circuit and return the
    input bytes object unchanged — no ONNX inference, no copying. This
    is the runtime kill-switch path (e.g. operator pushes
    `FilterEnableFrame(enable=False)`) and must be cheap."""
    f = DTLNAudioFilter()
    f._enabled = False
    audio = b"\x12\x34\x56\x78" * 100

    async def _drive() -> bytes:
        return await f.filter(audio)

    out = _run(_drive())
    assert out is audio, "disabled filter must return input identity, not a copy"


# ---------- Test 3: init failure falls back to passthrough --------------


def test_init_failure_disables_filter_passthrough() -> None:
    """If `DTLNNoiseSuppressor()` constructor raises (e.g. ONNX model file
    missing, runtime version mismatch), `start()` MUST catch the exception,
    log it, and disable the filter — the call continues with noisy but
    intact audio rather than crashing. This is the 'better than broken'
    principle from server/CLAUDE.md."""
    f = DTLNAudioFilter()

    async def _drive() -> bytes:
        # Monkey-patch the DTLNNoiseSuppressor import to raise on construction.
        import livekit.plugins.dtln as dtln_mod

        original = dtln_mod.DTLNNoiseSuppressor

        def _exploding_init(*args, **kwargs):
            raise RuntimeError("simulated ONNX init crash")

        dtln_mod.DTLNNoiseSuppressor = _exploding_init  # type: ignore[assignment]
        try:
            await f.start(sample_rate=48_000)
            return await f.filter(b"\x12\x34" * 100)
        finally:
            dtln_mod.DTLNNoiseSuppressor = original  # restore
            await f.stop()

    out = _run(_drive())
    assert out == b"\x12\x34" * 100, (
        "after init failure the filter must passthrough audio bytes exactly"
    )
    assert f._enabled is False, "init failure must flip _enabled to False"


# ---------- Test 4: FilterEnableFrame toggles _enabled ------------------


def test_filter_enable_frame_toggles_enabled_flag() -> None:
    """Pipecat ships a `FilterEnableFrame(enable: bool)` control frame for
    runtime toggling. The filter must apply it without going through the
    audio path — operators can disable mid-call for A/B testing."""
    from pipecat.frames.frames import FilterEnableFrame

    f = DTLNAudioFilter()
    # Stub a suppressor so the toggle propagates without ONNX init cost
    f._suppressor = MagicMock()
    f._suppressor.enabled = True
    f._enabled = True

    async def _drive() -> None:
        await f.process_frame(FilterEnableFrame(enable=False))

    _run(_drive())

    assert f._enabled is False
    assert f._suppressor.enabled is False, (
        "the enable flag must propagate to the underlying suppressor so "
        "downstream `_process` calls also short-circuit"
    )


# ---------- Test 5: filter exception falls back to passthrough this chunk -


def test_filter_exception_returns_input_unchanged() -> None:
    """If the underlying `_process` raises mid-call (e.g. ONNX session
    corrupted, OOM), the filter MUST return the input chunk unchanged
    rather than propagating the exception up the Pipecat pipeline. A
    swallowed denoising error costs one noisy chunk; an unhandled
    exception crashes the call's audio path entirely."""
    f = DTLNAudioFilter()
    f._sample_rate = 48_000
    f._enabled = True
    # Fake suppressor + rtc whose `_process` always raises
    fake_rtc = MagicMock()
    fake_rtc.AudioFrame.return_value = MagicMock()
    f._rtc = fake_rtc

    f._suppressor = MagicMock()
    f._suppressor._process.side_effect = RuntimeError("simulated ONNX crash")

    audio = b"\x12\x34\x56\x78" * 100

    async def _drive() -> bytes:
        return await f.filter(audio)

    out = _run(_drive())
    assert out == audio, (
        "filter exception must passthrough the chunk; do NOT propagate to "
        "Pipecat pipeline"
    )


# ---------- Test 6: stop() releases resources cleanly -------------------


def test_stop_releases_suppressor_and_rtc() -> None:
    """After `stop()`, the filter must release the suppressor + rtc refs
    so the ONNX sessions GC. Subsequent calls to `filter()` short-circuit
    to passthrough."""
    f = DTLNAudioFilter()
    f._suppressor = MagicMock()
    f._rtc = MagicMock()
    f._enabled = True

    async def _drive() -> bytes:
        await f.stop()
        return await f.filter(b"\x99\x99" * 50)

    out = _run(_drive())
    assert f._suppressor is None
    assert f._rtc is None
    assert out == b"\x99\x99" * 50, "post-stop filter must passthrough"


# ---------- Test 7: strength is clamped to [0.0, 1.0] -------------------


@pytest.mark.parametrize(
    ("input_strength", "expected_strength"),
    [
        (-0.5, 0.0),
        (0.0, 0.0),
        (0.5, 0.5),
        (1.0, 1.0),
        (1.5, 1.0),
    ],
)
def test_strength_clamped(input_strength: float, expected_strength: float) -> None:
    """`strength` outside [0.0, 1.0] must clamp to the valid range — the
    underlying DTLNNoiseSuppressor also clamps but we double-up to surface
    invalid configs in unit tests rather than at first ONNX inference."""
    f = DTLNAudioFilter(strength=input_strength)
    assert f._strength == expected_strength
