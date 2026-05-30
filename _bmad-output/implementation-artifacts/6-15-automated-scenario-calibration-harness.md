# Story 6.15: Automated Scenario Calibration Harness (text-driven + AI agents)

Status: ready-for-dev

## Story

As the operator (Walid),
I want to **test a scenario's conversation logic automatically with text instead of opening the app and talking**, using AI agents that play the learner and judge whether the scenario is well-calibrated,
so that I can validate the checkpoint judge + persona + difficulty **without the manual voice loop**, and **scale to many scenarios** (which I could never fine-test one by one by hand).

## Background

**Direct motivation — the 2026-05-30 "judge passes everything" bug.** The multi-goal checkpoint judge was silently validating EVERY checkpoint regardless of input (an off-topic "there are a lot of people here" flipped `greet`; garbage flipped `drink`/`confirm`/`close` → false `survived`). It took several manual device calls + log reading to catch. **A text-driven automated test would have caught it in seconds** by asserting "off-topic input → checkpoint UNMET". This story makes that class of regression impossible to ship unnoticed, and is the foundation for scaling scenario authoring.

**The broader frame (Walid 2026-05-30):** *"imaginons que j'en crée beaucoup, je ne pourrai pas tous les tester finement. Donc il faudra automatiser cela via des agents IA qui vont faire des tests et voir si le scénario est bien calibré… des tests automatisés qu'on lancera à chaque création de scénario."*

**This is the automation of work the project already does by hand.** Story 3.0 built scenario-calibration tooling (`score_transcript.py`, `TranscriptLogger`). Story 6.8 defined per-scenario **success-rate target bands** (Waiter 60-90%, Mugger/Girlfriend 35-55%, Cop/Landlord 15-35%) and a manual "Pass A / Pass B" device-calibration loop. Story 6.9b built `scripts/benchmark_classifier.py` + a 75-sample labeled corpus that **reuses the exact prod classifier code paths**. This story closes the loop: drive whole conversations in **text**, with an **AI learner** on the user side and an **AI/assertion judge** on the verdict side — no Soniox, no TTS, no LiveKit, no human.

**Key architectural principle (non-negotiable, inherited from `benchmark_classifier.py`):** the harness MUST exercise the **same production code paths** — the same `EXCHANGE_CLASSIFIER_MULTI_PROMPT` + `ExchangeClassifier.classify_multi`, the same `build_main_llm` character LLM, the same checkpoint-advance / goal-tracking logic, the same `resolve_patience_config`. If the harness re-implements any of that, it stops testing prod. It bypasses ONLY the transport layers (audio in/out, STT, TTS, LiveKit) — the layers a text test legitimately replaces.

**Two test modes — keep them distinct (they have different cost/determinism):**
1. **Deterministic golden checks (cheap, regression-grade).** Curated `(turn, expected-verdict)` cases per scenario checkpoint — including NEGATIVES (off-topic must be UNMET) and messy POSITIVES (hesitant B1 must be MET). Asserts `classify_multi` against labels. This is the net that catches "judge passes everything". Low cost, could run in CI behind a key.
2. **Stochastic calibration (expensive, band-grade).** An AI learner-agent runs many full conversations; compute the success/completion rate; compare to the scenario's target band. Catches "scenario too easy / too hard". Run at scenario creation, not on every commit.

**Critical reading before starting:**
- `server/scripts/benchmark_classifier.py` — the reuse-prod-paths precedent (imports prod prompt + `_parse_*`; per-provider request shapes; report generation). The new harness mirrors its structure.
- `server/tests/fixtures/classifier_benchmark_corpus.json` — the 75-sample labeled corpus shape; the golden fixtures extend this idea per-scenario.
- `server/pipeline/exchange_classifier.py` (`classify_multi`, `_build_verdict_schema`, `_format_pending_goals_block`) + `server/pipeline/prompts.py` (`EXCHANGE_CLASSIFIER_MULTI_PROMPT`) — the judge under test.
- `server/pipeline/checkpoint_manager.py` — the goal-tracking + advance logic to reuse (extract the pure decision logic if it's currently entangled with the pipecat FrameProcessor — see Deviation note).
- `server/pipeline/llm_provider.py` (`build_main_llm`, `resolve_llm_*`) — the character LLM construction.
- `server/scripts/score_transcript.py` + `_bmad-output/implementation-artifacts/calibration-tests/` — Story 3.0 / 6.9b calibration artifacts the reports should live alongside.
- Story 6.8 calibration bands (in that story file's Phase 3) — the per-scenario target success-rate ranges.

## Acceptance Criteria (BDD)

### AC1 — Text conversation harness reusing prod code paths

Given the prod pipeline judges turns via `classify_multi` + advances checkpoints + tracks patience
When this story lands
Then a harness (e.g. `server/scripts/simulate_conversation.py` + a reusable module) exists that, given a `scenario_id` and a sequence of **user text turns**, drives a conversation WITHOUT Soniox/TTS/LiveKit by calling:
  - the SAME character LLM (`build_main_llm`) for each character reply,
  - the SAME `classify_multi` + checkpoint-advance/goal-tracking logic for verdicts,
  - the SAME `resolve_patience_config` for patience effects,
And returns a structured transcript: per turn `{user_text, character_reply, verdicts: {goal_id: met|unmet|unsure}, goals_met_set, patience, scheduled_end_reason?}` + the final outcome (`survived` / `character_hung_up` / `noisy_environment` N/A here / in-progress).
And it imports those from the prod modules — it does NOT re-implement the prompt, the classifier, or the advance rule (a wiring/source assertion guards this).

### AC2 — Deterministic per-checkpoint golden tests (the regression net)

Given the 2026-05-30 bug (judge passed everything)
When this story lands
Then each scenario has a labeled fixture of `(character_line, user_text, goal_id, expected_verdict)` cases covering, per checkpoint, at least:
  - **NEGATIVE**: a clearly off-topic / small-talk turn that MUST be `unmet` (e.g. greet ← "there are a lot of people here" → unmet),
  - **POSITIVE (messy)**: a hesitant/fragmented but genuine attempt that MUST be `met` (e.g. main_course ← "uh… the chicken" → met),
And a runner feeds each case through prod `classify_multi` and asserts the verdict matches the label,
And the runner reports accuracy + lists every mismatch (false-pass / false-fail),
And a deliberately-reverted (over-lenient) judge prompt FAILS this runner (proven once during dev) — i.e. the net actually catches the bug it exists for.

### AC3 — AI learner-agent (user simulator)

Given testing whole conversations by hand is the bottleneck
When this story lands
Then an LLM-driven "learner" agent plays the USER side against the AC1 harness, with selectable strategies:
  - `cooperative` — a B1 learner who genuinely tries to complete the scenario's goals,
  - `hesitant` — cooperative but messy/fragmented (stress-tests false-negatives),
  - `off_topic` — engages but never addresses the goals (must NOT complete),
  - `minimal` — one-word / silent-ish (stresses patience + silence paths),
And the learner agent is given ONLY what a real user would plausibly know (the scenario briefing / character context), NOT the success_criteria (no cheating to the answer).

### AC4 — AI calibration judge + target-band check

Given Story 6.8's per-scenario success-rate bands
When this story lands
Then a calibrator runs **N conversations** (configurable, e.g. 10) with the `cooperative` learner per scenario, computes the **completion rate** (% reaching `survived`), and compares it to the scenario's target band → verdict `in_band` / `too_easy` / `too_hard`,
And it runs the `off_topic` learner and asserts those conversations do NOT complete (they should drain patience / hang up) — the inverse guardrail,
And it writes a per-scenario report artifact under `_bmad-output/implementation-artifacts/calibration-tests/` (timestamped, like the 6.9b bench reports) with the rates, the band verdict, and sampled transcripts for eyeballing,
And the target bands live in a single config (scenario metadata or a calibration table) — not hardcoded per scenario in the harness.

### AC5 — One command, run at scenario creation

Given the goal is "run automated tests at each scenario creation"
When this story lands
Then a single entry-point (e.g. `python scripts/calibrate_scenario.py <scenario_id>`) runs AC2 (golden) + AC4 (calibration) and prints a clear PASS/FAIL summary + the report path,
And the scenario-authoring docs (Epic 3 authoring guide / `server/CLAUDE.md` or a new doc) document this as the required step when adding/editing a scenario,
And running it with no scenario_id calibrates ALL scenarios (the "did my prompt/classifier change break any scenario?" sweep — exactly the check missing on 2026-05-30).

### AC6 — Cost + determinism controls (don't break `pytest`)

Given real LLM calls cost money and are non-deterministic
When this story lands
Then the harness's live-LLM runs are **NOT** part of the default `pytest` gate (they would cost money + flake); they require an API key + an explicit flag/command (mirror `benchmark_classifier.py`),
And the harness's own logic (transcript assembly, report math, band comparison, strategy prompt building) HAS fast unit tests with a **mocked LLM** that DO run in `pytest`,
And the classifier calls use low temperature + the calibration uses **rates over N samples** (never a single-shot pass/fail) so non-determinism averages out,
And the doc states the rough cost per `calibrate_scenario` run (so it's a deliberate, budgeted action).

### AC7 — Pre-commit gates

`ruff check . && ruff format --check . && pytest` (server) all green; the new mocked-LLM unit tests pass; `flutter` untouched (client-free story).

### AC8 — Validation

See `## Validation` below (this story is largely self-validating via AC2/AC4 — no device gate needed, which is the whole point).

## Validation (mostly automated — the point of this story)

- [ ] **Golden net catches the bug it exists for.** Temporarily revert the judge prompt to the old "Default to MET" wording → AC2 runner FAILS on the NEGATIVE cases. Restore → passes.
  - _Proof:_ <!-- runner output before/after -->
- [ ] **Waiter calibrates in-band.** `calibrate_scenario waiter_easy_01` → completion rate inside the Waiter band (60-90%); `off_topic` learner does NOT complete.
  - _Proof:_ <!-- report artifact -->
- [ ] **All-scenario sweep runs.** `calibrate_scenario` (no arg) produces a report for all 5 scenarios with a band verdict each.
  - _Proof:_ <!-- report -->
- [ ] **No device call required.** The full validation above ran from a terminal with an API key, zero app opens.

## Tasks / Subtasks

### Phase 1 — Extract reusable decision logic + text harness

- [ ] **Task 1 — Make the checkpoint-advance logic callable outside the pipecat FrameProcessor** (AC1)
  - [ ] 1.1 — Audit `CheckpointManager`: the goal-tracking + advance decision (verdict dict → goals_met update → success/fail → completion) should be reachable WITHOUT a running pipeline. If it's entangled with `process_frame`/`push_frame`, extract the pure decision into a function/helper the manager calls AND the harness calls (no logic fork).
  - [ ] 1.2 — Same for the patience effect (`apply_exchange_outcome`) — reuse `PatienceTracker`'s meter logic directly (it's already mostly pure).
- [ ] **Task 2 — `simulate_conversation` harness** (AC1)
  - [ ] 2.1 — Given (scenario_id, list[user_text]) → drive character LLM + classify_multi + advance + patience, return the structured transcript.
  - [ ] 2.2 — Source-assert it imports prod prompt/classifier/advance (no re-implementation).

### Phase 2 — Deterministic golden net

- [ ] **Task 3 — Per-scenario golden fixtures** (AC2) — labeled negative + messy-positive cases per checkpoint (start with the Waiter; template for the rest).
- [ ] **Task 4 — Golden runner** (AC2) — feed cases through `classify_multi`, assert verdict==label, report mismatches; prove it fails on the reverted lenient prompt.

### Phase 3 — AI learner + calibration

- [ ] **Task 5 — Learner agent** (AC3) — strategies cooperative / hesitant / off_topic / minimal; given briefing+character only (never success_criteria).
- [ ] **Task 6 — Calibrator + band check + report** (AC4) — N conversations, completion-rate vs band, off_topic-must-fail guardrail, timestamped report artifact.
- [ ] **Task 7 — `calibrate_scenario` entry-point + docs** (AC5) — per-scenario + all-scenario sweep; document as the scenario-creation step.

### Phase 4 — Tests + gates

- [ ] **Task 8 — Mocked-LLM unit tests** (AC6) for harness logic (transcript assembly, report math, band verdict, strategy-prompt building) — run in `pytest`.
- [ ] **Task 9 — Pre-commit gates** (AC7) + cost/determinism doc (AC6).

## Dev Notes

**Why reuse prod paths is sacred:** the value of this harness is that a green run means PROD behaves. If it re-implements the classifier or the advance rule, a passing test proves nothing about the real app. `benchmark_classifier.py` already set this precedent (it imports `EXCHANGE_CLASSIFIER_PROMPT` + `_parse_classifier_output`). The only legitimate substitution is the transport layer (text in/out instead of Soniox/TTS/LiveKit) — because that's exactly the layer a text test stands in for. STT/TTS quality is validated separately (device smoke); this harness validates LOGIC (judge correctness, persona coherence, difficulty calibration).

**Deterministic vs stochastic — why both:**
- The **golden net** (AC2) is deterministic-ish (low-temp, single classify per case) and cheap — it's the regression guard that runs whenever the judge/prompt changes. It directly encodes "off-topic must fail", which is the 2026-05-30 bug as a permanent assertion.
- The **calibration** (AC4) is inherently stochastic (an LLM learner + an LLM character + an LLM judge, multi-turn). A single conversation proves little; the SIGNAL is the rate over N runs vs the band. Treat it like the benchmark harness: rates, not single verdicts.

**Non-determinism + flakiness:** never assert on a single LLM conversation. Use rates over N (AC4) and exact-label golden cases at low temperature (AC2, tolerate the rare classifier flip by setting a pass threshold < 100% if needed, but log every mismatch). NEVER put live-LLM runs in the default `pytest` (cost + flake) — gate behind a key + flag, like `benchmark_classifier.py`.

**Cost:** a `calibrate_scenario` run = N conversations × ~K turns × (1 character LLM + 1 classifier + 1 learner) calls. Estimate it in the doc so it's a budgeted action, not a surprise. The golden net is far cheaper (1 classify per case).

**This is the scaffolding for scenario scale (Walid's broader goal):** once authoring many scenarios, `calibrate_scenario <new_id>` becomes the gate — golden net proves the checkpoints discriminate, calibration proves the difficulty lands in-band — all without a device. A future story can wire it into CI (behind a key) or into the `create-scenario` workflow.

**Out of scope:** voice/STT/TTS quality, jitter (Story 6.14), the LiveKit transport. Those need real audio + device. This story is the text-logic layer only.

### Project Structure Notes
- Server-only, dev tooling. New: `scripts/simulate_conversation.py`, `scripts/calibrate_scenario.py`, a harness module, per-scenario golden fixtures under `tests/fixtures/`, mocked-LLM unit tests. Reports under `_bmad-output/implementation-artifacts/calibration-tests/`.
- Possible refactor: extract pure checkpoint-advance decision logic out of `CheckpointManager.process_frame` so both prod + harness share it (Task 1) — do this WITHOUT changing prod behaviour (existing checkpoint tests must stay green).
- No DB / migration changes.

### References
- `server/scripts/benchmark_classifier.py` + `tests/fixtures/classifier_benchmark_corpus.json` (reuse-prod-paths precedent + corpus shape).
- `server/scripts/score_transcript.py` + `calibration-tests/` (Story 3.0 / 6.9b).
- Story 6.8 Phase 3 — per-scenario success-rate target bands.
- 2026-05-30 fix commit `4ca78fe` (judge default-to-UNMET) — the bug this harness would have caught.

## Dev Agent Record

### Agent Model Used

(filled at dev time)

### Debug Log References

(filled at dev time)

### Completion Notes List

(filled at dev time)

### File List

(filled at dev time)

## Change Log

- 2026-05-30 — Spec drafted (Walid ask) after the "judge passes every checkpoint" bug needed several manual device calls to catch. Automates the existing manual calibration (Story 3.0 tools + 6.8 bands + 6.9b corpus/bench) into a text-driven harness: prod-code-path conversation simulator (no audio/LiveKit) + deterministic per-checkpoint golden net (the regression guard) + AI learner-agent + stochastic band-calibration + one `calibrate_scenario` command to run at each scenario creation. Foundation for scaling scenario authoring. Awaiting Walid sign-off / `/bmad-dev-story`.
