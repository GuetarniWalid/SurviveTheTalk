"""Story 6.9 — DTLN noise-suppression filter for the input audio path.

Wraps `livekit.plugins.dtln.DTLNNoiseSuppressor` (Aloware open-source plugin,
MIT, ~4 MB ONNX model bundle) behind Pipecat's `BaseAudioFilter` interface so
it slots into the existing `LiveKitParams(audio_in_filter=...)` extension
point. Audio is denoised BEFORE pipecat's VAD + STT — same place Pipecat's
own filters live — so every downstream observer (Silero VAD, Soniox STT,
EmotionEmitter classifier, CheckpointManager classifier) sees clean speech.

**Architecture decision** — server-side denoising:
The two product alternatives we rejected (Krisp, Picovoice Koala) ship as
client-side mobile SDKs. Going client-side would have meant: (a) commercial
license + per-minute or flat fees ($500+/mo), (b) iOS+Android platform-channel
integration (~2-3 days dev), (c) two parallel native builds to maintain.
Server-side DTLN ships in 1 file + 1 pip dependency, costs $0, zero mobile
code change, applies to every client (iOS, Android, Flutter web if we add it).
Trade-off: noisy audio is still uploaded over WebRTC (Opus encoder copes
fine), and CPU cost lives on the VPS instead of the device (~3-4 ms inference
per 8 ms block on a Hetzner-class CPU — well inside real-time).

**Underlying model** — DTLN (Dual-Signal Transformation LSTM Network,
Westhausen & Meyer, Interspeech 2020). DNS Challenge non-reverberant: PESQ
3.04 vs unprocessed 2.45; placed 8th of 17 in DNS real-time track.
Datadog runs the same model in CoScreen production. Aloware's plugin
bench-compared favorably against Krisp on coffee-shop / taxi / gym scenes
(taxi: DTLN produced cleaner transcripts than Krisp).

**Latency** — DTLN block latency is 32 ms (one 512-sample window at 16 kHz)
plus ~3-4 ms inference. Net add to perceived turn-end is ~35 ms; our
current Story 6.8 median perceived latency is 1046 ms, so the overhead is
~3% — invisible.

**Failure mode** — if ONNX init throws at `start()` (e.g. model files missing,
ONNX runtime version mismatch), we log the error and fall back to passthrough.
Better to ship slightly-noisier audio than crash the call.
"""

from __future__ import annotations

from loguru import logger
from pipecat.audio.filters.base_audio_filter import BaseAudioFilter
from pipecat.frames.frames import FilterControlFrame, FilterEnableFrame


class DTLNAudioFilter(BaseAudioFilter):
    """Pipecat `BaseAudioFilter` that denoises with DTLN ONNX inference.

    Stateful: one instance per call session (the LSTM carries state across
    frames). `start()` lazily instantiates the underlying suppressor so the
    ONNX model load (~100-500 ms cold start) happens at call boot, not at
    module import. `stop()` releases the ONNX sessions.

    Args:
        strength: 0.0 = full bypass (no suppression), 1.0 = full suppression.
            Default 0.5 blends 50/50 wet/dry to keep voice timbre natural —
            full-strength can sound thin/metallic on borderline frames.
            Tune empirically against the smoke gate; bump toward 0.7-0.8 if
            café-bondé tests show residual babble noise leaking into STT.
        debug_logging: When True, the underlying DTLN suppressor emits mask
            + RMS stats every 100 blocks at DEBUG level. Useful for tuning
            `strength` against a target scenario; leave False in prod.
    """

    def __init__(
        self,
        *,
        strength: float = 0.5,
        debug_logging: bool = False,
    ) -> None:
        self._strength = max(0.0, min(1.0, strength))
        self._debug_logging = debug_logging
        self._suppressor = None
        self._sample_rate: int = 0
        self._enabled: bool = True
        # rtc import deferred to start() so that test code that never calls
        # start() doesn't pay the ONNX session cost on import (and so a
        # missing `livekit-plugins-dtln` install only fails when the filter
        # is actually used, not at module import time).
        self._rtc = None

    async def start(self, sample_rate: int) -> None:
        """Pipecat hook — called by the input transport when the call starts.

        We get the native input sample rate here (LiveKit ≈ 48 kHz); DTLN
        runs at 16 kHz internally so the suppressor's own resamplers handle
        the conversion. We just forward whatever rate Pipecat tells us.

        If suppressor instantiation fails (model files missing, ONNX runtime
        broken), log loud and disable the filter — the call continues with
        passthrough audio rather than crashing.
        """
        self._sample_rate = sample_rate
        try:
            from livekit import rtc  # noqa: F401 — imported for AudioFrame builder
            from livekit.plugins.dtln import DTLNNoiseSuppressor

            self._rtc = rtc
            self._suppressor = DTLNNoiseSuppressor(
                strength=self._strength,
                debug_logging=self._debug_logging,
            )
            logger.info(
                "DTLNAudioFilter started sample_rate={} strength={}",
                sample_rate,
                self._strength,
            )
        except Exception as exc:
            logger.exception("DTLNAudioFilter init failed; passthrough mode: {}", exc)
            self._suppressor = None
            self._enabled = False

    async def stop(self) -> None:
        """Pipecat hook — release the ONNX sessions on call teardown."""
        if self._suppressor is not None:
            try:
                self._suppressor._close()
            except Exception:  # pragma: no cover — defensive
                logger.exception("DTLNAudioFilter close failed")
        self._suppressor = None
        self._rtc = None

    async def process_frame(self, frame: FilterControlFrame) -> None:
        """Pipecat hook — runtime enable/disable via control frames."""
        if isinstance(frame, FilterEnableFrame):
            self._enabled = bool(frame.enable)
            if self._suppressor is not None:
                self._suppressor.enabled = self._enabled
            logger.info("DTLNAudioFilter enabled={}", self._enabled)

    async def filter(self, audio: bytes) -> bytes:
        """Pipecat hook — process one chunk of raw int16 PCM mono audio.

        DTLN handles arbitrary chunk sizes via internal block buffering; we
        just wrap the bytes in an `rtc.AudioFrame` to satisfy the suppressor's
        signature and unwrap the output bytes on the way back.

        Any failure inside the suppressor (e.g. ONNX session crash) returns
        the original audio unchanged — the call continues with passthrough
        audio rather than dropping the user's turn.
        """
        if not self._enabled or self._suppressor is None or self._rtc is None:
            return audio
        try:
            # int16 PCM mono → 2 bytes per sample
            samples_per_channel = len(audio) // 2
            in_frame = self._rtc.AudioFrame(
                data=audio,
                sample_rate=self._sample_rate,
                num_channels=1,
                samples_per_channel=samples_per_channel,
            )
            # `_process` is the public hook even though the leading underscore
            # suggests otherwise — see livekit.rtc.FrameProcessor abstract
            # base: `_process` and `_close` are the two abstract methods every
            # FrameProcessor implements, and room I/O calls `_process` directly
            # when wiring `AudioInputOptions(noise_cancellation=...)`.
            out_frame = self._suppressor._process(in_frame)
            return bytes(out_frame.data)
        except Exception:
            logger.exception("DTLNAudioFilter filter failed; passthrough this chunk")
            return audio
