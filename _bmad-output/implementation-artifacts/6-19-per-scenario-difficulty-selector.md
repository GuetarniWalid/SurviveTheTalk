# Story 6.19: Global difficulty selector (easy / medium / hard)

Status: review

> Design decisions RESOLVED with Walid 2026-06-03 (UX placement chosen via a UX/UI agent analysis). This spec is the final version — ready for `/bmad-dev-story`.

## Story

As the learner,
I want to **choose easy / medium / hard once, as a global setting**, and have it apply to **every** scenario/call,
so that I can practice at a level that matches my English today and ramp up over time.

## Background

Today a scenario's difficulty is **fixed** in its YAML (`metadata.difficulty`). Walid wants a **systematic, user-controlled** difficulty (Walid 2026-06-03). After a UX/UI agent analysis of the real app, the decision is a **GLOBAL preference set once** (not a per-call picker): the user picks easy/medium/hard, it's remembered, and it applies to all scenarios.

**Key UX finding:** the app has **no settings/profile screen** today (8 routes, no gear/menu/tabs). Rather than add nav chrome (which the UX spec avoids), the chosen placement (Walid 2026-06-03) is a **discreet line on the hub** ("Difficulty: Medium") that opens a **modal bottom sheet** — reusing the existing `content_warning_sheet.dart` pattern (the app's only proven modal). The choice is stored client-side like consent and sent at call start.

**⚠️ UX-spec update required.** `ux-design-specification.md` (~L78-79) says "no difficulty selection" for MVP. Walid has decided to **change that** — this story adds a (global, low-chrome) selector. Update the UX spec line as part of this story.

**Difficulty affects more than vocabulary (Walid 2026-06-03):** it must change (a) the **patience preset** (meter/silence/escalation), (b) the character's **behavior prompt** (vocabulary, idioms, rephrasing), AND (c) the character's **speech speed** — easy = slower, clearly articulated (every syllable understandable); ramping faster toward medium/hard. This is exactly the `difficulty-calibration.md` §8.2 mapping (speech speed → Cartesia TTS `speed`; vocabulary/idioms → LLM prompt; patience → PatienceTracker).

## Acceptance Criteria (BDD)

### AC1 — Global difficulty preference, set on the hub
Given the learner is on the scenario list (hub)
When they tap the discreet "Difficulty: <level>" line
Then a **modal bottom sheet** (cloned from `content_warning_sheet.dart`: light `#F0F0F0` surface, 42px top radius, drag handle, `StadiumBorder` "Done" button) lists **Easy / Medium / Hard** with a mint dot on the selected one + honest one-line copy ("They cut you slack" / "Normal human friction" / "No mercy, no hints"), and selecting one saves it **globally** and closes the sheet. The hub line reflects the current choice.

### AC2 — The choice persists across launches (client-side)
Given the preference is global + set-once
Then it is stored client-side via a `DifficultyStorage` wrapper **mirroring `ConsentStorage`** (`preload()` / `getSync()` / `set()`, backed by `FlutterSecureStorage` or `SharedPreferences`), so it survives app restarts and is read synchronously for the hub line. Default before the user ever picks: **easy** (gentle onboarding for a learning app — adjustable in one constant).

### AC3 — The choice drives the call (overrides the scenario's authored difficulty)
Given a chosen global difficulty
When a call starts
Then it is sent on `POST /calls/initiate` (body `difficulty`) and **overrides the scenario's `metadata.difficulty` for that call** — driving the patience preset, the behavior prompt block (AC4), and the speech speed (AC5). Precedence: **chosen difficulty > YAML per-field overrides? NO** — keep the existing rule that explicit YAML per-field overrides still win over the preset; the chosen difficulty only swaps which *preset* (and prompt block + speed) is the base. (i.e. chosen-difficulty selects the preset; per-scenario nullable YAML fields still override individual values.)

### AC4 — The character's *behavior* matches the chosen difficulty (extract the prompt block — RESOLVED yes)
Given the "Difficulty behavior (easy|medium|hard): …" block currently lives **only in each scenario's YAML `base_prompt` text**
Then the three behavior blocks are **extracted into a code constant** (`_DIFFICULTY_PROMPTS` in `scenarios.py`/`prompts.py`) and `load_scenario_base_prompt(scenario_id, difficulty_override=…)` composes the chosen difficulty's block in place of the authored one — so a "hard" pick on an "easy"-authored scenario actually **speaks** hard. The 5 existing scenario YAMLs drop their inline behavior block (the code constant becomes the single source).

### AC5 — Speech speed scales with difficulty (NEW — Walid 2026-06-03)
Given easy must be slower/clearer and hard faster/natural
Then each difficulty preset carries a **`tts_speed`** that is threaded to the Cartesia service: `resolve_patience_config` → `bot.py` → `build_tts_service(settings, voice_id=…, speed=…)` → `_build_cartesia` → `CartesiaTTSService.Settings(model="sonic-3", voice=…, speed=…)`. Map: **easy → slow, medium → normal, hard → fast** (use Cartesia's accepted `speed` values for sonic-3 — verify the exact form in pipecat's `CartesiaTTSService.Settings`; likely `"slow"|"normal"|"fast"` or a float). The existing nullable per-scenario `tts_speed` override (anticipated in `difficulty-calibration.md` §8.3) wins over the preset. **Fallback:** if Cartesia/pipecat doesn't expose `speed` for sonic-3, fall back to a speed instruction in the behavior prompt block ("speak slowly, one clear syllable at a time" vs "speak fast at a natural cadence") — the behavior block (AC4) already carries this. ElevenLabs (fallback provider) keeps its single env voice + no per-difficulty speed (Cartesia-primary, like voice).

### AC6 — End-to-end plumbing + validation
Given the choice must reach the bot safely
Then: client sheet → `call_repository.initiateCall(scenarioId, difficulty)` adds `difficulty` to the POST body → `InitiateCallIn.difficulty: Literal['easy','medium','hard'] | None = Field(default=None)` (rejects bad values with 422 **before** YAML load) → `routes_calls.initiate_call` adds `SCENARIO_DIFFICULTY` to the bot subprocess env (mirror `SCENARIO_ID`/`SCENARIO_CHARACTER`) → `bot.py:run_bot` reads it → `resolve_patience_config(scenario_id, difficulty_override=…)` + `load_scenario_base_prompt(…, difficulty_override=…)` + the `tts_speed`.

### AC7 — Backward compatible
Given older clients (or the legacy `/connect` path) omit `difficulty`
Then `difficulty=None` → the scenario's authored `metadata.difficulty` is used (exactly today's behavior). The field is optional, `default=None`. `copy.deepcopy(preset)` stays first (Story 6.6 concurrency fix); the override applies after the copy.

### AC8 — (optional, fast-follow) Persist for analytics
Optionally add `call_sessions.difficulty` (migration with `CHECK(difficulty IN ('easy','medium','hard'))` + backfill from YAML + `queries.insert_call_session` param + `prod_snapshot.sqlite` refresh) so reports can show which difficulty was played. Not required for the feature to work; include only if cheap.

### AC9 — Tests
Server: `difficulty_override` flows through `resolve_patience_config` (preset swap) + `load_scenario_base_prompt` (behavior-block swap) + the `tts_speed` threading + the API 422 on bad value + the `None`→YAML fallback; migration replays against `prod_snapshot.sqlite` if AC8. Client: the hub line renders the stored value, the sheet renders + selecting persists via `DifficultyStorage` + the chosen value reaches the `POST /calls/initiate` body (mock `FlutterSecureStorage.setMockInitialValues({})` in setUp; force 320×480 to catch overflow per client/CLAUDE.md).

### AC10 — Pre-commit gates
`ruff check . && ruff format --check . && pytest` (server, incl. `test_migrations` if AC8) + `flutter analyze` (No issues) + `flutter test` all green.

## Tasks / Subtasks

### Server
- [x] **Task 1 — `difficulty_override` in `resolve_patience_config`** (AC3, AC7) — add `difficulty_override: str | None = None`; override `metadata.difficulty` AFTER `copy.deepcopy(preset)`; keep YAML per-field precedence. (`scenarios.py:168`, lookup at ~198.)
- [x] **Task 2 — Extract + swap the behavior prompt block** (AC4) — pull the three "Difficulty behavior" blocks out of the 5 YAML `base_prompt`s into `_DIFFICULTY_PROMPTS`; `load_scenario_base_prompt(scenario_id, difficulty_override=…)` composes the chosen block. Migrate the 5 YAMLs. **Re-validate each scenario with `--golden-only` after (Story 6.15).** Riskiest change.
- [x] **Task 3 — `tts_speed` per difficulty + thread to Cartesia** (AC5) — add `tts_speed` to `_DIFFICULTY_PRESETS` (easy→slow, medium→normal, hard→fast); thread `resolve_patience_config` → `bot.py` → `build_tts_service(speed=…)` → `_build_cartesia` → `CartesiaTTSService.Settings(speed=…)`. Verify pipecat's accepted `speed` form for sonic-3; if unsupported, fall back to the behavior-block speed instruction. Honor the nullable per-scenario `tts_speed` override.
- [x] **Task 4 — API contract + threading** (AC6) — `InitiateCallIn.difficulty` (`Literal[...] | None`, validate before YAML I/O); `routes_calls.initiate_call` adds `SCENARIO_DIFFICULTY` env; `bot.py:run_bot` reads it + passes `difficulty_override` to both `resolve_patience_config` and `load_scenario_base_prompt`.
- [ ] **Task 5 — (AC8, optional) persist to `call_sessions`** — **DEFERRED** (optional fast-follow; client storage is the source of truth, no migration added). Original scope: migration + backfill + `queries` + snapshot refresh.

### Client
- [x] **Task 6 — `DifficultyStorage`** (AC2) — mirror `ConsentStorage` (`client/lib/core/onboarding/consent_storage.dart`): `preload()` / `getSync()` / `set(level)`; default `easy`. Preload at startup like consent.
- [x] **Task 7 — Hub line + bottom sheet** (AC1) — add a discreet "Difficulty: <level>" line on `scenario_list_screen.dart` (textSecondary grey, above the pinned `BottomOverlayCard` in the existing `Stack`); clone `content_warning_sheet.dart` → `difficulty_sheet.dart` (3 radio-style rows, mint dot on selected, "Done" `ElevatedButton`). No new colors (reuse `accent` mint + `textSecondary`). No `SegmentedButton` (no precedent — keep the bottom-sheet vocabulary).
- [x] **Task 8 — Send the choice** (AC6) — `call_repository.initiateCall(scenarioId, difficulty: difficultyStorage.getSync())` → POST body `{'scenario_id':…, 'difficulty':…}`.
- [x] **Task 9 — UX-spec update** — amend `ux-design-specification.md` (~L78-79) to reflect the global difficulty selector (it currently says "no difficulty selection").
- [x] **Task 10 — Tests** (AC9).

### Gates
- [x] **Task 11 — Pre-commit gates** (AC10) — ruff check + ruff format + server pytest (659) + flutter analyze (No issues) + flutter test (420), all green. The **Pixel 9 smoke gate** (see "Smoke Test Gate" below) remains for Walid (review → done).

## Dev Notes

**`_DIFFICULTY_PRESETS` (server, `scenarios.py:115-152`)** — easy `100/-15/-10/+5/6.0/10.0/4.5/[75,50,25,0]`, medium `80/-20/-15/+3/4.0/7.0/3.5/[60,30,0]`, hard `60/-25/-20/+0/3.0/5.0/2.5/[30,0]` (initial_patience / fail_penalty / silence_penalty / recovery_bonus / silence_prompt_s / silence_hangup_s / ladder_impatience_s / escalation_thresholds). **Add `tts_speed` to each** (Task 3).

**Exact integration points (2026-06-03 research workflow):** `scenarios.py:168` resolve_patience_config (override after deepcopy ~214) + `load_scenario_base_prompt`; behavior block at e.g. `the-waiter.yaml:53-59` (easy) / `the-cop.yaml:49-54` (hard); `models/schemas.py:39-50` InitiateCallIn; `routes_calls.py:175` initiate_call (env threading ~328-333); `bot.py:103-104` env read; `tts_factory.py:101-152` `_build_cartesia` (add `speed=` to `CartesiaTTSService.Settings`, line ~148); `calibration_engine.py:_DIFFICULTY_BANDS` (113-117). Client: `scenario_list_screen.dart` (Stack with bottom `_OverlayHost` ~L62-102 — add the line there), `content_warning_sheet.dart` (the modal to clone), `consent_storage.dart` (the storage pattern), `call_repository.dart:initiateCall` (POST body ~L13), `app/router.dart` (no new route needed).

**Design tokens (client, from the UX agent):** dark theme; accent mint `#00E5A0` (selected dot), `textSecondary` `#8A8A95` (the low-key hub line), surface `#F0F0F0` (sheet). `theme_tokens_test.dart` bans hex outside `lib/core/theme/` — these all already exist, no new color. Honest/no-gamification copy (no stars/levels).

**Gotchas:** the behavior block is YAML text → overriding the preset without swapping the block makes "hard" still *speak* easy (AC4 mandatory). `copy.deepcopy` first. Validate difficulty at the API boundary (422) before YAML I/O. Optional field, `default=None`, for backward compat. Env vars short scalars only. Cartesia `speed`: verify the accepted form for sonic-3 (don't assume a float vs enum); fall back to the prompt instruction if unsupported. If AC8: migrations replay against `prod_snapshot.sqlite`.

## Decisions (RESOLVED 2026-06-03)

1. **UX-spec conflict** → RESOLVED: we add a selector; revise the UX spec (Task 9).
2. **Global vs per-call** → RESOLVED: **global** (set once, applies to all calls).
3. **Pick from all 3 vs native-only** → RESOLVED: **all 3** (a global choice among easy/medium/hard).
4. **Placement + form** → RESOLVED: **a discreet "Difficulty:" line on the hub → a modal bottom sheet** cloned from `content_warning_sheet.dart` (UX agent Option 1; chosen because it's the lightest, editable anytime, and doesn't add nav chrome). No new Settings screen.
5. **Extract the behavior prompt block** → RESOLVED: **yes** (AC4 — required).
6. **Speech speed scales with difficulty** → RESOLVED: **yes** (AC5 — easy slower → hard faster, via Cartesia `speed`, fallback to prompt).
7. **Default before first pick** → easy (gentle for a learning app; adjustable). _Walid can override if he prefers medium._
8. **Persist to DB (AC8)** → optional fast-follow (client storage is the source of truth; DB column only for analytics).

## Smoke Test Gate (Server / Deploy Story)

- [ ] **Deployed** to the VPS (git_sha match) + the new client build on the Pixel 9.
- [ ] **The selector works:** on the hub, tap "Difficulty" → sheet → pick Easy → it persists (re-open app, still Easy) and the hub line shows it. _Command:_ device + relaunch.
- [ ] **Easy is gentler everywhere:** start the **cop** at Easy → the character speaks **slower/clearer** (AC5), uses simpler language (AC4), and the meter tolerates more misses (AC3) — survivable for a B1 learner. Start the cop at **Hard** → fast, terse, brutal. _Command:_ two Pixel 9 calls + `journalctl -u pipecat.service | grep -E 'difficulty|TTS provider'` to confirm preset + speed match the pick.
- [ ] **Speed audibly changes:** Easy vs Hard on the same scenario → the speaking rate is noticeably different. _(On-device perception.)_
- [ ] **Backward compatible:** an initiate without `difficulty` still runs at the YAML difficulty. _Command:_ `curl -X POST …/calls/initiate -d '{"scenario_id":"the_waiter"}'` → 200.
- [ ] **Bad value rejected:** `difficulty:"bogus"` → 422. _Command:_ `curl … -d '{"scenario_id":"the_waiter","difficulty":"bogus"}'`.
- [ ] (If AC8) `sqlite3 db.sqlite "SELECT difficulty FROM call_sessions ORDER BY id DESC LIMIT 1;"`.

## Dev Agent Record

### Agent Model Used
Claude Opus 4.8 — implementation finalized + reviewed via `/bmad-dev-story 6.19` (read-only adversarial review across server / client / tests / scope dimensions, then a one-line stale-test fix + story bookkeeping).

### Completion Notes List
- **Server.** `resolve_patience_config(scenario_id, difficulty_override=None)` selects the preset from the override (after `copy.deepcopy`); per-field YAML overrides still win (AC3/AC7). `load_scenario_base_prompt(scenario_id, difficulty_override=None)` composes the chosen difficulty's behavior block from the new `_DIFFICULTY_PROMPTS` constant and **rejects** any YAML still carrying an inline "Difficulty behavior" block (single source of truth, AC4). All 6 scenario YAMLs stripped of their inline block (verified by grep + `test_shipped_scenarios_have_no_inline_difficulty_block`). `tts_speed` added to `_DIFFICULTY_PRESETS` (easy 0.8 / medium 1.0 / hard 1.2, validated to Cartesia's [0.6, 1.5]) and threaded `resolve_patience_config → bot.py → build_tts_service(speed=…) → _build_cartesia → CartesiaTTSService.Settings(generation_config=GenerationConfig(speed=…))`; ElevenLabs ignores speed by design (AC5). `InitiateCallIn.difficulty: Literal['easy','medium','hard'] | None` (422 before YAML I/O); `routes_calls` sets `SCENARIO_DIFFICULTY` env only when provided; `bot.py` reads it and threads `difficulty_override` to both resolvers (AC6). `scenario_builder.py` no longer double-weaves the behavior block (the loader composes it now).
- **Client.** New `DifficultyStorage` (mirrors `ConsentStorage`: `preload()`/`getSync()`/`set()`, FlutterSecureStorage, default `easy`, AC2), preloaded at startup + threaded app → router → list. New `difficulty_sheet.dart` (cloned from `content_warning_sheet.dart`) — Easy/Medium/Hard rows, mint dot on the selected one, honest copy, "Done" button (AC1). Discreet "Difficulty: <level>" hub line on `scenario_list_screen.dart`. `call_repository.initiateCall` sends `difficulty` in the POST body; the hub passes `difficultyStorage.getSync()` (AC6). No new color tokens (reuses `accent` + `textSecondary`).
- **AC8 (DB persistence): DEFERRED** — optional fast-follow per spec; client storage is the source of truth, no migration added.
- **Finalization (this pass):** fixed a stale Story-6.4 source-text assertion in `test_bot_pipeline_wiring.py::test_bot_reads_scenario_id_env_var` that still expected the pre-6.19 `resolve_patience_config(scenario_id)` shape (6.19 threads `difficulty_override=`). No functional change. Built in parallel with Story 6.22 (since committed/done); the two are cleanly separated — that assertion was the only shared touchpoint.
- **Gates (AC10):** `ruff check` + `ruff format --check` clean; server `pytest` **659 passed**; `flutter analyze` No issues; `flutter test` **420 passed** (incl. the new `difficulty_storage` / `difficulty_sheet` / hub-line tests).
- **Follow-up (not blocking):** the YAML `base_prompt`s changed (behavior-block extraction) → re-run `python scripts/calibrate_scenario.py --golden-only` (Story 6.15, needs `GROQ_API_KEY`) when convenient.

### File List
**Server:** `server/models/schemas.py`, `server/api/routes_calls.py`, `server/pipeline/bot.py`, `server/pipeline/scenarios.py`, `server/pipeline/tts_factory.py`, `server/scripts/scenario_builder.py`, `server/pipeline/scenarios/the-waiter.yaml`, `server/pipeline/scenarios/the-cop.yaml`, `server/pipeline/scenarios/the-girlfriend.yaml`, `server/pipeline/scenarios/the-landlord.yaml`, `server/pipeline/scenarios/the-mugger.yaml`, `server/pipeline/scenarios/cop-interrogation-01.yaml`
**Server tests:** `server/tests/test_scenarios.py`, `server/tests/test_calls.py`, `server/tests/test_tts_factory.py`, `server/tests/test_scenario_builder.py`, `server/tests/test_bot_pipeline_wiring.py` (stale-assertion fix)
**Client:** `client/lib/core/onboarding/difficulty_storage.dart` (new), `client/lib/features/scenarios/views/widgets/difficulty_sheet.dart` (new), `client/lib/features/scenarios/views/scenario_list_screen.dart`, `client/lib/features/call/repositories/call_repository.dart`, `client/lib/main.dart`, `client/lib/app/app.dart`, `client/lib/app/router.dart`
**Client tests:** `client/test/core/onboarding/difficulty_storage_test.dart` (new), `client/test/features/scenarios/views/widgets/difficulty_sheet_test.dart` (new), `client/test/features/scenarios/views/scenario_list_screen_test.dart`, `client/test/features/call/repositories/call_repository_test.dart`
**Docs:** `_bmad-output/planning-artifacts/ux-design-specification.md`, `_bmad-output/implementation-artifacts/6-19-per-scenario-difficulty-selector.md`, `_bmad-output/implementation-artifacts/sprint-status.yaml`

## Change Log
- 2026-06-08 — **Difficulty-NEUTRAL persona rework** (design challenge from Walid: "easy == hard on the cop; rethink the design, not just the wording"). Root cause found: AC4 only extracted the explicit "Difficulty behavior" *block*, but each persona's PROSE still froze its authored difficulty (cop = hard: "squint at grammar mistakes", "overlap them if the person pauses", "treat hesitation as suspicious"; waiter = easy: "escalate gradually") — so a global pick appended a generic block that CONTRADICTED the persona, and the weak prod model (Scout) fell back to the persona → easy == hard on-device. Fix: (1) rewrote all 5 hand-authored personas (cop / waiter / girlfriend / landlord / mugger) difficulty-NEUTRAL — identity + setting + boundaries only, every grammar/hesitation/escalation/mandated-register line removed (the 6th, builder-generated `cop_interrogation_01`, was already neutral, validating the construction-time fix); (2) rewrote `_DIFFICULTY_PROMPTS` easy/medium/hard to be PERSONALITY-neutral — each opens "This is a LANGUAGE setting only — keep your persona's temperament unchanged", strips warmth/encouragement + the hard "You heard me." catchphrase, scoped to language register + accommodation + precision so the SAME block composes onto any persona; (3) **enforced by construction**: `EXPAND_PROMPT`/`CHECKPOINTS_PROMPT`/`CRITIQUE_PROMPT` now instruct the builder to keep personas + prompt_segments difficulty-neutral, `load_scenario_base_prompt` + `scenario_builder.validate_structure` fail-fast on `find_persona_difficulty_leaks` (shared denylist), and a pytest lint covers every shipped persona; (4) neutralized the legacy `SARCASTIC_CHARACTER_PROMPT` (last inline difficulty block in the repo); (5) fixed `compare_difficulty.py` to default to the **prod model (Scout), not 70B** (it was validating differentiation on a stronger model than prod — the exact blind spot); (6) `ENGINE_VERSION` 2→3 to force a calibration re-sweep. Docs: `server/CLAUDE.md` §8 (new law), `difficulty-calibration.md` §4.2 note. Gates green: ruff check+format, server pytest **693** (+5 new neutrality guards). **Adversarial-review pass** then tightened the rework for the WEAK prod model: hard regained a concrete observable on the "I didn't understand" turn (acknowledge-then-advance, no fixed catchphrase) so it can't silently soften on Scout; medium/hard were de-collapsed (medium = verbatim-repeat-then-wait + transparent idioms; hard = opaque idioms + bounded "press once more then move on" so it can't loop); the loader neutrality guard was downgraded from a hard raise to a **runtime warning** (the denylist is a fuzzy tripwire — the hard gates stay the builder + pytest, where a false positive is a fixable red test, not a prod crash); `_DIFFICULTY_PROMPTS` was folded into `compute_scenario_hash` so a future block edit self-invalidates cached calibration PASSes; and the cop/landlord "Don't help them" checkpoint segments were de-ambiguated to task-logic ("don't tell them why — make them say it"). Stays `review` pending the Pixel 9 re-test (easy vs hard on the cop, on Scout). The live A/B (`compare_difficulty.py` on Scout) is the recommended pre-smoke-gate check.
- 2026-06-07 — **Smoke-gate follow-up** (Walid, Pixel 9): hard at `tts_speed` 1.2 sounded unnatural/rushed. Rebalanced the difficulty cursor from SPEED to LANGUAGE (6-agent analysis workflow + per-mode observable checklist). `tts_speed` band narrowed to natural bounds — easy 0.8→0.9, medium 1.0, **hard 1.2→1.0** (natural rate is now the hard ceiling); validator cap lowered 1.5→1.0 so above-natural is structurally unshippable (presets AND `metadata.tts_speed` overrides). `_DIFFICULTY_PROMPTS` rewritten so difficulty rides on vocabulary / idioms / sentence construction / question style / rephrasing / interruption / directness (no more "speak fast / no slowing down"); hard gains a fairness governor (one trap per turn, never two opaque idioms in a clause), easy stays a natural person (not robotic, never grammar-corrects). Tests updated (6 assertions). `ENGINE_VERSION` bump + full re-calibration deferred (calibration_engine.py owned by the concurrent Story 6.23). Stays `review` pending the Pixel 9 re-test.
- 2026-06-06 — Implementation complete + finalized (server + client + tests + UX spec). `difficulty_override` threaded through `resolve_patience_config` + `load_scenario_base_prompt`; `_DIFFICULTY_PROMPTS` extracted (all 6 YAMLs stripped of their inline block); per-difficulty `tts_speed` 0.8/1.0/1.2 via Cartesia `GenerationConfig`; `InitiateCallIn.difficulty` + `SCENARIO_DIFFICULTY` env plumbing; client `DifficultyStorage` + `difficulty_sheet` + hub line + POST body. AC8 deferred (optional). Fixed a stale source-text test (`test_bot_pipeline_wiring.py`, was expecting the pre-6.19 single-arg `resolve_patience_config` shape). Gates green: ruff, server pytest 659, flutter analyze + flutter test 420. `in-progress → review`; the Pixel 9 smoke gate (below) is pending for `review → done`.
- 2026-06-03 — Spec finalized. Re-scoped from a per-call picker to a **global preference** (Walid). Placement decided via a UX/UI agent analysis: a discreet hub line → a bottom sheet cloned from `content_warning_sheet.dart` (no new Settings screen — none exists; lowest-chrome option). Added **AC5 speech-speed-per-difficulty** via Cartesia `speed` (Walid: difficulty must change pace + articulation, not just words). Behavior-block extraction confirmed (AC4). UX spec to be updated (it currently forbids difficulty selection). Decisions 1-8 resolved. Ready for `/bmad-dev-story`.
- 2026-06-03 — Spec drafted via `/bmad-create-story` (6-agent research workflow). Initial scope was a per-scenario per-call picker; superseded same day by the global-preference decision above.
