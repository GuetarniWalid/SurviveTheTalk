# Story 7.1: Build Debrief Generation Backend

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want the server to analyze my call transcript and generate a detailed debrief report after each call,
so that I receive specific, actionable feedback on my English performance.

This is a **server-only** story (zero Flutter changes). It builds the *generation + storage + read* backend for the post-call debrief. The Flutter consumers ship later: Story 7.2 (Call Ended overlay that fetches the debrief during its 3–4 s hold) and Story 7.3 (the debrief screen that renders it).

**All three open decisions are RESOLVED (Walid, 2026-06-08): D1 = Option A (bot generates, server serves), D2 = (a) build hesitation capture now, D3 = add a dedicated `scenario_title` field. The ACs and Tasks below already reflect these — the story is ready for `/bmad-dev-story`.**

---

## ⚠️ Source-Document Drift — READ FIRST

The epic AC and two of the three referenced design docs were authored in **April 2026**, before Epic 6 rebuilt the pipeline. Several "facts" in them are now **stale**. This story pins the current truth:

| Stale source statement | Current truth (use THIS) | Evidence |
|---|---|---|
| "LLM = Qwen 3.5 Flash via OpenRouter" (epics.md L1280, debrief-generation-prompt.md, debrief-content-strategy.md) | **All LLM paths run on Groq** since the 2026-05-29 all-Groq migration. OpenRouter is legacy/unused. | [server/CLAUDE.md §4]; memory `infra_groq_capacity_and_scout_fallback` |
| `json_schema` strict mode is available | Available on **Groq Llama-4 Scout**, NOT on Llama 3.3 70B (70B returns HTTP 400). Debrief needs a structured-output-capable model. | [server/CLAUDE.md §4]; [config.py `classifier_model`] |
| Migration is `003_debriefs.sql` | `003` is already `003_tier_rename_full_to_paid.sql`; latest on disk is `010`. **Next number is `011`.** | [server/db/migrations/] |
| Schema = `difficulty-calibration.md` §5.4 (`language_errors`/`error_type`/`repetitions`/`call_summary`) | **SUPERSEDED.** The authoritative schema is `debrief-content-strategy.md` + `debrief-generation-prompt.md` (both 2026-04-01, "Approved", "single source of truth", "consumed by Story 7.1"). It **removed** `strengths`, `summary`/`call_summary`, `error_type`, `repetitions`; renamed fields. | `debrief-content-strategy.md` Q1/Q2/Q3 |
| "Backend has the transcript / LiveKit session timestamps" | **FALSE in this architecture.** The conversation lives in the per-call **bot subprocess** (`pipeline/bot.py`). The REST API and its `/end` handler have **no transcript, no checkpoint counts, no STT timestamps.** This gap is the central design problem of this story (resolved by D1 = Option A). | [routes_calls.py:618 `TODO(Story 7.1)`]; Dev Notes §"The bot↔server data gap" |

**Do not implement against the stale statements.** Use the authoritative schema (`debrief-content-strategy.md`) and the current Groq/Scout reality.

---

## Acceptance Criteria

> Survival formula authority: the **epic AC** (`floor(checkpoints_passed / total_checkpoints × 100)`, FR11) is authoritative over the content-strategy doc's older "successful_exchanges / expected_exchanges" wording — the app's progression is measured in **checkpoints** (built in Epic 6), not "exchanges".

**AC1 — `debriefs` table + checkpoint-count + scenario-title persistence (migration 011).**
A new migration `server/db/migrations/011_debriefs.sql` creates a `debriefs` table: `id` PK, `call_session_id` INTEGER NOT NULL **UNIQUE** REFERENCES `call_sessions(id)`, `survival_pct` INTEGER (0–100, CHECK), `checkpoints_passed` INTEGER, `total_checkpoints` INTEGER, `debrief_json` TEXT NOT NULL, `prompt_version` TEXT NOT NULL, `created_at` TEXT NOT NULL. It also adds the **server-authoritative** checkpoint counts to `call_sessions` as nullable columns `checkpoints_passed INTEGER` + `total_checkpoints INTEGER` (written by the bot — see AC9), and (Decision 3) a nullable `scenario_title TEXT` column to `scenarios` (the distinct debrief title, seeded from YAML). All new columns are nullable — legacy rows pre-date them. The migration replays cleanly against `tests/fixtures/prod_snapshot.sqlite` (no FK/CHECK/integrity violation), and the snapshot is refreshed (`python scripts/refresh_prod_snapshot.py`) and committed alongside the migration (project-root `CLAUDE.md` rule).

**AC2 — Debrief LLM generation via Groq Scout structured output.**
A testable generator (`generate_debrief(...)`) sends the **full transcript + call-end reason + scenario metadata** to Groq using `response_format={"type":"json_schema","json_schema":{"name":"debrief_analysis","strict":True,"schema": <schema>}}`, mirroring `exchange_classifier.classify_multi`. The model is `Settings.debrief_model` (new field, default `"meta-llama/llama-4-scout-17b-16e-instruct"` — a structured-output-capable Groq model per the project law in server/CLAUDE.md §4). The system prompt is the **verbatim v1.0** `DEBRIEF_SYSTEM_PROMPT` from `debrief-generation-prompt.md`, stored as a module constant; the user message is built from the documented template. The call is **time-boxed and never raises** (mirrors `exit_line_generator.generate_exit_line` — `asyncio.wait_for` + swallow-all → return `None` on any failure). `prompt_version` (`"1.0"`) is recorded with each generation.

**AC3 — LLM output schema is exactly the authoritative one.**
The enforced `json_schema` matches `debrief-generation-prompt.md` exactly: top-level keys `errors[]` (each `{user_said, correction, context, count}`, 0–5), `hesitation_contexts[]` (each `{context}`, 0–3), `idioms[]` (each `{expression, meaning, context}`, 0–3), `areas_to_work_on` (`string[]`, `minItems:2`, `maxItems:3`), `inappropriate_behavior` (`string | null`). No `strengths`, no `summary`/`call_summary`, no `error_type`, no `repetitions`. Backend defensively clamps `areas_to_work_on` (if the model returns 1, keep as-is; if 4+, truncate to first 3) and parses with the house fence/first-`{...}` fallback.

**AC4 — Backend-calculated survival percentage.**
`survival_pct = floor(checkpoints_passed / total_checkpoints × 100)`, computed by the backend (NOT the LLM), integer 0–100, using `floor()` (a green 100% appears only on a truly complete scenario). `total_checkpoints == 0` ⇒ `survival_pct = 0` (no division-by-zero).

**AC5 — Backend assembly into the client-facing debrief.**
The stored/served debrief merges the LLM core with backend fields per `debrief-content-strategy.md` §"Complete Client-Facing Response": `survival_pct`, `character_name`, `scenario_title`, `attempt_number`, `previous_best`, `errors`, `hesitations` (`hesitation_contexts[i].context` merged by index with the backend-measured `duration_sec` → renamed `hesitations`), `idioms`, `areas_to_work_on`, `inappropriate_behavior`, and `encouraging_framing`. `encouraging_framing` (`{proximity, improvement}`) is **present only when `survival_pct > 40`** and **omitted entirely** when `survival_pct ≤ 40` (FR15b; null fields omitted convention). Field sources (Decision 3): `character_name` = `scenarios.title` (e.g. "The Mugger"); `scenario_title` = the new dedicated field (e.g. "Give me your wallet").

**AC6 — `user_progress` updated with new best + attempt count.**
On generation, `user_progress(user_id, scenario_id)` is upserted: `attempts` incremented by 1, `best_score = max(existing_best, survival_pct)`. The pre-update `best_score` is captured as the debrief's `previous_best` (null on first attempt); `attempt_number` = the post-increment `attempts`. **A new `upsert_user_progress(...)` query is required — no write path to this table exists today** (it is read-only via `get_*_with_progress`).

**AC7 — FR37 inappropriate-behavior explanation.**
When the call ended with `reason == "inappropriate_content"`, the debrief's `inappropriate_behavior` is a non-null factual explanation (the LLM is told the reason via the user message; the system prompt's "Inappropriate Behavior Rules" govern tone). For every other reason it is `null`.

**AC8 — `GET /debriefs/{call_id}` endpoint.**
A JWT-protected `GET /debriefs/{call_id}` (new `api/routes_debriefs.py`, `prefix="/debriefs"`, `AUTH_DEPENDENCY`) returns the assembled debrief in the `{data, meta}` envelope. Ownership is enforced via the owning `call_session` — a `call_id` that does not exist **or belongs to another user** returns the canonical **404 `CALL_NOT_FOUND`** envelope (info-leak parity with `/calls/{id}/end`). If the call exists for the user but no debrief is available yet, it returns **404 `DEBRIEF_NOT_READY`** (7.2's overlay treats this as "still generating" → shows its minimal loader).

**AC9 — Bot↔server data bridge (Decision 1 = Option A).**
The transcript, checkpoint counts (`checkpoints_passed` / `total_checkpoints`), and call-end `reason` reach the debrief generator keyed by the DB `call_id`. Per **Option A** (RESOLVED): `CALL_ID` is passed to the bot via env at spawn (`routes_calls.py` `bot_env`, mirroring `SCENARIO_ID`); the bot tags its `TranscriptCollector` with the real `call_id`; at call-end teardown (after `runner.run(task)` returns in `run_bot`) the bot computes `survival_pct`, calls `generate_debrief(...)`, writes the `debriefs` row + the `call_sessions` checkpoint counts + the `user_progress` upsert (direct aiosqlite, same VPS DB), and never lets a debrief failure crash teardown. The full transcript is never persisted (privacy) — only the distilled debrief is stored.

**AC10 — Latency budget (NFR7).**
Debrief generation completes within **<5 s target / 10 s hard ceiling**; the generator's `asyncio.wait_for` timeout is set accordingly (recommend 8 s). Generation is masked by Story 7.2's Call Ended overlay (3–4 s hold) and is non-blocking to the user's `/end` path.

**AC11 — Hesitation analysis (FR12) — Decision 2 = build now.**
The bot measures inter-turn gaps (character-stopped-speaking → user-speech-start), filters to >3 s, takes the top 3 by duration, and feeds them to the LLM (which returns `hesitation_contexts`); the backend merges duration + context into `hesitations[]`. When a call genuinely has no >3 s gap, the LLM receives "No significant hesitations detected." and `hesitations` is `[]` (the 7.3 section hides).

**AC12 — Gates green.**
`python -m ruff check .` + `python -m ruff format --check .` + `.venv/Scripts/python -m pytest` all pass, including `test_migrations.py` against the refreshed prod snapshot. New tests cover the generator (mocked Groq), the schema builder, survival/assembly/clamp logic, the `user_progress` upsert, the hesitation gap-measurement, the migration, and the `GET /debriefs/{call_id}` route (happy path + cross-user 404 + not-ready 404).

---

## Decisions — RESOLVED (Walid, 2026-06-08)

> All three forks are decided. The ACs and Tasks reflect them; kept here for the dev's rationale.

### Decision 1 — Where does debrief generation run? *(the architectural fork)*

The transcript exists **only inside the per-call bot subprocess** (`pipeline/bot.py` → `TranscriptCollector`, currently flushed to `/tmp/transcript_<unix-ts>.json`, not even keyed by `call_id`). Checkpoint counts live in the bot too (emitted only on the LiveKit data channel → reach the **client**, never the server). The REST `/end` handler has none of it. So *something* must bridge bot → persistence. Two clean shapes:

- **Option A — Bot generates, server serves.** Pass `CALL_ID` to the bot; at teardown the bot runs the (testable) `generate_debrief(...)`, computes `survival_pct`, and writes the finished `debriefs` row + `user_progress` upsert directly to the shared sqlite DB. `GET /debriefs/{call_id}` only reads + assembles `encouraging_framing`. Transcript never persisted/crosses a boundary; in-process data, no staging tables; masked by the overlay. Bot crash before generation ⇒ no debrief (acceptable degradation). Generation function stays unit-testable in isolation (mocked LLM).
- **Option B — Server lazy-generates on first `GET`.** Bot persists *raw materials* to a staging table keyed by `call_id`; `GET` generates-if-missing. Keeps LLM/`user_progress` logic in the API layer but **persists the full transcript in the DB** + needs a staging table.

**✅ RESOLVED → Option A** (Walid, 2026-06-08): the bot generates at teardown, the server serves. Reflected in AC9 + Tasks 5/6.

### Decision 2 — Hesitation analysis (FR12): build now or defer?

Accurate hesitation = gap between the **character finishing speaking** (TTS done / `BotStoppedSpeakingFrame`) and the **user starting to speak**. The current `TranscriptCollector` timestamps are frame-observation times (the character timestamp is when the LLM *text* was produced, *before* TTS plays) — **not** accurate enough to diff directly. So building it = a small bot-side observer pairing `BotStoppedSpeakingFrame` time with the next user speech-start time → gaps >3 s, top 3 (~60 LOC + tests).

**✅ RESOLVED → (a) build now** (Walid, 2026-06-08): the bot measures the gaps; FR12 ships complete in 7.1. Reflected in AC11 + Task 5.

### Decision 3 — `character_name` / `scenario_title` field

The debrief hero (and the LLM user message) want a `character_name` ("The Mugger") and a `scenario_title`. Real scenario YAML exposes only `metadata.title` (= "The Mugger") and `metadata.rive_character` (= `mugger`, a puppet id) — there is **no** separate scenario-title field.

**✅ RESOLVED → add a dedicated field** (Walid, 2026-06-08): `character_name = scenarios.title`; a NEW `scenario_title` field (e.g. "Give me your wallet") is added to each scenario's YAML `metadata` AND the `scenarios` table (migration 011 + seeder + loader); `brief_personality_description` = first 1–2 sentences of `base_prompt`. The 5 short titles are content to author — **dev proposes a title per scenario, Walid approves before they ship.** Reflected in AC1/AC5 + Tasks 1/4.

---

## Tasks / Subtasks

> Decisions locked: **D1 = Option A** (bot generates), **D2 = build hesitation now**, **D3 = dedicated `scenario_title` field**.

- [ ] **Task 1 — Migration 011 + schema + scenario_title (AC1, Decision 3)**
  - [ ] Write `server/db/migrations/011_debriefs.sql`: `CREATE TABLE debriefs(...)` (see AC1 column list; `call_session_id` UNIQUE FK; `survival_pct` CHECK 0–100) + `ALTER TABLE call_sessions ADD COLUMN checkpoints_passed INTEGER` + `ADD COLUMN total_checkpoints INTEGER` + `ALTER TABLE scenarios ADD COLUMN scenario_title TEXT` (all nullable — legacy rows pre-date them). Mirror the declarative style of `004_scenarios_and_user_progress.sql` / `008_call_sessions_status.sql`.
  - [ ] **Author `scenario_title` in all 5 scenario YAML `metadata` blocks** (`server/pipeline/scenarios/*.yaml`) — dev proposes a short title per scenario (e.g. The Mugger → "Give me your wallet"); **Walid approves before ship**. Thread it through the YAML→DB seeder (`db/seed_scenarios.py` / `upsert_scenario`) and `pipeline/scenarios.load_scenario_metadata` so the bot can read it.
  - [ ] `cd server && python scripts/refresh_prod_snapshot.py`; commit the refreshed `tests/fixtures/prod_snapshot.sqlite`.
  - [ ] Add `test_migrations.py` / `test_queries.py` assertions: `debriefs` table + index exist, new `call_sessions` + `scenarios` columns exist, snapshot replay clean.
- [ ] **Task 2 — `DEBRIEF_SYSTEM_PROMPT` + schema builder (AC2, AC3)**
  - [ ] Add `DEBRIEF_SYSTEM_PROMPT` (verbatim v1.0 from `debrief-generation-prompt.md` §"System Prompt") as a constant in `pipeline/prompts.py`, house style (triple-quoted, version-commented). Watch `str.format` brace-escaping if the prompt contains literal `{}` (see `exchange_classifier._escape_format_braces`).
  - [ ] Implement `_build_debrief_schema()` returning the exact `json_schema` from `debrief-generation-prompt.md` §"JSON Schema" (strict, `additionalProperties:false`, `areas_to_work_on` min2/max3).
- [ ] **Task 3 — `generate_debrief(...)` generator (AC2, AC3, AC7, AC10)**
  - [ ] New module `pipeline/debrief_generator.py` (or `services/debrief.py`). Build the user message from the documented template (scenario header, transcript as alternating `CHARACTER:`/`USER:` lines, hesitation block or "No significant hesitations detected.").
  - [ ] POST to Groq with `response_format` json_schema — copy the request shape from `exchange_classifier.classify_multi` (model from `Settings.debrief_model`, key via `resolve_llm_api_key`, URL via `resolve_llm_chat_url`). Parse with the house fence/first-`{...}` fallback.
  - [ ] Wrap in `asyncio.wait_for(..., timeout=8.0)` + swallow-all → `None` (copy `exit_line_generator.generate_exit_line` structure exactly; re-raise only `CancelledError`).
  - [ ] Return the validated LLM-core dict (clamp `areas_to_work_on` to 2–3) or `None`.
- [ ] **Task 4 — Backend calc + assembly (AC4, AC5, AC6)**
  - [ ] `compute_survival_pct(passed, total) -> int` = `floor(passed/total*100)`, `0` when `total==0`.
  - [ ] `assemble_debrief(...)`: merge LLM core + survival_pct + character_name (`scenarios.title`) + scenario_title (new field) + attempt_number + previous_best + `hesitations` (index-merge duration+context) + `encouraging_framing` (only if `survival_pct > 40`). Pure function → unit-test directly.
  - [ ] Add `upsert_user_progress(db, user_id, scenario_id, survival_pct, now_iso)` to `db/queries.py` (INSERT … ON CONFLICT(user_id,scenario_id) DO UPDATE: `attempts = attempts+1`, `best_score = max(best_score, :survival)`, `updated_at=:now`). Return the pre-update `best_score` (for `previous_best`) and post-update `attempts` (for `attempt_number`) — or read-then-write inside one transaction.
  - [ ] Add `insert_debrief(...)` + `get_debrief_by_call_id(...)` queries (the latter uses `call_sessions` for the ownership check).
- [ ] **Task 5 — Bot wiring + hesitation capture (AC9, AC11) — Option A**
  - [ ] `routes_calls.py`: add `"CALL_ID": str(call_id)` to `bot_env` (alongside `SCENARIO_ID`).
  - [ ] `bot.py run_bot`: read `os.environ.get("CALL_ID")`; tag `TranscriptCollector` with it; after `await runner.run(task)`, if `CALL_ID` set, gather final transcript + `checkpoints_passed`/`total_checkpoints` (from `CheckpointManager`/`PatienceTracker` — see `set_checkpoints_passed`/the `call_end` envelope data) + `reason` + scenario `title`/`scenario_title` (from `load_scenario_metadata`), call `generate_debrief`, compute survival, and persist (`insert_debrief` + `call_sessions` counts + `upsert_user_progress`) via `db.database.get_connection`. Wrap the whole block so a failure logs but never crashes teardown.
  - [ ] **(Decision 2) Hesitation observer** — a small FrameProcessor (or extend `TranscriptCollector`) that records each `BotStoppedSpeakingFrame` timestamp and the next user-speech-start timestamp; compute gaps, filter >3 s, keep top 3 by duration (with the preceding character line for the LLM prompt). Feed into `generate_debrief`. Add unit tests driving the frames through a real pipeline where direction matters (server/CLAUDE.md §1 trap).
- [ ] **Task 6 — `GET /debriefs/{call_id}` (AC8)**
  - [ ] New `api/routes_debriefs.py` (`APIRouter(prefix="/debriefs", tags=["debriefs"], dependencies=[AUTH_DEPENDENCY])`); register in `api/app.py`.
  - [ ] Handler: ownership via `get_call_session` (404 `CALL_NOT_FOUND` if missing/cross-user); fetch debrief (404 `DEBRIEF_NOT_READY` if absent); return `ok(DebriefOut(...))`.
  - [ ] Add `DebriefOut` (+ nested models) to `models/schemas.py`.
- [ ] **Task 7 — Tests + gates (AC12)**
  - [ ] Generator tests (mock the Groq POST; assert request carries `response_format` json_schema + correct model; assert None-on-failure paths). Schema-builder test. `compute_survival_pct` + `assemble_debrief` + clamp + encouraging-framing-omission tests. `upsert_user_progress` first-attempt vs improvement vs no-improvement tests. Hesitation gap-measurement tests. Route tests (happy / cross-user 404 / not-ready 404). Migration tests.
  - [ ] Run all three gates green.
- [ ] **Task 8 — Deploy + Smoke Test Gate (below).** Deploy to VPS, then Walid runs the Pixel 9 smoke gate for `review → done`.

---

## Smoke Test Gate (Server / Deploy Stories Only)

> Every unchecked box is a stop-ship for `in-progress → review`. Paste the actual command + output as proof.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ <!-- Active/Main PID line -->

- [ ] **Debrief generated end-to-end (happy path).** Place a real call (e.g. the Waiter), end it, then `GET /debriefs/{call_id}` returns a `{data, meta}` debrief with a plausible `survival_pct`, ≥1 `errors[]`, 2–3 `areas_to_work_on`, and the distinct `character_name` + `scenario_title`.
  - _Command:_ <!-- curl -sS -H "Authorization: Bearer $JWT" http://167.235.63.129/debriefs/<call_id> -->
  - _Expected:_ <!-- 200 + assembled debrief shape -->
  - _Actual:_ <!-- paste -->

- [ ] **Hesitation captured (FR12).** During the test call, deliberately stay silent >3 s after a character line; the debrief's `hesitations[]` has ≥1 entry with a `duration_sec > 3` and a context sentence.
  - _Proof:_ <!-- paste the hesitations array -->

- [ ] **Cross-user / not-ready produce `{error}` envelopes.** A `call_id` owned by another user → 404 `CALL_NOT_FOUND`; a just-ended call whose debrief hasn't generated → 404 `DEBRIEF_NOT_READY` (not a raw 500).
  - _Command:_ <!-- paste -->
  - _Actual:_ <!-- paste -->

- [ ] **DB side-effects verified.** Read back prod DB (`/opt/survive-the-talk/data/db.sqlite`, via the venv stdlib — no `sqlite3` CLI on VPS): a `debriefs` row exists for the call (one only), `call_sessions.checkpoints_passed/total_checkpoints` populated, and `user_progress` shows `attempts` incremented + `best_score` updated.
  - _Command:_ <!-- /opt/survive-the-talk/current/server/.venv/bin/python -c 'import sqlite3; c=sqlite3.connect("/opt/survive-the-talk/data/db.sqlite"); [print(r) for r in c.execute("SELECT call_session_id,survival_pct,checkpoints_passed,total_checkpoints FROM debriefs ORDER BY id DESC LIMIT 3")]' -->
  - _Actual:_ <!-- paste rows -->

- [ ] **DB backup taken BEFORE deploy (migration 011).**
  - _Command:_ `ssh root@167.235.63.129 "cp /opt/survive-the-talk/data/db.sqlite /opt/survive-the-talk/data/db.sqlite.bak-pre-7.1-$(date +%Y%m%d-%H%M%S)"` (the deploy pipeline also auto-backs-up pre-release).
  - _Proof:_ <!-- resulting filename -->

- [ ] **FR37 path (inappropriate_content).** End a call with `reason=inappropriate_content`; the debrief's `inappropriate_behavior` is a non-null factual sentence (and `null` on a normal call).
  - _Proof:_ <!-- paste the field from both a normal and an inappropriate-end debrief -->

- [ ] **Latency within budget (NFR7).** Time first-token-to-stored-debrief (journalctl timestamps) ≤5 s typical, never >10 s.
  - _Proof:_ <!-- timestamps -->

- [ ] **Server logs clean on the happy path.** `journalctl -u pipecat.service -n 80 --since "5 min ago"` shows no ERROR/Traceback for the debrief generation.
  - _Proof:_ <!-- tail or "no errors in window" + timestamp -->

---

## Dev Notes

### The bot↔server data gap (the crux of this story)

The conversation runs in a **per-call subprocess** spawned by `routes_calls.py:342-356`:
`python -m pipeline.bot --url … --room … --token …` with scenario context passed via env (`SYSTEM_PROMPT`, `SCENARIO_CHARACTER`, `SCENARIO_ID`, `SCENARIO_DIFFICULTY`). **The DB `call_id` is NOT passed today** — adding `CALL_ID` to `bot_env` is the small enabler for Option A (AC9).

What each side has at call end:
- **Bot subprocess** has: the full transcript (`pipeline/transcript_logger.py` `TranscriptCollector`, currently `session_id=f"call_{int(time.time())}"` at `bot.py:401` — a unix ts, **not** the DB call_id), the checkpoint counts (`CheckpointManager` → `PatienceTracker.set_checkpoints_passed` / `_total_checkpoints`, emitted in the `call_end` data-channel envelope `patience_tracker.py:~1295-1312`), the call-end `reason`, the Groq client config, and the scenario YAML. **Hook point (Option A):** after `await runner.run(task)` in `run_bot` (`bot.py:761-762`), the call is fully over and the transcript is collected.
- **REST `/end` handler** (`routes_calls.py:398-638`) has: only the client-supplied `reason`, `user_id`, `call_id`, `duration_sec`. It flips `call_sessions.status`/`duration_sec` and stops. Line 618 is the literal `# TODO(Story 7.1): trigger debrief generation here.` Note `/end` is fired by the **client**, possibly *before* the bot finishes teardown — Option A side-steps any race because the bot owns generation in-process at teardown.

### LLM call — reuse, don't reinvent (Groq Scout structured output)

- **Structured-output request:** copy the payload shape from `pipeline/exchange_classifier.py` `classify_multi` (`response_format={"type":"json_schema","json_schema":{"name":…,"strict":True,"schema":…}}`) and `_build_verdict_schema`. Groq validates server-side, so clean JSON normally arrives; keep the fence/first-`{...}` fallback (`_parse_*_output`, the `_FENCE_RE` pattern) as belt-and-suspenders.
- **Time-boxed standalone call:** copy `pipeline/exit_line_generator.py` `generate_exit_line` / `_generate` — outer `asyncio.wait_for`, inner httpx POST + envelope parse, **never raises** (returns `None`), re-raise only `CancelledError`. `pipeline/llm_warmup.py` is the minimal reference.
- **Provider config:** `Settings.llm_base_url` (`https://api.groq.com/openai/v1`), key via `pipeline/llm_provider.resolve_llm_api_key(settings)`, full URL via `resolve_llm_chat_url(settings)`. Add `Settings.debrief_model` (env `DEBRIEF_MODEL`, default Scout) next to `classifier_model` in `config.py`. **Project law (server/CLAUDE.md §4): `DEBRIEF_MODEL` MUST be a Groq model that supports `json_schema` — Scout/Llama-4/gpt-oss/kimi do; 70B does not (HTTP 400).**
- **Prompt constant** lives in `pipeline/prompts.py` (alongside `EXCHANGE_CLASSIFIER_PROMPT`, `COHERENCE_CHARTER`, exit-line prompts). Log `prompt_version` per generation (the generation-prompt doc calls this "the second most important text in the product").

### Schema authority (do not get this wrong)

Implement **`debrief-content-strategy.md` + `debrief-generation-prompt.md`** (2026-04-01, Approved, "single source of truth", consumed by Story 7.1). The LLM produces: `errors` / `hesitation_contexts` / `idioms` / `areas_to_work_on` (plain strings) / `inappropriate_behavior`. The backend adds: `survival_pct`, `character_name`, `scenario_title`, `attempt_number`, `previous_best`, `hesitations[].duration_sec`, `encouraging_framing`. The LLM's `hesitation_contexts` is **renamed to `hesitations`** during assembly (merge context + backend duration by index). `difficulty-calibration.md` §5.4 is **SUPERSEDED** for the schema (keep it only for the difficulty bands in §4.3: easy 60–80, medium 35–55, hard 15–35 — useful for `encouraging_framing.proximity`).

### Project conventions to follow

- **Response envelopes** (`api/responses.py`): `ok(model)` / `ok_list(items)` for success (`{data, meta}` with `timestamp`); errors raised as `HTTPException(status_code, detail={"code":…, "message":…})` and shaped by the app's exception handlers. Use `now_iso()` for timestamps.
- **Auth + ownership** (`api/middleware.py`): router-level `dependencies=[AUTH_DEPENDENCY]`; `user_id = request.state.user_id`; cross-user resources return **404** (not 403) — copy the `/calls/{id}/end` pre-check pattern (`get_call_session` then `row["user_id"] != user_id → 404`).
- **DB** (`db/database.py` `get_connection` + `db/queries.py`): `aiosqlite.Row` rows, `PRAGMA foreign_keys=ON`, `busy_timeout=5000`; writes that need atomicity use `BEGIN IMMEDIATE`. Migrations auto-run on startup (`run_migrations`). The bot writing to the same sqlite file concurrently with the API is safe under `busy_timeout` — keep the bot's write quick (one short transaction).
- **Migrations test against prod shape** (server/CLAUDE.md §2 / project-root CLAUDE.md): a new table MUST keep `test_migrations.py` green against `prod_snapshot.sqlite`; refresh + commit the snapshot.
- **Frame-direction trap** (server/CLAUDE.md §1): the hesitation observer reads `BotStoppedSpeakingFrame` — drive it through a real pipeline in tests, don't hard-code `FrameDirection`.
- **Loguru in tests** (server/CLAUDE.md §3): assert logs via a temp loguru sink, not `caplog`.

### Project Structure Notes

- New files: `server/db/migrations/011_debriefs.sql`, `server/api/routes_debriefs.py`, `server/pipeline/debrief_generator.py` (or `server/services/debrief.py`). New tests under `server/tests/`.
- Edited files: `server/config.py` (+`debrief_model`), `server/pipeline/prompts.py` (+`DEBRIEF_SYSTEM_PROMPT`), `server/db/queries.py` (+`upsert_user_progress`, `insert_debrief`, `get_debrief_by_call_id`), `server/models/schemas.py` (+`DebriefOut`), `server/api/app.py` (register router), `server/api/routes_calls.py` (+`CALL_ID` in `bot_env`), `server/pipeline/bot.py` (read `CALL_ID`, hesitation observer, teardown generation hook), the 5 `server/pipeline/scenarios/*.yaml` (+`scenario_title`), `server/db/seed_scenarios.py` + `server/pipeline/scenarios.py` (carry `scenario_title`).
- Decision 3 field: `character_name = scenarios.title`; the new `scenario_title` is authored in YAML `metadata` and seeded to the `scenarios` table; `metadata.rive_character` stays a puppet id (unused for the name).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story 7.1] — ACs (L1270-1301), Epic 7 framing (L1264-1268).
- [Source: _bmad-output/planning-artifacts/debrief-content-strategy.md] — **authoritative** content decisions (Q1-Q10), final LLM schema, backend-provided fields, assembly + hesitation-merge + encouraging-framing contracts, section ordering.
- [Source: _bmad-output/planning-artifacts/debrief-generation-prompt.md] — **authoritative** v1.0 system prompt, user-message template, `json_schema`, calibration examples.
- [Source: _bmad-output/planning-artifacts/difficulty-calibration.md#5] — SUPERSEDED schema (note only); §4.3 difficulty bands (still valid).
- [Source: _bmad-output/planning-artifacts/prd.md] — FR9-FR13, FR15b, FR37, NFR7.
- [Source: server/api/routes_calls.py:398] — `/end` handler + `TODO(Story 7.1)` at L618; bot spawn `bot_env` at L328-356.
- [Source: server/api/responses.py] — `ok` / `ok_list` / `err` / `now_iso`.
- [Source: server/api/middleware.py:27] — `require_auth` / `AUTH_DEPENDENCY`; 404-on-cross-user.
- [Source: server/db/database.py:34] — `get_connection`; L56 `run_migrations`.
- [Source: server/db/queries.py] — `get_call_session`, `insert_call_session`, `end_call_session`, `get_*_with_progress` (no `user_progress` write path exists — add one).
- [Source: server/db/migrations/004_scenarios_and_user_progress.sql] — `scenarios` + `user_progress` schemas; [002/008/009] — `call_sessions` schema.
- [Source: server/config.py] — `classifier_model` (Scout default), `character_model`, `groq_api_key`, `llm_base_url`, `llm_api_key`.
- [Source: server/pipeline/llm_provider.py] — `resolve_llm_api_key`, `resolve_llm_chat_url`.
- [Source: server/pipeline/exchange_classifier.py:549] — Scout `json_schema` request; `_build_verdict_schema`; `_parse_*_output` fence fallback.
- [Source: server/pipeline/exit_line_generator.py:201] — time-boxed standalone-call pattern; [server/pipeline/llm_warmup.py] — minimal reference.
- [Source: server/pipeline/prompts.py] — prompt-constant house style.
- [Source: server/pipeline/transcript_logger.py] — `TranscriptCollector` (transcript source; `session_id` needs `call_id`).
- [Source: server/pipeline/bot.py:89] — `run_bot` env reads; L401 collector; L761-762 `runner.run` (teardown hook); L765 `main`/args.
- [Source: server/pipeline/checkpoint_manager.py + patience_tracker.py] — checkpoint counts + `call_end` envelope (`checkpoints_passed` / `total_checkpoints`).
- [Source: server/pipeline/scenarios/the-mugger.yaml] — scenario `metadata` shape (`title`, `rive_character`, `base_prompt`) — where `scenario_title` is added.
- [Source: server/CLAUDE.md] — §1 frame-direction trap, §2 migration-prod-snapshot, §3 loguru-in-tests, §4 Groq structured-output **law**, §7/§8 scenario rules.
- Memory: `project_checkpoint_judge_structured_output`, `feedback_classifier_model_must_support_structured_output`, `infra_groq_capacity_and_scout_fallback`.

## Dev Agent Record

### Agent Model Used

<!-- filled by dev-story -->

### Debug Log References

### Completion Notes List

### File List
