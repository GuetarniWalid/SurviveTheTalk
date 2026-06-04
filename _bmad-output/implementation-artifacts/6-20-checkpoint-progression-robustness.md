# Story 6.20: Checkpoint progression robustness & envelope cleanup

Status: ready-for-dev

> Design decisions RESOLVED with Walid 2026-06-04. **Scope note:** the consigne↔character *alignment* fix moved to **Story 6.21** (character-enforced ordering) — Walid clarified the app is always guided/ordered, so the HUD's lowest-unmet display was already correct and the "frontier" idea is dropped. This story keeps only the **independent robustness + cleanup** items the alignment audit surfaced. Nothing coded yet.

## Story

As the learner (and the future debrief),
I want checkpoint progress to be **reliable and accurately recorded** — no silently-lost ticks, no stale wire fields, the real met-set carried to call end —
so that what I accomplished is never dropped or mislabeled.

## Background

A 32-agent code audit (run during Story 6.18's smoke gate, call_id=216) surfaced several issues in the goal-based checkpoint system. The **primary** one (the on-screen consigne diverging from what the character pursues) is fixed by **Story 6.21** (make the character follow the order; the display was already right). This story collects the audit's **other, independent** findings — all verified `is_real=True` — that are worth fixing regardless of the alignment work:

- **`breaks_progress` (rarer):** a goal the user genuinely completed can be silently dropped on fast re-speak.
- **Cleanup / forward-looking:** a dead wire field, a count-based (lossy) call-end reconcile, authoring drift between two checkpoint strings, and a lost-final-envelope with no resend.

## Design Decisions (RESOLVED 2026-06-04 with Walid)

- **D1 (alignment strategy) → MOVED OUT.** The HUD "frontier" display fix is **dropped**; alignment is owned by Story 6.21. This story makes **no change to the HUD active-step rule** (it stays lowest-unmet).
- **D2 (dropped-goal fix) → INCLUDE.**
- **D3 (minor items) → INCLUDE ALL FOUR** (next_hint cleanup, call_end set-based, hint/prompt lint, lost-envelope resend).

## Acceptance Criteria (BDD)

### AC1 — A completed goal is never silently dropped on fast re-speak
Given the user speaks a new finalized turn before the previous turn's classify resolves (~0.2-0.5 s)
When `_schedule_classification` handles the new turn on the **non-terminal** path
Then the previous turn's classify is **awaited to completion** (its flips, prompt recompose, and envelope land) before the new turn is judged against the updated state — no genuinely-met goal is discarded. The terminal-turn path (Deviation #7) and the generation guard are unchanged.

### AC2 — Dead `next_hint` removed (wire matches reality)
Given the HUD computes the active step locally and ignores the server `next_hint`
Then the unused `next_hint` field is removed from the server emit + `CheckpointAdvancedPayload` + handler parse, so the `checkpoint_advanced` wire contract carries only what the HUD consumes (`goals_met_indices` + `hints`). Pure cleanup, zero behavior change.

### AC3 — `call_end` carries the real met SET, not just a count
Given the `call_end` envelope currently carries only `checkpoints_passed` (a count)
Then it ALSO carries `goals_met_indices` (the real met set, from `CheckpointManager._goals_met_indices()`); the client reconcile prefers that exact set (walk-up-only / never shrink), falling back to the count-based `[0..count)` when absent — so a future debrief can't mislabel WHICH goals were met.

### AC4 — Authoring lint: `hint_text` vs `prompt_segment` drift
Given a checkpoint's `hint_text` (displayed) and `prompt_segment` (what the character is steered to say) are distinct authored strings
Then the Story 6.16 scenario builder / `scenarios.py` load path flags any checkpoint whose two strings share too few salient tokens (keyword-overlap below a threshold), surfacing authoring drift before a scenario ships. Static, per-scenario; no runtime change.

### AC5 — Lost final envelope self-heals
Given the per-flip `checkpoint_advanced` rides an URGENT/lossy frame and a lost FINAL flip has no resend (full-state envelopes only self-heal on the NEXT flip)
Then the full-state envelope is ALSO emitted on the reliable LiveKit datachannel (or via a periodic idempotent full-state resend) so a lost tail flip eventually lands; the client already dedupes via `_animatedMet`, so a duplicate is harmless. Keep the URGENT copy for the ~0.2-0.5 s tick latency.

### AC6 — No regression
Given these are additive/robustness changes
Then the goal-based engine (`classify_multi`/`advance_goals`), the terminal-turn sync, `survival_pct`, and the existing server + client checkpoint tests stay green; the HUD active-step rule is UNCHANGED (lowest-unmet).

### AC7 — Pre-commit gates
Server: `ruff check . && ruff format --check . && pytest` green. Client (if `call_end` reconcile / payload touched): `flutter analyze` + `flutter test` green.

### AC8 — Validation (smoke gate)
See `## Smoke Test Gate`: fast re-speak does not lose a just-completed tick (AC1); a normal call still ends cleanly with the correct met-set in `call_end` (AC3).

## Tasks / Subtasks

- [ ] **Task 1 — Serialize non-terminal classify (AC1)** — in `checkpoint_manager.py::_schedule_classification` (L610-621), on the non-terminal path **await** the prior in-flight classify (let it apply flips + recompose + emit) before scheduling the new one, instead of `prior.cancel()`. Keep the terminal-turn path + generation guard intact. Regression test: two finalized frames back-to-back through the real pipeline with a slow stub classifier → the first turn's flip is NOT lost.
- [ ] **Task 2 — Dead `next_hint` cleanup (AC2)** — remove `next_hint` from the server emit (`checkpoint_manager.py:565,773,806`) + `hintText` from `CheckpointAdvancedPayload` + the handler parse (`data_channel_handler.dart:140-153`). Update any tests that asserted the field.
- [ ] **Task 3 — `call_end` SET-based reconcile (AC3)** — add `goals_met_indices` to the `call_end` envelope (`patience_tracker.py` ~L1205, sourced from `CheckpointManager._goals_met_indices()`); in `call_screen.dart` `onCallEnd` (~L614-630) prefer the real set (walk-up-only), falling back to the count-based path when absent.
- [ ] **Task 4 — Authoring lint (AC4)** — in the Story 6.16 scenario builder / `scenarios.py` load path, flag checkpoints whose `hint_text` and `prompt_segment` share too few salient tokens (keyword-overlap threshold).
- [ ] **Task 5 — Lost-tail envelope self-heal (AC5)** — also emit the full-state `checkpoint_advanced` on the reliable LiveKit datachannel (or a periodic idempotent full-state resend); keep the URGENT copy.
- [ ] **Task 6 — Pre-commit gates + smoke gate (AC7, AC8).**

## Dev Notes

**Code references (from the 2026-06-03 alignment audit):**
- `server/pipeline/checkpoint_manager.py:610-621` `_schedule_classification` — the `prior.cancel()` is the dropped-goal bug (AC1). Cancel-before-`_generation`-bump means the generation guard itself is safe; the loss is the cancel discarding the in-flight POST → serialize on the non-terminal path.
- `:565,773,806` server `next_hint` emit (AC2 — dead, HUD ignores it: `client/.../data_channel_handler.dart:192` "no next_hint fallback"). `:822-828` `_goals_met_indices` (AC3 source).
- `server/pipeline/patience_tracker.py` ~L1205 — `call_end` carries `checkpoints_passed` count only (AC3).
- `client/lib/features/call/.../data_channel_handler.dart:140-153` (`hintText` parse — remove, AC2); `call_screen.dart:~614-630` `onCallEnd` reconcile (AC3).
- `server/pipeline/scenarios.py` load path + the Story 6.16 builder (AC4 lint).

**Reuse / do-not-reinvent:**
- The envelope is already full-state (`goals_met_indices` + `hints`) and self-healing on the next flip — AC5 just adds a reliable copy/resend so the LAST flip self-heals too; the client already dedupes via `_animatedMet`.
- **The HUD active-step rule stays "lowest unmet" — do NOT change it here** (alignment is Story 6.21).

**Gotchas:**
- Keep the terminal-turn sync (Deviation #7) + generation guard intact when changing `_schedule_classification` (AC1) — only the **non-terminal** cancel becomes an await.
- Removing `next_hint` (AC2) must not break the initial-state envelope path — verify `build_initial_envelope` + the client snapshot still work from `goals_met_indices` + `hints` alone.

### Project Structure Notes
- Server: `checkpoint_manager.py`, `patience_tracker.py`, `scenarios.py` + the 6.16 builder. Client: `data_channel_handler.dart`, `call_screen.dart` (payload + call_end reconcile). No DB migration (`call_end` is a data-channel envelope).
- Not in `epics.md` — audit-surfaced story (same path as 6.18/6.19/6.21).

### References
- [Source: alignment audit 2026-06-03, 32 agents — these are the verified `is_real=True` non-alignment findings]
- [Source: Story 6.21 `6-21-character-enforced-checkpoint-ordering.md` — owns the consigne↔character alignment; this story is its robustness companion]

## Smoke Test Gate (Server / Deploy Story)

- [ ] **Deployed** to the VPS (`deploy-server.yml` git_sha match).
- [ ] **No dropped goal on fast re-speak (AC1):** complete an objective, then immediately speak again — the completed step's tick must appear (not be swallowed). _Proof:_ device + `journalctl … | grep checkpoint_advanced` shows the flip.
- [ ] **Correct met-set at call end (AC3):** finish a call having met goals out of order → the `call_end` payload carries the real `goals_met_indices` (not a sequential best-guess). _Proof:_ `journalctl … | grep call_end`.
- [ ] **No regression:** a normal in-order run ticks each step; the HUD active step is still lowest-unmet; `allMet` ends cleanly (reason=survived).
- [ ] **Server logs clean** on the happy path.

## Dev Agent Record

### Agent Model Used
_(to be filled by dev)_

### Debug Log References

### Completion Notes List
_(to be filled by dev)_

### File List
_(to be filled by dev)_

## Change Log
- 2026-06-04 — Refocused (Walid): the consigne↔character alignment fix moved to Story 6.21 (app is always guided/ordered → HUD lowest-unmet was already correct, "frontier" idea dropped). This story keeps only the independent robustness + cleanup items: dropped-goal serialize, dead `next_hint` cleanup, `call_end` SET-based reconcile, hint/prompt authoring lint, lost-envelope resend. Renamed from `6-20-checkpoint-hud-alignment`.
- 2026-06-03 — Spec drafted via `/bmad-create-story` from a 32-agent alignment audit run during Story 6.18's smoke gate (call_id=216).
