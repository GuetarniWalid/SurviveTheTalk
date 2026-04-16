# Story 3.2: Create Launch Scenarios

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a user,
I want 5 diverse scenarios available at launch covering different real-world situations,
so that I have enough content to experience the product and make a subscription decision.

## Dependencies

- **Story 3.1 (review)** — Scenario authoring template must be approved before starting. Template at `_bmad-output/planning-artifacts/scenario-authoring-template.md` and reference example at `_bmad-output/planning-artifacts/scenarios/the-waiter.yaml` define the exact structure to follow.
- **Story 3.0 (done)** — Calibration tools (`TranscriptLogger`, `score_transcript.py`) are built and ready for testing.

## Acceptance Criteria

> **Scope decision (2026-04-15):** Full checkpoint-based calibration requires the CheckpointManager shipping in Epic 6. Story 3.2 was rescoped to deliver all 5 scenario YAMLs plus a pipeline + feel validation on The Waiter. The original calibration-style ACs were rewritten below to reflect what can be honestly validated in Epic 3. Remaining calibration work is tracked as a post-Epic 6 follow-up.

1. **5 scenario YAML files exist** in `_bmad-output/planning-artifacts/scenarios/` — each conforming to `scenario-authoring-template.md` checkpoint-based structure with complete metadata, base_prompt, ordered checkpoints (id, hint_text, prompt_segment, success_criteria), briefing, exit lines, and calibration scaffold (pass_a/pass_b blocks present, values may be null for deferred scenarios).

2. **Waiter pipeline and character feel validated on live VPS** — Monolithic Tina prompt deployed via `server/pipeline/prompts.py`, 2 end-to-end calls executed on the live Pipecat pipeline (STT → LLM → TTS), character stays in role, professional-by-default with sarcasm only when provoked. Validation findings, transcript references, and applied fixes recorded in `the-waiter.yaml` `calibration.pipeline_validation` block. Full survival-%-based calibration (Pass A / Pass B with verdicts) is deferred to post-Epic 6 when CheckpointManager is available.

3. **Difficulty progression maintained** — Easy → Medium → Medium → Hard → Hard ordering across the 5 scenarios, with per-pass survival targets recorded as comments on `pass_a.survival_pct` / `pass_b.survival_pct` fields, matching `difficulty-calibration.md` §4.3 presets.

4. **Content warnings defined** — Scenarios involving physical threat (Mugger), authority pressure (Cop), or emotional confrontation (Girlfriend, Landlord) have `content_warning` text. Non-threatening scenarios (Waiter) have `content_warning: null`.

5. **Character-specific exit lines written** — Both hang-up (failure) and completion (success) exit lines per character, matching UX specification tone. The boundary-violation hang-up phrasing inside `base_prompt` matches `exit_lines.hangup` exactly so the runtime LLM output and the YAML metadata agree.

6. **Pass A / Pass B calibration scaffold ready** — Each scenario's YAML contains populated `pass_a` and `pass_b` blocks with target survival % ranges recorded as comments (matching `difficulty-calibration.md` §4.3). Actual calibration (transcript capture + scoring + verdict) is deferred to post-Epic 6 when the CheckpointManager can track checkpoint progression and compute meaningful survival %.

7. **All scenarios VPS-loadable via prompts.py; Waiter validated end-to-end** — The Waiter scenario is loaded as a monolithic prompt in `server/pipeline/prompts.py` and tested end-to-end on the live Pipecat pipeline. The remaining 4 scenarios (Mugger, Girlfriend, Cop, Landlord) have complete YAML structure and can be swapped into `prompts.py` for future calibration; their `tts_voice_id` is intentionally `null` and will be selected during post-Epic 6 calibration alongside survival-% verification.

## The 5 Launch Scenarios

| # | Character | Difficulty | Free? | Rive Character | Content Warning | Survival Target |
|---|-----------|-----------|-------|----------------|-----------------|-----------------|
| 1 | The Waiter | easy | Yes | `waiter` | null | 60-80% |
| 2 | The Mugger | medium | Yes | `mugger` | Required (physical threat) | 35-55% |
| 3 | The Girlfriend | medium | Yes | `girlfriend` | Required (emotional intensity) | 35-55% |
| 4 | The Cop | hard | No | `cop` | Required (authority pressure) | 15-35% |
| 5 | The Landlord | hard | No | `landlord` | Required (confrontation) | 15-35% |

**Rationale:** These 5 characters match the 5 Rive character variants defined in architecture. They cover distinct real-world situations from low-stakes (restaurant) to high-stakes (robbery, police). The free tier gives users easy + medium exposure; paid unlocks hard scenarios.

## Tasks / Subtasks

### Phase 1: Write Scenario Files (4 new + finalize Waiter) — COMPLETE

- [x] Task 1: Convert The Waiter to YAML checkpoint format (AC: #1, #2)
  - [x] Create `scenarios/the-waiter.yaml` from `example-the-waiter.md`
  - [x] Write base_prompt (character identity, personality, difficulty behavior, boundaries)
  - [x] Design 6 checkpoints (greet, main_course, clarify, drink, confirm, close)
  - [x] Delete old `example-the-waiter.md` after conversion

- [x] Task 2: Convert The Mugger to YAML checkpoint format — medium difficulty (AC: #1, #3, #4, #5)
  - [x] Finalize `scenarios/the-mugger.yaml` (5 checkpoints: react, refuse, challenge, deflect, stand_firm)
  - [x] Write content warning: threatening phone call
  - [x] Write briefing (vocabulary, context, expect)
  - [x] Write exit lines — hang-up + completion
  - [x] Delete old `the-mugger.md` after finalization

- [x] Task 3: Write The Girlfriend YAML — medium difficulty (AC: #1, #3, #4, #5)
  - [x] Create `scenarios/the-girlfriend.yaml` with checkpoint format
  - [x] Write base_prompt + 6 checkpoints (react, explain, acknowledge, reassure, make_right, commit)
  - [x] Write content warning: emotional confrontation
  - [x] Write briefing + exit lines — hang-up: "You know what? We're done. Don't call me back." / completion: "...Okay. Fine. But we're still talking about this later."
  - [x] Delete old `the-girlfriend.md` after conversion

- [x] Task 4: Write The Cop YAML — hard difficulty (AC: #1, #3, #4, #5)
  - [x] Create `scenarios/the-cop.yaml` with checkpoint format
  - [x] Write base_prompt + 5 checkpoints (respond, explain_driving, justify, curveball, closing)
  - [x] Write content warning: authority pressure scenario
  - [x] Write briefing + exit lines — hang-up: "We're done here." / completion: "...Alright. I'll let you off with a warning this time. Drive safe."
  - [x] Delete old `the-cop.md` after conversion

- [x] Task 5: Write The Landlord YAML — hard difficulty (AC: #1, #3, #4, #5)
  - [x] Create `scenarios/the-landlord.yaml` with checkpoint format
  - [x] Write base_prompt + 6 checkpoints (acknowledge, explain_late, damage, negotiate, credibility, commit)
  - [x] Write content warning: housing confrontation
  - [x] Write briefing + exit lines — hang-up: "I'm calling my solicitor." / completion: "...Fine. You have until Friday. If I don't see that payment, don't bother unpacking."
  - [x] Delete old `the-landlord.md` after conversion

### Phase 2: Pipeline & Feel Validation (partial — full calibration deferred)

> **Decision (2026-04-15):** Full calibration (2 passes × 5 scenarios with survival % targets) requires the CheckpointManager (Epic 6) to track checkpoint progression and compute meaningful survival %. Without it, the LLM improvises the conversation flow and survival % is just a raw utterance count. Pipeline and character feel were validated with The Waiter. Fine-tuning all 5 scenarios will happen after Epic 6 when the checkpoint system is in place.

- [x] Task 6: Validate The Waiter pipeline & feel (AC: #2 partial, #7 partial)
  - [x] Deploy scenario on VPS: updated `prompts.py` + `bot.py`, restart service
  - [x] Call 1: Identified prompt too aggressive + VAD interruption cascade
  - [x] Fix: Rewrote prompt (tired-not-angry default), tuned VAD (stop_secs 0.8, speech_timeout 1.8)
  - [x] Call 2: Character feel validated — professional by default, sarcastic only when provoked
  - [x] Ran `score_transcript.py` — debrief scoring functional (5 errors, 3 hesitations, 3 idioms detected)
  - [x] Fixed TranscriptLogger bug (missing `super().process_frame()` call blocked entire pipeline)
  - [x] Record results in `scenarios/the-waiter.yaml` calibration section

- [ ] Task 7-10: Calibrate remaining 4 scenarios — **DEFERRED to post-Epic 6**
  - Rationale: Without CheckpointManager, no meaningful checkpoint-based survival % measurement
  - All scenario YAML files are complete and ready for calibration when system is built

### Phase 3: Production Readiness (partial)

- [x] Task 11: Verify scenario files and pipeline readiness (AC: #1, #3, #4, #5, #7 partial)
  - [x] All 5 scenario YAML files exist and conform to template structure
  - [x] All scenarios have metadata, base_prompt, checkpoints, exit_lines, briefing
  - [x] Content warnings defined for threatening scenarios (mugger, girlfriend, cop, landlord)
  - [x] Waiter scenario loadable and tested end-to-end on VPS
  - [ ] Full calibration results with PASS verdicts — deferred to post-Epic 6

## Dev Notes

### Story Nature: Content Creation + Live Testing

This story is **primarily content authoring**, not code. The deliverables are 5 YAML scenario files. The "development" is:
1. Writing scenario content (base_prompt, checkpoints, metadata, briefing)
2. Testing on live VPS pipeline (requires SSH access + human playing B1 learner)
3. Scoring with existing tools (no new code)

**No Flutter code changes. No new Python code.** Only scenario YAML files are created.

### File Format: YAML (Checkpoint-Based)

Scenarios use **YAML format** (`.yaml` extension). See `scenario-authoring-template.md` for full spec.

**Why YAML:** Natively structured, parseable by Python (`yaml.safe_load()`) and Dart (`yaml` package), directly loadable into database (Epic 5) and pipeline (Epic 6). No custom parsing needed.

**Reference example:** `_bmad-output/planning-artifacts/scenarios/the-waiter.yaml`

**Required YAML top-level keys (in order):**
1. `metadata` — id, title, difficulty, is_free, rive_character, language_focus, tts_voice_id, content_warning, nullable overrides
2. `base_prompt` — character identity, personality rules, difficulty behavior, behavioral boundaries (starts with `/no_think`)
3. `checkpoints` — ordered list of 4-6 checkpoint objects (id, hint_text, prompt_segment, success_criteria)
4. `exit_lines` — hangup + completion
5. `briefing` — vocabulary, context, expect
6. `calibration` — pass_a + pass_b results (filled after testing)

### Base Prompt Content

The `base_prompt` contains everything CONSTANT across all checkpoints:

1. **Character Identity** (2-3 sentences) — who, background, dominant trait
2. **Personality Rules** (4-6 bullets) — speech/behavior constants across difficulty
3. **Difficulty Behavior Rules** — speech speed, vocabulary, idioms, rephrasing (from difficulty presets)
4. **Behavioral Boundaries** — what character MUST NEVER do (safety)

**What does NOT go in base_prompt:** scenario context (→ first checkpoint), opening line (→ first checkpoint), escalation stages (→ pipeline), exit lines (→ separate YAML key)

### Checkpoint Design

Each checkpoint has 4 fields:
- **id** — unique name (e.g., `"greet"`, `"refuse"`, `"stand_firm"`)
- **hint_text** — short imperative phrase shown on stepper UI (~8 words max)
- **prompt_segment** — character behavior instructions for this phase (appended to base_prompt)
- **success_criteria** — what the user must do to pass (used by ExchangeClassifier in Epic 6)

**Key rules:**
- 4-6 checkpoints per scenario — enough structure without rigidity
- Sequential — user must pass checkpoint N before N+1
- Pipeline sends `base_prompt + checkpoints[current].prompt_segment` as active prompt
- `success_criteria` must be broad enough for natural language variation
- Survival % = `floor(checkpoints_passed / total_checkpoints × 100)`

### Difficulty Behavior Presets

From `difficulty-calibration.md` §4.2 — these define HOW the character behaves:

**Easy:**
- Speak slowly and clearly, basic vocabulary
- Short sentences (5-8 words), no idioms/slang
- Describe once if confused, never interrupt
- 4 escalation stages: [75, 50, 25, 0]

**Medium:**
- Natural pace, everyday vocabulary + occasional idioms
- Medium sentences (8-12 words), some phrasal verbs
- No rephrasing on confusion, may interrupt once
- 3 escalation stages: [60, 30, 0]

**Hard:**
- Fast pace, advanced vocabulary, frequent idioms/slang
- Complex sentences (12+ words), cultural references
- Never simplifies, interrupts freely, talks over user
- 2 escalation stages: [30, 0]

### Patience Presets (from difficulty-calibration.md §4.3)

| Parameter | Easy | Medium | Hard |
|-----------|------|--------|------|
| patience_start | 100 | 80 | 60 |
| fail_penalty | -15 | -20 | -25 |
| silence_penalty | -10 | -15 | -20 |
| recovery_bonus | +5 | +3 | +0 |
| silence_prompt_seconds | 6 | 4 | 3 |
| silence_hangup_seconds | 10 | 7 | 5 |

### Exit Lines (from UX Design Specification)

**Hang-up (failure) — already defined:**
- Mugger: "Forget it. You're not even worth robbing."
- Waiter: *heavy sigh* "I'm done. Next customer."
- Girlfriend: "You know what? We're done. Don't call me back."
- Cop: "We're done here."
- Landlord: "I'm calling my solicitor."

**Completion (success) — partially defined:**
- Mugger: "...Fine. Keep your wallet. You talk too much anyway."
- Waiter: "Huh. You actually knew what you wanted. That's a first."
- Girlfriend: "...Okay. Fine. But we're still talking about this later."
- Cop: "...Alright. I'll let you off with a warning this time. Drive safe."
- Landlord: "...Fine. You have until Friday. If I don't see that payment, don't bother unpacking."

### Content Warning Guidelines (from UX spec, FR38)

| Character | Warning Needed | Reason |
|-----------|---------------|--------|
| Waiter | No (`null`) | Non-threatening restaurant scenario |
| Mugger | Yes | Physical threat — robbery situation |
| Girlfriend | Yes | High emotional intensity — relationship conflict |
| Cop | Yes | Authority pressure — police questioning |
| Landlord | Yes | Confrontation — housing dispute, legal threats |

**Format:** 1-2 sentences describing intensity. Example: "This scenario involves a robbery situation with verbal threats. The character may be intimidating but will never describe violence."

### Briefing Text Format (FR14)

Three parts shown before first attempt:
1. **Key vocabulary** — 2-3 words/phrases the user might need
2. **Context** — 1 sentence describing the situation
3. **Expect** — 1 sentence describing character behavior

Keep it helpful without spoiling the scenario surprise. See Waiter example for reference.

### Checkpoint Replaces Narrative Arc

The old "narrative arc table" is now replaced by the `checkpoints` list. Each checkpoint IS a narrative beat. The checkpoint count is scenario-defined, NOT difficulty-defined. Difficulty changes HOW the character behaves within each checkpoint, not HOW MANY checkpoints exist.

### Calibration Testing Process

Reference: `_bmad-output/planning-artifacts/scenario-testing-process.md`

**Per-scenario process:**
1. Configure scenario on VPS — edit `server/pipeline/prompts.py`, `systemctl restart pipecat.service`
2. Play scenario as B1 learner (human tester required)
3. TranscriptLogger captures transcript to `/tmp/transcript_{session_id}.json`
4. Score with CLI:
   ```bash
   python scripts/score_transcript.py \
     --transcript /tmp/transcript_{session_id}.json \
     --scenario-name "{name}" \
     --difficulty {level} \
     --expected-exchanges {N} \
     --language-focus "{focus areas}"
   ```
5. Validate: survival % within target range (±10%), check subjective feel
6. If out of range: adjust nullable difficulty overrides, retest
7. Record results in scenario file's Calibration Results section

**Two required passes per scenario:**
- **Pass A (Good B1):** Tries hard, some grammar errors, stays on topic
- **Pass B (Struggling B1):** Struggles more, longer pauses, occasional off-topic

**Subjective checklist (per pass):**
- [ ] Character stays in personality throughout
- [ ] Escalation is theatrical, not hostile or disturbing
- [ ] Hang-up moment feels narratively satisfying
- [ ] Real B1 user would find it motivating
- [ ] Conversation rhythm feels natural
- [ ] Character replies are credible and varied

### Scenario Design Guidelines

**Character voice consistency:**
- Each character has a distinct personality and speech register
- Personality rules are CONSTANT across difficulty — only speech complexity changes
- Characters must feel like real people, not generic AI

**Language focus selection:**
- Choose 2-3 specific, actionable vocabulary/grammar areas per scenario
- Must match what a B1 learner would actually practice in that situation
- Examples: "ordering food, polite requests" (waiter), "describing events, past tense" (cop)

**Rive character assignment:**
- Valid values: `mugger`, `waiter`, `girlfriend`, `cop`, `landlord`
- Must match the scenario character (1:1 mapping for launch scenarios)

**TTS voice selection:**
- Each character needs a distinct Cartesia voice ID (`tts_voice_id`)
- The Waiter currently uses: `62ae83ad-4f6a-430b-af41-a9bede9286ca` (Cartesia "Gemma — Decisive Agent", British female) — matches `server/pipeline/prompts.py` runtime voice
- Select voices that match character personality (age, tone, energy)
- Voice IDs for the other 4 scenarios are deferred to post-Epic 6 calibration (`tts_voice_id: null`)

### VPS Deployment

- SSH to VPS: `ssh root@167.235.63.129`
- Edit prompts: `nano /root/surviveTheTalk2/server/pipeline/prompts.py`
- Restart service: `systemctl restart pipecat.service`
- Firewall: only ports 22, 80, 443 exposed — use port 80 (Caddy reverse proxy)

### What NOT To Do

- **Content-first, server tweaks only when pipeline validation requires them** — The primary deliverable is 5 scenario YAML files. Server Python code (`server/pipeline/*.py`) may only be touched when live pipeline validation (AC #2) exposes a blocker. Any server change must be recorded in the Completion Notes with a one-line justification. Specifically allowed in this story:
  - Updating `server/pipeline/prompts.py` with the Waiter monolithic prompt + voice ID (required for VPS deployment)
  - Tuning VAD parameters in `server/pipeline/bot.py` (required to stop interruption cascades observed during calibration)
  - Fixing pipeline-blocking bugs in `server/pipeline/transcript_logger.py` (e.g., missing `super().process_frame()` call)
  - Updating `server/tests/*.py` to match prompt/voice changes
- **Do NOT modify Flutter code** — No client changes.
- **Do NOT use Markdown for scenarios** — Scenarios use YAML format (`.yaml`). Markdown is for documentation only.
- **Do NOT create a database** — Scenarios are YAML files. Database comes in Epic 5.
- **Do NOT skip calibration** — Every scenario needs 2 test passes with recorded results.
- **Do NOT copy-paste the Waiter base_prompt** — Each character must have a unique personality and speech style. Only the STRUCTURE is shared.
- **Do NOT put scenario context in base_prompt** — Scenario context goes in the first checkpoint's prompt_segment. base_prompt is character identity only.
- **Do NOT use offensive content** — Characters are theatrical and sarcastic, never truly hostile. Follow behavioral boundaries strictly.
- **Do NOT exceed 3 sentences per character turn** — Keep responses short (1-3 sentences) for natural phone conversation feel.
- **Do NOT forget `/no_think`** — Every base_prompt must start with this token to suppress Qwen reasoning.

### Previous Story Intelligence

**From Story 3.0 (done):**
- TranscriptLogger captures `TranscriptionFrame` (user, after STT) and `TextFrame` (character, after LLM)
- Only finalized transcriptions recorded (`TranscriptionFrame.finalized = True`)
- score_transcript.py reads `OPENROUTER_API_KEY` from env or `.env` file
- Scoring uses exact AI prompt from `difficulty-calibration.md` §5.3 — do not modify
- Calibration reports saved to `_bmad-output/implementation-artifacts/calibration-tests/`
- 54 total tests passing (10 existing + 44 new)

**From Story 3.1 (review):**
- scenario-authoring-template.md defines the complete authoring workflow
- example-the-waiter.md demonstrates every section of the template
- 13-point production checklist in template §11
- Documentation only — no code changes in Story 3.1

**From Git history:**
- Recent commits: calibration tools (Story 3.0), Epic 3 planning artifacts
- No changes to Flutter client since Epic 2
- Python server: `bot.py` has TranscriptLogger integration, `pyproject.toml` has `httpx` dependency

### Project Structure Notes

**Scenario files location:**
```
_bmad-output/planning-artifacts/scenarios/
├── the-waiter.yaml          ← Convert from example-the-waiter.md
├── the-mugger.yaml          ← Convert from the-mugger.md
├── the-girlfriend.yaml      ← To create
├── the-cop.yaml             ← To create
└── the-landlord.yaml        ← To create
```

**Calibration output location:**
```
_bmad-output/implementation-artifacts/calibration-tests/
└── {scenario_name}_{difficulty}_{timestamp}.json
```

### References

- [Source: _bmad-output/planning-artifacts/scenario-authoring-template.md] — Complete template
- [Source: _bmad-output/planning-artifacts/scenarios/the-waiter.yaml] — Reference scenario
- [Source: _bmad-output/planning-artifacts/difficulty-calibration.md §4.2-4.3] — Difficulty presets
- [Source: _bmad-output/planning-artifacts/scenario-testing-process.md §4-6] — Testing workflow
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md] — Exit lines, content warnings, briefing format
- [Source: _bmad-output/planning-artifacts/prd.md] — User journeys (Karim→waiter, Sofia→mugger, Tomasz→cop)
- [Source: _bmad-output/planning-artifacts/epics.md] — Epic 3 acceptance criteria
- [Source: _bmad-output/implementation-artifacts/3-0-build-scenario-calibration-testing-tools.md] — Tool specs
- [Source: _bmad-output/implementation-artifacts/3-1-define-scenario-structure-and-authoring-format.md] — Template specs

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (claude-opus-4-6)

### Debug Log References

- TranscriptLogger blocking pipeline: missing `super().process_frame()` in Pipecat 0.0.108 — fixed in `server/pipeline/transcript_logger.py`
- VPS transcript path: systemd private tmp (`/tmp/systemd-private-*/tmp/transcript_call_*.json`)
- score_transcript.py .env path: `/opt/survive-the-talk/repo/server/.env` (not parent dir)

### Completion Notes List

- Phase 1 complete: 5 YAML scenario files with checkpoint-based structure
- Pipeline validated: STT→LLM→TTS functional, TranscriptLogger fixed, score_transcript.py works on VPS
- Waiter feel validated: prompt rewritten (tired-not-angry), VAD tuned (stop_secs 0.8, speech_timeout 1.8)
- Full calibration (AC #2, #6) deferred to post-Epic 6 — needs CheckpointManager for meaningful survival %
- Key fixes applied to server code: transcript_logger.py (super() call), bot.py (VAD params, opening line), prompts.py (Tina prompt + voice)

### File List

- `_bmad-output/planning-artifacts/scenarios/the-waiter.yaml` — easy, 6 checkpoints, calibration: pipeline-validated
- `_bmad-output/planning-artifacts/scenarios/the-mugger.yaml` — medium, 5 checkpoints, calibration: pending
- `_bmad-output/planning-artifacts/scenarios/the-girlfriend.yaml` — medium, 6 checkpoints, calibration: pending
- `_bmad-output/planning-artifacts/scenarios/the-cop.yaml` — hard, 5 checkpoints, calibration: pending
- `_bmad-output/planning-artifacts/scenarios/the-landlord.yaml` — hard, 6 checkpoints, calibration: pending
- `server/pipeline/transcript_logger.py` — fixed: added super().process_frame() call
- `server/pipeline/bot.py` — updated: VAD params, opening line, speech timeout
- `server/pipeline/prompts.py` — updated: Tina prompt (tired-not-angry), Gemma voice ID
