# Story 6.17: Full-auto scenario pipeline + per-scenario voice (incl. accent)

Status: review

## Story

As the operator (Walid),
I want the builder to do **everything** from a single fuzzy description — write the scenario,
pick the **right voice (gender + accent + vibe)**, validate it, and land it in my app's scenario
list — so that the only thing left to me is the **human on-device test** before the formal review.

The long-term goal (Walid 2026-06-02): *"à force de calibration, trouver l'équilibre parfait pour
que je n'aie plus jamais à faire les tests manuels et que j'aie full confiance."* So the base must
be as solid as possible — tests, scenario writing (with the app's sarcastic spirit), AND voice.

## Background

Story 6.16 built the text pipeline (description → 20 coherent checkpoints). Two gaps remained:
1. **Voice was never wired.** Every scenario spoke with one hardcoded voice (`CARTESIA_VOICE_ID`,
   a British female) — `tts_factory` ignored the scenario's `tts_voice_id`. So the detective would
   have sounded like a British woman.
2. **The builder didn't choose a voice.** Walid wants the builder to pick the voice that matches the
   character (gender/accent/vibe) from Cartesia's catalog.

## Acceptance Criteria

### AC1 — Per-scenario voice actually takes effect (prod)
`bot.py` passes the scenario's `metadata.tts_voice_id` to `build_tts_service(settings, voice_id=…)`,
which threads it into the Cartesia service (`_build_cartesia`), falling back to the default
`CARTESIA_VOICE_ID` when null. Tested (capture the voice the service is built with).

### AC2 — Builder selects a matching voice (gender + accent + vibe)
The builder fetches the live Cartesia voice catalog (`GET /voices`, fields incl. gender, language,
country, description) and an LLM picks the best-matching voice id for the character brief, written
into `tts_voice_id`. Honest limit: accent fidelity is bounded by Cartesia's catalog (English voices
are US/UK/AU; Spanish/etc. voices exist for typed characters but the app is English-practice).

### AC3 — Graceful degradation without a Cartesia key
If no Cartesia key is present (e.g. running locally where only the LLM key is set) or the catalog
fetch fails, the builder leaves `tts_voice_id` null + records why; the pipeline falls back to the
default voice. Voice selection is best-effort, never fatal to a build.

### AC4 — One command does the whole pipeline
`build_scenario` runs expand → draft → adversarial critique → **voice select** → assemble →
structural-validate → (`--validate`) golden net. Output: a complete, voiced, schema-valid scenario.

### AC5 — Lands in the app's scenario list
`build_scenario --deploy` scp's the YAML to the VPS + restarts pipecat (the startup seeder
re-seeds → the scenario appears in the app's list, since the app talks to the VPS), so Walid can
test it on-device before the review. (The 6.17 prod code — voice wiring — must also be on the VPS
for the chosen voice to play; that rides the normal commit→CI deploy.)

### AC6 — Cost + determinism (don't break pytest)
Voice catalog fetch + match are live-LLM/HTTP and run only via the CLI; the LOGIC (fetch filter,
matcher validation, voice threading) has mocked unit tests in `pytest`.

### AC7 — Pre-commit gates
ruff clean; the safe (non-livekit) test subset green; full pytest reserved for Walid.

## Tasks
- [x] **Part A (prod):** wire `tts_voice_id` → `build_tts_service` → `_build_cartesia` (fallback to
      default) + `bot.py`; test captures the voice (8/8 tts_factory tests pass).
- [x] **Part B (builder):** `fetch_cartesia_voices` (catalog client) + `select_voice` (LLM matcher,
      validates the id is in the catalog) + `cartesia_api_key` on `LlmSettings`/`load_llm_settings`;
      mocked tests (fetch filter, match valid/invalid/empty, full pipeline with+without key).
- [x] **Part C:** `build_scenario` threads the voice step + writes `tts_voice_id`; CLI prints the
      chosen voice; `BuildResult` carries `voice_id` + `voice_reason`.
- [x] **Part D:** `build_scenario --deploy` (scp YAML + restart pipecat). Cop given a real voice
      (Cartesia "Ronald - Thinker", deep/intense male) in `cop-interrogation-01.yaml`.
- [x] **Gates + finalize.**

## Dev Notes
- The five Rive puppets cap the visual character; voice is independent (Cartesia). A new scenario
  reuses a puppet but can have any catalogue voice.
- **"Appears in my list" requires the VPS to have BOTH the YAML and the 6.17 prod code** (the voice
  wiring + the Story 6.16 `_multi_max_tokens` fix the cop's 20-goal judge needs). `--deploy` ships
  the YAML; the code ships via the normal commit→CI deploy. Until the code is deployed, a deployed
  scenario appears in the list but plays with the default voice.
- ElevenLabs (fallback provider) keeps its single env voice — per-scenario voice is Cartesia-only
  (documented); Cartesia is the launch default.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8[1m] (`/bmad-dev-story`, 2026-06-02). Cartesia catalog fetched live from the VPS.

### Completion Notes List
- **Voice now works end-to-end**: prod reads the scenario's `tts_voice_id` (was ignored); the
  builder picks it from the live Cartesia catalog via an LLM matcher (gender/accent/vibe), graceful
  if no key. The cop got a fitting deep-male detective voice.
- **Cartesia catalog** (fetched from the VPS, `GET /voices`, `Cartesia-Version: 2024-11-13`): ~36
  English voices (US/UK/AU) + Spanish/Hindi/etc. for typed characters; fields gender/language/
  country/description. Accent fidelity is bounded by the catalogue (no bespoke "Mexican-accented
  English" — pick the closest).
- **Landing in the app list**: `--deploy` scp's the YAML + restarts pipecat (re-seed). The chosen
  voice only PLAYS once the 6.17 prod code is on the VPS — that rides the commit→CI deploy (Walid's
  /commit gate; full pytest must pass first, which the dev sandbox can't run — livekit import hang).
- **Files**: prod `pipeline/tts_factory.py` + `pipeline/bot.py` (voice wiring); builder
  `scripts/scenario_builder.py` (fetch_cartesia_voices + select_voice + voice threading) +
  `scripts/calibration_engine.py` (`cartesia_api_key` on LlmSettings) + `scripts/build_scenario.py`
  (`--deploy`, voice print); `scenarios/cop-interrogation-01.yaml` (voice set); tests
  `tests/test_tts_factory.py` (+1) + `tests/test_scenario_builder.py` (+6).
- ruff clean; safe subset green. Full pytest + on-device test reserved for Walid; `review → done`
  + `/commit` his.
- **Character-physique matching (Walid 2026-06-02):** only 5 puppets exist and you can't invent
  one — the scenario + voice must fit the chosen puppet's look. Added `CHARACTER_PROFILES` (the 5
  puppets' fixed gender/age/look + voice hint, derived from the shipped scenarios): waiter = weary
  British woman; mugger = rough young London man; girlfriend = expressive woman ~26; cop = sharp
  adult male officer; landlord = stern older British man. The builder injects the chosen puppet's
  look into the persona prompt (a `VISUAL CONSTRAINT` — persona must match gender/age/look, only the
  name/job/situation vary) AND restricts voice selection to the puppet's gender (`required_gender`).
  So a `girlfriend` scenario can't get a male voice or a male persona.
- **Interactive wizard (Walid's "simpler command"):** double-click `scripts\new-scenario.cmd` →
  `new_scenario.py` asks (plain French) for the character (shows the 5 faces + their looks), the
  idea, difficulty, a short name → builds the whole scenario (+ voice) → **auto-validates + repairs**
  → writes it → offers to deploy. No long command to type.
- **Auto build → validate → repair loop (Walid: "aller-retour intelligent jusqu'à un scénario
  cohérent"):** `build_and_validate_scenario` builds, runs the golden net (off-topic must be
  rejected on every checkpoint), and on failure `repair_checkpoints_from_golden` TIGHTENS only the
  offending checkpoints' `success_criteria`, then re-validates — up to `max_repair_rounds` (wizard
  default **10**, Walid: "10 essais; si ça passe pas, c'est un vrai problème"). The wizard checks
  INCONCLUSIVE (judge rate-limited → all-"unsure" → no failures → a FALSE pass) BEFORE declaring
  VALIDÉ. The wizard prints **✅ VALIDÉ** (with the repair count), or ⚠️ residual failures, or
  ⚠️ INCONCLUSIVE if the judge was rate-limited (free-tier daily cap). "Fini" only after the loop.
  This is the OFF-TOPIC-correctness net (cheap, free-tier-feasible); the difficulty-band calibration
  still needs the Dev tier (daily token cap). NOTE: `pytest` is unrelated to creating scenarios — it
  only gates ME deploying the engine CODE; the operator never runs it to author a scenario.

### File List
- `server/pipeline/tts_factory.py`, `server/pipeline/bot.py` — wire scenario voice (AC1).
- `server/scripts/scenario_builder.py` — voice catalog client + matcher + threading (AC2/C).
- `server/scripts/calibration_engine.py` — `cartesia_api_key` on the minimal config (AC3).
- `server/scripts/build_scenario.py` — `--deploy`, voice print (AC4/AC5).
- `server/pipeline/scenarios/cop-interrogation-01.yaml` — real voice (AC2 demo).
- `server/tests/test_tts_factory.py`, `server/tests/test_scenario_builder.py` — tests (AC6 + profiles + gender-matched voice).
- `server/scripts/new_scenario.py`, `server/scripts/new-scenario.cmd` — the double-click wizard.
- `CHARACTER_PROFILES` in `scenario_builder.py` — the 5 puppets' fixed physique (persona + voice match it).

## Change Log
- 2026-06-02 — Built + → review. Per-scenario voice wired into prod; builder selects voice from the
  live Cartesia catalog (gender/accent/vibe) with graceful no-key degradation; `build_scenario
  --deploy` lands a scenario in the app list; cop given a real detective voice. ruff clean, safe
  subset green.
