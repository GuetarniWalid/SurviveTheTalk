# Story 10.7: Tighten judge accuracy + raise the debrief budget (unblock the 10.6 smoke gate)

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

> **SCOPE NOTE — read first.** The sprint-status key for this story is
> `10-7-fix-checkpoint-conversation-sync-and-judge-accuracy` (a stable PK from when
> 10-7 was the whole "rail-keeper" brief). **This story is DELIBERATELY NARROWED**
> to the TWO device blockers confirmed on the Pixel 9 smoke gate of Story 10.6
> (call 340, OpenAI `gpt-4.1-mini`, deployed `a82cbb4`) — the only things standing
> between 10.6 and `done`:
>
> - **Bug B (small, do FIRST):** the post-call debrief times out and the user only
>   ever sees the degraded score-only recap.
> - **Bug A (the big part):** the judge credits weak / off-topic / nonsensical input
>   because the scenario `success_criteria` are authored too permissively, so a
>   scenario "plays itself."
>
> **The wider "rail-keeper" redesign is OUT of scope** (HUD stale-instruction sync,
> arc-ordering character conduct, the patience↔judge false-negative decoupling).
> That body of work is the original 10-7 description and stays in the brief §1–9; it
> is carved out to a NEW backlog stub `10-8-character-rail-keeper-arc-ordering-and-hud-sync`
> so it is not lost. It does NOT block 10.6. See **Dev Notes → Scope boundary**.
>
> **Decision (story vs epic):** this is ONE story, not an epic. Bug A and Bug B are
> bounded, share a single Pixel 9 re-smoke, and Bug A is a single coherent surface
> (one judge prompt + the `success_criteria` of 6 scenarios + one lint + one golden
> re-validation). An epic would only be warranted for the full rail-keeper redesign,
> which is explicitly deferred.

## Story

As the **maintainer shipping the MVP**,
I want **the debrief to always produce a real recap, and the checkpoint judge to
credit a beat ONLY when the learner genuinely accomplishes it**,
so that **Story 10.6 (the Scout→gpt-4.1-mini migration that MUST ship before Groq
decommissions Scout on 2026-07-17) finally passes its Pixel 9 smoke gate and flips
to `done`**.

## Context — why this story exists

Story 10.6 migrated all three LLM roles onto OpenAI `gpt-4.1-mini`. The migration
**code is correct and deployed** (`a82cbb4`). But the Pixel 9 smoke gate (call 340)
failed on two pre-existing, model-agnostic defects that the precise gpt-4.1 model
exposed (older models masked them by being noisier / less literal). Neither was
introduced by the 10.6 review patches (verified). They sent 10.6 back to
`in-progress`. This story clears both so the reviewer can flip 10.6 → `done`.

The authoritative problem framing lives in
`checkpoint-arc-rail-keeper-design-brief.md` — **read its `ADDENDUM (2026-06-29)`
(§A and §B) before coding**; this story implements exactly that addendum.

### Bug A evidence (waiter_easy_01, call 340) — the judge credits anything

| user turn | checkpoint credited | correct? |
|---|---|---|
| "Hi, good evening." | greet | ✅ |
| "I have the grilled chicken, please." | main_course **+ clarify (same turn)** | main ✅ / clarify ⚠️ premature |
| "a cola, please." | drink | ✅ |
| **"No other choice."** | **confirm** | ❌ not a confirmation |
| **"No other choice. Is it a question?"** | **close** | ❌ closes nothing |

Walid: *"c'est comme si il y avait rien, pas de scénario, je pouvais dire n'importe
quoi, ça se déroule tout seul."* Root cause = the criteria literally say "accept
anything": `confirm.success_criteria` → *"Any acknowledgement of the order summary
counts"*; `close.success_criteria` → *"Even a simple 'okay' or 'thanks' counts."*
gpt-4.1-mini obeys them literally. This is the design misconception
`server/CLAUDE.md §8` warns about: "easy" was conflated with "accept anything."
**Easy difficulty must forgive the learner's LANGUAGE/grammar, NOT credit wrong or
absent content.** A confused / evasive / tangential / question-back reply must be
`unmet` at every difficulty.

### Bug B evidence (call 340) — the debrief never produces a real recap

```
11:47:33  call_ended call_id=340 reason=survived
11:47:45  debrief_generation failed (non-fatal): (ReadTimeout)
11:47:45  generation returned None → storing a degraded (score-only) debrief
11:47:46  GET /debriefs/340 → 200 OK     (client gets the degraded one)
```

The full ~2–3k-token structured debrief takes LONGER than the debrief's
`_HTTP_TIMEOUT_SECONDS = 7.5 s` / `_GENERATION_TIMEOUT_SECONDS = 14 s` on
gpt-4.1-mini. Those budgets were sized for the old model and never raised in the
swap. The debrief is overlay-masked / non-blocking (Story 7.1), so raising them is
safe.

## Acceptance Criteria

**Bug B — debrief budget (do this first; Walid will eyeball a real recap immediately)**

1. The post-call debrief budgets in `server/pipeline/debrief_generator.py` are
   raised so a normal gpt-4.1-mini debrief completes instead of timing out:
   `_HTTP_TIMEOUT_SECONDS` 7.5 → ~20 s and `_GENERATION_TIMEOUT_SECONDS` 14 → ~25 s
   (inner HTTP budget stays strictly BELOW the outer wall-clock budget, so httpx
   aborts a hung attempt with a clean HTTP error before the opaque
   `asyncio.TimeoutError`; preserve that ordering, and the non-strict-retry headroom
   the existing comment describes).
2. The server's outer debrief budget finishes UNDER the client's give-up window so
   the user never sees a premature "Debrief unavailable". The client window is the
   Call-Ended overlay hard cap (`call_ended_screen.dart` `kMaxHold = 10 s`, which
   then hands off to) the debrief screen resume-poll (`debrief_screen.dart`
   `kPollBudget = 30 s`, `kPollInterval = 1 s`). **Verify the math** (server ~25 s <
   the 30 s screen poll). Only change a client budget if the math does NOT hold; if
   you do, run the Flutter gates and justify it. Default expectation: **server-only
   change, client verified-not-modified**.
3. The real gpt-4.1-mini debrief latency is MEASURED on the VPS
   (`server/scripts/probe_debrief_schema.py` times one live call against
   `Settings.debrief_model`). If it is routinely > 20 s, ALSO trim the debrief size
   or revisit `_MAX_TOKENS` / the model for this role. Confirm
   `finish_reason != "length"` after any change (a truncated doc fails strict parse
   and would still degrade).
4. A real on-device call (the re-smoke) shows a FULL, non-degraded recap and the
   server logs `debrief stored … inserted=True` (NOT `ReadTimeout` → degraded).

**Bug A — judge accuracy via prompt + criteria + a fail-fast lint**

5. `EXCHANGE_CLASSIFIER_MULTI_PROMPT` (`server/pipeline/prompts.py`) is STIFFENED so
   the generic judge behavior credits a beat ONLY when the user GENUINELY
   accomplishes that specific goal. A non-committal / off-topic / "I don't know" /
   question-back / contentless reply is `unmet`, **even if a scenario's own criteria
   text is loosely worded**. (The prompt already has good "Default to UNMET" / "do
   not credit just because the user engaged" principles — sharpen them and add an
   explicit rule that a criterion phrase like "any X counts" does NOT license
   crediting empty/evasive/wrong content; the user must perform the actual move.)
   This is the single highest-leverage lever — one prompt, all scenarios, any model.
6. The over-permissive `success_criteria` are rewritten across **ALL 6 shipped
   scenarios** to purge blanket-permissive license ("any … counts", "even a simple
   … counts", "any acknowledgement … counts", "any coherent … counts", "either way
   — pass it"). Each criterion states what GENUINELY satisfies the beat AND
   explicitly excludes the non-committal / off-topic / evasive reply (the landlord's
   existing "X counts; doing-nothing does NOT count" pattern is the model to
   propagate). See **Dev Notes → Bug A: the criteria to rewrite** for the per-file
   list.
7. **No over-correction into too-strict** (the §3c false-negative pole — the
   opposite, equally-bad failure where a clearly-engaged turn is wrongly `unmet`,
   which then drains patience and spirals the call). The criteria must still forgive
   B1 messy English, synonyms / brand names, fragments, and re-statements of prior
   turns. This is validated by the calibration band in AC10, not just the golden net.
8. A NEW fail-fast lint flags over-permissive criteria mechanically, mirroring the
   R1/R2 three-layer enforcement in `server/pipeline/scenarios.py`
   (`find_model_specific_tokens` / `find_scripting_violations`): a single
   source-of-truth helper (e.g. `find_permissive_criteria_phrases`) is (a) rejected
   HARD by `scenario_builder.validate_structure`, (b) WARNED by the loader, and (c)
   asserted over the FULL `_SCENARIO_INDEX` glob (NEVER a hand-list) by a new
   `tests/test_scenarios.py` lint that fails the commit. It targets the blanket
   "accept anything" idioms WITHOUT false-positiving on legitimate lenient prose
   (synonym lists, "B1 messy English counts"). Write the rewritten criteria FIRST,
   then add the lint so it passes on the cleaned scenarios. Record the new rule as
   **R8** in `server/CLAUDE.md §9`.

**Validation + gate (both bugs)**

9. `python scripts/calibrate_scenario.py --golden-only` returns **6/6 PASS** — the
   universal off-topic seed is `unmet` on EVERY beat of EVERY scenario (this is the
   permanent "judge passes everything" assertion). The 10.6 D1 sweep was 3/6 with
   the 3 fails being permissive opening beats (cop_hard_01, girlfriend_medium_01,
   mugger_medium_01); those must now pass.
10. A cooperative-learner calibration sweep
    (`python scripts/calibrate_scenario.py <id>`, default `--difficulty easy`) still
    lands each scenario's completion rate in the easy band (60–80, ±5 = ⚠️ warning,
    still passes) — proving AC7 (no over-correction). `ENGINE_VERSION` is bumped in
    `calibration_engine.py` if the rules changed, so the next sweep re-validates
    everything.
11. All automated gates green: `ruff check .` + `ruff format --check .` +
    `pytest` (incl. the new lint test, `test_scenarios.py`, and `test_migrations.py`).
    Flutter gates only if a client file changed.
12. Deployed to the VPS and the Pixel 9 re-smoke PASSES on the worst-observed cases:
    (a) a real call where saying "No other choice." to the confirm/close beats is
    correctly NOT credited (the scenario does not "play itself"), and (b) a real call
    that produces a full non-degraded debrief recap. This is the gate that flips
    BOTH 10.7 and 10.6 to `done`.

## Tasks / Subtasks

- [ ] **Task 1 — Bug B: raise the debrief budget (AC: 1, 2, 3)** — do this first.
  - [ ] In `server/pipeline/debrief_generator.py`, raise `_HTTP_TIMEOUT_SECONDS`
        7.5 → ~20 and `_GENERATION_TIMEOUT_SECONDS` 14 → ~25; update the surrounding
        comment (lines ~52–60) to reflect gpt-4.1-mini sizing (drop the stale
        "~2-3 s happy path / AC10 <5 s" framing — it was the old-model budget).
  - [ ] Verify the client give-up window covers it: overlay `kMaxHold = 10 s`
        (`call_ended_screen.dart:134`) → debrief screen `kPollBudget = 30 s`
        (`debrief_screen.dart:223`). Confirm server outer (~25 s) < 30 s screen poll.
        Do NOT change the client unless the math fails; if changed, run Flutter gates.
  - [ ] Measure one real debrief on the VPS with `probe_debrief_schema.py`; record
        the latency + `finish_reason` in the Dev Agent Record. If > 20 s, trim size /
        revisit `_MAX_TOKENS` and re-measure.
- [ ] **Task 2 — Bug A: stiffen the judge prompt (AC: 5)**
  - [ ] Sharpen `EXCHANGE_CLASSIFIER_MULTI_PROMPT` in `server/pipeline/prompts.py`
        so genuine-accomplishment-only is unambiguous and a loosely-worded criterion
        cannot license crediting empty/evasive/wrong content. Keep the abuse-check
        section (R5) and the INTENT-not-surface-form leniency (R-friendly to B1)
        intact — sharpen strictness on *content*, not on *language*.
- [ ] **Task 3 — Bug A: rewrite the over-permissive `success_criteria` (AC: 6, 7)**
  - [ ] Edit `success_criteria` in all 6 scenario YAMLs (see Dev Notes for the exact
        offenders). Purge blanket-permissive license; require the actual move; keep
        synonym / re-statement / messy-English leniency. Touch ONLY `success_criteria`
        (and only where over-permissive) — do not rewrite `prompt_segment`s or
        personas (that is the rail-keeper story).
- [ ] **Task 4 — Bug A: add the permissiveness lint (R8) (AC: 8)**
  - [ ] Add `find_permissive_criteria_phrases` (single source of truth) in
        `server/pipeline/scenarios.py`; wire it into `scenario_builder.validate_structure`
        (HARD reject), the loader (WARN), and a new `tests/test_scenarios.py` lint over
        the `_SCENARIO_INDEX` glob (commit fail). Tune patterns to flag the known
        offenders with ZERO false-positives on the cleaned criteria.
  - [ ] Document R8 in `server/CLAUDE.md §9` (rule + three-layer enforcement note).
- [ ] **Task 5 — Re-validate (AC: 9, 10, 11)**
  - [ ] `calibrate_scenario.py --golden-only` → 6/6. Bump `ENGINE_VERSION` if rules
        changed; per-scenario cooperative sweep stays in the easy band.
  - [ ] Run the full server pre-commit gate (ruff check + ruff format + pytest).
- [ ] **Task 6 — Deploy + smoke gate (AC: 4, 12)**
  - [ ] Commit per stage, deploy to the VPS, fill the Smoke Test Gate boxes below,
        then hand Walid a ready-to-play Pixel 9 script (see Dev Notes → Smoke script).

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** included — this story changes server code (judge prompt, debrief
> timeouts, scenario loaders/criteria, a lint) and requires a VPS deploy. **No DB
> migration** → the migration/backup boxes are N/A (one-line rationale each).
>
> **Transition rule:** every unchecked box is a stop-ship for `in-progress → review`.
> Paste the actual command + output as proof.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)`
      on the commit SHA under test (and `/health` `git_sha` matches HEAD).
  - _Proof:_ <!-- paste Active/Main PID + /health git_sha -->

- [ ] **Judge no longer credits weak input (the headline Bug A check).** On the VPS,
      `python scripts/calibrate_scenario.py --golden-only` → **6/6 PASS** (off-topic
      seed `unmet` on every beat, every scenario).
  - _Command:_ `cd /opt/survive-the-talk/repo/server && .venv/bin/python scripts/calibrate_scenario.py --golden-only`
  - _Expected:_ 6/6 PASS (cop_hard_01 / girlfriend_medium_01 / mugger_medium_01 now pass)
  - _Actual:_ <!-- paste summary -->

- [ ] **Debrief produces a REAL recap (the headline Bug B check).** A real on-device
      call ends → server log shows a full debrief stored, NOT a ReadTimeout/degraded.
  - _Command:_ `journalctl -u pipecat.service --since "5 min ago" | grep -E "debrief"`
  - _Expected:_ `debrief stored … inserted=True` (no `ReadTimeout`, no "storing a degraded")
  - _Actual:_ <!-- paste -->

- [ ] **Debrief latency measured under budget.** `probe_debrief_schema.py` on the VPS
      times one live gpt-4.1-mini debrief; latency < 20 s, `finish_reason != "length"`.
  - _Command:_ `cd /opt/survive-the-talk/repo/server && .venv/bin/python scripts/probe_debrief_schema.py`
  - _Actual:_ <!-- paste exit code + latency + finish_reason -->

- [ ] **DB side-effect** — N/A. This story writes no new rows and adds no migration
      (the debrief still stores via the existing Story 7.1 path; only its budget changed).

- [ ] **DB backup before deploy** — N/A. No schema change / migration.

- [ ] **Server logs clean on the happy path.** `journalctl -u pipecat.service -n 80
      --since "5 min ago"` shows no ERROR / Traceback around the call + debrief.
  - _Proof:_ <!-- paste tail or "no errors in window" + timestamp -->

- [ ] **Pixel 9 on-device gate (the real acceptance — Walid).** A live call where
      "No other choice." does NOT credit confirm/close (scenario does not auto-complete)
      AND the debrief screen shows a full non-degraded recap. **This is also the 10.6
      gate** — clearing it lets the reviewer flip BOTH 10.7 and 10.6 → `done`.
  - _Proof:_ <!-- Walid sign-off + call_id + agent log/DB verification -->

## Dev Notes

### Order of work (Walid's explicit instruction)
Do **Bug B first** (Task 1 — two constants + a measurement + a verification; Walid
wants to eyeball a real recap immediately), **then Bug A** (Tasks 2–5 — the bigger
judge/criteria/lint body). They share one deploy + one Pixel 9 re-smoke.

### Bug B — exact constants and the client give-up math
- Server: `server/pipeline/debrief_generator.py`
  - `_GENERATION_TIMEOUT_SECONDS = 14.0` (line ~59) → ~25 (outer wall-clock; masked
    by the Story 7.2 Call-Ended overlay, so non-blocking).
  - `_HTTP_TIMEOUT_SECONDS = 7.5` (line ~60) → ~20 (inner per-attempt; MUST stay <
    the outer so httpx aborts first with a clean HTTP error — preserve this ordering
    AND the headroom the comment describes for the rare non-strict json_object retry
    on a strict-schema 400).
  - `_MAX_TOKENS = 4096` (line ~72) — already generous; only revisit if AC3 measures
    a truncation (`finish_reason == "length"`).
- Client give-up window (verify, likely no change):
  - `client/lib/features/call/views/call_ended_screen.dart` — `kMaxHold = Duration(seconds: 10)`
    (line ~134): the overlay polls `GET /debriefs/{id}` (1 s) but HARD-CAPS the hold
    at 10 s, then exits handing the debrief screen a **null payload** + the callId.
  - `client/lib/features/debrief/views/debrief_screen.dart` — `kPollBudget = Duration(seconds: 30)`
    (line ~224), `kPollInterval = 1 s` (line ~223): on a null payload + non-null
    callId the screen polls for 30 s ("Analyzing your conversation…") before the quiet
    "Debrief unavailable" terminal state.
  - **Net:** the user only sees "Debrief unavailable" if the server takes longer than
    the 30 s screen poll. Server ~25 s outer < 30 s → safe. A DEGRADED (score-only)
    debrief is a DIFFERENT state — it renders "Detailed analysis is unavailable for
    this call" (`_kDegradedAnalysis`), which is exactly what Bug B is eliminating.
- Probe: `server/scripts/probe_debrief_schema.py` (header says "Groq Scout" but it
  reads `Settings.debrief_model` = gpt-4.1-mini now — update the stale docstring while
  you're there). Run from `server/` with the live OpenAI key in `.env`.

### Bug A — the judge prompt
`EXCHANGE_CLASSIFIER_MULTI_PROMPT` lives in `server/pipeline/prompts.py` (line ~286).
It already says "Default to UNMET when in doubt" and "Do NOT mark an objective met
just because the user said something or engaged." The gap call 340 exposed: a beat's
own `success_criteria` text ("Any acknowledgement … counts") OVERRIDES that good
instinct because the per-goal criteria are injected verbatim via `{pending_goals_block}`.
So the prompt needs an explicit clause that the criteria describe the TARGET, and a
permissive phrasing in a criterion never licenses crediting an empty / evasive /
off-topic / wrong-content reply — the user must perform the actual conversational
move. **Do NOT weaken** the INTENT-not-surface-form leniency (synonyms, fragments,
"uh… the chicken") or the abuse section (R5) — Bug A is about *content*, not *language*.

### Bug A — the criteria to rewrite (per file)
All under `server/pipeline/scenarios/`. Touch ONLY over-permissive `success_criteria`.
- **the-waiter.yaml** (the call-340 culprit): `confirm` (line ~191-194: "Any
  acknowledgement of the order summary counts") and `close` (line ~203-205: "Even a
  simple 'okay' or 'thanks' counts") are the worst. Also review `clarify` (line
  ~146-159: "in any coherent way" + "polite acknowledgements") and `drink` (line
  ~175-182: "either way — pass it") — keep the legitimate synonym/refusal acceptance
  but require the beat's actual move (confirm = affirms OR corrects the SPECIFIC
  order; close = a real closing courtesy, not merely "words exist").
- **the-cop.yaml** (cop_hard_01 — golden FAIL on the opening): lines ~80, 99, 113
  ("Any coherent justification counts"), 150. Tighten the opening react/respond beat
  so small-talk is NOT engagement.
- **the-girlfriend.yaml** (girlfriend_medium_01 — golden FAIL): lines ~107 ("Judge by
  intent, so a genuine reason … counts"), 175. Tighten the opening beat.
- **the-mugger.yaml** (mugger_medium_01 — golden FAIL): lines ~82 ("Any coherent
  response counts"), 144 ("Any firm closing statement counts").
- **the-landlord.yaml** (landlord_hard_01 — golden PASS already): lines ~80, 102, 118,
  133, 148, 163. It is the GOOD MODEL — several beats already say "X counts; doing
  nothing / ignoring does NOT count." Propagate that shape to the others; only tighten
  any landlord beat still carrying a blanket "any … counts".
- **cop-interrogation-01.yaml** (golden PASS): the line-36 hit is a `base_prompt` rule
  ("never end … on a bare acknowledgement"), NOT a `success_criteria` — leave it.

### Bug A — the lint (mirror R1/R2, add R8)
Pattern source of truth in `server/pipeline/scenarios.py` (alongside
`find_model_specific_tokens` line ~425 and `find_scripting_violations` line ~463).
Three-layer enforcement, identical posture:
1. `scenario_builder.validate_structure` imports the helper and HARD-fails a violator.
2. `load_scenario_*` WARNS (runtime canary; don't crash a live call on a fuzzy match).
3. `tests/test_scenarios.py` lints every shipped scenario via the `_SCENARIO_INDEX`
   glob (NEVER a hand-list) and fails the commit.
Candidate flag phrases (tune for zero false-positives AFTER the rewrite): `any
acknowledgement`, `even a simple`, `any coherent … counts`, `either way — pass it`,
a bare `any … counts`. Be careful: legitimate lenient prose ("Accept the menu items
AND common synonyms", "re-stating … counts") must NOT trip it. Because the rewrite
removes the blanket idioms first, the lint then passes — write criteria → add lint.
Record R8 in `server/CLAUDE.md §9` with the durable-lesson framing (a recurring bug
class becomes a lint, not a memory note or one-off patch).

### The swing is ONE defect (AC7 — do not over-correct)
The brief §3c documents the OPPOSITE pole: a FALSE-NEGATIVE ("I would like to know if
it is possible to order?" judged `greet: unmet`) drains −15 patience per unmet turn →
100→40 in ~50 s → impatience ladder → hang-up. Bug A (call 340) is the loose pole;
§3c is the strict pole. They are the SAME defect. So the criteria rewrite must thread
the needle: reject empty/off-topic/wrong content, but credit a clearly-engaged,
on-target turn even in messy B1 English. The calibration band (AC10) is the proof you
did not swing too far. The patience↔judge DECOUPLING itself (so a future false-negative
no longer punishes the user) is OUT of scope — it belongs to the rail-keeper story
(10-8); your job here is to NOT make it worse.

### Validation tooling (`server/CLAUDE.md §6`)
- `python scripts/calibrate_scenario.py --golden-only` — fast, fraction-of-a-cent;
  the universal off-topic seed must be `unmet` on every beat (the permanent
  "judge passes everything" regression assertion). This is your primary Bug A signal.
- `python scripts/calibrate_scenario.py <id>` — N=10 AI-learner sweep at run-level
  `--difficulty` (default easy); cooperative completion must land in the easy band
  (60–80). This proves AC7.
- These need the live LLM key and run via the CLI only (never imported by prod);
  `ENGINE_VERSION` in `calibration_engine.py` forces a full re-sweep when rules change.

### Constraints / what must NOT be broken (from brief §10 + server/CLAUDE.md)
- **Judge HTTP/outer timeouts** `_CLASSIFIER_TIMEOUT_SECONDS = 4.5` / `_HTTP_TIMEOUT_SECONDS = 4.0`
  in `exchange_classifier.py` — **leave them.** The 10.6 review measured the
  gpt-4.1-mini judge at ~2 s/call and restored these from a too-tight 2.5/2.0. This
  story tightens criteria, not the judge HTTP budget. (Bug B's debrief timeouts are a
  DIFFERENT pair — §10 of the brief calls this out explicitly; only the DEBRIEF
  budgets are raised.)
- **`VERDICT_WAIT_BUDGET_MS` (800 ms) and any felt-timing calibration** — off-limits
  (Walid owns these).
- **The strict structured-output contract** — the judge stays strict `json_schema`
  (`_build_verdict_schema`); the debrief keeps strict + its non-strict-400 retry.
  Do not touch the schema shapes (`server/CLAUDE.md §4` judge-model law).
- **`requires` (Story 6.23) and `implies` (anti-strand back-fill)** crediting
  semantics — do NOT change them; tightening `success_criteria` text is independent
  of the gating engine.
- **golden==prod parity** — `calibrate_scenario` judges the SAME `judgeable_goals`
  as prod; a green golden run means prod behaves.
- **The R1–R7 rulebook + three-layer enforcement (`server/CLAUDE.md §9`)** — extend
  it (add R8), never bypass it.

### Scope boundary (what is DEFERRED to 10-8, not this story)
From the brief §1–9, all OUT of scope here and carved to
`10-8-character-rail-keeper-arc-ordering-and-hud-sync` (new backlog stub):
- the HUD showing a stale "do this now" instruction when an early beat never credits
  (call 334/336) and the client computing the active step locally;
- the "character is the rail-keeper" conversational conduct (advance one distinct
  beat in order, redirect-don't-skip, confirm-not-re-ask, hard ordering constraints);
- the patience↔judge false-negative DECOUPLING (don't drain patience on a mis-judged
  good turn).
This story is the judge-accuracy + debrief slice that unblocks 10.6 ONLY.

## Project Structure Notes

- Server-only change (judge prompt, debrief budgets, scenario `success_criteria`, one
  lint helper + its 3 wiring points, a CLAUDE.md rule). No DB migration. No new files
  except possibly a test addition in `tests/test_scenarios.py`.
- Client is VERIFIED, not modified (Bug B AC2), unless the give-up math forces a budget
  bump — then Flutter gates apply and it must be justified as a declared deviation.
- Deploys via the normal `systemctl restart pipecat.service` / CI deploy-server path
  (no migration to apply). The bot subprocess holds the judge + debrief code, so a
  restart picks up the new prompt/criteria/timeouts.

## References

- [checkpoint-arc-rail-keeper-design-brief.md — ADDENDUM (2026-06-29) §A + §B](_bmad-output/implementation-artifacts/checkpoint-arc-rail-keeper-design-brief.md) — the authoritative spec for this story.
- [10-6 story (the migration this unblocks)](_bmad-output/implementation-artifacts/10-6-migrate-off-decommissioned-llama-4-scout-model.md)
- [server/CLAUDE.md §4 judge-model law, §6 calibration, §8 difficulty-neutral, §9 R1–R7 + durable lesson](server/CLAUDE.md)
- `server/pipeline/debrief_generator.py` (Bug B), `server/pipeline/prompts.py::EXCHANGE_CLASSIFIER_MULTI_PROMPT` (Bug A judge), `server/pipeline/scenarios.py` (lint pattern), `server/pipeline/scenarios/*.yaml` (criteria), `server/scripts/calibrate_scenario.py` + `server/scripts/probe_debrief_schema.py` (validation).
- `client/lib/features/call/views/call_ended_screen.dart` (`kMaxHold`), `client/lib/features/debrief/views/debrief_screen.dart` (`kPollBudget`/`kPollInterval`) — client give-up window (Bug B verification).

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
