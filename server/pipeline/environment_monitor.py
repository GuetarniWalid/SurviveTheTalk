"""Story 6.11 — EnvironmentMonitor Pipecat FrameProcessor.

Detects a parasitic BACKGROUND VOICE degrading the call (the
cocktail-party case Story 6.9's DTLN noise-suppression provably can't
fix — noise suppression pulls ambient hiss, it does NOT isolate one
human voice from another). When detected, the active scenario character
announces in-character that they can't hear, the call ends, and the
user's daily slot is refunded (`gifted` — see `routes_calls._compute`).

**Detection signal — Soniox V4 speaker diarization.** With
`enable_speaker_diarization=True` (set in `bot.py`, Story 6.11 AC1),
every Soniox token is annotated with a `speaker` id. Pipecat 0.0.108
surfaces these on `TranscriptionFrame.result` (the raw token-dict list),
NOT on `frame.metadata` — verified against `pipecat/services/soniox/
stt.py`, where the parser builds
`TranscriptionFrame(..., result=self._final_transcription_buffer)` and
each buffered entry is the raw Soniox dict carrying `speaker`. (The
spec's AC2 assumed `frame.metadata`; this is Deviation #6 — corrected to
match the installed runtime.)

**Why diarization and not energy/noise thresholds.** DTLN already pulls
ambient noise, so an energy metric would be polluted by DTLN's own
suppression. The problem isn't background NOISE — it's a background
VOICE. Diarization targets exactly that, at zero extra cost (it's a flag
on a model we already pay for).

**Early-warning + grace period (Deviation #2), not instant.** A single
two-speaker turn is often a Soniox mis-diarization (the same user's
prosody re-classified as a new speaker after a long pause). Firing on
that would refund + hang up on a false positive, which is worse UX than a
30-60 s delayed real warning. So detection requires **≥2 of the last 4
user turns** to each contain a real overlapping second voice (see the
co-occurrence rule below). The "primary" speaker is the one with the most
cumulative tokens across the call (= the user, who dominates their own
phone's mic); everyone else is parasitic.

**Co-occurrence rule (Story 6.20 follow-up — call_id=223 false positive).**
A turn counts as parasitic ONLY if the primary speaker AND a non-primary
speaker (≥`min_speaker_tokens` tokens) appear in the SAME turn. A genuine
background voice is audible *alongside* the user (both diarized within one
turn); a Soniox label-flip instead re-labels the SAME lone speaker
*between* turns — each turn carries only one speaker id, the id just flips
'1'→'2' across turns. In call_id=223 the user's single voice was split
across single-speaker turns (`{'1':8}`, `{'2':22}`, …) with no within-turn
overlap, yet the old "any non-primary speaker in the turn" rule read those
lone re-labelled turns as a parasite — compounded by the cumulative-primary
flipping onto the largest mis-labelled chunk and retro-branding the user's
real turns. Requiring co-occurrence makes a lone re-labelled turn NOT
parasitic, removing that whole false-positive class while a real two-voice
turn still trips it.

Pipeline position (AC2): wired BEFORE `emotion_emitter` so it observes
the raw finalized `TranscriptionFrame` straight from STT, before any
downstream processor. Mirrors EmotionEmitter / CheckpointManager
placement (Story 6.6 Dev #5 — the user aggregator CONSUMES
TranscriptionFrames, so any user-speech observer MUST sit upstream of
`context_aggregator.user()`).

Pass-through discipline: every observed frame is forwarded downstream
unchanged (Story 6.3's lesson — an observer that swallows a frame breaks
the LLM/TTS path).

Idempotent: fires the detection sequence ONCE per call via `_triggered`.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    OutputTransportMessageFrame,
    TranscriptionFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Detection tuning (Deviation #2 — early-warning + grace period).
_WINDOW_SIZE = 4
_TRIGGER_TURNS = 2
_MIN_SPEAKER_TOKENS = 3


class EnvironmentMonitor(FrameProcessor):
    """Observe user TranscriptionFrames; detect a parasitic background voice.

    Args:
        patience_tracker: The call's `PatienceTracker`. On detection the
            monitor calls `schedule_noisy_environment_exit()` directly
            (a sync method, mirroring how `CheckpointManager` calls
            `schedule_completion`) — the tracker owns the exit-line +
            `call_end` envelope sequence.
        window_size: Number of recent user turns kept in the sliding
            window (default 4).
        trigger_turns: How many turns in the window must contain a
            parasitic voice before firing (default 2).
        min_speaker_tokens: Minimum tokens a non-primary speaker must
            contribute WITHIN a turn for that turn to count as parasitic
            (default 3 — filters 1-2-token mis-diarization burps).
        enabled: Master switch (default True). When False the monitor is a
            pure pass-through observer — it never detects or hangs up. The
            live kill-switch (env `ENV_MONITOR_ENABLED=0`) for the
            diarization false-positive class while tuning, set in `bot.py`.
    """

    def __init__(
        self,
        *,
        patience_tracker: Any,
        input_gate: Any = None,
        window_size: int = _WINDOW_SIZE,
        trigger_turns: int = _TRIGGER_TURNS,
        min_speaker_tokens: int = _MIN_SPEAKER_TOKENS,
        enabled: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._patience_tracker = patience_tracker
        self._enabled = enabled
        # Story 6.11 fix (2026-05-30) — the InputGate placed after
        # transport.input(). Armed on detection to "stop listening" so the
        # loud parasite can't keep interrupting the exit line (smoke
        # call_id=205). Optional so unit tests can omit it.
        self._input_gate = input_gate
        self._window_size = window_size
        self._trigger_turns = trigger_turns
        self._min_speaker_tokens = min_speaker_tokens
        # Cumulative per-speaker token counts across the WHOLE call — used
        # only to decide which speaker id is the "primary" (the user). The
        # user dominates their own phone's mic, so the cumulative-max
        # speaker stabilises onto them within a turn or two even if a
        # single early turn is mis-diarized.
        self._cumulative: dict[str, int] = {}
        # Per-turn speaker→token-count maps for the last `window_size`
        # turns. Trigger evaluation re-scores each stored turn against the
        # CURRENT primary every turn, so a late-stabilising primary can't
        # leave stale verdicts in the window.
        self._window: deque[dict[str, int]] = deque(maxlen=window_size)
        # Idempotent: the detection sequence fires once per call.
        self._triggered = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Pass-through FIRST (mandatory observer discipline) so a raising
        # detection branch below can never swallow the frame from the
        # downstream LLM/TTS path.
        await self.push_frame(frame, direction)

        if self._triggered or not self._enabled:
            return
        # Only finalized user transcriptions carry a complete turn's tokens.
        # `getattr(..., False)` defaults interim frames OUT (same
        # conservative posture as EmotionEmitter / CheckpointManager —
        # never act on a half-word).
        if not (
            isinstance(frame, TranscriptionFrame) and getattr(frame, "finalized", False)
        ):
            return

        turn_counts = _speaker_token_counts(getattr(frame, "result", None))
        if turn_counts is None:
            # No diarization data on this frame (field absent, or no token
            # carried a speaker id) — can't decide, pass through silently
            # (AC2: missing diarization metadata = no detection).
            return

        self._window.append(turn_counts)
        for speaker, count in turn_counts.items():
            self._cumulative[speaker] = self._cumulative.get(speaker, 0) + count

        # Smoke-gate observability (AC3 spirit, one line per user turn —
        # same cadence as PatienceTracker's `patience_outcome`). THE
        # diagnostic for the open question "does Soniox actually assign a
        # DISTINCT speaker id to a parasitic voice on a single phone mic,
        # or merge everything onto one id?". A turn that reads
        # `speakers={'1': 12}` means Soniox merged (detection can never
        # fire); `speakers={'1': 9, '2': 4}` means it separated (the
        # feature's premise holds). Without this we couldn't tell a
        # non-trigger ("Soniox merged") from a too-high threshold.
        logger.info(
            "env_monitor turn speakers={} cumulative={} triggered={}",
            turn_counts,
            self._cumulative,
            self._triggered,
        )

        if self._is_parasitic_window():
            await self._on_parasitic_voice_detected()

    def _is_parasitic_window(self) -> bool:
        """True when ≥`trigger_turns` of the windowed turns each show a real
        overlapping second voice: a non-primary speaker with
        ≥`min_speaker_tokens` tokens AND the primary speaker present in the
        SAME turn (the Story 6.20 co-occurrence rule — see module docstring).
        """
        if not self._cumulative:
            return False
        # Primary = the cumulative-dominant speaker (the user). Ties broken
        # deterministically by speaker id so the choice is stable.
        primary = max(self._cumulative, key=lambda s: (self._cumulative[s], s))
        parasitic_turns = 0
        for turn in self._window:
            # Co-occurrence: the primary AND a substantial non-primary voice
            # must both be in THIS turn. A lone re-labelled single-speaker
            # turn (the Soniox label-flip false positive, call_id=223) has no
            # within-turn overlap and is therefore NOT parasitic.
            primary_present = turn.get(primary, 0) > 0
            has_parasite = any(
                speaker != primary and count >= self._min_speaker_tokens
                for speaker, count in turn.items()
            )
            if primary_present and has_parasite:
                parasitic_turns += 1
        return parasitic_turns >= self._trigger_turns

    async def _on_parasitic_voice_detected(self) -> None:
        """Fire-once: stop listening (arm the InputGate so the loud parasite
        can't interrupt the exit line), emit `env_warning` downstream, then
        schedule the in-character noisy-environment exit via the
        PatienceTracker."""
        self._triggered = True
        # ARM FIRST (Story 6.11 fix, smoke call_id=205) — mute the mic input
        # before anything else so the in-flight interruption storm stops
        # immediately and the exit line that PatienceTracker is about to
        # speak cannot be flushed by the continuing parasite voice.
        if self._input_gate is not None:
            self._input_gate.arm()
        # Distinct speakers seen recently (window union) — the user + the
        # parasitic voice(s). Reported to the client banner for context.
        detected_speakers = len({s for turn in self._window for s in turn})
        # INFO log makes the smoke gate observable from journalctl without
        # client-side instrumentation (AC3).
        logger.info(
            "env_warning emitted reason=background_voice detected_speakers={}",
            detected_speakers,
        )
        # Emit DOWNSTREAM so the envelope flows toward `transport.output()`
        # — the same proven client-bound path EmotionEmitter / Checkpoint
        # advanced envelopes ride (this monitor sits just upstream of
        # EmotionEmitter, which emits the same way in prod).
        await self.push_frame(
            OutputTransportMessageFrame(
                message={
                    "type": "env_warning",
                    "data": {
                        "reason": "background_voice",
                        "detected_speakers": detected_speakers,
                    },
                }
            ),
            FrameDirection.DOWNSTREAM,
        )
        # AC4 — the PatienceTracker owns the exit-line + call_end sequence.
        # Direct sync call (mirrors CheckpointManager → schedule_completion);
        # idempotent on the tracker side (`_hang_up_in_progress` guard).
        self._patience_tracker.schedule_noisy_environment_exit()


def _speaker_token_counts(result: Any) -> dict[str, int] | None:
    """Count tokens per speaker id in a Soniox `TranscriptionFrame.result`.

    `result` is the raw Soniox token-dict list (each `{"text", "is_final",
    ... , "speaker"}`); with diarization enabled, content tokens carry a
    `speaker` key (int or str). Returns a `{speaker_id: token_count}` map,
    or `None` when the frame carries no diarization data at all (not a
    list, or no token has a `speaker` key) — the caller treats `None` as
    "can't decide" and skips the turn.
    """
    if not isinstance(result, list):
        return None
    counts: dict[str, int] = {}
    for token in result:
        if not isinstance(token, dict):
            continue
        speaker = token.get("speaker")
        if speaker is None:
            continue
        key = str(speaker)
        counts[key] = counts.get(key, 0) + 1
    return counts or None
