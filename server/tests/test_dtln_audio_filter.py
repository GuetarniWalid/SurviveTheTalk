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


def test_filter_steady_state_denoises_audio() -> None:
    """Story 6.9 review patch (D5) — feed many chunks of non-stationary
    noise + tone so DTLN's internal block buffer fills and starts
    emitting actual ONNX-inference output (not the warm-up
    passthrough). Without this, the test above only exercises the
    startup-passthrough branch and gives a false sense of coverage on
    real noise suppression.

    The assertion is deliberately loose: we don't require a specific
    SNR improvement (varies with model, sample rate, strength) — we
    only assert (a) output length is preserved AND (b) at least one
    chunk's output content differs from its input AFTER the warm-up
    block buffer is flushed. That's enough to catch a future regression
    where DTLN is silently bypassed across all chunks.

    Strength is bumped to 1.0 (full suppression) to maximise the
    audible delta vs the 50/50 wet/dry blend used at runtime — a
    50/50 blend on a single chunk can occasionally yield bytes that
    quantise identical to the input.
    """
    import math as _math
    import struct

    f = DTLNAudioFilter(strength=1.0)

    # 20 chunks of 480 samples each (10 ms per chunk at 48 kHz) =
    # 9600 samples / ~200 ms total — well past DTLN's internal block
    # buffer fill. Drive them sequentially so the LSTM state has time
    # to warm up.
    sample_rate = 48_000
    samples_per_chunk = 480
    n_chunks = 20

    def _make_chunk(chunk_idx: int) -> bytes:
        samples: list[int] = []
        for s in range(samples_per_chunk):
            t = chunk_idx * samples_per_chunk + s
            # 220 Hz tone (rough male f0) + deterministic pseudo-noise.
            tone = 0.3 * _math.sin(2 * _math.pi * 220 * t / sample_rate)
            noise = 0.2 * (((t * 12347) % 65521) / 65521 - 0.5) * 2
            val = max(-32768, min(32767, int((tone + noise) * 32767)))
            samples.append(val)
        return struct.pack(f"<{samples_per_chunk}h", *samples)

    chunks_in = [_make_chunk(i) for i in range(n_chunks)]

    async def _drive() -> list[bytes]:
        await f.start(sample_rate=sample_rate)
        try:
            return [await f.filter(c) for c in chunks_in]
        finally:
            await f.stop()

    chunks_out = _run(_drive())

    # Length preservation on every chunk.
    for i, (cin, cout) in enumerate(zip(chunks_in, chunks_out, strict=True)):
        assert isinstance(cout, bytes), (
            f"chunk {i} filter output must be bytes; got {type(cout)}"
        )
        assert len(cout) == len(cin), (
            f"chunk {i} length mismatch: in={len(cin)} out={len(cout)}"
        )

    # The real validation: at least one chunk after the warm-up window
    # MUST mutate its input. We don't require ALL chunks to differ
    # (DTLN's block buffer may still align with chunk boundaries
    # producing identical bytes early on), only that the suppressor
    # produces SOME non-passthrough output during the run. Bypass /
    # disabled-suppressor regressions would leave every chunk
    # byte-identical.
    differed = [
        i
        for i, (cin, cout) in enumerate(zip(chunks_in, chunks_out, strict=True))
        if cin != cout
    ]
    assert differed, (
        "DTLN appears bypassed: ALL 20 chunks returned input bytes "
        "unchanged. Either _suppressor is None / disabled, or strength=1.0 "
        "didn't trigger inference. Regression vs the documented "
        "denoising contract."
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
    audio path — operators can disable mid-call for A/B testing.

    Story 6.9 review patch (AC5 partial) — also exercise the symmetric
    re-enable direction (`enable=True` after `enable=False`). The spec
    says "the symmetric `enable=True` re-enables the suppression chain"
    but the previous test only covered the disable direction.
    """
    from pipecat.frames.frames import FilterEnableFrame

    f = DTLNAudioFilter()
    # Stub a suppressor so the toggle propagates without ONNX init cost
    f._suppressor = MagicMock()
    f._suppressor.enabled = True
    f._enabled = True

    async def _drive() -> None:
        # Disable.
        await f.process_frame(FilterEnableFrame(enable=False))

    _run(_drive())

    assert f._enabled is False
    assert f._suppressor.enabled is False, (
        "the enable flag must propagate to the underlying suppressor so "
        "downstream `_process` calls also short-circuit"
    )

    # Symmetric re-enable.
    async def _drive_reenable() -> None:
        await f.process_frame(FilterEnableFrame(enable=True))

    _run(_drive_reenable())

    assert f._enabled is True, (
        "FilterEnableFrame(enable=True) must flip _enabled back to True"
    )
    assert f._suppressor.enabled is True, (
        "the re-enable must propagate to the underlying suppressor"
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


# ---------- Story 6.9 review patches ------------------------------------


@pytest.mark.parametrize("bad_strength", [float("nan"), float("inf"), float("-inf")])
def test_strength_nan_or_inf_falls_back_to_default(bad_strength: float) -> None:
    """Story 6.9 review patch — `max(0.0, min(1.0, NaN))` returns NaN
    because every comparison with NaN evaluates False. Passing NaN to
    the suppressor would break ONNX silently. Confirm the constructor
    rejects NaN/Inf and falls back to the documented 0.5 default."""
    f = DTLNAudioFilter(strength=bad_strength)
    assert f._strength == 0.5


def test_filter_short_circuits_on_empty_or_odd_length_bytes() -> None:
    """Story 6.9 review patch — empty buffers or odd-length buffers
    (int16 PCM expects 2 bytes per sample) would make `_process` raise
    on every chunk, flooding journalctl. `filter()` must guard the
    input length BEFORE wrapping into an AudioFrame.
    """
    f = DTLNAudioFilter()
    f._sample_rate = 48_000
    f._enabled = True
    f._suppressor = MagicMock()
    f._rtc = MagicMock()

    async def _drive_empty() -> bytes:
        return await f.filter(b"")

    async def _drive_odd() -> bytes:
        return await f.filter(b"\x00\x00\x00")  # 3 bytes — odd

    assert _run(_drive_empty()) == b""
    assert _run(_drive_odd()) == b"\x00\x00\x00"
    # And critically — `_process` must NOT have been called for either.
    f._suppressor._process.assert_not_called()


def test_start_idempotent_releases_prior_suppressor() -> None:
    """Story 6.9 review patch — calling `start()` twice (transport
    reconnect without intervening `stop()`) must release the previous
    suppressor before instantiating a new one. Otherwise the old ONNX
    session (~4 MB of model weights) leaks.
    """
    f = DTLNAudioFilter()
    # Pre-populate a fake suppressor as if start() had already run once.
    fake_old = MagicMock()
    f._suppressor = fake_old
    f._rtc = MagicMock()

    async def _drive() -> None:
        # Patch DTLNNoiseSuppressor so we don't pay the ONNX init cost.
        import livekit.plugins.dtln as dtln_mod

        original = dtln_mod.DTLNNoiseSuppressor
        dtln_mod.DTLNNoiseSuppressor = MagicMock(return_value=MagicMock())  # type: ignore[assignment]
        try:
            await f.start(sample_rate=48_000)
        finally:
            dtln_mod.DTLNNoiseSuppressor = original

    _run(_drive())

    # The old suppressor MUST have been closed before being replaced.
    fake_old._close.assert_called_once()
    # And the new suppressor must be different from the old one.
    assert f._suppressor is not fake_old


def test_filter_disables_after_N_consecutive_failures() -> None:
    """Story 6.9 review patch — a corrupt ONNX session whose `_process`
    raises every chunk would flood journalctl with `logger.exception`
    on every call. After `_MAX_CONSECUTIVE_FILTER_FAILURES` consecutive
    failures, the filter must flip `_enabled=False` and degrade to
    passthrough for the rest of the call.
    """
    from pipeline.dtln_audio_filter import _MAX_CONSECUTIVE_FILTER_FAILURES

    f = DTLNAudioFilter()
    f._sample_rate = 48_000
    f._enabled = True
    fake_rtc = MagicMock()
    fake_rtc.AudioFrame.return_value = MagicMock()
    f._rtc = fake_rtc
    f._suppressor = MagicMock()
    f._suppressor._process.side_effect = RuntimeError("simulated ONNX crash")

    audio = b"\x12\x34" * 100

    async def _drive() -> None:
        # Drive enough failures to cross the threshold.
        for _ in range(_MAX_CONSECUTIVE_FILTER_FAILURES + 1):
            out = await f.filter(audio)
            assert out == audio  # always passthrough on failure

    _run(_drive())

    assert f._enabled is False, (
        f"filter must disable itself after {_MAX_CONSECUTIVE_FILTER_FAILURES} "
        "consecutive failures to bound log spam"
    )
    # And subsequent filter calls must NOT invoke `_process` (the
    # `_enabled=False` short-circuit takes over).
    call_count_before = f._suppressor._process.call_count

    async def _drive_after_disable() -> None:
        await f.filter(audio)

    _run(_drive_after_disable())
    assert f._suppressor._process.call_count == call_count_before, (
        "post-disable filter() must short-circuit BEFORE calling _process"
    )


def test_consecutive_failure_counter_resets_on_success() -> None:
    """Story 6.9 review patch — a single transient failure must NOT
    push the filter toward disable. The counter resets to 0 on any
    successful filter call.
    """
    from pipeline.dtln_audio_filter import _MAX_CONSECUTIVE_FILTER_FAILURES

    f = DTLNAudioFilter()
    f._sample_rate = 48_000
    f._enabled = True
    fake_rtc = MagicMock()
    fake_frame = MagicMock()
    fake_frame.data = b"\xab\xcd" * 100
    fake_rtc.AudioFrame.return_value = MagicMock()
    f._rtc = fake_rtc

    # Suppressor fails once, then succeeds.
    f._suppressor = MagicMock()
    f._suppressor._process.side_effect = [
        RuntimeError("transient hiccup"),
        fake_frame,  # success
    ]

    audio = b"\x12\x34" * 100

    async def _drive() -> None:
        await f.filter(audio)  # fail → counter = 1
        await f.filter(audio)  # succeed → counter resets to 0

    _run(_drive())

    assert f._enabled is True, "transient failure must NOT disable the filter"
    assert f._consecutive_filter_failures == 0, (
        "successful filter call must reset the failure counter; got "
        f"{f._consecutive_filter_failures}"
    )
    # And the limit-1 threshold must NOT have been crossed.
    assert _MAX_CONSECUTIVE_FILTER_FAILURES > 1, (
        "test assumes threshold > 1; bump if the constant changes"
    )
