"""Story 6.4 — PatienceTracker Pipecat FrameProcessor.

Owns the per-call silence timer, the patience meter, and the dramatic
hang-up sequence. Sits between `context_aggregator.user()` and `llm` so
it observes user `TranscriptionFrame`s after the aggregator finalizes a
turn (see `difficulty-calibration.md` AD-2).

Story 6.6 extensions:
  - New public method `apply_exchange_outcome(success: bool)`. Called
    by `CheckpointManager` after each `ExchangeClassifier` verdict.
    Adds `recovery_bonus` to the meter on success; adds `fail_penalty`
    (a non-positive int) on failure. Bounded to `[0, initial_patience]`.
    Wires the previously-dormant `fail_penalty` / `recovery_bonus`
    constructor kwargs (Story 6.4 stored them but did not consume them).
    Story 6.6 post-deploy follow-up (2026-05-18, Deviation #6): when
    the meter falls into the warning band (`<= _PATIENCE_WARNING_THRESHOLD`,
    default 25) on a failed exchange, push a one-shot `patience_warning_line`
    TTSSpeakFrame ("last chance" warning). When the meter reaches 0,
    schedule `character_hung_up` directly with the silence exit line —
    NOT only the silence ladder ends the call; an actively-speaking
    user who burns through every try also gets cut off. The warning is
    spent permanently once emitted (recovery via `recovery_bonus` does
    NOT re-arm it).
  - New public method `schedule_completion(survival_pct: int)`. Called
    by `CheckpointManager` when the FINAL checkpoint passes. Routes
    through the existing hang-up coroutine with `reason='survived'`
    and `hang_up_line_survived` as the spoken exit line.
  - New constructor kwarg `hang_up_line_survived` — the YAML
    `exit_lines.completion` line, wired through `resolve_patience_config`.
  - **Deviation #1 — two distinct survival_pct formulas.** When the
    completion path fires (`reason='survived'`), `survival_pct` is
    **100 by definition** (the user passed every checkpoint). When the
    silence-ladder or abuse-classifier path fires
    (`reason='character_hung_up'` / `'inappropriate_content'`),
    `survival_pct` is the patience-meter ratio:
    `int(self._patience / self._initial_patience * 100)`.
    Two paths, two formulas — do not unify.

The silence timer is **driven by the client**, not by
`BotStoppedSpeakingFrame`. The bot's "I have finished speaking" event
fires when the LiveKit outbound buffer is flushed — but the client's
ear still has 0.5-1.5 s of WebRTC jitter buffer + decoder + speaker
latency to drain. Using the server-side signal makes the silence timer
count from a moment ~1 s in the user's perceived future, which causes
"I waited 2 s and the character is already impatient" UX bugs.
Instead, the client's `VisemeScheduler.onSilenceConfirmed` (which
rides the PCM stream feeding the speaker — same source as lip-sync)
detects when the speaker has been silent for 600 ms after bot speech,
and publishes a `{"type":"playback_idle"}` envelope upstream via the
LiveKit data channel. `bot.py` routes that to
`PatienceTracker.handle_playback_idle()`, which starts the ladder.
Frame-of-reference for the timer is now the user's ear — not the
server's outbox.

The 4-tier silence ladder is implemented as a single `asyncio.Task`
running `_run_silence_ladder`. Cancellation is the canonical "user
spoke" signal — `asyncio.CancelledError` is re-raised silently inside
the coroutine (log noise on every user turn would be unhelpful).

The hang-up sequence is a second `asyncio.Task` that emits:
  1. `{"type":"hang_up_warning","data":{"seconds_remaining":5}}` envelope
  2. ~0.5 s pause to let the envelope flush over SCTP
  3. `TTSSpeakFrame(<exit_line>)` — character delivers the line
  4. Wait for `BotStoppedSpeakingFrame` (6.0 s safeguard against stuck
     TTS). If ZERO audio has been observed by the 3.0 s stall-detection
     mark, re-queue the SAME line exactly once and wait up to 5.0 s
     more (call 277, 2026-06-11 — a silent Cartesia stall ate the
     goodbye; see `_await_exit_line_delivery`)
  5. `{"type":"call_end","data":{...}}` envelope with reason + survival %
  6. Wait 8.0 s as a safety bound for the client to drain its local
     audio playback and disconnect itself (the canonical termination
     path is the client triggering `on_participant_left` server-side,
     which pushes `EndFrame` cleanly from `bot.py`'s handler). If the
     client never disconnects, the safety `EndFrame` below tears the
     pipeline down so it doesn't leak.
  7. `EndFrame()` (safety fallback) — pipecat tears down the pipeline

`checkpoints_passed=0` is hardcoded for 6.4 — Story 6.6 will wire it to
`CheckpointManager` (Deviation #2). The optional `abuse_classifier`
constructor arg is the `inappropriate_content` reason hook; production
wiring (`bot.py`) passes `None`, so the path is exercised only by the
unit test in 6.4 (Deviation #1).

The four "dormant" kwargs (`fail_penalty`, `recovery_bonus`,
`silence_hangup_seconds`, `escalation_thresholds`) are accepted by the
constructor and stored on the instance but NOT applied to behavior in
this story. They're wired now so Stories 6.6 (`ExchangeClassifier`
feeds `fail_penalty`/`recovery_bonus` into the meter) and 6.7
(`CheckpointManager` reads `escalation_thresholds`) can consume them
without breaking the constructor contract. `silence_hangup_seconds`
will land when per-difficulty timing scaling is implemented (DW1).

`BotStoppedSpeakingFrame` also drives a separate downstream emit on
every bot turn: a `{"type":"bot_speaking_ended","data":{}}` envelope.
This arms the client's `_awaitingPlaybackIdle` gate so the next PCM-
stream silence on the client's speaker (post-audio-drain) publishes
`playback_idle` upstream. Without that gate the client would treat
intra-utterance Cartesia pauses (~600 ms between sentences in a multi-
sentence greeting) as end-of-turn and start the silence ladder
prematurely.

Pass-through discipline: every observed frame is forwarded downstream
regardless of branch (Story 6.3's lesson re-applied — frame-stealing
breaks the LLM/TTS path).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# ============================================================
# Silence-ladder timing anchors (Story 6.4)
# ============================================================

# Stage 1 anchor (impatience face emit) is now per-difficulty (Story 6.13
# AC3): easy=4.5, medium=3.5, hard=2.5 — read from
# `_DIFFICULTY_PRESETS['ladder_impatience_seconds']` in scenarios.py and
# threaded through the `PatienceTracker(ladder_impatience_seconds=...)`
# constructor kwarg. The old module-level `_LADDER_IMPATIENCE_AT = 3.0`
# constant was deleted: smoke gate call_id=148 showed 3 s was too
# aggressive (natural response time ~1.5-2.5 s after perception).

# Stages 3-4 (anger face + hang-up) are anchored to the moment the
# user's ear hears the stage-2 prompt finish — NOT to absolute time
# since ladder start. The server waits for the prompt's own
# `playback_idle` to arrive from the client (which clears
# `_self_speaking`) before counting down anger + hang-up. Without
# this anchoring, the anger face fired ~1 s before the user even
# heard the prompt end, because the prompt's audio takes ~2-3 s to
# play out via WebRTC.
_POST_PROMPT_ANGER_DELAY = 3.0
_POST_ANGER_HANGUP_DELAY = 2.0

# Safety bound on waiting for the prompt's `playback_idle` to come
# back from the client. Generous so a slow-cellular re-buffer of the
# prompt audio still fits. If the signal is lost, we proceed anyway
# so the ladder doesn't wedge forever.
_PROMPT_PLAYBACK_TIMEOUT_SECONDS = 10.0


# ============================================================
# Hang-up sequence timing + safety bounds (Story 6.4)
# ============================================================

# Safety cap so a stuck TTS during the hang-up exit line cannot wedge
# the call indefinitely. 6.0 s is generous for a 2-sentence line. This
# governs LINE COMPLETION (BotStoppedSpeakingFrame) when audio is
# actually flowing; the silent-stall decision happens much earlier, at
# `_HANG_UP_TTS_STALL_DETECT_SECONDS` below.
_HANG_UP_TTS_TIMEOUT_SECONDS = 6.0

# Call 277 follow-up (2026-06-11, Walid: "6 s feels like a bug") — how
# long after the exit-line push we wait before declaring a SILENT stall
# (zero audio at the transport) and re-queuing. First audio normally
# reaches the transport 0.3-1.0 s after dispatch, and this signal is
# SERVER-side (Cartesia → us), untouched by the phone's network — so
# 3.0 s is a 3-10x margin over the worst nominal case while halving the
# dead air vs the 6.0 s completion cap. Do NOT lower it further: a
# slow-but-alive synthesis riding a Cartesia WebSocket reconnect (~1-2 s)
# would get re-queued on top of itself → back-to-back double goodbye.
_HANG_UP_TTS_STALL_DETECT_SECONDS = 3.0

# Call 277 (2026-06-11) — bounded wait for the SINGLE re-queue of an exit
# line whose first synthesis stalled silently (zero audio ever reached
# the transport). 5.0 s covers synthesis dispatch + first audio + a short
# line's playout on the retry; a second stall simply expires this wait
# and the call-end path proceeds — the worst-case extra delay on call
# teardown is bounded by this constant. See `_await_exit_line_delivery`.
_HANG_UP_TTS_RETRY_TIMEOUT_SECONDS = 5.0

# Brief pauses to let envelopes flush over the data channel before the
# pipeline tears down. SCTP slow-start means a freshly-opened channel
# needs a beat to actually ship a small message; these values are the
# minimums that consistently land on-device under cellular conditions
# (smoke-validated alongside Story 6.3's emit pattern).
_HANG_UP_PRE_TTS_DELAY = 0.5

# Server-side safety bound between the `call_end` envelope and the
# downstream `EndFrame`. Normal operation: the client uses its native
# audio-playback signal (`VisemeScheduler.onSilenceConfirmed`, which
# rides the same PCM stream that drives the lips) to disconnect the
# LiveKit room when its local speaker has actually finished playing
# the exit line. The bot's `on_participant_left` handler then pushes
# `EndFrame` and the pipeline tears down naturally — this timeout
# never fires. It only matters if the client crashes / loses network
# mid-exit, in which case 8 s is generous enough that even a slow-
# cellular re-buffer of the full exit line completes before the
# server force-terminates.
_HANG_UP_CLIENT_DRAIN_TIMEOUT_SECONDS = 8.0


# ============================================================
# Reason whitelist + warning band (Story 6.6 + Deviation #6)
# ============================================================

# The meter band at or below which a one-shot "last chance" warning
# fires on the next failed exchange. Hardcoded for MVP; could be
# per-difficulty later if the calibration data warrants it.
_PATIENCE_WARNING_THRESHOLD = 25

# `EndCallIn.reason` Literal whitelist (server-side wire format).
# Aligns with Story 6.5 D4 — the epic spec said "completed" but the
# wire format is "survived". Story 6.6 ships the wire token.
_REASON_SILENCE = "character_hung_up"
_REASON_INAPPROPRIATE = "inappropriate_content"
_REASON_SURVIVED = "survived"
# Story 6.11 — parasitic background-voice detection (EnvironmentMonitor).
# The character announces in-character it can't hear, then hangs up; the
# call is refunded server-side (`gifted`). Shares the existing hang-up
# infra (exit-line TTS + `call_end` envelope), differing only in the
# spoken line and the wire `reason`.
_REASON_NOISY_ENVIRONMENT = "noisy_environment"
_VALID_REASONS = frozenset(
    {
        _REASON_SILENCE,
        _REASON_INAPPROPRIATE,
        _REASON_SURVIVED,
        _REASON_NOISY_ENVIRONMENT,
    }
)

# Story 6.18 — pseudo-reason for the one-shot patience-WARNING line. NOT a
# hang-up reason (deliberately excluded from `_VALID_REASONS` so it can never
# reach `_schedule_hang_up`); used only to pick the warning variant of the
# generation guidance in `_resolve_exit_line` / `_emit_patience_warning`.
_REASON_PATIENCE_WARNING = "patience_warning"

# SPIKE (spike/character-led, 2026-07-01) — generation-guidance-only pseudo-reason
# for the character-led bail. NOT a client/wire reason (the bail still sends
# `character_hung_up` to the client); it only selects the disrespect-appropriate,
# anti-fabrication exit-line guidance so the generator stops inventing a "your
# story's changed" accusation (call 353). Excluded from `_VALID_REASONS`, like
# `_REASON_PATIENCE_WARNING`.
_REASON_SPIKE_BAIL = "spike_character_led_bail"


def step_patience(
    meter: int,
    *,
    success: bool,
    initial_patience: int,
    fail_penalty: int,
    recovery_bonus: int,
) -> int:
    """Pure patience-meter step shared by `PatienceTracker.apply_exchange_outcome`
    (prod) and the Story 6.15 text calibration harness.

    On success add `recovery_bonus` (capped at `initial_patience`); on failure
    add `fail_penalty` (a non-positive int, floored at 0). No side effects — so
    the offline validator computes the SAME meter trajectory prod does without
    forking the formula (Story 6.15 AC1 / Task 10).
    """
    if success:
        return min(initial_patience, meter + recovery_bonus)
    return max(0, meter + fail_penalty)


class PatienceTracker(FrameProcessor):
    """4-tier silence escalation + meter-driven character hang-up.

    See module docstring. Wire between `context_aggregator.user()` and
    `llm` in the pipeline.

    Args:
        initial_patience: Starting meter value (per difficulty preset).
        silence_penalty: Meter cost applied when stage 4 fires
            (= the deduction that takes the meter toward 0 when the
            user has been silent through a full ladder run).
        silence_prompt_seconds: Wall-clock time from ladder start at
            which the verbal prompt fires (stage 2 anchor). Stages 3
            and 4 are anchored to the user-perceived prompt-end, not
            to absolute time — so `silence_hangup_seconds` from the
            difficulty preset is documentation-only in this story.
        total_checkpoints: Carried into the `call_end` envelope so
            the client can render `2/5`-style progress in a future
            debrief screen. Story 6.4 always sends
            `checkpoints_passed=0`; Story 6.6 will wire the live
            counter via `CheckpointManager`.
        silence_prompt_line: Spoken at stage 2.
        hang_up_line_silence: Spoken before terminating on silence.
        hang_up_line_inappropriate: Spoken before terminating on
            abuse-classifier hit.
        abuse_classifier: Optional `(text) -> bool` hook. `None` in
            production for 6.4; the unit test injects a stub to cover
            the `inappropriate_content` reason path. Story 6.6's
            `ExchangeClassifier` is the production trigger.
        fail_penalty: Meter cost when an exchange is judged failed.
            Stored on the instance for Story 6.6 (`ExchangeClassifier`)
            consumption; NOT applied to behavior in Story 6.4.
        recovery_bonus: Meter recovery when an exchange is judged
            successful. Stored for Story 6.6 consumption; NOT applied
            in Story 6.4.
        silence_hangup_seconds: Hard cap from difficulty preset on the
            total silence-to-hang-up window. Stored for forward-compat
            with per-difficulty timing scaling (DW1); NOT applied in
            Story 6.4 (the ladder is anchored to `silence_prompt_seconds`
            + the hardcoded `_POST_PROMPT_ANGER_DELAY` /
            `_POST_ANGER_HANGUP_DELAY` constants).
        escalation_thresholds: Patience-meter breakpoints for the
            visual escalation ladder. Stored for Story 6.7
            (`CheckpointManager`) consumption; NOT applied in Story 6.4.
        hang_up_line_generator: Story 6.18 — optional async callable
            `(reason, extra_user_text=None) -> str | None` that regenerates
            the exit / patience-warning line IN CHARACTER from the live
            transcript (injected in `bot.py`, closure over `llm_context` + the
            LLM config; the LLM wiring stays out of this transport-free
            processor). `extra_user_text` lets the survived path append the
            winning user turn that CheckpointManager suppressed from the LLM
            context (Deviation #7) so the closing line can ground on it.
            `None` (default) → the canned YAML lines are used unchanged (also
            the `HANGUP_LINE_GENERATION=0` kill-switch path). A `None` RETURN
            or any error → fall back to the canned line; the generator must
            never wedge or crash the hang-up.

    Raises:
        ValueError: If `initial_patience <= 0`. The survival-percent
            arithmetic would otherwise silently degrade against a
            zero/negative denominator.
    """

    def __init__(
        self,
        *,
        initial_patience: int,
        silence_penalty: int,
        silence_prompt_seconds: float,
        ladder_impatience_seconds: float,
        total_checkpoints: int,
        fail_penalty: int = 0,
        recovery_bonus: int = 0,
        silence_hangup_seconds: float = 10.0,
        escalation_thresholds: list[int] | None = None,
        silence_prompt_line: str = "Hello? Are you still there?",
        hang_up_line_silence: str = "I don't have time for this. Goodbye.",
        hang_up_line_inappropriate: str = "I'm done with this. Goodbye.",
        hang_up_line_survived: str = ("Looks like you got what you came for. Goodbye."),
        hang_up_line_noisy_environment: str = (
            "Look, I can't hear you over all that background noise. "
            "Try me again when you've got somewhere quieter."
        ),
        patience_warning_line: str = (
            "*sighs* Look, are you ordering or not? Last chance."
        ),
        abuse_classifier: Callable[[str], bool] | None = None,
        hang_up_line_generator: Callable[..., Awaitable[str | None]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if initial_patience <= 0:
            raise ValueError(f"initial_patience must be > 0, got {initial_patience!r}")
        # Story 6.13 AC3 — `ladder_impatience_seconds` replaces the deleted
        # module-level `_LADDER_IMPATIENCE_AT = 3.0` constant. Constructor
        # guard rejects only zero/negative + non-number values so a bogus
        # YAML override surfaces at PatienceTracker init rather than
        # asyncio.sleep'ing on a negative duration mid-ladder. Operational
        # range (0.5 ≤ x ≤ 10.0) is enforced upstream in
        # `resolve_patience_config`; tests that need fast ladders pass
        # sub-0.5 values directly without tripping the range guard.
        if (
            not isinstance(ladder_impatience_seconds, (int, float))
            or isinstance(ladder_impatience_seconds, bool)
            or ladder_impatience_seconds <= 0
        ):
            raise ValueError(
                "ladder_impatience_seconds must be a positive number, "
                f"got {ladder_impatience_seconds!r}"
            )
        # Story 6.6 review patch — defensive type guards on the kwargs
        # that Story 6.6 newly consumes via `apply_exchange_outcome` and
        # `CheckpointManager.is_terminal_turn`. In production these
        # values flow from `resolve_patience_config`, which already
        # type-checks them; but tests that bypass the resolver MUST get
        # a loud `TypeError` instead of an `unsupported operand` mid-
        # call when `self._patience + self._fail_penalty` runs. Reject
        # bool explicitly — `isinstance(True, int)` is True in Python.
        if not isinstance(fail_penalty, int) or isinstance(fail_penalty, bool):
            raise TypeError(
                f"fail_penalty must be an int (not bool), got {fail_penalty!r}"
            )
        if not isinstance(recovery_bonus, int) or isinstance(recovery_bonus, bool):
            raise TypeError(
                f"recovery_bonus must be an int (not bool), got {recovery_bonus!r}"
            )
        self._initial_patience = initial_patience
        self._patience = initial_patience
        self._silence_penalty = silence_penalty
        self._silence_prompt_seconds = silence_prompt_seconds
        # Story 6.13 AC3 — per-difficulty stage 1 anchor (was the deleted
        # module constant `_LADDER_IMPATIENCE_AT = 3.0`). Easy preset
        # raises this to 4.5 s to match natural-response timing observed
        # in call_id=148; medium 3.5 s; hard 2.5 s.
        self._ladder_impatience_seconds = float(ladder_impatience_seconds)
        self._total_checkpoints = total_checkpoints
        # Story 6.7 review (2026-05-20) — CheckpointManager calls
        # `set_checkpoints_passed` on every state change so the
        # `call_end` envelope carries the live count. Retires the
        # Story 6.4 hardcoded `checkpoints_passed=0` placeholder. Used
        # by both the survived (count == total) and hang_up
        # (count < total) paths in `_run_hang_up`.
        self._checkpoints_passed: int = 0
        # Story 6.20 AC3 — the REAL set of met-goal indices (author order),
        # mirrored from CheckpointManager alongside `_checkpoints_passed` so
        # the `call_end` envelope carries WHICH goals were met, not just how
        # many. A future debrief can then reconstruct the exact set even when
        # goals flipped out of order (the count alone would mislabel them as
        # the first N). Empty until the first flip.
        self._goals_met_indices: list[int] = []
        # Story 7.1 — the reason this call ended (`character_hung_up`,
        # `inappropriate_content`, `noisy_environment`, `survived`), recorded
        # when `call_end` is emitted so the bot's teardown debrief generator can
        # read it (AC9). Stays None when the tracker never drove the end (the
        # user hung up / the network dropped) — the bot then defaults to
        # `user_hangup`. See `call_end_reason`.
        self._call_end_reason: str | None = None
        self._silence_prompt_line = silence_prompt_line
        self._hang_up_line_silence = hang_up_line_silence
        self._hang_up_line_inappropriate = hang_up_line_inappropriate
        # Story 6.6 — exit line for the completion path. Sourced from
        # YAML `exit_lines.completion` via `resolve_patience_config`.
        self._hang_up_line_survived = hang_up_line_survived
        # Story 6.11 — exit line for the noisy-environment path. Sourced
        # from YAML `exit_lines.noisy_environment` via
        # `resolve_patience_config` (falls back to the generic default in
        # `NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT` when the YAML omits it).
        self._hang_up_line_noisy_environment = hang_up_line_noisy_environment
        # Story 6.6 post-deploy (2026-05-18, Deviation #6) — the "last
        # chance" warning line fired once per call when the meter falls
        # into the warning band on a failed exchange.
        self._patience_warning_line = patience_warning_line
        # One-shot flag: True once the warning has been emitted in this
        # call. `recovery_bonus` pulling the meter back above the
        # threshold does NOT clear it — the user's one warning is spent.
        self._warning_emitted = False
        # Story 6.6 — track the fire-and-forget warning push task so
        # `cleanup()` can drain it on shutdown. Without this the task
        # would be GC'd while pending → "Task was destroyed but it is
        # pending!" log noise (same hygiene as `_silence_task` /
        # `_hang_up_task`).
        self._warning_task: asyncio.Task[None] | None = None
        self._abuse_classifier = abuse_classifier
        # Story 6.18 — optional dynamic exit/warning-line generator. None
        # keeps the canned YAML lines (the kill-switch path); a callable
        # regenerates the line in-character from the live transcript, with
        # the canned line as fallback. See `_resolve_exit_line`.
        self._hang_up_line_generator = hang_up_line_generator
        # Story 6.6 — survival_pct override threaded by
        # `schedule_completion` so the `_run_hang_up` arithmetic
        # produces 100 (checkpoints-passed) instead of the meter
        # ratio. None on the silence/abuse paths (meter ratio wins).
        self._pending_survival_pct: int | None = None
        # Story 6.18 review (Decision #2 / Option A) — the winning user turn
        # CheckpointManager suppressed from the LLM context (Deviation #7),
        # threaded by `schedule_completion` so the survived exit line can be
        # generated FROM the answer that actually won. None on all other paths.
        self._pending_winning_user_text: str | None = None

        # Dormant fields — wired for forward-compat with Stories 6.6
        # / 6.7 / DW1. Stored on the instance so the constructor
        # signature matches AC1 verbatim; values are NOT applied to
        # behavior in Story 6.4.
        self._fail_penalty = fail_penalty
        self._recovery_bonus = recovery_bonus
        self._silence_hangup_seconds = silence_hangup_seconds
        self._escalation_thresholds: list[int] = (
            list(escalation_thresholds) if escalation_thresholds is not None else []
        )

        self._silence_task: asyncio.Task[None] | None = None
        self._hang_up_task: asyncio.Task[None] | None = None
        self._hang_up_in_progress = False
        # SPIKE (spike/character-led, 2026-06-30) — True for the duration of a
        # character-LED hang-up (the character emitted <end_call>). It reuses the
        # `_REASON_SILENCE` ("character_hung_up") teardown but adds the abuse-path
        # InterruptionFrame (the trigger fires WHILE the character's reply is
        # in-flight) and reports a checkpoint-based survival_pct (the meter is no
        # longer the truth in spike mode). Reset in `_run_hang_up`'s finally.
        self._spike_character_led_bail = False
        # Set by `cleanup()` so the hang-up coroutine's "wait for
        # client to disconnect" sleep can release immediately on
        # pipeline teardown instead of running the full 8 s safety
        # timeout (which would log a misleading "client never
        # disconnected" warning on every happy-path call).
        self._shutdown_event: asyncio.Event = asyncio.Event()
        # Set when stage 2 pushes the prompt TTSSpeakFrame; cleared in
        # `handle_playback_idle` when the prompt's client-confirmed
        # `playback_idle` arrives back from the data channel. The flag
        # routes that specific playback_idle to "release stage 3 wait"
        # instead of "start a new ladder" — without it the prompt's
        # own end-of-playback signal would loop the ladder back to
        # stage 1 and the call would never hang up.
        self._self_speaking = False
        # Created fresh inside `_run_hang_up` before pushing the exit
        # line; set in `process_frame` when the resulting
        # `BotStoppedSpeakingFrame` arrives.
        self._speaking_done: asyncio.Event | None = None
        # Call 277 (2026-06-11) — True once a `BotStartedSpeakingFrame`
        # has been observed AFTER the exit-line TTSSpeakFrame push (= the
        # exit line's audio actually reached the transport). Lets
        # `_await_exit_line_delivery` distinguish a SILENT TTS stall
        # (re-queue the line once) from a slow-but-audible line (never
        # re-queue — that would double-speak the goodbye). Reset in the
        # same synchronous block that creates `_speaking_done`.
        self._exit_line_audio_started = False
        # Created fresh inside `_run_silence_ladder` stage 2 before
        # pushing the verbal prompt; set in `handle_playback_idle`
        # when the prompt's client-confirmed `playback_idle` arrives
        # (clearing `_self_speaking`). The ladder coroutine awaits
        # this event so stages 3-4 count down from the moment the
        # user's ear heard the prompt finish, not from the moment
        # the server pushed the TTSSpeakFrame.
        self._prompt_played_event: asyncio.Event | None = None

        # Smoke-gate observability (AC9 item 5): log the resolved
        # config so a journalctl tail confirms YAML override + preset
        # fallback for the call under test. Logs every field accepted
        # by the constructor — including the dormant ones — so an
        # operator can verify the YAML→preset resolution end-to-end.
        logger.info(
            "PatienceTracker config initial_patience={} fail_penalty={} "
            "silence_penalty={} recovery_bonus={} silence_prompt_seconds={} "
            "ladder_impatience_seconds={} silence_hangup_seconds={} "
            "escalation_thresholds={} total_checkpoints={}",
            initial_patience,
            fail_penalty,
            silence_penalty,
            recovery_bonus,
            silence_prompt_seconds,
            self._ladder_impatience_seconds,
            silence_hangup_seconds,
            self._escalation_thresholds,
            total_checkpoints,
        )
        # Story 6.18 (AC7) — confirm in journalctl whether dynamic exit-line
        # generation is wired for this call (driven by HANGUP_LINE_GENERATION
        # in bot.py). The per-hang-up `source=generated|fallback` log lands at
        # the substitution point in `_resolve_exit_line`.
        logger.info(
            "PatienceTracker hang_up_line_generation={}",
            self._hang_up_line_generator is not None,
        )

    # ---------- Public read-only properties (Story 6.6 Deviation #7) ----------
    # `CheckpointManager` needs to read the meter + fail_penalty + hangup
    # status to decide whether a turn is terminal (preemptive sync path).
    # Exposing these via properties keeps the coupling explicit but
    # disciplined: read access is sanctioned, direct mutation is not.

    @property
    def patience(self) -> int:
        """Current patience meter value, bounded `[0, initial_patience]`."""
        return self._patience

    @property
    def fail_penalty(self) -> int:
        """Configured per-fail meter delta (a non-positive int)."""
        return self._fail_penalty

    @property
    def is_hanging_up(self) -> bool:
        """True once a hang-up sequence has been scheduled (set
        synchronously by `_schedule_hang_up` / `schedule_completion`)."""
        return self._hang_up_in_progress

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Pass-through is MANDATORY: PatienceTracker observes, never
        # consumes. Forward first so a follow-up branch that raises
        # cannot swallow the frame from downstream.
        await self.push_frame(frame, direction)

        if (
            isinstance(frame, BotStoppedSpeakingFrame)
            and direction == FrameDirection.UPSTREAM
        ):
            # The bot finished its server-side outbound — but the
            # client's speaker still has 0.5-1.5 s of buffered audio
            # to play. Tell the client we're done with this turn so
            # it can arm its "publish playback_idle on the next
            # confirmed silence" gate.
            #
            # Without this gate the client treats any 600 ms intra-
            # sentence Cartesia pause (e.g. between "Hi." and
            # "Welcome to The Golden Fork.") as the end of the
            # bot's turn and publishes `playback_idle` prematurely
            # → ladder starts mid-greeting → stage 1 impatience
            # fires while the user is still listening.
            #
            # Direction-gated: pipecat 0.0.108's BaseOutputTransport
            # (see `_bot_stopped_speaking()`) pushes BSF in BOTH
            # directions — downstream goes into the sink (nowhere,
            # output is the last processor), upstream travels BACK up
            # the pipeline. PatienceTracker sits UPSTREAM of the
            # output transport, so the only direction we actually see
            # is UPSTREAM. The original Story 6.4 implementation
            # checked DOWNSTREAM (latent bug — silent regression in
            # prod for 2 days; no escalation log ever fired in
            # journalctl despite multiple device tests). Fixed 2026-
            # 05-15 as Déviation #28.
            logger.info("PatienceTracker: pushing bot_speaking_ended envelope")
            await self.push_frame(
                OutputTransportMessageFrame(
                    message={"type": "bot_speaking_ended", "data": {}}
                ),
                FrameDirection.DOWNSTREAM,
            )

            # The hang-up coroutine awaits the same frame to release
            # its exit-line wait so it can push call_end + safety
            # EndFrame.
            if self._hang_up_in_progress:
                event = self._speaking_done
                if event is not None:
                    event.set()
        elif isinstance(frame, TranscriptionFrame):
            finalized = getattr(frame, "finalized", True)
            text = (getattr(frame, "text", "") or "").strip()
            # Turn-taking fix (2026-06-08 smoke gate) — cancel the silence
            # ladder on the FIRST sign of user speech, INTERIM frames
            # included, so the "Hello? Are you still there?" prompt can never
            # fire while the user is mid-sentence. Previously only FINALIZED
            # frames cancelled (interim returned early here), so a hesitating
            # B1 learner ("uh, uh, in front of...") got the prompt spoken over
            # their own voice (cop call 2026-06-08: the stage-2 prompt fired
            # ~0.3 s AFTER interim words were already streaming). Per the cost
            # analysis in server/CLAUDE.md §1, a stray-artifact cancel only
            # DEFERS the silence hangup by one ladder cycle (recoverable); a
            # prompt spoken over live speech is the bad UX we are killing.
            # `finalized` still defaults to True so an STT that drops the
            # field keeps working.
            #
            # `_self_speaking` guard: while WE are playing our own stage-2
            # prompt, an interim frame is almost certainly the user's mic
            # echoing that prompt — it must NOT cancel the ladder (that would
            # abort the hang-up escalation on a genuinely silent user). A
            # FINALIZED frame during self-speaking IS a real answer to the
            # prompt and still cancels.
            if finalized or (text and not self._self_speaking):
                self._cancel_silence_timer()
            # Interim frames only reset the ladder; the abuse-classifier and
            # downstream turn logic run on the finalized turn only.
            if not finalized:
                return
            if not text:
                return
            if self._abuse_classifier is not None and not self._hang_up_in_progress:
                # Story 6.6 will inject an LLM-backed `ExchangeClassifier`
                # here — defensive try/except so a transient classifier
                # error never kills the pipeline. The unit test for 6.4
                # injects a pure-Python lambda that never raises.
                try:
                    is_abuse = self._abuse_classifier(text)
                except Exception:
                    logger.exception(
                        "PatienceTracker: abuse_classifier raised; ignoring"
                    )
                    return
                if is_abuse:
                    self._schedule_hang_up(_REASON_INAPPROPRIATE)
        elif isinstance(frame, InterimTranscriptionFrame):
            # Story 10.8 (Stream A3) — the user is AUDIBLY producing speech.
            # Soniox streams interim results as `InterimTranscriptionFrame`, a
            # SEPARATE class from the finalized `TranscriptionFrame` above (the
            # server/CLAUDE.md §1 frame-type trap), so interims NEVER reached the
            # finalized branch's cancel path. The branch above (L639) was always
            # MEANT to cancel on interim speech (`text and not self._self_speaking`)
            # but keyed on `TranscriptionFrame(finalized=False)`, which Soniox
            # never emits — and Soniox emits NO `UserStartedSpeakingFrame` either.
            # So a long, no-pause utterance Soniox never finalized (call 341:
            # ~51 words, interims streaming) produced NO cancel signal and the
            # silence ladder ran to a hang-up WHILE the user was still talking.
            # Cancel the ladder on real interim speech — the missing branch.
            #
            # Per server/CLAUDE.md §1's cost analysis, a stray-artifact interim
            # cancel only DEFERS a genuine-silence hang-up by one ladder cycle
            # (the next post-bot-turn `playback_idle` re-arms it) — recoverable;
            # a prompt/hang-up spoken over live speech is the bad UX we kill.
            # `_self_speaking` guard (same as the finalized branch): while WE
            # play our own stage-2 prompt, an interim is almost certainly the
            # user's mic echoing it — it must NOT cancel the hang-up escalation
            # on a genuinely silent user. A genuine barge-in still cancels when
            # it FINALIZES (the finalized branch's `if finalized or ...`).
            text = (getattr(frame, "text", "") or "").strip()
            if text and not self._self_speaking:
                self._cancel_silence_timer()
        elif isinstance(frame, UserStartedSpeakingFrame):
            # Defensive: VAD start may land before the STT finalizes
            # a transcription. Cancel the ladder now so a user mid-
            # speech doesn't trip stage 1 emit.
            self._cancel_silence_timer()
        elif (
            isinstance(frame, BotStartedSpeakingFrame)
            and direction == FrameDirection.UPSTREAM
        ):
            # Story 6.13 AC2 (2026-05-26) — pause the silence ladder when
            # the bot starts speaking. Pipecat 0.0.108's
            # BaseOutputTransport._bot_started_speaking pushes BSF in
            # both directions; same direction logic as
            # BotStoppedSpeakingFrame above — PatienceTracker sits
            # UPSTREAM of the output, so the only direction we
            # observe is UPSTREAM (the downstream copy goes into the
            # sink).
            #
            # Why: smoke gate call_id=150 T6 (2026-05-26) showed the
            # ladder counting down WHILE Tina was actively speaking —
            # the client's `playback_idle` for the prior turn armed
            # the ladder, then Tina's new turn started mid-stage-1,
            # and "Hello? Are you still there?" fired AT 45.501s
            # while Tina was mid-sentence (T6 spans 39.498-45.998).
            # Cancelling on BSF guarantees no ladder event can
            # interrupt a bot turn that is audibly playing on the
            # user's device. The next `playback_idle` (post-Tina-
            # turn) re-arms the ladder cleanly.
            #
            # Patience meter is NOT touched — we're not punishing the
            # bot for speaking; we're simply suppressing the ladder
            # event window. Same semantics as a user-speech cancel:
            # next playback_idle re-arms.
            #
            # Call 277 (2026-06-11) — once the hang-up exit line has been
            # pushed (`_speaking_done` exists only from that point in the
            # hang-up sequence), a bot speech start means its audio reached
            # the transport: record it so `_await_exit_line_delivery` never
            # re-queues a line that is already audibly playing. The retry
            # is strictly for ZERO-audio stalls. Gating on `_speaking_done`
            # (not just `_hang_up_in_progress`) keeps the tail of a just-
            # interrupted reply landing during the pre-TTS delay from
            # masquerading as exit-line audio.
            if self._hang_up_in_progress and self._speaking_done is not None:
                self._exit_line_audio_started = True
            # Story 6.13 review (2026-05-27) — `_self_speaking` guard is
            # LOAD-BEARING. When the ladder reaches stage 2 it pushes its
            # OWN verbal prompt ("Hello? Are you still there?") downstream
            # and sets `_self_speaking = True`; that prompt's audio makes
            # the output transport emit a BotStartedSpeakingFrame which
            # travels right back up here. Without this guard we'd cancel
            # the very ladder task that is mid-flight awaiting
            # `_prompt_played_event` — killing stages 3 (anger) + 4
            # (silence hang-up) so the character NEVER hangs up on a
            # silent user. A real character turn (the AC2 case this branch
            # exists for) has `_self_speaking == False` and still cancels
            # as intended.
            if not self._self_speaking:
                self._cancel_silence_timer()

    def handle_playback_idle(self) -> None:
        """Client-driven trigger — the user's speaker has been silent
        for the configured confirmation window after bot speech.

        Wired from `bot.py`'s `on_data_received` event handler when
        the client publishes a `{"type":"playback_idle"}` envelope
        via `room.localParticipant?.publishData(...)`. The client
        fires this from `VisemeScheduler.onSilenceConfirmed`, which
        rides the same PCM stream that drives lip-sync — so the
        timer's frame-of-reference is the user's ear, not the
        server's outbox.

        Guards:
          - Hang-up in progress → ignore (the call is ending).
          - `_self_speaking` (we just pushed the stage-2 prompt
            ourselves) → clear the flag, set the prompt-played
            event so the ladder coroutine's stage-2 → stage-3 wait
            releases. Stages 3 and 4 then count down from THIS
            moment (= user's ear heard the prompt finish), so the
            anger face never fires while the prompt audio is still
            playing. Do NOT restart the ladder in this branch —
            otherwise the prompt's own playback_idle would loop the
            ladder back to stage 1 and the hang-up would never fire.
        """
        if self._hang_up_in_progress:
            return
        if self._self_speaking:
            self._self_speaking = False
            # Unblock the ladder coroutine waiting at stage 2 → stage 3.
            # Stages 3-4 now count down from THIS moment (= user's ear
            # heard the prompt finish), not from stage 2's push.
            event = self._prompt_played_event
            if event is not None:
                event.set()
            logger.info(
                "PatienceTracker: playback_idle while self-speaking — "
                "prompt audio drained; releasing stage 3 wait"
            )
            return
        # Concurrent-safety: SCTP retransmits or fast back-to-back
        # client emits can deliver `playback_idle` twice for the same
        # bot turn. A second call while a ladder is already running
        # would otherwise cancel-and-restart it, briefly leaving two
        # tasks alive on the event loop and re-running stage 1 from
        # zero. Drop the duplicate.
        prior = self._silence_task
        if prior is not None and not prior.done():
            logger.info(
                "PatienceTracker: playback_idle while ladder running — "
                "duplicate envelope, ignored"
            )
            return
        logger.info("PatienceTracker: playback_idle — starting silence ladder")
        self._start_silence_timer()

    async def cleanup(self) -> None:
        """Drain ladder + hang-up tasks on pipeline shutdown.

        Without this hook a pending `asyncio.Task` is GC'd while
        unfinished → `Task was destroyed but it is pending!` log noise
        (Story 6.3 EmotionEmitter shipped the same pattern).

        Sets `_shutdown_event` first so any hang-up coroutine sleeping
        on the post-`call_end` client-disconnect timeout releases
        immediately rather than running the full 8 s safety window and
        emitting a misleading "client never disconnected" warning on
        every clean teardown.
        """
        await super().cleanup()
        self._shutdown_event.set()
        await self._cancel_silence_timer_and_drain()
        prior_hang_up = self._hang_up_task
        if prior_hang_up is not None and not prior_hang_up.done():
            prior_hang_up.cancel()
            await asyncio.gather(prior_hang_up, return_exceptions=True)
        self._hang_up_task = None
        # Story 6.6 Deviation #6 — drain the warning push task too.
        prior_warning = self._warning_task
        if prior_warning is not None and not prior_warning.done():
            prior_warning.cancel()
            await asyncio.gather(prior_warning, return_exceptions=True)
        self._warning_task = None

    # ---------- Story 6.6 — checkpoint outcome + completion ----------

    def apply_exchange_outcome(self, success: bool) -> None:
        """Apply `fail_penalty` (failure) or `recovery_bonus` (success) to the meter.

        Called by `CheckpointManager` after each `ExchangeClassifier`
        verdict. The meter is bounded `[0, initial_patience]`.

        On a failed exchange (`success=False`):
          - If the meter drops to **zero**: schedule `character_hung_up`
            with the silence exit line ("I don't have time for this.
            Goodbye."). An actively-speaking user who burned through
            every try gets cut off — same outcome as a silent user,
            different trigger.
          - Else if the meter drops into the **warning band**
            (`<= _PATIENCE_WARNING_THRESHOLD`, default 25): push the
            `patience_warning_line` as a TTSSpeakFrame ("last chance"
            warning). One-shot per call — `recovery_bonus` pulling the
            meter back above the threshold does NOT re-arm the warning.

        Recovery is additive (positive `recovery_bonus`); penalty is
        additive (`fail_penalty` is non-positive). Idempotent w.r.t.
        concurrent calls — single event loop, no locks needed.
        """
        if self._hang_up_in_progress:
            # The call is ending; further outcome events from a stale
            # in-flight classifier task MUST NOT mutate the meter.
            return
        # Pure meter math (shared with the Story 6.15 harness via
        # `step_patience`). `_fail_penalty` is a non-positive int; the helper
        # floors at 0 on failure and caps at `_initial_patience` on success.
        self._patience = step_patience(
            self._patience,
            success=success,
            initial_patience=self._initial_patience,
            fail_penalty=self._fail_penalty,
            recovery_bonus=self._recovery_bonus,
        )
        logger.info(
            "patience_outcome success={} patience={}/{}",
            success,
            self._patience,
            self._initial_patience,
        )

        # Story 6.6 post-deploy (Deviation #6) — meter-driven hangup and
        # last-chance warning ladder. Only checked on failed exchanges;
        # a successful exchange that crosses a threshold downward
        # (impossible by construction since recovery_bonus >= 0) would
        # not need to trigger anything.
        if not success:
            if self._patience == 0:
                # Meter depleted while user was actively trying. Same
                # exit line as silence-driven hangup ("I don't have
                # time for this. Goodbye.") — semantically the same
                # outcome from the user's POV.
                logger.info("patience_meter_zero — scheduling hang-up")
                self._schedule_hang_up(_REASON_SILENCE)
                return
            if (
                self._patience <= _PATIENCE_WARNING_THRESHOLD
                and not self._warning_emitted
                and (self._warning_task is None or self._warning_task.done())
            ):
                logger.info(
                    "patience_warning emitting at patience={}/{}",
                    self._patience,
                    self._initial_patience,
                )
                # Fire-and-forget the TTSSpeakFrame push so this sync
                # method stays sync (matches `_schedule_hang_up`
                # pattern). The caller is already in an event loop
                # context (CheckpointManager._classify_and_advance).
                # Store the task so `cleanup()` can drain it on
                # shutdown — otherwise a pending push at teardown
                # produces `Task was destroyed but it is pending!`
                # log noise.
                #
                # Review patch — `_warning_emitted = True` is set INSIDE
                # `_emit_patience_warning` AFTER a successful push, not
                # before task creation. Setting it pre-spawn would burn
                # the one-shot even if the push synchronously failed
                # (transport down, pipeline mid-teardown), leaving the
                # user on "last chance" with no audible warning. The
                # `_warning_task is None or done()` check on the line
                # above prevents duplicate spawns in the gap between
                # spawn and successful push — single-event-loop
                # guarantees a second `apply_exchange_outcome` cannot
                # run between `create_task` and the next yield point.
                self._warning_task = asyncio.create_task(self._emit_patience_warning())

    async def _emit_patience_warning(self) -> None:
        """Push the patience-warning TTSSpeakFrame downstream.

        Spawned as a fire-and-forget task from `apply_exchange_outcome`
        so the sync API stays sync. The push targets the LLM/TTS
        downstream path — same lane used by `_run_silence_ladder` for
        its stage-2 verbal prompt. Defensive try/except so a transient
        push failure (TTS down, transport error) is logged and
        swallowed instead of dying silently inside the spawned task.

        Story 6.18 — the spoken line is regenerated in-character from the
        live transcript (`_resolve_exit_line`, `patience_warning` variant)
        with the canned `_patience_warning_line` as fallback.

        Review patch — `_warning_emitted` flips to True only AFTER the
        push lands successfully. If the push raises synchronously
        (transport closed during pipeline teardown), the flag stays
        False so a future failed exchange in the warning band can re-
        attempt the warning. The `_warning_task is None or done()`
        guard in the caller blocks duplicate concurrent spawns, so
        post-success vs. post-failure semantics never produce two
        in-flight warnings.
        """
        # Story 6.18 — regenerate the warning line in-character from the live
        # transcript so it points at what is ACTUALLY still missing (the
        # call-212 canned warning asked "where were you at 8:30?" before the
        # conversation had reached the alibi). Falls back to the canned
        # `_patience_warning_line`; `_resolve_exit_line` never raises.
        line = await self._resolve_exit_line(
            _REASON_PATIENCE_WARNING, self._patience_warning_line
        )
        try:
            await self.push_frame(
                # Turn-taking fix (2026-06-08) — `append_to_context=False`: the
                # one-shot patience-warning is a meta-nudge, not part of the
                # dramatic exchange, so it is spoken but kept OUT of the LLM
                # conversation memory (same pipecat plumbing + rationale as the
                # silence relance), preventing it from merging into the next reply.
                TTSSpeakFrame(text=line, append_to_context=False),
                FrameDirection.DOWNSTREAM,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("patience_warning push failed (warning NOT delivered)")
            return
        self._warning_emitted = True

    @property
    def call_end_reason(self) -> str | None:
        """The reason this call ended, or None if the tracker never drove the
        end (user hang-up / network drop). Read by the bot's teardown debrief
        generator (Story 7.1 AC9); set when `call_end` is emitted."""
        return self._call_end_reason

    def set_checkpoints_passed(self, count: int) -> None:
        """Record the current passed-checkpoint count.

        Called by CheckpointManager on every state change so the
        `call_end` envelope's `checkpoints_passed` field reflects
        live progress regardless of which exit path fires (survived /
        character_hung_up / inappropriate / silence). Idempotent and
        monotonic in practice — CheckpointManager only ever calls with
        a non-decreasing value.
        """
        self._checkpoints_passed = count

    def set_goals_met_indices(self, indices: list[int]) -> None:
        """Record the current set of met-goal indices (author order).

        Story 6.20 AC3 — called by CheckpointManager on every successful
        flip alongside `set_checkpoints_passed`, so the `call_end` envelope
        carries the REAL met set (`goals_met_indices`), not just a count.
        The client reconcile prefers this exact set (walk-up-only) and falls
        back to the count-based `[0..count)` when a pre-6.20 server omits it.
        Stored as a defensive copy so a later mutation of the manager's list
        can't retroactively change what `call_end` reports.
        """
        self._goals_met_indices = list(indices)

    def schedule_completion(
        self, survival_pct: int, winning_user_text: str | None = None
    ) -> None:
        """Route to `_run_hang_up` with `reason='survived'` and the YAML's
        `exit_lines.completion` line. Idempotent re-call swallowed.

        Args:
            survival_pct: 100 from `CheckpointManager` today (all
                checkpoints passed). Threaded explicitly so a future
                tuned-rubric story can dampen the value (e.g. 80 when
                the user passed but with multiple `fail_penalty`
                hits along the way). Bounded to `[0, 100]` inside
                `_run_hang_up` before being emitted.
            winning_user_text: Story 6.18 review (Decision #2 / Option A) —
                the final winning user utterance that CheckpointManager
                suppressed from the LLM context (Deviation #7). Threaded so
                the survived exit line can be generated FROM the answer that
                actually won, instead of a transcript that ends on the
                character's unanswered question. `None` → generate from the
                context as-is.
        """
        if self._hang_up_in_progress:
            return
        # Stash the override BEFORE scheduling so `_run_hang_up` sees
        # it when it reaches the `call_end` emit. Set conditionally
        # only on the survived path; other paths leave it None and
        # use the meter-ratio calculation.
        self._pending_survival_pct = survival_pct
        self._pending_winning_user_text = winning_user_text
        self._schedule_hang_up(_REASON_SURVIVED)

    def schedule_noisy_environment_exit(self) -> None:
        """Route to `_run_hang_up` with `reason='noisy_environment'` and the
        YAML's `exit_lines.noisy_environment` line. Idempotent re-call
        swallowed (the `_hang_up_in_progress` guard in `_schedule_hang_up`).

        Called by `EnvironmentMonitor` when a parasitic background voice is
        confirmed (Story 6.11 AC4). No `survival_pct` override is stashed —
        `_run_hang_up` falls through to the meter-ratio branch (Deviation
        #3: there is no meaningful "performance" measure for an
        environmental cut, and the 5th `CallEndedNoticeScreen` variant
        doesn't render survival % for this reason anyway; keeping the int
        meter ratio avoids churning the `call_end` envelope shape + the
        client's non-nullable `survival_pct` parse).
        """
        self._schedule_hang_up(_REASON_NOISY_ENVIRONMENT)

    def schedule_inappropriate_exit(self) -> None:
        """Route to `_run_hang_up` with `reason='inappropriate_content'` and the
        in-character inappropriate exit line. Idempotent re-call swallowed (the
        `_hang_up_in_progress` guard in `_schedule_hang_up`).

        FR37 — called by `CheckpointManager` when the SAME `classify_multi` call
        that judges goals flags the user's turn as clearly abusive
        (`__user_abusive__`). The character speaks an in-character closing line
        (Story 6.18 generates it from the actual transcript + the inappropriate
        reason → coherent, references what was said) and the call ends; the
        teardown debrief then sets `inappropriate_behavior` (Story 7.1 AC7). No
        `survival_pct` override (meter ratio, like the silence path) — the exit
        is a behavioral cut, not a performance measure. This was the dormant
        `_REASON_INAPPROPRIATE` path (previously only `abuse_classifier=None` in
        prod); it is now wired with no extra LLM call.
        """
        self._schedule_hang_up(_REASON_INAPPROPRIATE)

    def schedule_character_led_bail(self) -> None:
        """SPIKE (spike/character-led, 2026-06-30) — the character itself decided
        to END the call in-character (it wrote the <end_call> marker, stripped by
        `reply_sanitizer`). This is the Phase-2 stakes mechanic: a character can
        walk away when the other person wastes its time / stonewalls / crosses a
        line, WITHOUT the patience meter.

        Reuses the existing `_REASON_SILENCE` (= client `character_hung_up`)
        teardown — the Story 6.18 generator produces an in-character closing line
        from the transcript + the "ran out of patience / stopped cooperating"
        guidance, exactly the bail flavor. `_spike_character_led_bail` makes
        `_run_hang_up` ALSO push the abuse-path InterruptionFrame (the marker
        fires WHILE the character's reply is in-flight, so that reply must be
        flushed) and report a checkpoint-based survival_pct. Idempotent (the
        `_hang_up_in_progress` guard in `_schedule_hang_up`)."""
        if self._hang_up_in_progress:
            return
        logger.info(
            "spike_character_led_bail → in-character hang-up (checkpoints_passed={}/{})",
            self._checkpoints_passed,
            self._total_checkpoints,
        )
        self._spike_character_led_bail = True
        self._schedule_hang_up(_REASON_SILENCE)

    # ---------- silence ladder ----------

    def _start_silence_timer(self) -> None:
        self._cancel_silence_timer()
        self._silence_task = asyncio.create_task(self._run_silence_ladder())

    def _cancel_silence_timer(self) -> None:
        # Called from two paths: (a) `TranscriptionFrame` /
        # `UserStartedSpeakingFrame` arrival (= user spoke), and (b)
        # `_start_silence_timer` clearing the previous task before
        # creating a new one (= ladder restart). The log is neutral
        # to avoid mis-attributing the cause.
        prior = self._silence_task
        if prior is not None and not prior.done():
            logger.info("PatienceTracker: silence ladder cancelled")
            prior.cancel()
        self._silence_task = None
        # Reset the prompt-played gate. If the ladder was cancelled
        # mid-stage-2 (right after the prompt TTSSpeakFrame push but
        # before the user heard it), the prompt's later
        # `playback_idle` MUST NOT consume `_self_speaking` — that
        # would steal the next bot turn's signal and prevent the new
        # ladder from starting. Cancellation = back to a clean
        # "no in-flight self speech" state.
        self._self_speaking = False
        self._prompt_played_event = None

    async def _cancel_silence_timer_and_drain(self) -> None:
        prior = self._silence_task
        if prior is not None and not prior.done():
            prior.cancel()
            await asyncio.gather(prior, return_exceptions=True)
        self._silence_task = None

    async def _run_silence_ladder(self) -> None:
        try:
            # Stage 1 — `_ladder_impatience_seconds` (per-difficulty —
            # Story 6.13 AC3) of post-bot-turn silence: emit
            # `impatience` so the Rive face shifts to a mildly
            # impatient state. Each ladder run emits fresh — the
            # client-side Rive enum is discrete (intensity is
            # currently dropped), so a re-emit to the same enum
            # value is a no-op visually but harmless.
            await asyncio.sleep(self._ladder_impatience_seconds)
            logger.info("PatienceTracker stage 1: impatience@0.5")
            await self._emit_emotion("impatience", 0.5)

            # Stage 2 — silence_prompt_seconds total: push the
            # verbal prompt + bump impatience. The face stays
            # `impatience` (Rive enum is discrete; intensity is
            # currently dropped client-side), so the visible change
            # is the audio prompt itself.
            stage2 = max(
                0.0,
                self._silence_prompt_seconds - self._ladder_impatience_seconds,
            )
            await asyncio.sleep(stage2)
            logger.info("PatienceTracker stage 2: verbal prompt + impatience@0.7")
            self._self_speaking = True
            self._prompt_played_event = asyncio.Event()
            await self.push_frame(
                # Turn-taking fix (2026-06-08) — `append_to_context=False` so this
                # mechanical silence relance is SPOKEN but NEVER recorded in the
                # LLM conversation memory. pipecat threads the flag from the
                # TTSSpeakFrame to the emitted TTSTextFrame
                # (services/tts_service.py: `append_tts_text_to_context`) and the
                # assistant aggregator drops frames whose `append_to_context` is
                # False (aggregators/llm_response_universal.py
                # `_handle_text`). Without it the relance buffered and MERGED into
                # the next reply ("Hello? Are you still there? 14 Maple Street,
                # noted...") — cop call 2026-06-08. It is a nudge, not dialogue.
                TTSSpeakFrame(text=self._silence_prompt_line, append_to_context=False),
                FrameDirection.DOWNSTREAM,
            )
            await self._emit_emotion("impatience", 0.7)

            # Wait for the user's ear to actually finish hearing the
            # prompt before counting down anger + hang-up. The signal
            # comes from `handle_playback_idle` when the client's
            # post-prompt `playback_idle` arrives (= speaker drained
            # the prompt audio).
            try:
                await asyncio.wait_for(
                    self._prompt_played_event.wait(),
                    timeout=_PROMPT_PLAYBACK_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "PatienceTracker: prompt playback_idle timeout "
                    "after {}s — proceeding with stage 3 anyway",
                    _PROMPT_PLAYBACK_TIMEOUT_SECONDS,
                )

            # Stage 3 — anger N seconds AFTER the user heard the
            # prompt finish.
            await asyncio.sleep(_POST_PROMPT_ANGER_DELAY)
            logger.info("PatienceTracker stage 3: anger@0.8")
            await self._emit_emotion("anger", 0.8)

            # Stage 4 — hang-up M seconds after anger.
            await asyncio.sleep(_POST_ANGER_HANGUP_DELAY)
            self._patience = max(0, self._patience + self._silence_penalty)
            logger.info(
                "PatienceTracker stage 4: silence_penalty applied, "
                "patience={} → schedule hang-up",
                self._patience,
            )
            if not self._hang_up_in_progress:
                self._schedule_hang_up(_REASON_SILENCE)
        except asyncio.CancelledError:
            # Cancellation == "user spoke". Re-raise silently.
            raise

    async def _emit_emotion(self, emotion: str, intensity: float) -> None:
        await self.push_frame(
            OutputTransportMessageFrame(
                message={
                    "type": "emotion",
                    "data": {"emotion": emotion, "intensity": intensity},
                }
            ),
            FrameDirection.DOWNSTREAM,
        )

    # ---------- hang-up sequence ----------

    def _schedule_hang_up(self, reason: str) -> None:
        if reason not in _VALID_REASONS:
            # Defensive: a future caller passing a typo should fail loud
            # here, not silently fall through to a wrong exit line.
            raise ValueError(
                f"PatienceTracker._schedule_hang_up: unknown reason {reason!r}; "
                f"expected one of {sorted(_VALID_REASONS)}"
            )
        if self._hang_up_in_progress:
            return
        logger.info("PatienceTracker: scheduling hang-up reason={}", reason)
        self._hang_up_in_progress = True
        # The ladder may have called us at stage 4 — cancel it so the
        # remaining (empty) coroutine tail is reaped immediately.
        self._cancel_silence_timer()
        self._hang_up_task = asyncio.create_task(self._run_hang_up(reason))

    async def _resolve_exit_line(
        self, reason: str, fallback: str, extra_user_text: str | None = None
    ) -> str:
        """Story 6.18 — return the dynamic, in-character line for `reason`,
        or `fallback` (the canned YAML line) when generation is disabled,
        slow, empty, or fails. NEVER raises — a canned line beats a crashed
        hang-up. Logs `hangup_line source=generated|fallback latency_ms=…` at
        this substitution point so a journalctl tail confirms the feature
        worked vs fell back (AC7).

        `extra_user_text` (survived path) is the winning user turn that
        CheckpointManager suppressed (Deviation #7); the generator appends it
        to the transcript so the closing line can reference what actually won.

        `gen` (the injected `generate_exit_line` closure from `bot.py`) is
        itself fire-tolerant (returns None on any error / timeout / empty
        transcript), but the `try/except` here also guards an arbitrary
        injected stub so an unexpected raise still degrades to the canned
        line (AC2).
        """
        gen = self._hang_up_line_generator
        if gen is None:
            logger.info(
                "hangup_line source=fallback reason={} (generation disabled)",
                reason,
            )
            return fallback
        start = time.monotonic()
        try:
            line = await gen(reason, extra_user_text)
        except asyncio.CancelledError:
            raise
        except Exception:
            latency_ms = int((time.monotonic() - start) * 1000)
            # AC7 (review #32) — keep the structured `source=fallback
            # latency_ms=` shape on this path too (the None-return / disabled
            # paths already carry it). Log level stays ERROR via
            # logger.exception; the WARNING-alignment nit is deferred (#30).
            logger.exception(
                "hangup_line source=fallback reason={} latency_ms={} "
                "(generation raised)",
                reason,
                latency_ms,
            )
            return fallback
        latency_ms = int((time.monotonic() - start) * 1000)
        if line:
            # AC7 — source + latency at INFO (the journalctl signal); the
            # verbatim line is transcript-derived, so it goes to DEBUG only
            # (review #19 — keep user-derived content out of INFO logs).
            logger.info(
                "hangup_line source=generated reason={} latency_ms={}",
                reason,
                latency_ms,
            )
            logger.debug("hangup_line generated text reason={} text={!r}", reason, line)
            return line
        logger.info(
            "hangup_line source=fallback reason={} latency_ms={} "
            "(generation returned None)",
            reason,
            latency_ms,
        )
        return fallback

    async def _await_exit_line_delivery(self, reason: str, line: str) -> None:
        """Wait for the exit line's `BotStoppedSpeakingFrame`, re-queuing the
        synthesis exactly ONCE if the TTS stalled silently.

        Call 277 (2026-06-11): the survived goodbye was generated and sent to
        Cartesia (`Generating TTS` logged) but no audio ever came back — the
        TTSWatchdog fired (`no_audio_within_5.0s`), this wait expired at 6 s,
        and the call ended on ~6 s of dead air with no audible goodbye. The
        OPENING line is protected against this stall class by the Story 6.24
        pre-call warm-up (`tts_warmup.py`); the exit line gets this bounded
        in-flight retry instead.

        Two-phase wait (call 277 follow-up — Walid: a 6 s gap before the
        retry "feels like a bug"; the stall verdict doesn't need the line
        to FINISH, only to know whether its audio ever STARTED, which is
        knowable within ~1 s on the happy path):

          Phase A — `_HANG_UP_TTS_STALL_DETECT_SECONDS` (3.0 s): wait for
          the line to complete outright (short line, fast TTS). On expiry,
          branch on `_exit_line_audio_started`:
          - True → audio reached the transport; the line is playing, just
            not finished. Phase B: keep waiting for completion up to the
            original overall cap (`_HANG_UP_TTS_TIMEOUT_SECONDS` total).
            On phase-B expiry: WARN + proceed to `call_end` (the client
            drains in-flight audio after `call_end` before disconnecting,
            so nothing is cut). NEVER re-queue on this branch — a second
            push would double-speak the goodbye, breaking the Story
            6.25/6.22 invariant that the exit line is the sole final
            utterance.
          - False → silent stall, declared at 3 s instead of 6. Re-push
            the SAME resolved `line` once (no second `_resolve_exit_line`
            round-trip) with `append_to_context=False` — the first push
            already recorded the text in the LLM context via its
            TTSTextFrame, and the Story 7.1 teardown debrief must not read
            a doubled goodbye — then wait a further
            `_HANG_UP_TTS_RETRY_TIMEOUT_SECONDS`.

        Bounded by construction: ONE retry maximum. `_run_hang_up` pushes
        the `call_end` envelope strictly AFTER this method returns, so the
        retry can never race it. The TTSWatchdog backstop is untouched
        code-wise; note its 5 s timer for the FIRST synthesis is re-armed
        by the retry's own TTSStartedFrame
        (`test_watchdog_fires_at_most_once_per_turn`), so on the hang-up
        path the `hangup_exit_line_retry` INFO line below is the primary
        journalctl signal for the stall, and a `cartesia_tts_watchdog_fired`
        WARN after it means the RETRY stalled too.
        """
        # Phase A — stall-detection window.
        try:
            await asyncio.wait_for(
                self._speaking_done.wait(),
                timeout=_HANG_UP_TTS_STALL_DETECT_SECONDS,
            )
            return
        except asyncio.TimeoutError:
            pass

        if self._exit_line_audio_started:
            # Audio is flowing — not a stall. Phase B: wait out the rest of
            # the original completion cap; on expiry keep the pre-call-277
            # behavior, byte-identical log line.
            try:
                await asyncio.wait_for(
                    self._speaking_done.wait(),
                    timeout=max(
                        0.0,
                        _HANG_UP_TTS_TIMEOUT_SECONDS
                        - _HANG_UP_TTS_STALL_DETECT_SECONDS,
                    ),
                )
                return
            except asyncio.TimeoutError:
                logger.warning(
                    "PatienceTracker hang-up TTS timeout after {}s",
                    _HANG_UP_TTS_TIMEOUT_SECONDS,
                )
                return

        # Smoke-gate grep anchor — the primary stall signal on this path
        # (the watchdog's 5 s timer gets re-armed by the retry's own
        # TTSStartedFrame before it can fire for the first synthesis).
        logger.info(
            "hangup_exit_line_retry reason={} no_audio_within={}s — "
            "re-queuing exit line once",
            reason,
            _HANG_UP_TTS_STALL_DETECT_SECONDS,
        )
        # Fresh event so the retry's own BotStoppedSpeakingFrame releases
        # the wait below — assigned BEFORE the push, same non-None-target
        # rule as the first attempt.
        self._speaking_done = asyncio.Event()
        await self.push_frame(
            TTSSpeakFrame(text=line, append_to_context=False),
            FrameDirection.DOWNSTREAM,
        )
        try:
            await asyncio.wait_for(
                self._speaking_done.wait(),
                timeout=_HANG_UP_TTS_RETRY_TIMEOUT_SECONDS,
            )
            logger.info("hangup_exit_line_retry delivered — goodbye spoken on retry")
        except asyncio.TimeoutError:
            logger.warning(
                "PatienceTracker hang-up TTS timeout after retry ({}s + {}s) "
                "— proceeding to call_end",
                _HANG_UP_TTS_TIMEOUT_SECONDS,
                _HANG_UP_TTS_RETRY_TIMEOUT_SECONDS,
            )

    async def _run_hang_up(self, reason: str) -> None:
        # 3-way exit-line selection. Deviation #1 from Story 6.6: the
        # completion path speaks its own line (YAML `exit_lines.completion`
        # via `_hang_up_line_survived`). silence + inappropriate paths
        # remain on their respective lines.
        if reason == _REASON_SILENCE:
            line = self._hang_up_line_silence
        elif reason == _REASON_INAPPROPRIATE:
            line = self._hang_up_line_inappropriate
        elif reason == _REASON_NOISY_ENVIRONMENT:
            # Story 6.11 — parasitic-voice exit line.
            line = self._hang_up_line_noisy_environment
        else:  # _REASON_SURVIVED — validated by _schedule_hang_up
            line = self._hang_up_line_survived

        # Story 6.18 review (#3) — start exit-line generation NOW as a task so
        # the ≤1.5 s LLM round-trip overlaps the pre-TTS delay + (for
        # noisy_environment) the InterruptionFrame flush, instead of running
        # serially AFTER the pipeline is silenced (which injected up to ~1.5 s
        # of dead air right after cutting the user off). AC6 ordering holds:
        # the InterruptionFrame is still pushed before the TTSSpeakFrame; only
        # the generation RESULT is consumed after the interrupt. P0 (Decision
        # #2 / Option A): on the survived path, hand the generator the winning
        # user turn CheckpointManager suppressed (Deviation #7) so the closing
        # line can ground on the answer that actually won.
        winning_user_text = (
            self._pending_winning_user_text if reason == _REASON_SURVIVED else None
        )
        # SPIKE — the character-led bail keeps its CLIENT reason (character_hung_up)
        # but generates its closing line from the disrespect-appropriate guidance,
        # not the meter's "you stopped giving clear answers" one (which fabricated a
        # "changed story" accusation — call 353).
        gen_reason = _REASON_SPIKE_BAIL if self._spike_character_led_bail else reason
        exit_line_task = asyncio.create_task(
            self._resolve_exit_line(gen_reason, line, extra_user_text=winning_user_text)
        )
        self._pending_winning_user_text = None
        try:
            await self.push_frame(
                OutputTransportMessageFrame(
                    message={
                        "type": "hang_up_warning",
                        "data": {"seconds_remaining": 5},
                    }
                ),
                FrameDirection.DOWNSTREAM,
            )
            await asyncio.sleep(_HANG_UP_PRE_TTS_DELAY)

            # Story 6.11 fix (2026-05-30, smoke call_id=200) + FR37
            # (2026-06-09, smoke call_id=261) — noisy_environment AND
            # inappropriate_content BOTH fire WHILE the character LLM is
            # mid-generating a normal reply to the triggering turn, so the
            # generated exit line gets queued BEHIND that reply (silence has no
            # in-flight speech; survived is suppressed by CheckpointManager's
            # terminal-turn sync). call_id=200: the parasite's continued-speech
            # interruption then flushed the queued exit line (user never heard
            # it). call_id=261: the abusive turn drew a full normal reply (the
            # waiter re-listed the whole menu) that buried the exit line until
            # PAST the 6 s hang-up TTS timeout — the user perceived "she never
            # hung up" and bailed. (The OLD persona prompt masked this on the
            # inappropriate path by scripting a SHORT hang-up line as that
            # reply; removing it — so the deterministic detector owns the
            # hang-up — unmasked the same call_id=200 bug here.) Push an
            # InterruptionFrame first to cancel the in-flight reply + clear the
            # TTS queue, so the exit line is the only thing that speaks. Silence
            # + survived stay un-interrupted
            # (test_silence_hangup_does_not_push_interruption).
            # SPIKE — a character-led bail fires WHILE the character's <end_call>
            # reply is in-flight (same shape as inappropriate), so it ALSO needs
            # the InterruptionFrame to flush that reply before the closing line.
            if (
                reason in (_REASON_NOISY_ENVIRONMENT, _REASON_INAPPROPRIATE)
                or self._spike_character_led_bail
            ):
                await self.push_frame(
                    InterruptionFrame(),
                    FrameDirection.DOWNSTREAM,
                )

            # Story 6.18 — consume the pre-scheduled generation (started above
            # so it overlapped the delay + interrupt instead of injecting dead
            # air). `_resolve_exit_line` never raises: a disabled/slow/failed
            # generation yields the canned `line` selected above. Awaited AFTER
            # the noisy_environment InterruptionFrame so the interrupt still
            # flushes the in-flight reply first (AC6 ordering preserved); the
            # generated text is spoken in the same TTSSpeakFrame the canned
            # line would have used.
            line = await exit_line_task

            # Create the event BEFORE pushing the TTSSpeakFrame so the
            # bot-stopped handler always has a non-None target. The
            # audio-started flag resets in the same synchronous block, so
            # only a BotStartedSpeakingFrame landing AFTER this push can
            # flip it (call 277 — see `_await_exit_line_delivery`).
            self._speaking_done = asyncio.Event()
            self._exit_line_audio_started = False
            await self.push_frame(
                TTSSpeakFrame(text=line),
                FrameDirection.DOWNSTREAM,
            )

            await self._await_exit_line_delivery(reason, line)

            # Emit `call_end` immediately — the client is responsible
            # for waiting until its local audio actually drains before
            # disconnecting the room (it watches the same PCM stream
            # that drives lip-sync, via `VisemeScheduler`). No fixed
            # buffer here means the timing is adaptive: a fast WiFi
            # client disconnects in ~100 ms after `call_end`, a slow
            # cellular client takes 1-2 s. The audio is never cut.
            #
            # Survival-pct sourcing (Deviation #1 from Story 6.6):
            #   reason='survived'   → 100 (passed every checkpoint —
            #                         override threaded by
            #                         `schedule_completion`).
            #   reason='character_hung_up' / 'inappropriate_content'
            #                       → patience-meter ratio (the user
            #                         got dropped before completing).
            if reason == _REASON_SURVIVED and self._pending_survival_pct is not None:
                survival_pct = max(0, min(100, self._pending_survival_pct))
                # Review patch — clear the override after consumption.
                # `_hang_up_in_progress` already prevents a second
                # `_run_hang_up` from firing today, but a future caller
                # that loosens that invariant (e.g. retry-on-error)
                # would otherwise read stale 100 on a non-survived path.
                # Defensive reset keeps the field's lifetime scoped to
                # one schedule_completion → _run_hang_up cycle.
                self._pending_survival_pct = None
            elif self._spike_character_led_bail:
                # SPIKE — the meter is no longer the truth (fail-drain is off),
                # so report progress as the share of checkpoints actually passed.
                survival_pct = max(
                    0,
                    min(
                        100,
                        round(
                            self._checkpoints_passed
                            / max(1, self._total_checkpoints)
                            * 100
                        ),
                    ),
                )
            else:
                survival_pct = max(
                    0,
                    min(
                        100,
                        int(max(0, self._patience) / self._initial_patience * 100),
                    ),
                )
            # Story 7.1 — record the end reason for the bot's teardown debrief
            # generator (AC9). Set here, at the single point the call-end reason
            # is finalized, so it reflects the SAME `reason` the client sees.
            self._call_end_reason = reason
            await self.push_frame(
                OutputTransportMessageFrame(
                    message={
                        "type": "call_end",
                        "data": {
                            "reason": reason,
                            "survival_pct": survival_pct,
                            "checkpoints_passed": self._checkpoints_passed,
                            "total_checkpoints": self._total_checkpoints,
                            # Story 6.20 AC3 — the REAL met set (author order),
                            # so a future debrief can't mislabel WHICH goals
                            # were met when they flipped out of order. The
                            # client prefers this over the count-based
                            # `[0..checkpoints_passed)` reconstruction.
                            "goals_met_indices": list(self._goals_met_indices),
                        },
                    }
                ),
                FrameDirection.DOWNSTREAM,
            )

            # Wait for the client to disconnect (which fires
            # `on_participant_left` in `bot.py` → that handler pushes
            # `EndFrame` and tears down the pipeline cleanly, which
            # in turn calls our `cleanup()` and sets `_shutdown_event`).
            # We `wait_for` the shutdown signal with an 8 s safety cap:
            # on the happy path the event is set within ~1-2 s and we
            # exit cleanly (no warning, no force-EndFrame). Only if the
            # client crashed / froze / lost network do we hit the
            # timeout and push EndFrame ourselves as a safety so the
            # pipeline doesn't leak.
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=_HANG_UP_CLIENT_DRAIN_TIMEOUT_SECONDS,
                )
                logger.info("PatienceTracker hang-up: client disconnected cleanly")
            except asyncio.TimeoutError:
                logger.warning(
                    "PatienceTracker hang-up: client did not disconnect "
                    "within {}s — force-terminating pipeline",
                    _HANG_UP_CLIENT_DRAIN_TIMEOUT_SECONDS,
                )
                await self.push_frame(EndFrame(), FrameDirection.DOWNSTREAM)
        except asyncio.CancelledError:
            raise
        finally:
            # Story 6.18 review (#3) — if a teardown/exception cut the sequence
            # short before the pre-scheduled generation was consumed, reap the
            # task so it is not orphaned.
            if not exit_line_task.done():
                exit_line_task.cancel()
            # Clear the flag even on error: a transient `push_frame`
            # failure must not wedge the tracker in "hang-up active"
            # forever (which would block any later `_schedule_hang_up`
            # idempotency-style retry and silently swallow recovery).
            # On the happy path this clears post-EndFrame — pipeline
            # is dead, the reset is a no-op semantically.
            self._hang_up_in_progress = False
            # SPIKE — scope the bail flag to this one teardown cycle.
            self._spike_character_led_bail = False
