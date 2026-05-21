# Story 6.10: Goal-Based Dialogue Architecture (Steps → Goals shift)

Status: ready-for-dev

## Story

As the operator (Walid),
I want the dialogue engine to track scenario objectives as a **set of goals to achieve in any order** rather than a strict linear checkpoint sequence,
so that the conversation flows naturally (LLM can ask about drinks before clarifying cooking style, then naturally return to clarify), and B1 learners never get unfair hang-ups from a desync between Tina's question and the active checkpoint.

## Background

**Direct successor of Story 6.9's smoke test (2026-05-20, call_id=137)** where Tina hung up on Walid despite his reasonable responses. Root cause confirmed in transcript + journalctl: at turn 3, Tina asked "Anything to drink?" (skipping the `clarify` step), but the `CheckpointManager` was still anchored on `clarify`. Walid's 6 subsequent on-topic answers ("cola", "yeah sure", etc.) were ALL judged against the `clarify` criterion and ALL marked `not_met` → patience drained from 100 to 0 → `reason=character_hung_up` after 6 false negatives.

**The fundamental architectural diagnosis** (per dialogue 2026-05-20):

The current `CheckpointManager` enforces a **state machine** (`self._index` advances 0→1→2→…), but LLMs (qwen-flash, Claude, GPT, etc.) are trained on **naturally-fluid conversation**. When a state-machine constraint contradicts the LLM's training (e.g., "you MUST ask question A before B"), the LLM **drifts** — it generates the most natural response (the drink question after a dish is ordered), not the script-prescribed one. The state machine then becomes desynchronized from the conversation, and the user pays the cost.

The fix is NOT to fight the LLM with harder prompt constraints (per-scenario hacks Walid explicitly rejects). The fix is to **realign the architecture with how LLMs reason**: track GOALS to achieve, let the LLM choose the order naturally, evaluate every user turn against ALL pending goals, and accept any of them being met as a success.

**Walid's exact ask (2026-05-20)**:
> "j'aime regarder une discussion fluide si jamais naturellement la discussion irait vers la boisson Peut être que ça serait bien de valider Le scénario boisson Et puis que naturellement le personnage revienne sur la demande initiale qui est la cuisson du plat"

This is **task-oriented dialogue with non-linear goal tracking** — the standard pattern in modern conversational AI systems (Voiceflow, OpenAI Assistants v2, Botpress conversational flows).

**Hard prerequisite chain:**
- ✅ Story 6.8 (latency + coherence + Waiter calibration) — review/done
- ✅ Story 6.9 (DTLN noise suppression) — review (test café pending Walid)
- ⏳ Story 6.10 (this story) — ready-for-dev

**Critical reading before starting:**
- `_bmad-output/implementation-artifacts/6-9-dtln-noise-suppression.md` — predecessor
- `server/pipeline/checkpoint_manager.py` — the file that gets a meaningful rewrite
- `server/pipeline/exchange_classifier.py` — extended with `classify_multi`
- `server/pipeline/prompts.py` — new `EXCHANGE_CLASSIFIER_MULTI_PROMPT`
- `server/pipeline/scenarios/the-waiter.yaml` — reference for the 6-checkpoint shape (unchanged on this story)
- `client/lib/features/call/views/widgets/checkpoint_stepper.dart` — adapted for non-sequential fills
- `client/lib/features/call/services/checkpoint_advanced_payload.dart` — extended payload shape
- Memory: `feedback_coherence_must_be_system_wide.md` (the COHERENCE_CHARTER pattern from Story 6.8 still applies and is now MORE important — the dynamic system_instruction needs the charter every turn)

**Up-front deviations to document in Implementation Notes:**

1. **(Deviation #1) Architecture shift, not a feature add.** This story REPLACES the linear `_index` with a dictionary of `{goal_id: "pending" | "met"}`. Existing tests (~25 in `test_checkpoint_manager.py`) must be rewritten — they all assert linear-advance semantics that no longer apply. The number of tests stays roughly the same but the assertions change.

2. **(Deviation #2) Classifier signature changes.** `ExchangeClassifier.classify` (single objective, returns bool|None) is extended/replaced by `classify_multi(user_text, last_character_line, pending_goals: list[dict]) -> dict[goal_id, bool]`. Single LLM call evaluates ALL pending goals at once via structured JSON output. Old single-objective `classify` may stay as a thin wrapper for backward compat, but the production path uses `classify_multi`.

3. **(Deviation #3) Existing scenario YAMLs do NOT change.** The `checkpoints` array stays as-is (id, hint_text, prompt_segment, success_criteria, ordering). The order now serves as a HINT to the LLM (which goal to pursue first naturally), not as a constraint. Scenarios authored for Story 6.6 (linear) work without modification under Story 6.10 (goals).

4. **(Deviation #4) `prompt_segment` per-checkpoint is no longer swapped in/out individually.** Instead, the `system_instruction` becomes a dynamic composition: `base_prompt + COHERENCE_CHARTER + REMAINING_GOALS_BLOCK + SUGGESTED_FOCUS_BLOCK`, where REMAINING_GOALS_BLOCK enumerates all pending goals with their `prompt_segment` text, and SUGGESTED_FOCUS_BLOCK soft-points to the first pending goal as "the natural next focus". This gives the LLM full context of what's left while preserving the author's intended natural order.

5. **(Deviation #5) Patience semantics change.** Today: `apply_exchange_outcome(success=False)` fires on EVERY `checkpoint_unmet` event = `-fail_penalty` per turn. Under goals: fail fires ONLY if NO pending goal was met by the user's turn (i.e., the turn was truly off-topic). A turn that meets a future goal (out-of-order) succeeds. Net effect: patience drains MUCH more slowly under the new architecture. Existing calibration numbers (Waiter 60-90%, Mugger 35-55%, etc.) will need re-tuning — survival rates will go UP. Documented in AC-Calibration block.

6. **(Deviation #6) Client envelope shape extends, doesn't break.** Existing clients receive `checkpoint_advanced { checkpoint_id, index, total, next_hint }` per goal flip. The new shape adds `goals_met_indices: list[int]` carrying the FULL set of met indices (idempotent — client can reconcile by rendering exactly those circles as filled). Old field `index` retained as "the index that JUST flipped" for compat. Client stepper widget switches from "fill up to lastCheckIndex" to "fill each index in goals_met_indices" (~30-50 LOC client change).

7. **(Deviation #7 — preserved from Story 6.6 Dev #7) Terminal-turn preemptive synchronous classify still applies, redefined for goals.** Terminal turn = "any user turn where success would complete all goals" OR "any turn where one more fail would zero the meter". On terminal turns, await the multi-classifier synchronously (1.0s timeout per Story 6.8 AC4) BEFORE forwarding the frame, so the exit line is the sole final utterance (no disjointed "Tina asks a question, then 2s silence, then exit line"). The lock + post-acquire re-check pattern from Story 6.6 P1 is preserved.

## Acceptance Criteria (BDD)

### AC1 — `CheckpointManager` tracks goals as a dict, not an index

Given today's `CheckpointManager.__init__` initializes `self._index = 0`
And `_classify_and_advance` mutates `self._index += 1` on every met checkpoint
When this story lands
Then `CheckpointManager.__init__` initializes `self._goals: dict[str, str] = {cp["id"]: "pending" for cp in checkpoints}`
And the manager exposes a read-only property `goals_state` returning a copy of the dict (for tests + observability)
And the manager exposes a read-only property `pending_goals` returning the list of pending checkpoint dicts (in original author order — preserves "suggested focus" semantics)
And the manager exposes a read-only property `met_count` for observability + envelope payload
And the `_index` attribute is REMOVED (or kept as a compat alias = `met_count` — dev's call)

### AC2 — `ExchangeClassifier` gets a `classify_multi` method

Given `ExchangeClassifier.classify` evaluates ONE objective per LLM call (single bool|None verdict)
When this story lands
Then a new method `ExchangeClassifier.classify_multi(...)` lands:

```python
async def classify_multi(
    self,
    *,
    user_text: str,
    last_character_line: str,
    pending_goals: list[dict],  # each: {"id": str, "success_criteria": str}
    scenario_description: str,
) -> dict[str, bool | None]:
    """Returns {goal_id: True | False | None} for each pending goal.
    None = classifier inconclusive (timeout/parse error) — caller treats as
    'no verdict, keep pending'."""
```

And the old `classify(...)` method is preserved as a thin compatibility wrapper (single-goal case) so existing tests + the legacy `/connect` PoC path don't break
And the multi-goal output uses structured JSON: `{"goals_met": ["goal_id_1", "goal_id_3"], "goals_unmet": ["goal_id_2"]}` (a goal omitted from both lists is "no verdict")
And the prompt structure preserves the COHERENCE_CHARTER intent-first principles (Story 6.8) — synonyms, fragments, hesitations, default-to-MET-when-uncertain still apply

### AC3 — New `EXCHANGE_CLASSIFIER_MULTI_PROMPT` constant

Given the existing `EXCHANGE_CLASSIFIER_PROMPT` (Story 6.8 intent-first) targets one objective per call
When this story lands
Then a new module-level constant `EXCHANGE_CLASSIFIER_MULTI_PROMPT` lands in `server/pipeline/prompts.py`
And it embeds the same 6 intent-first guiding principles from `EXCHANGE_CLASSIFIER_PROMPT` (prioritize INTENT, accept synonyms/colloquialisms, accept fragments, accept re-statements, default to MET, evaluate only listed objectives)
And it accepts a placeholder `{pending_goals_block}` that the classifier formats as a numbered list:
```
1. [goal_id="greet"] User states they want to order, asks for the menu, asks what's available, or mentions any food item.
2. [goal_id="main_course"] User names a specific dish from the menu...
3. [goal_id="clarify"] User specifies the variation, cooking preference...
```
And it requests strict JSON output: `{"goals_met": [...], "goals_unmet": [...]}` (omitted = no verdict)
And the prompt-injection resistance from Story 6.6 D3 (XML `<user_response>` / `<character_line>` tags) is preserved

### AC4 — Dynamic system_instruction composition

Given today's `_classify_and_advance` swaps `llm._settings.system_instruction = base_prompt + charter + next_checkpoint["prompt_segment"]`
When this story lands
Then `CheckpointManager._update_system_instruction()` is a new method that composes:
```
base_prompt
+ "\n\n" + COHERENCE_CHARTER
+ "\n\n" + REMAINING_GOALS_BLOCK
+ "\n\n" + SUGGESTED_FOCUS_BLOCK
```

Where:
- `REMAINING_GOALS_BLOCK` enumerates ALL pending goals with their `prompt_segment` text, prefixed with a header like "Your remaining objectives (achievable in any order):"
- `SUGGESTED_FOCUS_BLOCK` soft-points to `pending_goals[0]["prompt_segment"]` as "The natural next focus is: …. If the conversation flows toward another remaining objective, accept that and circle back to this one later naturally."

And `_update_system_instruction()` is called:
1. Once at construction (initial composition)
2. After every goal flip from pending → met (recompose with smaller pending set)

And the WARN-on-duplicate guard from Story 6.8 (charter appears more than once) is preserved
And when ZERO goals remain pending, the system_instruction composes to `base_prompt + charter + "All objectives complete. Wrap up the conversation naturally."` (the LLM-driven completion utterance)

### AC5 — `process_frame` evaluates multi-goals atomically per user turn

Given today's `process_frame` schedules ONE classifier task per user TranscriptionFrame (latest-line-wins via generation counter)
When this story lands
Then `process_frame` still schedules ONE async task per finalized user turn
But the task calls `classify_multi` (one LLM call, multi-goal verdicts)
And on verdict return:
1. For each goal_id where verdict is True → flip `self._goals[goal_id] = "met"`, emit `checkpoint_advanced` envelope for THAT goal (so client stepper can fill the matching circle in real-time)
2. `_update_system_instruction()` is recomposed
3. `patience_tracker.apply_exchange_outcome(success=any_goal_met)` is called
4. If all goals are now met → `patience_tracker.set_checkpoints_passed(len(self._checkpoints))` + `schedule_completion(survival_pct=100)`

And the generation-counter latest-line-wins pattern from Story 6.6 is preserved (stale task verdict dropped silently)
And the Deviation #7 terminal-turn preemptive synchronous classify is preserved — terminal = "completing the last pending goal would end the call" OR "one more fail zeroes the meter"

### AC6 — `checkpoint_advanced` envelope shape extends backward-compatibly

Given today's envelope is `{"type": "checkpoint_advanced", "data": {"checkpoint_id", "index", "total", "next_hint"}}`
When this story lands
Then the envelope is emitted ONCE per goal flip (not batched, so the stepper animates per-flip)
And the `data` block adds a new field `goals_met_indices: list[int]` — the FULL set of indices (in original author order) of all goals currently marked met
And the existing `index` field carries the index of THE goal that JUST flipped (so old clients that read `index` still render correctly for the most-recent flip)
And `next_hint` carries the hint_text of the suggested-focus pending goal (the first remaining one in author order), or empty string if all goals are met

### AC7 — Client `CheckpointStepper` renders non-sequential fills

Given today's stepper widget receives `index` and fills circles 0..index as filled
When this story lands
Then the stepper switches to reading `goals_met_indices` from the envelope payload
And it renders each index in that list as filled (regardless of order — circle 3 can be filled before circle 2)
And circles NOT in that list render as not-yet-met (empty/outlined)
And the existing single-`index` field is read for the "JUST flipped" animation (the most recently filled circle pulses or fades in)
And the existing AAC announcement ("checkpoint X of Y complete") fires per flip
And the client-side `CheckpointAdvancedPayload` model gains a `goalsMetIndices: List<int>` field (defaults to `[index]` if envelope is from a pre-6.10 server for backward compat during rolling deploys)

### AC8 — Patience semantics: fail only if NO goal matched this turn

Given today's `apply_exchange_outcome(success=False)` fires on every `checkpoint_unmet`
And this drains patience by `fail_penalty` (-15 default) per unmet
When this story lands
Then `apply_exchange_outcome(success=...)` is called ONCE per user turn (not per-goal)
And `success` is `True` if ANY goal flipped from pending → met this turn
And `success` is `False` only if NO goal flipped this turn (off-topic / nonsense / true miss)
And the patience meter drains by `fail_penalty` only on truly off-topic turns
And the recovery_bonus (+5 default) applies on any successful turn (even if only one of three pending goals was met)
And the calibration block in each scenario YAML grows a comment noting that pre-6.10 survival% baselines are INVALID under the new architecture (re-calibration required, target bands stay the same)

### AC9 — Pre-commit gates green

Given the dual-side discipline (CLAUDE.md root + server/CLAUDE.md + client/CLAUDE.md)
When this story lands
Then ALL pass before flipping `in-progress → review`:
- `ruff check .` → zero issues
- `ruff format --check .` → zero issues
- `pytest` → all green; expect significant test rewrite (~25 tests in `test_checkpoint_manager.py` adapt to new state model). Target: ≥350 passing (341 Story 6.9 baseline + ~10 net new — multi-classifier tests + 3-4 new behavioral tests for non-linear goal flips, partial credit, completion-via-out-of-order).
- `flutter analyze` → clean
- `flutter test` → all green; expect ~3-5 new tests for stepper non-sequential rendering + payload backward compat. Target: ≥376 passing (373 Story 6.8 baseline + ~3-5).

### AC10 — Smoke Test Gate validates the Tina-drift case is fixed

See `## Smoke Test Gate` section below — a 7-box gate replay of yesterday's call_id=137 hangup case, plus a recalibration sanity check on Waiter (full happy path completion under new architecture).

## Smoke Test Gate (Server / Deploy Story)

> **Scope rule:** Server-side architectural change affecting every dialogue turn. Mandatory gate on the device after VPS deploy.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ <!-- Active line + commit SHA -->

- [ ] **Replay call_id=137 drift case — must NOT hang up.** Dial Waiter on Pixel 9 Pro XL. Use the exact same script as 2026-05-20 13:43 (which hung up under Story 6.9): "I would like to order" → "What do you have?" → "fish and chips" → (Tina jumps to drink) → "Uh, what is, uh," → "cola" → "yeah sure" → "sorry, yes, I'm okay".
  - _Expected:_ call completes with `reason=survived`. No `checkpoint_unmet` on the user's on-topic-but-out-of-order replies. Goals `main_course`, `drink`, `confirm` flip to met across the conversation; `clarify` may flip via Tina circling back ("oh wait, grilled or fried?"), or may remain unmet at the end (acceptable — partial completion still counts as a real conversation, not a hangup).
  - _Proof:_ <!-- transcript + journalctl goals_met events + call_end reason -->

- [ ] **Happy-path Waiter completion test.** Standard script (chicken → grilled → cola → confirm → thanks).
  - _Expected:_ all 6 goals met, `reason=survived`, perceived latency ≤1500ms median (Story 6.8 target preserved despite the bigger system_instruction).
  - _Proof:_ <!-- transcript timing + journalctl goal flips -->

- [ ] **Off-topic turn correctly penalizes.** Standard script but inject one truly off-topic turn ("what's the weather today?"). Verify it triggers `apply_exchange_outcome(success=False)` and the patience meter ticks down by -15.
  - _Expected:_ patience_outcome log line shows the deduction; other on-topic turns do NOT deduct.
  - _Proof:_ <!-- journalctl patience_outcome stream -->

- [ ] **Non-sequential goal flip on the client.** During a call, deliver a sentence that meets 2 goals at once (e.g., "Grilled chicken with a cola, please" → both `clarify` (cooking style) AND `drink` flip in the same turn).
  - _Expected:_ client stepper renders both circles as filled in the same envelope cycle (no "1 then 2" sequential animation); journalctl emits 2 `checkpoint_advanced` envelopes within the same turn with the SAME `goals_met_indices` list.
  - _Proof:_ <!-- visual confirmation + journalctl pair -->

- [ ] **Latency under goal-architecture.** The system_instruction is now bigger (lists all pending goals instead of just current). Verify median perceived latency stays ≤1500ms (Story 6.8 AC5 target).
  - _Expected:_ median ≤1500ms, p95 ≤2000ms — same target as Story 6.8. If exceeded by >100ms, investigate (likely the system_instruction bloat → consider trimming `prompt_segment` lengths in YAML).
  - _Proof:_ <!-- transcript timing summary -->

- [ ] **Server logs clean.** `journalctl -u pipecat.service --since "10 min ago" | grep -iE "(error|traceback|exception|duplicate COHERENCE)"` returns zero matches.
  - _Proof:_ <!-- "no errors in window" + timestamp -->

## Tasks / Subtasks

### Phase 1 — Server: classifier + state model

- [ ] **Task 1 — Multi-goal classifier prompt** (AC: #3)
  - [ ] 1.1 — Draft `EXCHANGE_CLASSIFIER_MULTI_PROMPT` in `prompts.py` with the 6 intent-first principles + numbered pending-goals list + strict JSON output schema
  - [ ] 1.2 — Define helper `_format_pending_goals_block(goals: list[dict]) -> str` that renders the goal list (id, criteria)
  - [ ] 1.3 — Sanity-check the prompt size: enumerating 6 goals × ~50 tokens criteria = ~300 tokens. Add to the ~200 tokens charter + ~600 tokens base = ~1100 tokens system. Comfortable for qwen-flash's 32K context.

- [ ] **Task 2 — `ExchangeClassifier.classify_multi`** (AC: #2)
  - [ ] 2.1 — Add `classify_multi` method, keep `classify` as legacy wrapper
  - [ ] 2.2 — Use the same httpx + 1.0s timeout + 0.8s HTTP budget pattern from Story 6.8
  - [ ] 2.3 — JSON parsing with fence-stripping fallback (mirrors existing `_parse_classifier_output`)
  - [ ] 2.4 — Return `dict[goal_id, bool | None]` — missing goals = None (no verdict, keep pending)

- [ ] **Task 3 — `CheckpointManager` state model rewrite** (AC: #1, #5)
  - [ ] 3.1 — Replace `self._index = 0` with `self._goals: dict[str, str]`
  - [ ] 3.2 — Add `goals_state`, `pending_goals`, `met_count` read-only properties
  - [ ] 3.3 — Adapt `_classify_and_advance` → `_classify_and_flip_goals` using `classify_multi`
  - [ ] 3.4 — Per-goal-flip emission of `checkpoint_advanced` envelope (one per flip, with updated `goals_met_indices`)
  - [ ] 3.5 — Patience semantics: one `apply_exchange_outcome(success=any_flip)` per turn (not per-goal)
  - [ ] 3.6 — Completion condition: `all(state == "met" for state in self._goals.values())` → `schedule_completion(survival_pct=100)`
  - [ ] 3.7 — Generation-counter latest-line-wins preserved
  - [ ] 3.8 — Deviation #7 terminal-turn preemptive synchronous classify preserved (redefined for goals — "would completing this turn end the call?")
  - [ ] 3.9 — Delete `_index` (or alias to `met_count` for back-compat — dev call)

- [ ] **Task 4 — Dynamic `system_instruction` composition** (AC: #4)
  - [ ] 4.1 — Add `_update_system_instruction()` method that composes `base + charter + REMAINING_GOALS_BLOCK + SUGGESTED_FOCUS_BLOCK`
  - [ ] 4.2 — Call it at `__init__` (initial composition) and after every successful flip
  - [ ] 4.3 — Preserve the WARN-on-duplicate-charter guard from Story 6.8
  - [ ] 4.4 — Update `bot.py` initial composition similarly (use the same helper or duplicate the formula)

### Phase 2 — Server: envelope + bot.py

- [ ] **Task 5 — Extend `checkpoint_advanced` envelope** (AC: #6)
  - [ ] 5.1 — Add `goals_met_indices: list[int]` to the envelope's `data` block
  - [ ] 5.2 — Keep existing `checkpoint_id`, `index`, `total`, `next_hint` for backward compat with old clients
  - [ ] 5.3 — `next_hint` now reads from `pending_goals[0]` (suggested focus), or empty if all met
  - [ ] 5.4 — Adapt `build_initial_envelope()` (Story 6.7) to carry `goals_met_indices: []` at call start

- [ ] **Task 6 — Adapt `bot.py` for goals** (AC: #1, #4)
  - [ ] 6.1 — Update the initial `system_instruction` composition in `bot.py` to use the new full-goals format (or call into the CheckpointManager helper)
  - [ ] 6.2 — Verify no other bot.py code expects `_index` (unlikely — should be all encapsulated in the manager)

### Phase 3 — Server: tests

- [ ] **Task 7 — Rewrite `test_checkpoint_manager.py`** (~25 tests)
  - [ ] 7.1 — Rewrite `_make_manager` helper for the new state model
  - [ ] 7.2 — Adapt existing tests (advance-on-met, no-advance-on-not-met, conservative-None-fallback, last-checkpoint-completion, stale-verdict-guard, cleanup, empty-checkpoints, init-log, llm-settings-missing) to assert goal-state changes instead of `_index` changes
  - [ ] 7.3 — Adapt Deviation #7 preemptive tests (suppress-on-meter-zero, suppress-on-completion, fall-through-on-recovery) to new "would completing this turn end the call" terminal definition
  - [ ] 7.4 — Adapt charter tests (appears-in-every-swap, warn-on-duplicate) to the new dynamic composition

- [ ] **Task 8 — New behavioral tests for goal-based architecture** (~10 new)
  - [ ] 8.1 — `test_two_goals_flip_in_same_turn` — user says "grilled chicken with cola" → both `clarify` + `drink` flip in one turn (asserts envelope emits 2 events with same `goals_met_indices`)
  - [ ] 8.2 — `test_out_of_order_goal_completion` — user fills goal index 3 before index 2, both legit, eventually all 6 met → `reason=survived`
  - [ ] 8.3 — `test_off_topic_turn_only_fails_when_no_goal_matched` — fully off-topic turn ("what's the weather") → `apply_exchange_outcome(success=False)`, no goal flips
  - [ ] 8.4 — `test_partial_credit_does_not_fail` — turn that meets 1 of 3 pending goals → `apply_exchange_outcome(success=True)`, no patience deduction
  - [ ] 8.5 — `test_system_instruction_recomposes_after_goal_flip` — drive 2 successful turns, assert system_instruction was rewritten 2× and each recomposition contains the updated REMAINING_GOALS_BLOCK
  - [ ] 8.6 — `test_completion_fires_when_all_goals_met_via_out_of_order_path` — fill goals in order [0, 2, 1, 4, 3, 5] → all met → completion
  - [ ] 8.7 — `test_classify_multi_returns_per_goal_verdict` — direct test of `ExchangeClassifier.classify_multi` with a mock LLM response
  - [ ] 8.8 — `test_envelope_carries_goals_met_indices` — verify the envelope payload extension
  - [ ] 8.9 — `test_legacy_classify_still_works` — backward-compat for the single-objective `classify` wrapper
  - [ ] 8.10 — `test_suggested_focus_is_first_pending_in_author_order` — even after out-of-order flips, the suggested focus stays anchored to author order

- [ ] **Task 9 — Wiring + integration tests**
  - [ ] 9.1 — Add `test_classify_multi_threaded_through_pipeline_drive` to `test_bot_pipeline_wiring.py` (Déviation-#28 pattern — drive a real Pipecat pipeline with a real TranscriptionFrame to ensure the new multi-goal classifier path runs end-to-end)

### Phase 4 — Client: stepper non-sequential rendering

- [ ] **Task 10 — Adapt `CheckpointAdvancedPayload`** (AC: #7)
  - [ ] 10.1 — Add `goalsMetIndices: List<int>` to the payload model in `checkpoint_advanced_payload.dart`
  - [ ] 10.2 — Backward-compat parser: if envelope lacks the field, default to `[index]` (single-most-recent-flip)

- [ ] **Task 11 — Adapt `CheckpointStepper` widget** (AC: #7)
  - [ ] 11.1 — Switch from `lastCheckIndex` linear fill to per-index lookup against `goalsMetIndices`
  - [ ] 11.2 — Preserve "just-flipped" animation on the most-recent `index` (so the user sees which circle just lit up)
  - [ ] 11.3 — TalkBack/AAC announcement still fires per envelope ("checkpoint X of Y complete")

- [ ] **Task 12 — Client tests** (~3-5 new)
  - [ ] 12.1 — Stepper renders circles 0 and 3 filled when payload has `goalsMetIndices: [0, 3]` (non-sequential)
  - [ ] 12.2 — Backward-compat: payload without `goalsMetIndices` falls back to filling `[index]`
  - [ ] 12.3 — Animation still triggers on the `index` field (just-flipped)

### Phase 5 — Pre-commit + Smoke Gate

- [ ] **Task 13 — Pre-commit gates** (AC: #9)
  - [ ] 13.1 — `ruff check . && ruff format --check .` → green
  - [ ] 13.2 — `pytest` → ≥350 passed
  - [ ] 13.3 — `flutter analyze && flutter test` → ≥376 passed

- [ ] **Task 14 — VPS deploy + Smoke Test Gate** (AC: #10)
  - [ ] 14.1 — **WALID** — `git push` → CI/CD deploy
  - [ ] 14.2 — **WALID** — 7-box Smoke Test Gate above on Pixel 9 Pro XL
  - [ ] 14.3 — **WALID** — paste proofs into each gate box
  - [ ] 14.4 — Sprint-status + story Status flipped `in-progress → review` after pre-commit; `review → done` after smoke gate per Story 6.5 D6

## Dev Notes

**The architectural shift in one sentence:** stop telling the LLM "follow this exact sequence" and start telling it "achieve these objectives in any natural order".

**Why this works:** LLMs are pre-trained on naturally-fluid conversations. A state machine that enforces strict ordering contradicts that training, leading to drift (Tina jumping ahead). A goal-tracking system that lets the LLM choose the natural order aligns with the model's strengths — the LLM does what it does well (fluid conversation toward goals), and the system does what it does well (track which goals are achieved).

**Why this is more robust than per-scenario fixes:** every future scenario inherits the goal-based fluidity for free. No more "tweaking the YAML to make Tina ask the right questions in the right order". The author defines what counts as meeting each goal; the LLM figures out the natural conversation path.

**Why patience semantics change is critical:** today, every `checkpoint_unmet` deducts -15. A 6-step scenario where the LLM drifts costs the user 6 × -15 = -90 patience even on totally reasonable user replies (the call_id=137 case). Under goals, a turn that meets ANY pending objective is a success (no deduction); only true off-topic turns deduct. This makes the survival rate a genuine measure of user performance, not a measure of LLM-system desync.

**Calibration impact (this story doesn't recalibrate — that's a separate post-story task):**
- Waiter (target 60-90%): expect 90-95% survival under goals (most B1 attempts succeed naturally)
- Mugger (target 35-55%): expect 50-70% — more permissive, may need `fail_penalty` bump to -20 or -25 to hit target
- Cop/Landlord (target 15-35%): expect 30-50% — same as above
- A Story 6.11 (or 6.10b) will be needed to re-tune `fail_penalty` per scenario to hit the difficulty bands again. Acceptable trade-off because the new survival rate is a TRUER measure (not contaminated by desync penalties).

**Why the existing scenario YAMLs work without modification:**
- The `checkpoints` array structure (id, hint_text, prompt_segment, success_criteria) stays the same
- The order in the array becomes a HINT (suggested focus) rather than a strict requirement
- Authors can keep authoring scenarios linearly; the engine handles natural fluidity at runtime
- Zero migration effort for existing scenarios

**Backward-compat for the client during rolling deploy:**
- Old clients (Story 6.9 and earlier) read `index` from the envelope and fill 0..index → still works for the most-recent flip (the just-flipped one)
- New clients (Story 6.10) read `goals_met_indices` and fill the exact set → correct for non-sequential cases
- A client that mixes the two (old reads `index`, new reads `goals_met_indices`) renders consistently because `goals_met_indices` is a superset of what `index` represents

**Why one big classifier call instead of N parallel calls?**
- Cost: 1 call ≈ 1 × cost vs N × cost (qwen-flash is cheap but still 5-6× cost for 6 goals)
- Latency: 1 call's TTFT vs max-of-N latencies (1 call is faster)
- Atomicity: a single LLM judgement of "which of these did the user meet" is more coherent than N independent judgements that might contradict each other (e.g., goal A "yes" but goal B "no" when they're actually mutually exclusive)
- Token reuse: the system + user_text are shared across N goals, the prompt is largely fixed → 1 call saves significant duplicated prompt tokens

### Project Structure Notes

**Server — modified:**
- `server/pipeline/checkpoint_manager.py` — major rewrite: state model, classification path, system_instruction composition, envelope emission
- `server/pipeline/exchange_classifier.py` — new `classify_multi` method, `classify` becomes legacy wrapper
- `server/pipeline/prompts.py` — new `EXCHANGE_CLASSIFIER_MULTI_PROMPT` constant
- `server/pipeline/bot.py` — initial `system_instruction` composition uses new full-goals format
- `server/tests/test_checkpoint_manager.py` — ~25 tests rewritten + ~10 new
- `server/tests/test_exchange_classifier.py` — new tests for `classify_multi`
- `server/tests/test_prompts.py` — assert new constant present
- `server/tests/test_bot_pipeline_wiring.py` — wiring test for the new classification path

**Server — NO changes:**
- `server/pipeline/scenarios/*.yaml` — all 5 scenarios unchanged
- `server/pipeline/scenarios.py` — loader unchanged
- `server/pipeline/patience_tracker.py` — semantics SAME (still receives `apply_exchange_outcome(success: bool)`, the caller just calls it differently)
- `server/pipeline/dtln_audio_filter.py` — unchanged
- `server/db/migrations/` — no schema change
- `server/api/routes_calls.py` — no API change

**Client — modified:**
- `client/lib/features/call/services/checkpoint_advanced_payload.dart` — new `goalsMetIndices: List<int>` field
- `client/lib/features/call/views/widgets/checkpoint_stepper.dart` — per-index rendering instead of linear fill
- `client/test/features/call/views/widgets/checkpoint_stepper_test.dart` — new tests

**Client — NO changes:**
- `call_bloc.dart`, `data_channel_handler.dart` — unchanged
- Rive assets, design system, error UX — unchanged

**Implementation artifacts — modified:**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — new entry `6-10-goal-based-dialogue: ready-for-dev`
- `_bmad-output/implementation-artifacts/6-10-goal-based-dialogue.md` — this file

### References

- `_bmad-output/implementation-artifacts/6-9-dtln-noise-suppression.md` — predecessor; the 6.9 smoke test surfaced the drift case
- `server/pipeline/checkpoint_manager.py` — current linear-index implementation
- `server/pipeline/prompts.py` — Story 6.8 `EXCHANGE_CLASSIFIER_PROMPT` (intent-first; the new multi-goal prompt extends it)
- `memory/feedback_coherence_must_be_system_wide.md` — Walid's "système-wide" doctrine; this story is the second concrete realization (after the COHERENCE_CHARTER) of that doctrine applied to dialogue flow
- Voiceflow / OpenAI Assistants v2 / Botpress — industry reference architectures for task-oriented dialogue with non-linear goal tracking

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context)

### Debug Log References

(filled at dev time)

### Completion Notes List

(filled at dev time)

### File List

(filled at dev time)

## Change Log

- 2026-05-20 — Spec drafted post-Story 6.9 smoke test analysis. Architecture shift from linear state machine to goal-tracking. 7 up-front deviations documented. Awaiting Walid sign-off before implementation begins.
