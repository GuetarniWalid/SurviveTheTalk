# Story 6.22: Suppress user turns once a hang-up is in progress (no reply over the exit line)

Status: ready-for-dev

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

- [ ] **Task 1 — Suppress post-hang-up turns** (AC1, AC3) — in `checkpoint_manager.py::process_frame`, add an early `if pt.is_hanging_up: return` (suppress, no `push_frame`) for finalized user `TranscriptionFrame`s, placed BEFORE the `is_terminal_turn` computation so it catches turns that arrive after the hang-up is scheduled. Keep the existing terminal-turn block intact for the triggering turn. Mind the `_terminal_turn_lock` + the `getattr(frame, "finalized", …)` asymmetry (`server/CLAUDE.md` §1).
- [ ] **Task 2 — Decide & (if chosen) mic mute** (see Decisions D1) — optionally arm the Story 6.11 `InputGate` when the hang-up is scheduled so a loud, continuous talker can't keep feeding STT/VAD during the exit line. Reuse the existing `input_gate` wiring; do not duplicate it.
- [ ] **Task 3 — Tests** (AC5) — post-hang-up suppression unit/pipeline test + a regression that the terminal-turn suppression and the normal path are unchanged.
- [ ] **Task 4 — Pre-commit + smoke gate** (AC6, AC7).

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

## Change Log
- 2026-06-04 — Drafted via `/bmad-create-story` (Walid's call) from the Story 6.18 smoke gate (call_id=219). Server-only; pre-existing overlap bug spun off from 6.18. Open `## Decisions` (D1 mechanism / D2 scope) — review before `/bmad-dev-story`.
