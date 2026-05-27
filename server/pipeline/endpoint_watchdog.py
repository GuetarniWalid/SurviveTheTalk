"""Story 6.9 review patch (D3) — `EndpointWatchdog` FrameProcessor.

Wall-clock backstop for Soniox endpoint detection. Story 6.9 Deviation #8
flipped `vad_force_turn_endpoint=False` so Soniox's neural VAD owns
endpoint detection (more robust than Silero against ambient noise). The
trade-off: if Soniox itself never declares endpoint (long mid-utterance
pause, network hiccup, neural-VAD misfire), the call hangs because every
downstream observer — `CheckpointManager`, `PatienceTracker`,
`LLMContextAggregatorPair.user()` — gates on `finalized=True` and stays
silent on continuous interim TFs.

This processor watches the post-STT frame stream. While
`InterimTranscriptionFrame`s keep arriving without a final
`TranscriptionFrame`, a watchdog timer ticks. If the timer fires after
`_WATCHDOG_TIMEOUT_SECONDS` of continuous interim activity, the
watchdog synthesises a `finalized=True` `TranscriptionFrame` using the
last observed interim text and pushes it downstream so the rest of the
pipeline can move forward. The user gets a slightly truncated turn (the
last word might be mid-articulation) but the call doesn't hang.

**Frame-type contract (Story 6.13 follow-up, 2026-05-27 — CRITICAL):**
Soniox streams interim results as `InterimTranscriptionFrame` and final
results as `TranscriptionFrame(finalized=True)` — these are SEPARATE
classes (both subclass `TextFrame`; neither inherits the other), and
`SonioxSTTService` notes "every TranscriptionFrame is inherently
finalized". The original Story 6.9 watchdog armed on `TranscriptionFrame`
with `finalized=False`, which Soniox NEVER emits — so the watchdog was
DORMANT for all of Epic 6. It surfaced on call_id=171 (2026-05-27): a
3-word interim that never finalized hung the call ~23 s until the user
gave up, with no `endpoint_watchdog_fired` log. The fix observes
`InterimTranscriptionFrame` to arm and `TranscriptionFrame` to cancel.
See `server/CLAUDE.md` §1 (the FrameProcessor "test and code mutually
wrong" trap) — the original unit tests drove `TranscriptionFrame(
finalized=False)` and passed against fiction.

The watchdog is reset on every real `TranscriptionFrame` (finalize), so
the common case (Soniox finalizes correctly) costs nothing. It also
fires at most once per pending turn — once the synthetic finalize is
pushed, the watchdog clears and waits for the next interim stream.

Placement: between `SonioxSTTService` and `EmotionEmitter` /
`LLMContextAggregatorPair.user()` in `bot.py`. Mirrors the Story 6.6
Dev #5 / Dev #29 lessons — sit upstream of the user aggregator so the
synthesised frame reaches every observer.
"""

from __future__ import annotations

import asyncio

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Story 6.9 review patch (D3) — fire the watchdog after this many seconds
# of continuous `finalized=False` TFs without a `finalized=True`. Chosen
# at 8 s to give Soniox's own endpoint detection time to resolve normal
# pauses (typical mid-utterance hesitation is ~1-3 s) while still
# unblocking the call before a real human would hang up (smoke-test
# call 142 hung 22 s before user abandoned).
_WATCHDOG_TIMEOUT_SECONDS = 8.0


class EndpointWatchdog(FrameProcessor):
    """Force-finalize after `_WATCHDOG_TIMEOUT_SECONDS` of continuous
    interim TranscriptionFrames without a real finalize.

    Pass-through MANDATORY (mirrors Story 6.3 / 6.6 lessons) — every
    observed frame is forwarded unchanged. The watchdog adds a new
    synthesised frame on timeout; it never swallows real frames.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._last_interim_text: str = ""
        self._last_interim_user_id: str = ""
        self._last_interim_timestamp: str = ""
        self._watchdog_task: asyncio.Task[None] | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        # NOTE the isinstance ORDER: `InterimTranscriptionFrame` and
        # `TranscriptionFrame` are siblings (both subclass `TextFrame`),
        # so a single isinstance never matches both — but checking
        # TranscriptionFrame first keeps the finalize/cancel path explicit.
        if isinstance(frame, TranscriptionFrame):
            # Soniox pushes `TranscriptionFrame` ONLY on a real endpoint
            # (always `finalized=True`). A finalize resolves the pending
            # turn → cancel any armed watchdog + clear interim state.
            self._cancel_watchdog()
            self._last_interim_text = ""
            self._last_interim_user_id = ""
            self._last_interim_timestamp = ""
        elif isinstance(frame, InterimTranscriptionFrame):
            # Interim result (the frame Soniox actually streams while the
            # user is mid-utterance). Track the latest text so we have
            # something to synthesise on timeout, and (re)arm the watchdog
            # so a stuck interim stream that never finalizes still unblocks
            # the call. See the module docstring's frame-type contract.
            text = (frame.text or "").strip()
            if text:
                self._last_interim_text = text
                self._last_interim_user_id = getattr(frame, "user_id", "") or ""
                self._last_interim_timestamp = getattr(frame, "timestamp", "") or ""
                self._restart_watchdog()
        await self.push_frame(frame, direction)

    def _cancel_watchdog(self) -> None:
        task = self._watchdog_task
        if task is not None and not task.done():
            task.cancel()
        self._watchdog_task = None

    def _restart_watchdog(self) -> None:
        self._cancel_watchdog()
        self._watchdog_task = asyncio.create_task(self._watchdog_fire())

    async def _watchdog_fire(self) -> None:
        try:
            await asyncio.sleep(_WATCHDOG_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            return
        text = self._last_interim_text
        if not text:
            return
        logger.error(
            "endpoint_watchdog_fired text={!r} timeout={}s — synthesizing "
            "finalized TranscriptionFrame because Soniox never declared "
            "endpoint (Story 6.9 Deviation #8 backstop)",
            text[:64],
            _WATCHDOG_TIMEOUT_SECONDS,
        )
        synthetic = TranscriptionFrame(
            text=text,
            user_id=self._last_interim_user_id,
            timestamp=self._last_interim_timestamp,
            finalized=True,
        )
        # Clear state BEFORE pushing so the synthetic frame's downstream
        # propagation (which may itself trip into TranscriptionFrame
        # observers) can't re-arm the watchdog mid-fire.
        self._last_interim_text = ""
        self._last_interim_user_id = ""
        self._last_interim_timestamp = ""
        self._watchdog_task = None
        await self.push_frame(synthetic, FrameDirection.DOWNSTREAM)

    async def cleanup(self) -> None:
        await super().cleanup()
        self._cancel_watchdog()
        if self._watchdog_task is not None and not self._watchdog_task.done():
            await asyncio.gather(self._watchdog_task, return_exceptions=True)
        self._watchdog_task = None
