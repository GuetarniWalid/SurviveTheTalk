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

Placement: between `SonioxSTTService` and the downstream TF observers /
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
#
# This timer is RESTARTED on every interim (`_restart_watchdog`), so it fires
# only when interims STOP arriving for 8 s — the "stuck partial" case
# (call 171: a 3-word interim that never grows and never finalizes).
_WATCHDOG_TIMEOUT_SECONDS = 8.0

# Story 10.8 (Stream A, call 341) — hard cap on the TOTAL duration of a single
# continuously-streamed interim turn. The stuck-partial timer above is RESET on
# every interim, so a user who speaks a long, no-pause sentence
# (call 341: ~51 words, `num_spoken_words` 33→51, `interim_transcription=True`,
# Soniox never declared endpoint) keeps refreshing it — it never fires and the
# turn never finalizes, so the bot can't respond and (pre-Stream-A3) the silence
# ladder ran to a hang-up WHILE the user was still talking. This SECOND timer is
# armed ONCE on the first interim of a turn and is NOT restarted, so a
# continuously-growing interim still force-finalizes within a bounded time —
# the structural distinction the watchdog lacked between "stuck partial" (no new
# interims → the 8 s timer) and "still talking" (new interims arriving → this
# cap). 15 s is a generous backstop: B1 learners rarely produce 15 s of
# unbroken speech (any pause Soniox catches finalizes earlier), and the user
# gets a slightly truncated turn (the last few words may be mid-articulation)
# rather than a turn that never completes. Stream A3 (interim-aware silence
# ladder) is the primary fix for the hang-up; this cap guarantees the bot
# eventually RESPONDS to a marathon utterance (Interaction #5).
_MAX_INTERIM_DURATION_SECONDS = 15.0


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
        # Stuck-partial timer (restarted on every interim — fires when interims
        # STOP). See `_WATCHDOG_TIMEOUT_SECONDS`.
        self._watchdog_task: asyncio.Task[None] | None = None
        # Story 10.8 — continuous-growth hard-cap timer (armed ONCE per turn on
        # the first interim, NOT restarted — fires when interims KEEP arriving
        # past `_MAX_INTERIM_DURATION_SECONDS`). Distinct task so the per-interim
        # `_restart_watchdog` can't refresh it. See `_arm_hardcap_if_needed`.
        self._hardcap_task: asyncio.Task[None] | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        # NOTE the isinstance ORDER: `InterimTranscriptionFrame` and
        # `TranscriptionFrame` are siblings (both subclass `TextFrame`),
        # so a single isinstance never matches both — but checking
        # TranscriptionFrame first keeps the finalize/cancel path explicit.
        if isinstance(frame, TranscriptionFrame):
            # Soniox pushes `TranscriptionFrame` ONLY on a real endpoint
            # (always `finalized=True`). A finalize resolves the pending
            # turn → cancel BOTH timers (the turn is over) + clear interim state.
            self._cancel_watchdog()
            self._cancel_hardcap()
            self._last_interim_text = ""
            self._last_interim_user_id = ""
            self._last_interim_timestamp = ""
        elif isinstance(frame, InterimTranscriptionFrame):
            # Interim result (the frame Soniox actually streams while the
            # user is mid-utterance). Track the latest text so we have
            # something to synthesise on timeout, (re)arm the stuck-partial
            # watchdog so a frozen interim stream that never finalizes still
            # unblocks the call, AND arm the continuous-growth hard cap ONCE
            # (Story 10.8) so a never-pausing long utterance still finalizes.
            # See the module docstring's frame-type contract.
            text = (frame.text or "").strip()
            if text:
                self._last_interim_text = text
                self._last_interim_user_id = getattr(frame, "user_id", "") or ""
                self._last_interim_timestamp = getattr(frame, "timestamp", "") or ""
                self._restart_watchdog()
                self._arm_hardcap_if_needed()
        await self.push_frame(frame, direction)

    def _cancel_watchdog(self) -> None:
        task = self._watchdog_task
        if task is not None and not task.done():
            task.cancel()
        self._watchdog_task = None

    def _restart_watchdog(self) -> None:
        self._cancel_watchdog()
        self._watchdog_task = asyncio.create_task(self._watchdog_fire())

    def _arm_hardcap_if_needed(self) -> None:
        """Arm the continuous-growth hard cap ONCE per turn (Story 10.8).

        Called on every interim, but only starts a timer when none is already
        running — so subsequent interims do NOT refresh it (unlike
        `_restart_watchdog`). That's the whole point: a continuously-growing
        interim stream (call 341) keeps refreshing the stuck-partial timer so it
        never fires; this cap, armed once and left to run, force-finalizes the
        marathon turn within `_MAX_INTERIM_DURATION_SECONDS`. Cleared on a real
        finalize (`_cancel_hardcap`) so the NEXT turn's first interim re-arms it.
        """
        if self._hardcap_task is None or self._hardcap_task.done():
            self._hardcap_task = asyncio.create_task(self._hardcap_fire())

    def _cancel_hardcap(self) -> None:
        task = self._hardcap_task
        if task is not None and not task.done():
            task.cancel()
        self._hardcap_task = None

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
            "endpoint (Story 6.9 Deviation #8 backstop — stuck partial)",
            text[:64],
            _WATCHDOG_TIMEOUT_SECONDS,
        )
        # This timer won; clear its own ref + cancel the sibling hard cap so a
        # single synthetic finalize fires, not two.
        self._watchdog_task = None
        self._cancel_hardcap()
        await self._synthesize_finalize(text)

    async def _hardcap_fire(self) -> None:
        try:
            await asyncio.sleep(_MAX_INTERIM_DURATION_SECONDS)
        except asyncio.CancelledError:
            return
        text = self._last_interim_text
        if not text:
            return
        logger.error(
            "endpoint_watchdog_hardcap_fired text={!r} cap={}s — synthesizing "
            "finalized TranscriptionFrame because a continuously-growing interim "
            "stream never finalized (Story 10.8 Stream A, call 341)",
            text[:64],
            _MAX_INTERIM_DURATION_SECONDS,
        )
        # This timer won; clear its own ref + cancel the sibling stuck-partial
        # timer so a single synthetic finalize fires, not two.
        self._hardcap_task = None
        self._cancel_watchdog()
        await self._synthesize_finalize(text)

    async def _synthesize_finalize(self, text: str) -> None:
        """Push a synthetic `finalized=True` TranscriptionFrame from the last
        interim text (shared by both timer paths). Clears interim state BEFORE
        pushing so the frame's downstream propagation (which may trip into
        TranscriptionFrame observers) can't re-arm a timer mid-fire."""
        synthetic = TranscriptionFrame(
            text=text,
            user_id=self._last_interim_user_id,
            timestamp=self._last_interim_timestamp,
            finalized=True,
        )
        self._last_interim_text = ""
        self._last_interim_user_id = ""
        self._last_interim_timestamp = ""
        await self.push_frame(synthetic, FrameDirection.DOWNSTREAM)

    async def cleanup(self) -> None:
        await super().cleanup()
        # Capture the live tasks BEFORE cancelling (the cancel helpers null the
        # refs), then drain so a cancelled timer is reaped before teardown.
        pending = [
            t
            for t in (self._watchdog_task, self._hardcap_task)
            if t is not None and not t.done()
        ]
        self._cancel_watchdog()
        self._cancel_hardcap()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
