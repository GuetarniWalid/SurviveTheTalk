# Story 6.16: Scenario Builder (fuzzy description → complete validated scenario)

Status: review

## Story

As the operator (Walid),
I want to give a **short, fuzzy description** of a scenario and have an AI **build a complete, coherent scenario** (persona + ~20 time-advancing checkpoints + exit lines + briefing), which is then **automatically checked by the Story 6.15 validator**,
so that I can author many rich scenarios **without hand-writing every checkpoint**, and without the "too short to last 5 minutes" / "one sentence validates 4 checkpoints" failure modes.

## Background

The Waiter (6 checkpoints) is too short — it cannot fill a 5-minute call. Authoring 20 coherent
checkpoints by hand for every scenario does not scale (Walid's broader goal, same as Story 6.15).
This story is the **front half** of the authoring loop: **build** (this story) → **validate**
(Story 6.15). The builder fills the gaps an AI should fill: from a thin premise it invents a
believable persona, a time-ordered interrogation/conversation arc long enough for ~5 minutes, and
distinct per-beat success criteria — then the 6.15 engine proves the result holds (golden net +
difficulty calibration), so a bad generation is caught, not shipped.

**Walid's worked example (the acceptance test):**
> A cop calls you because your fingerprints were found at a crime scene. You must justify why they
> were there. The cop probes your gang ties and where you were at 8:30pm last night. The cop is
> suspicious and thinks you're lying. The whole thing must be 20 checkpoints. You succeed if the
> cop finds no flaw in your story.

That premise is too thin for 20 checkpoints on its own — the builder must be creative enough to
fill the gaps with AI.

**Mission success:** giving the prompt above yields a **20-checkpoint story that is coherent,
advances in time (does not loop), and where a single sentence does NOT validate 4 checkpoints at
once.**

## Acceptance Criteria (BDD)

### AC1 — Fuzzy description → complete, schema-valid scenario
Given a short free-text description + (scenario_id, difficulty, rive_character, checkpoint count)
When `build_scenario` runs
Then it produces a complete scenario dict/YAML matching the existing schema exactly (metadata with
the 8 nullable patience overrides, `base_prompt`, ordered `checkpoints[]` with
id/hint_text/prompt_segment/success_criteria, `exit_lines`, `briefing`, a `calibration` stub) and
writes it to `server/pipeline/scenarios/<file>.yaml`.

### AC2 — AI fills the gaps creatively
Given a thin premise (e.g. the cop example)
Then the builder expands it via the LLM into a rich brief: persona, setting, the user's objective,
win/lose conditions, canonical facts the character knows (for coherence), and a **time-ordered
narrative arc** with one beat per checkpoint — inventing believable detail the premise omitted.

### AC3 — Exactly N checkpoints, unique ids, all fields
The output has exactly the requested count (default 20) of checkpoints, each a non-empty
id/hint_text/prompt_segment/success_criteria, ids unique (passes `load_scenario_checkpoints`).

### AC4 — Checkpoints advance in time (no circular repeats)
An adversarial critique pass flags + repairs beats that repeat, regress, or could occur in any
order; the final arc progresses (beat k depends on beat k-1's exchange).

### AC5 — Checkpoints are discriminative (no "one sentence = 4 checkpoints")
The critique pass explicitly de-overlaps: it rewrites any pair of `success_criteria` a single
plausible utterance could satisfy, so each checkpoint targets a distinct user action tied to its
beat. A cheap lexical near-duplicate heuristic flags suspicious pairs up front; the Story 6.15
**calibration `too_easy` gate is the empirical backstop** (a scenario that collapses completes in
1-2 turns → flagged).

### AC6 — Long enough for ~5 minutes
Default 20 checkpoints (≈ 20 Q&A exchanges ≈ 4-6 min). `--checkpoints` is parameterizable.

### AC7 — Structurally valid + immediately validatable
The output loads through the prod `scenarios.py` loaders without error (unique ids, required
fields, `base_prompt` has NO speak-first directive, difficulty ∈ easy/medium/hard, patience
validators pass). `build_scenario --validate` chains directly into the Story 6.15
`calibrate_scenario` engine.

### AC8 — Cost + determinism (don't break `pytest`)
Live generation needs an API key + the CLI (never imported by prod), mirroring 6.15 /
`benchmark_classifier.py`. The builder's pure LOGIC (assembly, structural validation, overlap
heuristic, patience sizing, the pipeline driven with a FAKE LLM) has unit tests that run in
`pytest`.

### AC9 — Worked artifact
The cop/fingerprints scenario, produced by the builder, committed as a real scenario
(`rive_character: cop`, structurally valid, `is_free: false`, calibration pending Walid's live run).

### AC10 — Pre-commit gates
`ruff check . && ruff format --check . && pytest` (server) green for the in-sandbox-safe subset;
full `pytest` reserved for Walid (sandbox livekit import hang).

## Tasks / Subtasks

- [x] **Task 1 — Builder engine** (`scripts/scenario_builder.py`): `expand_brief` →
      `draft_checkpoints` → `critique_and_repair` (de-overlap + time-advance) → `build_base_prompt`
      → `assemble_scenario` → `validate_structure` → `scenario_to_yaml`. Prompts as module
      constants (the worked-example workflow uses the SAME prompt intent). (AC1-AC5, AC7)
- [x] **Task 2 — Pure helpers + structural validation** mirroring `scenarios.py` shape rules;
      `lexical_overlap_pairs`, `suggest_patience_start(n, difficulty)`, `slugify`/`sanitize_checkpoints`
      id-uniqueness. (AC3, AC5)
- [x] **Task 3 — CLI** (`scripts/build_scenario.py`): fuzzy desc → YAML; `--checkpoints`,
      `--difficulty`, `--character`, `--id`, `--dry-run`, `--validate`, `--overwrite`. Refuses an
      existing id; `--validate` chains the 6.15 golden net. (AC1, AC6, AC7)
- [x] **Task 4 — `.cmd` wrappers** (`scripts\build.cmd`, `scripts\calibrate.cmd`) → call the venv
      python, bypassing the Windows `python` App-Execution-Alias Store stub.
- [x] **Task 5 — Mocked-LLM unit tests** (`tests/test_scenario_builder.py`, 14 tests). (AC8)
- [x] **Task 6 — Generate the cop artifact** via the pipeline (expand → draft → 3-lens adversarial
      critique → repair → verify); committed as `cop-interrogation-01.yaml`; loads through every
      prod loader (20 unique checkpoints, patience_start 90, base_prompt valid). (AC9)
- [x] **Task 7 — Gates + finalize.** ruff clean; safe subset 193 passed. (AC10)

## Dev Notes

- **Goal-based engine is any-order (Story 6.10).** Strict temporal gating is NOT enforced by the
  runtime, so AC4/AC5 are enforced at AUTHORING time (the critique pass makes criteria distinct +
  beat-bound) and empirically at VALIDATION time (6.15 `too_easy` catches collapse). Document this.
- **Patience for long scenarios.** With goal-tracking, patience drains on OFF-TOPIC turns, not per
  checkpoint, so a cooperative user surviving 20 beats is plausible. The builder seeds a
  `patience_start` sized to the checkpoint count as a starting guess; calibration tunes it.
- **rive_character must be one of the 5 existing puppets** (waiter/mugger/girlfriend/cop/landlord)
  — a new scenario reuses an existing puppet (the cop example → `cop`). Document.
- **Reuse, don't fork.** Structural validation mirrors `scenarios.py` rules; `--validate` calls the
  Story 6.15 engine directly. The builder writes YAML; the validator judges it.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8[1m] (`/bmad-dev-story`, 2026-06-02). The cop artifact was generated by a 7-agent
Workflow (expand → draft → 3 adversarial critics → repair → verify).

### Completion Notes List
- **Builder pipeline** turns a fuzzy premise into a complete scenario: `expand_brief` (persona +
  canonical facts + a 20-beat time arc) → `draft_checkpoints` → `critique_and_repair` (adversarial
  de-overlap + time-advance + judgeability) → pure `build_base_prompt`/`assemble_scenario`/
  `validate_structure`/`scenario_to_yaml`. Reuses the 6.15 LLM client; structural validation mirrors
  `scenarios.py`; `--validate` chains into the 6.15 validator. Build → validate is the full loop.
- **Worked artifact — `cop_interrogation_01` ("The 8:30 Alibi")**: Detective Mercer, a break-in at
  Halloran's Electronics at 8:30pm, fingerprints on the INSIDE handle of the forced rear fire door,
  a grey-hooded witness at 8:25, CCTV timestamps, the "Carver Street Boys". 20 checkpoints that
  escalate (identity → accusation → alibi place/time/activity/companion → travel → misquote trap →
  gang → named associate → inside-handle reveal → silence-elaboration → last-touched date → witness
  → CCTV reconcile → companion recall trap → biggest-hole push → three-pillar close). The verifier
  agent confirms **all three of Walid's bars pass**: 20 distinct ✅, advances in time ✅, no single
  sentence satisfies 3+ checkpoints ✅ (lexical-overlap heuristic also found ZERO collisions).
- **Honest caveat (relayed to Walid):** the runtime checkpoint engine is GOAL-BASED / any-order
  (Story 6.10) — it judges every pending goal's `success_criteria` against each user turn, with no
  notion of "this beat's own probe". The builder mitigates collapse at AUTHORING time (each criterion
  is made distinct + carries explicit "earlier mention does not count" gating), and the Story 6.15
  calibration `too_easy` gate is the EMPIRICAL backstop (a collapsing scenario completes in 1-2 turns
  → flagged). So "one sentence ≠ 4 checkpoints" is enforced by design + caught empirically, not by a
  runtime temporal lock. Walid's live `calibrate_scenario cop_interrogation_01` is the confirmation.
- **Walid-owned next steps:** `calibrate.cmd cop_interrogation_01` (live, needs GROQ_API_KEY) to
  confirm the difficulty lands in band + the off_topic guardrail holds; tune `patience_start` (seeded
  at 90) if calibration says too_hard/too_easy; then `review → done`. The scenario is `is_free:false`
  with calibration pending — validate before launch (the whole point of 6.15).
- **DX fix:** `python` was hitting the Windows Store stub; `scripts\build.cmd` + `scripts\calibrate.cmd`
  call the venv python directly so Walid never types the full path.
- **DX fix 2 (post first live run):** the dev tools were constructing the FULL prod `config.Settings`
  (which requires Soniox / LiveKit / JWT / Resend), so they refused to run on a local `.env` that only
  has the LLM key. Added `calibration_engine.load_llm_settings()` — a minimal LLM-only config (reads
  ONLY `GROQ_API_KEY` + optional `LLM_*`/`*_MODEL` overrides, defaults mirroring `config.Settings`).
  All three CLIs (`calibrate_scenario`, `build_scenario`, `simulate_conversation`) now use it, so the
  validator/builder run with just `GROQ_API_KEY` set — no full prod env needed. +3 unit tests.
- **Post-live-run fixes (2026-06-02, running the tool on Walid's real key surfaced 3 things):**
  1. **PROD BUG fixed — `classify_multi` `max_tokens` was a fixed 128**, too small for a 20-goal
     verdict object → Groq returned HTTP 400 `json_validate_failed` ("max completion tokens reached")
     on EVERY classify for a 20-checkpoint scenario (1 & 5 goals were fine). This would have broken
     the cop scenario in PROD too (all 20 pending early-game). Fixed in
     `pipeline/exchange_classifier.py`: `_multi_max_tokens(n) = 64 + 24·n` (6→208, 20→544) + a
     regression test. Also added the response **body** to the non-2xx log (a bare status hid the
     cause).
  2. **429 rate-limit storm** — NOT a bug: Walid's Groq plan is the FREE `on_demand` tier = **30
     requests/minute**. The validator makes many calls, so it now THROTTLES (default 2.1 s/call =
     under 30 RPM) + retries (`ResilientJudge` in `calibration_engine.py`; `--throttle-ms` to speed
     up on a paid tier). Live golden-only re-run after the fix: **0×429, 0×400**. Follow-up: the
     judge (Scout) and the character/learner LLM (70B) are SEPARATE rate buckets, so the full
     calibration also needed the chat path throttled — added `ResilientChat` (same throttle+retry),
     wrapping `chat_llm` in all three CLIs. **Cop golden-only on Walid's real free-tier key: ✅ PASS
     (0×429, 0×400, exit 0).** Full calibration on free tier is feasible but slow (~12-15 min at
     `--n 3`, ~30-40 min at the N=10 default); fast once Groq Dev tier is back (`--throttle-ms 200`).
     [Dev tier upgrade was temporarily unavailable 2026-06-02.] **Update:** the full cop calibration
     attempt then hit the HARDER free-tier limit — **100k tokens/DAY** on the 70B character model
     (`openai.RateLimitError` TPD) — which throttling can't fix. So the full difficulty-band
     calibration is **not feasible on the free tier at all** (needs Dev tier); `--golden-only` (Scout-
     only, cheap) is the working free-tier path and the cop already PASSED it. Added: graceful
     exit-code-3 + guidance on a rate/token limit (no traceback), and `max_turns` now scales with
     checkpoint count (`max(given, n+8)`) — the default 12 made a 20-step scenario un-survivable →
     false too_hard. See [[infra-groq-free-tier-rpm-limit]].
  3. **Windows emoji crash** — `print("✅…")` raised `UnicodeEncodeError` on the cp1252 console;
     `force_utf8_stdio()` now reconfigures stdout/stderr to UTF-8 at CLI start.
  - Also DX: the CLIs use `load_llm_settings()` (LLM-only minimal config) so they run with just
    `GROQ_API_KEY`, not the full prod env.
  - **Live proof on Walid's real key:** `calibrate_scenario waiter_easy_01 --golden-only` → **✅ PASS**
    (exit 0, 0 rate-limit / 0 bad-request). The cop golden-only works the same (the 20-goal classify
    was verified returning a full correct verdict) but takes ~3-4 min on the 30-RPM free tier (100
    calls); the FULL calibration is impractical on free tier (hundreds of calls) — use the Groq Dev
    tier or be patient. See [[infra-groq-free-tier-rpm-limit]].
- **Pre-commit:** ruff clean; safe non-livekit subset green (179 passed incl. the new builder +
  max_tokens regression tests). Full `pytest` reserved for Walid before `/commit` (sandbox livekit
  import hang).

### File List
**New — the builder:**
- `server/scripts/scenario_builder.py` — the engine (expand/draft/critique/assemble/validate/yaml +
  pure helpers).
- `server/scripts/build_scenario.py` — the CLI (fuzzy desc → YAML; `--dry-run`/`--validate`/`--overwrite`).
- `server/scripts/build.cmd`, `server/scripts/calibrate.cmd` — venv-python wrappers (Windows stub fix).
- `server/tests/test_scenario_builder.py` — mocked-LLM unit tests (14 for 6.16; the file now totals
  ~28+ incl. Story 6.17 voice/auto-repair tests bundled in commit `e258dbf`, +2 from the 2026-06-02 review).
- `server/pipeline/scenarios/cop-interrogation-01.yaml` — the worked-example scenario (20 checkpoints).

**Touched (post-live-run fixes):**
- `server/pipeline/exchange_classifier.py` — PROD fix: `_multi_max_tokens(n)` scales the multi-goal
  completion budget (`64 + 24·n`; was a fixed 128 → **544** on 20 goals) + non-2xx body logging.
- `server/scripts/calibration_engine.py` — `load_llm_settings()` (LLM-only config), `ResilientJudge`
  (throttle + retry for the free-tier 30-RPM limit), `force_utf8_stdio()`.
- `server/scripts/{calibrate_scenario,build_scenario,simulate_conversation}.py` — use the minimal
  config + UTF-8 + the resilient judge.
- `server/tests/test_exchange_classifier.py` — `_multi_max_tokens` regression test.

**Docs / tracking:**
- `_bmad-output/implementation-artifacts/6-16-scenario-builder.md` — this story.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — status flips.

## Change Log
- 2026-06-02 — Dev-story COMPLETE, `in-progress` → `review`. Built the scenario builder
  (`scenario_builder.py` + `build_scenario.py` + `.cmd` wrappers + 14 tests) and generated the
  worked cop/fingerprints artifact via a 7-agent adversarial workflow → `cop-interrogation-01.yaml`
  (20 distinct, time-advancing, non-collapsing checkpoints; loads through every prod loader). All 10
  ACs delivered. ruff clean; safe subset 193 passed. Live calibration of the new scenario + full
  pytest reserved for Walid.
- 2026-06-02 — Spec drafted + dev started (Walid ask, `/bmad-dev-story` continuation). Front half of
  the authoring loop (build → validate-via-6.15). Target: fuzzy premise → 20 coherent, time-advancing,
  discriminative checkpoints; worked example = the cop/fingerprints interrogation.

## Review Findings — /bmad-code-review (2026-06-02)

Three adversarial layers (Blind Hunter diff-only + Edge Case Hunter + Acceptance Auditor) on the 6.16 net-new scope (`scenario_builder.py` + `build_scenario.py` + `build.cmd` + `cop-interrogation-01.yaml` + `test_scenario_builder.py` + the PROD fix `exchange_classifier.py` + `test_exchange_classifier.py`). The "touched" files `calibration_engine.py`/`calibrate_scenario.py`/`simulate_conversation.py` were already covered in the Story 6.15 review, so they were NOT re-audited here. The Acceptance Auditor confirmed all 10 ACs delivered EXCEPT AC3's "exactly N" (verified absent via a fake-LLM test); AC2/AC4/AC5(efficacy)/AC6(timing)/AC9(live calibration) are legitimately UNVERIFIABLE without a live run. The cop artifact has exactly 20 unique checkpoints and loads through every prod loader; the PROD `_multi_max_tokens` fix is real (64+24·20 = **544** for 20 goals) and low-risk (only raises the ceiling). **3 patches, 11 deferred, 7 dismissed.**

### Patch (action items)
- [ ] [Review][Patch] **AC3 not enforced — a wrong checkpoint count ships silently** [server/scripts/scenario_builder.py:884 `finalize_build`] — neither `sanitize_checkpoints` nor `validate_structure` checks `len(checkpoints) == requested N`; the Auditor drove a fake LLM returning 3 when 20 requested → written with 3, `structural_problems` empty. AC3 says "exactly N". Fix: thread the expected count into `finalize_build` and append a structural problem on mismatch (blocks the write) + a regression test.
- [ ] [Review][Patch] **`--id` path traversal / unvalidated slug** [server/scripts/build_scenario.py:70 `_amain`; scenario_builder.py:1086 `default_scenario_path`] — `default_scenario_path` puts `--id` straight into the filename (only `_`→`-`), so `--id ../x` writes outside the scenarios dir, and the id flows unvalidated into the index key + metadata. Fix: reject an `--id` that isn't `^[a-z0-9_]+$` early in `_amain`.
- [ ] [Review][Patch] **Dev Agent Record accuracy** [6-16-scenario-builder.md] — File List says the prod fix is "→400 on 20 goals" but the code is 64+24·20 = **544** (the Completion Notes are right); test counts are stated as 14 / 179 / 193 but `test_scenario_builder.py` has 28 (≈14 of them are Story 6.17 voice/auto-repair tests bundled in the same file). Fix: correct 400→544 + clarify the count is bundled 6.16+6.17.

### Deferred (logged to deferred-work.md)
- [x] [Review][Defer] cop artifact has compound `PASS if (a) … AND (b) …` success_criteria the one-verdict-per-goal judge handles as a whole (harder, not unrepresentable) [cop-interrogation-01.yaml] — deferred, live calibration is the backstop
- [x] [Review][Defer] `critique_and_repair` silently no-ops on unparseable critique output; lexical-overlap is advisory only (doesn't block the write) [scenario_builder.py:critique_and_repair] — deferred, the 6.15 `too_easy` gate is the empirical backstop
- [x] [Review][Defer] `_multi_max_tokens` has no upper ceiling for huge N + its regression test only checks monotonicity/≥500, not that 544 actually holds a 20-goal verdict [exchange_classifier.py:134] — deferred, fine for realistic N
- [x] [Review][Defer] non-2xx body log (`response.text[:300]`) — low PII risk for `json_validate_failed` (model output, not user input), other 4xx bodies unverified [exchange_classifier.py:440] — deferred, consider debug-level
- [x] [Review][Defer] `parse_json_array`/`parse_json_object` greedy bracket span breaks on stray brackets in LLM prose [scenario_builder.py:783] — deferred, operator sees the error
- [x] [Review][Defer] `expand_brief` trusts keys blindly → a brief missing `arc`/`canonical_facts` yields a hollow scenario that passes structural validation [scenario_builder.py:expand_brief] — deferred, calibration catches a hollow scenario
- [x] [Review][Defer] `sanitize_checkpoints` dedupe can mangle ids on degenerate LLM output (foo,foo,foo_2→foo_2_2) [scenario_builder.py:331] — deferred, low frequency
- [x] [Review][Defer] `suggest_patience_start` absorbs ~3 misses regardless of length; the long-scenario bump is cosmetic vs its docstring [scenario_builder.py:420] — deferred, it's a seed; calibration tunes
- [x] [Review][Defer] `--deploy` (Story 6.17) deploys to prod root with no confirmation, `StrictHostKeyChecking=no`, NOT gated on `--validate`/golden, overwrites prod with no backup [build_scenario.py:41,156] — deferred, revisit in the 6.17 review
- [x] [Review][Defer] `--out` can overwrite an unrelated existing YAML (`--overwrite` only guards the index id, not an arbitrary `--out`) [build_scenario.py:129] — deferred, trusted operator
- [x] [Review][Defer] Story 6.17 code in 6.16-attributed files (auto-repair loop id-drift, voice-fetch shape) to be reviewed under the 6.17 review [scenario_builder.py, build_scenario.py] — deferred to the 6.17 review

### Dismissed (7 — false positives / working-as-specified)
- BH#5 `validate_structure` "weaker fork" — Auditor verified byte-identical speak-first guard + identical difficulty/character/required-field rules; the unmirror'd rules (patience/exit_lines shape) are builder-CONSTRUCTED, so it cannot emit a value prod rejects. No fork.
- BH#9 deploy shell injection — `subprocess.run` uses an argv LIST (no local shell); the remote-path risk is mitigated by the P2 snake_case `--id` guard + trusted operator.
- BH#10 auto-repair loop "dead code" — it's Story 6.17 functionality reached via `new_scenario.py` (the wizard), not 6.16's CLI; reviewed under 6.17.
- BH#16 `_data_from_result` passes `patience={}`/re-derived difficulty — immaterial: `run_golden` uses only title + checkpoints, not patience/difficulty.
- BH#15 YAML representer block-scalar only on `\n` — cosmetic; output is valid YAML.
- BH#17 `ScriptedLLM` clamps its index — minor test-harness point; the call count IS pinned in the main pipeline test.
- ECH `--checkpoints 0`/negative — n=0 yields an empty list which `validate_structure`'s "non-empty list" rule already rejects.
