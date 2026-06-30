# Story 10.9: Decouple SURVIVAL (engagement) from PROGRESS (beats) — patience drains on disengagement, not beat-non-advancement

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

> **SCOPE NOTE — read first.** The sprint-status key is
> `10-9-decouple-survival-from-progress`. This is a **server-only, zero-client-change**
> re-architecture of the patience/survival mechanic. It is **carved out of the Story 10.8
> live Pixel 9 smoke gate** (calls 344/345, the 20-beat Detective): an *engaged* B1 learner
> kept getting hung up (10/20 then 8/20) because the patience meter drains on **beat-non-advancement**,
> while an engaged learner doesn't advance for **good reasons** (the cop circles back to
> already-met beats; `lock_arrival_and_departure` is near-unsatisfiable for a stay-home
> alibi; clarification turns; slow B1 pace). This is **NOT a 10.8 bug** — 10.8's own fixes
> (judge accuracy, HUD sync, no mid-sentence hang-up, no truncation) are validated live +
> golden 6/6. Lowering `fail_penalty` −15→−9 in the 10.8 review only **slowed the bleed** of
> a mis-placed wound; the cure is structural.
>
> **The single source of truth for this story is the design brief:**
> [`survival-decoupling-design-brief.md`](_bmad-output/implementation-artifacts/survival-decoupling-design-brief.md)
> — a 13-agent design exploration (5 competing architectures adversarially stress-tested on a
> 12-case battery + the "Survive the Talk" DNA + feasibility). **Read it in full before
> starting.** This spec is the dedicated `/bmad-create-story` session the brief reserved
> (one agent per workflow — the 10.8 dev agent did not, and must not, write it).
>
> **TWO things Walid still owes / two non-negotiables:**
> - **`DECISION (proposed → confirm at dev)` — the gaming stall-backstop (Stream C).** The
>   brief says the bounded re-coupling that closes "engaged-looking filler forever" needs
>   **Walid's explicit blessing**. It is grounded with a recommended direction, but resolve
>   it WITH Walid when you reach Stream C — do not just build it.
> - **MANDATORY de-risking sequence (Stream E) — ship the signal flag-OFF, measure it on
>   real calls, THEN flip ON.** The judge's accuracy on the NEW engagement axis is **unproven
>   and load-bearing** (the "judge is accurate" grant was earned on `met`/`unmet`, never on
>   good-faith/disengaged). This sequence is **not optional** (brief §2, §5.1).
>
> **THREE dev traps surfaced during context engineering — do NOT copy the obvious-but-wrong
> pattern (details in Dev Notes):**
> 1. `__engaged__` defaults **`True`** (lenient — never fabricate disengagement) at BOTH the
>    parse layer and the manager-pop — **the opposite of `ABUSE_KEY`, which defaults `False`.**
> 2. `stall_grace_turns` is a **per-difficulty preset (easy 8 / med 6 / hard 4) routed through
>    `resolve_patience_config`** — NOT a hardcoded map inside `checkpoint_manager.py`.
> 3. `_no_progress_streak` resets **only on a flip (a `success` turn)** — NOT after a
>    backstop drain (the brief is explicit: past grace, "resume draining until a flip resets it").

## Story

As the **maintainer shipping the MVP**,
I want **the patience/survival meter to measure ENGAGEMENT ("are you participating in good
faith?") instead of BEAT-PROGRESS ("did you tick a beat this turn?") — so that an engaged
learner who re-answers a circled-back beat, hits a beat that doesn't fit their path, asks for
clarification, or is just a slow B1 is NEVER punished or hung up, while a disengaged user
(off-topic, refusal, empty filler) still loses — and so the arc LENGTH stops being a death
multiplier (a 6-beat waiter and a 20-beat detective are both fair)**,
so that **a genuinely-engaged learner can complete the worst-case 20-beat Detective without
being hung up for the wrong reason, the "Survive the Talk" DNA (disengagement always loses)
is preserved, and the change ships safely (measured before it bites a real user)**.

## Context — why this story exists

The patience meter is welded to beat-advancement: the drain fires when
`advance_goals().outcome == "fail"` (no flip + ≥1 goal actively `unmet`) in
`checkpoint_manager._classify_and_flip_goals`. That branch **conflates two different things**:
a *disengaged* user (off-topic / refusal / filler) and an *engaged-but-didn't-advance-the-
pursued-beat* user. The brief's one-line problem: **the meter measures the wrong axis.**

This surfaced as the **Story 10.8 completion confound**. Two clean Pixel 9 calls on the 20-beat
Detective proved every 10.8 fix held (no mid-sentence hang-up, beat 0 credited immediately,
HUD never froze, judge zero false-negatives) — yet **both calls ended in a patience hang-up of
an engaged learner**. The 13-agent exploration that followed concluded a "solid for all
*engaged* cases" architecture **is achievable on our exact stack** — no extra LLM call, no DB
migration — by **severing survival from beat-advancement** and re-keying the drain on a
good-faith-engagement signal the existing judge call can emit (the `__user_abusive__` reserved
key proves the wiring is free). Two cases stay honest hard problems (gaming; STT word-salad
garble) — handled explicitly below, not hidden.

### The live evidence (anchor every change to the real calls)

| Call | What happened | Root surface |
|------|---------------|--------------|
| 344 | 20-beat Detective, engaged B1 learner. Conversation was good; judge accurate. The learner was **hung up at 10/20** because patience drained on every turn that didn't flip a *new* beat — including turns where the cop circled back to an already-met beat and the learner faithfully re-answered. | Patience↔beat-advancement conflation |
| 345 | Same scenario, same outcome at **8/20**. `lock_arrival_and_departure` (a two-clock-time beat) is near-**unsatisfiable** for a stay-home alibi — the learner can never advance it, so every on-topic turn spent on it drains. | Conflation + path-dependent construction (R10) |

**The headline win this story must deliver:** the drain **no longer integrates beat-non-
advancement**, so arc LENGTH stops being a death multiplier — the exact call-344/345 fix, made
structural. The HUD ("X of N beats") does not change; `survival_pct` formulas do not change
(the number on a good-faith hang-up simply **rises** — intended, more honest; see AC16).

## Acceptance Criteria

> The work splits into six streams (A–F) + a global gate. **A** (the signal) and **F**
> (golden/tests) ship FIRST and are **flag-independent** so the engagement axis can be measured
> in shadow. **B/C** (the behaviour change) are gated **OFF by default** and only flip ON after
> the Stream-E measurement. **D** (the lint) lands as a follow-up commit. **E** is the mandatory
> sequence that ties them together.

### Stream A — the `__engaged__` engagement signal (ships flag-independent; emits + logs)

1. The per-turn judge call (`exchange_classifier.classify_multi`) emits **one extra reserved
   boolean `__engaged__`**, folded into the SAME strict `json_schema` exactly like
   `__user_abusive__` (no extra LLM call). It is added to `_build_verdict_schema` properties +
   `required`, and `_MULTI_MAX_TOKENS_BASE` is bumped `96 → 112` so the extra key can't truncate
   the verdict object.
2. `__engaged__` is parsed out in `_parse_multi_classifier_output` and **defaults to `True`
   (lenient) on missing / non-bool / garbled output** — the system must **never fabricate
   disengagement**. (This is the OPPOSITE default from `ABUSE_KEY`, which defaults `False`.)
3. The judge prompt (`EXCHANGE_CLASSIFIER_MULTI_PROMPT`) gains a **good-faith-vs-disengaged
   principle** for `__engaged__`. It MUST reuse the principle-7 anti-permissive wall so
   "engaged" can NOT be claimed for empty / contentless / off-topic / refusal / filler content:
   engaged = the user is participating in good faith on the scenario (on-topic attempt, a
   clarification, a slow or partial but genuine try); disengaged = off-topic, refusal, empty
   filler, or shoving the task back with no content.
4. **The re-answer fix.** The judge receives the **already-met beats as read-only prompt
   context** (a new `{recently_met_block}`, NOT schema keys) with the rule: *"if the user
   faithfully re-answers a met objective the character circled back to, set `__engaged__: true`;
   emit no verdict key for it."* `classify_multi` gains a `met_goals` (or `recently_met`)
   parameter threaded from `checkpoint_manager`; a `_format_recently_met_block` helper builds the
   block (mirroring `_format_pending_goals_block`).
5. `checkpoint_manager._classify_and_flip_goals` **pops `__engaged__` out of the verdict dict
   before `advance_goals`** (exactly like the `ABUSE_KEY` pop at L1288), defaulting `True`, and
   **logs it every turn** alongside the outcome (e.g. `checkpoint_engagement engaged={} outcome={}
   streak={}`) so it can be measured in shadow (Stream E). **`advance_goals` and `judgeable_goals`
   stay byte-identical** (golden==prod; no call-336/337 regression).
6. **Regression guard:** with `__engaged__` now in the strict schema, the golden net **still
   passes 6/6** on the deployed judge (proves the new required field did not regress the proven
   `met`/`unmet` axis). `ENGINE_VERSION` is bumped (see AC15).

### Stream B — the de-welded drain rule (gated by `ENGAGEMENT_GATING_ENABLED`, default OFF)

7. A new boolean setting `ENGAGEMENT_GATING_ENABLED` (Pydantic `Settings`, default **`False`**)
   is threaded into `CheckpointManager` exactly like `abuse_detection_enabled`
   (`self._engagement_gating_enabled`). **When OFF: behaviour is byte-identical to today** — the
   drain stays welded to `outcome == "fail"`, `__engaged__` is still computed + logged but
   ignored for the drain decision.
8. **When ON:** in the `outcome == "fail"` branch (today's single drain site, `checkpoint_manager.py`
   ~L1308–1334), drain `fail_penalty` **only when the turn is non-advancing AND `__engaged__ == False`**
   (off-topic / refusal / empty filler). An **engaged-but-non-advancing** turn (slow build, clarify,
   faithful re-answer, path-misfit, on-topic) is **patience-NEUTRAL** — it does NOT call
   `apply_exchange_outcome(success=False)`.
9. The existing **5-consecutive-`None` infra backstop**, the Story 6.25 **fast-re-speak
   coalescing**, the **recovery** (`success=True`) path, and the **completion** path are all
   preserved unchanged. `patience_tracker.py` is **UNTOUCHED** (no meter-math change).
10. Off-topic / refusal / filler (`__engaged__ == False`, non-advancing) **still drains and still
    eventually hangs up** at the same rate as today — the DNA (disengagement always loses) is
    intact and proven by the calibration off-topic seed + the smoke gate.

### Stream C — the gaming stall-backstop (`DECISION (proposed → confirm at dev)`)

> **This stream needs Walid's explicit sign-off (brief §2, §5.2, closing reminder).** It is the
> only place non-advancement is re-coupled to an end-state. Present the recommended direction,
> get the OK, then build. If Walid declines, Stream B ships without a backstop and the
> glacial-gaming risk is named + deferred (brief §7).

11. A `_no_progress_streak` counter on `CheckpointManager` increments on every **engaged-but-non-
    advancing** turn (the Stream-B neutral case) and **resets to 0 on ANY flip** (a `success`
    turn). It does **NOT** reset on a backstop drain.
12. A per-difficulty `stall_grace_turns` preset (**easy 8 / medium 6 / hard 4**, brief §3) is
    added to `_DIFFICULTY_PRESETS`, to `_PATIENCE_OVERRIDE_KEYS` (scenario override), and given a
    validator in `resolve_patience_config` (positive int). The resolved value is **threaded into
    `CheckpointManager`** (it does not know difficulty today) — **NOT** hardcoded as a map inside
    the manager.
13. While `_no_progress_streak < stall_grace_turns` → engaged-non-advancing turns are neutral
    (Stream B). Once `_no_progress_streak >= stall_grace_turns` → **resume draining** on each
    subsequent engaged-non-advancing turn **until a flip resets the streak**. This gates the
    **ONSET** of drain (it only ever touches engaged-no-flip turns) — it is **NOT** the rejected
    grace-counter (which softened an *existing* drain on good faith).

### Stream D — R10 construction lint (`find_path_dependent_criteria`; follow-up commit)

14. A new **R10** lint `find_path_dependent_criteria(text)` in `scenarios.py` flags a
    `success_criteria` that demands a fact a **common coherent path makes non-existent** — the
    mechanically-detectable slice being **paired motion/arrival/departure clock-time demands**
    (the cop's `lock_arrival_and_departure` two-clock-times beat, unsatisfiable for a stay-home
    alibi). It is wired through the **identical three layers as R9**: builder HARD reject
    (`scenario_builder.validate_structure`), loader WARN (`load_scenario_checkpoints`), and a
    `tests/test_scenarios.py` commit glob over `_SCENARIO_INDEX` (never a hand-list). Zero false
    positives (dedicated negative tests). The **broader class** (semantically path-dependent but
    not lexically detectable) stays **builder guidance + smoke**, same posture as R3/R7/R9.
15. The seed offender (the cop `lock_arrival_and_departure` beat) is audited and reconciled so it
    loads clean (e.g. credit the genuine alibi move without demanding two specific clock times
    that a stay-home path never produces). R10 is recorded in `server/CLAUDE.md §9` as the next
    rule after R9.

### Stream E — shadow-launch rollout + measurement (MANDATORY, non-negotiable)

16. The rollout follows the brief §6 sequence and is documented in the story Completion Notes:
    **(1)** deploy with `ENGAGEMENT_GATING_ENABLED=False` — `__engaged__` is emitted + logged on
    every real call but changes nothing; **(2)** measure `__engaged__` accuracy on real calls
    (replay the 344/345 evidence + new flag-OFF live calls — see Dev Notes on the measurement
    corpus, since transcripts are not persisted per Story 7.1); **(3)** only after the
    measurement supports it, flip `ENGAGEMENT_GATING_ENABLED=True` + (if Walid approved Stream C)
    the backstop; **(4)** R10 lands as a follow-up commit; **(5)** rollback = the env flag (full
    revert = one commit). The **`survival_pct` semantic shift** (a good-faith partial now ends
    HIGHER, since fewer good-faith turns drained) is an **intended, surfaced product change** —
    call it out for Walid, do not let it ship silently.

### Stream F — calibration + golden + tests (REAL work, not free)

17. `ENGINE_VERSION` is bumped (**8 → 9**) to force a full revalidation sweep (the judge prompt,
    the new engagement signal, and the streak logic are CODE constants outside `scenario_hash`).
18. **~5 new golden fixtures** cover the engagement axis: off-topic → `engaged:false`; faithful
    re-answer → `engaged:true` / no-drain; clarification → `engaged:true`; path-misfit →
    `engaged:true`; refusal → `engaged:false` / drain; (optional) empty filler → `engaged:false`.
    The golden fixture schema is **extended to assert `__engaged__`** per case (the harness today
    only asserts `met`/`unmet`).
19. Because `_no_progress_streak` is **stateful across turns**, the calibration replay is **no
    longer a pure per-turn replay**: `calibration_engine` learns the engaged split + the streak,
    and a **dedicated streak-replay harness test** (`tests/test_calibration_engine.py`) drives a
    multi-turn run and asserts (a) engaged-non-advancing turns do NOT drain below grace, (b) the
    backstop drains past grace, (c) a flip resets the streak, (d) off-topic still drains every
    turn. Re-confirm the **off-topic learner still loses** and re-tune `stall_grace` if the sweep
    shows it bites a genuinely-engaged run.

### Global — validation + gate (all streams)

20. Server gates green: `ruff check .` + `ruff format --check .` + `pytest` (new classifier,
    checkpoint-manager, scenarios-lint, and calibration tests included). Client is **unchanged**
    (`flutter analyze` + `flutter test` run as a trivial regression check — no client edits).
21. Deployed to the VPS via the CI deploy-server path; `/health` `git_sha` matches; live golden
    `--golden-only` **6/6** on the deployed judge (incl. the new engagement fixtures asserting
    `__engaged__`); a cooperative easy sweep stays in band AND an off-topic learner does not
    complete.
22. **Pixel 9 smoke gate** (with `ENGAGEMENT_GATING_ENABLED=True`): the slow-engaged cop (20-beat
    Detective) must **HOLD** (no patience hang-up of an engaged learner); an off-topic learner
    must **LOSE fast**; (if Stream C shipped) a gaming filler-forever learner must **END after
    grace**; the 6-beat waiter still completes cleanly. Script handed to Walid at Task 7.

## Tasks / Subtasks

> **Recommended order (= the brief's safe rollout):** A + F first (the signal + the tests +
> ENGINE_VERSION), deploy **flag-OFF**, run Stream E measurement, get Walid's Stream-C decision,
> THEN flip ON (B + C), THEN R10 (D) as a follow-up commit. After the flag-OFF deploy, confirm
> on a real call that `__engaged__` logs sane values before flipping.

- [ ] **Task 1 — Stream A: the `__engaged__` signal (AC: 1–6)**
  - [ ] `exchange_classifier.py`: add `ENGAGED_KEY = "__engaged__"`; add it to `_build_verdict_schema` properties + `required` (L799–827, next to `ABUSE_KEY`); bump `_MULTI_MAX_TOKENS_BASE` 96 → 112 (L153); surface it in `_parse_multi_classifier_output` defaulting **`True`** (NOT the abuse `is True` pattern — see Dev Notes trap #1).
  - [ ] `exchange_classifier.py`: add a `met_goals` / `recently_met` param to `classify_multi` + `_classify_multi`; add `_format_recently_met_block`; thread `{recently_met_block}` into the `.format(...)` call.
  - [ ] `prompts.py`: add the `{recently_met_block}` placeholder (after the pending-goals block, ~L351) + the good-faith engagement principle (a new principle after the principle-7 wall, ~L340) + the re-answer rule. Reuse principle 7's anti-permissive language so "engaged" can't be claimed for empty content.
  - [ ] `checkpoint_manager.py::_classify_and_flip_goals`: pop `__engaged__` (default **True**) right after the `ABUSE_KEY` pop (~L1288); log it every turn; keep `advance_goals` / `judgeable_goals` byte-identical.
  - [ ] Tests: schema includes + requires `__engaged__`; parse defaults True on missing/garbled; the recently-met block renders; the manager pops + logs it; abuse + engaged coexist in one verdict.
- [ ] **Task 2 — Stream F: calibration + golden + ENGINE_VERSION (AC: 17–19)** — do this WITH Task 1 so the new field is validated before any deploy.
  - [ ] Bump `ENGINE_VERSION` 8 → 9 (`calibration_engine.py:147`).
  - [ ] Extend the golden fixture schema to assert `__engaged__`; add ~5 fixtures (off-topic/re-answer/clarify/path-misfit/refusal [+filler]).
  - [ ] Teach the replay the engaged split + the streak; add the dedicated streak-replay test in `tests/test_calibration_engine.py`.
- [ ] **Task 3 — Stream B: the de-welded drain rule, gated OFF (AC: 7–10)**
  - [ ] `config.py`: `engagement_gating_enabled: bool = False  # ENGAGEMENT_GATING_ENABLED` (mirror `abuse_detection_enabled` at L311). Thread into `CheckpointManager` ctor (mirror the abuse-flag threading from `bot.py`).
  - [ ] `checkpoint_manager.py`: refactor the `outcome == "fail"` branch (~L1308–1334) so that **when the flag is ON**, drain only when `not engaged`; engaged-non-advancing = neutral. **When OFF, today's drain is unchanged.** Keep the 5-None backstop (L1263), coalescing (L1319), recovery (L1414), completion (L1391) intact. Do NOT touch `patience_tracker.py`.
  - [ ] Tests: flag-OFF = identical drain to today (regression-lock); flag-ON + engaged-non-advancing = no drain; flag-ON + disengaged-non-advancing = drain; off-topic still hangs up.
- [ ] **Task 4 — Stream C: the gaming stall-backstop (AC: 11–13)** — **DECISION (proposed → confirm with Walid FIRST).**
  - [ ] Confirm the backstop direction + the easy 8 / med 6 / hard 4 grace with Walid.
  - [ ] `scenarios.py`: add `stall_grace_turns` to `_DIFFICULTY_PRESETS` (155–227) + `_PATIENCE_OVERRIDE_KEYS` (331–343) + a positive-int validator in `resolve_patience_config` (after ~L908). Thread the resolved value into `CheckpointManager`.
  - [ ] `checkpoint_manager.py`: add `_no_progress_streak` (init near `_consecutive_none_count` ~L578); increment on engaged-non-advancing; reset **only on a flip**; drain past grace (see Dev Notes traps #2/#3).
  - [ ] Tests: streak increments on engaged-no-flip; resets on flip (not on backstop drain); drain resumes past grace; per-difficulty grace honoured; scenario override + validator.
- [ ] **Task 5 — Stream D: R10 construction lint (AC: 14–15)** — follow-up commit.
  - [ ] `scenarios.py`: `find_path_dependent_criteria` mirroring R9 (`find_unsatisfiable_criteria`, L562–580) + a `_R10_*_PATTERNS` tuple for paired motion/arrival/departure clock-time demands. Wire builder reject + loader warn + `_SCENARIO_INDEX` test glob + 2 unit tests (positive + zero-false-positive).
  - [ ] Audit the cop `lock_arrival_and_departure` beat; reconcile it so it loads clean. Record R10 in `server/CLAUDE.md §9`.
- [ ] **Task 6 — Stream E: shadow rollout + measurement (AC: 16)**
  - [ ] Deploy flag-OFF; confirm `__engaged__` logs on a live call; measure on the 344/345 evidence + new flag-OFF calls; report the measurement to Walid; flip ON only after it supports the axis; surface the `survival_pct` semantic shift.
- [ ] **Task 7 — Global: validate + gate (AC: 20–22)** — gates green, deploy, live golden 6/6 + band, Pixel 9 smoke (flag ON) on the 20-beat Detective + the off-topic + 6-beat waiter.

## Interactions — verify these overlaps BEFORE building (binding)

1. **The flag boundary is the whole safety story.** Stream A (schema, prompt, parse, pop, log)
   and Stream F (golden, tests, `ENGINE_VERSION`) ship **regardless of the flag** so the
   engagement axis is measurable in shadow. Only the **drain decision** (B) and the **backstop**
   (C) are gated. Do NOT gate the signal itself — if the signal is gated OFF too, there is
   nothing to measure and Stream E is impossible.
2. **Do NOT re-fight Story 10.8's Stream C.** 10.8 deliberately REJECTED softening the
   patience↔judge coupling (it would dilute the DNA) and instead hardened judge *reliability* so
   a false-negative spiral never starts. **10.9 is different and complementary:** it does not
   soften the drain on a genuine miss — it removes beat-non-advancement from the drain entirely
   for *engaged* turns. A confident-but-wrong `unmet` on an engaged turn is now covered too (it's
   engaged → neutral), but that is a *consequence*, not the goal. Keep 10.8's judge-reliability
   work; build on it.
3. **`advance_goals` / `judgeable_goals` must stay byte-identical** (golden==prod, Story 6.15 /
   6.23). All 10.9 logic lives in `_classify_and_flip_goals` (the pop + the gated branch) and in
   `exchange_classifier` (the new key) — never in the pure decision functions. The crediting
   stays any-order; the HUD/steering are untouched.
4. **The re-answer fix (A4) influences `__engaged__`, not `met`/`unmet`.** Met beats are not in
   `pending_goals`, so the judge "emits no verdict key for them" — the `recently_met_block` only
   raises `__engaged__` for a faithful re-answer. It must NOT cause a met beat to be re-judged or
   a pending beat to flip on a re-answer. Verify the golden net is unchanged by the block in
   shadow (AC6).
5. **R10 (D) is build-time; the engagement split (B) is runtime.** R10 stops the *badgering* at
   build (an unsatisfiable beat never ships); the engagement split stops the *drain* at runtime.
   They are independent — R10 can land before or after the flip. Both target the same call-345
   `lock_arrival_and_departure` symptom from different ends.

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** included — server pipeline changes (judge call, checkpoint-manager drain,
> scenarios presets + a new lint, calibration) + a VPS deploy. **No new DB migration** (the
> engagement + streak state is in-memory: the checkpoint goals dict + the patience meter). Mark
> the migration/backup boxes N/A.
>
> **Transition rule:** every unchecked box is a stop-ship for `in-progress → review`. Paste the
> actual command + output as proof.

- [ ] **Deployed to VPS.** `GET https://api.survivethetalk.com/health` `git_sha` matches the
      commit under test; the CI deploy-server run was green.
  - _Proof:_ <!-- /health JSON + CI run id -->

- [ ] **Golden net not regressed + engagement fixtures pass.**
      `python scripts/calibrate_scenario.py --golden-only` → **6/6 PASS** on the deployed judge,
      AND the new engagement fixtures assert `__engaged__` correctly (off-topic→false,
      re-answer→true, clarify→true, path-misfit→true, refusal→false).
  - _Command:_ `cd server && python scripts/calibrate_scenario.py --golden-only` (on the VPS, live gpt-4.1-mini)
  - _Expected:_ `=== 6/6 passed ===` (0 cached after the ENGINE_VERSION 8→9 bump) + engagement assertions green
  - _Actual:_ <!-- paste -->

- [ ] **Calibration band holds (DNA intact + engaged learner survives).** A cooperative easy
      sweep stays in band; an **off-topic** learner does NOT complete (still drains every turn);
      a slow-engaged cop sweep does NOT hang up below `stall_grace`.
  - _Command:_ `cd server && python scripts/calibrate_scenario.py cop_interrogation_01` (+ the off-topic seed)
  - _Actual:_ <!-- paste survival %, hang-up reason -->

- [ ] **DB migration / backup — N/A** (no schema change — engagement + streak state is in-memory).

- [ ] **Server logs clean on deploy/boot + `__engaged__` emitted in shadow.** `systemctl is-active
      pipecat.service` → `active`; `journalctl -u pipecat.service` shows the new
      `checkpoint_engagement` line on a real call and no ERROR/Traceback; with the flag OFF, the
      drain behaviour is unchanged.
  - _Proof:_ <!-- paste -->

- [ ] **Pixel 9 on-device smoke gate (flag ON) — the 20-beat Detective + off-topic + 6-beat
      waiter.** (Script handed to Walid at Task 7.)
  - **Engaged-survives:** play the 20-beat Detective as a cooperative-but-slow B1 (re-answer when
    the cop circles back, take a clarification) → the cop **does NOT hang up** for impatience; the
    learner can keep going / complete.
  - **Disengaged-loses:** go off-topic / refuse / filler → patience drains and the character hangs
    up at roughly the same pace as today (DNA intact).
  - **(If Stream C shipped) Gaming-ends:** engaged-looking filler forever → after `stall_grace`
    turns with no flip, patience resumes draining → eventual hang-up.
  - **Short scenario fair:** the 6-beat waiter still completes cleanly for an engaged learner.
  - _Result:_ <!-- Walid -->

## Dev Notes

### Read first
- [`survival-decoupling-design-brief.md`](_bmad-output/implementation-artifacts/survival-decoupling-design-brief.md)
  §1–7 — the problem, the verdict on feasibility (§2 — honest about gaming + STT garble), the
  recommended hybrid architecture (§3), the 12-case synthesis (§4), the trade-offs (§5), the
  per-file scope (§6), and what's explicitly out (§7). **This story IS §6 turned into ACs.**
- [`10-8` story](_bmad-output/implementation-artifacts/10-8-character-rail-keeper-arc-ordering-and-hud-sync.md)
  — the immediate predecessor; shares every seam. Its Stream C (judge-reliability, NOT
  patience-softening) is the thing 10.9 must not re-fight (Interaction #2).
- `server/CLAUDE.md` §4 (judge strict `json_schema` law — the new `__engaged__` key keeps the
  schema strict), §8 (difficulty-neutral personas — `stall_grace` is a difficulty *preset*, the
  same family as `fail_penalty`, never baked into a persona), §9 (R1–R9 + the three-layer
  fail-fast enforcement + "THE DURABLE LESSON" = always glob `_SCENARIO_INDEX`, never hand-list —
  add R10 here).

### ⚠️ The three dev traps (do NOT copy the obvious-but-wrong pattern)

1. **`__engaged__` defaults `True`, not `False`.** `ABUSE_KEY` parses as
   `verdicts[ABUSE_KEY] = data.get(ABUSE_KEY) is True` (`exchange_classifier.py:933`) and pops as
   `verdicts.pop(ABUSE_KEY, False)` (`checkpoint_manager.py:1288`) — **conservative: a wrong
   `True` ends a call, so default `False`.** `__engaged__` is the MIRROR IMAGE: a wrong `False`
   would *drain* a good-faith learner, so it must **default `True`** at BOTH layers
   (`data.get(ENGAGED_KEY)` → `True` unless it is explicitly `False`; `verdicts.pop(ENGAGED_KEY,
   True)`). Brief §3: "missing/garbled parse → `True` = lenient, never fabricate disengagement."
2. **`stall_grace_turns` is a per-difficulty PRESET, not a hardcoded map.** The manager does not
   know difficulty today. Add `stall_grace_turns` to `_DIFFICULTY_PRESETS` (easy 8 / med 6 /
   hard 4), `_PATIENCE_OVERRIDE_KEYS`, and a validator in `resolve_patience_config` — then
   **thread the resolved int into `CheckpointManager`** (a new ctor param, the same way
   `fail_penalty` reaches `PatienceTracker`). Do NOT write `{"easy":3,...}` inside
   `checkpoint_manager.py` (it would bypass the override + validator + the §8 difficulty contract).
3. **`_no_progress_streak` resets only on a flip.** Brief §3: past grace, "resume draining until
   a **flip** resets it." So increment on each engaged-non-advancing turn; reset to 0 **only** in
   the `outcome == "success"` branch (the flip). Do **not** reset it after a backstop drain (that
   would let a gamer re-earn the full grace every `grace+1` turns → glacial gaming).

### Stream A — exact seams (`exchange_classifier.py` + `prompts.py`)
- `ABUSE_KEY = "__user_abusive__"` (`exchange_classifier.py:135`) is the precedent for
  `ENGAGED_KEY = "__engaged__"`. `_build_verdict_schema` (L799–827) builds per-goal enum props +
  `properties[ABUSE_KEY] = {"type": "boolean"}` (L821) + `required = list(goal_ids) + [ABUSE_KEY]`
  (L825) — add `__engaged__` to both, exactly there.
- `_MULTI_MAX_TOKENS_BASE = 96` (L153); `_multi_max_tokens(n) = base + 24*max(1,n)` (L157). Bump
  base to **112** (the brief's `96→~112`) so the extra `"__engaged__": false` (~12 tokens) can't
  truncate the object under strict decoding.
- `_parse_multi_classifier_output` (L860–934): per-goal map at L923–928; `ABUSE_KEY` surfaced at
  L933. Add `verdicts[ENGAGED_KEY] = data.get(ENGAGED_KEY) is not False` (or explicit: `raw =
  data.get(ENGAGED_KEY); verdicts[ENGAGED_KEY] = raw if isinstance(raw, bool) else True`).
- `classify_multi` (L436–522) → `_classify_multi` (L711–757): the `.format(...)` (L719–730) wires
  `pending_goals_block=_format_pending_goals_block(...)`. There is **no met-beats placeholder
  today** — add `met_goals`/`recently_met` to the signature + a `_format_recently_met_block`
  helper (mirror `_format_pending_goals_block`, L830–845) + a `{recently_met_block}` arg.
- `EXCHANGE_CLASSIFIER_MULTI_PROMPT` (`prompts.py:286–382`): principle 7 = the anti-permissive
  wall (L323–340); the `{pending_goals_block}` placeholder is at L351. Insert the new engagement
  principle after L340 and the `{recently_met_block}` after L351. **Preserve all 10.7/10.8 prompt
  content** (principle 2 polite-question, principle 7 wall) — extend, don't rewrite.
- The Story 10.8 transient-timeout retry (`_last_failure_was_timeout` + the bounded retry in
  `classify_multi`, L498–519) and the cold-start retry (L481–497) are **untouched** — the new key
  rides the same payload.

### Stream B/C — exact seams (`checkpoint_manager.py` + `config.py` + `scenarios.py`)
- THE DRAIN: `checkpoint_manager.py:1334` — `self._patience_tracker.apply_exchange_outcome(success=False)`,
  inside the `if advance.outcome == "fail":` branch (L1308). `advance_goals` (L375–440) sets
  `outcome="fail"` when no flip AND ≥1 verdict is `False` (L428–433). The `ABUSE_KEY` pop is at
  L1288; pop `__engaged__` right after it.
- The three outcome branches: **fail** (L1308–1335, the drain + the 6.25 coalesce return at
  L1319), **neutral** (L1337–1350, all-`None` → patience unchanged), **success** (L1352–1414,
  recovery `apply_exchange_outcome(success=True)` at L1414, completion `schedule_completion` at
  L1391, `self._goals = advance.new_goals` at L1356 — the flip = where `_no_progress_streak`
  resets). The 5-`None` force-drain backstop is ~L1263.
- State init is in `__init__` (~L480–642); existing counters `_consecutive_none_count` (~L578) and
  `_last_outcome_was_fail` (~L596) are the neighbours for `_no_progress_streak`. `self._goals` is
  `dict[str,str]` ("pending"/"met"); `pending_goals` property at L653–657 (invert it for
  `met_goals` to feed the recently-met block).
- The flag precedent: `abuse_detection_enabled: bool = True  # ABUSE_DETECTION_ENABLED`
  (`config.py:311`) → `CheckpointManager` reads it as `self._abuse_detection_enabled` (used at the
  abuse branch ~L1289). Add `engagement_gating_enabled: bool = False  # ENGAGEMENT_GATING_ENABLED`
  the same way and thread it identically. Pydantic `BaseSettings` parses the env bool automatically
  (no validator needed).
- `_DIFFICULTY_PRESETS` (`scenarios.py:155–227`, easy `fail_penalty:-9` / med `-20` / hard `-25`);
  `_PATIENCE_OVERRIDE_KEYS` (L331–343); the YAML-alias + validation in `resolve_patience_config`
  (L663–910, the per-field `isinstance(... ) and not bool` + sign checks — copy that exact shape
  for `stall_grace_turns` as a positive int). No YAML alias for `stall_grace_turns` (code key =
  YAML key). Add a nullable `stall_grace_turns: null` to each scenario `metadata` block.

### Stream D — exact seams (the R10 lint)
- Mirror **R9** `find_unsatisfiable_criteria` (`scenarios.py:562–580`) + its `_UNSATISFIABLE_CRITERIA_PATTERNS`
  tuple (L554–559). The three wiring sites to copy verbatim: builder reject
  (`scripts/scenario_builder.py:814–827`), loader warn (`scenarios.py:972–990`), commit glob
  (`tests/test_scenarios.py:2069–2094`, iterating `_SCENARIO_INDEX`) + the two unit tests
  (L2007–2066). R8 (`find_permissive_criteria_phrases`, L516–533) is the same pattern if you want
  a second reference.
- R10's regex is a genuine design choice: target the **paired clock-time** slice (e.g. a single
  criterion demanding BOTH an arrival time AND a departure time). Tune for **zero false positives**
  (a single time, or a relative time, is fine) — the broader semantic class stays builder guidance
  (brief §3, §7), exactly like R9's "broader same-moment class stays guidance + smoke" caveat.
- Scan ONLY `success_criteria` (the judge-facing field) — the same words in a `prompt_segment` /
  `briefing` / persona are harmless.

### Stream F — exact seams (calibration + golden)
- `ENGINE_VERSION = 8` (`calibration_engine.py:147`) → **9**. `is_cached_pass` (L1477–1490)
  invalidates the ledger on a version mismatch, forcing a full re-judge (the engagement signal +
  streak are code constants outside `scenario_hash`).
- Golden fixtures live in `tests/fixtures/golden/*.json`; schema = `{scenario_id, engine_version,
  reviewed, cases:[{checkpoint_id, kind: positive|negative, character_line, user_text, note}]}`.
  Today each case asserts the goal verdict (`met`/`unmet`); **extend the schema** with an
  engagement assertion (e.g. `expect_engaged: true|false`) and teach `run_golden` to check it.
  Gate: positives (`reviewed:true`) ≥90% `True`, negatives `False`.
- The replay (`simulate_conversation`) is **stateless per-turn today** (the meter is initialized
  once and stepped per verdict). `_no_progress_streak` makes it stateful → add the dedicated
  multi-turn streak-replay test (brief §5.5: this is REAL calibration work, not free — budget a
  paid live sweep + a `stall_grace` re-tune).

### Constraints / what must NOT be broken
- **`patience_tracker.py` is UNTOUCHED** (brief §3 — "change WHAT drains, not the meter math").
  No change to `fail_penalty`, `step_patience`, the silence ladder, or the escalation thresholds.
- **`advance_goals` / `judgeable_goals` byte-identical** (golden==prod, §6/§7 of `server/CLAUDE.md`).
- **HUD + `survival_pct` formulas unchanged.** The HUD still shows "X of N beats"; the survival
  number simply rises on a good-faith hang-up (AC16 — intended, surfaced).
- **Strict judge `json_schema`** (§4) — `__engaged__` is a `required` boolean inside the same
  strict schema; do not add an out-of-schema field.
- **The 10.8 retries** (`_last_failure_was_timeout` bounded retry, cold-start retry) and the
  **5-`None` backstop** stay intact.
- **No DB migration** — engagement + streak are in-memory; do not add a migration (the
  `tests/test_migrations.py` prod-snapshot replay must stay green with zero new files).
- **Difficulty-neutral law (§8):** `stall_grace_turns` is a difficulty *preset/override*, never a
  persona behaviour.

### Out of scope / deferred (brief §7 — do NOT pull in)
- A second meter / any client change / a character-authority survival float (rejected
  architectures B and C in the brief).
- An `objective_group` HUD rollup.
- STT word-salad-garble + the 8s force-finalize truncation (orthogonal STT-confidence work).
- Glacial-but-nonzero gaming (refill-on-any-flip) — named + deferred; the cure (a wall-clock
  term) is only worth it if it ever bites.
- `fail_penalty` re-hardening (propose separately once good faith is exempt — the −9 easy was a
  10.8 stop-gap on the OLD coupling).
- Debrief engagement-narrative polish.

## Project Structure Notes
- **Server-only.** Files: `pipeline/exchange_classifier.py`, `pipeline/prompts.py`,
  `pipeline/checkpoint_manager.py`, `pipeline/scenarios.py` (+ each scenario YAML's `metadata` for
  the nullable `stall_grace_turns`), `scripts/scenario_builder.py`, `scripts/calibration_engine.py`,
  `config.py`, `server/CLAUDE.md` (§9 R10), `tests/*` (classifier, checkpoint-manager, scenarios,
  calibration). Deploys via the normal CI deploy-server path. **No new migration.**
- **Client: zero change.** The HUD, the survival % rendering, the debrief — all unchanged.
  `flutter analyze` + `flutter test` run as a no-op regression check.
- Validation = `calibrate_scenario.py` (golden + band, the prod-equivalent text harness) + pytest
  (incl. the new streak-replay) + the Pixel 9 smoke gate (the only thing Walid runs).

## References
- [survival-decoupling-design-brief.md §1–7](_bmad-output/implementation-artifacts/survival-decoupling-design-brief.md) — the binding source.
- [10-8 story (predecessor; the carve-out origin; the judge-reliability work not to re-fight)](_bmad-output/implementation-artifacts/10-8-character-rail-keeper-arc-ordering-and-hud-sync.md)
- [10-7 story (judge permissiveness + progressive debrief this builds on)](_bmad-output/implementation-artifacts/10-7-fix-checkpoint-conversation-sync-and-judge-accuracy.md)
- [server/CLAUDE.md §4 judge law, §8 difficulty-neutral, §9 R1–R9 + durable lesson](server/CLAUDE.md)
- Stream A: `server/pipeline/exchange_classifier.py`, `server/pipeline/prompts.py`.
- Stream B/C: `server/pipeline/checkpoint_manager.py`, `server/config.py`, `server/pipeline/scenarios.py`.
- Stream D: `server/pipeline/scenarios.py`, `server/scripts/scenario_builder.py`, `server/tests/test_scenarios.py`, the cop scenario YAML.
- Stream F: `server/scripts/calibration_engine.py`, `server/scripts/calibrate_scenario.py`, `server/tests/fixtures/golden/`, `server/tests/test_calibration_engine.py`.

## Dev Agent Record

### Agent Model Used

### Debug Log References

### Completion Notes List

### File List
