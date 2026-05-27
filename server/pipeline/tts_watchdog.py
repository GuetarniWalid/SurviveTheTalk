"""Story 6.13 AC1 — Cartesia silent-stall watchdog.

Story 6.9b smoke gate on Pixel 9 Pro XL (2026-05-26) reproduced a
~30 %-rate failure mode in `CartesiaTTSService`: for multi-frame
character responses, the upstream Cartesia WebSocket logs
`Generating TTS [...]` but the matching `cleaning up TTS context
<uuid>` debug line that normally follows ~1.2 s later never appears.
No `TTSStoppedFrame`, no `OutputAudioRawFrame`, no WARN, no
WebSocket disconnect — the pipeline soft-locks until the user gives
up and hangs up manually (calls 149 + 151 reproduced).

Root cause investigation requires a packet capture of a known-repro
Cartesia WebSocket session and is deferred to a follow-up; see
Story 6.13 Deviation #1. In the meantime this `TTSWatchdog` is a
**mitigation that makes the bug recoverable**, not a fix that
prevents it from happening:

  1. Observes `TTSStartedFrame` flowing downstream out of the TTS
     service. Each new `TTSStartedFrame` ARMS a fresh 5.0 s
     wall-clock timer and clears the `_fired_this_turn` flag.
  2. Observes `OutputAudioRawFrame` (the first audio chunk reaching
     the downstream `LatencyProbe` position). Cancels the timer —
     audio is flowing, Cartesia is healthy.
  3. Observes `TTSStoppedFrame` — TTS completed normally, cancel
     the timer.
  4. If the timer fires (5 s with no audio + no stop): push a
     synthetic `TTSStoppedFrame` downstream + structured WARN log.
     Downstream observers (`tts_first_audio_probe`,
     `transport.output()`, `context_aggregator.assistant()`)
     interpret it as the TTS completing — the pipeline unblocks,
     the silence ladder can re-arm on the next `playback_idle`,
     the user gets silence on their device for that turn but the
     call survives. Fires max ONCE per turn — `_fired_this_turn`
     blocks re-fire until the next `TTSStartedFrame` re-arms.

Pass-through is mandatory (Story 6.3 / 6.6 lesson re-applied):
every observed frame is forwarded downstream unchanged. The
synthetic `TTSStoppedFrame` is pushed via `push_frame` from inside
the timer coroutine — not by swallowing the real one.

The watchdog wraps no upstream resource; on `cleanup()` it just
cancels its outstanding asyncio task so the pipeline shutdown
doesn't log `Task was destroyed but it is pending!` noise.

Inert in nominal operation: Cartesia returns audio in <1 s on the
happy path, so the timer is cancelled long before its 5 s anchor.
The watchdog adds zero latency overhead — only a single
`isinstance` per frame and a Task spawn on TTSStartedFrame arrival.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    Frame,
    OutputAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Cartesia round-trip on the happy path is 0.3-1.0 s from
# `TTSStartedFrame` to first `OutputAudioRawFrame`. 5.0 s leaves
# room for slow-cellular variance + WebSocket reconnect retries
# without firing on legitimate delays. Smoke-gate observation: the
# stall reproduces with audio never arriving (forever), so any cap
# >2 s catches every reproduction case.
_WATCHDOG_TIMEOUT_SECONDS = 5.0


class TTSWatchdog(FrameProcessor):
    """5 s wall-clock backstop against `CartesiaTTSService` silent stalls.

    Wire AFTER the TTS service and BEFORE the `tts_first_audio`
    LatencyProbe so it sees the same audio-frame timing the probe
    does. Pass-through; never consumes frames.

    Implementation note: this processor doesn't gate on direction.
    The frames we care about (TTSStartedFrame / OutputAudioRawFrame /
    TTSStoppedFrame) flow DOWNSTREAM out of the TTS service — that's
    the only direction we ever observe them in. Adding a direction
    gate would risk silently breaking the watchdog on a future
    pipecat that routes these frames differently.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._timer_task: asyncio.Task[None] | None = None
        # One-shot per TTS turn. Set when the timer fires; cleared on
        # the next `TTSStartedFrame` arrival (= new turn). Without
        # this flag, a downstream observer that re-emits
        # `TTSStartedFrame` (or a tightly-timed sequence) could
        # spawn multiple watchdog tasks, each pushing its own
        # synthetic `TTSStoppedFrame` — the pipeline would see
        # ghost-TTS-stop events.
        self._fired_this_turn = False
        # `_current_context_id` is captured at arm-time so the
        # synthetic `TTSStoppedFrame` carries the matching context_id
        # — pipecat 0.0.108's TTS frames pair Started/Stopped via
        # this id; a synthetic Stop with the wrong id could confuse
        # downstream aggregators.
        self._current_context_id: str | None = None
        # Cache the first ~40 chars of the TTS text for the WARN log
        # — helps the operator disambiguate which turn stalled when
        # multiple are happening near each other. Reset on each
        # arm. Pipecat doesn't pair text→TTSStartedFrame today
        # (text comes via the TextFrame upstream of the TTS service),
        # so we leave this empty unless populated externally; the
        # log line still carries context_id which is the canonical
        # identifier.
        self._current_text_preview: str = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Pass-through MANDATORY (Story 6.3 lesson) — forward first
        # so a follow-up branch that raises cannot swallow the
        # frame from downstream.
        await self.push_frame(frame, direction)

        # Story 6.13 follow-up (2026-05-27) — audio-frame diagnostic, gated
        # by `TTS_AUDIO_DEBUG=1`. Logs sample_rate + byte count + max
        # amplitude of every OutputAudioRawFrame passing this point (right
        # after the TTS service, before transport.output()). Used to locate
        # where audio dies on the ElevenLabs path (real audio confirmed at
        # the API level; bug is downstream). Inert in prod when the env var
        # is unset.
        if os.environ.get("TTS_AUDIO_DEBUG") == "1" and isinstance(
            frame, OutputAudioRawFrame
        ):
            audio = getattr(frame, "audio", b"") or b""
            n = len(audio) // 2
            max_amp = 0
            if n:
                # int16 little-endian max-abs without numpy.
                mv = memoryview(audio)[: n * 2].cast("h")
                for s in mv:
                    a = -s if s < 0 else s
                    if a > max_amp:
                        max_amp = a
            logger.info(
                "[TTS-AUDIO-DEBUG] OutputAudioRawFrame bytes={} sample_rate={} "
                "num_channels={} max_amp={} type={} direction={}",
                len(audio),
                getattr(frame, "sample_rate", "?"),
                getattr(frame, "num_channels", "?"),
                max_amp,
                type(frame).__name__,
                direction.name,
            )

        if isinstance(frame, TTSStartedFrame):
            # New TTS turn — cancel any stale timer, clear the one-
            # shot flag, arm a fresh 5 s timer. The cancel is a
            # defensive guard against the (rare) case where the prior
            # TTS ended without emitting either OutputAudioRawFrame
            # or TTSStoppedFrame; without it the prior timer would
            # eventually fire and emit a synthetic Stop for the new
            # turn's context_id, which would be wrong.
            await self._cancel_timer()
            self._fired_this_turn = False
            self._current_context_id = getattr(frame, "context_id", None)
            self._timer_task = asyncio.create_task(self._wait_and_emit())
        elif isinstance(frame, OutputAudioRawFrame):
            # First audio chunk arrived — Cartesia is healthy.
            # Cancel the timer so the synthetic Stop doesn't fire
            # on an in-flight nominal turn. Multiple audio chunks
            # in the same turn no-op (timer already cancelled).
            if self._timer_task is not None and not self._timer_task.done():
                await self._cancel_timer()
        elif isinstance(frame, TTSStoppedFrame):
            # Real TTS stop — cancel timer + clear the fire flag so
            # the next TTSStartedFrame arms cleanly.
            await self._cancel_timer()
            self._fired_this_turn = False
        elif isinstance(frame, BotStoppedSpeakingFrame):
            # Defensive secondary reset: if a TTSStoppedFrame went
            # missing for whatever reason but the bot's speaking
            # window closed, clear the fire flag so the next turn
            # is unblocked.
            self._fired_this_turn = False

    async def _wait_and_emit(self) -> None:
        try:
            await asyncio.sleep(_WATCHDOG_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            # Nominal cancel (audio arrived / TTSStopped arrived /
            # cleanup ran). Re-raise silently.
            raise

        if self._fired_this_turn:
            # Belt-and-braces — another path already fired (e.g.
            # tight race between an audio arrival cancel and the
            # timer expiring). Don't double-emit.
            return
        self._fired_this_turn = True
        context_id = self._current_context_id
        logger.warning(
            "cartesia_tts_watchdog_fired reason=no_audio_within_{}s "
            "context_id={!r} text_preview={!r}",
            _WATCHDOG_TIMEOUT_SECONDS,
            context_id,
            self._current_text_preview,
        )
        # Push a synthetic Stop downstream so the pipeline unblocks
        # (transport.output / context_aggregator.assistant treat it
        # as a normal turn-end). The synthetic frame carries the
        # arm-time context_id so downstream aggregators that pair
        # by id don't mis-match.
        try:
            await self.push_frame(
                TTSStoppedFrame(context_id=context_id),
                FrameDirection.DOWNSTREAM,
            )
        except Exception:  # pragma: no cover — defensive shutdown race
            logger.exception(
                "cartesia_tts_watchdog: synthetic TTSStoppedFrame push failed"
            )

    async def _cancel_timer(self) -> None:
        prior = self._timer_task
        self._timer_task = None
        if prior is not None and not prior.done():
            prior.cancel()
            await asyncio.gather(prior, return_exceptions=True)

    async def cleanup(self) -> None:
        """Cancel the outstanding timer on pipeline shutdown so the
        asyncio task doesn't log `Task was destroyed but it is
        pending!` noise (Story 6.3 EmotionEmitter shipped the
        same pattern)."""
        await super().cleanup()
        await self._cancel_timer()
