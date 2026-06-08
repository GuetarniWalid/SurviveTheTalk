"""Story 7.1 (Decision 2 / AC11 / FR12) — hesitation gap observer.

A "hesitation" is a >3 s gap between the CHARACTER finishing speaking
(`BotStoppedSpeakingFrame`) and the USER starting to speak
(`UserStartedSpeakingFrame`). The `TranscriptCollector` timestamps are
frame-OBSERVATION times (the character stamp is when the LLM *text* was
produced, BEFORE TTS plays), so they can't be diffed directly for an accurate
gap — hence this dedicated observer pairs the two speech-boundary frames.

At teardown the bot reads `top_hesitations()` (the longest 3 gaps, each with
the character line that preceded it) and feeds them to `generate_debrief`; the
backend then merges the measured `duration_sec` with the LLM's situational
`context` by index (`debrief_assembly._merge_hesitations`).

Frame-direction trap (server/CLAUDE.md §1): this observer is placed
IMMEDIATELY adjacent to `PatienceTracker` in the pipeline, which already
observes BOTH `BotStoppedSpeakingFrame` (UPSTREAM, from the output transport)
and `UserStartedSpeakingFrame` (DOWNSTREAM, from VAD) at that slot — so both
frames provably reach this position. To stay immune to the trap we do NOT gate
on `direction`: we react to the frame TYPE wherever it passes, and forward
every frame untouched (observe-never-consume, mirroring PatienceTracker).
"""

from __future__ import annotations

import time
from typing import Callable

from loguru import logger
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    Frame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# FR12 / debrief-content-strategy Q6 — only silences strictly longer than this
# are reported (a ~1.5 s pause is a natural conversational gap, not a
# revealing hesitation).
_THRESHOLD_SECONDS = 3.0
# Top-N longest gaps fed to the debrief LLM (debrief-content-strategy Q6).
_TOP_N = 3


class HesitationObserver(FrameProcessor):
    """Pairs `BotStoppedSpeakingFrame` → next `UserStartedSpeakingFrame` gaps.

    Args:
        collector: the shared `TranscriptCollector` — used to snapshot the
            character line that just finished (for the LLM prompt's "after
            CHARACTER said: …"). At BSF time the character turn is already in
            `collector.transcript` (logged when the text was produced, before
            TTS played it).
        threshold_seconds: gaps must EXCEED this to count (default 3 s).
        top_n: how many longest gaps `top_hesitations()` returns (default 3).
        clock: monotonic time source, injectable for tests.
    """

    def __init__(
        self,
        *,
        collector,
        threshold_seconds: float = _THRESHOLD_SECONDS,
        top_n: int = _TOP_N,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self._collector = collector
        self._threshold = threshold_seconds
        self._top_n = top_n
        # Stored as `_now`, NOT `_clock`: pipecat's base FrameProcessor owns a
        # `self._clock` attribute that `setup()` (run at StartFrame on every
        # real call) UNCONDITIONALLY overwrites with a non-callable `BaseClock`
        # (frame_processor.py:184/563). Storing our monotonic callable as
        # `_clock` would be silently clobbered → `self._clock()` raises
        # `'SystemClock' object is not callable` and every hesitation read dies
        # in prod while unit tests (which never run `setup()`) stay green — the
        # CLAUDE.md §1 / Déviation #28 trap, via attribute-name collision.
        self._now = clock
        # When the bot last stopped speaking (None = not awaiting a user start,
        # e.g. the user interrupted, so the next UserStartedSpeakingFrame has no
        # paired stop).
        self._bot_stopped_at: float | None = None
        self._preceding_line: str = ""
        # (duration_sec, preceding_character_line) for every gap > threshold.
        self._gaps: list[tuple[float, str]] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        # Pass-through FIRST (observe-never-consume) so a later branch can never
        # swallow the frame — mirrors PatienceTracker.
        await self.push_frame(frame, direction)

        if isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_stopped_at = self._now()
            self._preceding_line = self._last_character_line()
        elif isinstance(frame, UserStartedSpeakingFrame):
            if self._bot_stopped_at is None:
                # User spoke without a pending bot-stop (interruption / the very
                # first user start) — no measurable post-character gap.
                return
            gap = self._now() - self._bot_stopped_at
            self._bot_stopped_at = None
            if gap > self._threshold:
                self._gaps.append((gap, self._preceding_line))

    def _last_character_line(self) -> str:
        """The most-recent character turn text from the collector, or ''."""
        for turn in reversed(self._collector.transcript):
            if isinstance(turn, dict) and turn.get("role") == "character":
                return str(turn.get("text", "")).strip()
        return ""

    def top_hesitations(self) -> list[dict]:
        """The longest `top_n` gaps, longest first — the debrief input shape.

        Each entry is `{"duration_sec": float, "preceding_character_line": str}`,
        ready to pass to `generate_debrief` (which renders the
        `=== HESITATION DATA ===` block) and to `assemble_debrief` (which merges
        the duration with the LLM context by index).
        """
        ranked = sorted(self._gaps, key=lambda g: g[0], reverse=True)[: self._top_n]
        result = [
            {"duration_sec": round(duration, 2), "preceding_character_line": line}
            for duration, line in ranked
        ]
        if result:
            logger.info("hesitation_observer captured {} gaps >3s", len(result))
        return result
