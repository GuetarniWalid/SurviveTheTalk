# Story 6.28: Remove Per-Scenario Difficulty

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As Walid (product owner),
I want the per-scenario authored difficulty concept (easy/medium/hard labels ON scenarios) removed from every layer — YAML, DB, API, runtime fallback, tools, and docs,
so that the learner's GLOBAL difficulty setting is the only difficulty cursor in the product and scenarios exist purely to vary the experience.

## Product Ruling (source of truth)

**Walid, 2026-06-10 (D3 of the Story 6.27 decision pass):** *"Il n'y a plus de scénario easy/medium/hard. Cette notion ne doit plus être au niveau des scénarios. Le seul curseur easy/medium/hard doit être au niveau du réglage général. […] Les scénarios sont juste là pour varier l'expérience."*

The per-scenario `difficulty` field is legacy from the pre-6.19 design. Story 6.19 already made the user's GLOBAL pick override the authored difficulty everywhere at runtime; the authored label is now a dead vestige that only confuses authoring and analysis (e.g. the call-266 aggravator was framed as "hard-on-easy" — a frame that should not exist). Recorded in `memory/project_difficulty_global_only.md`; the standing dev constraint from Story 6.27 ("introduce NO new coupling to `metadata.difficulty`") graduates here into full removal.

---

## ⚠️ THE CENTRAL TRAP — read this before touching anything

**"Remove per-scenario difficulty" ≠ "remove the difficulty system".** Difficulty SURVIVES as a runtime concept anchored on the user's global pick (Story 6.19). A first-pass analysis of this story over-deleted; the dev agent must not repeat it. The boundary:

### STAYS (do NOT delete or weaken)

| Thing | Where | Why it stays |
|---|---|---|
| `_DIFFICULTY_PRESETS` (patience/timing/tts_speed per level) | `server/pipeline/scenarios.py:106-178` | The GLOBAL pick selects one of these rows per call |
| `_DIFFICULTY_PROMPTS` (3 behavior blocks) | `server/pipeline/scenarios.py:180-277` | Composed onto the persona at load time per the GLOBAL pick |
| `find_persona_difficulty_leaks` + `_PERSONA_DIFFICULTY_LEAK_PATTERNS` + the WARN in `load_scenario_base_prompt` | `scenarios.py:298-403, 915-925` | Persona difficulty-NEUTRALITY is MORE critical now: every scenario must work at all 3 global levels (server/CLAUDE.md §8 is law) |
| `InitiateCallIn.difficulty` optional Literal field | `server/models/schemas.py:57` | This IS the global pick arriving from the client on every call. Keep optional (D2) |
| `SCENARIO_DIFFICULTY` env plumbing (route → bot subprocess + parked-bot allowlist) | `routes_calls.py:340-347`, `bot.py:119-124, 930` | Carries the global pick across the process boundary. Keep the env var NAME too — renaming would churn the warm-pool protocol for zero user value |
| Client global difficulty feature (storage, hub line, sheet, POST body field) | `client/lib/core/onboarding/difficulty_storage.dart`, `scenario_list_screen.dart:202-243, 267-271, 325-366`, `widgets/difficulty_sheet.dart`, `call_repository.dart:10-27` | The product's ONLY difficulty cursor. Untouched |
| Nullable per-scenario patience overrides (`patience_start`, `fail_penalty`, … `ladder_impatience_seconds`, `escalation_thresholds`) in YAML metadata + DB + API detail | YAMLs, `schemas.py:174-184`, seeder, queries | These are experience-tuning knobs applied ON TOP of whichever global preset is active (e.g. `cop-interrogation-01.yaml` `patience_start: 90`), NOT difficulty labels |
| `scripts/compare_difficulty.py` | whole file | It A/B-tests the GLOBAL blocks' behavioral effect on a scenario (server/CLAUDE.md §8 proof tool). Only its kwarg call site changes |
| `scripts/score_transcript.py --difficulty` | `score_transcript.py:72-77` | Describes the global difficulty a recorded call ran at. Out of scope |
| `_DIFFICULTY_BANDS` + `band_for_difficulty` in the calibration engine | `calibration_engine.py:131-146, 1189-1199` | Bands re-anchor on the RUN-level difficulty (D3), they don't disappear |
| `tts_speed` in presets + bot wiring | presets, `bot.py:364-367` | Global-difficulty channel (easy slows speech). Untouched |

### GOES (the actual story)

- YAML `metadata.difficulty` in all **6** scenario files.
- DB `scenarios.difficulty` column + its CHECK + the `CASE s.difficulty` bucket ordering.
- Seeder read/write of `difficulty`.
- API exposure: `ScenarioListItem.difficulty` (hence both `GET /scenarios` and `GET /scenarios/{id}` payloads).
- The authored-difficulty FALLBACK inside `resolve_patience_config` / `load_scenario_base_prompt` (replaced by a server default, D2) + the `difficulty_override` kwarg name.
- `build_scenario.py --difficulty` + the builder's difficulty params and preset tables.
- Calibration engine's per-YAML difficulty (`ScenarioData.difficulty`, `"difficulty"` in `_HASH_FIELDS`).
- Doc wording that says scenarios are authored with a difficulty.

### NOT TOUCHED (explicitly out of scope)

- **Scenario ids stay as-is** (`waiter_easy_01`, `mugger_medium_01`, `cop_hard_01`, `landlord_hard_01`, `girlfriend_medium_01`, `cop_interrogation_01`). The id is the stable PK across DB (`call_sessions`/`user_progress` FKs), API, client cache, golden fixtures, and 300+ test references. The embedded `_easy/_medium/_hard` substrings are now cosmetic misnomers — renaming is a deliberate, riskier future story. Do not rename anything.
- `users` table / client storage of the global pick — unchanged.
- `_DIFFICULTY_PROMPTS` / `_DIFFICULTY_PRESETS` CONTENT — no tuning in this story.

---

## Decisions (pre-resolved with recommended defaults — Walid may veto any before `dev-story`)

### D1 — Hub ordering after the difficulty bucket sort disappears → **explicit `display_order`**

`_SELECT_LIST_WITH_PROGRESS` orders by `CASE s.difficulty` then id (`queries.py:246-252`). Dropping the column without a replacement falls back to id order → `cop_hard_01` first, `waiter_easy_01` LAST — an onboarding UX regression (the waiter is the gentle free intro).

**Resolved: add a nullable `display_order INTEGER` column** (same migration), authored in YAML `metadata.display_order`, seeded, ordered by `COALESCE(display_order, 999999999), id` (NULLs last = future daily scenarios append at the end by default). NOT exposed on the API (server-side ordering concern only). Values preserve today's exact visible order:

| scenario | display_order |
|---|---|
| waiter_easy_01 | 10 |
| girlfriend_medium_01 | 20 |
| mugger_medium_01 | 30 |
| cop_hard_01 | 40 |
| cop_interrogation_01 | 50 |
| landlord_hard_01 | 60 |

(Gaps of 10 leave insertion room.) Rejected alternatives: plain id order (cop first), `is_free DESC` (waiter still 3rd). Aligned with the content-is-server-side principle — reordering the hub never needs an app update.

### D2 — Difficulty when the request omits it → **server constant `DEFAULT_DIFFICULTY = "easy"`**

Today `InitiateCallIn.difficulty=None` → bot falls back to the authored `metadata.difficulty` (6.19 AC7). That fallback target disappears. **Resolved:** module constant `DEFAULT_DIFFICULTY = "easy"` in `scenarios.py`; `None` resolves to it inside both loaders. Matches the client's own default (`DifficultyStorage.defaultDifficulty = 'easy'`, `difficulty_storage.dart:16`). The field stays OPTIONAL (legacy `/connect` path + robustness); making it required buys nothing pre-launch.

### D3 — Calibration band re-anchor → **run-level `--difficulty` (default `easy`), ENGINE_VERSION 6, golden-only gate**

Bands were derived from the authored difficulty (`difficulty-calibration.md` §4.3: easy 60-80 / medium 35-55 / hard 15-35; engine `_DIFFICULTY_BANDS`). **Resolved:** `calibrate_scenario.py` gains `--difficulty {easy,medium,hard}` (default `easy`) → threaded into `build_scenario_data`/`run_calibration` so the AI learner plays the scenario COMPOSED at that global level and the band is `band_for_difficulty(run_difficulty)`. `ScenarioData.difficulty` (from YAML) is removed; `"difficulty"` leaves `_HASH_FIELDS`; `ENGINE_VERSION` bumps **5 → 6** (forces revalidation on the next sweep). **The gate for this story is the cheap `--golden-only` sweep**; the full N=10 band sweep stays a deliberate budgeted action (Groq free-tier daily cap — same posture as 6.27/6.29).

---

## Acceptance Criteria

1. **AC1 — YAML cleanup.** `metadata.difficulty` is gone from all 6 scenario YAMLs; `metadata.display_order` added per the D1 table. Header comments lose the difficulty word ("The Waiter — Easy Difficulty (Free)" → "The Waiter (Free)"); the nullable-override comment block reads "null = use the ACTIVE GLOBAL-difficulty preset" instead of quoting per-authored-difficulty effective values. The explicit `patience_start: 90` in `cop-interrogation-01.yaml` is preserved. The seeder logs ONE WARNING (loguru) per YAML that still carries a vestigial `metadata.difficulty` key (hand-edited VPS YAMLs must not crash boot) and otherwise ignores it.
2. **AC2 — DB migration 013.** New `server/db/migrations/013_remove_scenario_difficulty.sql`: `ALTER TABLE scenarios DROP COLUMN difficulty;` + `ALTER TABLE scenarios ADD COLUMN display_order INTEGER;`. Replays green against `tests/fixtures/prod_snapshot.sqlite` (`test_migrations.py` — FK check + integrity ok + no row loss). No table rebuild / no `PRAGMA foreign_keys=OFF` needed: SQLite ≥ 3.35 drops a column carrying its own inline CHECK (empirically verified 2026-06-11 on 3.49.1 local incl. inbound-FK table + rows; VPS sqlite 3.45.1). Seeder writes `display_order`; `_UPSERT_SCENARIO_SQL` loses `difficulty`, gains `display_order`.
3. **AC3 — Query + API surface.** List ordering = `ORDER BY COALESCE(s.display_order, 999999999) ASC, s.id ASC` (CASE bucket deleted); for the 6 prod scenarios the returned order is BYTE-IDENTICAL to today (regression-asserted). `difficulty` is absent from `ScenarioListItem` (and therefore `ScenarioDetail`) and from both route payloads; `display_order` is NOT exposed. `InitiateCallIn.difficulty` survives unchanged in shape (its docstring re-anchored per D2).
4. **AC4 — Runtime resolution.** `resolve_patience_config(scenario_id, difficulty: str | None = None)` and `load_scenario_base_prompt(scenario_id, difficulty: str | None = None)`: `None` → `DEFAULT_DIFFICULTY` ("easy"); NO read of `metadata.difficulty` remains anywhere in `server/pipeline/`; invalid value still raises RuntimeError. `bot.py` passes `difficulty=scenario_difficulty`; the `SCENARIO_DIFFICULTY` env plumbing (cold Popen + warm-pool parked path incl. the `bot.py:930` allowlist) is byte-identical. The source-text contract test (`test_bot_pipeline_wiring.py:348-352`) is updated to pin the NEW literal. Presets, prompts, leak-lint, tts_speed: untouched.
5. **AC5 — Tools re-anchored.** `build_scenario.py` loses `--difficulty` (and its docstring example); `scenario_builder.py` loses the difficulty parameter end-to-end (`_VALID_DIFFICULTIES`, `_PRESET_FAIL_PENALTY`, `_TARGET_ABSORBED_MISSES` deleted; `suggest_patience_start(n_checkpoints)` re-anchored on the medium constants inline: `base = 20*4` + the existing long-scenario bump; EXPAND_PROMPT keeps the full difficulty-NEUTRALITY mandate but drops the `Difficulty: {difficulty}` input line). `compare_difficulty.py:66` updated to the new kwarg (tool kept). `calibrate_scenario.py` + `calibration_engine.py` per D3 (`ENGINE_VERSION = 6`).
6. **AC6 — Client model cleanup, zero UI change.** `Scenario.difficulty` removed entirely (field `scenario.dart:6`, ctor `:24`, parse `:52`) — it is parsed-but-never-read today (`grep scenario\.difficulty` in `client/lib` = 0 hits). The tutorial hardcode in `incoming_call_screen.dart:41-52` and every test fixture constructing a `Scenario` drop the param. `DifficultyStorage`, the hub line, the sheet, and the `difficulty` POST field are UNTOUCHED. `flutter analyze` drives the sweep; zero visual/behavioral change.
7. **AC7 — Docs re-anchored, not deleted.** `server/CLAUDE.md` §6 (authoring "set `difficulty`" line + band wording) and §8 (the `load_scenario_base_prompt(difficulty_override=…)` reference and authored-difficulty framing) re-worded to the global-only model. `difficulty-calibration.md` gets a short banner: per-scenario difficulty removed by 6.28, §4.3 bands now anchor on the global level a calibration run targets. `scenario-authoring-template.md` metadata example drops `difficulty:` and re-words the preset note. `memory/project_difficulty_global_only.md` stays accurate (no edit needed).
8. **AC8 — Golden gate under EV6.** `python scripts/calibrate_scenario.py --golden-only` sweep runs post-bump: waiter (the reviewed gating fixture) PASSES; the pre-existing `mugger_medium_01` stable seed-fail and `cop_hard_01` flaky-borderline are documented as NOT-6.28 (known since the 6.29 sweep) — they must not silently rot further, but they don't block this story. Full N=10 band calibration explicitly deferred (Groq cap).
9. **AC9 — Gates.** `ruff check` + `ruff format --check` + `pytest` (baseline 875) green in `server/`; `flutter analyze` (No issues) + `flutter test` (baseline 451) green in `client/`; net test delta documented in the Dev Agent Record. Commit cadence: this story's dev lands as its own commit (no amend/squash).

---

## Tasks / Subtasks

- [x] **T1 — Migration 013** (AC2)
  - [x] Create `server/db/migrations/013_remove_scenario_difficulty.sql` with a header comment in the 012 style (story, what, why, replay note): `ALTER TABLE scenarios DROP COLUMN difficulty;` then `ALTER TABLE scenarios ADD COLUMN display_order INTEGER;`
  - [x] `pytest tests/test_migrations.py` green against the prod snapshot (no refresh needed pre-deploy — the 012-era snapshot still carrying the column is exactly what proves the drop replays; post-deploy refresh is optional housekeeping)
- [x] **T2 — Seeder** (`server/db/seed_scenarios.py`) (AC1, AC2)
  - [x] Remove `"difficulty": meta["difficulty"],` (line 107)
  - [x] Add `"display_order": meta.get("display_order")` with validation: present value must be a non-bool `int` (mirror the `is_free` strictness posture; ValueError on anything else); absent → None
  - [x] Add the vestige WARNING: if `"difficulty" in meta`, `logger.warning(...)` naming the file, continue seeding
- [x] **T3 — Queries** (`server/db/queries.py`) (AC3)
  - [x] `_SELECT_LIST_WITH_PROGRESS`: replace the `CASE s.difficulty … END ASC` block (lines 246-252) with `COALESCE(s.display_order, 999999999) ASC, s.id ASC`; rewrite the comment at 234-236 (it currently explains the CASE trick) + the docstring at 271-276
  - [x] `_UPSERT_SCENARIO_SQL`: drop `difficulty` from columns/values/`ON CONFLICT` SET (lines 294, 304, 317); add `display_order` to all three
- [x] **T4 — Schemas** (`server/models/schemas.py`) (AC3)
  - [x] Delete `difficulty: str` from `ScenarioListItem` (line 149)
  - [x] `ScenarioDetail` docstring 166-167: "every nullable difficulty-override column" → "every nullable patience-override column"
  - [x] `InitiateCallIn` docstring (lines 48-53): re-anchor — `difficulty` is the global pick; absent → server `DEFAULT_DIFFICULTY` ("easy"), authored fallback is GONE (Story 6.28)
- [x] **T5 — Scenario routes** (`server/api/routes_scenarios.py`) (AC3)
  - [x] Remove `difficulty=row["difficulty"],` at lines 87 and 140
  - [x] Docstring line 61: ordering description → display_order
- [x] **T6 — Runtime loaders** (`server/pipeline/scenarios.py`) (AC4)
  - [x] Add `DEFAULT_DIFFICULTY = "easy"` module constant (near the presets, documented: D2 — server-side default when the client/env omits the global pick)
  - [x] `resolve_patience_config`: signature `(scenario_id: str, difficulty: str | None = None)`; body: `difficulty = difficulty if difficulty is not None else DEFAULT_DIFFICULTY`; DELETE the `metadata.get("difficulty")` branch (lines 498-499); keep the `not in _DIFFICULTY_PRESETS` RuntimeError; rewrite the 6.19-era docstring (450-471)
  - [x] `load_scenario_base_prompt`: same signature/default treatment; DELETE the authored read (lines 930-932); keep the inline-block guard (896-902), the speak-first guard, and the leak WARN (915-925) verbatim; update docstring (849-857)
  - [x] Module-level comment at line 188 (`prompt(scenario_id, difficulty_override=…)`) → new kwarg name
- [x] **T7 — Bot + route comments** (AC4)
  - [x] `bot.py:129-130, 148-149`: `difficulty_override=scenario_difficulty` → `difficulty=scenario_difficulty`; comment block 119-123 re-worded (absent env → server default easy, not "authored difficulty")
  - [x] `bot.py:930` parked-mode allowlist: NO change (verified — `SCENARIO_DIFFICULTY` present in `_PARKED_JOB_ENV_KEYS`, byte-identical)
  - [x] `routes_calls.py:340-347`: comment re-word (absence → `DEFAULT_DIFFICULTY`, drop the AC7-authored-fallback sentence); logic unchanged
- [x] **T8 — Scenario YAMLs ×6** (AC1)
  - [x] `the-waiter.yaml`: delete `difficulty: easy` (line 10); add `display_order: 10`; header comment line 2 → "The Waiter (Free)"; override comments lines 25-33 → "null = use the active GLOBAL-difficulty preset" (drop the per-level effective values)
  - [x] Same treatment: `the-girlfriend.yaml` (display_order 20), `the-mugger.yaml` (30), `the-cop.yaml` (40), `cop-interrogation-01.yaml` (50 — KEEP `patience_start: 90` ✓), `the-landlord.yaml` (60)
- [x] **T9 — Tools** (AC5)
  - [x] `scripts/build_scenario.py`: drop the `--difficulty` argument (lines 225-227) + the docstring example (line 5); stop forwarding it
  - [x] `scripts/scenario_builder.py`: remove `difficulty` from the build params/docstring (line 4, 24); delete `_VALID_DIFFICULTIES` / `_PRESET_FAIL_PENALTY` / `_TARGET_ABSORBED_MISSES` (146-154); `suggest_patience_start(n_checkpoints: int)` anchored on the medium constants (`base = 20 * 4`, keep the `>12`-checkpoint bump + rounding); EXPAND_PROMPT: delete `Difficulty: {difficulty}.` from line 171 and re-word the 173-181 paragraph to mandate neutrality against the GLOBAL setting (the mandate itself STAYS — personas/segments must read identically at every global level); builder emits NO `difficulty` key in the YAML it writes (and may emit `display_order: null` placeholder with a comment)
  - [x] `scripts/compare_difficulty.py:66`: `difficulty_override=difficulty` → `difficulty=difficulty`; module docstring sentence re-anchored (it A/Bs the GLOBAL blocks)
  - [x] `scripts/calibrate_scenario.py`: add `--difficulty {easy,medium,hard}` (default `easy`), threaded to the engine; help text: "global difficulty level the calibration run plays at (band anchor)"
  - [x] `scripts/calibration_engine.py`: `ENGINE_VERSION = 6` (line 129, with a dated comment explaining the 6.28 bump); `ScenarioData` drops the `difficulty` field (551, 565) — run-level difficulty becomes a parameter threaded from the CLI into `load_scenario_data` (compose `load_scenario_base_prompt(scenario_id, difficulty=run_difficulty)` + `resolve_patience_config(scenario_id, difficulty=run_difficulty)` at lines 566-569) and into `run_calibration`/`evaluate_calibration`/ledger/report; drop `"difficulty"` from `_BEHAVIOUR_META_KEYS` (line 1356); keep `_DIFFICULTY_BANDS`/`band_for_difficulty`; diagnostics wording: "this scenario is X" → "this run played at X" — PLUS `scripts/new_scenario.py` + `scripts/new-scenario.cmd` (the 6.17 wizard forwarded difficulty end-to-end: interactive question removed)
- [x] **T10 — Server tests** (AC2-AC5, AC9) — see the Test Inventory table in Dev Notes; headline moves:
  - [x] `test_scenarios.py`: rename/rewrite the override tests (1523-1558) to the new kwarg; REPLACED `test_difficulty_override_none_uses_authored_difficulty` with `test_difficulty_none_uses_default_easy`; same treatment for the base-prompt pair; ordering test re-anchored on display_order + NEW `test_list_order_is_byte_identical_to_pre_6_28_hub` (exact 6-id order) + NEW `test_scenario_payloads_do_not_expose_difficulty_or_display_order`; seeder display_order + vestige-warning tests added in `test_queries.py` (loguru temp-sink per server/CLAUDE.md §3); KEPT `test_shipped_personas_have_no_difficulty_coded_phrases`; synthetic-YAML fixtures dropped their `difficulty:` keys (default path)
  - [x] `test_calls.py`: env plumbing tests STAY (193-235, 832) — comment at 220-222 re-worded (absence → server default, not authored); scenario payloads carried no difficulty assertions to flip (absence covered by the new test_scenarios.py test)
  - [x] `test_bot_parked_mode.py`: env passthrough byte-identical (verified); one stale docstring re-worded (authored → server default — same edit class as the test_calls comment)
  - [x] `test_bot_pipeline_wiring.py:348-352`: pinned the new literal `difficulty=scenario_difficulty`
  - [x] `test_scenario_builder.py` / `test_calibration_engine.py` / `test_prompts.py` / `test_score_transcript.py`: aligned with T9 (builder difficulty tests deleted/rewritten incl. `suggest_patience_start` single-arg; engine tests thread run-difficulty, `_scenario_data` helper dropped the field, CLI-arity Namespace gained `difficulty="easy"`, EV pinned test → 6; test_prompts + score_transcript needed NO change — full suite green)
- [x] **T11 — Client** (AC6)
  - [x] `client/lib/features/scenarios/models/scenario.dart`: delete field (6), ctor param (24), fromJson line (52)
  - [x] `client/lib/features/call/views/incoming_call_screen.dart:41-52`: drop `difficulty: 'easy'` from the tutorial Scenario
  - [x] Swept every test fixture constructing `Scenario(...)` (analyzer-driven: analyze "No issues found!"): `scenario_test.dart` (payload key + round-trip assertion removed), `scenarios_repository_test.dart` (5 JSON fixtures), `scenarios_bloc_test.dart` (×2), `scenario_list_screen_test.dart`, `scenario_card_test.dart`, `scenario_card_semantics_label_test.dart`, `call_screen_test.dart`, `call_bloc_test.dart`, `call_ended_screen_test.dart`, `content_warning_sheet_test.dart`; `difficulty_storage_test.dart` / `difficulty_sheet_test.dart` / hub-line tests / `call_repository_test.dart` UNTOUCHED (global feature — verified the repo test's `difficulty: 'hard'` is the initiateCall POST param, not a Scenario ctor)
- [x] **T12 — Docs** (AC7)
  - [x] `server/CLAUDE.md` §6 + §8 re-anchor (incl. the §8 line 435 kwarg reference + ledger hash-coverage line)
  - [x] `_bmad-output/planning-artifacts/difficulty-calibration.md`: banner note at top (per-scenario difficulty removed 6.28; bands anchor on the run/global level; §4.3 preset tables stay the live source of truth)
  - [x] `_bmad-output/planning-artifacts/scenario-authoring-template.md`: metadata example drops `difficulty:`, gains `display_order` + a 6.28 note; "Difficulty Override Fields" → "Patience Override Fields"; §5 base-prompt anatomy purged of the inline difficulty block (it would be loader-REJECTED since 6.19) and its example made difficulty-neutral; score_transcript `--difficulty` example annotated as the GLOBAL level; checklist line re-worded
- [x] **T13 — Golden gate + full gates** (AC8, AC9)
  - [x] `python scripts/calibrate_scenario.py --golden-only` post-EV6 (2026-06-11): **waiter_easy_01 PASS** (the reviewed gating fixture), girlfriend_medium_01 PASS, landlord_hard_01 PASS, cop_interrogation_01 PASS; mugger_medium_01 + cop_hard_01 known-fails documented verbatim in the Dev Agent Record (NOT-6.28 — structural proof there: the golden judge sees only `data.title` + criteria, never the composed base_prompt, so the run-difficulty change cannot shift golden verdicts)
  - [x] `ruff check .` (clean) + `ruff format --check .` (clean) + `pytest` **880 passed** (server) / `flutter analyze` (No issues found!) + `flutter test` **451 passed** (client) — all green
- [ ] **T14 — Deploy + smoke gate** (Smoke Test Gate below)
  - [ ] Push → `deploy-server.yml` (auto DB backup pre-deploy) → verify migration 013 applied + seeder re-seeded + hub order intact → hand Walid the Pixel 9 script

---

## Smoke Test Gate (Server / Deploy Stories Only)

> **Transition rule:** every unchecked box is a stop-ship for `review → done` (deploy-gate convention, Story 6.5 D6). Paste the actual command + output as proof.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ <!-- Active/Main PID line -->

- [ ] **DB backup taken BEFORE deploy (migration story).** The `deploy-server.yml` auto-backup ran (or manual):
  - _Command:_ `ssh root@167.235.63.129 "ls -t /opt/survive-the-talk/backups/ | head -3"`
  - _Proof:_ <!-- db.pre-<sha7>.sqlite filename -->

- [ ] **Migration 013 applied + column gone + display_order live.**
  - _Command:_ `ssh root@167.235.63.129 "/opt/survive-the-talk/current/server/.venv/bin/python -c 'import sqlite3; c=sqlite3.connect(\"/opt/survive-the-talk/data/db.sqlite\"); print([r[1] for r in c.execute(\"PRAGMA table_info(scenarios)\")]); print(list(c.execute(\"SELECT id, display_order FROM scenarios ORDER BY COALESCE(display_order,999999999), id\")))'"`
  - _Expected:_ column list WITHOUT `difficulty`, WITH `display_order`; rows in order waiter → girlfriend → mugger → cop → cop_interrogation → landlord
  - _Actual:_ <!-- paste -->

- [ ] **Happy-path endpoint round-trip — difficulty key absent, order preserved.**
  - _Command:_ `curl -sS -H "Authorization: Bearer $JWT" http://167.235.63.129/scenarios | python -c "import json,sys; d=json.load(sys.stdin)['data']; print([s['id'] for s in d]); print('difficulty' in d[0])"`
  - _Expected:_ the 6 ids in today's order + `False`
  - _Actual:_ <!-- paste -->

- [ ] **Call initiation still carries the global pick.** `POST /calls/initiate` with `{"scenario_id":"waiter_easy_01","difficulty":"hard"}` → 200 envelope; journalctl shows the bot composing hard.
  - _Command:_ <!-- curl + journalctl -u pipecat.service | grep -E "SCENARIO_DIFFICULTY|pooled|cold" -->
  - _Actual:_ <!-- paste -->

- [ ] **Error path intact.** `POST /calls/initiate` with `{"scenario_id":"waiter_easy_01","difficulty":"extreme"}` → 422 `{error}` envelope (Literal boundary).
  - _Actual:_ <!-- paste -->

- [ ] **Server logs clean.** `journalctl -u pipecat.service -n 50 --since "5 min ago"` — no ERROR/Traceback for the requests above (the seeder vestige WARNING must NOT be firing post-deploy since the YAMLs are clean).
  - _Proof:_ <!-- paste -->

### Pixel 9 voice smoke script (read-and-watch, ~3 min)

The user-visible promise of this story is **nothing changes**: same hub, same order, same global difficulty behavior. It is a live LLM — responses are approximate; watch the structure, not the words.

1. **Open the app → hub.** WATCH: scenario list order is unchanged (The Waiter first, the two cop scenarios + landlord last); the `Difficulty: <level>` line still shows top-right; NO scenario card shows any difficulty label (none ever did).
2. **Tap the Difficulty line → set `Hard` → Done.** WATCH: line updates to `Difficulty: Hard`.
3. **Call The Waiter.** Say: **"Hi, I'd like to order dinner please."** EXPECT: Tina answers in the HARD register — fast, idiomatic, no hand-holding (e.g. brisk "what are you having then?" with slang). **💰 MONEY MOMENT:** hard-style speech on the waiter proves the GLOBAL pick still drives composition with the authored label gone (the old fallback path is deleted).
4. Say: **"I'll have the grilled chicken."** EXPECT: a checkpoint ticks on the HUD (greet/main course), conversation continues normally.
5. **Hang up.** EXPECT: normal Call Ended overlay. Done — report "fini" and I compile the report (silent-monitoring rule applies).

---

## Dev Notes

### Why this story exists (context for the dev agent)

Story 6.19 shipped the GLOBAL difficulty selector and made the global pick override the authored difficulty per call. Since then the authored `metadata.difficulty` has had exactly TWO remaining live effects: (1) the no-override FALLBACK in the two loaders (legacy `/connect` path — replaced by D2's constant), and (2) the hub ORDERING bucket in `_SELECT_LIST_WITH_PROGRESS` (replaced by D1's `display_order`). Everything else (API field, DB column, builder/calibration inputs, doc wording) is dead weight that keeps the retired mental model alive. This story deletes the concept and re-anchors the two live effects.

### Current effective-difficulty chain (UNCHANGED by this story except the final fallback)

client `DifficultyStorage.getSync()` → `POST /calls/initiate` body `difficulty` (`call_repository.dart:20`) → `InitiateCallIn.difficulty` Literal 422-boundary (`schemas.py:57`) → `per_call_env["SCENARIO_DIFFICULTY"]` when not None (`routes_calls.py:346-347`) → warm-pool job env / cold Popen env (`bot.py:930` allowlist) → `bot.py:124` reads env → `resolve_patience_config` + `load_scenario_base_prompt` (`bot.py:129-149`) → preset row + `_DIFFICULTY_PROMPTS` block. **After 6.28 the only change in this chain is the last hop's fallback: absent → `DEFAULT_DIFFICULTY` instead of authored YAML.**

### Architecture compliance

- **Boundary 4 (raw SQL only in `queries.py`)**: the ordering change + UPSERT change stay in `queries.py`; routes keep owning `json.loads` (comment at `queries.py:228-232`).
- **ADR 001 (scenarios canonical column list)**: amended by migration 013 — `difficulty` out, `display_order` in. JSON-in-TEXT columns untouched.
- **Migration safety law (root CLAUDE.md + server/CLAUDE.md §2)**: 013 must keep `test_migrations.py` green against the prod snapshot. The current snapshot (refreshed at the 011/7.1 deploy era, carries `difficulty` + 6 rows) is the right fixture to PROVE the drop replays — do NOT refresh it pre-commit; optional refresh post-deploy.
- **SQLite empirics (2026-06-11, this spec)**: `ALTER TABLE … DROP COLUMN` on a column with its own inline CHECK succeeds (the column-level CHECK drops with it); inbound FKs to `scenarios.id` from `user_progress`/`call_sessions` are unaffected (`PRAGMA foreign_key_check` clean, `integrity_check` ok). Verified on local 3.49.1 with rows + FK table; VPS = 3.45.1, DROP COLUMN exists since 3.35. The Story-5.1 table-rebuild trap (`PRAGMA foreign_keys=OFF`) does NOT apply here — no rebuild.
- **Loguru, not stdlib (server/CLAUDE.md §3)**: the seeder vestige WARNING test needs a temp loguru sink, `caplog` sees nothing.
- **Difficulty-neutral persona law (server/CLAUDE.md §8 + `memory/feedback_difficulty_neutral_persona.md`)**: STRENGTHENED by this story, never weakened — keep every lint/guard; only re-word the prose that references authored difficulty.

### Test inventory (current refs → action)

| File | Current difficulty refs | Action |
|---|---|---|
| `test_scenarios.py` | override/authored tests 1523-1558; base-prompt compose 1654-1726, 1819-1820; ordering; seeder/API shape; persona lint | Rename kwarg; authored-fallback tests → default-easy tests; ordering → display_order (+ exact-6-id-order regression); difficulty-in-response assertions → absence; **KEEP** `test_shipped_personas_have_no_difficulty_coded_phrases` + presets/tts_speed tests (they test the GLOBAL machinery — e.g. `test_presets_carry_tts_speed…` stays, exercised via explicit `difficulty=` now) |
| `test_calls.py` | 193-235 (env set/absent), 832 | STAY; comments re-worded; any scenario-payload difficulty assertion → absence |
| `test_bot_parked_mode.py` | 27-62 env passthrough | STAYS untouched (verify) |
| `test_bot_pipeline_wiring.py` | 348-352 source-text contract | Update pinned literal to `difficulty=scenario_difficulty` |
| `test_scenario_builder.py` | 2 difficulty tests | Delete/rewrite per T9 (suggest_patience_start now single-arg) |
| `test_calibration_engine.py` | 1 | Thread run-difficulty; hash test updated (`_HASH_FIELDS` minus difficulty) |
| `test_prompts.py` / `test_score_transcript.py` | 1 / 2 | prompts: align if it asserts the EXPAND difficulty line; score_transcript: untouched |
| `test_migrations.py` | — | Auto-covers 013 via snapshot replay |
| client `scenario_test.dart` + 9 fixture files | `difficulty: 'easy'` ctor params + 1 assertion | Remove param everywhere (analyzer-driven); keep ALL `difficulty_storage`/`difficulty_sheet`/hub/`call_repository` tests |

### Previous story intelligence

- **6.27 (checkpoint crediting robustness, done 2026-06-10)** — origin of this story (D3 of its decision pass). Its standing constraint "no NEW coupling to `metadata.difficulty`" was verified at its review; 6.28 is the removal it deferred. Pattern to reuse: superset/`implies` work went through the PURE engine functions so golden==prod held — same posture here (loaders + engine change together, `ENGINE_VERSION` bump signals it).
- **6.29 (character dialogue coherence, done 2026-06-11)** — freshest patterns: `ENGINE_VERSION` is now **5** (you bump to 6); baselines post-review = **pytest 875 / flutter 451**; the golden sweep has a STABLE pre-existing `mugger_medium_01` seed-fail (permissive opening criteria — deferred-work entry + chip filed) and a flaky-borderline `cop_hard_01` — do NOT burn time "fixing" them under 6.28, just re-document. Commit-per-stage discipline (create→dev→review each its own commit) is law.
- **6.19 (the global selector)** — its AC7 (absent difficulty → authored fallback) is the contract being retired; its AC3 precedence (explicit YAML per-field overrides still beat preset values) is PRESERVED.

### Git intelligence (last 5 commits)

`c00fb5d` 6.29 review patches + done flip; `950102b`/`a6f5634` exit-line TTS stall retry (call 277); `efde2df` 6.29 smoke docs; `49de9bb` STT drink-name bias (call 276). Recent work = classifier/TTS robustness; none touches difficulty plumbing — no rebase landmines. Conventions visible: `fix:`/`docs:` prefixes, bulleted bodies, no Co-Authored-By.

### Latest tech notes (no web research needed)

Pure-removal refactor on pinned in-repo libs (FastAPI/Pydantic v2/aiosqlite/pipecat 0.0.108 unchanged). The single external-tech fact that matters — SQLite DROP-COLUMN-with-inline-CHECK — was verified EMPIRICALLY for this spec (see Architecture compliance) rather than from docs memory.

### Project Structure Notes

- New file: `server/db/migrations/013_remove_scenario_difficulty.sql` only. Everything else is edits in place.
- No new Python modules, no new Flutter files, no new deps.
- `_bmad-output/implementation-artifacts/.review-*.diff` and `find.exe.stackdump` at repo root are pre-existing untracked artifacts — leave them.

### What NOT to do (hard guardrails)

1. **Do NOT delete** `_DIFFICULTY_PRESETS`, `_DIFFICULTY_PROMPTS`, `_PATIENCE_OVERRIDE_KEYS`, `find_persona_difficulty_leaks`, or any leak-lint wiring — the global system lives on them.
2. **Do NOT remove or require** `InitiateCallIn.difficulty`; do NOT rename the `SCENARIO_DIFFICULTY` env var (warm-pool protocol + tests churn for zero value).
3. **Do NOT rename scenario ids** or golden fixture filenames.
4. **Do NOT touch** the nullable patience-override columns/fields (they are NOT difficulty).
5. **Do NOT run the full N=10 calibration sweep** as a gate (Groq cap) — `--golden-only` is the gate.
6. **Do NOT "fix"** the mugger/cop_hard golden flakiness inside this story.
7. **Do NOT refresh** `prod_snapshot.sqlite` before commit (the stale-shape snapshot is the proof the migration replays); never hand-doctor it.
8. **Do NOT order the hub by raw id** as a "simpler" D1 — cop-first is a product regression.
9. **Do NOT add `display_order` to the API payload** — server-side ordering concern.
10. **Old-APK note:** once the server stops sending `difficulty`, a STALE installed build (whose model still requires the key) fails scenario-list parse → error screen. Pre-launch this only affects Walid's device: install the new APK as part of the smoke gate. Do not build a compatibility shim.

### References

- [Source: memory/project_difficulty_global_only.md] — the product ruling + known touchpoints
- [Source: _bmad-output/implementation-artifacts/6-27-checkpoint-crediting-robustness.md#Decision-3] — D3 origin + AC6 (no new coupling)
- [Source: server/CLAUDE.md §2 (migrations), §3 (loguru), §6 (calibration), §8 (difficulty-neutral personas)]
- [Source: _bmad-output/planning-artifacts/difficulty-calibration.md §4.3] — band table (engine `_DIFFICULTY_BANDS` mirror)
- [Source: _bmad-output/planning-artifacts/architecture.md — Boundary 4, ADR 001]
- [Source: CLAUDE.md root — migration snapshot law, commit format, smoke-gate discipline]
- Key code anchors: `server/db/queries.py:234-252,292-330` · `server/models/schemas.py:39-57,141-188` · `server/api/routes_scenarios.py:61,87,140` · `server/pipeline/scenarios.py:106-277,445-525,837-941` · `server/pipeline/bot.py:119-149,930` · `server/api/routes_calls.py:332-369` · `server/db/seed_scenarios.py:98-138` · `server/scripts/calibration_engine.py:98-146,551-569,1189-1243,1356-1409` · `server/scripts/scenario_builder.py:138-154,162-197,555-567` · `server/scripts/build_scenario.py:215-260` · `client/lib/features/scenarios/models/scenario.dart:6,24,52`

## Dev Agent Record

### Agent Model Used

Claude Fable 5 (claude-fable-5) — dev-story executed 2026-06-11.

### Debug Log References

- Migration RED→GREEN: after writing 013, `pytest tests/test_migrations.py` showed exactly the expected intermediate state — the 5 replay/FK/integrity tests PASSED (proving the DROP COLUMN replays against the prod snapshot incl. inbound-FK rows) while `test_full_lifespan_starts_against_prod_snapshot` failed on the seeder still writing `difficulty` ("table scenarios has no column named difficulty"). T2/T3 turned it green.
- Initial failure inventory after T1-T8 (before test alignment): 49 failed / 291 passed across the impacted files — all in the expected categories (ordering helpers, override-kwarg tests, builder difficulty params, engine `_ScenarioData.difficulty`, seeder dict).
- Golden-only sweep post-EV6 (2026-06-11): 4/6 PASS — `waiter_easy_01` ✅ (the reviewed gating fixture, AC8's headline), `girlfriend_medium_01` ✅, `cop_interrogation_01` ✅, `landlord_hard_01` ✅.
- **Known-fail #1 (pre-existing, NOT-6.28): `mugger_medium_01`** — byte-identical signature to the 6.29-sweep documentation: checkpoint `react` (`checkpoints[0].success_criteria`), universal seed "There are a lot of people here today." judged **met** (should be unmet). Stable seed-fail from permissive opening criteria; deferred-work entry + chip already filed under 6.29. Report: `calibration-tests/calibrate_mugger_medium_01_2026-06-11T10-50-29Z.{json,md}`.
- **Known-fail #2 (pre-existing flaky-borderline, NOT-6.28): `cop_hard_01`** — checkpoint `respond` (`checkpoints[0].success_criteria`), seed "I think the traffic was terrible this morning." judged **met**. Failed on the sweep AND on a solo re-run today (6.29's sweep day it passed on re-run — single-seed verdict flips on a borderline criteria, live Scout judge). **Structural proof this cannot be a 6.28 regression:** the golden judge payload carries only `scenario_description=data.title` + per-checkpoint criteria — it NEVER sees the composed base_prompt, so the EV6 run-difficulty change (authored-hard → default-easy composition) is invisible to golden verdicts. Same first-checkpoint-too-permissive class as the mugger. Watch item: it failed twice today vs pass-on-rerun on 2026-06-10 — flagged for the reviewer as possible (judge-side) drift, NOT silently absorbed. Per guardrail #6, no fix attempted in this story. Report: `calibration-tests/calibrate_cop_hard_01_2026-06-11T12-48-23Z.{json,md}`.

### Completion Notes List

- **All 14 tasks T1-T13 complete** (T14 = deploy + Pixel 9 smoke gate, below). Net server test delta: **875 → 880 (+5)**; client **451 unchanged** (AC9/AC6).
- **AC1-AC2**: migration 013 (DROP difficulty + ADD display_order, no table rebuild — SQLite ≥3.35 drops the inline CHECK with the column); seeder writes validated `display_order` (non-bool int or None), warns-and-ignores a vestigial `metadata.difficulty` (one loguru WARNING naming the file); all 6 YAMLs carry `display_order` per the D1 table (10/20/30/40/50/60), `patience_start: 90` preserved in cop-interrogation-01.
- **AC3**: hub ordering `COALESCE(display_order, 999999999), id` — exact pre-6.28 order regression-asserted twice (API level in test_scenarios.py + SQL level in test_queries.py); `difficulty` absent from both payloads, `display_order` never exposed; `InitiateCallIn.difficulty` shape untouched.
- **AC4**: both loaders are `(scenario_id, difficulty: str | None = None)` with `None → DEFAULT_DIFFICULTY ("easy")`; zero reads of `metadata.difficulty` remain under `server/pipeline/`; `SCENARIO_DIFFICULTY` env plumbing byte-identical (route conditional, pool job, `_PARKED_JOB_ENV_KEYS` allowlist verified); source-text contract test pins the new literal; presets/prompts/leak-lint/tts_speed untouched.
- **AC5**: builder difficulty-free end-to-end (`build_scenario.py`, `scenario_builder.py`, the 6.17 wizard `new_scenario.py` + `.cmd`); `suggest_patience_start(n)` anchored on medium constants (base 80); EXPAND_PROMPT difficulty input dropped, neutrality mandate re-worded against the GLOBAL setting and KEPT; builder emits `display_order: null` placeholder; `compare_difficulty.py` kwarg updated (tool kept); `calibrate_scenario.py --difficulty` (default easy) threaded into `load_scenario_data`/`run_calibration`/`evaluate_calibration`; `ENGINE_VERSION = 6`.
- **AC6**: `Scenario.difficulty` deleted (field/ctor/fromJson); tutorial literal updated; 10 client test files swept analyzer-driven; the global-difficulty feature files (storage/sheet/hub line/`call_repository`) untouched — verified `call_repository_test.dart`'s `difficulty: 'hard'` is the initiateCall POST param.
- **AC7**: server/CLAUDE.md §6+§8 re-anchored; difficulty-calibration.md banner added; scenario-authoring-template.md re-anchored (also purged the §5 inline-difficulty-block example — it instructed authors to write a base_prompt the loader REJECTS since 6.19, and its example contained literal leak-lint phrases).
- **AC8**: golden-only sweep post-EV6 documented above (waiter PASS; mugger/cop_hard known-fails NOT-6.28 with structural proof). Full N=10 band calibration explicitly deferred (Groq free-tier cap).
- **AC9**: ruff check + ruff format --check + pytest 880 (server); flutter analyze No issues + flutter test 451 (client). This dev stage lands as its own commit (commit-per-stage law).
- **Deviation D#1 (in spirit of T9, beyond its letter)**: `scripts/new_scenario.py` + `scripts/new-scenario.cmd` were not named by T9 but forwarded `difficulty` into `build_and_validate_scenario` — removing the builder param end-to-end (AC5) forced the wizard's interactive difficulty question out too. No behavioral loss: the wizard now builds difficulty-free scenarios playable at every global level.
- **Deviation D#2**: `test_bot_parked_mode.py` was "verify only" per T10, but one docstring still claimed "the bot falls back to the scenario's authored difficulty" — factually wrong post-6.28; re-worded (same edit class as the T10 test_calls comment re-word). Env passthrough logic untouched.
- **Deviation D#3**: the waiter YAML's `calibration.pipeline_validation.findings` historical log line ("follows easy difficulty guidelines", dated 2026-04-15) was left as-is — it is a dated record of a past observation, not authoring guidance; rewording history would falsify it.
- **NOT done (out of scope per spec)**: scenario ids unrenamed; `users` table/client global storage untouched; `_DIFFICULTY_PROMPTS`/`_DIFFICULTY_PRESETS` content untuned; prod snapshot NOT refreshed (the stale shape IS the replay proof); mugger/cop_hard golden flakiness not "fixed"; `score_transcript.py --difficulty` kept.

### File List

New:
- server/db/migrations/013_remove_scenario_difficulty.sql

Modified (server):
- server/db/seed_scenarios.py
- server/db/queries.py
- server/models/schemas.py
- server/api/routes_scenarios.py
- server/api/routes_calls.py
- server/pipeline/scenarios.py
- server/pipeline/bot.py
- server/pipeline/scenarios/the-waiter.yaml
- server/pipeline/scenarios/the-girlfriend.yaml
- server/pipeline/scenarios/the-mugger.yaml
- server/pipeline/scenarios/the-cop.yaml
- server/pipeline/scenarios/the-landlord.yaml
- server/pipeline/scenarios/cop-interrogation-01.yaml
- server/scripts/build_scenario.py
- server/scripts/scenario_builder.py
- server/scripts/new_scenario.py
- server/scripts/new-scenario.cmd
- server/scripts/compare_difficulty.py
- server/scripts/calibrate_scenario.py
- server/scripts/calibration_engine.py
- server/CLAUDE.md
- server/tests/test_scenarios.py
- server/tests/test_queries.py
- server/tests/test_calls.py
- server/tests/test_bot_pipeline_wiring.py
- server/tests/test_bot_parked_mode.py
- server/tests/test_scenario_builder.py
- server/tests/test_calibration_engine.py

Modified (client):
- client/lib/features/scenarios/models/scenario.dart
- client/lib/features/call/views/incoming_call_screen.dart
- client/test/features/scenarios/models/scenario_test.dart
- client/test/features/scenarios/repositories/scenarios_repository_test.dart
- client/test/features/scenarios/bloc/scenarios_bloc_test.dart
- client/test/features/scenarios/views/scenario_list_screen_test.dart
- client/test/features/scenarios/views/widgets/scenario_card_test.dart
- client/test/features/scenarios/views/widgets/scenario_card_semantics_label_test.dart
- client/test/features/scenarios/views/widgets/content_warning_sheet_test.dart
- client/test/features/call/bloc/call_bloc_test.dart
- client/test/features/call/views/call_screen_test.dart
- client/test/features/call/views/call_ended_screen_test.dart

Modified (docs/tracking):
- _bmad-output/planning-artifacts/difficulty-calibration.md
- _bmad-output/planning-artifacts/scenario-authoring-template.md
- _bmad-output/implementation-artifacts/6-28-remove-per-scenario-difficulty.md
- _bmad-output/implementation-artifacts/sprint-status.yaml

## Change Log

- 2026-06-11 — Story 6.28 dev-story complete (T1-T13): per-scenario difficulty removed across YAML/DB/API/runtime/tools/client/docs; `display_order` hub ordering (D1); `DEFAULT_DIFFICULTY = "easy"` server fallback (D2); calibration re-anchored on run-level difficulty, `ENGINE_VERSION` 5→6 (D3). Gates: server ruff clean + pytest 880 (+5 net); client analyze clean + 451 tests. Golden-only post-EV6: waiter/girlfriend/cop-interrogation/landlord PASS; mugger + cop_hard pre-existing known-fails documented (NOT-6.28). Status → review; T14 (deploy + Pixel 9 smoke gate) pending.
