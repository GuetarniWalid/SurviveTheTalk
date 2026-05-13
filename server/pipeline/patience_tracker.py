"""Story 6.4 — PatienceTracker Pipecat FrameProcessor.

Owns the per-call silence timer, the patience meter, and the dramatic
hang-up sequence. Sits between `context_aggregator.user()` and `llm` so
it observes user `TranscriptionFrame`s after the aggregator finalizes a
turn (see `difficulty-calibration.md` AD-2).

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
  4. Wait for `BotStoppedSpeakingFrame` (6.0 s safeguard against stuck TTS)
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
from typing import Any, Callable

from loguru import logger
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    EndFrame,
    Frame,
    OutputTransportMessageFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Stage 1 anchor (impatience face emit) — measured from the start
# of the ladder, which itself starts on client-confirmed
# `playback_idle` (= user's ear heard the bot finish speaking).
_LADDER_IMPATIENCE_AT = 3.0

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

# Safety cap so a stuck TTS during the hang-up exit line cannot wedge
# the call indefinitely. 6.0 s is generous for a 2-sentence line.
_HANG_UP_TTS_TIMEOUT_SECONDS = 6.0

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

_REASON_SILENCE = "character_hung_up"
_REASON_INAPPROPRIATE = "inappropriate_content"


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
        total_checkpoints: int,
        fail_penalty: int = 0,
        recovery_bonus: int = 0,
        silence_hangup_seconds: float = 10.0,
        escalation_thresholds: list[int] | None = None,
        silence_prompt_line: str = "Hello? Are you still there?",
        hang_up_line_silence: str = "I don't have time for this. Goodbye.",
        hang_up_line_inappropriate: str = "I'm done with this. Goodbye.",
        abuse_classifier: Callable[[str], bool] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if initial_patience <= 0:
            raise ValueError(f"initial_patience must be > 0, got {initial_patience!r}")
        self._initial_patience = initial_patience
        self._patience = initial_patience
        self._silence_penalty = silence_penalty
        self._silence_prompt_seconds = silence_prompt_seconds
        self._total_checkpoints = total_checkpoints
        self._silence_prompt_line = silence_prompt_line
        self._hang_up_line_silence = hang_up_line_silence
        self._hang_up_line_inappropriate = hang_up_line_inappropriate
        self._abuse_classifier = abuse_classifier

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
            "silence_hangup_seconds={} escalation_thresholds={} "
            "total_checkpoints={}",
            initial_patience,
            fail_penalty,
            silence_penalty,
            recovery_bonus,
            silence_prompt_seconds,
            silence_hangup_seconds,
            self._escalation_thresholds,
            total_checkpoints,
        )

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Pass-through is MANDATORY: PatienceTracker observes, never
        # consumes. Forward first so a follow-up branch that raises
        # cannot swallow the frame from downstream.
        await self.push_frame(frame, direction)

        if (
            isinstance(frame, BotStoppedSpeakingFrame)
            and direction == FrameDirection.DOWNSTREAM
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
            # Direction-gated: BSF is canonically downstream; an
            # upstream BSF (e.g. from a sniffing test harness) must
            # not emit a spurious envelope.
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
            # Skip interim transcriptions — they fire mid-utterance and
            # would prematurely cancel the silence ladder. Only
            # finalized text confirms the user actually completed a
            # turn. `finalized` defaults to True if absent so STTs that
            # don't carry the field (older pipecat) keep working.
            if not getattr(frame, "finalized", True):
                return
            # Cancel BEFORE the empty-text early-return: an artifact
            # frame from the STT (whitespace-only result, etc.) should
            # still reset the ladder defensively — the user clearly
            # made some sound.
            self._cancel_silence_timer()
            text = (getattr(frame, "text", "") or "").strip()
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
        elif isinstance(frame, UserStartedSpeakingFrame):
            # Defensive: VAD start may land before the STT finalizes
            # a transcription. Cancel the ladder now so a user mid-
            # speech doesn't trip stage 1 emit.
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
            # Stage 1 — 3.0 s of post-bot-turn silence: emit
            # `impatience` so the Rive face shifts to a mildly
            # impatient state. Each ladder run emits fresh — the
            # client-side Rive enum is discrete (intensity is
            # currently dropped), so a re-emit to the same enum
            # value is a no-op visually but harmless.
            await asyncio.sleep(_LADDER_IMPATIENCE_AT)
            logger.info("PatienceTracker stage 1: impatience@0.5")
            await self._emit_emotion("impatience", 0.5)

            # Stage 2 — silence_prompt_seconds total: push the
            # verbal prompt + bump impatience. The face stays
            # `impatience` (Rive enum is discrete; intensity is
            # currently dropped client-side), so the visible change
            # is the audio prompt itself.
            stage2 = max(0.0, self._silence_prompt_seconds - _LADDER_IMPATIENCE_AT)
            await asyncio.sleep(stage2)
            logger.info("PatienceTracker stage 2: verbal prompt + impatience@0.7")
            self._self_speaking = True
            self._prompt_played_event = asyncio.Event()
            await self.push_frame(
                TTSSpeakFrame(text=self._silence_prompt_line),
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
        if self._hang_up_in_progress:
            return
        logger.info("PatienceTracker: scheduling hang-up reason={}", reason)
        self._hang_up_in_progress = True
        # The ladder may have called us at stage 4 — cancel it so the
        # remaining (empty) coroutine tail is reaped immediately.
        self._cancel_silence_timer()
        self._hang_up_task = asyncio.create_task(self._run_hang_up(reason))

    async def _run_hang_up(self, reason: str) -> None:
        line = (
            self._hang_up_line_silence
            if reason == _REASON_SILENCE
            else self._hang_up_line_inappropriate
        )
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

            # Create the event BEFORE pushing the TTSSpeakFrame so the
            # bot-stopped handler always has a non-None target.
            self._speaking_done = asyncio.Event()
            await self.push_frame(
                TTSSpeakFrame(text=line),
                FrameDirection.DOWNSTREAM,
            )

            try:
                await asyncio.wait_for(
                    self._speaking_done.wait(),
                    timeout=_HANG_UP_TTS_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "PatienceTracker hang-up TTS timeout after {}s",
                    _HANG_UP_TTS_TIMEOUT_SECONDS,
                )

            # Emit `call_end` immediately — the client is responsible
            # for waiting until its local audio actually drains before
            # disconnecting the room (it watches the same PCM stream
            # that drives lip-sync, via `VisemeScheduler`). No fixed
            # buffer here means the timing is adaptive: a fast WiFi
            # client disconnects in ~100 ms after `call_end`, a slow
            # cellular client takes 1-2 s. The audio is never cut.
            survival_pct = max(
                0,
                min(
                    100,
                    int(max(0, self._patience) / self._initial_patience * 100),
                ),
            )
            await self.push_frame(
                OutputTransportMessageFrame(
                    message={
                        "type": "call_end",
                        "data": {
                            "reason": reason,
                            "survival_pct": survival_pct,
                            "checkpoints_passed": 0,
                            "total_checkpoints": self._total_checkpoints,
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
            # Clear the flag even on error: a transient `push_frame`
            # failure must not wedge the tracker in "hang-up active"
            # forever (which would block any later `_schedule_hang_up`
            # idempotency-style retry and silently swallow recovery).
            # On the happy path this clears post-EndFrame — pipeline
            # is dead, the reset is a no-op semantically.
            self._hang_up_in_progress = False
