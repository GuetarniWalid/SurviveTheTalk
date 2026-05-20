"""Story 6.8 Phase 1 AC3 — LLM→TTS streaming-overlap probe.

A tiny `FrameProcessor` that logs `time.monotonic_ns()` timestamps the
FIRST time it sees a frame of interest each turn, then stays silent.
Pair two instances (one between `llm` and `transcript_character`, one
between `tts` and `transport.output()`) and compute the gap
`(tts_first_audio_ns - llm_first_text_ns) / 1_000_000` ms from a
single calibrated call's journalctl tail. If the gap is <500 ms, LLM
tokens are streaming into TTS as the PRD `Performance` section
mandates ("streaming overlap mandatory — LLM streams to TTS before
full response generated"); if >500 ms, TTS is buffering the full LLM
response and we need to enable a `stream=True`-equivalent flag.

The probe is **opt-in via the `LATENCY_PROBE` env var** so production
doesn't emit three INFO lines per turn. Smoke-gate operators export
`LATENCY_PROBE=1` on the VPS, run a single calibrated call, capture
the 2 log lines, then unset the var (or just leave it — the probe is
cheap when active, but the noise is what we don't want in steady-state).

Per-turn reset: each probe instance resets its "first seen" flag on
`BotStoppedSpeakingFrame` (DOWNSTREAM) so the NEXT user turn starts a
fresh measurement. Without this, only the very first turn of the call
would emit; subsequent turns would silently drop their timestamps and
the operator would think the probe broke.
"""

from __future__ import annotations

import os
import time

from loguru import logger
from pipecat.frames.frames import BotStoppedSpeakingFrame, Frame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


_LATENCY_PROBE_ENABLED = bool(os.environ.get("LATENCY_PROBE"))


class LatencyProbe(FrameProcessor):
    """Per-turn first-frame-of-kind timestamp logger.

    Args:
        label: Short tag in the log line so the smoke-gate operator can
            disambiguate the two probe sites (e.g. "llm_first_text"
            between `llm` and `transcript_character`, or
            "tts_first_audio" between `tts` and `transport.output()`).
        frame_type: The first frame of this type seen per turn triggers
            the log emit. Pass `TextFrame` for the LLM-side probe and
            `OutputAudioRawFrame` for the TTS-side probe.
    """

    def __init__(
        self,
        *,
        label: str,
        frame_type: type[Frame],
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._label = label
        self._frame_type = frame_type
        self._fired_this_turn = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Reset per-turn on the bot's last word leaving the pipeline —
        # next user turn gets a fresh first-frame measurement.
        if isinstance(frame, BotStoppedSpeakingFrame):
            self._fired_this_turn = False

        if (
            _LATENCY_PROBE_ENABLED
            and not self._fired_this_turn
            and isinstance(frame, self._frame_type)
        ):
            self._fired_this_turn = True
            logger.info(
                "latency_probe label={} ts_ns={}",
                self._label,
                time.monotonic_ns(),
            )

        await self.push_frame(frame, direction)
