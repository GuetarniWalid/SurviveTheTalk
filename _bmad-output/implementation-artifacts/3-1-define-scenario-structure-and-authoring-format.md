# Story 3.1: Define Scenario Structure and Authoring Format

Status: done

## Story

As a product owner,
I want a documented scenario structure defining all required fields and their format,
So that scenarios can be created consistently and loaded by the Pipecat pipeline.

## Acceptance Criteria

1. **Given** the Architecture defines a `scenarios` table (id, title, system_prompt, difficulty, is_free, briefing_text, content_warning, rive_character, expected_exchanges, language_focus, patience_start, fail_penalty, silence_penalty, recovery_bonus, silence_prompt_seconds, silence_hangup_seconds, escalation_thresholds, tts_voice_id)
   **When** the scenario structure is finalized
   **Then** a documented template exists at `_bmad-output/planning-artifacts/scenario-authoring-template.md` covering: system prompt format, debrief generation parameters, briefing text format, content warning criteria, difficulty calibration parameters, and rive_character assignment

2. **Given** the operator (Walid) authors scenarios manually
   **When** the authoring workflow is defined
   **Then** the template document includes a step-by-step authoring process: write system prompt → configure metadata → test with pipeline → run `score_transcript.py` → validate calibration → write briefing → push to production

3. **Given** FR42 requires difficulty adjustment without code changes
   **When** the scenario format is designed
   **Then** all difficulty parameters (patience_start, fail_penalty, silence_penalty, recovery_bonus, silence_prompt_seconds, silence_hangup_seconds, escalation_thresholds) are documented as nullable fields that default to difficulty preset values from `difficulty-calibration.md` §4.3

4. **Given** an example scenario is needed to validate the template
   **When** the template is complete
   **Then** a fully worked example scenario file exists at `_bmad-output/planning-artifacts/scenarios/example-the-waiter.md` using "The Waiter" (easy difficulty) with all fields filled in, demonstrating every section of the template

5. **Given** system prompts must produce consistent character behavior
   **When** the system prompt format is designed
   **Then** the template defines mandatory prompt sections (character identity, scenario context, personality rules, difficulty behavior rules, escalation behavior, exit lines) and includes annotated guidance for each section

## Tasks / Subtasks

- [x] Task 1: Create the scenario authoring template document (AC: #1, #3, #5)
  - [x] Create `_bmad-output/planning-artifacts/scenario-authoring-template.md`
  - [x] Define the metadata header section (all scenario table fields with types, descriptions, and default logic)
  - [x] Define the system prompt format with mandatory sections and annotated guidance
  - [x] Define briefing text format and content warning criteria
  - [x] Define difficulty preset defaults table (from `difficulty-calibration.md` §4.3)
  - [x] Document nullable override fields and their inheritance logic
  - [x] Document rive_character field — valid values: mugger, waiter, girlfriend, cop, landlord
  - [x] Document tts_voice_id field — how to select per-character voice
  - [x] Document debrief-related metadata (language_focus as comma-separated string, expected_exchanges)
- [x] Task 2: Define the authoring workflow process (AC: #2)
  - [x] Write the step-by-step authoring process section in the template document
  - [x] Reference tools from Story 3.0: TranscriptLogger for capture, `score_transcript.py` for scoring
  - [x] Reference calibration validation checklist from `scenario-testing-process.md` §5
  - [x] Define the "configure on VPS → test → score → validate → adjust → retest" loop
  - [x] Document how to push a scenario to production (SSH to VPS, edit `prompts.py`, restart service)
- [x] Task 3: Create the example scenario file (AC: #4)
  - [x] Create `_bmad-output/planning-artifacts/scenarios/` directory
  - [x] Create `_bmad-output/planning-artifacts/scenarios/example-the-waiter.md`
  - [x] Fill all metadata fields for "The Waiter" (easy difficulty, is_free=true, rive_character=waiter)
  - [x] Write a complete system prompt following the template format — personality, scenario context, difficulty behavior, escalation, exit lines
  - [x] Write briefing text for the waiter scenario (key vocabulary, context, what to expect)
  - [x] Set content_warning to null (waiter scenario is non-threatening)
  - [x] Set difficulty calibration overrides to null (uses easy defaults)
  - [x] Include expected_exchanges, language_focus, and all metadata
  - [x] Include character-specific hang-up and completion exit lines per UX spec

## Dev Notes

### Story Type: Documentation Only (No Code)

This story produces **documentation files only** — Markdown files in `_bmad-output/planning-artifacts/`. No Flutter code. No Python code. No tests required.

**Pre-commit validation is NOT applicable** — there are no code changes to validate. This story is complete when the documents exist and satisfy the acceptance criteria.

### Key Source Documents

These documents contain all the technical specifications that the template must reference:

1. **`difficulty-calibration.md`** — The primary reference. Contains:
   - §3: Scoring definitions (exchange success criteria, survival % formula)
   - §4.2: Difficulty levers catalog (every knob available for tuning)
   - §4.3: Difficulty presets table (default values for easy/medium/hard)
   - §5.3: AI scoring system prompt (used by `score_transcript.py`)
   - §8.3: Scenario config schema (technical field definitions)
   [Source: _bmad-output/planning-artifacts/difficulty-calibration.md]

2. **`scenario-testing-process.md`** — The testing workflow:
   - §2: Process overview diagram (configure → play → capture → score → validate → adjust → retest)
   - §3: Technical components (TranscriptLogger, score_transcript.py) — built in Story 3.0
   - §4: Step-by-step testing process
   - §5: Calibration test checklist template
   [Source: _bmad-output/planning-artifacts/scenario-testing-process.md]

3. **Architecture** — Database schema and API patterns:
   - `scenarios` table definition with all columns
   - Rive character variants: mugger, waiter, girlfriend, cop, landlord (EnumInput in the .riv file)
   - LiveKit data channel messages: emotion, viseme, hang_up_warning, call_end
   [Source: _bmad-output/planning-artifacts/architecture.md]

4. **UX Design Spec** — Character behavior and call experience:
   - §Phase 3: Character reaction system (Rive emotional states table)
   - §Phase 4: Hang-up exit lines and completion exit lines per character
   - §Phase 2: Scene setting — character speaks first, sets the scenario
   [Source: _bmad-output/planning-artifacts/ux-design-specification.md]

5. **PRD** — Business requirements:
   - FR19: First scenario calibrated for near-guaranteed success
   - FR38: Content warnings for threat/confrontation scenarios
   - FR40-42: Operator scenario authoring and difficulty adjustment
   [Source: _bmad-output/planning-artifacts/prd.md]

### Scenario Metadata Fields Reference

From `difficulty-calibration.md` §8.3 and `architecture.md`:

| Field | Type | Description | Default |
|-------|------|-------------|---------|
| `id` | string | Unique scenario identifier | Required |
| `title` | string | Display name (e.g., "The Waiter") | Required |
| `system_prompt` | text | Complete character behavior prompt | Required |
| `difficulty` | enum | `easy`, `medium`, or `hard` | Required |
| `is_free` | boolean | Available to free users | Required |
| `briefing_text` | text | Pre-call vocabulary/context (FR14) | Required |
| `content_warning` | text/null | Shown before threatening scenarios (FR38) | Null if non-threatening |
| `rive_character` | string | Rive EnumInput value: mugger/waiter/girlfriend/cop/landlord | Required |
| `expected_exchanges` | integer | Narrative arc length (scenario-defined, NOT difficulty-defined) | Required |
| `language_focus` | string | Comma-separated target areas (e.g., "ordering food,polite requests") | Required |
| `patience_start` | integer/null | Override default patience meter | Null = difficulty preset |
| `fail_penalty` | integer/null | Override failed exchange penalty | Null = difficulty preset |
| `silence_penalty` | integer/null | Override silence penalty | Null = difficulty preset |
| `recovery_bonus` | integer/null | Override recovery per success | Null = difficulty preset |
| `silence_prompt_seconds` | integer/null | Override silence tolerance (prompt) | Null = difficulty preset |
| `silence_hangup_seconds` | integer/null | Override silence tolerance (hang-up) | Null = difficulty preset |
| `escalation_thresholds` | JSON array/null | Override escalation stages (e.g., [75,50,25,0]) | Null = difficulty preset |
| `tts_voice_id` | string | Cartesia voice ID for this character | Required |

**Important:** Nullable fields inherit from the difficulty preset defaults (§4.3). Most scenarios should just set `difficulty: "easy"` and get all defaults. Override only when calibration testing shows the need.

### Difficulty Presets Quick Reference

From `difficulty-calibration.md` §4.3:

| Parameter | Easy | Medium | Hard |
|-----------|------|--------|------|
| patience_start | 100 | 80 | 60 |
| fail_penalty | -15 | -20 | -25 |
| silence_penalty | -10 | -15 | -20 |
| recovery_bonus | +5 | +3 | +0 |
| silence_prompt_seconds | 6 | 4 | 3 |
| silence_hangup_seconds | 10 | 7 | 5 |
| escalation_thresholds | [75,50,25,0] | [60,30,0] | [30,0] |
| B1 first-attempt survival target | 60-80% | 35-55% | 15-35% |

### System Prompt Structure

The template must define these mandatory sections for every scenario system prompt:

1. **Character Identity** — Who the character is, their background, their personality traits
2. **Scenario Context** — The situation, what happened before this call, the stakes
3. **Personality Rules** — How the character speaks, their tone, emotional register
4. **Difficulty Behavior Rules** — Speech speed, vocabulary level, idiomatic expressions, rephrasing behavior (pulled from difficulty-calibration.md §4.2 categories B and C)
5. **Escalation Behavior** — How the character escalates frustration, stage descriptions
6. **Hang-up Exit Line** — The character's dramatic exit line when patience hits 0
7. **Completion Exit Line** — The character's grudging acceptance when user completes all exchanges
8. **Behavioral Boundaries** — What the character will NEVER do (slurs, threats, truly offensive content per FR35)
9. **Opening Line** — The character's first line that sets the scene (character always speaks first per UX spec)

### Briefing Text Format

From PRD FR14 and UX spec: a short pre-call briefing shown before the first attempt at a scenario. Contains:
- 2-3 key vocabulary words the user might need
- Brief context of the situation (1-2 sentences)
- What to expect from the character's behavior (1 sentence)

The briefing should be **helpful without being a spoiler** — it reduces anxiety on first attempt without removing the surprise element.

### Content Warning Criteria

From PRD FR38: content warnings are displayed before scenarios involving:
- **Threat** — mugger scenario (physical threat)
- **Confrontation** — angry landlord, cop (authority pressure)
- **Emotional intensity** — girlfriend scenario (emotional confrontation)

Non-threatening scenarios (waiter, interviewer) have `content_warning = null`.

The content_warning text should be 1-2 sentences describing the nature of the scenario's intensity.

### Rive Character Variants

From Architecture: the Rive character file exposes a `character` EnumInput with 5 values:
- `mugger` — Street criminal
- `waiter` — Restaurant server
- `girlfriend` — Angry romantic partner
- `cop` — Suspicious police officer
- `landlord` — Angry property owner

Each scenario maps to exactly one character variant. The Flutter app sets the EnumInput before the call screen loads. All 5 variants share the same state machine (emotions, visemes, hang-up) — only the visual appearance changes.

### Exit Lines Reference

From UX Design Spec §Phase 4:

**Hang-up (failure) exit lines:**
- Mugger: *slams something* "Forget it. You're not even worth robbing." *call ends*
- Waiter: *heavy sigh* "I'm done. Next customer." *call ends*
- Girlfriend: "You know what? We're done. Don't call me back." *hangs up with force*
- Cop: "We're done here." *call ends*
- Landlord: "I'm calling my solicitor." *call ends*

**Completion (success) exit lines:**
- Mugger: "...Fine. Keep your wallet. You talk too much anyway." *walks away*
- Waiter: "Huh. You actually knew what you wanted. That's a first." *brings the food*
- Girlfriend: "...Okay. Fine. But we're still talking about this later."
- Cop: TBD (to be authored in Story 3.2)
- Landlord: TBD (to be authored in Story 3.2)

### What NOT to Do

1. **Do NOT write actual scenario system prompts** (except the Waiter example) — that's Story 3.2
2. **Do NOT write code or modify any files in `client/` or `server/`** — this is documentation only
3. **Do NOT modify `difficulty-calibration.md` or `scenario-testing-process.md`** — those documents are finalized; this story creates a complementary authoring template that references them
4. **Do NOT create database migration SQL** — that's Epic 5 (Story 5.1)
5. **Do NOT build automated scenario loading** — scenarios are manually configured on VPS during Epic 3; automated loading is Epic 5+
6. **Do NOT duplicate content from the reference documents** — link to sections rather than copy-pasting tables. The template should reference `difficulty-calibration.md §4.3` for presets, not reproduce the table

### Project Structure Notes

**New files:**
```
_bmad-output/
  planning-artifacts/
    scenario-authoring-template.md        # NEW — Main deliverable
    scenarios/
      example-the-waiter.md               # NEW — Worked example
```

**No modified files.** This story creates new documentation only.

### Previous Story Intelligence (Story 3.0)

Story 3.0 (Build Scenario Calibration Testing Tools) creates the technical infrastructure this story references:
- `TranscriptLogger` — captures transcripts to `/tmp/transcript_{session_id}.json`
- `score_transcript.py` — CLI tool that scores a transcript against the AI scoring prompt
- Both tools are documented in `scenario-testing-process.md` and built in `server/`
- The authoring workflow defined in this story must reference these tools for the "test → score → validate" loop

### Git Intelligence

Recent commits are all from Epic 2 (UX Design & Assets). No code patterns to carry forward — this story is the first documentation-only story in Epic 3.

### References

- [Source: _bmad-output/planning-artifacts/difficulty-calibration.md — §3 scoring, §4 difficulty levels, §5 AI scoring prompt, §8.3 scenario config schema]
- [Source: _bmad-output/planning-artifacts/scenario-testing-process.md — §2 process overview, §3 technical tools, §4 step-by-step, §5 checklist]
- [Source: _bmad-output/planning-artifacts/architecture.md — scenarios table schema, Rive character variants, API design]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md — §Phase 3 character reactions, §Phase 4 exit lines, §Phase 2 scene setting]
- [Source: _bmad-output/planning-artifacts/prd.md — FR14 briefing text, FR19 first-scenario calibration, FR38 content warnings, FR40-42 operator tools]
- [Source: _bmad-output/planning-artifacts/epics.md — Epic 3 stories and acceptance criteria]
- [Source: _bmad-output/implementation-artifacts/3-0-build-scenario-calibration-testing-tools.md — TranscriptLogger spec, score_transcript.py spec]
- [Source: server/pipeline/prompts.py — Current PoC system prompt format example]

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
