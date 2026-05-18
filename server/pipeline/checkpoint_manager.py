"""Story 6.6 — CheckpointManager Pipecat FrameProcessor.

Scenario-progression brain: owns a single `_index` into the ordered
checkpoint list, judges each finalized user turn against the CURRENT
checkpoint's `success_criteria` via `ExchangeClassifier`, and on
`{met: true}` mutates the live LLM system instruction so the next bot
turn replies under the new checkpoint's `prompt_segment`. After the
final checkpoint passes, routes through
`PatienceTracker.schedule_completion(survival_pct=100)` to end the call
with `reason='survived'` and the YAML's `exit_lines.completion` line.

**Pass-through is mandatory.** This processor observes user
`TranscriptionFrame`s; it must forward every frame downstream unchanged
(Story 6.3 review found 3 silent regressions where a `return` before
`push_frame` swallowed the LLM/TTS path). The classifier call is
fire-and-forget inside an `asyncio.create_task` so the main pipeline
never blocks on the 2.0 s OpenRouter round-trip.

Three Story 6.6 deviations documented at the module level (also in the
story's `Implementation Notes`):

  - **Deviation #1.** Two distinct `survival_pct` formulas:
        reason='survived'   → 100 (passed every checkpoint).
        reason='character_hung_up' / 'inappropriate_content'
                            → patience-meter ratio.
    Owned by `PatienceTracker._run_hang_up` after this manager threads
    the override via `schedule_completion(survival_pct=100)`.

  - **Deviation #2 — system-prompt swap mechanism.** The spec proposed
    `LLMContext.set_messages([{role:'system', ...}, *non_system])`.
    Reading the pipecat 0.0.108 source shows that the OpenAI adapter
    (`open_ai_adapter.py:90`) **always prepends** `_settings.system_instruction`
    to the request messages at every invocation, AND the `LLMContext`
    created in `bot.py` is empty at boot (no system message inside it).
    Mutating the context would either (a) add a system message that the
    adapter would then prepend ANOTHER one in front of (two system
    messages with a noisy warning from `_resolve_system_instruction`),
    or (b) be ignored because the adapter authoritatively reads
    `system_instruction` from settings. The cleanest mechanism is to
    mutate `llm._settings.system_instruction` directly — a single
    point of truth that the adapter consults at every turn.
    `pipecat.services.settings.Settings.apply_update` documents these
    fields as "Runtime-updatable settings"; direct field assignment is
    explicitly supported.

  - **Deviation #3.** YAML `exit_lines.completion` flows into
    `hang_up_line_survived`; `exit_lines.hangup` is shared by both
    silence and inappropriate paths. Owned by
    `scenarios.resolve_patience_config`.

  - **Deviation #7 (post-deploy 2026-05-18).** Preemptive synchronous
    classify on TERMINAL turns. A terminal turn is one where the next
    failed exchange would zero the patience meter (hangup path) OR
    where we are at the last checkpoint (completion path). On terminal
    turns the manager AWAITS the classifier verdict before forwarding
    the user `TranscriptionFrame`; if the verdict confirms terminal
    state, the frame is **suppressed** (not pushed downstream), so the
    LLM never produces a parallel response. The exit line (hangup or
    completion) becomes the SOLE terminative final utterance — no more
    awkward "Tina asks a question then 5-8 s of silence then the
    dramatic exit line". Pass-through is INTENTIONALLY violated for
    terminal turns; non-terminal turns retain the original
    forward-first pattern.

Last-character-line sourcing: this manager reads the most recent
assistant message from `llm_context.get_messages()` at classify time,
not by observing `TextFrame`s. The spec's frame-observation pattern
won't work because the LLM's `TextFrame` flows DOWNSTREAM (toward TTS)
and CheckpointManager sits UPSTREAM of the LLM. The shared
`LLMContext` populated by `LLMContextAggregatorPair.assistant()` is the
authoritative source for "what the character last said".

Direction sensitivity (per `server/CLAUDE.md` §1 and project memory
🪤 `feedback_pipecat_frame_direction_test_trap.md`): user
`TranscriptionFrame`s flow DOWNSTREAM from STT through the user
aggregator to this processor; we don't gate on direction (mirroring
`EmotionEmitter`). The pipeline-driven contract test in
`test_bot_pipeline_wiring.py` is the regression net per AC8 #6.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    OutputTransportMessageFrame,
    TranscriptionFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from pipeline.exchange_classifier import ExchangeClassifier
from pipeline.patience_tracker import PatienceTracker


class CheckpointManager(FrameProcessor):
    """Owns scenario-checkpoint progression for one call.

    Args:
        base_prompt: Scenario YAML `base_prompt` (rstrip'd, no
            `_SPEAK_FIRST_DIRECTIVE` suffix). Composed live with the
            current checkpoint's `prompt_segment` on every advance.
        checkpoints: Ordered list of checkpoint dicts; each entry has
            `id`, `hint_text`, `prompt_segment`, `success_criteria`.
            Validated at load time by `scenarios.load_scenario_checkpoints`.
        llm: Pipecat LLM service (e.g. `OpenRouterLLMService`). Must
            expose `._settings.system_instruction` for in-place mutation
            on advance (Deviation #2). Typed loosely so tests can pass
            a simple stub with the required attribute path.
        llm_context: The shared `LLMContext` instance. Read at classify
            time to source the last assistant message as the classifier's
            `last_character_line` context.
        classifier: `ExchangeClassifier` instance, owned by this
            manager for the call's lifetime.
        patience_tracker: `PatienceTracker` instance — receives
            `apply_exchange_outcome` after every verdict and
            `schedule_completion` after the final checkpoint passes.
        scenario_description: Short scenario context (e.g. metadata
            title "The Waiter") embedded in the classifier prompt.
    """

    def __init__(
        self,
        *,
        base_prompt: str,
        checkpoints: list[dict],
        llm: Any,
        llm_context: LLMContext,
        classifier: ExchangeClassifier,
        patience_tracker: PatienceTracker,
        scenario_description: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if not checkpoints:
            raise ValueError("CheckpointManager requires a non-empty checkpoints list")
        # Story 6.6 review patch — fail-loud assertion on the Deviation
        # #2 mechanism. The advance path mutates
        # `llm._settings.system_instruction` directly (private attribute
        # of the pipecat LLM service); a future pipecat minor version
        # that renames `_settings` or makes it a frozen dataclass would
        # silently break the swap with NO `AttributeError` at advance
        # time (`setattr` on a frozen dataclass raises, but mutating a
        # renamed-away attribute on a regular object just sets a new
        # attribute that the adapter no longer reads — checkpoint
        # progression would appear to succeed but the LLM would stay
        # on the original system prompt). Check the path exists at
        # construction so pipecat API drift surfaces at call init.
        if not hasattr(llm, "_settings") or not hasattr(
            llm._settings, "system_instruction"
        ):
            raise RuntimeError(
                "CheckpointManager: llm._settings.system_instruction not exposed "
                "by the LLM service. Deviation #2 (in-place system-prompt swap) "
                "depends on this private attribute path; a pipecat upgrade likely "
                "renamed or restructured it. Verify against the current pipecat "
                "OpenAI adapter source."
            )
        self._base_prompt = base_prompt.rstrip()
        self._checkpoints = checkpoints
        self._llm = llm
        self._llm_context = llm_context
        self._classifier = classifier
        self._patience_tracker = patience_tracker
        self._scenario_description = scenario_description
        self._index = 0
        # Latest-line-wins: each new finalized TranscriptionFrame cancels
        # the prior classify before scheduling a fresh task. Same shape
        # as EmotionEmitter's generation-counter guard — the cancel
        # alone isn't enough because `push_frame` may not be a
        # cancellation point in pipecat.
        self._in_flight: asyncio.Task[None] | None = None
        self._generation = 0
        # Story 6.7 Phase 2 retouche #5 (2026-05-19) — defer the
        # initial-state emit until this processor has seen its
        # first frame (i.e. `_started=True`). `bot.py::
        # on_first_participant_joined` calls `schedule_initial_emit()`
        # which only sets this flag; the actual `push_frame` happens
        # inside `process_frame` AFTER `super().process_frame(...)`
        # has flipped `_started=True`. This routes the initial
        # envelope through EXACTLY the same downstream chain
        # (patience_tracker → context_aggregator.user() → ... →
        # transport.output()) as the working advance envelopes,
        # rather than via `task.queue_frames` which would inject
        # the frame at the SOURCE of the pipeline (before
        # transport.input(), stt, etc.) — that source-side path
        # risks intermediate consumers (e.g. user aggregator) eating
        # OutputTransportMessageFrame before it reaches the output.
        self._initial_emit_pending = False
        # Story 6.6 review patch (D1) — serialize concurrent terminal-
        # turn invocations. Without this lock, a second finalized
        # `TranscriptionFrame` arriving while the first turn awaits
        # `_run_classifier_blocking` would call `_schedule_classification`
        # which cancels the prior in-flight task. The outer `gather`
        # then returns immediately with a swallowed `CancelledError`,
        # `apply_exchange_outcome` was never called, `pt.is_hanging_up`
        # is still False, and the suppression contract of Deviation #7
        # silently breaks. The lock forces the second turn to wait for
        # the first to fully complete (including the meter update);
        # after acquiring, the second turn re-evaluates whether the
        # state is still terminal.
        self._terminal_turn_lock = asyncio.Lock()

        # Smoke-gate observability: a journalctl tail confirms both
        # the checkpoint count and the first checkpoint id alongside
        # `PatienceTracker config initial_patience=...` on call start.
        logger.info(
            "CheckpointManager init scenario_description={!r} "
            "checkpoint_count={} first_checkpoint_id={}",
            scenario_description,
            len(checkpoints),
            checkpoints[0]["id"],
        )

    def schedule_initial_emit(self) -> None:
        """Story 6.7 Phase 2 retouche #5 — flag the initial-state
        envelope for emission as soon as this processor's first frame
        has propagated (`_started=True`). Called by
        `bot.py::on_first_participant_joined`. The actual `push_frame`
        runs inside `process_frame` once `super().process_frame(...)`
        has flipped `_started=True`, ensuring the envelope rides the
        SAME downstream chain as the working `_classify_and_advance`
        envelopes (rather than entering at the pipeline source via
        `task.queue_frames`, which can be intercepted by upstream
        processors like the user aggregator).
        """
        self._initial_emit_pending = True

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Story 6.7 Phase 2 retouche #5 — emit the initial-state
        # envelope on the FIRST frame seen post-start. `super(
        # ).process_frame(...)` above has already set `_started=True`,
        # so `push_frame` is safe. Idempotent via the flag.
        if self._initial_emit_pending:
            self._initial_emit_pending = False
            await self.push_frame(
                self.build_initial_envelope(),
                FrameDirection.DOWNSTREAM,
            )
            logger.info(
                "checkpoint_initial_state total={} first_id={}",
                len(self._checkpoints),
                self._checkpoints[0]["id"],
            )

        # Pass-through MANDATORY for non-terminal turns. The terminal
        # turn path (Deviation #7) deliberately SUPPRESSES the user
        # frame so the LLM doesn't produce a parallel response that
        # lands before the hangup/completion exit line.
        if (
            isinstance(frame, TranscriptionFrame)
            # Conservative default: a future pipecat that drops the
            # `finalized` field filters interim frames OUT instead of
            # tripping the classifier on every partial transcription.
            # NOTE — intentional asymmetry with
            # `patience_tracker.py::process_frame` which uses
            # `getattr(frame, "finalized", True)` (aggressive default —
            # cancels the silence ladder on every interim TF). The
            # asymmetry reflects different cost calculus for false
            # positives: a CheckpointManager false-positive advances a
            # checkpoint on a half-word; a PatienceTracker false-
            # positive defers a hangup by one ladder tick. Both
            # defaults are documented in server/CLAUDE.md §1.
            and getattr(frame, "finalized", False)
            and frame.text.strip()
        ):
            text = frame.text.strip()
            # Deviation #7 (post-deploy 2026-05-18) — preemptive
            # synchronous classify when this turn is TERMINAL:
            #   - meter > 0 AND meter + fail_penalty <= 0  (hangup path:
            #     one more fail will zero the meter), OR
            #   - we're on the last checkpoint  (completion path: a
            #     successful verdict triggers schedule_completion).
            #
            # Under the normal parallel architecture (LLM + classifier
            # fire concurrently from the same user TranscriptionFrame),
            # the LLM lands its response in ~2-3 s while the classifier
            # verdict takes ~8-10 s. On a terminal turn this produces an
            # incoherent UX: Tina says a normal-conversation reply
            # ("What do you want to eat?"), then a 5-8 s silence, then
            # the dramatic exit line ("I don't have time for this.
            # Goodbye."). The user perceives the question as Tina's
            # last word and the exit line as a disconnected afterthought.
            #
            # The fix: when we detect a terminal turn, await the
            # classifier verdict BEFORE forwarding the frame. If the
            # verdict confirms terminal state (hangup or completion was
            # scheduled), DO NOT forward the frame — the LLM never sees
            # the user's last line, never produces a response, and the
            # exit line is the SOLE final utterance.
            #
            # If the verdict is non-terminal (user recovers in the
            # danger zone, or fails on the last checkpoint without
            # advancing), forward the frame normally so the LLM can
            # respond. Cost: ~2 s of added latency on the terminal-turn
            # check; bounded by the classifier's own 2.0 s timeout.
            pt = self._patience_tracker
            is_terminal_turn = not pt.is_hanging_up and (
                (pt.patience > 0 and pt.patience + pt.fail_penalty <= 0)
                or self._index + 1 >= len(self._checkpoints)
            )
            if is_terminal_turn:
                # Review patch (D1) — serialize concurrent terminal-turn
                # invocations through `_terminal_turn_lock`. If a second
                # finalized TranscriptionFrame arrives during the
                # `_run_classifier_blocking` await, this second call
                # blocks here until the first releases. By that time the
                # first turn's `apply_exchange_outcome` has either
                # zeroed the meter (→ `is_hanging_up=True`, this turn
                # suppresses) or recovered it (→ this turn re-checks
                # terminal state below). Without the lock, the second
                # call's `_schedule_classification` would cancel the
                # first task's awaited gather and the first turn's
                # outcome would never apply — `is_hanging_up` stays
                # False, the suppression breaks, and we get the
                # disjointed UX Deviation #7 was meant to eliminate.
                async with self._terminal_turn_lock:
                    # Re-check post-acquire: the prior holder may have
                    # already advanced/zeroed the meter while we waited.
                    if pt.is_hanging_up:
                        logger.info(
                            "checkpoint_preemptive_suppress text={!r}",
                            text[:64],
                        )
                        return
                    still_terminal = (
                        pt.patience > 0 and pt.patience + pt.fail_penalty <= 0
                    ) or self._index + 1 >= len(self._checkpoints)
                    if still_terminal:
                        try:
                            await self._run_classifier_blocking(text)
                        except Exception:
                            # Graceful degradation: if anything goes
                            # wrong in the synchronous path, fall
                            # through to push_frame below so the LLM
                            # still has something to respond to. Better
                            # than wedging the call.
                            logger.exception(
                                "checkpoint_preemptive_error; falling through to LLM"
                            )
                        if pt.is_hanging_up:
                            # Suppress the frame. Tina's exit line is the
                            # terminative final utterance.
                            logger.info(
                                "checkpoint_preemptive_suppress text={!r}",
                                text[:64],
                            )
                            return
                        # Verdict was non-terminal — fall through to
                        # push_frame below so the LLM can produce a
                        # response.
                    else:
                        # No longer terminal post-acquire (prior turn
                        # advanced a checkpoint or recovered the meter).
                        # Drop to the normal parallel path.
                        await self._schedule_classification(text)
            else:
                # Normal parallel path: schedule the classifier
                # asynchronously, let the LLM run in parallel.
                await self._schedule_classification(text)

        await self.push_frame(frame, direction)

    def build_initial_envelope(self) -> OutputTransportMessageFrame:
        """Story 6.7 AC1 — build the informational `checkpoint_advanced`
        envelope describing the FIRST checkpoint (index=0).

        Re-uses the existing `checkpoint_advanced` envelope shape
        (Story 6.7 Deviation #1 — no `v: 1` schema version; additive
        evolution under `data.{}`); the client treats this initial
        envelope identically to a real advance.

        **Important — Phase 2 retouche #4 (2026-05-19).** This method
        ONLY builds the frame. The caller (typically
        `bot.py::on_first_participant_joined`) MUST queue it via
        `task.queue_frames([...])` — NOT push via this processor —
        because `on_first_participant_joined` fires BEFORE the
        pipeline's `StartFrame` has propagated to this processor
        (`_started=False`). A `push_frame` call from that callback
        is silently rejected by pipecat with
        `"Trying to process OutputTransportMessageFrame but
        StartFrame not received yet"` (logged ERROR) — the envelope
        never reaches `transport.output()` and the client stepper
        stays blank until the first real checkpoint advance. Going
        through `task.queue_frames` adds the frame to the task's
        source queue, which is drained AFTER `StartFrame` propagation
        completes.
        """
        first = self._checkpoints[0]
        return OutputTransportMessageFrame(
            message={
                "type": "checkpoint_advanced",
                "data": {
                    "checkpoint_id": first["id"],
                    "index": 0,
                    "total": len(self._checkpoints),
                    "next_hint": first["hint_text"],
                },
            }
        )

    async def emit_initial_state(self) -> None:
        """**Legacy path — kept for unit-test coverage of the push
        mechanism**. In production, call sites MUST use
        `build_initial_envelope()` + `task.queue_frames(...)` instead
        (see [build_initial_envelope]'s docstring for the StartFrame
        race). Calling this method directly from
        `on_first_participant_joined` will fail silently because
        pipecat's `_check_started` rejects the push before `StartFrame`
        has propagated to this processor.
        """
        await self.push_frame(
            self.build_initial_envelope(),
            FrameDirection.DOWNSTREAM,
        )
        logger.info(
            "checkpoint_initial_state total={} first_id={}",
            len(self._checkpoints),
            self._checkpoints[0]["id"],
        )

    async def cleanup(self) -> None:
        """Drain any in-flight classifier task on pipeline shutdown.

        Without this hook the asyncio task is GC'd while pending →
        `Task was destroyed but it is pending!` log noise. Same pattern
        as `EmotionEmitter.cleanup` / `PatienceTracker.cleanup`.
        """
        await super().cleanup()
        prior = self._in_flight
        if prior is not None and not prior.done():
            prior.cancel()
            await asyncio.gather(prior, return_exceptions=True)
        self._in_flight = None

    async def _schedule_classification(self, user_text: str) -> None:
        """Cancel any in-flight task and schedule a fresh classifier."""
        prior = self._in_flight
        if prior is not None and not prior.done():
            prior.cancel()
            await asyncio.gather(prior, return_exceptions=True)

        self._generation += 1
        gen = self._generation
        self._in_flight = asyncio.create_task(
            self._classify_and_advance(user_text, gen)
        )

    async def _run_classifier_blocking(self, user_text: str) -> None:
        """Schedule the classifier and await its task to completion.

        Used by the Deviation #7 preemptive terminal-turn path:
        `process_frame` needs to know the verdict BEFORE deciding to
        forward the frame. `_schedule_classification` is the existing
        cancel-and-create_task primitive; this helper awaits the
        resulting in-flight task so the caller can inspect the
        post-verdict state (specifically `patience_tracker.is_hanging_up`).
        """
        await self._schedule_classification(user_text)
        in_flight = self._in_flight
        if in_flight is not None:
            await asyncio.gather(in_flight, return_exceptions=True)

    async def _classify_and_advance(self, user_text: str, generation: int) -> None:
        try:
            current = self._checkpoints[self._index]
            verdict = await self._classifier.classify(
                user_text=user_text,
                last_character_line=self._last_character_line(),
                success_criteria=current["success_criteria"],
                scenario_description=self._scenario_description,
            )
        except asyncio.CancelledError:
            # Latest-line-wins replacement; propagate the cancellation.
            raise

        # Generation guard: a newer finalized TranscriptionFrame may have
        # bumped the counter while we were waiting on OpenRouter. If our
        # task is stale, suppress its side effects — the newer task owns
        # both the meter update and any envelope emit. Log at DEBUG so
        # smoke-gate operators can disambiguate "classifier was called
        # but verdict was dropped" from "classifier never ran" when a
        # journalctl trace shows only the newer turn's apply_outcome.
        if generation != self._generation:
            logger.debug(
                "checkpoint_stale_verdict_dropped generation={} current={}",
                generation,
                self._generation,
            )
            return

        # Trimmed user_text in logs — keeps PII out of journalctl per
        # `architecture.md` line 666 ("zero PII in logs"). 64 chars is
        # enough to disambiguate cases during smoke-gate debugging
        # without storing full conversational content.
        trimmed = user_text[:64]
        current_id = current["id"]

        if verdict is None:
            # Conservative fallback per epic AC6 line 1196: classifier
            # failure / timeout / parse-error treats the exchange as a
            # failed turn for the meter, BUT does NOT advance the
            # checkpoint (no free progression). Log at warning level
            # so a degraded classifier surfaces in journalctl.
            logger.warning(
                "checkpoint_classifier_inconclusive checkpoint_id={} text={!r}",
                current_id,
                trimmed,
            )
            self._patience_tracker.apply_exchange_outcome(success=False)
            return

        if verdict is False:
            logger.info(
                "checkpoint_unmet checkpoint_id={} index={}",
                current_id,
                self._index,
            )
            self._patience_tracker.apply_exchange_outcome(success=False)
            return

        # verdict is True — checkpoint passed.
        if self._index + 1 >= len(self._checkpoints):
            # Final checkpoint passed → route to completion path.
            # Story 6.7 may later emit a separate "all complete"
            # envelope; for 6.6 the `call_end{reason:'survived'}`
            # envelope emitted by PatienceTracker._run_hang_up is the
            # client-visible signal.
            logger.info("checkpoint_completion all_passed total={}", self._index + 1)
            # Story 6.7 review (2026-05-20) — push the final count to
            # PatienceTracker so `call_end.checkpoints_passed` reflects
            # full survival (= len(self._checkpoints)) instead of the
            # legacy hardcoded 0. Drives the client-side reconcile
            # path (Deviation #2) to its terminal frame.
            self._patience_tracker.set_checkpoints_passed(len(self._checkpoints))
            self._patience_tracker.schedule_completion(survival_pct=100)
            return

        # Intermediate checkpoint passed → advance.
        self._index += 1
        next_checkpoint = self._checkpoints[self._index]
        # Story 6.7 review (2026-05-20) — keep PatienceTracker in sync
        # so a mid-flight character_hung_up emits the real passed count
        # in `call_end`, not the legacy 0.
        self._patience_tracker.set_checkpoints_passed(self._index)

        # Deviation #2 — swap the live system instruction so the LLM's
        # NEXT turn replies under the new checkpoint's prompt_segment.
        # Direct mutation of `_settings.system_instruction` is the
        # single point of truth: the OpenAI adapter reads it on every
        # request at `open_ai_adapter.py:90` and prepends it to the
        # context messages. The `LLMContext` itself stays untouched
        # (no system message lives inside it; mutating it would either
        # be ignored or trigger a "two system messages" warning).
        new_system_prompt = (
            self._base_prompt + "\n\n" + next_checkpoint["prompt_segment"].rstrip()
        )
        self._llm._settings.system_instruction = new_system_prompt

        await self.push_frame(
            OutputTransportMessageFrame(
                message={
                    "type": "checkpoint_advanced",
                    "data": {
                        "checkpoint_id": next_checkpoint["id"],
                        "index": self._index,
                        "total": len(self._checkpoints),
                        "next_hint": next_checkpoint["hint_text"],
                    },
                }
            ),
            FrameDirection.DOWNSTREAM,
        )
        logger.info(
            "checkpoint_advanced index={} total={} id={}",
            self._index,
            len(self._checkpoints),
            next_checkpoint["id"],
        )
        self._patience_tracker.apply_exchange_outcome(success=True)

    def _last_character_line(self) -> str:
        """Return the most recent assistant message from the LLMContext,
        or empty string if none yet (first user turn).

        `LLMContextAggregatorPair.assistant()` appends an assistant
        message to the context at the end of every bot turn (see
        `pipecat/processors/aggregators/llm_response_universal.py:990`).
        By the time CheckpointManager observes the NEXT user
        `TranscriptionFrame`, the previous assistant turn is already in
        the context. Reading the latest assistant message here is
        more robust than observing `TextFrame`s, which can't reach
        this processor: the LLM emits `TextFrame` DOWNSTREAM toward
        TTS, but CheckpointManager sits UPSTREAM of the LLM.
        """
        try:
            messages = self._llm_context.get_messages()
        except Exception:  # pragma: no cover — defensive
            return ""
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str):
                    return content.strip()
                # Multi-part content (image, audio) — pick the first
                # text part; if none, empty.
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            return str(part.get("text", "")).strip()
                return ""
        return ""
