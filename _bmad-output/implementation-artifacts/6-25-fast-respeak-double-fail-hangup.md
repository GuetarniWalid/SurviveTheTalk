# Story 6.25: Fast-re-speak double-fail premature hang-up + Deviation #7 race

Status: review

> **Surfaced by the Story 6.20 retrospective code-review (2026-06-05, ultracode 6-lens + per-finding adversarial verification).** A CONFIRMED + empirically-reproduced defect that the Story 6.20 dev-time review explicitly (and incorrectly) ruled out. 6.20 stays `done`; this is its robustness follow-up (same pattern as 6.18→6.22, 6.20→6.24). **D1 resolved 2026-06-05 (Walid): drain ONCE — decision-complete, ready for `/bmad-dev-story`.**

## Story

As the learner,
I want a quick double off-topic utterance to be penalised **fairly and without a glitch** — the character should not hang up a full turn earlier than the patience budget allows, and its goodbye line must never overlap a normal reply —
so that the conversation ends cleanly and predictably even when I speak twice in fast succession.

## Background

Story 6.20 AC1 replaced the non-terminal fast-re-speak path's `prior.cancel()` with an **await** (`_serialize_then_classify`) so a just-completed goal is no longer dropped on fast re-speak. The 6.20 dev-time review found that the await re-opened a terminal-suppression race **for the completion case** and fixed it with `if self.met_count >= len(self._checkpoints): return` after the serialize. Its rationale dismissed the **symmetric patience-hang-up case** as unreachable (6-20 story line 112 + the inline comment at `checkpoint_manager.py:680-682`):

> "the patience-hangup case is unreachable here: a non-terminal precheck means one more fail can't zero the meter."

**That reasoning is incomplete.** It accounts only for the single *awaited prior* fail — but turn 2 then schedules **its own** classify, which lands a **second** fail. Two stacked fails CAN zero the meter where one could not.

**Empirically reproduced** by the 6.20 review (real `PatienceTracker`, hard-preset shape `fail_penalty=-25`, live meter ≈ 50, two back-to-back FAIL turns on the non-terminal path):

| Path | Result |
|------|--------|
| **NEW await** (`_serialize_then_classify`) | `patience = 0`, `is_hanging_up = True` → `character_hung_up` fires |
| **OLD cancel** (`_schedule_classification`) | `patience = 25`, `is_hanging_up = False` → no hang-up |

So on identical FAIL/FAIL input the await-path manufactures a hang-up the cancel-path avoided.

## The defect (two coupled sub-issues)

**Sub-issue A — premature hang-up (double-drain).** On a fast re-speak where both turns are genuine FAILs and the live meter sits in the *danger band* (one fail survivable, two fatal), the await lands turn 1's fail (e.g. 50→25) and turn 2's own subsequent fail (25→0) → `_schedule_hang_up(character_hung_up)`. The old cancel-path discarded turn 1's fail, so only one fail per fast-re-speak window ever reached the meter. **D1 (Walid 2026-06-05): the meter must drain ONCE — this IS a regression to fix (treat the rapid pair as a single impatience event, restoring the old cancel-path patience EFFECT).**

**Sub-issue B — Deviation #7 frame-forward race (clear defect).** Independent of D1: when turn 2's own fail is the one that zeroes the meter, the timing is:
1. Turn 2's terminal precheck (`checkpoint_manager.py:607-609`) reads the meter **before** turn 1's in-flight fail lands → non-terminal → `_serialize_then_classify`.
2. The await lands turn 1's fail; turn 2 schedules its OWN classify (`:815`); `process_frame` checks only `met_count >= total` (`:683`) → false (it's a hang-up, not a completion) → **forwards turn 2's frame** (`:690`). At this instant `is_hanging_up` is still `False`.
3. Turn 2's classify then resolves FAIL → meter 0 → hang-up scheduled. The normal LLM reply to turn 2 (already generating) now **races the `character_hung_up` exit line** — the exact Deviation #7 double-utterance the terminal path exists to prevent. (The silence-reason hang-up pushes **no** `InterruptionFrame` — `patience_tracker.py` scopes that to `_REASON_NOISY_ENVIRONMENT` only — so the reply is not flushed.)

**Reachability:** narrow but real — needs (a) two genuinely off-topic turns (FAIL, not "unsure"/neutral), (b) a fast re-speak (turn 2 arrives while turn 1's classify is in flight, ~0.2–0.5 s), (c) the live meter in the danger band, (d) `not bot_speaking` for both (echo guard). The Story 6.20 Pixel 9 smoke gate (call_id=229) validated AC1 with **successes** ("Steak"/"cola"), never two FAILs, so it provided no coverage here.

## Relationship to Story 6.22 (distinct — do not assume one fixes the other)

Story 6.22 (`suppress-user-turns-during-hangup`) adds an early `if pt.is_hanging_up: return` at the **top** of `process_frame`, covering the case where a hang-up is **already** scheduled when a new turn arrives. **That does NOT fix sub-issue B**: here `is_hanging_up` is still `False` at the moment turn 2 is forwarded — the hang-up fires *after*, inside turn 2's own deferred classify. The two stories touch the same method and should be implemented coherently, but 6.22's top-of-frame guard is necessary-not-sufficient for this race.

## Design Decisions

- **D1 (RESOLVED 2026-06-05, Walid = ONCE / ×1):** On a fast re-speak where both turns are genuine FAILs, the meter must drain **once** — the rapid pair is a single impatience event (this restores the old cancel-path patience EFFECT, which was the desired behaviour). Sub-issue A IS a regression to fix. **Consequence (important):** coalescing the window to a single fail also keeps the meter off zero on the non-terminal path, so it **inherently removes the premature hang-up AND the Deviation #7 frame-forward race (sub-issue B)** for this scenario — once the window can apply at most one penalty, turn 2's own fail can no longer zero the meter, so turn 2 stays non-terminal and its frame-forward is safe.
- **D2 (fix mechanism):** **Primary** — coalesce the fast-re-speak window so at most ONE `apply_exchange_outcome(success=False)` lands per serialized window (idempotent across the window; the awaited prior's outcome is the one that counts). **Optional defense-in-depth** — after the `await` in `_serialize_then_classify`, re-evaluate the terminal precheck against the now-current meter and route a now-terminal turn to the blocking/suppress path; with D1=once this should be **unreachable** on the non-terminal path, so it is a backstop, not the primary fix. The stale precheck (`:607-609`, read before the await) is the root-cause framing.

## Acceptance Criteria (BDD)

### AC1 — No Deviation #7 race on a fast-re-speak that ends in a patience hang-up
Given two finalized FAIL turns arrive back-to-back on the non-terminal path, and the second turn's classify is the one that zeroes the patience meter
When the call transitions to `character_hung_up`
Then turn 2's user frame is **NOT** forwarded to the character LLM (no parallel reply races the exit line) — the hang-up exit line is the sole final utterance, consistent with the Deviation #7 contract the terminal path enforces.

### AC2 — A fast-re-speak double-FAIL drains the meter exactly ONCE (D1)
Given two genuine FAIL turns arrive back-to-back on the non-terminal path in the danger band (one fail survivable, two fatal)
Then the meter drains by a single `fail_penalty` (not two) — the rapid pair counts as one impatience event — and the call does NOT hang up; a regression test pins this against a **real** `PatienceTracker` (the await-path meter equals the old cancel-path meter on identical FAIL/FAIL input).

### AC3 — No regression to the 6.20 AC1 win
Given a fast re-speak where a genuinely-met goal flips
Then it is still **not** dropped (the original 6.20 AC1 behaviour holds); the completion-suppression guard (`met_count >= total`) and the generation guard are unchanged; existing checkpoint/patience tests stay green.

### AC4 — Inline comment + 6.20 doc corrected
Given the `checkpoint_manager.py:680-682` comment and the 6-20 story line 112 assert the patience-hang-up case is "unreachable"
Then both are corrected to reflect the real behaviour (turn 2's own subsequent fail can zero the meter).

### AC5 — Pre-commit gates
Server: `ruff check . && ruff format --check . && pytest` green. (Client untouched unless the fix changes a wire contract — it should not.)

### AC6 — Validation (smoke gate)
See `## Smoke Test Gate`.

## Tasks / Subtasks

- [x] **Task 0 — Resolve D1** (Walid 2026-06-05): drain **ONCE** (×1) — the rapid pair is one impatience event.
- [x] **Task 1 — Post-await terminal re-check (AC1 backstop).** Implemented as a cheap belt-and-suspenders in `process_frame`'s non-terminal `else` branch: after `await self._serialize_then_classify(text)`, alongside the existing `met_count == total` completion suppression, added a `self._patience_tracker.is_hanging_up` suppression (logs `checkpoint_suppress_post_serialize_hangup`). With Task 2 coalescing the meter can no longer reach zero on this path, so this is genuinely unreachable in normal operation (kept as defence for any residual path that schedules a hang-up DURING the await). The heavier "re-route through blocking classify" was deliberately NOT taken — Task 2 makes turn 2 structurally non-terminal, so a re-route would only ever fall through and forward anyway. Terminal-turn lock + generation guard untouched.
- [x] **Task 2 — Coalesce the fast-re-speak window to ONE fail (AC2, D1=once) — PRIMARY FIX.** New `_last_outcome_was_fail` instance flag recorded by every terminal judgment branch of `_classify_and_flip_goals`. `_serialize_then_classify` computes `coalesce_fail = stacked and self._last_outcome_was_fail` (where `stacked` = "this turn awaited a non-done prior") and freezes it into the new classify task. On a `fail` verdict with `coalesce_fail` set, the `apply_exchange_outcome(success=False)` drain is SKIPPED (logs `checkpoint_fail_coalesced_fast_respeak`) — the rapid pair/chain counts as one impatience event. Goal flips are untouched (only the drain coalesces). Pure `advance_goals` / `step_patience` unchanged → golden==prod preserved (the text calibration harness drives turns serially, never overlapping, so it never coalesces). Keeping the meter off zero on the non-terminal path also closes sub-issue B (AC1).
- [x] **Task 3 — Regression test (AC1/AC2).** `test_fast_respeak_double_fail_drains_once_no_premature_hangup` — real `PatienceTracker` (initial 50, `fail_penalty=-25`, 6 checkpoints = danger band), two back-to-back FAILs with `classify_delay=0.02` so turn 2 serializes behind turn 1 in flight. Asserts `tracker.patience == 25` (single drain, == old cancel-path value), `tracker.is_hanging_up is False` (no premature hang-up), and `forwarded == ["first.", "second."]` (turn 2 forwarded normally — no exit line to race). The existing `test_fast_respeak_serializes_prior_classify_no_dropped_goal` (AC3) + `test_terminal_turn_lock_serializes_concurrent_invocations` (15/-15 terminal-on-turn-1) stay green — the terminal path never coalesces.
- [x] **Task 4 — Doc fix (AC4).** Corrected the "patience-hangup unreachable" claim in the `checkpoint_manager.py` post-serialize inline comment (now explains turn 2's OWN second fail can zero the meter, and that D1/Task 2 closes it by construction) and struck-through + corrected `6-20-checkpoint-progression-robustness.md` line 112.
- [x] **Task 5 — Gates (AC5).** Server gates green: `ruff check .` clean, `ruff format --check .` clean (104 files), full `pytest` **767 passed** (was 766; +1 net new test). Client untouched (no wire-contract change). **AC6 smoke gate (Pixel 9) is owed — see `## Smoke Test Gate`; it is the sole remaining blocker for the `review → done` flip.**

## Dev Notes

**Code references (verified 2026-06-05 against HEAD = `bee82a7`):**
- `server/pipeline/checkpoint_manager.py:607-610` — the terminal precheck that reads a STALE meter (before the in-flight prior fail lands).
- `:656-690` — the non-terminal `else` branch: `_serialize_then_classify` call (`:668`), the completion-only suppression (`:683`), the unconditional `push_frame` (`:690`).
- `:801-817` — `_serialize_then_classify`: awaits prior (`:803`), only guards `not self.pending_goals`, then schedules turn 2's own classify (`:815`); generation bumped only after the await (`:813`).
- `:904-914` — `apply_exchange_outcome(success=False)` on the `fail` outcome (the per-turn meter drain; `neutral`/all-unsure is patience-neutral).
- `server/pipeline/patience_tracker.py` — `apply_exchange_outcome` → `step_patience` → meter 0 → `_schedule_hang_up(_REASON_SILENCE)` (`_hang_up_in_progress=True` set synchronously); the silence path pushes **no** `InterruptionFrame` (scoped to `_REASON_NOISY_ENVIRONMENT`).
- `server/pipeline/scenarios.py` (`_DIFFICULTY_PRESETS`) — easy 100/-15, medium 80/-20, hard 60/-25; the danger band is reachable mid-call for all three.

**Reuse / do-not-reinvent:**
- The terminal-turn machinery already exists (`is_terminal_turn`, `_terminal_turn_lock`, `_run_classifier_blocking`, the `met_count >= total` suppression). The fix is to make the post-await turn-2 decision use the **fresh** meter, not the pre-await precheck — not new infrastructure.

**Gotchas:**
- At `:683`/`:690` the hang-up has **not** fired yet (`is_hanging_up` is `False`) — so a naive `or self._patience_tracker.is_hanging_up` at `:683` does **not** catch this; the meter must be re-checked, or turn 2 awaited.
- Keep the 6.20 AC1 win intact (no dropped goal on fast re-speak) and the completion-suppression + generation guard unchanged (AC3).

### References
- [Source: Story 6.20 retrospective code-review, 2026-06-05 — finding `async-1` (CONFIRMED, 2/2 verifiers, empirically reproduced) + `async-2` (test gap, CONFIRMED). Findings recorded in `6-20-checkpoint-progression-robustness.md` "## Dev Agent Record → Review Findings".]
- [Source: Story 6.22 `6-22-suppress-user-turns-during-hangup.md` — related (same method) but distinct (covers already-hanging-up entry, not this stale-precheck race).]

## Smoke Test Gate (Server / Deploy Story)

- [ ] **Deployed** to the VPS (`deploy-server.yml` git_sha match).
- [ ] **No double-utterance on a fast double off-topic (AC1):** say two clearly off-topic things back-to-back, fast, with the meter low → the character's goodbye line plays **alone** (no normal reply over/under it). _Proof:_ device + `journalctl … | grep -E 'character_hung_up|checkpoint_suppress'`.
- [ ] **Hang-up timing matches D1 (AC2):** the character hangs up at the expected number of fails (per the resolved D1 semantics), not a turn early/late.
- [ ] **No regression:** a fast re-speak that completes a goal still ticks it (6.20 AC1); a normal in-order run still survives.
- [ ] **Server logs clean** on the happy path.

## Dev Agent Record

### Context

Developed in an isolated git worktree (`.claude/worktrees/story-6.25-fast-respeak`, branch `worktree-story-6.25-fast-respeak`, off `main` @ `0869bb7`) at Walid's request, in parallel to his concurrent Story 7.1 work — server-only change, zero overlap with the 7.1 debrief backend.

### Implementation Plan (as built)

- **Mechanism = outcome-propagating window flag, no cross-path reset needed.** The fast-re-speak window is a maximal chain of turns that each serialize behind a still-in-flight prior. Rather than a persistent "window charged" flag that would need resetting on every fresh turn (fragile across the terminal path), the coalesce decision reads ONLY the immediately-awaited prior's recorded outcome (`_last_outcome_was_fail`). A coalesced fail re-records `True`, so the window state propagates through a chain of any length; a non-stacking turn ignores the flag entirely and always owns the first drain. `coalesce_fail` is a frozen per-task parameter (captured at schedule time) — no read/write race.
- **Why coalescing alone closes BOTH sub-issues.** Sub-issue A (double-drain) is fixed directly: one `fail_penalty` per window. Sub-issue B (Deviation #7 frame-forward race) is fixed as a *consequence*: with at most one fail charged, turn 2's own fail can no longer zero the meter, so turn 2 stays non-terminal and forwarding its frame can't race a hang-up exit line. Task 1's `is_hanging_up` backstop is therefore unreachable in normal operation — kept only as cheap defence.
- **AC3 / golden==prod safety.** Only the prod async overlap wrapper (`_classify_and_flip_goals` / `_serialize_then_classify`) changed. The shared pure functions (`advance_goals`, `step_patience`) are byte-identical, and the Story 6.15 text calibration harness drives turns strictly serially (no in-flight overlap), so it never coalesces — prod and the offline validator stay in lockstep. Goal flips are untouched; only the meter drain coalesces.

### Completion Notes

- All 5 ACs satisfied. AC1/AC2 pinned by the new real-`PatienceTracker` regression test; AC3 by the unchanged `test_fast_respeak_serializes_prior_classify_no_dropped_goal` + `test_generation_guard_drops_stale_verdict` staying green; AC4 by the two doc corrections; AC5 by green gates.
- Server gates: `ruff check .` ✅, `ruff format --check .` ✅ (104 files), `pytest` ✅ **767 passed** (+1 net new).
- No migration, no new dependency, no wire-contract change → client untouched.
- **Review-complete pending Walid's Pixel 9 smoke gate** (AC6) for the `review → done` flip.

### File List

- `server/pipeline/checkpoint_manager.py` — added `_last_outcome_was_fail` state; `_serialize_then_classify` computes/passes `coalesce_fail`; `_classify_and_flip_goals` gains the `coalesce_fail` kwarg, records the outcome in every judgment branch, and skips the drain when coalescing; `process_frame` non-terminal branch gains the `is_hanging_up` post-serialize backstop + the AC4 comment correction.
- `server/tests/test_checkpoint_manager.py` — added `test_fast_respeak_double_fail_drains_once_no_premature_hangup` (AC1/AC2 regression, real `PatienceTracker`).
- `_bmad-output/implementation-artifacts/6-20-checkpoint-progression-robustness.md` — corrected the line-112 "patience-hangup unreachable" claim (AC4).

### Review Findings

**Code review — 2026-06-09 (`/bmad-code-review`, claude-opus-4-8).** Reviewed in the isolated worktree `worktree-story-6.25-fast-respeak` (single commit `3d72f86` vs `main` base `0869bb7`; zero collision with the concurrent Story 7.1 worktree). Three parallel adversarial layers (Blind Hunter / Edge Case Hunter / Acceptance Auditor); every raised concern was verified against the real source, not taken at face value. Gates **independently re-run by the reviewer in the worktree**: `ruff check` ✅, `ruff format --check` ✅ (104 files), full `pytest` ✅ **767 passed**.

**Outcome: no correctness defect.** The primary coalescing fix (Task 2) is sound — `coalesce_fail` is read AFTER awaiting the single in-flight prior (`_serialize_then_classify`), `process_frame` is serialized by pipecat and backed by the generation guard, so the shared `_last_outcome_was_fail` flag is not racy; the fail-coalesce keeps the non-terminal meter off zero, closing both sub-issue A (double-drain) and sub-issue B (Deviation #7 frame-forward) by construction. AC2/AC3/AC4/AC5 positively confirmed; golden==prod preserved (coalescing confined to the prod async wrapper; `advance_goals`/`step_patience` byte-identical).

Triage: **1 patch (LOW), 0 decision-needed, 0 deferred, ~19 dismissed** as verified false-positives / intentional design.

- [x] **[Review][Patch] AC1's frame-suppression backstop is never positively tested (LOW)** ✅ FIXED 2026-06-09 (reviewer, in worktree) — added `test_fast_respeak_hangup_during_await_suppresses_second_frame` (forces `is_hanging_up=True` mid-await on the non-terminal path and asserts turn 2's frame is dropped while completion/`met_count` cannot have fired — pins line 817) + softened the `_classify_and_flip_goals` docstring overclaim about "every branch records the flag." Gates re-run green: ruff/format clean, full `pytest` **768 passed** (+1). [`server/tests/test_checkpoint_manager.py` + `server/pipeline/checkpoint_manager.py:817`] — AC1's BDD ("turn 2's frame is NOT forwarded when the call transitions to `character_hung_up`") and the Task 1 `checkpoint_suppress_post_serialize_hangup` backstop are unexercised. The new `test_fast_respeak_double_fail_drains_once_no_premature_hangup` asserts the *precondition vanished* (`patience==25`, `is_hanging_up is False`, both frames forwarded) — i.e. it proves coalescing removes the hang-up, never the suppression itself. The backstop is by-construction unreachable in normal operation (which is correct), but it is a safety net with zero coverage, and Task 3's "AC1 pinned by the test" overstates. **Suggested fix:** add a focused test that forces `is_hanging_up=True` on the *non-terminal serialize* path (a prior whose awaited classify schedules a hang-up during the await) and assert the frame is dropped + `checkpoint_suppress_post_serialize_hangup` is logged. Minor doc nit to bundle: `_classify_and_flip_goals`'s docstring claim "Every terminal judgment branch records `_last_outcome_was_fail`" is not literally true for the early-return paths (`:1007` empty-pending, `:1018` judgeable-empty, `:1055` generation-guard, Cancelled/exception) — those are safe (unreachable or safe-direction under-drain) but the line should be softened to say so.

**Dismissed (verified — kept for the record):**
- *Shared-flag race / "frozen param reads stale outcome"* (Blind #1/#3, Edge #3/#4/#5/#6/#7) — `process_frame` is serialized; the non-terminal path awaits the single `_in_flight` prior to completion *before* reading `_last_outcome_was_fail` and creating its own task, so at most one classify is in flight and the flag reflects exactly the awaited prior. Stale-flag on the generation-guard / cancel / exception early-returns errs toward *under*-drain (the lenient/safe direction) and is unreachable on the non-terminal path. Terminal turns can't be stacked behind (the blocking path awaits to completion), so the cross-path flag write never mis-coalesces.
- *Forced-None backstop double-drains* (Blind #5) — unreachable: `_MAX_CONSECUTIVE_NONE_VERDICTS=5`; a real fail resets the None counter, and each sub-threshold None sets the flag `False`, so the forced drain is never coalescing-eligible.
- *Coalesced return skips the `_consecutive_none_count` reset* (Blind #12) — false; the reset is at `:1100`, before the outcome branches.
- *Pair→chain scope creep* (Blind #2) — intentional and documented (D1 + Dev Notes: "chain of any length"); a longer rapid burst as one impatience event is the chosen, defensible semantics, and the smoke gate validates timing.
- *`is_hanging_up` flips async* (Blind #6) — it flips synchronously inside `apply_exchange_outcome`/`_schedule_hang_up`, so the backstop read is meaningful.
- Test reaches private tracker tasks (Blind #9) — async test hygiene, not a prod leak. Default-False terminal asymmetry (Blind #10) — documented + terminal turns can't stack. "Prose outruns diff / 767 unverified" (Blind #13) — 767 independently confirmed. Empty-pending / judgeable-empty no-flag-write (Edge #1/#2) — empty-pending ⇒ completion (call ending), judgeable-empty provably unreachable (6.23 f4/f5, server/CLAUDE.md §7).

**Story 6.25 is review-complete; it is now waiting ONLY on your Pixel 9 smoke gate for the `review → done` flip.**

## Change Log
- 2026-06-09 — Implemented (`/bmad-dev-story`, in worktree). Task 2 (primary): coalesce the fast-re-speak window to ONE `fail_penalty` via `_last_outcome_was_fail` + a frozen `coalesce_fail` per-task flag — two stacked FAILs now drain the meter once (50→25, the old cancel-path value), which by keeping the meter off zero ALSO closes the Deviation #7 frame-forward race (sub-issue B / AC1). Task 1: cheap `is_hanging_up` post-serialize backstop. Task 3: real-`PatienceTracker` danger-band regression test. Task 4: corrected the stale "unreachable" claim in code + the 6.20 story. Gates green (ruff clean, 767 pytest). Status `ready-for-dev` → `review`. Awaiting Pixel 9 smoke gate for `review → done`.
- 2026-06-05 — Drafted from the Story 6.20 retrospective code-review (ultracode). **D1 RESOLVED same day (Walid): drain ONCE** — the fast-re-speak window coalesces to a single fail penalty (primary fix, Task 2), which also closes the Deviation #7 race (sub-issue B). Decision-complete. Server-only, no migration, client untouched (unless the fix touches a wire contract). Ready for `/bmad-dev-story`.
