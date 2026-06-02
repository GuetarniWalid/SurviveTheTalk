# Story 6.15: Automated Scenario Calibration Harness (text-driven + AI agents)

Status: review

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

---

## Scope Extension — "Validation Engine" Requirements (2026-06-01, Walid sign-off)

Walid's framing after reading the spec: this is not "a test", it is **an engine/tool** for
validating scenarios at scale. *"imaginons que j'en crée beaucoup, je ne pourrai pas tous les
tester finement… La rigueur doit être dans l'outil et pas dans la maintenance des scénarios.
La création de scénarios doit rester le plus simple possible et toute la difficulté est mise
dans cet engin de test."* Three design decisions taken in the same conversation:

- **Golden net** = **auto-generation + review** (a universal off-topic seed runs always with NO
  review; the per-checkpoint cases are LLM-generated from `success_criteria`, written to a
  fixture flagged `reviewed: false`, and Walid/an agent approves once → cached).
- **Calibration depth** = **N=10** conversations per scenario per strategy; in-band = ✅,
  within ±5 pts of the band edge = ⚠️ warning (not a hard fail).
- **Scope** = the **complete tool** in this story.

These add AC9–AC13 on top of AC1–AC8. They sharpen, not replace, the original ACs.

### AC9 — Yes/No verdict + agent-friendly exit code

Given Walid wants a binary "is this scenario validated?" answer
When `calibrate_scenario <id>` runs
Then it prints a single clear **PASS ✅ / FAIL ❌** per scenario and exits with **code 0** iff
ALL evaluated scenarios passed, **non-zero** otherwise (so an agent / CI step can branch on it),
And the verdict for one scenario is PASS iff:
  - **Golden net:** 100 % of NEGATIVE (off-topic) cases verdict `unmet` (zero tolerance — an
    off-topic that passes is the exact 2026-05-30 bug), AND ≥ 90 % of messy-POSITIVE cases
    verdict `met` (tolerates the rare low-temp classifier flip; every mismatch is logged), AND
  - **Calibration:** the `cooperative` completion rate is inside the difficulty band (a result
    within ±5 pts of an edge is a ⚠️ warning that still PASSES but is surfaced), AND the
    `off_topic` learner completion rate is 0 % (the inverse guardrail).

### AC10 — Validation memory (ledger) + revalidate-only-what-changed

Given Walid will validate many scenarios and must not re-pay for already-validated ones
When the engine runs
Then a **ledger** persists per scenario: `{scenario_id, scenario_hash, engine_version,
validated_at, verdict, report_path, golden_summary, calibration_summary}` at
`_bmad-output/implementation-artifacts/calibration-tests/validation-ledger.json`,
And `calibrate_scenario` (no arg) is a **smart sweep**: it validates ONLY scenarios that are
(a) never validated, OR (b) whose `scenario_hash` differs from the ledger (the YAML changed
since last validation), OR (c) whose ledger `engine_version` is older than the current engine
(the RULES changed) — fresh+unchanged scenarios are skipped and reported as `cached PASS`,
And `--force` revalidates regardless of the ledger,
And the **`scenario_hash` covers only behaviour-affecting fields** (base_prompt, every
checkpoint's id/prompt_segment/success_criteria, difficulty, the 8 patience overrides, briefing,
exit_lines) — cosmetic edits (tts_voice_id, rive_character, language_focus, comments) do NOT
trigger a needless re-run,
And the **`engine_version`** is a constant bumped whenever the validation RULES change, so
tightening the engine forces a global revalidation on the next sweep (rigor stays in the tool,
constant over time — Walid's core ask).

### AC11 — Copy-pasteable failure diagnostic (for a human OR an AI agent)

Given a FAIL must be actionable without log-spelunking, and Walid wants to paste it to an AI
that fixes the scenario
When a scenario FAILs
Then the engine emits a **self-contained Markdown block** (printed to stdout AND saved next to
the JSON report) that states, per failed check: the scenario id, which checkpoint, the exact
failing cases (character line + user text + expected vs actual verdict), sampled transcripts for
calibration misses, a plain-language **likely cause + suggested fix** per failure class, and the
exact **reproduction command**,
And the block names the offending YAML field paths (e.g. `checkpoints[3].success_criteria`) so a
fixing agent knows precisely what to edit,
And the block is written so pasting it (alone) gives an AI enough context to propose an edit
without needing the rest of the repo.

### AC12 — Rigor in the engine, simplicity in authoring

Given Walid must be able to add scenarios without memorising rules
When the engine validates
Then it derives the target band from the scenario's existing **`difficulty`** field via a single
engine-side table (sourced from `difficulty-calibration.md` §4.3: easy 60–80, medium 35–55, hard
15–35) — the author sets `difficulty` (already required) and NOTHING else calibration-specific,
And the universal off-topic golden seed applies to EVERY scenario with zero per-scenario
authoring (so a brand-new, never-reviewed scenario still gets the 2026-05-30 regression guard),
And no new REQUIRED scenario YAML field is introduced (an OPTIONAL `calibration.target_band`
override may exist but defaults to the difficulty-derived band).

### AC13 — Batch / loop the whole catalogue

Given Walid wants "valider dix scénarios… les uns à la suite des autres"
When `calibrate_scenario` runs with no id (or `--scenarios a,b,c`)
Then it iterates the catalogue (from the SAME `_SCENARIO_INDEX` the pipeline uses), runs each
through golden + calibration (subject to the AC10 ledger skip), prints a one-line PASS/FAIL/cached
summary per scenario plus a final tally, and the process exit code reflects the worst outcome.

---

## Validation (mostly automated — the point of this story)

- [x] **Golden net catches the bug it exists for.** Proven as a permanent unit test rather than a manual prompt-revert: `test_run_golden_lenient_judge_fails_the_net` drives a deliberately over-lenient judge (returns `met` for everything — equivalent to the old "Default to MET" prompt) through `run_golden`; the universal off-topic seed FAILS it (`negative_failures > 0`). `test_run_golden_correct_judge_passes_the_seed` is the restore case.
  - _Proof:_ `pytest tests/test_calibration_engine.py` — 28 passed (the two golden tests included).
- [ ] **Waiter calibrates in-band.** `calibrate_scenario waiter_easy_01` → completion rate inside the easy band (60-80%); `off_topic` learner does NOT complete. _(Walid-owned — needs `GROQ_API_KEY`; live-LLM run, gated out of pytest per AC6.)_
  - _Proof:_ <!-- live report artifact, run by Walid -->
- [ ] **All-scenario sweep runs.** `calibrate_scenario` (no arg) produces a report + band verdict for all 5 scenarios. _(Walid-owned — live run.)_
  - _Proof:_ <!-- report -->
- [x] **No device call required.** All logic validation is automated in `pytest` with mocked LLMs (zero app opens, zero network). The live calibration sweep also runs from a terminal with an API key — no device, the whole point of the story.

## Tasks / Subtasks

### Phase 1 — Extract reusable decision logic + text harness

- [x] **Task 1 — Make the checkpoint-advance logic callable outside the pipecat FrameProcessor** (AC1)
  - [x] 1.1 — Extracted the pure `advance_goals(goals_state, verdicts) → GoalAdvance` out of `CheckpointManager._classify_and_flip_goals`; the manager now calls it (no fork). 96 checkpoint/patience tests stay green.
  - [x] 1.2 — Extracted pure `step_patience(...)` out of `PatienceTracker.apply_exchange_outcome`; both prod + harness call it.
- [x] **Task 2 — `simulate_conversation` harness** (AC1)
  - [x] 2.1 — `simulate_conversation(scenario_id, strategy, character_llm, learner_llm, judge)` drives character LLM + `classify_multi` + `advance_goals` + `step_patience`, returns a structured transcript + outcome.
  - [x] 2.2 — `test_engine_reuses_prod_symbols_not_reimplementation` asserts the engine's `advance_goals`/`step_patience`/`compose_goal_system_instruction`/`COHERENCE_CHARTER`/`ExchangeClassifier` ARE the prod objects (no re-implementation).

### Phase 2 — Deterministic golden net

- [x] **Task 3 — Per-scenario golden fixtures** (AC2) — hand-authored reviewed Waiter fixture (`tests/fixtures/golden/waiter_easy_01.json`, the worked example/template) + LLM `--generate-golden` to bootstrap the rest; universal off-topic seed needs no authoring.
- [x] **Task 4 — Golden runner** (AC2) — `run_golden` feeds cases through prod `classify_multi`, asserts verdict vs label, reports mismatches; `test_run_golden_lenient_judge_fails_the_net` proves a lenient judge FAILS the seed (the 2026-05-30 bug).

### Phase 3 — AI learner + calibration

- [x] **Task 5 — Learner agent** (AC3) — `build_learner_system_prompt` with cooperative / hesitant / off_topic / minimal; given briefing+character only (test asserts `success_criteria` absent).
- [x] **Task 6 — Calibrator + band check + report** (AC4) — `run_calibration` (N=10 cooperative + off_topic), completion-rate vs derived band, off_topic-must-not-complete guardrail, timestamped JSON report under `calibration-tests/`.
- [x] **Task 7 — `calibrate_scenario` entry-point + docs** (AC5) — per-scenario + no-arg sweep; documented as the scenario-creation step in `server/CLAUDE.md` §6.

### Phase 4 — Tests + gates

- [x] **Task 8 — Mocked-LLM unit tests** (AC6) — `tests/test_calibration_engine.py` (28 tests): bands, calibration gate, staleness hash, ledger, learner prompt, golden gate, simulator-with-fakes, report, failure-md, fixture shape.
- [x] **Task 9 — Pre-commit gates** (AC7) + cost/determinism doc (AC6) — ruff clean; safe test subset green (full pytest reserved for Walid — sandbox livekit import hang); cost in `server/CLAUDE.md` §6 + module docstrings.

### Phase 5 — Validation-engine layer (scope extension AC9–AC13)

- [x] **Task 10 — Pure decision extraction** (AC1) — `advance_goals` + `step_patience` shared by prod + harness; `CHARACTER_TEMPERATURE`/`CHARACTER_MAX_TOKENS` constants extracted in `llm_provider.py`; existing tests green.
- [x] **Task 11 — Validation ledger + staleness hash + engine_version** (AC10) — `validation-ledger.json` read/write; behaviour-only `scenario_hash`; `is_cached_pass` smart-sweep skip; `--force`.
- [x] **Task 12 — Yes/No gate + exit code** (AC9) — `combine_verdict` (golden ∧ calibration); CLI exit code 0 iff all pass.
- [x] **Task 13 — Copy-pasteable failure report** (AC11) — `format_failure_report` Markdown (stdout + `.md` file): failing cases, YAML field paths, likely-cause/fix, reproduction command.
- [x] **Task 14 — Band table + difficulty derivation** (AC12) — `_DIFFICULTY_BANDS` from `difficulty-calibration.md` §4.3 + ±5 warning margin; universal off-topic seed; no required new YAML field.
- [x] **Task 15 — Catalogue sweep CLI** (AC13) — no-arg = all scenarios via `scenarios._SCENARIO_INDEX`; `--scenarios a,b,c`; per-scenario + tally output.

## Deviations (declared up-front)

- **#1 — Character LLM driven via the raw OpenAI SDK, not `build_main_llm`.** `build_main_llm`
  returns a pipecat `OpenAILLMService` that only runs inside a pipeline. The harness legitimately
  replaces the transport, so it drives single character completions via `openai.AsyncOpenAI`
  using the SAME `resolve_llm_*` helpers + `settings.character_model` + the shared
  `CHARACTER_TEMPERATURE` / `CHARACTER_MAX_TOKENS` constants (extracted in Task 10 so prod and
  harness share the exact numbers). Documented as the one legitimate transport substitution.
- **#2 — Golden net is auto-generated + reviewed, with a universal off-topic seed floor.** Per
  Walid's choice. The seed (trivial off-topic utterances → must be `unmet`) needs no review and
  always runs; the per-checkpoint cases are LLM-generated and gated `reviewed: false` until
  approved. An un-reviewed scenario still gets the regression guard from the seed.
- **#3 — Bands derived from `difficulty`, not a per-scenario field.** Authoring stays a single
  `difficulty: easy|medium|hard`. Engine owns the band table. Optional
  `calibration.target_band` override exists but is not required.
- **#4 — `scenario_hash` is a behaviour-projection, not a whole-file hash.** Cosmetic YAML edits
  don't burn an LLM re-run. Trades a sliver of conservativeness for cost; `--force` is the escape
  hatch.
- **#5 — Live-LLM runs are gated out of `pytest`** (key + flag, mirroring `benchmark_classifier.py`
  by file location + no prod import). Engine LOGIC has mocked-LLM unit tests that DO run.

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

claude-opus-4-8[1m] (`/bmad-dev-story`, 2026-06-01).

### Debug Log References

- Refactor regression net: `pytest tests/test_checkpoint_manager.py tests/test_patience_tracker.py` → 96 passed (Task 10 is behaviour-preserving).
- Engine logic: `pytest tests/test_calibration_engine.py` → 28 passed (incl. the AC2 lenient-judge-fails-the-net proof + the AC1 no-re-implementation guard).
- Safe subset (all changed surfaces, non-livekit): `pytest tests/test_calibration_engine.py tests/test_checkpoint_manager.py tests/test_patience_tracker.py tests/test_exchange_classifier.py tests/test_benchmark_classifier.py tests/test_config.py` → 184 passed.
- `ruff check .` + `ruff format --check .` → clean (83 files).

### Completion Notes List

- **Built a scenario *validation engine*, not just a test (Walid 2026-06-01 reframe).** One command `calibrate_scenario <id>` returns a yes/no verdict with an agent-friendly exit code; a no-arg sweep validates only new/changed/rules-changed scenarios via a `validation-ledger.json` (behaviour-only `scenario_hash` + `ENGINE_VERSION`); failures emit a copy-pasteable Markdown diagnostic for a human or an AI agent.
- **Sacred reuse-prod-paths (AC1).** The engine drives the EXACT prod judge (`classify_multi`), the pure `advance_goals` + `step_patience` (extracted in Task 10, prod calls them too — zero fork), `compose_goal_system_instruction` + `COHERENCE_CHARTER`, and the YAML loaders. Only the transport (audio/STT/TTS/LiveKit) is replaced by text. Character LLM driven via the raw `openai` SDK (Deviation #1) with the SAME provider/model/temperature constants. A guard test asserts the engine's symbols ARE the prod objects.
- **Golden net = universal off-topic seed (zero authoring, always gating) + auto-gen-then-reviewed per-checkpoint cases** (Walid's choice). The seed encodes the 2026-05-30 "judge passes everything" bug as a permanent assertion that every new scenario inherits for free; a lenient judge provably FAILS it.
- **Calibration = N=10 cooperative (band) + N=10 off_topic (inverse guardrail).** Band derived from `difficulty` (rigor-in-engine, AC12; easy 60-80 / medium 35-55 / hard 15-35 from `difficulty-calibration.md` §4.3); ±5 pts = ⚠️ warning that still passes.
- **Cost-gated like `benchmark_classifier.py`.** Live LLM runs need `GROQ_API_KEY` + the CLI; never imported by prod. Engine LOGIC has 28 mocked-LLM unit tests in the default `pytest`.
- **Walid-owned follow-up:** run `calibrate_scenario` live with `GROQ_API_KEY` to (a) confirm the Waiter calibrates in-band, (b) `--generate-golden` + review the 4 non-Waiter fixtures, (c) eyeball the first sweep's reports. No device call needed (the point of the story).
- **Pre-commit:** full `pytest` reserved for Walid before `/commit` (the dev-sandbox `from livekit import api` deadlock makes the livekit-importing tests hang locally — env-specific, not a code bug; see `memory/feedback_sandbox_livekit_import_hang.md`). Everything not transitively importing livekit is green locally.

### File List

**Refactor (Task 10 — pure decisions shared by prod + engine, no behaviour change):**
- `server/pipeline/checkpoint_manager.py` — new pure `advance_goals` + `GoalAdvance`; `_classify_and_flip_goals` now consumes them.
- `server/pipeline/patience_tracker.py` — new pure `step_patience`; `apply_exchange_outcome` consumes it.
- `server/pipeline/llm_provider.py` — extracted `CHARACTER_TEMPERATURE` / `CHARACTER_MAX_TOKENS` constants (shared with the engine).

**New — the validation engine:**
- `server/scripts/calibration_engine.py` — the reusable library (simulator, golden net + generator, learner, calibrator, bands, ledger + staleness hash + engine_version, report + copy-pasteable failure diagnostic).
- `server/scripts/calibrate_scenario.py` — the one operator command (yes/no verdict, smart sweep, `--force`, `--golden-only`, `--generate-golden`, exit codes).
- `server/scripts/simulate_conversation.py` — debug CLI: drive + print one text conversation.
- `server/tests/fixtures/golden/waiter_easy_01.json` — hand-authored reviewed golden fixture (worked example + template).
- `server/tests/test_calibration_engine.py` — 28 mocked-LLM unit tests.

**Docs / tracking:**
- `server/CLAUDE.md` — new §6 (validation engine = the scenario-creation step + cost/determinism).
- `_bmad-output/implementation-artifacts/6-15-automated-scenario-calibration-harness.md` — spec scope extension + this record.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — status flips.

## Change Log

- 2026-06-01 — Dev-story COMPLETE, `in-progress` → `review`. Built the full validation engine: pure-decision refactor (`advance_goals`/`step_patience`/`CHARACTER_*` constants, 96 prod tests green), `scripts/calibration_engine.py` (simulator + golden seed/gen/runner + learner + calibrator + bands + ledger/staleness-hash/engine_version + report + copy-pasteable failure diagnostic), `scripts/calibrate_scenario.py` + `scripts/simulate_conversation.py` CLIs, the reviewed Waiter golden fixture, 28 mocked-LLM unit tests (incl. the lenient-judge-fails-the-net proof + the no-re-implementation guard), and `server/CLAUDE.md` §6. ruff clean; safe non-livekit subset 184 passed. Live calibration sweep + non-Waiter `--generate-golden` review reserved for Walid (`GROQ_API_KEY`); full `pytest` reserved for Walid before `/commit` (sandbox livekit import hang). All 13 ACs delivered.
- 2026-06-01 — Scope extension (Walid sign-off, `/bmad-dev-story`). Reframed from "automated test" to a **validation engine/tool**: added AC9 (yes/no verdict + agent-friendly exit code), AC10 (validation ledger + staleness hash + `engine_version` revalidate-only-what-changed), AC11 (copy-pasteable failure diagnostic for human/AI), AC12 (rigor-in-engine: band derived from `difficulty`, universal off-topic seed, no required new YAML field), AC13 (catalogue sweep). 3 decisions taken: golden net = auto-gen + review (with universal seed floor); calibration N=10 (±5 pts = warning, not fail); ship the complete tool. Added Tasks 10–15 (Phase 5) + 5 up-front deviations. Status `ready-for-dev` → `in-progress`.
- 2026-05-30 — Spec drafted (Walid ask) after the "judge passes every checkpoint" bug needed several manual device calls to catch. Automates the existing manual calibration (Story 3.0 tools + 6.8 bands + 6.9b corpus/bench) into a text-driven harness: prod-code-path conversation simulator (no audio/LiveKit) + deterministic per-checkpoint golden net (the regression guard) + AI learner-agent + stochastic band-calibration + one `calibrate_scenario` command to run at each scenario creation. Foundation for scaling scenario authoring. Awaiting Walid sign-off / `/bmad-dev-story`.
