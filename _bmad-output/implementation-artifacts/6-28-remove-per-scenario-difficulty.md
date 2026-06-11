# Story 6.28: Remove Per-Scenario Difficulty

Status: ready-for-dev

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

- [ ] **T1 — Migration 013** (AC2)
  - [ ] Create `server/db/migrations/013_remove_scenario_difficulty.sql` with a header comment in the 012 style (story, what, why, replay note): `ALTER TABLE scenarios DROP COLUMN difficulty;` then `ALTER TABLE scenarios ADD COLUMN display_order INTEGER;`
  - [ ] `pytest tests/test_migrations.py` green against the prod snapshot (no refresh needed pre-deploy — the 012-era snapshot still carrying the column is exactly what proves the drop replays; post-deploy refresh is optional housekeeping)
- [ ] **T2 — Seeder** (`server/db/seed_scenarios.py`) (AC1, AC2)
  - [ ] Remove `"difficulty": meta["difficulty"],` (line 107)
  - [ ] Add `"display_order": meta.get("display_order")` with validation: present value must be a non-bool `int` (mirror the `is_free` strictness posture; ValueError on anything else); absent → None
  - [ ] Add the vestige WARNING: if `"difficulty" in meta`, `logger.warning(...)` naming the file, continue seeding
- [ ] **T3 — Queries** (`server/db/queries.py`) (AC3)
  - [ ] `_SELECT_LIST_WITH_PROGRESS`: replace the `CASE s.difficulty … END ASC` block (lines 246-252) with `COALESCE(s.display_order, 999999999) ASC, s.id ASC`; rewrite the comment at 234-236 (it currently explains the CASE trick) + the docstring at 271-276
  - [ ] `_UPSERT_SCENARIO_SQL`: drop `difficulty` from columns/values/`ON CONFLICT` SET (lines 294, 304, 317); add `display_order` to all three
- [ ] **T4 — Schemas** (`server/models/schemas.py`) (AC3)
  - [ ] Delete `difficulty: str` from `ScenarioListItem` (line 149)
  - [ ] `ScenarioDetail` docstring 166-167: "every nullable difficulty-override column" → "every nullable patience-override column"
  - [ ] `InitiateCallIn` docstring (lines 48-53): re-anchor — `difficulty` is the global pick; absent → server `DEFAULT_DIFFICULTY` ("easy"), authored fallback is GONE (Story 6.28)
- [ ] **T5 — Scenario routes** (`server/api/routes_scenarios.py`) (AC3)
  - [ ] Remove `difficulty=row["difficulty"],` at lines 87 and 140
  - [ ] Docstring line 61: ordering description → display_order
- [ ] **T6 — Runtime loaders** (`server/pipeline/scenarios.py`) (AC4)
  - [ ] Add `DEFAULT_DIFFICULTY = "easy"` module constant (near the presets, documented: D2 — server-side default when the client/env omits the global pick)
  - [ ] `resolve_patience_config`: signature `(scenario_id: str, difficulty: str | None = None)`; body: `difficulty = difficulty if difficulty is not None else DEFAULT_DIFFICULTY`; DELETE the `metadata.get("difficulty")` branch (lines 498-499); keep the `not in _DIFFICULTY_PRESETS` RuntimeError; rewrite the 6.19-era docstring (450-471)
  - [ ] `load_scenario_base_prompt`: same signature/default treatment; DELETE the authored read (lines 930-932); keep the inline-block guard (896-902), the speak-first guard, and the leak WARN (915-925) verbatim; update docstring (849-857)
  - [ ] Module-level comment at line 188 (`prompt(scenario_id, difficulty_override=…)`) → new kwarg name
- [ ] **T7 — Bot + route comments** (AC4)
  - [ ] `bot.py:129-130, 148-149`: `difficulty_override=scenario_difficulty` → `difficulty=scenario_difficulty`; comment block 119-123 re-worded (absent env → server default easy, not "authored difficulty")
  - [ ] `bot.py:930` parked-mode allowlist: NO change (verify only)
  - [ ] `routes_calls.py:340-347`: comment re-word (absence → `DEFAULT_DIFFICULTY`, drop the AC7-authored-fallback sentence); logic unchanged
- [ ] **T8 — Scenario YAMLs ×6** (AC1)
  - [ ] `the-waiter.yaml`: delete `difficulty: easy` (line 10); add `display_order: 10`; header comment line 2 → "The Waiter (Free)"; override comments lines 25-33 → "null = use the active GLOBAL-difficulty preset" (drop the per-level effective values)
  - [ ] Same treatment: `the-girlfriend.yaml` (display_order 20), `the-mugger.yaml` (30), `the-cop.yaml` (40), `cop-interrogation-01.yaml` (50 — KEEP `patience_start: 90`), `the-landlord.yaml` (60)
- [ ] **T9 — Tools** (AC5)
  - [ ] `scripts/build_scenario.py`: drop the `--difficulty` argument (lines 225-227) + the docstring example (line 5); stop forwarding it
  - [ ] `scripts/scenario_builder.py`: remove `difficulty` from the build params/docstring (line 4, 24); delete `_VALID_DIFFICULTIES` / `_PRESET_FAIL_PENALTY` / `_TARGET_ABSORBED_MISSES` (146-154); `suggest_patience_start(n_checkpoints: int)` anchored on the medium constants (`base = 20 * 4`, keep the `>12`-checkpoint bump + rounding); EXPAND_PROMPT: delete `Difficulty: {difficulty}.` from line 171 and re-word the 173-181 paragraph to mandate neutrality against the GLOBAL setting (the mandate itself STAYS — personas/segments must read identically at every global level); builder emits NO `difficulty` key in the YAML it writes (and may emit `display_order: null` placeholder with a comment)
  - [ ] `scripts/compare_difficulty.py:66`: `difficulty_override=difficulty` → `difficulty=difficulty`; module docstring sentence re-anchored (it A/Bs the GLOBAL blocks)
  - [ ] `scripts/calibrate_scenario.py`: add `--difficulty {easy,medium,hard}` (default `easy`), threaded to the engine; help text: "global difficulty level the calibration run plays at (band anchor)"
  - [ ] `scripts/calibration_engine.py`: `ENGINE_VERSION = 6` (line 129, with a dated comment explaining the 6.28 bump); `ScenarioData` drops the `difficulty` field (551, 565) — run-level difficulty becomes a parameter threaded from the CLI into `build_scenario_data` (compose `load_scenario_base_prompt(scenario_id, difficulty=run_difficulty)` + `resolve_patience_config(scenario_id, difficulty=run_difficulty)` at lines 566-569) and into `evaluate_calibration`/ledger/report (1220+, 1494-1495); drop `"difficulty"` from `_HASH_FIELDS` (line 1356); keep `_DIFFICULTY_BANDS`/`band_for_difficulty`; diagnostics wording 1687-1716: "this scenario is X" → "this run played at X"
- [ ] **T10 — Server tests** (AC2-AC5, AC9) — see the Test Inventory table in Dev Notes; headline moves:
  - [ ] `test_scenarios.py`: rename/rewrite the override tests (1523-1558) to the new kwarg; REPLACE `test_difficulty_override_none_uses_authored_difficulty` (1537-1551) with `test_difficulty_none_uses_default_easy`; same treatment for the base-prompt pair (1654-1726, 1819-1820); ordering test re-anchored on display_order (add a regression asserting the exact 6-id prod order); seeder tests: difficulty assertions out, display_order + vestige-warning tests in (loguru temp-sink per server/CLAUDE.md §3); KEEP `test_shipped_personas_have_no_difficulty_coded_phrases`; synthetic-YAML fixtures in tests that author `difficulty:` keys → remove the key (they now exercise the default path)
  - [ ] `test_calls.py`: env plumbing tests STAY (193-235, 832) — update the comment at 221-223 (absence → server default, not authored); API-shape tests asserting `difficulty` in scenario responses → assert ABSENCE
  - [ ] `test_bot_parked_mode.py`: STAYS as-is (env passthrough unchanged — verify only)
  - [ ] `test_bot_pipeline_wiring.py:348-352`: pin the new literal `difficulty=scenario_difficulty`
  - [ ] `test_scenario_builder.py` / `test_calibration_engine.py` / `test_prompts.py` / `test_score_transcript.py`: align with T9 (builder difficulty tests deleted; engine tests thread run-difficulty; score_transcript untouched)
- [ ] **T11 — Client** (AC6)
  - [ ] `client/lib/features/scenarios/models/scenario.dart`: delete field (6), ctor param (24), fromJson line (52)
  - [ ] `client/lib/features/call/views/incoming_call_screen.dart:41-52`: drop `difficulty: 'easy'` from the tutorial Scenario
  - [ ] Sweep every test fixture constructing `Scenario(...)` (analyzer-driven; expected files: `scenario_test.dart`, `scenarios_bloc_test.dart`, `scenario_list_screen_test.dart`, `scenario_card_test.dart`, `scenario_card_semantics_label_test.dart`, `scenarios_repository_test.dart`, `call_screen_test.dart`, `call_bloc_test.dart`, `call_ended_screen_test.dart`, `content_warning_sheet_test.dart`) — remove the param + the `scenario_test.dart` difficulty round-trip assertion; DO NOT touch `difficulty_storage_test.dart`, `difficulty_sheet_test.dart`, the hub-line tests, or `call_repository_test.dart` (global feature)
- [ ] **T12 — Docs** (AC7)
  - [ ] `server/CLAUDE.md` §6 + §8 re-anchor (incl. the §8 line 435 kwarg reference)
  - [ ] `_bmad-output/planning-artifacts/difficulty-calibration.md`: banner note at top (per-scenario difficulty removed 6.28; bands anchor on the run/global level)
  - [ ] `_bmad-output/planning-artifacts/scenario-authoring-template.md`: drop `difficulty: easy` from the metadata example (line 61), re-word lines 71-76 + 305 + 397
- [ ] **T13 — Golden gate + full gates** (AC8, AC9)
  - [ ] `python scripts/calibrate_scenario.py --golden-only` post-EV6: waiter PASS; document mugger/cop_hard known-fails verbatim in the Dev Agent Record
  - [ ] `ruff check .` + `ruff format --check .` + `pytest` (server) / `flutter analyze` + `flutter test` (client) — all green
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

### Debug Log References

### Completion Notes List

### File List
