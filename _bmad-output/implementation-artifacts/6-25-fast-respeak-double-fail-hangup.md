# Story 6.25: Fast-re-speak double-fail premature hang-up + Deviation #7 race

Status: ready-for-dev

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
- [ ] **Task 1 — Post-await terminal re-check (AC1 backstop).** With D1=once (Task 2) this should be unreachable on the non-terminal path — keep only as a cheap belt-and-suspenders. In `checkpoint_manager.py::process_frame` (the non-terminal `else` branch, ~`:656-690`): after `await self._serialize_then_classify(text)`, re-evaluate the terminal condition against the **current** meter (mirror the `:607-609` precheck) and, if now terminal/hanging-up, suppress the frame (the same `return` the completion case uses). Prefer re-routing a now-terminal turn through the blocking classify so its verdict is awaited before the forward decision. Keep the terminal-turn lock + generation guard intact.
- [ ] **Task 2 — Coalesce the fast-re-speak window to ONE fail (AC2, D1=once) — PRIMARY FIX.** Make the meter-drain idempotent across a serialized fast-re-speak window so two stacked FAILs apply a single `fail_penalty` (restore the old cancel-path patience effect; the awaited prior's outcome is the one that counts). By keeping the meter off zero on the non-terminal path this ALSO closes sub-issue B (AC1) — then verify Task 1's post-await re-check is unreachable on the non-terminal path (keep it only as a cheap backstop).
- [ ] **Task 3 — Regression test (AC1/AC2).** Real `PatienceTracker`, danger-band meter (e.g. `initial_patience=50, fail_penalty=-25`, 6 checkpoints), two back-to-back FAILs with `classify_delay>0` so turn 2 awaits turn 1 in flight; assert the meter / `is_hanging_up` per the D1 contract **and** that turn 2's frame is not forwarded into a hang-up. (This is the coverage gap the 6.20 review found — `test_fast_respeak_*` only drives flips/completion; the only real-tracker two-fail test `test_terminal_turn_lock_serializes_concurrent_invocations` at `:1219` is 15/-15 = terminal on turn 1.)
- [ ] **Task 4 — Doc fix (AC4).** Correct `checkpoint_manager.py:680-682` + `6-20-checkpoint-progression-robustness.md` line 112.
- [ ] **Task 5 — Gates + smoke gate (AC5/AC6).**

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

## Change Log
- 2026-06-05 — Drafted from the Story 6.20 retrospective code-review (ultracode). **D1 RESOLVED same day (Walid): drain ONCE** — the fast-re-speak window coalesces to a single fail penalty (primary fix, Task 2), which also closes the Deviation #7 race (sub-issue B). Decision-complete. Server-only, no migration, client untouched (unless the fix touches a wire contract). Ready for `/bmad-dev-story`.
