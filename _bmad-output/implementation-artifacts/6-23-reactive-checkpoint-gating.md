# Story 6.23: Reactive-checkpoint precondition gating (stop out-of-context crediting)

Status: done

> **Design-surfaced story (drafted via a 9-agent design workflow, 2026-06-04).** Motivated by the Story 6.21 smoke gate (cop call_id=222): a far-later **trap** checkpoint (`correct_misquoted_time`) was credited at turn 3 by a bare "actually + a time" alibi, before the trap was ever played. We hand-patched that one beat's criteria — but Walid correctly flagged that the *manual, per-beat* patch does not scale: the same **class** recurs for every reactive beat (the cop scenario alone has ~7-10) and every future builder-generated scenario. This story makes the class **structurally impossible**, not patched case-by-case.
>
> **Recommended approach (one concept):** a checkpoint may declare `requires: <prior_checkpoint_id>`. A beat with `requires` is **reactive** and is simply *not eligible to be judged/credited* until the required beat is `met`. No `requires` = **proactive** = today's any-order behaviour, byte-for-byte. The guarantee lives in the engine (one pure helper at the single crediting choke point), the taxonomy lives as data in YAML, the proof lives in the golden net, and the builder auto-populates the field. **Decisions RESOLVED 2026-06-04 (Walid): all 6 → option A (the recommendations). Story is decision-complete → ready for `/bmad-dev-story` (see `## Design Decisions`).**

## Story

As the learner,
I want each scenario beat to be credited **only when it actually happens in context** — so a trap, reveal, or circle-back can never be ticked off before the character has even played it —
so that my on-screen progress and my met/total score honestly reflect what I demonstrated, and the hard "gotcha" beats still land later as designed instead of being silently dead.

(Process angle, for the author/maintainer: I want this guaranteed by the engine + validated automatically, so that I never have to hand-patch criteria beat-by-beat to stop premature crediting.)

## Background

**The bug class.** The goal-based engine (Story 6.10) judges **every** pending checkpoint against **every** user turn, independently and any-order, using each beat's `success_criteria` **text alone** (`checkpoint_manager.py` `_classify_and_flip_goals` passes `{id, success_criteria}` per pending goal to `classify_multi`; `advance_goals` flips any beat whose verdict is `True`, regardless of position). That any-order design is **correct and intentional for PROACTIVE beats** — information the learner may truthfully volunteer at any time (give your name, state your alibi). But many beats are **REACTIVE**: they only make sense as a *response* to a specific prior **character** action (a misquote trap, a named-associate confrontation, an inside-handle reveal, a circle-back recall, a go-silent draw, a cited CCTV timestamp). When a reactive beat's `success_criteria` is written as a self-contained **lexical** pattern that does not encode its precondition, an unrelated earlier turn that superficially matches credits it **prematurely**.

**The live incident (cop_interrogation_01, call_id=222).** The learner's turn-3 alibi *"actually at half past 8… at Jos's diner on 5th Avenue"* correctly credited the proactive `state_where_at_830` (CP5) — but **also** falsely credited the far-later trap `correct_misquoted_time` (CP9), whose criteria was a bare *"correction marker ('actually', 'no I said') + a time"*. No misquote had been delivered, so the trap fired **before it existed**; it is now permanently dead when Mercer later springs it, and the met-set misrepresents what the learner demonstrated.

**Why a process fix, not another patch.** We tightened CP9's prose to require a real prior misquote. But the prose approach is brittle: it relies on the judge inferring from `last_character_line` (the **single** most recent assistant line) whether a trap fired several turns back — which it usually cannot see. `cop_interrogation_01` alone has ~7-10 reactive beats exposed to this exact class, and the problem **scales linearly** with every future builder-generated multi-trap scenario. Walid: *"c'est trop manuel et isolé… il faut un process qui fait que ça ne se répète plus."*

**The key reframing.** Not all checkpoints are equal. **Proactive** beats stay fully any-order (preserving the 6.10 win). **Reactive** beats have a real ordering dependency on a character action — and a reactive beat *literally cannot occur before its trigger*, so gating it removes nothing legitimate and does **not** re-impose ordering on proactive beats.

## Design Decisions (RESOLVED 2026-06-04 — Walid: all 6 = option A)

**Recommended approach — a layered fix anchored on ONE new concept (`requires`), enforced structurally at runtime:**

- **Keystone — runtime trigger gate (engine + data model).** Add one optional checkpoint field `requires: <prior_checkpoint_id>`. A beat is **reactive iff** it carries a `requires` edge; absence == **proactive** == today's behaviour byte-for-byte. Introduce a tiny module-level **pure** helper `judgeable_goals(checkpoints, goals_state) -> list[dict]` returning pending checkpoints whose `requires` id (if any) is already `met`. In `_classify_and_flip_goals`, change the single line that builds the judge payload from `pending = self.pending_goals` to `pending = judgeable_goals(...)`. A gated reactive beat is **never in the judge payload**, so it **cannot flip** — the guarantee is **structural and upstream of the LLM**, immune to criteria wording. `advance_goals` (the frozen pure flip rule shared verbatim with the Story 6.15 harness) stays **untouched** — the gate lives in the *selection of what to judge*, not in the flip rule.
- **Keep the UN-gated `pending_goals`** driving the character steering prompt + the terminal-turn count: the character should still *pursue* a reactive beat (it is the one that delivers the trigger), and a gated beat stays pending so the call can't complete with an un-sprung trap.
- **Layer 2 — golden-net premature-credit assertion (cheap, NON-LLM).** For each beat with `requires`, the calibration engine asserts (pure function over the gate, no extra classify calls) that it is **not** in `judgeable_goals` until its required beat is met. Bump `ENGINE_VERSION` so the ledger force-revalidates every scenario and surfaces any reactive-but-ungated beat already shipped.
- **Layer 3 — builder auto-populates `requires` (light).** The DRAFT LLM already has the time-ordered arc; add ONE rule to `CHECKPOINTS_PROMPT` and stop `sanitize_checkpoints` from dropping the key, so generated scenarios emit `requires` for free (human-confirmed). **Do NOT** add a 4th critique mode or a bare-marker lint as gating machinery in v1 — the runtime gate makes loose criteria *safe*, so the lint is redundant for correctness (it can be a later advisory warning).
- **Discipline — loader fail-fast.** The loader rejects a `requires` pointing at a non-existent or non-earlier (cyclic) id, at call init — same posture as the existing duplicate-id guard.

**Why this is the most elegant.** It fixes the **cause** (a category error in the data model: the engine treated a reactive beat as proactive because the model had no way to say *"this beat is a RESPONSE"*) with one concept and one changed hot-path line. The other sites all fight downstream of that missing concept. The `requires` gate makes *"a reactive beat cannot be credited before its trigger"* a hard property of the crediting path, immune to wording. It is **backward-compatible** (no `requires` = identical code path; all 5 simple scenarios + every proactive beat untouched), **faithful to 6.10 any-order**, and it **inverts the maintenance burden** — net authoring text goes **down**, because the brittle *"PASS only AFTER Mercer has ALREADY…"* clauses get **deleted** and replaced by one structural edge the loader validates.

### Decisions — RESOLVED 2026-06-04 (Walid chose option A on all six; the recommendations below ARE the decisions)

1. **WHERE the guarantee lives — runtime gate vs author-time prose.** (A) Structural `requires` gate in the engine **[RECOMMENDED]**; or (B) keep encoding preconditions in `success_criteria` prose + a builder lint. → **A.** B is judge-dependent and blind to traps beyond the single `last_character_line`; A is wording-immune and lets criteria get *simpler*. The hand-patches are the fragile status quo we are retiring.
2. **SCOPE of `requires` value — single id vs list/OR now.** (A) Ship single-id (AND-able later as a list) **[RECOMMENDED]**; or (B) build the OR-grammar up front. → **A.** Single-id covers every current at-risk beat; gating `answer_biggest_hole` on the single CCTV beat is a safe, slightly-stricter approximation. YAGNI on the grammar.
3. **NON-CHECKPOINT triggers — build `requires_action` now vs defer.** (A) Defer (Phase 2) **[RECOMMENDED]**; or (B) add a character-action signal (a steering-prompt marker read off `last_character_line`) in v1. → **A.** In this catalogue every trigger is itself a credited checkpoint, so Phase 1 is complete.
4. **BUILDER enforcement — light vs also-gating-lint.** (A) Light builder (emit `requires`, un-drop the key) + rely on the runtime gate + golden assertion **[RECOMMENDED]**; or (B) also add the deterministic bare-marker lint + a 4th critique mode as build **blockers**. → **A.** Once the engine gate makes loose criteria safe, the lint is redundant for correctness and risks false positives on legitimate proactive criteria.
5. **"Trigger MET" vs "trigger DELIVERED" gap.** The required beat must be **credited**, not merely **delivered** — the character may spring a trap on a turn where the learner doesn't satisfy the trigger beat's own criteria, leaving the reactive beat gated though the trap is on the table. (A) Accept this and point `requires` at an earlier, reliably-met beat when it bites **[RECOMMENDED]**; or (B) add a separate per-beat "delivered" flag set from the steering prompt. → **A.** In the cop arc triggers are themselves learner-response beats that get credited as the conversation advances; revisit only if a real call strands a beat.
6. **EXISTING scenario migration — hand-add edges vs re-build.** (A) Hand-add ~7 `requires` edges to `cop_interrogation_01` and **delete the brittle prose clauses** (incl. the CP9 hand-patch) **[RECOMMENDED]**; or (B) re-run the builder to regenerate. → **A.** ~7 one-line edits, lets us verify the gate against the known incident, and the prose was already hand-patched so a regenerate buys little.

## Acceptance Criteria (BDD)

### AC1 — The incident, fixed
Given `cop_interrogation_01` with `correct_misquoted_time` carrying `requires: <departure-time beat>`, when the learner's turn-3 alibi *"actually at half past 8… at Jos's diner"* is processed and the misquote trap has NOT yet been delivered/credited, then `correct_misquoted_time` is **not** in the judge payload and is **not** credited (only the proactive location beat flips).

### AC2 — Trigger fires, beat becomes live
Given the same scenario, when the required departure beat is credited and Mercer later springs the misquote, then `correct_misquoted_time` becomes judgeable and a genuine correction credits it.

### AC3 — Proactive untouched (no regression)
Given any checkpoint WITHOUT `requires`, when judged, then behaviour is **byte-identical** to pre-change (any-order preserved); all 5 simple scenarios pass unchanged.

### AC4 — Golden == prod (no fork)
Given the calibration harness, when it derives its pending set, then it uses the **same** `judgeable_goals` helper as prod, so a reactive beat gated in prod is gated in the harness.

### AC5 — Loader fail-fast
Given a `requires` pointing at a non-existent id or a later/cyclic beat, when the scenario loads, then it raises at call init with a clear message (like the duplicate-id guard).

### AC6 — Golden assertion + recurrence sweep
Given a scenario with a `requires` beat, when `calibrate_scenario --golden-only` runs, then it asserts that beat is un-judgeable until its trigger is met and FAILs if not; the `ENGINE_VERSION` bump forces a full catalogue re-sweep (surfacing any reactive-but-ungated beat already shipped).

### AC7 — Criteria simplification
Given `correct_misquoted_time`, when its prose precondition is **reverted** to a clean lexical test, then AC1/AC2 still hold (the engine, not the prose, holds the precondition).

### AC8 — No stranded call
Given a reactive beat that is never triggered, when the call would otherwise complete, then the gated beat keeps the call from completing only as designed (terminal-turn count still includes it), and there is no regression in normal completion for fully-triggered runs.

### AC9 — Pure unit tests (no live LLM)
`judgeable_goals` + the loader validation + the golden assertion are covered in `pytest` with the fake judge, **zero network**. Plus a fake-judge regression test reproducing the call_id=222 alibi and asserting CP9 does NOT credit.

### AC10 — Pre-commit gates
Server: `ruff check . && ruff format --check . && pytest` green (incl. `test_migrations` — though this story adds **no** migration). Client untouched.

### AC11 — Smoke gate (device)
On a cop call, jump to the alibi early with "actually …": CP9 must NOT tick at that turn; later, once the misquote trap is genuinely sprung + answered, the beat ticks. See `## Smoke Test Gate`.

## Tasks / Subtasks

- [x] **T1 — Engine gate.** Add module-level pure `judgeable_goals(checkpoints, goals_state)` in `checkpoint_manager.py`; switch the judge-payload line in `_classify_and_flip_goals` to use it. Leave `advance_goals` and `pending_goals` (prompt/terminal-count) **untouched**. Unit-test the helper (gated / un-gated / no-`requires`).
- [x] **T2 — Harness mirror (the load-bearing coupling).** Adopt the **same** `judgeable_goals` at the harness pending-derivation site (`calibration_engine.py` ~`:586`) so golden == prod. Add a parity test.
- [x] **T3 — Loader validation.** Add optional-field validation in `scenarios.py` (existence + earlier-in-author-order / acyclic); raise on malformed. Unit-test pass/fail. Add `requires` to the checkpoint loader projection so it reaches the runtime.
- [x] **T4 — Data (cop scenario migration).** Add `requires` edges to the ~7 reactive beats in `cop-interrogation-01.yaml`; **revert** `correct_misquoted_time` (and the other hand-patched beats) to clean lexical criteria now that the engine holds the precondition.
- [x] **T5 — Golden net.** Add the pure premature-credit assertion over `requires`; add `requires` to `compute_scenario_hash`'s per-checkpoint projection; bump `ENGINE_VERSION`; run a `--golden-only` sweep. _(Live `--golden-only` sweep deferred to deploy — bundled with the Pixel 9 smoke gate; the gating assertion is non-LLM and unit-proven.)_
- [x] **T6 — Builder.** Add one `CHECKPOINTS_PROMPT` rule to emit `requires` for reactive beats; stop `sanitize_checkpoints` dropping it; thread through `assemble_scenario` (verbatim). Fake-LLM unit test: a reactive draft emits a `requires`, a proactive one omits it.
- [x] **T7 — Docs.** Add a `server/CLAUDE.md` §6 note + a memory entry on reactive-beat gating.
- [x] **T8 — Verify + smoke gate.** Full `pytest` green (683 → 688 after the review patch); ruff check + format clean. Pixel 9 smoke gate (AC11) cleared (call_id=244). Live `calibrate_scenario cop_interrogation_01 --golden-only` run on the VPS after the f2 edge deploy (git_sha `2e2e475`) → **✅ PASS (0 cached)**, 2026-06-08.

## Dev Notes

**The one-concept data model (backward-compatible, additive, YAML-only — no DB/migration):**
```yaml
- id: correct_misquoted_time
  requires: lock_arrival_and_departure   # NEW optional field: this beat is REACTIVE,
  hint_text: ...                         #   gated until lock_arrival_and_departure is met.
  prompt_segment: ...
  success_criteria: ...                  # can now be a CLEAN lexical test again
```
Field absent ⇒ proactive ⇒ unchanged. The field's **mere presence is the taxonomy** — no `beat_type` enum, no free-prose `precondition`, no `requires_action`.

**Proposed cop edges (illustrative — dev to finalise against the YAML; decision 5 may nudge a target to an earlier reliably-met beat):**
| reactive beat | `requires` |
|---|---|
| `correct_misquoted_time` | `lock_arrival_and_departure` |
| `address_named_associate` | `deny_knowing_crew` |
| `explain_prints_on_inside_handle` | `react_to_fingerprint_accusation` |
| `elaborate_through_silence` | `explain_prints_on_inside_handle` |
| `reconcile_cctv_timestamp` | `deny_grey_hood_witness` |
| `hold_consistency_on_recall` | `name_who_was_with_them` |
| `answer_biggest_hole` | `reconcile_cctv_timestamp` (single-id approximation of "CCTV gap OR door-touch") |

**Code references (verify line numbers — from the design-workflow code map):**
- `server/pipeline/checkpoint_manager.py` — `_classify_and_flip_goals` builds the judge payload from `pending_goals` (the single line to switch, ~`:733`); `advance_goals` is the **frozen** pure flip rule shared with the harness (**do NOT touch**); `pending_goals` property (~`:464`) stays for the character prompt; terminal-turn count (~`:533`); `_last_character_line` (~`:976`) is the single most-recent assistant line (why prose preconditions are blind to older traps).
- `server/pipeline/exchange_classifier.py` — `classify_multi`; `server/pipeline/prompts.py` — `EXCHANGE_CLASSIFIER_MULTI_PROMPT`.
- `server/pipeline/scenarios.py` — checkpoint loader + `required` field tuple + the duplicate-id fail-fast guard (~`:435`) to mirror for the `requires` validation.
- `server/scripts/calibration_engine.py` — **harness pending derivation (~`:586`) MUST adopt `judgeable_goals` (golden==prod, the load-bearing coupling)**; `run_golden` (off-topic seed ~`:700-716`, `:787`); `compute_scenario_hash` per-checkpoint projection (~`:1201`); `ENGINE_VERSION` (currently `1` → bump).
- `server/scripts/scenario_builder.py` — `CHECKPOINTS_PROMPT` (~`:192`); `sanitize_checkpoints` (~`:331`, the **whitelist that silently drops new keys** — the load-bearing builder edit); `CRITIQUE_PROMPT` (~`:216`, note its mode-2 *circularity* pass actively launders ordering dependencies OUT — must EXEMPT reactive beats); `validate_structure` (~`:554`); `assemble_scenario` (~`:484`).

**Reuse / do-not-reinvent:**
- The `judgeable_goals` helper is the **same idiom** as `advance_goals`: a module-level pure function shared verbatim by prod and the Story 6.15 harness. The gate is in the **selection** of what to judge, NOT in the flip rule — so the "harness does NOT re-implement the advance rule" contract holds.
- The loader `requires` validation mirrors the existing duplicate-id fail-fast (same posture, same place).

**Gotchas (do NOT trip these):**
- **Golden==prod fork is the #1 risk.** If `calibration_engine.py` is not updated to the shared `judgeable_goals`, gated beats are judged in validation but not prod (false-green). Extract ONE helper, adopt at BOTH call sites, add a parity test.
- **Ship engine + loader + golden + data together (T1–T5) in one commit.** A YAML `requires` field the runtime ignores is *worse* than none (false confidence). The builder (T6) is additive and safe to land in the same change.
- **Do NOT touch `advance_goals`** — the pure flip rule and its golden==prod contract stay byte-for-byte.
- **The builder's CRITIQUE_PROMPT (mode 2) currently rewrites "any-order" dependencies away** — this is plausibly how CP9 became a standalone lexical test. The new builder rule must EXEMPT reactive beats from "make it any-order."

### Project Structure Notes
- Server-only (engine + loader + calibration + builder + cop YAML). **No DB migration** (additive YAML field). Client untouched (HUD already renders met-set; gating only changes *when* a beat enters that set).
- Not in `epics.md` — design-surfaced story (same path as 6.18–6.22).

### Non-goals (explicit)
- Do **NOT** re-impose ordering on PROACTIVE beats — Story 6.10 any-order is preserved verbatim; only beats with an explicit `requires` are gated.
- Do **NOT** undo Story 6.21 character-enforced pursuit (that steers what the character *asks*; this gates only what gets *credited*).
- Do **NOT** add the heavy author-time machinery (4th critique mode + gating bare-marker lint) in v1.
- Do **NOT** build `requires_action` (non-checkpoint triggers), list/OR grammar, or a "delivered" flag now — all YAGNI for the current catalogue.

## References
- [Source: Story 6.21 smoke gate, cop call_id=222 — the live CP9 premature-credit incident + the manual hand-patch this story systematises]
- [Source: Story 6.10 `6-10-goal-based-dialogue.md` — the any-order crediting this story preserves for proactive beats]
- [Source: Story 6.15 `6-15-automated-scenario-calibration-harness.md` — the golden net + the `advance_goals`/`compose` golden==prod sharing idiom this story mirrors]
- [Source: Story 6.16/6.17 scenario builder — the author-time layer that auto-populates `requires`]
- [Source: design workflow 2026-06-04 — 4-reader code map + 4-approach panel + synthesis]

## Smoke Test Gate (Server / Deploy Story)

- [x] **Deployed** to the VPS — git_sha `a7bdf06` (verified: `/health` git_sha match + `judgeable_goals` present in the deployed `checkpoint_manager.py`). 2026-06-07. (Earlier release `03e6031` had the YAML edges WITHOUT the engine gate — the "worse than none" half-state — now corrected.)
- [x] **Premature-credit blocked (the incident):** VALIDATED on device (call_id=244, 2026-06-08, character on Scout). Across a full 9-beat run the learner gave the alibi (turn 16) AND both clock times (turn 20) — yet `correct_misquoted_time` (CP9) **never appeared in any `goals_met_indices`**. Giving a time ≠ correcting a misquote; the gate held. journalctl met-sets walked [0,1,2,3,4,5,6,7,8] with CP9 absent throughout.
- [~] **Trap still lands later:** on-device demonstration **waived by Walid** (2026-06-08) — covered by the automated test `test_reactive_beat_becomes_judgeable_after_trigger_met` (gate opens once the trigger is met → a genuine correction credits CP9). On call_id=244 CP9 became *eligible* after the times were locked (turn 20, gate opened correctly) but the call hit `character_hung_up` (patience drained on repeated "can you repeat?") before Mercer reached the misquote beat.
- [x] **Proactive unchanged:** VALIDATED (call_id=244) — out-of-order credit intact (e.g. `describe_what_doing` idx6 credited before idx4/idx5) and ordered-pursuit return-to-skipped-beat behaving as in Story 6.21.
- [~] **No stranded completion:** the call ended via normal `character_hung_up` (patience), NOT stranded by gating; normal `survived` completion is covered by the automated calibration harness + Stories 6.10/6.20.
- [x] **Server logs clean** — no 429 / errors on Scout; only the pre-existing non-fatal exit-line generator ReadTimeout→fallback (unrelated to 6.23).

**Smoke gate PRE-CLEARED (Walid, 2026-06-08):** "On valide sur le test auto + ce run" — accepted the automated AC9 regression (replays the exact call_id=222 incident) + the device run showing zero out-of-context CP9 misfire across 9 beats. This clears the SMOKE-GATE half only. Story stays in **`review`** — the formal `/bmad-code-review` has NOT been run yet (ideally with a different LLM than the implementer). `review → done` once that review is complete + findings resolved (smoke gate already cleared).

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (ultracode — implementation + 4-dimension adversarial review workflow).

### Debug Log References
- Full server `pytest`: **683 passed** (was ~660; +23 tests). `ruff check .` + `ruff format --check .` clean (91 files).

### Completion Notes List

**The one concept, shipped.** Added the optional checkpoint field `requires: <earlier_checkpoint_id>` and one pure choke-point helper `checkpoint_manager.judgeable_goals(checkpoints, goals_state)`. `_classify_and_flip_goals` now builds its judge payload from `judgeable_goals` instead of `pending_goals`: a reactive beat (one carrying `requires`) is excluded from the classify payload until its required beat is `met`, so it can NEVER flip before its trigger fires — structural, upstream of the LLM, immune to `success_criteria` wording. `advance_goals` (the frozen pure flip rule) and the UN-gated `pending_goals` (character steering prompt + terminal-turn count) are **untouched** (AC3 — proactive-only scenarios are byte-identical).

- **T1 (engine).** `judgeable_goals` + the single switched line. The new `if not judgeable: return` is a defensive guard — with valid backward-only edges the earliest pending beat is always judgeable, so it is effectively unreachable, but it costs nothing and is honest.
- **T2 (harness, the load-bearing coupling).** `calibration_engine.run_calibration` now derives `judgeable = judgeable_goals(...)` for the classify payload while keeping `pending` for the character prompt — exactly mirroring prod. Empty-judgeable → `verdicts = {}` (no flips, no drain), matching prod's early return. Parity test asserts a reactive beat is absent from the judge payload until its trigger is met.
- **T3 (loader).** `load_scenario_checkpoints` validates each `requires` (existence + strictly-earlier author order ⇒ acyclic), raising at call init like the duplicate-id guard. `requires` already reaches the runtime (the loader returns the raw dicts; CheckpointManager stores them).
- **T4 (cop data).** 7 `requires` edges hand-added per the design table; `correct_misquoted_time` (the call_id=222 incident, AC7) and `explain_prints_on_inside_handle` reverted from "PASS only AFTER…" prose to clean lexical tests now the engine holds the precondition.
- **T5 (golden net).** Pure non-LLM `requires_gating_failures` assertion folded into `run_golden.passed` (so `--golden-only` catches it); `requires` added to `compute_scenario_hash`'s per-checkpoint projection; `ENGINE_VERSION` 1 → 2 (forces a full re-sweep). The assertion is a contract guard over `judgeable_goals` (tautological for valid data; its test exercises the failure branch via a broken-gate monkeypatch).
- **T6 (builder).** `CHECKPOINTS_PROMPT` emits `requires` for reactive beats; `sanitize_checkpoints` now PRESERVES it (slugified to match the target id) instead of dropping it — the load-bearing builder edit; `CRITIQUE_PROMPT`'s circularity pass EXEMPTS reactive beats (it used to launder ordering deps out); `validate_structure` mirrors the loader's edge validation. `assemble_scenario` threads `requires` verbatim (no change needed).
- **T7 (docs).** `server/CLAUDE.md` §7 + memory `project_reactive_checkpoint_gating.md`.

**AC9 regression (the incident).** `test_cop_call_222_alibi_does_not_credit_correct_misquoted_time` drives the turn-3 alibi through a CheckpointManager over the REAL cop checkpoints with an OVER-EAGER fake judge (credits everything in the payload); the trap stays pending because the gate keeps it out of the payload — proving the gate, not the criteria, blocks it. Zero network.

**⚠️ Concurrent-commit note (surface to Walid).** A concurrent Story 6.19 dev process committed `03e6031` MID-SESSION and swept 4 of this story's files into ITS commit: `server/pipeline/scenarios.py`, `server/scripts/scenario_builder.py`, `server/pipeline/scenarios/cop-interrogation-01.yaml`, and `sprint-status.yaml` (6-23 → in-progress). All edits are intact + coherent (verified via `git show 03e6031:…` + 683 green), but a future `/commit` of Story 6.23 will NOT include those 4 files (already in history under the 6.19 commit). One-story-one-commit is therefore split; flagged rather than rewriting another live agent's commit.

### File List
**Working tree (uncommitted — Story 6.23):**
- `server/pipeline/checkpoint_manager.py` — `judgeable_goals` helper + judge-payload switch (T1)
- `server/scripts/calibration_engine.py` — harness mirror, `requires_gating_failures`, hash projection, `ENGINE_VERSION`=2, `run_golden` fold (T2/T5)
- `server/CLAUDE.md` — §7 reactive-gating note (T7)
- `server/tests/test_checkpoint_manager.py` — pure helper + engine-integration + AC9 regression tests
- `server/tests/test_scenarios.py` — loader `requires`-edge validation tests
- `server/tests/test_calibration_engine.py` — golden-assertion + harness-parity + hash tests
- `server/tests/test_scenario_builder.py` — sanitize/validate/prompt `requires` tests
- `_bmad-output/implementation-artifacts/6-23-reactive-checkpoint-gating.md` — this story file

**Already committed inside `03e6031` (concurrent 6.19 commit — see note above):**
- `server/pipeline/scenarios.py` — `load_scenario_checkpoints` `requires` validation (T3)
- `server/pipeline/scenarios/cop-interrogation-01.yaml` — 7 `requires` edges + reverted CP9/explain_prints prose (T4)
- `server/scripts/scenario_builder.py` — `CHECKPOINTS_PROMPT`/`CRITIQUE_PROMPT` rules, `sanitize_checkpoints`, `validate_structure` (T6)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — 6-23 status line

**Memory (outside repo):**
- `memory/project_reactive_checkpoint_gating.md` + `MEMORY.md` pointer (T7)

### Review (ultracode adversarial, 2026-06-06)

4-dimension parallel review (engine-correctness+concurrency / golden==prod coupling / loader+builder+data / AC-coverage+test-quality), every finding skeptic-verified by an independent agent (32 agents, 28 raw findings). **Zero code defects confirmed** — the 9 "confirmed-real" engine/coupling/data findings were positive verifications (no proactive regression per AC3; harness judges the exact gated set per AC4; `advance_goals` untouched; loader acyclicity per AC5; `ENGINE_VERSION`+hash invalidation; AC9 regression genuinely proves the gate not the criteria). **2 MEDIUM test-coverage gaps fixed:**
- Added `test_judgeable_goals_multi_level_chain_opens_one_step_at_a_time` — a 3-level A→B→C chain opens one link at a time (the cop arc ships exactly this: react_to_fingerprint_accusation → explain_prints_on_inside_handle → elaborate_through_silence).
- Added `test_judgeable_goals_returns_empty_when_every_pending_beat_is_gated` — direct coverage of the defensive empty-judgeable branch (unreachable with valid backward-only edges, but the helper must be correct for degenerate input).

Gates after fixes: ruff check + format clean (91 files), full server `pytest` **683 passed** (the 2 new pure tests bring 6.23's net to +23; counted in the 681). Server-only, no migration, client untouched.

**Story 6.23 is review-complete; it is now waiting ONLY on your live `calibrate_scenario cop_interrogation_01 --golden-only` + Pixel 9 smoke gate (AC11) for the `review → done` flip.**

### Review Findings (/bmad-code-review, 2026-06-08 — formal review, different session/diff-scope than the 2026-06-06 dev-time review)

**Process.** ultracode adversarial workflow over the combined 6.23 diff (commits `027bf14` + `a7bdf06` + the 6.23 files of `03e6031`): 6 finders — Blind Hunter (diff-only) + Edge Case Hunter + Acceptance Auditor + 3 deep dimension finders (engine-correctness/concurrency, golden==prod coupling, data/criteria). 9 raw → 9 unique. The automated skeptic-verification pass was lossy (subagent StructuredOutput failures), so **every finding was re-adjudicated by hand against the on-disk source**. Final outcome: **0 confirmed shipping defects in the gate mechanism · 2 patch (APPLIED) · 1 defer · 6 dismissed (verified, incl. f4/f5 proven unreachable).** The engine gate, the golden==prod coupling, `advance_goals` untouched, the loader fail-fast, and all 11 ACs were positively confirmed.

**Patch — APPLIED 2026-06-08**
- [x] [Review][Patch] Reactive beat `date_last_touched_door` left ungated — recurrence-sweep gap, same premature-credit class as call_id=222 [`server/pipeline/scenarios/cop-interrogation-01.yaml:103`] — It is the 3rd beat in the door chain (`react_to_fingerprint_accusation` → `explain_prints_on_inside_handle` → `elaborate_through_silence` → `date_last_touched_door`), a post-reveal cross-check structurally identical to the GATED sibling `elaborate_through_silence` — yet it carried no `requires`, so it sat in the judge payload from turn 1. Its generic day-criteria (PASS on "an explicit date or day, e.g. 'last Friday', 'Saturday afternoon'") could be credited by a day the learner volunteers during the EARLY alibi beats, before the inside-handle door is ever revealed — exactly the class this story exists to kill. **FIX APPLIED:** added `requires: explain_prints_on_inside_handle` (loader-valid: `explain_prints_on_inside_handle` precedes it; mirrors its sibling). The edge is additive/stricter (can only PREVENT a premature credit, never cause a false miss — the beat is still judged once the door reveal is credited, which always precedes the date cross-check in a real interrogation), so the call_id=244 device gate stays valid. NOTE: bumps `scenario_hash` → wants a `--golden-only` re-run on deploy. (Found by: dim-data-criteria; f2.)
- [x] [Review][Patch] Builder silently dropped a non-string truthy `requires` (demoted a reactive beat to proactive, no signal) [`server/scripts/scenario_builder.py:373`] — `sanitize_checkpoints` kept `requires` only when `isinstance(str) and .strip()`; a draft LLM emitting `requires: ['a','b']` or `requires: 5` lost the gate silently — the residual of the exact silent-drop class T6 was built to fix, invisible to `validate_structure` (it `continue`s on `requires is None`). **FIX APPLIED:** a present-but-non-clean-string `requires` is coerced to an unmatchable sentinel `__malformed_requires__<slug>` so the existing loader / `validate_structure` "unknown id" fail-fast surfaces it loud + a unit test (`test_sanitize_keeps_malformed_nonstring_requires_as_fail_loud_sentinel`). LOW (authoring tool only, human-confirmed). (Found by: edge-case-hunter; f8.)

**Deferred**
- [x] [Review][Defer] Harness empty-judgeable branch runs `advance_goals({})` while prod early-returns [`server/scripts/calibration_engine.py:644`] — deferred, behaviorally identical (empty verdicts = flip no-op, meter unchanged) on a branch unreachable in shipped data; optional 1-line exact-parity tidy (`continue` instead of `advance_goals({})`). Not a real golden==prod fork — the validated property (goal-state + meter + completion) cannot diverge. (Found by: blind-hunter; f6.)

**Dismissed (verified)**
- f4/f5 — "All-gated tail state skips patience drain / mis-routes the terminal precheck" (initially raised as decision-needed): **proven UNREACHABLE.** Goals are binary `pending`/`met`, and the loader guarantees every `requires` points strictly earlier (acyclic). So the EARLIEST still-pending beat is always judgeable — its trigger, being an earlier beat than the earliest pending one, is necessarily already `met` (or it has none). Therefore `judgeable_goals` is never empty while any beat is pending; the `if not judgeable: return` is a never-executes defensive guard, NOT a patience-drain hole (the dev's own T1 note said as much). A loader "tail must be proactive" guard was considered (Walid's pick) but **dropped on this proof** — it guards an impossible state AND would wrongly reject valid scenarios that legitimately END on a reactive beat (when only that beat remains, its trigger is already met → it's judgeable). Instead the invariant is now documented (server/CLAUDE.md §7 + a strengthened inline comment at `checkpoint_manager.py`) so it isn't re-raised; revisit only if `requires` ever grows OR/list/forward semantics. (Found by: edge-case-hunter.)
- f1 — "Reverted cop criteria can credit in the open gate before the trap is sprung": accepted Decision D5 (the trigger-MET-not-DELIVERED gap, Walid chose option A); the alternating user→character→user protocol delivers the trap between the trigger-credit turn and the next user turn (no premature user-turn slot); the criteria still require a *dispute* posture; empirically validated on device call_id=244 (CP9 never credited even after both clock times were locked).
- f3 — "Girlfriend `explain` 'almost dead' over-strict": the exclusion is FUNCTION-anchored ("a circumstance that would not actually have prevented contact"), not lexical; "almost dead" is a parenthetical example targeting a real off-topic golden-seed false-positive (per the guard-test docstring); Scout's measured bias is 0 false-negatives (never wrongly rejects a real attempt); "judge by intent / informal English passes" is explicit. Deliberate, test-backed tightening.
- f7 — "Reactive beat can't be credited the same turn its trigger is met (one-turn delay)": design property of the single per-turn `judgeable` snapshot, identical in prod and harness (golden==prod preserved); reactive beats are responses to a LATER character action, so naturally separate turns.
- f9 — "Builder slugified `requires` can mis-wire on a duplicate-id collision": near-impossible (needs the draft LLM to emit duplicate ids AND a `requires` whose intended target is the renamed 2nd occurrence); Decision D4 light/human-confirmed builder; the loader + `validate_structure` fail-fast catch every dangling edge.

## Change Log
- 2026-06-08 — **`review → done` (Walid sign-off).** Formal `/bmad-code-review` complete (0 defects in the gate mechanism; 2 patches applied — f2 gated the ungated reactive beat `date_last_touched_door`, f8 made the builder fail-loud on a malformed `requires`; f4/f5 proven unreachable; f6 deferred; f1/f3/f7/f9 dismissed-verified). Committed `2e2e475` + pushed; CI deploy success (VPS git_sha `2e2e475`); the f2 cop edge re-validated live via `calibrate_scenario cop_interrogation_01 --golden-only` → ✅ PASS (0 cached, `ENGINE_VERSION` bump forced re-sweep). Smoke gate already pre-cleared (call_id=244); all gates green (ruff + pytest 688). Story flipped `review → done` in both the story file and `sprint-status.yaml`.
- 2026-06-08 — **Smoke gate PRE-CLEARED; status stays `review` (code-review still owed).** A premature `review → done` flip earlier today was **reverted** — Walid: "on était en mode développement… on n'a même pas fait la review encore." His "On valide sur le test auto + ce run" cleared the SMOKE-GATE half only (device call_id=244: gate held across 9 beats — alibi + both clock times given, CP9 never credited out of context; proactive out-of-order credit intact; full 🅑 trap-fire waived, covered by the automated AC9 regression). Deploy verified (gate `judgeable_goals` live + 7 cop edges). NEXT: run the formal `/bmad-code-review` (ideally a different LLM than the implementer) → resolve findings → THEN `review → done`. NOTE: the device run used the character model on **Groq Llama-4-Scout** (temporary free-tier unblock — Groq paid Dev tier walled platform-wide for months; see [[infra-groq-capacity-and-scout-fallback]]); the gate is model-independent so validity is unaffected.
- 2026-06-06 — **/bmad-dev-story COMPLETE (ultracode)**, ready-for-dev → review. Shipped the one-concept `requires` reactive-gating fix (T1–T7): pure `judgeable_goals` choke point in `checkpoint_manager` (judge payload only; `advance_goals` + un-gated `pending_goals` untouched); harness mirror in `calibration_engine` (golden==prod); loader fail-fast + 7 cop edges + reverted CP9/explain_prints prose; golden premature-credit assertion + `ENGINE_VERSION` 1→2 + hash projection; builder emits/preserves/exempts `requires`; `server/CLAUDE.md` §7 + memory. +23 tests. 4-dimension ultracode adversarial review → 0 code defects, 2 test gaps closed. ⚠️ 4 files (scenarios.py, scenario_builder.py, cop yaml, sprint-status.yaml) were swept into the concurrent Story 6.19 commit `03e6031` — intact but a 6.23 `/commit` won't re-include them.
- 2026-06-04 — **Decisions RESOLVED (Walid): all 6 → option A** — engine-side `requires` gate (D1), single-id value (D2), defer non-checkpoint triggers (D3), light builder + no gating lint (D4), point `requires` at a reliably-met beat (D5), hand-add cop edges + delete prose preconditions (D6). Story is decision-complete → ready for `/bmad-dev-story`.
- 2026-06-04 — Drafted via a 9-agent design workflow (4-reader code map of builder/golden-net/engine + survey of at-risk beats → 4-approach panel → architect synthesis). Recommended approach: a single optional `requires` precondition edge, enforced structurally at the engine's crediting choke point (`judgeable_goals`), proven by the golden net (`ENGINE_VERSION` bump), auto-populated by the builder; `advance_goals` and proactive any-order untouched. 6 open decisions documented with recommendations — Walid to confirm the approach before `/bmad-dev-story`.
