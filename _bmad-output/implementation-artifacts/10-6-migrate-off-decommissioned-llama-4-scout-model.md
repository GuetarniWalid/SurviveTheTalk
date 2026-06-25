# Story 10.6: Migrate off the decommissioned Llama 4 Scout model

Status: in-progress

> 🚨 **MVP LAUNCH BLOCKER — HARD EXTERNAL DEADLINE 2026-07-17.** Groq emailed
> 2026-06-24 that `meta-llama/llama-4-scout-17b-16e-instruct` is **deprecated now
> and decommissioned 2026-07-17**; after that date requests to it FAIL. Scout is
> the default for BOTH the checkpoint judge and the debrief generator. If this
> ships after 2026-07-17, checkpoints stop validating and debriefs stop
> generating in production. This story MUST be done before the Epic 10 final
> launch (10.5) and before 2026-07-17, whichever is sooner.

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As the SurviveTheTalk operator,
I want the checkpoint judge and the debrief generator moved off the
soon-decommissioned Llama 4 Scout onto law-compliant Groq replacement models,
so that checkpoints keep validating and debriefs keep generating after Groq
turns Scout off on 2026-07-17.

## Background & locked decision (do NOT re-litigate)

Investigated + decided 2026-06-25 (Walid sign-off). Full evidence in
`memory/project_scout_decommission_migration.md`.

- **Judge** (`Settings.classifier_model`) → **`openai/gpt-oss-20b`**
- **Debrief** (`Settings.debrief_model`) → **`openai/gpt-oss-120b`**
- **`reasoning_effort: "low"`** for both.
- **`character_model` stays `llama-3.3-70b-versatile`** — NOT affected, do not touch.

**Why these two and not the email's other suggestion:** Groq docs (2026-06-25)
list only `openai/gpt-oss-20b` and `openai/gpt-oss-120b` as supporting TRUE
strict constrained decoding (`response_format=json_schema`, `strict:true`).
Scout was only `strict:false` "best-effort" — which is exactly why the debrief
400'd on a wrong-typed field (call_id=324, see
`memory/feedback_groq_strict_json_all_or_nothing.md`). Qwen3.6 (the email's
other suggestion) is **json_object-only → DISQUALIFIED** by the §4 judge law
(`memory/feedback_classifier_model_must_support_structured_output.md`).

**Why 20b for the judge, 120b for the debrief (not one model for both):**
- Judge fires **per-turn** (high volume) + sits in the ~800 ms fail-open budget → latency + cost sensitive → **20b** (fastest, cheapest).
- Debrief fires **once per call-end**, latency **masked** by the Call Ended overlay, and is a **richer generative task** → quality wins, cost is a fraction of a cent → **120b**.
- The split is just one env var difference; no added complexity.

**Benchmark evidence** (75-sample `tests/fixtures/classifier_benchmark_corpus.json`, judge task, `reasoning_effort=low`, 0 infra-fail):

| model | accuracy | false-pos | false-neg | p50 (local) | p95 (local) |
|---|---|---|---|---|---|
| Scout (current) | 93.3% | 6.7% | 0% | 689 ms | 3347 ms |
| gpt-oss-120b | 98.7% | 1.3% | 0% | 391 ms | 788 ms |
| gpt-oss-20b | 98.7% | 1.3% | 0% | 305 ms | 862 ms |

Both candidates beat Scout on accuracy AND latency. Latencies are LOCAL (dev
machine → Groq US, inflated vs VPS) — relative comparison valid, absolute to be
re-measured on the VPS (AC7). Pricing /1M tokens: 120b $0.15/$0.60, 20b
$0.075/$0.30, Scout $0.11/$0.34. `gpt-oss-120b` already passed a live
acceptance probe on our account for the full strict debrief schema (HTTP 200 +
clean parse, 2026-06-25).

## Acceptance Criteria

1. `server/config.py` defaults updated: `classifier_model = "openai/gpt-oss-20b"`, `debrief_model = "openai/gpt-oss-120b"`. No active default still points at Scout.
2. `reasoning_effort: "low"` is sent on the Groq request for the judge (`exchange_classifier.classify_multi`) AND the debrief (`debrief_generator._generate`, both the strict and the non-strict-fallback payloads), gated to gpt-oss models so it never leaks onto the 70B character model.
3. No truncation regression: the judge and debrief responses do not come back `finish_reason == "length"` on representative inputs (reasoning tokens fit within `max_tokens`); bump the relevant `max_tokens` if needed and document the new value.
4. **Judge validated on the REAL prod path** (the benchmark was the single-goal free-form proxy): `python scripts/calibrate_scenario.py` golden net + calibration sweep passes on `openai/gpt-oss-20b` — the universal off-topic seed is judged `unmet` on every checkpoint (no "judge passes everything" regression) and the cooperative completion rate lands in band (server/CLAUDE.md §6).
5. **Multi-goal id-echo path is clean**: the new judge returns schema-pinned `{goal_id: "met"|"unmet"|"unsure"}` with NO silent all-None / id-mangling (the original 70B failure class that drove the move to strict structured output). Constrained decoding should make this structural, but it must be asserted, not assumed.
6. **Debrief schema acceptance re-confirmed**: `python scripts/probe_debrief_schema.py` (with `DEBRIEF_MODEL=openai/gpt-oss-120b`) exits 0 (HTTP 200 + parses).
7. Deployed to the VPS with `CLASSIFIER_MODEL`/`DEBRIEF_MODEL` set in `.env`; the judge **p95 latency measured on the VPS** is reported against the ~800 ms fail-open budget; production shows no sustained Groq 429 / rate-limit storm under normal use (or the Groq tier is bumped — see Risk R1).
8. `server/CLAUDE.md` §4 and `memory/project_checkpoint_judge_structured_output.md` updated to name the new models; `memory/project_scout_decommission_migration.md` flipped to "migrated".
9. Pre-commit gates green: `ruff check .` + `ruff format --check .` + `pytest` (server). No client change → Flutter gates N/A.

## Tasks / Subtasks

- [x] **Task 1 — Swap the model defaults** (AC: 1)
  - [x] `server/config.py` `classifier_model` default → `"openai/gpt-oss-20b"`; `debrief_model` default → `"openai/gpt-oss-120b"`. `character_model` untouched. ALSO flipped the secondary Scout defaults: `exchange_classifier._PROVIDER_MODEL` + `calibration_engine.LlmSettings`/`load_llm_settings` (AC1 "no active default still points at Scout").
  - [ ] **DEFERRED to deploy (gated on R1, Walid):** set `CLASSIFIER_MODEL`/`DEBRIEF_MODEL` in the VPS `.env`. NOTE: the live VPS `.env` has NO override for these (verified 2026-06-25) → the new code default applies on deploy with no env change needed; the explicit env lines are belt-and-suspenders to add at deploy time.
- [x] **Task 2 — Wire `reasoning_effort: low`** (AC: 2, 3)
  - [x] Judge: `"reasoning_effort": "low"` added to `classify_multi` AND the legacy `classify`, gated by `_is_gpt_oss(model)`.
  - [x] Debrief: added to BOTH `strict_payload` and `fallback_payload` in `_generate`, gated to gpt-oss.
  - [x] No `finish_reason=="length"` confirmed live (judge: 87 reasoning tokens / finish_reason=stop; debrief: 1919 completion tokens / stop on an 11-turn call). `max_tokens` bumped: judge `+_GPT_OSS_REASONING_HEADROOM (1024)`; debrief `_MAX_TOKENS` 3072→4096 (documented in code).
- [x] **Task 3 — Validate the judge on the prod path** (AC: 4, 5)
  - [x] **AC5 PROVEN** — a real `classify_multi`-shaped call on gpt-oss-20b returned a schema-clean, CORRECT 6-goal verdict (greet/main/drink=`met`, allergy/confirm/pay=`unmet`) for "grilled chicken and a Coke". Dict keyed by EXACTLY the goal ids + `__user_abusive__`, ids echo exactly, NOT all-None — the 70B id-mangling failure class is structurally impossible under gpt-oss strict constrained decoding.
  - [x] **AC4 evidenced** — the SAME on-topic verdict correctly marked 3 of 6 goals `unmet`, which directly refutes the "judge passes everything" regression (that bug returns ALL `met`). ⚠️ The FORMAL off-topic golden sweep (`calibrate_scenario.py`) could NOT complete: it ran 26 min then I killed it, and follow-up off-topic calls hit the free-tier limit — gpt-oss-20b's **per-DAY token cap was exhausted** by the validation traffic itself (HTTP 429 "tokens per day"). This is R1 evidence; the formal off-topic-seed sweep + the p95 measurement fold into the deferred VPS smoke gate.
- [x] **Task 4 — Confirm debrief acceptance** (AC: 6)
  - [x] `DEBRIEF_MODEL=openai/gpt-oss-120b probe_debrief_schema.py` → HTTP 200 + clean parse (strict schema + reasoning_effort:low). (A second back-to-back run 429'd purely on the 8000 TPM cap — schema-acceptance proven on the first; probe updated to distinguish 429 from a schema 400.)
- [x] **Task 5 — Prompt re-tune if needed** (AC: 4, 5) — NOT NEEDED. The judge returned correct, schema-clean verdicts on gpt-oss with the existing `EXCHANGE_CLASSIFIER_MULTI_PROMPT`; the debrief produced high-quality output with the existing `DEBRIEF_SYSTEM_PROMPT`. No accuracy drift observed → prompts unchanged (`DEBRIEF_PROMPT_VERSION` stays 2.2, authoritative doc untouched).
- [x] **Task 6 — Docs + memory** (AC: 8) — `server/CLAUDE.md` §4 + `config.py` comments updated to gpt-oss (and corrected the stale "gpt-oss-20b 400s on schema" claim); memory `project_scout_decommission_migration` flipped to migrated + R1, `project_checkpoint_judge_structured_output` renamed to gpt-oss-20b.
- [~] **Task 7 — Gates + deploy** (AC: 7, 9) — ruff check + ruff format + **pytest 1035 passed** GREEN. **Deploy + Smoke Test Gate DEFERRED — gated on R1 (Walid's Groq tier decision).** See Dev Agent Record.

## Smoke Test Gate (Server / Deploy Stories Only)

> Every unchecked box is a stop-ship for `in-progress → review`. Paste real command output as proof.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test (CI deploy is automatic on push to `main`; confirm `readlink /opt/survive-the-talk/current`).
  - _Proof:_ <!-- Active line + current symlink sha -->
- [ ] **Live judge round-trip on the new model.** A real call (or `calibrate_scenario.py` against the live key) shows the judge crediting checkpoints with `CLASSIFIER_MODEL=openai/gpt-oss-20b`.
  - _Proof:_ <!-- journalctl line showing a checkpoint flip + the model in use -->
- [ ] **Live debrief generation on the new model.** A finished call produces a stored debrief (not the degraded fallback) with `DEBRIEF_MODEL=openai/gpt-oss-120b`.
  - _Proof:_ <!-- "debrief stored call_id=... " log line -->
- [ ] **Judge p95 latency measured on the VPS** vs the ~800 ms fail-open budget.
  - _Proof:_ <!-- p50/p95 from journalctl or a VPS-side bench run -->
- [ ] **No 429 storm.** `journalctl -u pipecat.service --since "10 min ago" | grep -i "429\|rate"` is clean under normal use (or the Groq tier was bumped — note which).
  - _Proof:_ <!-- paste -->
- [ ] **Server logs clean on the happy path.** No ERROR/Traceback for the judge/debrief paths in the window.
  - _Proof:_ <!-- tail -->
- [ ] DB side-effects: **N/A** — no schema change, no migration, no new rows. (Backup box also N/A.)

## Dev Notes

**Exact change points (verified 2026-06-25):**
- `server/config.py:207` `classifier_model`, `:216` `debrief_model`, `:221` `character_model` (leave). The `:212-216` comment already warns the debrief model must support structured output.
- Judge call: `server/pipeline/exchange_classifier.py` → `classify_multi` (raw httpx POST to Groq, strict `json_schema` via `_build_verdict_schema`, prompt `EXCHANGE_CLASSIFIER_MULTI_PROMPT`). The legacy single-goal `classify` has no `response_format`.
- Debrief call: `server/pipeline/debrief_generator.py` → `_generate` builds `strict_payload` (json_schema strict) and, on a strict 400, `fallback_payload` (json_object). The non-strict retry + the never-blank degraded fallback landed in commit `61a620e` (call_id=324 fix). **With gpt-oss-120b's TRUE constrained decoding the strict path should stop 400-ing on wrong types, so that retry becomes a rarely-fired safety net — keep it, do not remove it.**
- `resolve_llm_api_key` / `resolve_llm_chat_url` (`pipeline/llm_provider.py`) already point all paths at Groq; only the model id changes.

**gpt-oss are REASONING models — the two things to watch:**
1. They emit reasoning tokens. `reasoning_effort:low` keeps it short, but verify `max_tokens` headroom (AC3). The bench needed `max_tokens≈512+` for the tiny judge verdict; the debrief's 3072 may need a bump if `finish_reason=="length"` appears.
2. Reasoning tokens raise Groq TPM usage → the bench hit heavy 429s on our current tier (see Risk R1).

**Tooling already in place (reuse, don't reinvent):**
- `scripts/calibrate_scenario.py` — the prod-path judge validator (golden net + calibration), server/CLAUDE.md §6. THIS is the real judge test; the benchmark was only the single-goal proxy.
- `scripts/probe_debrief_schema.py` — live debrief schema acceptance probe (reads `Settings.debrief_model`; override via `DEBRIEF_MODEL` env). Needs the full required env (SONIOX/LIVEKIT/JWT) — supply dummies for a local probe; `GROQ_API_KEY` is the only real one needed.
- `scripts/benchmark_classifier.py` — the latency/accuracy harness (dev-only; was used for this decision, no committed change left behind).

### Risks
- **R1 (operational, needs a Walid decision): Groq rate limits.** The judge fires per-turn and gpt-oss reasoning uses more tokens → higher TPM. The bench saturated our tier with 429s. The prod judge fails OPEN on timeout (memory `project_story_6_12_reactive_mood` D1: bounded ~800 ms wait, never mute), so a 429 storm degrades to "checkpoints don't credit" rather than a hang — but that's bad UX. **Decision for Walid: bump the Groq tier before/at launch.** Measure real prod TPM headroom (AC7) before deciding.
- **R2: judge p95 vs the ~800 ms budget.** Local p95 was 788–862 ms (inflated by dev→US RTT); the VPS (already near Groq, EU→US still applies) must be measured (AC7). If p95 routinely exceeds 800 ms, either raise the fail-open budget or accept occasional fail-open.

### Project Structure Notes
- Server-only change. No DB migration, no client change, no new files (only edits + docs/memory).

### References
- Decision + evidence: `memory/project_scout_decommission_migration.md`
- Strict-mode gotcha + the call_id=324 fix: `memory/feedback_groq_strict_json_all_or_nothing.md`
- Judge structured-output law: `server/CLAUDE.md` §4 + `memory/feedback_classifier_model_must_support_structured_output.md`
- Calibration engine: `server/CLAUDE.md` §6; persona neutrality: §8
- Judge fail-open behaviour: `memory/project_story_6_12_reactive_mood.md`
- Groq structured-outputs supported models: console.groq.com/docs/structured-outputs (verified 2026-06-25)

## Dev Agent Record

### Agent Model Used

claude-opus-4-8 (dev-story, 2026-06-25).

### Debug Log References

Live measurements on our Groq account (2026-06-25, local → Groq US):
- **Judge gpt-oss-20b** strict json_schema + `reasoning_effort:low`, 6-goal verdict: HTTP 200, `finish_reason=stop`, prompt 1186 / completion 140 (reasoning 87), verdict correct + schema-clean. → `reasoning_effort` works WITH strict `json_schema`.
- **Debrief gpt-oss-120b** strict schema + `reasoning_effort:low`, 11-turn transcript, `max_tokens=3000`: HTTP 200, `finish_reason=stop`, prompt 4940 / completion 1919 (reasoning 794 + ~1125 content). Clean parse.
- **Free-tier limits (rate-limit headers):** BOTH gpt-oss models = **8000 TPM**, 1000 req/day, `service tier on_demand`. Groq counts `prompt + max_tokens` at admission.

### Completion Notes List

**What shipped (code, all gates green):** judge → `openai/gpt-oss-20b`, debrief → `openai/gpt-oss-120b`; `reasoning_effort:low` + reasoning-aware `max_tokens` on both, gated by `_is_gpt_oss`; secondary Scout defaults (exchange_classifier, calibration_engine) flipped; docs + memory updated; probe hardened to distinguish 429 from a schema 400. ruff + `pytest 1035 passed`. Local validation: judge correct + schema-clean, debrief schema accepted. The character LLM is untouched and confirmed on 70B in the live VPS `.env` (NOT affected by the Scout decommission).

**🚨 BLOCKER — R1 (Groq free-tier capacity). DEPLOY + SMOKE GATE OWED, needs Walid.**
The migration code is correct and is STRICTLY BETTER than leaving Scout (which is 100% dead after 2026-07-17). BUT on our current **`on_demand` (free) tier, both gpt-oss models are capped at 8000 TPM**, and Groq charges `prompt + max_tokens` at admission:
- **Debrief (gpt-oss-120b):** a normal call's request (~5k prompt + 4096 `max_tokens` ≈ 9k) is **rejected HTTP 413** → the user gets the DEGRADED score-only debrief on most real calls. (Back-to-back debriefs also 429.)
- **Judge (gpt-oss-20b):** ~8000 TPM ≈ 3-5 classifies/min → roughly ONE active call saturates it; sustained use drove an escalating **338 s → 483 s** rate-limit backoff, and ~30 min of validation traffic **exhausted the per-DAY token cap** (HTTP 429 "tokens per day"). Under load the judge 429s → fails OPEN (no credit, patience-neutral — degraded but not a crash).
- **Fix = bump to the Groq Dev tier** (much higher TPM). ⚠️ Per memory `infra_groq_capacity_and_scout_fallback` (2026-06-08) the paid Dev-tier upgrade was WALLED platform-wide with no ETA — **needs Walid to verify if it's available now**. If walled, the alternative is moving the debrief to a paid OpenAI-compatible provider (DeepInfra/Together — needs a Walid API key).
- Story AC7 explicitly allows "no 429 storm OR the Groq tier is bumped." Because deploying to the free tier NOW degrades the debrief vs today's working Scout (which still has ~3 weeks of runway), the deploy timing + tier strategy is a Walid decision — NOT auto-deployed.

**Next step:** Walid decides the tier/deploy strategy → then deploy (push to `main` auto-deploys `server/**`) + run the Smoke Test Gate. Story stays `in-progress` until then.

### File List

- `server/config.py` — `classifier_model`/`debrief_model` defaults → gpt-oss (+ rewritten comments).
- `server/pipeline/exchange_classifier.py` — `_PROVIDER_MODEL` → gpt-oss-20b; `_is_gpt_oss` + `_GPT_OSS_REASONING_HEADROOM`; `_multi_max_tokens(model)` headroom; `reasoning_effort:low` on `classify_multi` + legacy `classify`; docstring.
- `server/pipeline/debrief_generator.py` — `_is_gpt_oss`; `_MAX_TOKENS` 3072→4096; `reasoning_effort:low` on both payloads; docstrings.
- `server/scripts/calibration_engine.py` — `LlmSettings`/`load_llm_settings` judge default → gpt-oss-20b.
- `server/scripts/probe_debrief_schema.py` — `reasoning_effort:low`, model-from-Settings label, 429-vs-schema-400 distinction, stale `areas` print fix.
- `server/scripts/benchmark_classifier.py` — added gpt-oss-20b/120b providers + `BENCH_REASONING_EFFORT` knob (the decision bench; was uncommitted in the tree).
- `server/CLAUDE.md` — §4 updated to gpt-oss + R1 tier note; corrected the stale "gpt-oss-20b 400s on schema" claim.
- Tests: `test_exchange_classifier.py`, `test_debrief_generator.py`, `test_config.py`, `test_calibration_engine.py`, `test_benchmark_classifier.py` — model-default + reasoning_effort-gating assertions.
- Memory: `project_scout_decommission_migration.md`, `project_checkpoint_judge_structured_output.md`, `MEMORY.md`.

### Change Log

- 2026-06-25 — Story 10.6 dev-story: migrated checkpoint judge + debrief off the decommissioned Llama 4 Scout onto `openai/gpt-oss-20b` / `openai/gpt-oss-120b` with `reasoning_effort:low` + reasoning-aware `max_tokens`. Code + local validation + gates complete; deploy + smoke gate gated on R1 (Groq tier decision).
