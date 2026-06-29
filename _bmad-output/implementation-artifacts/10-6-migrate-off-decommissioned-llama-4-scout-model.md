# Story 10.6: Migrate off the decommissioned Llama 4 Scout model

Status: in-progress

> 🟢 **2026-06-29 — FINAL RUNTIME = OpenAI `gpt-4.1-mini` (all 3 roles). READ THIS FIRST.**
> Supersedes BOTH the gpt-oss-on-Groq decision (ACs/Tasks below) AND the
> 2026-06-26 Gemini 2.5 banner beneath this one. Committed in `7487186`
> (`config.py` + `exchange_classifier` + `calibration_engine` flipped to OpenAI;
> `llm_base_url=api.openai.com`; the VPS already runs this via `.env`, so
> git == prod). gpt-4.1-mini supports strict `json_schema` NATIVELY and is NOT a
> reasoning model. The Acceptance Criteria (AC1–AC9) + Tasks below are the
> HISTORICAL gpt-oss dev record — read them as such (the Story statement's
> "Groq replacement models" is likewise historical).
>
> **Code-review reconciliation (2026-06-29, claude-opus-4-8 — see Review Findings
> at the bottom).** Applied: removed the dead gpt-oss/Gemini `reasoning_effort`
> gating (D2); tried cutting `_CLASSIFIER/_HTTP_TIMEOUT_SECONDS`
> 4.5/4.0→2.5/2.0 s then REVERTED to 4.5/4.0 s after a live VPS golden sweep
> measured the gpt-4.1-mini judge at ~2 s/call (2.0 s HTTP → ~2 % fail-open) (D3);
> made the never-silent floor PER-SCENARIO (D4); hardened
> the §9 scenario lints (P3); reconciled every stale gpt-oss/Groq/Gemini comment
> in `config.py` / `exchange_classifier` / `debrief_generator` / `probe` /
> `server/CLAUDE.md` §4+§9 to gpt-4.1-mini (P1).
> **🚨 SMOKE GATE FAILED (Pixel 9, call_id=340, 2026-06-29) — back to `in-progress`.**
> The checkpoint experience is broken: the judge credited `confirm` on "No other
> choice." and `close` on "No other choice. Is it a question?" — weak/nonsensical
> input completing the scenario. ROOT CAUSE: the `success_criteria` are authored
> FAR too permissively (waiter `confirm`: "Any acknowledgement of the order summary
> counts"; `close`: "Even a simple okay or thanks counts"), so the precise
> gpt-4.1-mini judge follows them literally. NOT a model bug — a SCENARIO-AUTHORING
> bug (conflates "easy difficulty" with "accept anything"; §8 says easy forgives
> LANGUAGE, not wrong content). This is BROADER than the golden's opening beats
> (confirm/close + likely every scenario). **MVP BLOCKER.** Fix = (1) stiffen the
> judge prompt `EXCHANGE_CLASSIFIER_MULTI_PROMPT` to credit ONLY genuine goal
> accomplishment, (2) rewrite the over-permissive `success_criteria` across
> scenarios to require the goal actually done, then re-run the §6 golden + re-smoke.
> This is a DEV story (10-7, scope expanded from "openings" to all loose criteria)
> — a SEPARATE agent/session per the one-agent-per-workflow rule. 10.6's migration
> CODE stays correct + deployed; it just can't flip `done` until the experience is
> fixed. (The D3 timeout retune was already reverted to 4.5/4.0 after the live
> sweep measured the judge at ~2 s/call.)
>
> **🚨 SECOND smoke-gate blocker (same call 340) — the DEBRIEF never produces a
> real recap.** Logs: `debrief_generation failed (non-fatal): (ReadTimeout)` →
> `generation returned None → storing a degraded (score-only) debrief`. The full
> ~2-3k-token structured debrief takes LONGER than the debrief's 7.5 s HTTP /
> 14 s outer budget on gpt-4.1-mini, so EVERY recent call falls back to the
> score-only degraded debrief (no analysis). Pre-existing from the model swap
> (`7487186`), NOT the review patches (debrief_generator timeouts were untouched).
> Fix: raise `_HTTP_TIMEOUT_SECONDS` (7.5→~20 s) + `_GENERATION_TIMEOUT_SECONDS`
> (14→~25 s) — the debrief is overlay-masked / non-blocking — AND check the
> CLIENT poll budget (Story 7.3 = ~30 s) so it doesn't give up first; possibly
> trim the debrief size. Folds into the 10-7 fix (or a 10.6 follow-up). Both
> device blockers (loose criteria + debrief timeout) must clear before `done`.

> ⚠️ **2026-06-26 — DECISION SUPERSEDED + SCOPE EXPANDED. READ THIS FIRST.**
> The locked gpt-oss decision further below is **OBSOLETE**. Groq is being LEFT
> ENTIRELY (its paid tier stays walled), so judge + debrief no longer move to
> gpt-oss-on-Groq. **Current runtime = Google Gemini 2.5** (deployed for test on the
> VPS, validated on device for the waiter). Switching providers also uncovered a
> class of model-specific scenario bugs, now governed by **server/CLAUDE.md §9
> (scenarios MUST be model-agnostic + correct-by-construction)**.
>
> **DECISION (2026-06-26):** all 3 roles → **Gemini 2.5** via the OpenAI-compatible
> endpoint (`…/v1beta/openai`): `CHARACTER_MODEL = CLASSIFIER_MODEL = DEBRIEF_MODEL =
> gemini-2.5-flash`; judge + debrief send `reasoning_effort:"none"`. Why: live-proven
> on our EXACT strict schemas (true constrained decoding, `["string","null"]` union
> OK); OpenAI-compatible (near-zero code); char TTFT ~480ms; self-serve paid (Cloud
> billing). Mistral was tried first (cheapest) but set aside on quality (judge
> timeouts, abuse false-positives, terse persona). NOTHING matches Groq's ~120ms
> judge with reliable paid quota — the ~800ms Gemini judge is an ACCEPTED regression
> (fail-open / non-blocking). `VERDICT_WAIT_BUDGET_MS` stays the calibrated 800.
>
> **DONE this session (code edited on disk, NOT YET COMMITTED — see Task C):**
> - Gemini thinking-control: `_reasoning_effort_for` in `exchange_classifier.py` +
>   `debrief_generator.py` (judge fast; debrief no longer times out → real report).
> - Scenario model-agnostic hardening (server/CLAUDE.md §9, rules R1-R6):
>   R1 `/no_think` purged from ALL 5 YAMLs + `prompts.SARCASTIC_CHARACTER_PROMPT`,
>   `find_model_specific_tokens` guardrail (builder hard-fail + loader warn + commit
>   test `test_shipped_scenarios_have_no_model_specific_tokens`); R2/R3 waiter
>   `confirm` de-scripted + `clarify` no longer invents pasta varieties; R4
>   COHERENCE_CHARTER rule 9 (always speak); R5 abuse prompt hardened (validated:
>   frustration/flirt ≠ abuse, real abuse still caught); R6 waiter `clarify` drives
>   forward + builder `CHECKPOINTS_PROMPT` carries R1/R2/R3/R6.
> - `/opt/survive-the-talk/reset-quota.sh` fixed (was hardcoded `user_id=1` → now by
>   email, so account re-creation never breaks it again).
> - Waiter validated clean on device (call 333 "survived": pasta→drink drive,
>   coherent confirm, real debrief). 347+ unit tests green, ruff clean.
>
> **REMAINING before MVP — the tracked task list (do in order):**
> - **Task A — PAID Gemini key.** We're on the FREE tier (503 "high demand" risk on
>   real users). Enable Google Cloud billing + set the paid key in the VPS `.env`.
>   Walid-owned (billing + key). **Blocking for production.**
> - **Task B — Audit + fix the OTHER 4 scenarios** (cop, girlfriend, landlord,
>   mugger) against R1-R6 + their inventory. They only got the `/no_think` purge and
>   likely share the waiter's R2/R3/R6 defects. Each: fix → `calibrate_scenario`
>   (golden + band) → Pixel 9 smoke.
> - **Task C — Consolidate + commit + REAL deploy.** The VPS runs scp'd file PATCHES
>   that diverge from git `current` (pre-gpt-oss); a real deploy would overwrite them.
>   Commit everything above (commit-per-stage rule), update `config.py` defaults to
>   Gemini, run the full deploy so **git == prod**. (Until then prod is fragile.)
> - **Task D — Harden R2/R3 into automatic lints** (today they are builder-prompt
>   guidance only; R1/R4/R5 are already code-enforced).
> - **Task E — Noise/STT phantom turns**: Soniox transcribes ambient noise into
>   "Hmm."/"Um, okay." → the character answers a non-existent turn. VAD/STT tuning —
>   PROPOSE before touching calibrated thresholds (`stop_secs`/`user_speech_timeout`).
> - **Task F — Persona quality pass** ("pas la folie") across all scenarios on Gemini.
> - **Re-validate** debrief + judge latency over a few on-device calls once A-C land.

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

### Review Findings

> Code review 2026-06-29 (claude-opus-4-8). Scope = the full story-10.6 NET arc `61a620e..HEAD` (Scout → gpt-oss/Groq → Gemini 2.5 → **final: OpenAI `gpt-4.1-mini` for all 3 roles**). 3 adversarial layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor), per-finding source verification. Triage: 4 decision-needed, 3 patch, 0 defer, 3 dismissed. **Functional end-state is defensible** (strict `json_schema` judge+debrief paths intact + unconditional, non-strict debrief fallback preserved per §4, provider switch is env-driven with no hardcoded-Groq POST path, gpt-4.1-mini natively supports strict structured output, 6 scenarios lexically clean). The issues are a pervasive **half-migration of comments/docs/laws**, **dead `reasoning_effort` gating**, an **unvalidated judge on the §6 net for the shipped model**, and **story bookkeeping two pivots stale**.

**Resolution (2026-06-29 — Walid decided the 4 decisions; the 6 patches batch-applied, gates green):**

- **D1 (judge §6 validation) → RAN on the live VPS (gpt-4.1-mini, 2026-06-29): golden 3/6.** ✅ PASS: `cop_interrogation_01`, `landlord_hard_01`, `waiter_easy_01`. ❌ FAIL: `cop_hard_01` (2), `girlfriend_medium_01` (1), `mugger_medium_01` (4) — but EVERY failure is the OPENING `react`/`respond` beat (`checkpoints[0]`) accepting generic small-talk ("I think the traffic was terrible this morning", "Did you watch the game last night?") as "engagement". This is a **pre-existing, model-agnostic permissive-opening-criteria looseness** (the sprint log already flagged mugger/cop openings as permissive pre-migration), **NOT a gpt-4.1 regression** — the judge correctly rejects off-topic on every TIGHTER criterion and on the later beats of the failing scenarios. (Timeouts can't cause this: a timeout → no credit, the safe direction.) **DECISION (Walid 2026-06-29): SHIP 10.6** — the migration is sound; the 3 permissive opening `react`/`respond` criteria (cop_hard / girlfriend / mugger) are tightened in **10-7** (which already carries the broader gpt-4.1 judge mis-credit). Story flipped `in-progress → review`; the ONLY remaining gate for `review → done` is the **Pixel 9 smoke gate**.
- **D2 (dead reasoning gating) → DELETED.** Removed `_is_gpt_oss` / `_reasoning_effort_for` / `_GPT_OSS_REASONING_HEADROOM` + the `_multi_max_tokens(model=…)` headroom + the `reasoning_extra` spreads + the probe gating, across `exchange_classifier.py`, `debrief_generator.py`, `probe_debrief_schema.py` (+ their tests).
- **D3 (terminal dead-air) → tried 2.5/2.0 s, then REVERTED to 4.5/4.0 s after live measurement.** The retune to 2.5/2.0 s was caught wrong by the D1 golden run: a live VPS sweep measured the gpt-4.1-mini judge at **~2 s/call**, so the 2.0 s HTTP budget clipped the tail (~2 % fail-open). Restored to the proven 4.5/4.0 s (near-zero fail-opens); the terminal-stall worry is rare at OpenAI latency (normal calls land ~2 s, well under the ceiling — the ~9 s case needs back-to-back infra failures, not slowness). The surgical option (cap only the terminal blocking path) is noted in-code if ever needed. Still corrected the false "zero reply latency" comment.
- **D4 (`"Go on."` floor) → PER-SCENARIO.** `ReplySanitizer(fallback_line=…)` wired from a new optional YAML `never_silent_fallback`; in-character lines authored for all 6 scenarios (global `"Go on."` kept only as the default for un-authored scenarios).
- **P1/P2/P3 → APPLIED.** P1: every stale gpt-oss/Groq/Gemini comment reconciled to gpt-4.1-mini (`config.py`, `exchange_classifier`, `debrief_generator`, `probe`, `server/CLAUDE.md` §4+§9, R1→historical). P2: this story re-anchored (top banner). P3: `_TEMPLATE_PLACEHOLDER_RE` broadened (leading space/digit no longer evades) + `success_criteria` now scanned (builder + commit test) + model-token scan widened to `briefing`/`exit_lines`/`never_silent_fallback`.
- **Gates:** `ruff check` + `ruff format --check` clean; full `pytest` green.

---

**Decision-needed:**

- [ ] [Review][Decision] **Judge accuracy on the shipped model is unvalidated against the §6 golden net** — `calibrate_scenario.py` was NEVER run on `gpt-4.1-mini`; AC4/AC5 are marked `[x]` on obsolete `gpt-oss-20b` evidence, and a known gpt-4.1 judge mis-credit (too-strict / too-loose) is backlogged to story 10-7. This is the strongest stop-ship for a `review→done` flip. Decide: run the golden net + banded sweep on gpt-4.1-mini before flipping, OR fold it into the owed VPS smoke gate / 10-7. [CLAUDE.md §6; scripts/calibrate_scenario.py]
- [ ] [Review][Decision] **Dead `reasoning_effort` / headroom gating** — `_is_gpt_oss` / `_reasoning_effort_for` only return non-None for `gpt-oss` / `gemini-2.5`, so on the shipped `gpt-4.1-mini` the entire Story-10.6 reasoning machinery (`reasoning_effort`, `_GPT_OSS_REASONING_HEADROOM`, `_multi_max_tokens` headroom, legacy-`classify` headroom, probe gating) is inert. Risk seed: pointing `CLASSIFIER_MODEL`/`DEBRIEF_MODEL` at a real OpenAI reasoning model (`o4-mini`, `gpt-5*`) via `.env` would size `max_tokens` with zero reasoning headroom → truncation. Decide: keep as clearly-commented rollback scaffolding (and generalize to `_is_reasoning_model`), or delete. [exchange_classifier.py:133-150, debrief_generator.py:82-99]
- [ ] [Review][Decision] **Terminal-turn dead air** — `_CLASSIFIER_TIMEOUT_SECONDS` was raised 2.0→4.5s (commit 6fdb220) for the now-abandoned **Gemini** era; the terminal-turn path awaits the classify under this timeout, so a single OpenAI error/429 on a CALL-ENDING turn can stall ~9s (2×4.5 with the Story-6.27 first-call retry). The in-code "adds zero reply latency (gated by 800ms)" comment is FALSE for the terminal path. Decide: re-tune the timeout down for fast OpenAI, cap `_run_classifier_blocking` with its own short wall-clock, or accept. (Touches calibrated thresholds → proposing, not auto-changing.) [exchange_classifier.py:226 → checkpoint_manager.py:799-830]
- [ ] [Review][Decision] **`_NEVER_SILENT_FALLBACK = "Go on."` is one global English filler** pushed for every character when a reply is all-meta — for a mugger/detective mid-threat it breaks persona, and "Go on." wrongly invites the user to keep talking. Already on-device validated (call-335) as a never-silent floor. Decide: keep the global floor or make it scenario/character-driven. [reply_sanitizer.py:106,260,343]

**Patch:**

- [ ] [Review][Patch] Reconcile stale comments/docstrings that LIE about the runtime model (gpt-oss/Groq/Gemini → `gpt-4.1-mini`, AC8) — incl. the false "zero reply latency" comment [server/config.py:191-235, server/pipeline/exchange_classifier.py:112-121 + module docstring + strict-schema comment, server/pipeline/debrief_generator.py:854-893, server/CLAUDE.md §4 + §9 + R1 box]
- [ ] [Review][Patch] Re-anchor the story doc to the gpt-4.1-mini end-state — the Story statement still says "law-compliant **Groq** replacement models", the "READ THIS FIRST" banner still says **Gemini 2.5**, and AC4/5/6 evidence cites gpt-oss [10-6-migrate-off-decommissioned-llama-4-scout-model.md]
- [ ] [Review][Patch] Harden the §9 model-agnostic lints — `_TEMPLATE_PLACEHOLDER_RE` misses brackets with a leading space/digit and never scans `success_criteria`; the `find_model_specific_tokens` commit test skips `briefing`/`exit_lines` (latent — current 6 scenarios are clean) [server/pipeline/scenarios.py:283-285, server/scripts/scenario_builder.py:2087, server/tests/test_scenarios.py]

**Dismissed (noise / false-positive):** (1) debrief test pinning a Groq URL + `gpt-oss-120b` — it's a legitimate unit test of the `_is_gpt_oss` gating branch (forces the model); coupled to the dead-gating decision, not a standalone bug. (2) `test_settings_..._default_to_groq` rename + orphaned `emotion_model` Groq id — intentional, nothing reads it. (3) never-silent fallback emitted as a bare `TextFrame` vs `LLMTextFrame` — speculative; fine for the current one-word literal.
