"""Story 7.1 (Decision 2 / AC11 / FR12) — hesitation gap observer.

A "hesitation" is a >4 s gap (Story 7.5, raised from 3 s) between the CHARACTER
finishing speaking and the USER starting to speak (`UserStartedSpeakingFrame`).
Story 7.5 re-anchors the gap-START on the client's `playback_idle` signal (the
user-perceived bot-end, routed via `handle_playback_idle()`), NOT the server's
`BotStoppedSpeakingFrame` outbound flush — that fires ~1 s ahead of the user's
ear (WebRTC jitter buffer) and inflated the measured gap. A freeze so long the
character must re-speak is closed as UNRESOLVED on `BotStartedSpeakingFrame`
(Story 7.5 C2).

At teardown the bot reads `top_hesitations()` (the longest 3 gaps, each with
the character line that preceded it) and feeds them to `generate_debrief`; the
backend then merges the measured `duration_sec` with the LLM's situational
`context` BY ID (`debrief_assembly._merge_hesitations`, Story 7.5 C3).

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
    BotStartedSpeakingFrame,
    Frame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# FR12 / debrief-content-strategy Q6 — only silences strictly longer than this
# are reported. Raised 3.0 -> 4.0 (Walid 2026-06-15): a ~3 s pause is a natural
# beat people take to compose a reply, so counting from 4 s avoids flagging
# normal thinking time as a hesitation.
_THRESHOLD_SECONDS = 4.0
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
        threshold_seconds: gaps must EXCEED this to count (default 4 s).
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
        # Every gap > threshold, as a dict:
        #   {"id": "h<n>", "duration": float, "line": str, "resolved": bool}
        # `resolved` is False for a freeze so long the CHARACTER had to speak
        # again before the user did (Story 7.5 C2 — the v1 invisible-freeze
        # class: that gap used to be silently OVERWRITTEN by the re-speak's
        # BotStoppedSpeakingFrame and never recorded). `id` lets the debrief pair
        # the measured duration to the LLM's situational context BY ID rather
        # than by index (Story 7.5 C3).
        self._gaps: list[dict] = []
        self._gap_counter: int = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        # Pass-through FIRST (observe-never-consume) so a later branch can never
        # swallow the frame — mirrors PatienceTracker.
        await self.push_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            # The character STARTED speaking while a gap was still pending — i.e.
            # the user froze long enough that the patience ladder made the
            # character speak AGAIN before the user replied. Close that gap as
            # UNRESOLVED here (Story 7.5 C2). Direction is NOT gated
            # (server/CLAUDE.md §1): we react to the frame TYPE wherever it
            # passes, mirroring PatienceTracker.
            if self._bot_stopped_at is None:
                # First character turn, or the gap was already closed by a user
                # start — no pending freeze to record.
                return
            gap = self._now() - self._bot_stopped_at
            self._bot_stopped_at = None
            self._record_gap(gap, self._preceding_line, resolved=False)
        elif isinstance(frame, UserStartedSpeakingFrame):
            if self._bot_stopped_at is None:
                # User spoke without a pending bot-stop (interruption / the very
                # first user start) — no measurable post-character gap.
                return
            gap = self._now() - self._bot_stopped_at
            self._bot_stopped_at = None
            self._record_gap(gap, self._preceding_line, resolved=True)

    def handle_playback_idle(self) -> None:
        """Anchor the gap-start on the PLAYBACK-IDLE signal (Story 7.5 fix,
        2026-06-15). The client publishes `playback_idle` when ITS speaker-side
        PCM stream confirms the bot's turn finished playing — i.e. the moment the
        USER actually heard the bot stop. Anchoring here (instead of the
        server-side `BotStoppedSpeakingFrame`, which fires ~1 s AHEAD of the
        user's ear because of WebRTC jitter buffering) removes the playout-delay
        inflation that made a quick reply read as a ~3 s hesitation. Routed in
        from `bot.py`'s `on_data_received`, alongside `PatienceTracker`."""
        self._bot_stopped_at = self._now()
        self._preceding_line = self._last_character_line()

    def _record_gap(self, duration: float, line: str, *, resolved: bool) -> None:
        """Append a gap that EXCEEDS the threshold, with a stable id + the
        resolved flag. Sub-threshold gaps are dropped (a ~1.5 s pause is a
        natural conversational gap, not a hesitation)."""
        if duration <= self._threshold:
            return
        self._gap_counter += 1
        self._gaps.append(
            {
                "id": f"h{self._gap_counter}",
                "duration": duration,
                "line": line,
                "resolved": resolved,
            }
        )

    def _last_character_line(self) -> str:
        """The most-recent character turn text from the collector, or ''."""
        for turn in reversed(self._collector.transcript):
            if isinstance(turn, dict) and turn.get("role") == "character":
                return str(turn.get("text", "")).strip()
        return ""

    def top_hesitations(self) -> list[dict]:
        """The longest `top_n` gaps, longest first — the debrief input shape.

        Each entry is
        `{"id": str, "duration_sec": float, "preceding_character_line": str,
        "resolved": bool}`, ready to pass to `generate_debrief` (which renders
        the `=== HESITATION DATA ===` block, feeding the `id` so the LLM echoes
        it back) and to `assemble_debrief` (which pairs the measured duration to
        the LLM context BY ID — Story 7.5 C3). `resolved` is False for a freeze
        the character had to break by re-speaking (C2). `id` / `resolved` are
        additive: a v1 consumer that reads only `duration_sec` /
        `preceding_character_line` is unaffected.
        """
        ranked = sorted(self._gaps, key=lambda g: g["duration"], reverse=True)[
            : self._top_n
        ]
        result = [
            {
                "id": g["id"],
                "duration_sec": round(g["duration"], 2),
                "preceding_character_line": g["line"],
                "resolved": g["resolved"],
            }
            for g in ranked
        ]
        if result:
            logger.info(
                "hesitation_observer captured {} gaps over {}s",
                len(result),
                self._threshold,
            )
        return result
