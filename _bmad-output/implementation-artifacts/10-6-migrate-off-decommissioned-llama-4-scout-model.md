# Story 10.6: Migrate off the decommissioned Llama 4 Scout model

Status: ready-for-dev

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

- [ ] **Task 1 — Swap the model defaults** (AC: 1)
  - [ ] `server/config.py:207` `classifier_model` default → `"openai/gpt-oss-20b"`; `:216` `debrief_model` default → `"openai/gpt-oss-120b"`. Leave `:221` `character_model` untouched.
  - [ ] Set `CLASSIFIER_MODEL` + `DEBRIEF_MODEL` in the VPS `/opt/survive-the-talk/shared/.env` (or the live `.env`) so the running service uses them even before the next code default ships.
- [ ] **Task 2 — Wire `reasoning_effort: low`** (AC: 2, 3)
  - [ ] Judge: add `"reasoning_effort": "low"` to the payload in `pipeline/exchange_classifier.classify_multi` (and the legacy `classify` if it shares the path), gated to gpt-oss models (`if "gpt-oss" in model`).
  - [ ] Debrief: add the same to BOTH payloads in `pipeline/debrief_generator._generate` (`strict_payload` and `fallback_payload`), gated to gpt-oss.
  - [ ] Verify no `finish_reason=="length"` on representative inputs; bump `max_tokens` (judge verdict cap; debrief `_MAX_TOKENS=3072` at `debrief_generator.py`) only if truncation is observed, and record the new value.
- [ ] **Task 3 — Validate the judge on the prod path** (AC: 4, 5)
  - [ ] `cd server && python scripts/calibrate_scenario.py` (golden-only sweep first, then a full sweep on a representative scenario) with the new judge model; paste PASS/FAIL.
  - [ ] Confirm the multi-goal verdict is schema-clean (no all-None) — a live `classify_multi` exercise or a targeted run; assert ids echo back exactly.
- [ ] **Task 4 — Confirm debrief acceptance** (AC: 6)
  - [ ] `DEBRIEF_MODEL=openai/gpt-oss-120b python scripts/probe_debrief_schema.py` → exit 0. (Already passed once on 2026-06-25; re-run from the final code.)
- [ ] **Task 5 — Prompt re-tune if needed** (AC: 4, 5)
  - [ ] If the calibration sweep reveals accuracy drift, lightly re-tune `EXCHANGE_CLASSIFIER_MULTI_PROMPT` / `DEBRIEF_SYSTEM_PROMPT` for gpt-oss (the prompts were written for Qwen/Llama; `/no_think` is a Qwen-ism, inert here). Keep persona difficulty-neutral (server/CLAUDE.md §8). If you edit `DEBRIEF_SYSTEM_PROMPT`, update the authoritative `planning-artifacts/debrief-generation-prompt.md` to stay byte-identical (the drift-guard test `test_system_prompt_matches_authoritative_doc`) and bump `DEBRIEF_PROMPT_VERSION`.
- [ ] **Task 6 — Docs + memory** (AC: 8)
- [ ] **Task 7 — Gates + deploy** (AC: 7, 9) — ruff + pytest green; push to `main` (CI auto-deploys `server/**`); then the Smoke Test Gate below.

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

### Debug Log References

### Completion Notes List

### File List
