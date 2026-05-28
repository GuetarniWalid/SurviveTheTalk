"""Story 6.6 / 6.10 — CheckpointManager Pipecat FrameProcessor.

Scenario-progression brain. **Story 6.10 rewrote this from a linear
state machine into a goal-tracking engine** (see
`6-10-goal-based-dialogue.md`): instead of a single `_index` that
advances 0→1→2→…, the manager owns `self._goals: dict[id, "pending" |
"met"]` and judges each finalized user turn against ALL pending
objectives in one `ExchangeClassifier.classify_multi` call. A turn that
meets ANY pending objective (in any order) is a success; the LLM is free
to pursue objectives in the order it finds natural, and the system
simply tracks which ones are achieved.

Why the shift (call_id=137, 2026-05-20): LLMs are trained on naturally-
fluid conversation. A state machine that forces a strict question order
contradicts that training → the LLM drifts (e.g. Tina jumps to the drink
question before clarifying the dish) → the old single-index classifier,
still anchored on the skipped checkpoint, judged every on-topic reply as
`not_met` → patience drained to zero on perfectly reasonable answers →
unfair `character_hung_up`. Goal-tracking realigns the architecture with
how the LLM actually reasons.

On a successful turn the manager recomposes the live LLM system
instruction (`base_prompt + COHERENCE_CHARTER + REMAINING_GOALS_BLOCK +
SUGGESTED_FOCUS_BLOCK`) so the next bot turn sees the smaller pending set
plus a soft pointer to the author-order-first remaining objective. After
ALL goals are met, routes through
`PatienceTracker.schedule_completion(survival_pct=100)` to end the call
with `reason='survived'` and the YAML's `exit_lines.completion` line.

**Pass-through is mandatory.** This processor observes user
`TranscriptionFrame`s; it must forward every frame downstream unchanged
(Story 6.3 review found 3 silent regressions where a `return` before
`push_frame` swallowed the LLM/TTS path). The classifier call is
fire-and-forget inside an `asyncio.create_task` so the main pipeline
never blocks on the OpenRouter/Groq round-trip.

Deviations carried forward (also in the story's Implementation Notes):

  - **Deviation #1 (6.6).** Two distinct `survival_pct` formulas:
        reason='survived'   → 100 (met every objective).
        reason='character_hung_up' / 'inappropriate_content'
                            → patience-meter ratio.
    Owned by `PatienceTracker._run_hang_up` after this manager threads
    the override via `schedule_completion(survival_pct=100)`.

  - **Deviation #2 — system-prompt swap mechanism.** Mutate
    `llm._settings.system_instruction` directly — the single point of
    truth the OpenAI adapter reads on every request
    (`open_ai_adapter.py:90`). The `LLMContext` stays untouched (empty
    at boot; mutating it would add a 2nd system message + a warning).
    `pipecat.services.settings.Settings` documents these as
    "Runtime-updatable settings"; direct assignment is supported.

  - **Deviation #3 (6.6).** YAML `exit_lines.completion` flows into
    `hang_up_line_survived`; `exit_lines.hangup` is shared by both
    silence and inappropriate paths. Owned by
    `scenarios.resolve_patience_config`.

  - **Deviation #7 (6.6, redefined for goals in 6.10).** Preemptive
    synchronous classify on TERMINAL turns. Under goals a terminal turn
    is one where (a) the next failed exchange would zero the patience
    meter (hangup path) OR (b) only ONE objective remains pending so
    completing it would end the call (completion path). On terminal
    turns the manager AWAITS the classifier verdict before forwarding
    the user `TranscriptionFrame`; if the verdict confirms terminal
    state, the frame is **suppressed** (not pushed downstream) so the
    LLM never produces a parallel response that lands before the
    hangup/completion exit line. Pass-through is INTENTIONALLY violated
    for terminal turns; non-terminal turns retain the forward-first
    pattern.

Last-character-line sourcing: this manager reads the most recent
assistant message from `llm_context.get_messages()` at classify time,
not by observing `TextFrame`s. The LLM's `TextFrame` flows DOWNSTREAM
(toward TTS) and CheckpointManager sits UPSTREAM of the LLM, so the
shared `LLMContext` (populated by `LLMContextAggregatorPair.assistant()`)
is the authoritative source for "what the character last said".

Direction sensitivity (per `server/CLAUDE.md` §1 and project memory
🪤 `feedback_pipecat_frame_direction_test_trap.md`): user
`TranscriptionFrame`s flow DOWNSTREAM from STT through the user
aggregator to this processor; we don't gate on direction (mirroring
`EmotionEmitter`). The pipeline-driven contract test in
`test_bot_pipeline_wiring.py` is the regression net.
"""

from __future__ import annotations

import asyncio
import inspect
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

# Story 6.9 review patch (D1) — after this many consecutive turns where
# the classifier returns NO real verdict (all goals inconclusive — HTTP
# error / timeout / parse failure), force `apply_exchange_outcome(
# success=False)` to surface the sustained infra failure to the user
# instead of soft-locking the call. Picked at 5 because at -15 patience
# per drain, 5 consecutive forces ~one hangup cycle (75 / 100 initial
# patience) — the user sees the call degrade and ends naturally instead
# of silently spinning forever on a degraded classifier.
_MAX_CONSECUTIVE_NONE_VERDICTS = 5


# ============================================================
# Story 6.10 — dynamic system-instruction composition helpers
# ============================================================
#
# The goal-based prompt is recomposed after every successful turn. These
# module-level functions are shared by `bot.py` (initial composition at
# call boot) and `CheckpointManager._update_system_instruction` (every
# recompose) so the two never drift — a single source of truth for the
# `base + charter + REMAINING_GOALS_BLOCK + SUGGESTED_FOCUS_BLOCK` shape.


def format_remaining_goals_block(pending_goals: list[dict]) -> str:
    """Enumerate ALL pending objectives (author order) with their
    `prompt_segment` text, under a goal-agnostic header. The LLM sees
    everything that is left so it can pursue any of them naturally.
    """
    lines = ["Your remaining objectives (you may pursue them in any order):"]
    for cp in pending_goals:
        lines.append(f"- {cp['prompt_segment'].rstrip()}")
    return "\n".join(lines)


def format_suggested_focus_block(first_pending: dict) -> str:
    """Soft-point the LLM at the author-order-first remaining objective
    as "the natural next focus", while explicitly permitting it to flow
    to another remaining objective and circle back. This preserves the
    scenario author's intended order as a HINT, not a constraint.
    """
    return (
        "The natural next focus is: "
        + first_pending["prompt_segment"].rstrip()
        + "\nIf the conversation flows toward another remaining objective, "
        "accept that and circle back to this one later — naturally."
    )


def compose_goal_system_instruction(
    *,
    base_prompt: str,
    coherence_charter: str,
    pending_goals: list[dict],
) -> str:
    """Compose the full goal-based system instruction.

    `base_prompt + COHERENCE_CHARTER + REMAINING_GOALS_BLOCK +
    SUGGESTED_FOCUS_BLOCK`. When ZERO goals remain pending, the
    objectives blocks collapse to a single wrap-up directive so the LLM
    closes the conversation naturally (the completion exit line is owned
    by PatienceTracker, but the LLM may speak one last in-character turn
    before the call ends). The charter ALWAYS sits between base_prompt
    and the objectives so its position never moves across the call.
    """
    base = base_prompt.rstrip()
    if not pending_goals:
        return (
            base
            + "\n\n"
            + coherence_charter
            + "\n\nAll objectives complete. Wrap up the conversation naturally."
        )
    return (
        base
        + "\n\n"
        + coherence_charter
        + "\n\n"
        + format_remaining_goals_block(pending_goals)
        + "\n\n"
        + format_suggested_focus_block(pending_goals[0])
    )


class CheckpointManager(FrameProcessor):
    """Owns scenario-goal progression for one call (Story 6.10).

    Args:
        base_prompt: Scenario YAML `base_prompt` (rstrip'd, no
            `_SPEAK_FIRST_DIRECTIVE` suffix). Composed live with the
            COHERENCE_CHARTER + the pending-goals blocks on every
            successful turn.
        checkpoints: Ordered list of checkpoint dicts; each entry has
            `id`, `hint_text`, `prompt_segment`, `success_criteria`.
            The ORDER serves as a HINT (suggested focus) — not a strict
            constraint — under the goal-based model. Validated at load
            time by `scenarios.load_scenario_checkpoints`.
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
            `schedule_completion` after the final objective is met.
        scenario_description: Short scenario context (e.g. metadata
            title "The Waiter") embedded in the classifier prompt.
        coherence_charter: Story 6.8 Phase 2 — system-wide conversation
            coherence rules (the `COHERENCE_CHARTER` constant from
            `pipeline.prompts`). Threaded EXPLICITLY (no default) so a
            future refactor that drops the import in `bot.py` surfaces
            as a missing-kwarg `TypeError` at call init. Composed
            BETWEEN `base_prompt` and the objectives blocks — same
            position as `bot.py`'s initial composition.
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
        coherence_charter: str,
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
        # time. Check the path exists at construction so pipecat API
        # drift surfaces at call init.
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
        # Story 6.8 Phase 2 — see class docstring. Stored verbatim; the
        # composition slots it BETWEEN base_prompt and the objectives so
        # the charter never moves around the prompt. No rstrip/lstrip —
        # the YAML-author convention is that the constant ships with its
        # own trailing newline.
        self._coherence_charter = coherence_charter

        # Story 6.10 — goal-tracking state model. `self._goals` maps each
        # checkpoint id to "pending" | "met"; `self._id_to_index` maps id
        # → author-order index (for the envelope `index` field +
        # `goals_met_indices`). Replaces the linear `self._index`.
        self._goals: dict[str, str] = {cp["id"]: "pending" for cp in checkpoints}
        self._id_to_index: dict[str, int] = {
            cp["id"]: i for i, cp in enumerate(checkpoints)
        }

        # Latest-line-wins: each new finalized TranscriptionFrame cancels
        # the prior classify before scheduling a fresh task. Same shape
        # as EmotionEmitter's generation-counter guard — the cancel
        # alone isn't enough because `push_frame` may not be a
        # cancellation point in pipecat.
        self._in_flight: asyncio.Task[None] | None = None
        self._generation = 0
        # Story 6.7 Phase 2 retouche #5 — defer the initial-state emit
        # until this processor has seen its first frame
        # (`_started=True`). `bot.py::on_first_participant_joined` calls
        # `schedule_initial_emit()` which only sets this flag; the actual
        # `push_frame` happens inside `process_frame` AFTER
        # `super().process_frame(...)` has flipped `_started=True`,
        # routing the envelope through the SAME downstream chain as the
        # working advance envelopes.
        self._initial_emit_pending = False
        # Story 6.6 review patch (D1) — serialize concurrent terminal-
        # turn invocations so a second finalized TranscriptionFrame
        # cannot cancel the first turn's awaited classify (which would
        # swallow its `apply_exchange_outcome` and silently break the
        # Deviation #7 suppression contract).
        self._terminal_turn_lock = asyncio.Lock()

        # Story 6.9 review patch (D1) — counter for consecutive turns
        # where the classifier returns NO real verdict (all goals
        # inconclusive). Deviation #5 made infra failure patience-neutral
        # to stop punishing the user for provider hiccups; the side
        # effect is an unbounded soft-lock window if the provider stays
        # degraded. After `_MAX_CONSECUTIVE_NONE_VERDICTS` consecutive
        # all-None turns we force `apply_exchange_outcome(success=False)`
        # to surface the degradation as a normal drain. Reset on any
        # real (True/False) verdict.
        self._consecutive_none_count: int = 0

        # Story 6.10 — compose the initial goal-based system instruction
        # so the FIRST LLM turn already reflects the full pending-goals
        # set (AC4: `_update_system_instruction` called once at
        # construction). bot.py composes the identical string for the
        # `OpenRouterLLMService.Settings(system_instruction=...)` it
        # passes in; this call re-sets it to the same value (idempotent),
        # and keeps the manager authoritative if bot.py's initial
        # composition ever drifts.
        self._update_system_instruction()

        # Smoke-gate observability: a journalctl tail confirms both the
        # checkpoint count and the first checkpoint id alongside
        # `PatienceTracker config initial_patience=...` on call start.
        logger.info(
            "CheckpointManager init scenario_description={!r} "
            "checkpoint_count={} first_checkpoint_id={}",
            scenario_description,
            len(checkpoints),
            checkpoints[0]["id"],
        )

    # ---------- Public read-only properties (Story 6.10 AC1) ----------

    @property
    def goals_state(self) -> dict[str, str]:
        """Copy of the `{goal_id: "pending"|"met"}` state map (for tests
        + observability)."""
        return dict(self._goals)

    @property
    def pending_goals(self) -> list[dict]:
        """Pending checkpoint dicts in ORIGINAL AUTHOR ORDER (preserves
        the suggested-focus semantics — `pending_goals[0]` is the
        author's intended next focus)."""
        return [cp for cp in self._checkpoints if self._goals[cp["id"]] == "pending"]

    @property
    def met_count(self) -> int:
        """Number of objectives currently met (envelope payload +
        observability + the terminal-turn predicate)."""
        return sum(1 for state in self._goals.values() if state == "met")

    def schedule_initial_emit(self) -> None:
        """Story 6.7 Phase 2 retouche #5 — flag the initial-state
        envelope for emission as soon as this processor's first frame has
        propagated (`_started=True`). Called by
        `bot.py::on_first_participant_joined`. The actual `push_frame`
        runs inside `process_frame` once `super().process_frame(...)` has
        flipped `_started=True`.
        """
        self._initial_emit_pending = True

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        # Story 6.7 Phase 2 retouche #5 — emit the initial-state envelope
        # on the FIRST frame seen post-start. Idempotent via the flag.
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

        # Pass-through MANDATORY for non-terminal turns. The terminal-turn
        # path (Deviation #7) deliberately SUPPRESSES the user frame so
        # the LLM doesn't produce a parallel response that lands before
        # the hangup/completion exit line.
        if (
            isinstance(frame, TranscriptionFrame)
            # Conservative default: a future pipecat that drops the
            # `finalized` field filters interim frames OUT instead of
            # tripping the classifier on every partial transcription.
            # NOTE — intentional asymmetry with `patience_tracker.py`
            # which defaults to True (documented in server/CLAUDE.md §1).
            and getattr(frame, "finalized", False)
            and frame.text.strip()
        ):
            text = frame.text.strip()
            # Deviation #7 (redefined for goals, Story 6.10) — preemptive
            # synchronous classify when this turn is TERMINAL:
            #   - meter > 0 AND meter + fail_penalty <= 0  (hangup path:
            #     one more fail will zero the meter), OR
            #   - only ONE objective remains pending (completion path: a
            #     successful verdict on the last goal triggers
            #     schedule_completion).
            #
            # On a terminal turn we await the verdict BEFORE forwarding
            # the frame; if the verdict confirms terminal state the frame
            # is suppressed and the exit line is the SOLE final utterance.
            # If non-terminal (recovery / partial), fall through to
            # push_frame so the LLM responds normally.
            pt = self._patience_tracker
            is_terminal_turn = not pt.is_hanging_up and (
                (pt.patience > 0 and pt.patience + pt.fail_penalty <= 0)
                or self.met_count + 1 >= len(self._checkpoints)
            )
            if is_terminal_turn:
                # Review patch (D1) — serialize concurrent terminal-turn
                # invocations through `_terminal_turn_lock`. Without it,
                # a second finalized TranscriptionFrame's
                # `_schedule_classification` would cancel the first task's
                # awaited gather before its outcome applied, breaking the
                # suppression contract.
                async with self._terminal_turn_lock:
                    # Re-check post-acquire: the prior holder may have
                    # already completed/zeroed the meter while we waited.
                    if pt.is_hanging_up:
                        logger.info(
                            "checkpoint_preemptive_suppress text={!r}",
                            text[:64],
                        )
                        return
                    still_terminal = (
                        pt.patience > 0 and pt.patience + pt.fail_penalty <= 0
                    ) or self.met_count + 1 >= len(self._checkpoints)
                    if still_terminal:
                        try:
                            await self._run_classifier_blocking(text)
                        except Exception:
                            # Graceful degradation: if anything goes wrong
                            # in the synchronous path, fall through to
                            # push_frame below so the LLM still has
                            # something to respond to.
                            logger.exception(
                                "checkpoint_preemptive_error; falling through to LLM"
                            )
                        if pt.is_hanging_up:
                            # Suppress the frame. The exit line is the
                            # terminative final utterance.
                            logger.info(
                                "checkpoint_preemptive_suppress text={!r}",
                                text[:64],
                            )
                            return
                        # Verdict was non-terminal — fall through to
                        # push_frame below so the LLM can respond.
                    else:
                        # No longer terminal post-acquire (prior turn met
                        # a goal or recovered the meter). Drop to the
                        # normal parallel path.
                        await self._schedule_classification(text)
            else:
                # Normal parallel path: schedule the classifier
                # asynchronously, let the LLM run in parallel.
                await self._schedule_classification(text)

        await self.push_frame(frame, direction)

    def build_initial_envelope(self) -> OutputTransportMessageFrame:
        """Build the informational `checkpoint_advanced` envelope
        describing the initial state (no goals met yet).

        Re-uses the `checkpoint_advanced` envelope shape (Story 6.7
        Deviation #1 — no `v: 1` schema version; additive evolution under
        `data.{}`). Story 6.10 adds `goals_met_indices: []` so a 6.10
        client renders zero filled circles on connect; a pre-6.10 client
        reads `index=0` and renders nothing filled too.

        **Important (Phase 2 retouche #4).** This method ONLY builds the
        frame. In production it is queued via `schedule_initial_emit()` +
        the deferred push in `process_frame`, never pushed directly from
        `on_first_participant_joined` (StartFrame race — see git history).
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
                    # Story 6.10 — full set of met indices (empty at boot).
                    "goals_met_indices": [],
                    # Story 6.10 (UI refonte) — ALL step hints in author
                    # order so the Flutter step HUD can render + animate any
                    # step locally (including out-of-order completions).
                    "hints": self._all_hints(),
                },
            }
        )

    async def emit_initial_state(self) -> None:
        """**Legacy push path — kept for unit-test coverage of the push
        mechanism**. Production call sites MUST use
        `schedule_initial_emit()` (see `build_initial_envelope`'s
        docstring for the StartFrame race).
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
        """Drain any in-flight classifier task + close the classifier's
        persistent httpx client on pipeline shutdown.

        Same pattern as `EmotionEmitter.cleanup` / `PatienceTracker.
        cleanup`. `inspect.iscoroutinefunction` guards against a test
        classifier without a real async `close()`.
        """
        await super().cleanup()
        prior = self._in_flight
        if prior is not None and not prior.done():
            prior.cancel()
            await asyncio.gather(prior, return_exceptions=True)
        self._in_flight = None
        close_fn = getattr(self._classifier, "close", None)
        if close_fn is not None and inspect.iscoroutinefunction(close_fn):
            await close_fn()

    async def _schedule_classification(self, user_text: str) -> None:
        """Cancel any in-flight task and schedule a fresh classifier."""
        prior = self._in_flight
        if prior is not None and not prior.done():
            prior.cancel()
            await asyncio.gather(prior, return_exceptions=True)

        self._generation += 1
        gen = self._generation
        self._in_flight = asyncio.create_task(
            self._classify_and_flip_goals(user_text, gen)
        )

    async def _run_classifier_blocking(self, user_text: str) -> None:
        """Schedule the classifier and await its task to completion.

        Used by the Deviation #7 preemptive terminal-turn path:
        `process_frame` needs the verdict BEFORE deciding to forward the
        frame, so it inspects the post-verdict
        `patience_tracker.is_hanging_up`.
        """
        await self._schedule_classification(user_text)
        in_flight = self._in_flight
        if in_flight is not None:
            await asyncio.gather(in_flight, return_exceptions=True)

    async def _classify_and_flip_goals(self, user_text: str, generation: int) -> None:
        """Judge the user turn against ALL pending goals in one call and
        flip every goal the user met. Story 6.10 AC5."""
        pending = self.pending_goals
        if not pending:
            # All goals already met (completion path fired on a prior
            # turn). Nothing to evaluate.
            return
        try:
            verdicts = await self._classifier.classify_multi(
                user_text=user_text,
                last_character_line=self._last_character_line(),
                pending_goals=[
                    {"id": cp["id"], "success_criteria": cp["success_criteria"]}
                    for cp in pending
                ],
                scenario_description=self._scenario_description,
            )
        except asyncio.CancelledError:
            # Latest-line-wins replacement; propagate the cancellation.
            raise

        # Generation guard: a newer finalized TranscriptionFrame may have
        # bumped the counter while we waited on the provider. If our task
        # is stale, suppress its side effects — the newer task owns both
        # the meter update and any envelope emit.
        if generation != self._generation:
            logger.debug(
                "checkpoint_stale_verdict_dropped generation={} current={}",
                generation,
                self._generation,
            )
            return

        trimmed = user_text[:64]

        # Which pending goals flipped to met this turn?
        flipped_ids = [
            gid
            for gid, verdict in verdicts.items()
            if verdict is True and self._goals.get(gid) == "pending"
        ]
        any_real_verdict = any(v is not None for v in verdicts.values())

        if not flipped_ids:
            # No objective met this turn. Distinguish infra failure
            # (all-None — provider hiccup) from a genuine off-topic miss
            # (at least one objective actively judged False).
            if not any_real_verdict:
                # INFRA FAILURE path (Deviation #5) — patience-neutral,
                # plus the consecutive-None backstop (Story 6.9 D1).
                self._consecutive_none_count += 1
                if self._consecutive_none_count >= _MAX_CONSECUTIVE_NONE_VERDICTS:
                    logger.error(
                        "checkpoint_classifier_sustained_failure consecutive_none={} "
                        "pending={} — forcing fail_penalty to surface "
                        "classifier degradation",
                        self._consecutive_none_count,
                        len(pending),
                    )
                    self._patience_tracker.apply_exchange_outcome(success=False)
                    self._consecutive_none_count = 0
                    return
                logger.warning(
                    "checkpoint_classifier_inconclusive text={!r} consecutive_none={} "
                    "pending={} (patience unchanged — infra failure)",
                    trimmed,
                    self._consecutive_none_count,
                    len(pending),
                )
                return
            # Genuine off-topic / true-miss turn — the user addressed
            # none of the pending objectives. Drain patience (AC8: fail
            # ONLY when NO goal matched this turn).
            self._consecutive_none_count = 0
            logger.info(
                "checkpoint_unmet no_goal_flipped met_count={} pending={}",
                self.met_count,
                len(pending),
            )
            self._patience_tracker.apply_exchange_outcome(success=False)
            return

        # >=1 objective flipped → SUCCESS turn. Reset the infra counter.
        self._consecutive_none_count = 0
        for gid in flipped_ids:
            self._goals[gid] = "met"

        all_met = all(state == "met" for state in self._goals.values())

        # Keep PatienceTracker's checkpoints_passed in sync so a mid-flight
        # character_hung_up emits the real passed count in `call_end`
        # (Story 6.7 review). On completion met_count == total.
        self._patience_tracker.set_checkpoints_passed(self.met_count)

        # Recompose the live system instruction with the smaller pending
        # set (Deviation #2 + AC4). When all_met the composition collapses
        # to the wrap-up directive.
        self._update_system_instruction()

        # Emit one envelope per flip so the client stepper animates each
        # circle (AC6). All envelopes in this turn carry the SAME
        # post-flip `goals_met_indices` + suggested-focus `next_hint`.
        goals_met_indices = self._goals_met_indices()
        next_hint = self._suggested_focus_hint()
        for gid in flipped_ids:
            await self._emit_checkpoint_advanced(gid, goals_met_indices, next_hint)

        if all_met:
            # Final objective met → completion path. PatienceTracker emits
            # the `call_end{reason:'survived'}` envelope. Do NOT also call
            # apply_exchange_outcome — the call is ending and
            # schedule_completion has already flipped is_hanging_up
            # (apply_exchange_outcome would be a no-op anyway).
            logger.info(
                "checkpoint_completion all_passed total={}", len(self._checkpoints)
            )
            self._patience_tracker.schedule_completion(survival_pct=100)
            return

        # Partial / intermediate success (AC8 — recovery_bonus applies on
        # ANY successful turn, even if only one of several pending goals
        # was met this turn).
        self._patience_tracker.apply_exchange_outcome(success=True)

    async def _emit_checkpoint_advanced(
        self, goal_id: str, goals_met_indices: list[int], next_hint: str
    ) -> None:
        """Push one `checkpoint_advanced` envelope for a single flipped
        goal (Story 6.10 AC6).

        - `index` = the author-order index of THE goal that just flipped
          (so a pre-6.10 client renders the most-recent flip correctly).
        - `goals_met_indices` = the FULL set of met indices (author
          order) so a 6.10 client renders the exact set, including
          out-of-order fills.
        - `next_hint` = hint of the suggested-focus pending goal, or "".
        """
        idx = self._id_to_index[goal_id]
        await self.push_frame(
            OutputTransportMessageFrame(
                message={
                    "type": "checkpoint_advanced",
                    "data": {
                        "checkpoint_id": goal_id,
                        "index": idx,
                        "total": len(self._checkpoints),
                        "next_hint": next_hint,
                        "goals_met_indices": goals_met_indices,
                        # Story 6.10 (UI refonte) — see build_initial_envelope.
                        "hints": self._all_hints(),
                    },
                }
            ),
            FrameDirection.DOWNSTREAM,
        )
        logger.info(
            "checkpoint_advanced index={} total={} id={} goals_met_indices={}",
            idx,
            len(self._checkpoints),
            goal_id,
            goals_met_indices,
        )

    def _goals_met_indices(self) -> list[int]:
        """Sorted author-order indices of all currently-met goals."""
        return sorted(
            self._id_to_index[gid]
            for gid, state in self._goals.items()
            if state == "met"
        )

    def _all_hints(self) -> list[str]:
        """All checkpoint hint_texts in author order (envelope payload).

        Story 6.10 UI refonte — the client step HUD is now a Flutter
        widget overlaid on the Rive character (the Rive `.riv` no longer
        renders checkpoints). Carrying every step's text on each envelope
        lets the widget render + animate ANY step locally — including the
        out-of-order completion choreography (show the just-completed step
        checked, then return to the active pending step) — without a
        per-flip round-trip. Idempotent + cheap (~6 short strings), same
        loss-robust philosophy as `goals_met_indices`.
        """
        return [cp["hint_text"] for cp in self._checkpoints]

    def _suggested_focus_hint(self) -> str:
        """Hint of the author-order-first pending goal, or "" if all met."""
        pending = self.pending_goals
        return pending[0]["hint_text"] if pending else ""

    def _update_system_instruction(self) -> None:
        """Recompose `llm._settings.system_instruction` from the current
        pending-goals set (Deviation #2 + AC4). Called at construction and
        after every successful flip.
        """
        composed = compose_goal_system_instruction(
            base_prompt=self._base_prompt,
            coherence_charter=self._coherence_charter,
            pending_goals=self.pending_goals,
        )
        # Story 6.8 Phase 2 (AC15 box 3 / smoke-gate guard) — WARN if the
        # composed prompt accidentally contains the charter twice (e.g. a
        # future refactor pre-pends it inside base_prompt AND lets the
        # composition add it again). Surface the mistake LOUD in
        # journalctl so the operator catches the ~200-token bloat.
        charter_count = composed.count(self._coherence_charter)
        if charter_count > 1:
            logger.warning(
                "prompt contains duplicate COHERENCE_CHARTER count={} met_count={}",
                charter_count,
                self.met_count,
            )
        self._llm._settings.system_instruction = composed

    def _last_character_line(self) -> str:
        """Return the most recent assistant message from the LLMContext,
        or empty string if none yet (first user turn).

        Reading the latest assistant message is more robust than observing
        `TextFrame`s: the LLM emits `TextFrame` DOWNSTREAM toward TTS, but
        CheckpointManager sits UPSTREAM of the LLM.
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
                # Multi-part content (image, audio) — pick the first text
                # part; if none, empty.
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            return str(part.get("text", "")).strip()
                return ""
        return ""
