# Story 7.1: Build Debrief Generation Backend

Status: done

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

- [x] **Task 1 — Migration 011 + schema + scenario_title (AC1, Decision 3)**
  - [x] Write `server/db/migrations/011_debriefs.sql`: `CREATE TABLE debriefs(...)` (`call_session_id` UNIQUE FK; `survival_pct` NOT NULL CHECK 0–100) + `ALTER TABLE call_sessions ADD checkpoints_passed/total_checkpoints` + `ALTER TABLE scenarios ADD scenario_title TEXT` — all nullable, ADD-only (no rebuild, replays clean).
  - [x] **Authored `scenario_title` in ALL 6 scenario YAMLs** (the spec said "5" — there are now 6, incl. the 2 cop scenarios). Threaded through `seed_scenarios._row_from_yaml` + `_UPSERT_SCENARIO_SQL`; `load_scenario_metadata` already returns it. **⚠️ Proposed titles AWAIT Walid's approval** (Waiter→"Order your dinner", Mugger→"Give me your wallet", Girlfriend→"Explain where you were", Cop→"Answer the questions", Landlord→"Your rent is late", 8:30 Alibi→"Where were you at 8:30?").
  - [x] `refresh_prod_snapshot.py` — **DONE 2026-06-09 (post-deploy).** After 7.1 deployed (`2d25a63`, 011 confirmed live on prod), ran the refresh; the snapshot now carries `011_debriefs` (FK 0 / integrity ok, PII scrubbed), `test_migrations` + full `pytest` 775 green, snapshot committed. (Originally deferred because the script SSH-pulls live prod, which only carries 011 AFTER it deploys — git history confirms migration+snapshot land together at deploy.)
  - [x] Added `test_migrations.py::test_migration_011_debrief_schema` (table + UNIQUE index + new columns) + the existing snapshot-replay tests stay green.
- [x] **Task 2 — `DEBRIEF_SYSTEM_PROMPT` + schema builder (AC2, AC3)**
  - [x] `DEBRIEF_SYSTEM_PROMPT` added to `pipeline/prompts.py` — extracted VERBATIM (programmatically) from `debrief-generation-prompt.md` §"System Prompt"; static (no `.format()`, no braces). A drift test asserts it matches the doc.
  - [x] `_build_debrief_schema()` returns the strict json_schema. **DEVIATION: `areas_to_work_on` `minItems`/`maxItems` OMITTED** — Groq/OpenAI strict mode rejects array-length constraints (would 400). The 2-3 guarantee comes from the prompt + the AC3-mandated backend `_clamp_areas`.
- [x] **Task 3 — `generate_debrief(...)` generator (AC2, AC3, AC7, AC10)**
  - [x] `pipeline/debrief_generator.py` — user message from the documented template (header + transcript + hesitation block / "No significant hesitations detected."). Built via f-strings (no `.format()`, so no brace-escaping needed).
  - [x] POSTs to Groq with `response_format` json_schema (mirrors `classify_multi`); `Settings.debrief_model` (new, default Scout), key/URL via `resolve_llm_*`. House fence/first-`{...}` parse fallback.
  - [x] `asyncio.wait_for(timeout=8.0)` + swallow-all → `None` (mirrors `exit_line_generator`; re-raises only `CancelledError`); `finish_reason=length` → None.
  - [x] Returns the validated LLM-core dict (areas clamped to ≤3) or `None`.
- [x] **Task 4 — Backend calc + assembly (AC4, AC5, AC6)** (`pipeline/debrief_assembly.py`)
  - [x] `compute_survival_pct(passed, total)` = `floor(passed/total*100)`, `0` on `total==0`, clamped 0–100.
  - [x] `assemble_debrief(...)`: merges core + survival + character_name + scenario_title + attempt_number + previous_best + `hesitations` (index-merge) + `encouraging_framing` (only if `>40`). Pure.
  - [x] `upsert_user_progress(...)` added to `db/queries.py` (read-then-write inside `BEGIN IMMEDIATE`; returns pre-update best + post-increment attempts) — the FIRST `user_progress` write path.
  - [x] `insert_debrief(...)` (idempotent via UNIQUE + ON CONFLICT DO NOTHING), `get_debrief_by_call_id(...)`, `set_call_checkpoint_counts(...)` added.
- [x] **Task 5 — Bot wiring + hesitation capture (AC9, AC11) — Option A**
  - [x] `routes_calls.py`: `"CALL_ID": str(call_id)` added to `bot_env`.
  - [x] `bot.py run_bot`: reads `CALL_ID`, tags the collector, and after `runner.run(task)` calls `persist_debrief` (`pipeline/debrief_teardown.py`) — gathers transcript + `checkpoint_manager.met_count` + `len(checkpoints)` + `patience_tracker.call_end_reason` (new property) + titles, generates, computes survival, upserts progress, writes counts, and inserts the debrief — wrapped so a failure NEVER crashes teardown. (Storage choice: the bot stores the FULLY-assembled debrief incl. `encouraging_framing`; `GET` only reads — simpler than assemble-on-read, identical output.)
  - [x] **(Decision 2) `HesitationObserver`** (`pipeline/hesitation_observer.py`) pairs `BotStoppedSpeakingFrame`↔next `UserStartedSpeakingFrame`, >3 s, top 3 (+ preceding character line). Placed ADJACENT to `PatienceTracker` (proven to see both frames at that slot); observes regardless of `direction` → immune to the §1 trap. Tested by driving frames in their real directions.
- [x] **Task 6 — `GET /debriefs/{call_id}` (AC8)**
  - [x] `api/routes_debriefs.py` (`prefix=/debriefs`, `AUTH_DEPENDENCY`); registered in `api/app.py`.
  - [x] Ownership via `get_call_session` (404 `CALL_NOT_FOUND` missing/cross-user); 404 `DEBRIEF_NOT_READY` if absent; serves the stored dict (preserving the `encouraging_framing` null-omission) validated against `DebriefOut`.
  - [x] `DebriefOut` (+ `DebriefError`/`DebriefHesitation`/`DebriefIdiom`/`EncouragingFraming`) added to `models/schemas.py`.
- [x] **Task 7 — Tests + gates (AC12)**
  - [x] 67 new debrief tests across 6 files (generator incl. strict-schema request + all None paths, schema builder, survival/assembly/clamp/framing-omission, `upsert_user_progress` first/improve/no-improve, hesitation gap-measurement, route happy/cross-user-404/not-ready-404, teardown persistence, prompt-drift guard) + 1 migration test.
  - [x] All three gates green: `ruff check` ✅, `ruff format --check` ✅, `pytest` **756 passed** ✅.
- [ ] **Task 8 — Deploy + Smoke Test Gate (below).** Deploy to VPS (applies migration 011 → then refresh+commit the prod snapshot), then Walid runs the Pixel 9 smoke gate for `review → done`.

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

claude-opus-4-8 (Claude Opus 4.8) — via `/bmad-dev-story`, executed in an isolated git worktree (`story/7.1-debrief-backend`).

### Debug Log References

- Full server suite: **756 passed** (`.venv/Scripts/python -m pytest`).
- Gates: `python -m ruff check .` → All checks passed; `python -m ruff format --check .` → all formatted.
- Migration replay verified against the committed `prod_snapshot.sqlite` (FK/CHECK/integrity clean) — 011 is ADD-only.

### Completion Notes List

Implemented server-only post-call debrief backend (Option A — bot generates at teardown, server serves). All 12 ACs addressed; gates green. Items needing Walid / surfaced for review:

1. **`scenario_title` content awaits approval (Task 1 / D3).** 6 proposed titles authored in the YAMLs (the spec said 5 — there are 6 since the 2nd cop scenario). Trivially editable. Approve/adjust before the smoke gate.
2. **Prod-snapshot refresh deferred to deploy (Task 1 / AC1).** The refresh script SSH-pulls live prod, which only carries migration 011 *after* it deploys — so it can't be refreshed pre-deploy (git history shows migration+snapshot always land together at deploy). The migration replays clean against the current snapshot now; the snapshot must be refreshed + committed right after the Task 8 deploy.
3. **Guardrail test kept rigorous.** `test_full_lifespan_starts_against_prod_snapshot` asserts `schema_migrations` post-lifespan equals the EXACT repo migration count (not a blanket `>=`) — a not-yet-deployed repo migration legitimately records its row on replay, and this self-corrects to an exact match once the snapshot is refreshed. Every user-data table still `==`, FK/integrity re-checked.
4. **AC3 schema deviation:** `areas_to_work_on` `minItems`/`maxItems` omitted from the strict schema (Groq strict mode rejects array-length constraints → would HTTP 400). The 2-3 guarantee = system prompt + the AC3-mandated backend `_clamp_areas`.
5. **`encouraging_framing` stored, not assembled-on-read.** The bot stores the fully-assembled debrief; `GET` is a trivial read. Same output as Option A's "GET assembles framing", fewer moving parts, single source of truth. Its exact copy is provisional (Story 7.3 owns final UX wording).
6. **NOT live-tested against Groq** (no key in sandbox, costs $). Generator is fully mocked-LLM tested; the real Scout `json_schema` round-trip is validated by `scripts/probe_debrief_schema.py` (run pre-smoke-gate) + the Task 8 smoke gate.

### Senior Developer Review (AI) — adversarial multi-agent, 2026-06-08

An 8-dimension adversarial review (parallel reviewers → an independent skeptic per finding → a completeness critic → synthesis) ran on the branch. 19 findings raised → 14 confirmed after verification. **1 CRITICAL fixed**, plus low-severity hardening. All 4 deliberate deviations were judged SOUND.

- 🔴 **CRITICAL (fixed).** `HesitationObserver` stored its injected clock as `self._clock`, which pipecat's `FrameProcessor.setup()` overwrites with a non-callable `BaseClock` on every real call → `self._clock()` raised `TypeError` → hesitation capture was **silently dead in prod** while every unit test passed (the §1 / Déviation #28 trap, via attribute-name collision). Renamed `_clock`→`_now`; added a real-pipeline drive test (runs `setup()`) + a pipeline-ordering assertion. Bug reproduced and fix proven.
- 🟠 **AC7 backend-enforced.** `inappropriate_behavior` is now pinned to the server-authoritative reason (non-null IFF `inappropriate_content`), not trusted to the model. +3 tests.
- 🟠 **Write-time contract validation + idempotent teardown.** `persist_debrief` validates the assembled blob against `DebriefOut` before storing (a malformed fallback-path blob would otherwise make `GET` a permanent 500 — the insert is idempotent), and is now a no-op on re-run via the `checkpoints_passed` marker (future-proofs Story 6.26 bot pooling; also skips the wasteful LLM call). +route 500 tests + double-call test.
- 🟠 **Teardown survives a `runner.run` error** (try/finally) so progress + counts always land. **Opening greeting seeded** into the transcript (it is a `TTSSpeakFrame`, never logged) so the debrief analyses the whole conversation and the first hesitation has an anchor.
- 🟢 **Migration guardrail tightened** to the exact repo-migration count; **Groq Scout acceptance probe** (`scripts/probe_debrief_schema.py`) added for Walid to run pre-smoke-gate (the one untested risk).

Net: +8 tests (**764** total), all three gates green.

### File List

**New (server/):**
- `db/migrations/011_debriefs.sql`
- `pipeline/debrief_generator.py`
- `pipeline/debrief_assembly.py`
- `pipeline/debrief_teardown.py`
- `pipeline/hesitation_observer.py`
- `api/routes_debriefs.py`
- `scripts/probe_debrief_schema.py` (review — live Groq-acceptance probe)
- `tests/test_debrief_generator.py`
- `tests/test_debrief_assembly.py`
- `tests/test_debrief_queries.py`
- `tests/test_debrief_teardown.py`
- `tests/test_hesitation_observer.py`
- `tests/test_routes_debriefs.py`

**Modified (server/):**
- `config.py` (+`debrief_model`)
- `pipeline/prompts.py` (+`DEBRIEF_SYSTEM_PROMPT`, +`DEBRIEF_PROMPT_VERSION`)
- `db/queries.py` (+`upsert_user_progress`, `insert_debrief`, `set_call_checkpoint_counts`, `get_debrief_by_call_id`; +`scenario_title` in `_UPSERT_SCENARIO_SQL`)
- `db/seed_scenarios.py` (+`scenario_title` in `_row_from_yaml`)
- `models/schemas.py` (+`DebriefOut` + nested models)
- `api/app.py` (register `debriefs_router`)
- `api/routes_calls.py` (+`CALL_ID` in `bot_env`)
- `pipeline/bot.py` (read `CALL_ID`, tag collector, `HesitationObserver` in pipeline, teardown `persist_debrief`)
- `pipeline/patience_tracker.py` (+`call_end_reason` capture + property)
- `pipeline/scenarios/*.yaml` (6 files: +`scenario_title`)
- `tests/test_migrations.py` (+011 schema test; `schema_migrations` growth allowed)

### Change Log

| Date | Change |
|---|---|
| 2026-06-08 | Story 7.1 implemented (Option A): migration 011 (`debriefs` + checkpoint counts + `scenario_title`), Groq-Scout `generate_debrief` (strict `json_schema`), pure survival/assembly, `user_progress` upsert + debrief queries, bot teardown generation + `HesitationObserver`, `GET /debriefs/{call_id}`. 67 new tests; gates green (ruff + 756 pytest). Status → review. Snapshot refresh + smoke gate pending deploy. |
| 2026-06-08 | Adversarial multi-agent review fixes. **CRITICAL:** `HesitationObserver._clock`→`_now` (pipecat `setup()` clobbered `_clock` → hesitations dead in prod) + real-pipeline regression test + ordering assertion. Backend-enforce AC7 `inappropriate_behavior`. `persist_debrief` validates the blob vs `DebriefOut` before storing + is idempotent (re-run no-op) + survives a `runner.run` error (try/finally). Seed the opening greeting into the transcript. Tighten the migration guardrail to the exact repo count. Add `scripts/probe_debrief_schema.py`. +8 tests (**764** total); gates green. |
| 2026-06-09 | `/bmad-code-review` (independent adversarial pass, isolated worktree). **2 patches applied.** P1 idempotency hardening: `persist_debrief` now performs the `checkpoints_passed` CLAIM (`UPDATE … WHERE checkpoints_passed IS NULL`) + the `upsert_user_progress` bump in ONE `BEGIN IMMEDIATE` — `upsert_user_progress` made composable (caller owns the txn), `set_call_checkpoint_counts` folded into the conditional claim — so a crash/retry/concurrent teardown (the future Story 6.26 bot-pooling case) can't double-count `attempts`; +1 deterministic regression test that defeats the pre-check to prove the claim is the real guard. P2: `_merge_hesitations` renders `""` not the string `"None"` on a null context. Net test count unchanged (−1 folded `set_call_checkpoint_counts` test, +1 claim regression). Gates GREEN: ruff check + ruff format + pytest **775**. 6 items deferred to `deferred-work.md`. Status stays `review` (owes the Task 8 deploy + Pixel 9 smoke gate). |
| 2026-06-09 | **Deployed (Task 8) + AC1 closed.** Pushed `2d25a63` → CI green → deployed to VPS (`/health` git_sha match). Note: migration 011 + the whole 7.1 backend had already shipped to prod with the b5dc122 (6.25) deploy since `52a8a13` is its ancestor — confirmed live: `schema_migrations` carries `011_debriefs`, `debriefs` table has 13 real rows, `call_sessions.checkpoints_passed/total_checkpoints` + `scenarios.scenario_title` present. Ran `refresh_prod_snapshot.py` (snapshot now carries 011, FK 0 / integrity ok, PII scrubbed) → `test_migrations` + full pytest **775** green → committed the refreshed snapshot, closing AC1. **Remaining for `review → done`: only Walid's Pixel 9 smoke gate** (+ approve the 6 scenario titles). |

### Code Review Findings — `/bmad-code-review` (2026-06-09)

Independent adversarial pass (Blind Hunter + Edge-Case Hunter + Acceptance Auditor, run in the isolated `story/7.1-debrief-backend` worktree at commit `52a8a13`). The implementation is strong — the prior dev self-review already caught the one CRITICAL (`_clock`). This pass confirms **no shipping defect at the current architecture**; the headline item is latent. **0 decision-needed, 2 patch, 6 deferred, 9 dismissed as noise.** (Both patches applied 2026-06-09; gates green — ruff + pytest 775.)

**Patch (FIXED 2026-06-09):**

- [x] [Review][Patch] 🟡 Idempotency double-bump of `user_progress.attempts` — **FIXED.** `persist_debrief` now does the `checkpoints_passed` CLAIM (`UPDATE … WHERE checkpoints_passed IS NULL`) + the `upsert_user_progress` bump in ONE `BEGIN IMMEDIATE`; `upsert_user_progress` was made composable (caller owns the txn) and `set_call_checkpoint_counts` was folded into the conditional claim. A crash/retry/concurrent teardown now bumps `attempts` exactly once (rolls back BOTH the marker and the bump on failure). +1 deterministic regression test (`test_persist_claim_blocks_double_bump_when_precheck_is_defeated`) that defeats the pre-check to prove the claim — not the pre-check — is the real guard. [`pipeline/debrief_teardown.py` + `db/queries.py`] (blind+edge+auditor)
- [x] [Review][Patch] 🟢 `_merge_hesitations` literal `"None"` — **FIXED.** `str(contexts[i].get("context") or "").strip()` (the `.get` default fired only on an absent key, not a null value). [`pipeline/debrief_assembly.py`:92] (edge)

**Deferred (tracked in `deferred-work.md`):**

- [x] [Review][Defer] ✅ AC1 — refreshed `prod_snapshot.sqlite` — **RESOLVED 2026-06-09 (post-deploy).** 7.1 deployed (`2d25a63`, 011 live on prod), snapshot refreshed (carries `011_debriefs`, FK 0 / integrity ok), `test_migrations` + full pytest 775 green, committed. [`tests/fixtures/prod_snapshot.sqlite`]
- [x] [Review][Defer] 🟢 Fallback-path malformed LLM item drops the whole debrief → `GET` `NOT_READY` forever; `_normalize_core` could validate-and-drop per item. [`pipeline/debrief_generator.py`:320-342] — deferred
- [x] [Review][Defer] 🟢 `busy_timeout` contention → progress/counts silently lost (swallowed by the bot's outer except); consider an `OperationalError` retry. [`pipeline/debrief_teardown.py`:128-135] — deferred
- [x] [Review][Defer] 🟢 `DEFAULT_END_REASON = "user_hangup"` mislabels a fully-completed call to the LLM (survival_pct unaffected); consider a `completed` reason. [`pipeline/debrief_teardown.py`:43] — deferred
- [x] [Review][Defer] 🟢 Hesitation timing is an approximation (FR12) — index-merge trusts the model's ordering (AC5) + the server-side gap includes downlink/playback/uplink RTT (over-states the pause). Verify a real >3 s hesitation at the smoke gate. [`pipeline/debrief_assembly.py`:77-99 + `pipeline/hesitation_observer.py`] — deferred
- [x] [Review][Defer] 🟢 Minor robustness — `brief_personality` sentence-split mishandles "Det."/"8:30 p.m."; `_parse_debrief_output` first-`{...}` fallback can over-capture on a large body. [`pipeline/debrief_teardown.py`:46,63 + `pipeline/debrief_generator.py`:390-396] — deferred

**Dismissed (9, by-design / false positive):** survival `floor` vs `survived` reason (AC4); `inappropriate_behavior` nulled on non-`inappropriate_content` reason (AC7); `_clamp_areas` no lower bound (AC3 — a min can't be fabricated); "permanent 500" (write-time `DebriefOut` gate prevents it → serves `NOT_READY`); `DebriefOut` no `extra="forbid"` / raw-dict serve (writer controls the shape; null-omission intentional); `get_call_session` KeyError pre-011 (migrations auto-run before the bot writes); FK pragma (db layer sets `foreign_keys=ON`); shared transcript list (copied at the boundary, read synchronously); `upsert_user_progress` nested `BEGIN` (safe as called; folded into the patch fix).

> **Story 7.1 is review-complete on the code** (1 CRITICAL already fixed by the dev pass; this pass found 0 shipping defects, 1 latent + 1 trivial patch, 6 low-priority deferrals). It is **NOT** yet eligible for `review → done` — it still owes the **Task 8 VPS deploy** (migration 011 + the `prod_snapshot.sqlite` refresh) **and your Pixel 9 smoke gate**. Status stays `review`.
