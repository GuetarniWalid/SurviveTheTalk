# Story 6.20: Checkpoint progression robustness & envelope cleanup

Status: review

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

- [x] **Task 1 — Serialize non-terminal classify (AC1)** — in `checkpoint_manager.py::_schedule_classification` (L610-621), on the non-terminal path **await** the prior in-flight classify (let it apply flips + recompose + emit) before scheduling the new one, instead of `prior.cancel()`. Keep the terminal-turn path + generation guard intact. Regression test: two finalized frames back-to-back through the real pipeline with a slow stub classifier → the first turn's flip is NOT lost.
- [x] **Task 2 — Dead `next_hint` cleanup (AC2)** — remove `next_hint` from the server emit (`checkpoint_manager.py:565,773,806`) + `hintText` from `CheckpointAdvancedPayload` + the handler parse (`data_channel_handler.dart:140-153`). Update any tests that asserted the field.
- [x] **Task 3 — `call_end` SET-based reconcile (AC3)** — add `goals_met_indices` to the `call_end` envelope (`patience_tracker.py` ~L1205, sourced from `CheckpointManager._goals_met_indices()`); in `call_screen.dart` `onCallEnd` (~L614-630) prefer the real set (walk-up-only), falling back to the count-based path when absent.
- [x] **Task 4 — Authoring lint (AC4)** — in the Story 6.16 scenario builder / `scenarios.py` load path, flag checkpoints whose `hint_text` and `prompt_segment` share too few salient tokens (keyword-overlap threshold).
- [x] **Task 5 — Lost-tail envelope self-heal (AC5)** — also emit the full-state `checkpoint_advanced` on the reliable LiveKit datachannel (or a periodic idempotent full-state resend); keep the URGENT copy.
- [x] **Task 6 — Pre-commit gates + smoke gate (AC7, AC8).** — Server `ruff check`/`ruff format`/`pytest` green (621 passed); client `flutter analyze` clean + `flutter test` green (405 passed). Smoke gate (AC8) reserved for Walid's Pixel 9 device.

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
claude-opus-4-8 (`/bmad-dev-story`, ultracode multi-agent review pass)

### Debug Log References
- Server gates: `ruff check .` clean, `ruff format --check .` clean (89 files), full `pytest` **622 passed** (was ~615 pre-story; +7 net new tests).
- Client gates: `flutter analyze` → "No issues found!"; `flutter test` → **405 passed** (was 404; +1 net new AC3 reconcile test).

### Review (ultracode, 2026-06-04)
4-lens adversarial review (AC-coverage / async-correctness / regression / test-quality) with every raised finding skeptic-verified: **17 raised → 2 confirmed real → both FIXED**, 15 dismissed (verified false positives / out-of-scope / nits).
- **HIGH (fixed):** AC1's await-not-cancel re-opened a terminal-suppression race the old cancel path structurally avoided. When turn 1 flips the FINAL goal(s) (→ `schedule_completion`) while turn 2 is already committed to the non-terminal path (its terminal precheck read a stale `met_count`), turn 2's user frame would be forwarded to the LLM and race the survived exit line (Deviation #7 double-utterance). Fix: after `_serialize_then_classify`, suppress the frame when `met_count == total` (call completing); `_serialize_then_classify` also skips scheduling a no-op classify once `pending_goals` is empty. Both signals are mock-independent (real instance state). New regression test `test_fast_respeak_into_completion_suppresses_second_user_frame`. (The verifier confirmed the symmetric patience-hangup sub-case is UNREACHABLE on the non-terminal path — a non-terminal precheck means one more fail cannot zero the meter — so only the completion case needed handling.)
- **LOW (fixed):** stale `[hintText]` dartdoc reference in `checkpoint_advanced_payload.dart` contradicting AC2 → corrected to "HUD renders nothing when `hints` empty".

### Completion Notes List

**AC1 — serialize non-terminal classify.** Added `CheckpointManager._serialize_then_classify` (new non-terminal path): it `await`s the in-flight classify to natural completion (flips + recompose + envelope land) before bumping the generation counter and scheduling the fresh classify, replacing the old `prior.cancel()` that discarded a genuinely-met goal on fast re-speak. `process_frame` is serialized per pipecat processor, so awaiting the prior task inside it is re-entrancy-safe; the await also correctly defers the LLM forward until the recomposed (smaller) pending set lands. The terminal blocking path (`_run_classifier_blocking` → cancel-based `_schedule_classification`) and the generation guard are untouched.

**AC2 — dead `next_hint` removed.** Dropped from `build_initial_envelope` + `_emit_checkpoint_advanced` (and deleted the now-unused `_suggested_focus_hint`) on the server; removed `hintText` from `CheckpointAdvancedPayload` + the `data_channel_handler.dart` parse/validation. The HUD already computed the active step locally from `goals_met_indices` + `hints`.

**AC3 — `call_end` SET-based reconcile.** New `PatienceTracker.set_goals_met_indices` (mirrors `set_checkpoints_passed`), called by `CheckpointManager` on every flip; `call_end` now carries `goals_met_indices`. `call_screen.dart` `onCallEnd` prefers the real set (union with current → walk-up-only / never shrink), falling back to the count-based `[0..passed)` reconstruction when the field is absent (pre-6.20 server).

**AC4 — authoring drift lint.** New pure `hint_prompt_drift_pairs` in `scenario_builder.py` (refactored a shared `_salient_tokens` + `_SALIENT_STOPWORDS` out of `lexical_overlap_pairs`); flags any checkpoint whose `hint_text`↔`prompt_segment` salient-token overlap is below 0.2. Surfaced as a `BuildResult.hint_prompt_drift` field + an advisory `build_scenario.py` CLI warning (never blocks the write). Static / authoring-time only — no runtime change.

**AC5 — lost-tail self-heal.** `_emit_checkpoint_advanced` now pushes the SAME full-state envelope BOTH as the existing URGENT `OutputTransportMessageUrgentFrame` (immediate, queue-jumping) AND as a queued `OutputTransportMessageFrame` (ordered media-sender path) — a second independent delivery so a lost tail flip eventually lands. Both ride `send_data(reliable=True)` in this pipecat build; the client dedupes via `_animatedMet` (an identical full-state snapshot is a value-equal no-op). The terminal/hang-up tail is additionally backstopped by the AC3 `call_end` reconcile.

**Test-helper note.** Added `_flip_envelopes` (URGENT-only) in `test_checkpoint_manager.py` so per-flip count/index assertions aren't doubled by the AC5 reliable copy; `_advance_envelopes` still matches all frames (used by initial-state + the AC5-duplicate assertion). The former `test_stale_verdict_dropped_by_generation_guard` was split into `test_fast_respeak_serializes_prior_classify_no_dropped_goal` (AC1, both flips land) + `test_generation_guard_drops_stale_verdict` (direct guard coverage).

### File List
- `server/pipeline/checkpoint_manager.py` — AC1 `_serialize_then_classify` + non-terminal path; AC2 `next_hint`/`_suggested_focus_hint` removal; AC3 `set_goals_met_indices` call; AC5 reliable-copy emit.
- `server/pipeline/patience_tracker.py` — AC3 `_goals_met_indices` field + `set_goals_met_indices` setter + `goals_met_indices` in the `call_end` envelope.
- `server/scripts/scenario_builder.py` — AC4 `_SALIENT_STOPWORDS` + `_salient_tokens` + `hint_prompt_drift_pairs` + `BuildResult.hint_prompt_drift` (computed in `finalize_build`).
- `server/scripts/build_scenario.py` — AC4 CLI drift warning.
- `client/lib/features/call/services/checkpoint_advanced_payload.dart` — AC2 `hintText` removal.
- `client/lib/features/call/services/data_channel_handler.dart` — AC2 `next_hint` parse/validation removal.
- `client/lib/features/call/views/call_screen.dart` — AC3 SET-based `onCallEnd` reconcile.
- `server/tests/test_checkpoint_manager.py` — `_flip_envelopes` helper; AC1/AC2/AC3/AC5 tests; `next_hint` assertion removals.
- `server/tests/test_patience_tracker.py` — AC3 `goals_met_indices` assertions.
- `server/tests/test_scenario_builder.py` — AC4 drift-lint tests.
- `client/test/features/call/services/data_channel_handler_test.dart` — AC2 `next_hint`/`hintText` removal.
- `client/test/features/call/views/call_screen_test.dart` — AC2 `hintText` removal; AC3 SET-preference test.

## Change Log
- 2026-06-04 — `/bmad-dev-story` implementation (ultracode). AC1 non-terminal classify serialized (`_serialize_then_classify`, await-not-cancel — no dropped goal on fast re-speak); AC2 dead `next_hint`/`hintText` removed server+client; AC3 `call_end` carries real `goals_met_indices` + client prefers the SET (walk-up-only) over the count; AC4 `hint_text`↔`prompt_segment` drift lint in the 6.16 builder (+CLI warning); AC5 per-flip `checkpoint_advanced` also emitted as a reliable queued copy (lost-tail self-heal, client dedupes). Gates green: server ruff + `pytest 622`, client `flutter analyze` clean + `flutter test 405`. Ultracode 4-lens adversarial review (17 raised → 2 confirmed → both fixed: a terminal-suppression race AC1 re-opened + a stale dartdoc). Status → review; Pixel 9 smoke gate (AC8) reserved for Walid.
- 2026-06-04 — Refocused (Walid): the consigne↔character alignment fix moved to Story 6.21 (app is always guided/ordered → HUD lowest-unmet was already correct, "frontier" idea dropped). This story keeps only the independent robustness + cleanup items: dropped-goal serialize, dead `next_hint` cleanup, `call_end` SET-based reconcile, hint/prompt authoring lint, lost-envelope resend. Renamed from `6-20-checkpoint-hud-alignment`.
- 2026-06-03 — Spec drafted via `/bmad-create-story` from a 32-agent alignment audit run during Story 6.18's smoke gate (call_id=216).
