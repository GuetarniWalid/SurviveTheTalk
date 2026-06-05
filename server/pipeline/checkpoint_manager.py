"""Story 6.6 / 6.10 — CheckpointManager Pipecat FrameProcessor.

Scenario-progression brain. **Story 6.10 rewrote this from a linear
state machine into a goal-tracking engine** (see
`6-10-goal-based-dialogue.md`): instead of a single `_index` that
advances 0→1→2→…, the manager owns `self._goals: dict[id, "pending" |
"met"]` and judges each finalized user turn against ALL pending
objectives in one `ExchangeClassifier.classify_multi` call. A turn that
meets ANY pending objective is credited as a success in ANY order
(anti-repetition: a credited-ahead goal drops out of the pending set, so
the character never re-asks it). **Story 6.21** then makes the character
PURSUE the remaining objectives strictly in AUTHOR ORDER — after
acknowledging what the user gave, it returns to the lowest-unmet
objective and holds there (firm but in-character) instead of roaming
ahead, so the on-screen step always matches what the character asks. This
is a STEERING-prompt change only (`format_suggested_focus_block` /
`format_remaining_goals_block`); the classifier crediting stays
any-order, so it does NOT re-introduce the strict-classifier unfair-fail
that Story 6.10 removed (see below). The system tracks which objectives
are achieved.

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
plus a FIRM pointer that holds the character on the author-order-first
remaining objective until it is addressed (Story 6.21). After
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
from dataclasses import dataclass
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
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
    """Enumerate ALL pending objectives in AUTHOR ORDER, under a header
    that tells the character to work through them strictly top-to-bottom.

    Story 6.21 — the header changed from the soft "you may pursue them in
    any order" to FIRM ordered pursuit (address the FIRST pending objective
    before any later one). The list holds ONLY unmet objectives — a
    credited-ahead goal has already dropped out of `pending_goals` — so the
    "already settled has dropped off" line is a factual reminder, NOT a
    re-ask instruction; anti-repetition is owned by the COHERENCE_CHARTER
    (Rule 1), which sits above this block.
    """
    lines = [
        "Your remaining objectives are listed in the exact order you must "
        "work through them, top to bottom: pursue the FIRST one below before "
        "any other, and move down only as each is covered. Anything already "
        "settled has dropped off this list, so everything shown is still "
        "outstanding."
    ]
    for cp in pending_goals:
        lines.append(f"- {cp['prompt_segment'].rstrip()}")
    return "\n".join(lines)


def format_suggested_focus_block(first_pending: dict) -> str:
    """Firmly point the LLM at the author-order-first remaining objective
    and hold it there until addressed — Story 6.21's core steering change.

    Replaces the soft "natural next focus / circle back later" (Story 6.10)
    with FIRM-but-FLUID ordered pursuit: the character stays on the lowest
    unmet objective and does not advance until it is addressed, but FIRST
    acknowledges (in character) anything the user volunteered for a later
    objective — so the redirect never reads as a deaf, robotic loop (which
    would also drain patience badly). "Do not re-ask settled items" is
    deferred to the COHERENCE_CHARTER above, not re-implemented here.

    Smoke-gate hardening (call_id=221): also caps the turn at ONE ask for
    the current objective and forbids tacking on later-objective probes —
    when the focused beat was already asked but not yet credited, the
    character must press/rephrase THIS objective, not roam ahead to fill
    the turn (the reply-4 forward-leak).
    """
    return (
        "Right now the only objective you may pursue is: "
        + first_pending["prompt_segment"].rstrip()
        + "\nStay on it until it is genuinely addressed, and do not move on "
        "to anything below it yet. Raise EXACTLY ONE ask this turn — this "
        "objective only — and never tack on questions that belong to later "
        "objectives to round out the turn. If you have already asked this "
        "and their answer fell short, press or rephrase THIS objective "
        "rather than advancing. If the other person has volunteered "
        "something that belongs to a later objective, genuinely take it in "
        'and react in character — a quick nod, a "noted", a flicker of '
        "interest or irritation, whatever fits you — so you never sound deaf "
        "or stuck in a loop; then, without re-raising anything already "
        "settled (the rules above keep you from that), ease the conversation "
        "back to it as the thing you still need from them. Keep that pull "
        "firm and fully in character — in your own voice and register, never "
        "a robotic, word-for-word repeated refusal."
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


# ============================================================
# Story 6.10 — pure goal-advance decision (shared with the harness)
# ============================================================


@dataclass(frozen=True)
class GoalAdvance:
    """Pure result of judging one turn's verdicts against the goal state.

    Returned by `advance_goals`. Holds everything both the live
    `CheckpointManager` AND the Story 6.15 text calibration harness need to
    apply a turn's outcome WITHOUT re-deriving the rule independently:

    - `new_goals`: post-flip `{id: "pending"|"met"}` map (a fresh copy — the
      caller may assign it back to its state without aliasing).
    - `flipped_ids`: the goal ids that flipped pending→met THIS turn, in the
      order the verdicts dict presented them (so per-flip envelope emission
      order is stable).
    - `met_count` / `all_met`: progress over `new_goals`.
    - `outcome`: `"success"` (≥1 flip → recovery_bonus), `"fail"` (no flip but
      ≥1 goal actively `unmet` → genuine off-topic, drain patience, AC8), or
      `"neutral"` (no flip, all `unsure` → model ambiguity, patience-neutral).
    """

    new_goals: dict[str, str]
    flipped_ids: list[str]
    met_count: int
    all_met: bool
    outcome: str


def advance_goals(
    goals_state: dict[str, str],
    verdicts: dict[str, bool | None],
) -> GoalAdvance:
    """Pure goal-advance decision shared by `CheckpointManager` (prod) and the
    Story 6.15 calibration harness.

    Given the current `{id: "pending"|"met"}` state and a parsed verdict dict
    `{id: True|False|None}` (the shape `ExchangeClassifier.classify_multi`
    returns — NEVER the infra-failure `None` whole-value, which the caller
    handles before reaching here), compute which goals flip, the resulting
    state, and the turn's outcome class. No side effects, no I/O — so the
    offline validator gets the EXACT flip/outcome rule prod uses (Story 6.15
    AC1: "does NOT re-implement the advance rule").
    """
    flipped_ids = [
        gid
        for gid, verdict in verdicts.items()
        if verdict is True and goals_state.get(gid) == "pending"
    ]
    new_goals = dict(goals_state)
    for gid in flipped_ids:
        new_goals[gid] = "met"
    met_count = sum(1 for state in new_goals.values() if state == "met")
    all_met = all(state == "met" for state in new_goals.values())
    if flipped_ids:
        outcome = "success"
    elif any(verdict is False for verdict in verdicts.values()):
        outcome = "fail"
    else:
        outcome = "neutral"
    return GoalAdvance(
        new_goals=new_goals,
        flipped_ids=flipped_ids,
        met_count=met_count,
        all_met=all_met,
        outcome=outcome,
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
        llm: Pipecat LLM service (e.g. `OpenAILLMService` pointed at
            Groq since the 2026-05-29 all-Groq migration). Must
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
        # `OpenAILLMService.Settings(system_instruction=...)` (Groq) it
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
                #
                # Story 6.20 AC1 — on fast re-speak (a new finalized turn
                # arrives while the PRIOR turn's classify is still in
                # flight) we AWAIT the prior classify to completion (so its
                # flips, prompt recompose, and envelope land) before judging
                # this turn against the updated goal state, instead of
                # cancelling it. Cancelling silently DROPPED a genuinely-met
                # goal (breaks_progress). The terminal-turn path above and
                # the generation guard are unchanged.
                await self._serialize_then_classify(text)
                # Story 6.20 review (async-correctness) — the awaited prior
                # classify may have flipped the FINAL goal(s) and scheduled
                # completion WHILE this turn was already committed to the
                # non-terminal path (its terminal precheck above read a STALE
                # met_count, from before the prior turn's flip landed). If the
                # call is now completing, SUPPRESS this user frame so the
                # survived exit line stays the sole final utterance — same
                # Deviation #7 contract the terminal path enforces. The old
                # cancel-based path got this for free (a cancelled prior never
                # reached schedule_completion); the await re-opened the window.
                # `met_count == total` is the precise, mock-independent signal
                # that the prior completed the call (the patience-hangup case
                # is unreachable here: a non-terminal precheck means one more
                # fail can't zero the meter).
                if self.met_count >= len(self._checkpoints):
                    logger.info(
                        "checkpoint_suppress_post_serialize_completion text={!r}",
                        text[:64],
                    )
                    return

        await self.push_frame(frame, direction)

    def build_initial_envelope(self) -> OutputTransportMessageFrame:
        """Build the informational `checkpoint_advanced` envelope
        describing the initial state (no goals met yet).

        Re-uses the `checkpoint_advanced` envelope shape (Story 6.7
        Deviation #1 — no `v: 1` schema version; additive evolution under
        `data.{}`). Story 6.10 adds `goals_met_indices: []` so a 6.10
        client renders zero filled circles on connect; a pre-6.10 client
        reads `index=0` and renders nothing filled too. Story 6.20 AC2
        dropped the dead `next_hint` field — the HUD computes the active
        step locally from `goals_met_indices` + `hints` and never read it.

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

    async def _serialize_then_classify(self, user_text: str) -> None:
        """Non-terminal fast-re-speak path (Story 6.20 AC1).

        AWAIT any in-flight classify to COMPLETION — letting it apply its
        flips, recompose the system instruction, and emit its envelope —
        BEFORE scheduling the fresh classify for this turn. Replaces the
        old cancel-before-schedule (`_schedule_classification`) on the
        non-terminal path, which discarded the in-flight POST and so
        silently dropped a goal the user had genuinely completed when they
        spoke again within the ~0.2-0.5 s classify window.

        Because `process_frame` is serialized per pipecat processor, awaiting
        the prior task here is safe (no re-entrancy). The prior task runs to
        its natural end (NOT cancelled), so its `self._goals` mutation lands;
        the fresh classify created below is then judged against that updated
        state. The generation counter is only bumped AFTER the await, so the
        prior task always sees its own generation and applies its side
        effects (the generation guard stays a backstop for the still-cancel-
        based terminal path).

        Trade-off (accepted by AC1): on a genuine fast re-speak this defers
        forwarding the new user frame to the LLM until the prior classify
        resolves — which is also CORRECT for coherence, since the recomposed
        system instruction (smaller pending set) must land before the LLM
        replies to the new turn. In the common case the prior task is already
        `done()` and the await is a no-op (zero added latency).
        """
        prior = self._in_flight
        if prior is not None and not prior.done():
            await asyncio.gather(prior, return_exceptions=True)

        # Story 6.20 review — if the awaited prior classify completed every
        # goal, the call is ending (schedule_completion already fired); don't
        # schedule a fresh classify that would only no-op on an empty pending
        # set. The caller (process_frame) suppresses the user frame so no
        # parallel LLM reply races the exit line.
        if not self.pending_goals:
            return

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

        # INFRA FAILURE — `classify_multi` returns None on timeout / HTTP
        # error / closed-client race / non-2xx / empty choices / unparseable
        # body. Patience-neutral (Deviation #5) + the consecutive-None
        # backstop (Story 6.9 D1). A PARSED response is a dict, NOT None —
        # even an all-"unsure" dict is genuine model ambiguity, not infra,
        # so it must NOT feed the backstop (review D3, 2026-05-29: the old
        # all-None-dict conflation fabricated a false "sustained failure"
        # alert on a healthy-but-uncertain classifier).
        if verdicts is None:
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
                user_text[:64],
                self._consecutive_none_count,
                len(pending),
            )
            return

        # A real (parsed) verdict landed — reset the infra backstop.
        self._consecutive_none_count = 0

        # Pure goal-advance decision (shared verbatim with the Story 6.15
        # text calibration harness via `advance_goals`) — keeps prod and the
        # offline validator from forking the flip/outcome rule.
        advance = advance_goals(self._goals, verdicts)

        if advance.outcome == "fail":
            # No objective flipped AND the classifier actively judged at
            # least one goal "unmet" (False) → genuine off-topic / true
            # miss → drain patience (AC8: fail ONLY when NO goal matched).
            logger.info(
                "checkpoint_unmet no_goal_flipped met_count={} pending={}",
                self.met_count,
                len(pending),
            )
            self._patience_tracker.apply_exchange_outcome(success=False)
            return

        if advance.outcome == "neutral":
            # EVERY goal came back "unsure" (all None in a PARSED dict) →
            # genuine model ambiguity → patience-neutral (no penalty, no
            # false sustained-failure alert).
            logger.info(
                "checkpoint_all_unsure no_goal_flipped met_count={} pending={} "
                "(patience unchanged — model uncertain, not infra)",
                self.met_count,
                len(pending),
            )
            return

        # outcome == "success": >=1 objective flipped → SUCCESS turn.
        self._goals = advance.new_goals
        flipped_ids = advance.flipped_ids
        all_met = advance.all_met

        # Keep PatienceTracker's checkpoints_passed in sync so a mid-flight
        # character_hung_up emits the real passed count in `call_end`
        # (Story 6.7 review). On completion met_count == total.
        self._patience_tracker.set_checkpoints_passed(self.met_count)
        # Story 6.20 AC3 — also mirror the REAL met SET (author-order
        # indices) so `call_end` carries WHICH goals were met, not just how
        # many; the client reconcile prefers it (walk-up-only / never shrink)
        # and a future debrief can't mislabel out-of-order completions.
        self._patience_tracker.set_goals_met_indices(self._goals_met_indices())

        # Recompose the live system instruction with the smaller pending
        # set (Deviation #2 + AC4). When all_met the composition collapses
        # to the wrap-up directive.
        self._update_system_instruction()

        # Emit one envelope per flip so the client stepper animates each
        # circle (AC6). All envelopes in this turn carry the SAME post-flip
        # full-state `goals_met_indices` + `hints` (Story 6.20 AC2 dropped
        # the dead `next_hint`).
        goals_met_indices = self._goals_met_indices()
        for gid in flipped_ids:
            await self._emit_checkpoint_advanced(gid, goals_met_indices)

        if all_met:
            # Final objective met → completion path. PatienceTracker emits
            # the `call_end{reason:'survived'}` envelope. Do NOT also call
            # apply_exchange_outcome — the call is ending and
            # schedule_completion has already flipped is_hanging_up
            # (apply_exchange_outcome would be a no-op anyway).
            logger.info(
                "checkpoint_completion all_passed total={}", len(self._checkpoints)
            )
            # Story 6.18 review (Decision #2 / Option A) — hand the winning
            # user turn to the completion path. This turn is the one being
            # SUPPRESSED from the LLM context (Deviation #7), so the survived
            # exit line is otherwise generated from a transcript that ends on
            # the character's unanswered question; passing it lets the closing
            # line reference the answer that actually won.
            self._patience_tracker.schedule_completion(
                survival_pct=100, winning_user_text=user_text
            )
            return

        # Partial / intermediate success (AC8 — recovery_bonus applies on
        # ANY successful turn, even if only one of several pending goals
        # was met this turn).
        self._patience_tracker.apply_exchange_outcome(success=True)

    async def _emit_checkpoint_advanced(
        self, goal_id: str, goals_met_indices: list[int]
    ) -> None:
        """Push the `checkpoint_advanced` envelope(s) for a single flipped
        goal (Story 6.10 AC6).

        - `index` = the author-order index of THE goal that just flipped
          (so a pre-6.10 client renders the most-recent flip correctly).
        - `goals_met_indices` = the FULL set of met indices (author
          order) so a 6.10 client renders the exact set, including
          out-of-order fills.

        Story 6.20 AC2 dropped the dead `next_hint` field (the HUD computes
        the active step locally from `goals_met_indices` + `hints`).
        """
        idx = self._id_to_index[goal_id]
        data = {
            "checkpoint_id": goal_id,
            "index": idx,
            "total": len(self._checkpoints),
            "goals_met_indices": goals_met_indices,
            # Story 6.10 (UI refonte) — see build_initial_envelope.
            "hints": self._all_hints(),
        }
        message = {"type": "checkpoint_advanced", "data": data}
        # URGENT (SystemFrame), NOT the queued OutputTransportMessageFrame:
        # the flip fires mid-turn while the character LLM is busy streaming
        # its reply. A queued DataFrame would sit in each processor's
        # process-queue BEHIND that in-flight generation (pipecat serializes
        # non-system frames per processor), so the client only received the
        # checkpoint AFTER Tina finished speaking — the box looked unticked
        # the whole time she talked (Walid 2026-05-29). A SystemFrame jumps
        # the per-processor queue at every stage and reaches the transport
        # immediately, so the tick lands ~at classify time (~0.2-0.5 s),
        # before/while she starts speaking. The envelope is full-state
        # (goals_met_indices + hints), so out-of-order delivery is safe.
        await self.push_frame(
            OutputTransportMessageUrgentFrame(message=message),
            FrameDirection.DOWNSTREAM,
        )
        # Story 6.20 AC5 — lost-tail self-heal. The URGENT copy above jumps
        # the per-processor queue and is sent the moment the flip lands, but
        # it does so during the most turbulent moment of the turn (mid-LLM
        # stream, and on the completion path right before the hang-up
        # InterruptionFrame). If that send races with room teardown the LAST
        # flip would have NO resend — full-state envelopes otherwise only
        # self-heal on the NEXT flip, and there is no next flip after the
        # final one. So ALSO emit the SAME full-state envelope as a queued
        # `OutputTransportMessageFrame`, which travels the ordered media-
        # sender path (a second, independent delivery opportunity). Both
        # ride LiveKit `send_data(reliable=True)` in this pipecat build, so
        # this is belt-and-suspenders, not a lossy→reliable upgrade. The
        # client dedupes via `_animatedMet` (an identical full-state snapshot
        # is a value-equal no-op), so the duplicate is harmless. The mid-call
        # case is covered here; the terminal/hang-up case is ALSO backstopped
        # by the `call_end` `goals_met_indices` reconcile (AC3).
        await self.push_frame(
            OutputTransportMessageFrame(message=message),
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
