"""Story 6.29 — ReplySanitizer Pipecat FrameProcessor (AC2 + AC8).

Sits between the LLM and TTS (`bot.py`: after `llm_first_text_probe`, before
`transcript_character`) and guarantees that ONLY spoken dialogue reaches the
TTS, the transcript, and — via the downstream assistant aggregator — the LLM
context. Two jobs:

1. **Strip non-spoken artifacts (AC2 / call-274 P2).** Parenthetical spans
   ``( … )`` and asterisk actions ``* … *`` are removed from LLM-origin
   streamed `TextFrame`s. The charter's spoken-dialogue-only rule (rule 7)
   reduces occurrence upstream; this processor is the deterministic backstop.
   A reply that becomes EMPTY after stripping (a pure-meta reply — the exact
   call-274 "(Actually, I still need to confirm…)" case) is dropped whole:
   nothing is sent to TTS, one INFO line is logged, and the rare silent turn
   is the accepted trade-off (the silence ladder still runs; never regenerate
   — latency — and never let the raw text through).

2. **Extract the co-generated mood tag (AC8 / the Story 6.12 design).** The
   reply LLM appends a trailing ``<mood:VALUE>`` tag
   (`prompts.MOOD_TAG_DIRECTIVE`). The tag is stripped from the text stream
   and, when VALUE is one of the 7-value Rive enum, re-emitted at end-of-reply
   as the SAME ``{"type":"emotion","data":{"emotion":...,"intensity":...}}``
   envelope the retired `EmotionEmitter` produced (byte-compatible — AC3).
   Absent/invalid/malformed tag → no envelope; the character keeps its prior
   pose (same degradation as the old classifier-timeout path).

Streaming contract (AC2 — no perceivable TTS latency):

- Plain text passes through IMMEDIATELY, frame by frame (the frame object is
  mutated in place so its concrete type — `LLMTextFrame`, with its
  `includes_inter_frame_spaces` semantics — survives).
- The ONLY held-back text is a small tail that might begin a split artifact:
  a partial ``<mood:…`` tag prefix (bounded by `_MAX_TAG_HOLD`) or a single
  trailing ``*`` whose span/literal nature needs the next character.
  Suppressed span content is dropped as it streams, never buffered.
- State resets on `LLMFullResponseStartFrame` and on interruption frames
  (barge-in mid-reply: held text and any pending mood are discarded — never
  emit a face from a half-reply).

Scope guards:

- ONLY `TextFrame`s BETWEEN `LLMFullResponseStartFrame` and
  `LLMFullResponseEndFrame` are transformed. `TTSSpeakFrame` exit lines (e.g.
  PatienceTracker's ``*heavy sigh* I'm done.``) are NOT `TextFrame` subclasses
  and pass untouched — pre-existing, PatienceTracker-owned behavior (story
  What-NOT-to-do).
- `TranscriptionFrame` IS a `TextFrame` subclass (pipecat 0.0.108) — excluded
  defensively even though user transcriptions are consumed upstream of the LLM.
- Every other frame type passes through unchanged (pass-through is mandatory —
  Story 6.3 lesson).

The pure scanning logic lives in `_SpanScanner` (no pipecat) so the Story
6.15 calibration harness sanitizes the simulated character's replies through
`sanitize_reply_text` with EXACTLY the code prod streams through
(golden==prod).

Per server/CLAUDE.md §1: no instance attribute here shadows a pipecat
base-class one (`_clock`, `_next`, `_observer`, …), and the real-pipeline
drive test in `test_bot_pipeline_wiring.py` runs this processor inside a
`PipelineTask` so a shadow would surface loud.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    OutputTransportMessageFrame,
    TextFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Runtime-reactive subset of Story 2.6's Rive `emotion` enum — the canonical
# contract with the `.riv` ViewModel (`sadness`/`boredom`/`impressed` stay
# reserved for other emitters, e.g. PatienceTracker's escalation poses). Moved
# here from the retired `emotion_emitter.py`; keep in lockstep with
# `prompts.MOOD_TAG_DIRECTIVE`.
_ALLOWED_EMOTIONS: frozenset[str] = frozenset(
    {
        "satisfaction",
        "smirk",
        "frustration",
        "impatience",
        "anger",
        "confusion",
        "disgust_hangup",
    }
)

# The emotion envelope carries the same shape as the retired EmotionEmitter's
# (AC3 — byte-compatible `data` fields). The tag carries no intensity, so we
# emit the emitter's old missing-intensity fallback; the client receives but
# does not use it (verified 2026-06-10, story Dev Notes).
_DEFAULT_INTENSITY = 0.5
# call-335: structural never-silent floor. When the whole reply is non-spoken
# meta (a mood tag only), the character would otherwise fall literally silent
# (the dead air a user hung up on). A prompt-only "always speak" guard already
# failed there, so we substitute this one short, deterministic spoken line.
_NEVER_SILENT_FALLBACK = "Go on."

# A complete mood tag, e.g. "<mood:frustration>". MOOD_TAG_DIRECTIVE instructs
# lowercase snake_case, but the match is case-INSENSITIVE as a defense (review
# 6.29): a case-deviant tag ("<Mood:Anger>") must still never reach TTS — match
# leniently, then validate the LOWERCASED value strictly against the enum.
_MOOD_TAG_RE = re.compile(r"<mood:([a-z_]+)>", re.IGNORECASE)
_MOOD_TAG_PREFIX = "<mood:"
# Longest legal tag is "<mood:disgust_hangup>" (21 chars). A held '<…' run
# longer than this without a '>' is provably not a tag — release it as text.
_MAX_TAG_HOLD = 24


def _could_be_tag_prefix(s: str) -> bool:
    """True if ``s`` (starting at ``<``) could still grow into a mood tag.

    Case-insensitive, mirroring `_MOOD_TAG_RE` — a held split tag must use
    the same leniency as the whole-tag match or a case-deviant split tag
    would be released mid-hold and spoken.
    """
    s = s.lower()
    if len(s) >= _MAX_TAG_HOLD:
        return False
    if len(s) < len(_MOOD_TAG_PREFIX):
        return _MOOD_TAG_PREFIX.startswith(s)
    if not s.startswith(_MOOD_TAG_PREFIX):
        return False
    return re.fullmatch(r"[a-z_]*", s[len(_MOOD_TAG_PREFIX) :]) is not None


# SPIKE (spike/character-led, 2026-06-30) — a character-led end-of-call marker.
# Stripped from the stream EXACTLY like the mood tag (never spoken, never in the
# transcript/context); its presence schedules the in-character hang-up. Throwaway.
_END_CALL_RE = re.compile(r"<end_call>", re.IGNORECASE)
_END_CALL_FULL = "<end_call>"


def _could_be_end_call_prefix(s: str) -> bool:
    """True if ``s`` (starting at ``<``) could still grow into ``<end_call>``."""
    s = s.lower()
    if len(s) >= len(_END_CALL_FULL):
        return False
    return _END_CALL_FULL.startswith(s)


class _SpanScanner:
    """Pure streaming span/tag stripper (no pipecat, no I/O).

    Feed it chunks; it returns the text safe to forward NOW and keeps the
    split-artifact state (held tail, open span, last mood) across chunks.
    One instance per LLM reply.
    """

    def __init__(self) -> None:
        # Held-back tail: only ever a potential split tag prefix or a lone "*".
        self.held_tail = ""
        # None | "paren" | "asterisk" — currently inside a stripped span.
        self.suppress_mode: str | None = None
        self.paren_depth = 0
        # Last valid mood tag value seen this reply (last wins).
        self.mood: str | None = None
        # Spans stripped this reply (observability).
        self.stripped_spans = 0
        # SPIKE — set True if the character wrote the <end_call> marker this reply.
        self.end_call = False

    def feed(self, chunk: str) -> str:
        text = self.held_tail + chunk
        self.held_tail = ""
        out: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            if self.suppress_mode == "paren":
                ch = text[i]
                if ch == "(":
                    self.paren_depth += 1
                elif ch == ")":
                    self.paren_depth -= 1
                    if self.paren_depth <= 0:
                        self.suppress_mode = None
                i += 1
                continue
            if self.suppress_mode == "asterisk":
                if text[i] == "*":
                    self.suppress_mode = None
                i += 1
                continue

            ch = text[i]
            if ch == "(":
                self.suppress_mode = "paren"
                self.paren_depth = 1
                self.stripped_spans += 1
                i += 1
                continue
            if ch == "*":
                if i + 1 >= n:
                    # Can't tell yet whether this starts an action span
                    # ("*sighs*") or is a literal ("2 * 3") — hold it.
                    self.held_tail = "*"
                    break
                if text[i + 1].isspace():
                    # Literal asterisk ("2 * 3") — spoken math, keep it.
                    out.append(ch)
                    i += 1
                    continue
                self.suppress_mode = "asterisk"
                self.stripped_spans += 1
                i += 1
                continue
            if ch == "<":
                rest = text[i:]
                match = _MOOD_TAG_RE.match(rest)
                if match:
                    value = match.group(1).lower()
                    if value in _ALLOWED_EMOTIONS:
                        self.mood = value
                    else:
                        logger.warning(
                            "reply_sanitizer rejected mood value: {!r}", value
                        )
                    i += match.end()
                    continue
                end_match = _END_CALL_RE.match(rest)
                if end_match:
                    # SPIKE — character-led end marker. Strip it (never spoken);
                    # ReplySanitizer schedules the hang-up at end-of-reply.
                    self.end_call = True
                    i += end_match.end()
                    continue
                if _could_be_tag_prefix(rest) or _could_be_end_call_prefix(rest):
                    # Possible split tag ("<mo" + "od:smirk>" / "<end" +
                    # "_call>") — hold the tail, bounded by _MAX_TAG_HOLD.
                    self.held_tail = rest
                    break
                out.append(ch)
                i += 1
                continue

            out.append(ch)
            i += 1
        return "".join(out)

    def finish(self) -> None:
        """Resolve end-of-reply state.

        A held tail is either a partial/truncated mood tag or a lone trailing
        ``*`` — neither was ever meant to be spoken, so both are dropped. An
        unterminated ``( …`` / ``* …`` span began as a stage direction: its
        content (already never forwarded) stays dropped.
        """
        if self.held_tail:
            # SPIKE — a <end_call> marker split across the final chunk (the ">"
            # never arrived) still means the character asked to end; honor it
            # before dropping the tail.
            if self.held_tail.lower().startswith("<end"):
                self.end_call = True
            logger.debug(
                "reply_sanitizer dropped unterminated tail: {!r}", self.held_tail
            )
            self.held_tail = ""
        if self.suppress_mode is not None:
            logger.info(
                "reply_sanitizer dropped unterminated {} span", self.suppress_mode
            )
            self.suppress_mode = None
            self.paren_depth = 0


def sanitize_reply_text(
    text: str, fallback_line: str | None = None
) -> tuple[str, str | None]:
    """Pure, non-streaming variant for whole-string replies.

    Returns ``(clean_text, mood)`` where ``mood`` is the LAST valid tag value
    found (or None). Used by the Story 6.15 calibration harness so the
    simulated character's replies are sanitized EXACTLY like prod's streamed
    ones (golden==prod): same span-stripping, same tag extraction.

    ``fallback_line`` mirrors the FrameProcessor's per-scenario never-silent floor
    (Story 10.6 review D4); ``None`` uses the global default.
    """
    scanner = _SpanScanner()
    cleaned = scanner.feed(text)
    scanner.finish()
    # golden==prod: mirror the live never-silent floor — an all-meta (or
    # empty) reply becomes the deterministic fallback line, never silence.
    return (cleaned.strip() or (fallback_line or _NEVER_SILENT_FALLBACK)), scanner.mood


class ReplySanitizer(FrameProcessor):
    """Strips non-spoken artifacts + extracts the trailing mood tag."""

    def __init__(self, *, fallback_line: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._in_llm_response = False
        self._scanner = _SpanScanner()
        # True once any non-whitespace SPOKEN text was forwarded this reply.
        self._spoke_any = False
        # Story 10.6 review (D4) — the never-silent floor line, per scenario.
        # None → the global default (`_NEVER_SILENT_FALLBACK`). An in-character
        # line keeps a mugger/detective from breaking persona, and avoids the
        # generic "Go on." inviting the learner to keep talking after, e.g., a
        # threat. bot.py passes `load_scenario_never_silent_fallback(scenario_id)`.
        self._fallback_line = (fallback_line or "").strip() or _NEVER_SILENT_FALLBACK
        # SPIKE (spike/character-led, 2026-06-30) — optional callback invoked once
        # at end-of-reply when the character wrote <end_call> (it decided to end
        # the call in-character). bot.py wires it to
        # PatienceTracker.schedule_character_led_bail ONLY when SPIKE_CHARACTER_LED
        # is on; None → the marker is still stripped but no hang-up is scheduled.
        self._character_led_end_callback: Callable[[], None] | None = None

    def set_character_led_end_callback(self, cb: Callable[[], None] | None) -> None:
        """SPIKE — wire (post-construction) the character-led end trigger."""
        self._character_led_end_callback = cb

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._reset_reply_state()
            self._in_llm_response = True
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            # Flush ONLY when a reply is actually open (review 6.29): a
            # straggling End after an InterruptionFrame already reset the
            # state (or an End with no Start) would otherwise log a spurious
            # `reply_sanitizer_empty_reply_dropped` on every barge-in.
            if self._in_llm_response:
                await self._flush_end_of_reply()
            self._in_llm_response = False
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, InterruptionFrame):
            # Barge-in mid-reply: the generation is aborted — drop held text
            # and any pending mood (never emit a face from a half-reply).
            self._reset_reply_state()
            self._in_llm_response = False
            await self.push_frame(frame, direction)
            return

        if (
            self._in_llm_response
            and isinstance(frame, TextFrame)
            # TranscriptionFrame IS a TextFrame (pipecat 0.0.108) — user
            # speech is consumed upstream of the LLM, but exclude it
            # defensively; only LLM-origin reply text is ours to edit.
            and not isinstance(frame, TranscriptionFrame)
        ):
            cleaned = self._scanner.feed(frame.text)
            if not cleaned:
                # Fully suppressed chunk (inside a span / held tail) —
                # forward nothing; the stream resumes on the next chunk.
                return
            if cleaned.strip():
                self._spoke_any = True
            # Mutate in place so the frame KEEPS its concrete type and
            # `includes_inter_frame_spaces` semantics (a re-built plain
            # TextFrame would make the TTS re-space LLM chunks).
            frame.text = cleaned
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)

    async def _flush_end_of_reply(self) -> None:
        scanner = self._scanner
        scanner.finish()
        if scanner.stripped_spans:
            # Greppable strip event for the smoke-gate journalctl tail.
            logger.info(
                "reply_sanitizer_stripped spans={} spoke_any={}",
                scanner.stripped_spans,
                self._spoke_any,
            )
        if not self._spoke_any:
            # call-335: the whole reply was non-spoken meta (a mood tag only),
            # which previously left the turn literally silent — the dead air a
            # user hung up on. A prompt-only "always speak" guard already
            # failed here, so this is the STRUCTURAL floor: push one short,
            # deterministic spoken line so the character is never silent.
            # Mirrored in sanitize_reply_text for golden==prod.
            await self.push_frame(
                TextFrame(self._fallback_line), FrameDirection.DOWNSTREAM
            )
            logger.info(
                "reply_sanitizer_empty_reply_filled fallback={!r} "
                "(reply was entirely non-spoken meta)",
                self._fallback_line,
            )
        if scanner.mood is not None:
            await self.push_frame(
                OutputTransportMessageFrame(
                    message={
                        "type": "emotion",
                        "data": {
                            "emotion": scanner.mood,
                            "intensity": _DEFAULT_INTENSITY,
                        },
                    }
                ),
                FrameDirection.DOWNSTREAM,
            )
            # Same observability contract as the retired EmotionEmitter: a
            # journalctl tail shows each emitted face in real time.
            logger.info("reply_sanitizer_mood_emit emotion={}", scanner.mood)
        if scanner.end_call:
            # SPIKE — the character decided to end the call in-character. Strip
            # already removed the marker; now schedule the hang-up (the wired
            # PatienceTracker generates + speaks the closing line, then ends).
            logger.info(
                "spike_character_led_end_call detected spoke_any={} "
                "→ scheduling character-led hang-up",
                self._spoke_any,
            )
            if self._character_led_end_callback is not None:
                self._character_led_end_callback()
        self._reset_reply_state()

    def _reset_reply_state(self) -> None:
        self._scanner = _SpanScanner()
        self._spoke_any = False
