"""Story 6.3 — VisemeEmitter Pipecat FrameProcessor.

Observes per-word `TTSTextFrame`s emitted by Cartesia and maps each word to
one of the 12 Rive `visemeId` enum cases. Emits a primary
`{"type":"viseme","data":{"viseme_id": <int>, "timestamp_ms": <int>}}`
envelope per word, followed by a "rest" viseme to close the mouth between
words.

**Why a heuristic word→viseme mapper, not a phoneme library** (Deviation #1):
The architecture line 59 (Story 6.3 Background §2) presumed Cartesia would
surface phoneme timestamps; it actually surfaces only word-level timestamps
via `TTSService._add_word_timestamps`. Pulling in `g2p_en` or `phonemizer`
costs ~50 MB of NLTK data plus cold-start latency that we do not need at
MVP. The heuristic produces visually-acceptable lip-flap at conversational
speed — the user is watching a stylized 2D character, not a photoreal
mouth. The data-channel envelope shape is identical between heuristic and
phoneme paths, so a future quality bump only touches this file.
"""

from __future__ import annotations

from typing import Any

from pipecat.frames.frames import (
    Frame,
    OutputTransportMessageFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# 12-case Rive `visemeId` enum from Story 2.6 §3 (rest=0, aei=1,
# cdgknstxyz=2, o=3, ee=4, chjsh=5, bmp=6, qwoo=7, r=8, l=9, th=10, fv=11).
_REST_ID: int = 0
_DEFAULT_VOWEL_ID: int = 1  # aei

# Heuristic priority — first hit wins. Order intent:
#
#   1. **Strong, lip-distinct consonants** first (th, fv, bmp): they make
#      the most visible mouth-shape and read clearly even at glance speed.
#      `fv` MUST sit before `chjsh` so "fish" → 11 (lip-bite) rather than
#      `5` (lip-rounding from "sh"); the f-onset dominates visually.
#   2. **Mid-strength consonants** (chjsh, l, r): visible but less unique.
#   3. **Strong vowels** (ee, qwoo, o): when no strong consonant cluster
#      is present, the vowel formant drives the mouth shape. `ee`/`qwoo`
#      sit ahead of the generic `cdgknstxyz` fallback so "see" maps to ee
#      (4) rather than to the generic alveolar bucket (2).
#   4. **Generic alveolar bucket** (cdgknstxyz): catch-all for plain
#      consonants that produce a non-distinctive open shape.
#   5. **Default**: aei (1), used for words with no recognisable cluster
#      (single-letter "a", punctuation, etc.).
#
# Each entry is `(name, viseme_id, substrings)`. Substrings are scanned in
# the order written; place digraphs (ee, ea, ie, oo, etc.) before single
# letters so they win the lookup.
_PRIORITY: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    ("th", 10, ("th",)),
    ("fv", 11, ("f", "v")),
    ("bmp", 6, ("b", "m", "p")),
    ("chjsh", 5, ("ch", "sh", "j")),
    ("l", 9, ("l",)),
    ("r", 8, ("r",)),
    ("ee", 4, ("ee", "ea", "ie")),
    ("qwoo", 7, ("oo", "u", "w")),
    ("o", 3, ("o", "aw", "au")),
    ("cdgknstxyz", 2, ("c", "d", "g", "k", "n", "s", "t", "x", "z")),
)


def word_to_viseme_id(word: str) -> int:
    """Map a word to one of the 12 Rive visemeId enum ids via a heuristic.

    The function lowercases the input, strips non-alphabetic chars, then
    walks `_PRIORITY` and returns the first matching id. Falls back to
    `1` (`aei`) when nothing matches — empty / punctuation-only input
    also returns `1` so the mouth animates rather than freezing on rest
    mid-sentence.
    """
    cleaned = "".join(ch for ch in word.lower() if ch.isalpha())
    if not cleaned:
        return _DEFAULT_VOWEL_ID

    for _name, viseme_id, substrings in _PRIORITY:
        for sub in substrings:
            if sub in cleaned:
                return viseme_id

    return _DEFAULT_VOWEL_ID


def _word_duration_ms(word: str) -> int:
    """Rough per-word duration estimate (ms) for the rest follow-up.

    The real per-word duration is unavailable from pipecat's word-timestamp
    stream — Cartesia only gives us start times, not durations. The estimate
    is intentionally generous so the rest viseme lands near the end of the
    word's audio rather than inside it.
    """
    return max(80, len(word) * 60)


class VisemeEmitter(FrameProcessor):
    """Emits per-word viseme envelopes onto the LiveKit data channel.

    Constructor takes no arguments; instantiate with `VisemeEmitter()`.
    Inserted into the pipeline AFTER `tts` and BEFORE `transport.output()`.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Pass-through is mandatory: the emitter is an observer.
        if isinstance(frame, TTSTextFrame):
            await self._emit_viseme_for(frame)

        await self.push_frame(frame, direction)

    async def _emit_viseme_for(self, frame: TTSTextFrame) -> None:
        word = (frame.text or "").strip()
        if not word:
            return

        # `frame.pts` is the presentation timestamp in nanoseconds (set by
        # `TTSService._add_word_timestamps`); convert to ms for the wire
        # format. Frames produced before the audio baseline is set leave pts
        # as None — fall back to 0 for those edge cases. Use `is None`
        # explicitly so that a legitimate `pts == 0` (the very first frame
        # at the audio baseline) is preserved as `timestamp_ms = 0`.
        pts_ns = getattr(frame, "pts", None)
        timestamp_ms = int(round(pts_ns / 1_000_000)) if pts_ns is not None else 0

        viseme_id = word_to_viseme_id(word)
        await self.push_frame(
            OutputTransportMessageFrame(
                message={
                    "type": "viseme",
                    "data": {
                        "viseme_id": viseme_id,
                        "timestamp_ms": timestamp_ms,
                    },
                }
            ),
            FrameDirection.DOWNSTREAM,
        )

        # Follow-up rest viseme so the mouth closes between words.
        rest_at = timestamp_ms + _word_duration_ms(word)
        await self.push_frame(
            OutputTransportMessageFrame(
                message={
                    "type": "viseme",
                    "data": {"viseme_id": _REST_ID, "timestamp_ms": rest_at},
                }
            ),
            FrameDirection.DOWNSTREAM,
        )
