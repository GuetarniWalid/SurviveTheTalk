# Story 6.22: Suppress user turns once a hang-up is in progress (no reply over the exit line)

Status: review

> Drafted 2026-06-04 from the Story 6.18 Pixel 9 smoke gate (call_id=219). Has an open `## Decisions for Walid` — review before `/bmad-dev-story`.

## Story

As the learner,
I want the character to deliver **only** its hang-up line once it has decided to end the call — even if I keep talking after that —
so that I don't hear a normal reply playing **on top of** the exit line (two voices at once), which feels broken and incoherent.

## Background

**The trigger — cop call `call_id=219` (2026-06-04, Story 6.18 smoke gate, kill-switch path).** The patience meter hit zero and the character scheduled a `character_hung_up`. The turn that drained the meter ("…I don't know.") was correctly suppressed. But the user **kept speaking** ("Maybe you are someone else.") **after** the hang-up was already scheduled. That new turn was **not** suppressed → it flowed to the LLM → the character generated a **normal reply** that played **over** the canned exit line. Result: two overlapping bot utterances + a 6 s `hang-up TTS timeout` + force-terminate. Walid heard "one line, then another thrown on top right after."

**Root cause (verified in the on-disk code + the call_id=219 journalctl trace).** In `checkpoint_manager.py::process_frame`, the suppression decision is:

```python
is_terminal_turn = not pt.is_hanging_up and (
    (pt.patience > 0 and pt.patience + pt.fail_penalty <= 0)
    or self.met_count + 1 >= len(self._checkpoints)
)
```

Because of the leading `not pt.is_hanging_up`, **once a hang-up is already in progress** (`is_hanging_up == True`) every subsequent turn is judged **non-terminal** → it falls through to the normal parallel path and `await self.push_frame(frame, direction)` forwards it to the LLM. The preemptive-suppress `if pt.is_hanging_up: return` exists, but it lives **inside** the `if is_terminal_turn:` block, so a post-hang-up turn (which is non-terminal by the above) **never reaches it**.

**Not a Story 6.18 regression.** This overlap happens with **canned OR generated** exit lines (it is about turn routing, not line content). It is pre-existing — `is_hanging_up` gating and the terminal-turn suppression predate 6.18. Story 6.18's dynamic lines are ≤2 sentences and actually mask it more often (shorter lines finish before the user re-speaks); the long canned cop lines on the kill-switch path made it audible.

**Out of scope:** the exit-line *content* (owned by Story 6.18), difficulty, and the multi-goal "two goals complete in the same final turn" disjoint-ending case (a distinct deferred item — `deferred-work.md`).

## Acceptance Criteria (BDD)

### AC1 — Post-hang-up user turns are suppressed
Given a hang-up has been scheduled (`patience_tracker.is_hanging_up == True`)
When a subsequent finalized user `TranscriptionFrame` reaches `CheckpointManager`
Then the frame is **suppressed** (not forwarded downstream to `context_aggregator.user()` / the LLM), so **no normal reply is generated** to play over the exit line. A single `checkpoint_preemptive_suppress` (or equivalent) log line records the drop.

### AC2 — The exit line is the sole final utterance
Given AC1 holds
When the call ends
Then only the hang-up line (generated or canned) is spoken — no overlapping second bot utterance — and the `hang-up TTS timeout` WARNING does **not** fire on this account (the BotStoppedSpeaking for the exit line is not delayed by a competing reply).

### AC3 — Existing suppression unchanged
Given the meter-zero / all-met **terminal turn** (the turn that *triggers* the hang-up)
Then it is still suppressed exactly as today (the survived terminal-turn sync — Deviation #7 — and the `character_hung_up` meter-zero suppression are unchanged); no double-suppression log, no behavior change on the happy path.

### AC4 — No regression to the other paths
Given a normal (non-hang-up) call
Then nothing changes: turns route to the LLM as before; the silence ladder, `survived`, `noisy_environment`, and `patience_warning` paths are unaffected. (`noisy_environment` already mutes the mic via `InputGate` — this story must not conflict with that.)

### AC5 — Test
Given a `CheckpointManager` whose `PatienceTracker.is_hanging_up` is True
When a finalized user `TranscriptionFrame` is driven through it
Then a test asserts the frame is **not** pushed downstream and the classifier is **not** scheduled. (Drive through a real-ish pipeline per `server/CLAUDE.md` §1 frame-direction guidance where practical.)

### AC6 — Pre-commit gates
`ruff check .` + `ruff format --check .` + `pytest` (server) green.

### AC7 — Smoke gate (device)
On a `hard` cop call, **keep talking after the character starts to hang up** → only the exit line plays (no second voice over it), and `journalctl … | grep 'hang-up TTS timeout'` shows none for that call.

## Tasks / Subtasks

- [x] **Task 1 — Suppress post-hang-up turns** (AC1, AC3) — DONE. Added an early `if … is_hanging_up: return` (suppress, no `push_frame`) for finalized user `TranscriptionFrame`s in `checkpoint_manager.py::process_frame`, placed BEFORE the echo-skip guard AND the `is_terminal_turn` computation, and independent of `_bot_speaking` (covers the over-the-exit-line case). Existing terminal-turn block left intact; the triggering turn is judged while `is_hanging_up` is still False (AC3). Distinct log `checkpoint_post_hangup_suppress`.
- [x] **Task 2 — Decide & (if chosen) mic mute** (see Decisions D1) — DONE. **D1 → (a) frame-suppress only**; no `InputGate` mic-mute wiring (option (b) deferred — only justifiable if the AC7 smoke gate still shows interference). **D2 → finalized turns only.**
- [x] **Task 3 — Tests** (AC5) — DONE. 5 new tests (post-hang-up suppression; over-the-exit-line/bot-speaking; interim pass-through; triggering-vs-post distinct logs with a real `PatienceTracker`; real-pipeline-drive suppression) + 2 MagicMock-fixture pins + stale-comment fix.
- [x] **Task 4 — Pre-commit + smoke gate** (AC6, AC7) — pre-commit (AC6) DONE: `ruff check` + `ruff format --check` + `pytest` (643 passed) green. AC7 device smoke gate OWED to Walid (the `review → done` gate — see Smoke Test Gate below).

## Dev Notes

- Pipeline order (verified): `… → checkpoint_manager → patience_tracker → context_aggregator.user() → llm → …`. `CheckpointManager` sits UPSTREAM of the user aggregator, so dropping the frame there prevents the LLMRun that would generate the overlapping reply.
- `is_hanging_up` is set synchronously inside `_schedule_hang_up` (`_hang_up_in_progress = True`), so it is reliably True for any turn processed after the hang-up is scheduled.
- The `inappropriate_content` path is dormant in prod (`abuse_classifier=None`); this story does not change that.
- Server-only; no client change expected; no migration.

## Decisions for Walid

- **D1 — Suppression mechanism.** (a) **Frame-suppress only** in `CheckpointManager` (lightest; drops the post-hang-up TF so no reply is generated) — recommended, matches the existing terminal-turn suppression. (b) **Frame-suppress + arm the `InputGate` mic mute** (mirrors Story 6.11's noisy-environment fix; more robust against a LOUD continuous talker who would otherwise keep the STT busy, but adds wiring). Recommendation: start with (a); add (b) only if a device smoke test still shows the user's continued speech interfering.
- **D2 — Scope of "user turn".** Suppress only **finalized** user TFs (consistent with the existing observers), or also drop interim transcriptions during hang-up? Recommendation: finalized only (the LLMRun is what matters); interim frames are harmless.

## Smoke Test Gate (Server / Deploy Story)

- [ ] **Deployed** to the VPS (`deploy-server.yml` git_sha match).
- [ ] **No overlap:** `hard` cop call, keep talking after the character begins to hang up → only the exit line is heard, no second bot voice over it.
- [ ] **No false timeout:** `journalctl … | grep 'hang-up TTS timeout'` → none for that call.
- [ ] **No regression:** a normal completed `survived` call still ends cleanly with its single closing line (Story 6.18 behavior intact).

## Dev Agent Record

### Completion Notes (2026-06-05)

Implemented via `/bmad-dev-story` (ultracode). Server-only; no client change, no migration.

**Root-cause fix (Task 1, AC1/AC2/AC3).** Added a post-hang-up suppression early-return in `CheckpointManager.process_frame` (`server/pipeline/checkpoint_manager.py`). For a finalized, non-empty user `TranscriptionFrame`, when `self._patience_tracker.is_hanging_up` is True it logs `checkpoint_post_hangup_suppress` and returns WITHOUT `push_frame` — dropping the turn so it never reaches `context_aggregator.user()` / the LLM and cannot generate a reply over the exit line.
- Placed BEFORE the echo-skip guard and the `is_terminal_turn` computation, and INTENTIONALLY independent of `_bot_speaking`. Key design choice: the overlap happens precisely WHILE the exit line is playing (bot speaking), and the Story 6.20 echo guard only skips *classification* (it still forwards). A suppression inside the `not _bot_speaking` block would let the over-the-exit-line turn slip through — so it must sit before it.
- AC3 preserved: the TRIGGERING terminal turn is judged while `is_hanging_up` is still False (the hang-up is scheduled DURING its awaited classify), so the early-return is skipped for it and its existing `checkpoint_preemptive_suppress` path is unchanged. Each turn logs at most one suppression line (no double-suppression).

**Decisions resolved.** **D1 → (a) frame-suppress only** (no `InputGate` mic-mute; matches the existing terminal-turn suppression, lightest fix; option (b) deferred — only justifiable if the AC7 device smoke gate still shows interference). **D2 → finalized turns only** (guards on `getattr(frame, "finalized", False)`, the conservative default per `server/CLAUDE.md` §1; interim partials pass through untouched).

**Tests (Task 3, AC5).** 5 new tests + 2 fixture pins:
- `test_post_hangup_user_turn_is_suppressed` — not forwarded + classifier not scheduled + single log line.
- `test_post_hangup_turn_suppressed_even_while_bot_speaking` — the over-the-exit-line case (pins the placement before the echo guard).
- `test_post_hangup_interim_turn_passes_through_unchanged` — D2 finalized-only.
- `test_triggering_turn_then_post_hangup_turn_distinct_suppress_logs` — AC3, real `PatienceTracker`: triggering turn → `checkpoint_preemptive_suppress`, follow-up → `checkpoint_post_hangup_suppress`, no double.
- `test_post_hangup_user_turn_suppressed_via_real_pipeline_drive` (`test_bot_pipeline_wiring.py`) — AC5 pipeline-drive: a recorder downstream of the manager never sees the suppressed TF and the classifier is never invoked, through a real `PipelineTask`.
- Fixture: the default `_make_manager` MagicMock tracker (and the Déviation-#28 drive test's tracker) now pin `is_hanging_up=False`, `patience=100`, `fail_penalty=-15` — a bare auto-Mock's truthy `is_hanging_up` would trip the new early-return, and the `is_terminal_turn` comparison needs real ints once the truthy short-circuit is gone. Updated the now-stale rationale comment in `test_pass_through_for_all_frame_types`.

**Gates (Task 4, AC6).** `ruff check .` ✅ · `ruff format --check .` ✅ · full server `pytest` ✅ **643 passed**.

**Adversarial review (ultracode).** 3-dimension parallel review (AC-coverage / fixture-ripple / suppression-logic+concurrency) with per-finding adversarial verification. AC-coverage and logic/concurrency dimensions returned ZERO findings. Fixture-ripple surfaced 3 observations: 2 verified benign (two existing default-tracker tests now route their final-goal turn through the terminal-blocking path — production-faithful, coverage intact elsewhere), 1 confirmed low-severity stale comment — fixed.

**AC7 device smoke gate — OWED to Walid** (the `review → done` gate).

### File List
- `server/pipeline/checkpoint_manager.py` (modified) — post-hang-up suppression early-return in `process_frame`.
- `server/tests/test_checkpoint_manager.py` (modified) — default `_make_manager` tracker pins + stale-comment fix + Story 6.22 test section (4 tests).
- `server/tests/test_bot_pipeline_wiring.py` (modified) — pinned tracker in the Déviation-#28 drive test + new pipeline-drive suppression test.

## Change Log
- 2026-06-04 — Drafted via `/bmad-create-story` (Walid's call) from the Story 6.18 smoke gate (call_id=219). Server-only; pre-existing overlap bug spun off from 6.18. Open `## Decisions` (D1 mechanism / D2 scope) — review before `/bmad-dev-story`.
- 2026-06-05 — Implemented via `/bmad-dev-story` (ultracode). Post-hang-up turn suppression in `CheckpointManager.process_frame` (D1 → (a) frame-suppress only, D2 → finalized-only). 5 new tests + 2 fixture pins + stale-comment fix; `ruff` + `pytest` (643) green; 3-dimension adversarial review (1 low-sev stale comment fixed). `ready-for-dev` → `review`. AC7 Pixel 9 smoke gate owed before `review → done`.
