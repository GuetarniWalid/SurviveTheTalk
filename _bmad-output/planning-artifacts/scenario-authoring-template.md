# Scenario Authoring Template

Date: 2026-04-15
Status: Active (Updated for checkpoint-based YAML format)
Epic 3 Dependency: Used by Story 3.2 (Create Launch Scenarios)

---

## 1. Overview

This document is the **operator's guide for creating scenarios**. Each scenario is a checkpoint-based conversation experience — a character, a situation, ordered progression goals, and all metadata needed by the pipeline and scoring tools.

Scenarios are authored as **YAML files** in `_bmad-output/planning-artifacts/scenarios/`. At deployment, the YAML is loaded into the SQLite database as structured JSON. The pipeline reads checkpoints from the database and swaps prompt segments dynamically during the call.

**Key concept — Checkpoint-based progression:**
- Each scenario defines a `base_prompt` (character identity, personality, boundaries — constant) and an ordered list of `checkpoints` (typically 4-6, up to 10-12 for complex scenarios)
- Each checkpoint defines: what the user must do (`success_criteria`), what the user sees (`hint_text`), and how the character behaves while waiting (`prompt_segment`)
- The pipeline sends `base_prompt + current checkpoint's prompt_segment` as the active system prompt
- When a checkpoint is met, the prompt swaps to the next checkpoint's segment
- Survival % = `floor(checkpoints_passed / total_checkpoints × 100)`

---

## 2. File Format

Scenario files use **YAML** format (`.yaml` extension). YAML is chosen because:
- Natively structured — trivially parseable by Python (`yaml.safe_load()`) and Dart (`yaml` package)
- Multiline strings handled cleanly with `|` block scalar
- Each field is explicitly named and typed — no parsing ambiguity
- Directly loadable into database (Epic 5) and pipeline (Epic 6)

**File naming:** `{character-name}.yaml` (e.g., `the-waiter.yaml`, `the-mugger.yaml`)

**File location:** `_bmad-output/planning-artifacts/scenarios/`

---

## 3. YAML File Structure

Every scenario file must contain these top-level keys in order:

```yaml
metadata:       # All scenario metadata fields (§4)
base_prompt:    # Character identity + personality + boundaries (§5)
checkpoints:    # Ordered list of checkpoint objects (§6)
exit_lines:     # Hang-up + completion lines (§7)
briefing:       # Pre-call vocabulary/context (§8)
calibration:    # Test results — filled after testing (§12)
```

---

## 4. Metadata Fields

### Required Fields

```yaml
metadata:
  id: waiter_easy_01              # Unique identifier (database primary key)
  title: "The Waiter"             # Display name shown to user
  difficulty: easy                # easy | medium | hard
  is_free: true                   # true = free tier, false = paid only
  rive_character: waiter          # mugger | waiter | girlfriend | cop | landlord
  language_focus: "ordering food, polite requests, food adjectives"  # Comma-separated target areas
  tts_voice_id: "cd6256ef-..."    # Cartesia voice ID (confirmed during calibration)
  content_warning: null           # null for non-threatening, text for threatening scenarios
```

### Difficulty Override Fields (all nullable)

Override difficulty preset defaults. **Leave as `null` unless calibration testing shows custom tuning is needed.**

Default values per difficulty level: [`difficulty-calibration.md`](difficulty-calibration.md) §4.3

```yaml
  # Nullable overrides — null = use difficulty preset
  patience_start: null            # Starting patience meter value
  fail_penalty: null              # Patience cost per failed checkpoint attempt
  silence_penalty: null           # Patience cost per silence incident
  recovery_bonus: null            # Patience recovered per successful checkpoint
  silence_prompt_seconds: null    # Seconds before character prompts ("Hello?")
  silence_hangup_seconds: null    # Seconds of silence before hang-up
  escalation_thresholds: null     # Patience values triggering escalation stages
```

### Debrief Generation

The `language_focus` metadata field feeds into the AI scoring prompt ([`difficulty-calibration.md`](difficulty-calibration.md) §5) to personalize post-call debrief feedback. The scoring system evaluates the user's performance specifically in the areas listed (e.g., "ordering food, polite requests") rather than generating generic feedback. The number of checkpoints replaces `expected_exchanges` in the survival % calculation (`floor(checkpoints_passed / total_checkpoints × 100)`).

---

## 5. Base Prompt

The `base_prompt` defines everything about the character that stays **constant across all checkpoints**. It is prepended to every checkpoint's `prompt_segment` to form the active system prompt.

**Must start with `/no_think`** to suppress Qwen reasoning tokens.

**Required content:**
1. **Character Identity** (2-3 sentences) — name, occupation, backstory, dominant trait
2. **Personality Rules** (4-6 bullets) — speech style, tone, behavior constants
3. **Difficulty Behavior Rules** — speech speed, vocabulary level, idioms, rephrasing (from [`difficulty-calibration.md`](difficulty-calibration.md) §4.2)
4. **Behavioral Boundaries** — what the character MUST NEVER do (safety rules)

**What does NOT go in `base_prompt`:**
- Scenario context (goes in first checkpoint's `prompt_segment`)
- Escalation stages (patience is managed by the pipeline, not the prompt)
- Opening line (goes in first checkpoint's `prompt_segment`)
- Exit lines (separate YAML key, injected by pipeline at the right moment)

```yaml
base_prompt: |
  /no_think
  You are Tina, a waitress at a struggling downtown restaurant called
  "The Golden Fork". You've been on your feet for 12 hours, you're
  underpaid, and every customer today has been insufferable.

  Rules you MUST follow:
  - Keep every response to 1-3 short sentences
  - Be sarcastic and impatient, but never cruel — you're tired, not evil
  - If the customer hesitates, show frustration with sighs and sarcasm
  - If they make grammar mistakes, react with mild annoyance
  - Speak English only. Never break character

  Difficulty behavior (easy):
  - Speak slowly and clearly, basic everyday vocabulary
  - Short sentences (5-8 words), no idioms or slang
  - If confused, describe the dish once — then escalate
  - Never interrupt the customer mid-sentence

  Boundaries you MUST NEVER cross:
  - No slurs, threats, or truly offensive content
  - Insult the SITUATION, not the PERSON
  - No sexual, violent, or discriminatory content
  - Never break the fourth wall or acknowledge being an AI
  - If customer is abusive: "I don't get paid enough for this." → end call
```

---

## 6. Checkpoints

The `checkpoints` key is an **ordered list** of checkpoint objects. Each checkpoint represents one phase of the scenario that the user must pass through.

### Checkpoint Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier within the scenario (e.g., `"react"`, `"refuse"`) |
| `hint_text` | string | Short phrase shown to user on the call screen stepper (e.g., `"Order your main course."`) |
| `prompt_segment` | text | System prompt fragment active during this checkpoint — defines character behavior WHILE WAITING for this checkpoint to be met |
| `success_criteria` | text | What the user must say/do to pass this checkpoint — used by the ExchangeClassifier to detect completion |

### Design Rules

- **4-6 checkpoints for launch scenarios** (up to 10-12 for complex scenarios) — enough structure without feeling rigid
- **Sequential progression** — user cannot skip checkpoints; must pass 1 before 2
- **One active at a time** — pipeline sends `base_prompt + checkpoints[current].prompt_segment`
- **Clear success criteria** — must be specific enough for an LLM classifier to evaluate, broad enough to accept natural variation
- **Each prompt_segment is self-contained** — the character doesn't know what comes next; it only knows the current phase
- **hint_text is concise** — max ~8 words, imperative form ("Order your main course", "Refuse to pay")

### Example

```yaml
checkpoints:
  - id: greet
    hint_text: "Tell the waitress you want to order."
    prompt_segment: |
      A customer just sat down. Greet them rudely and ask what
      they want. The menu has: grilled chicken, fried chicken,
      pasta, steak, fish and chips, soup of the day (tomato).
      No dessert tonight. Wait for them to speak.
    success_criteria: >
      User states they want to order, asks for the menu, or
      mentions any food item. Any coherent response to the
      greeting counts.

  - id: main_course
    hint_text: "Order your main course."
    prompt_segment: |
      They've responded. Now ask what main course they want.
      List a few options impatiently if they seem lost. If they
      name something not on the menu, tell them it's not available
      with visible annoyance.
    success_criteria: >
      User names a specific dish from the menu (chicken, pasta,
      steak, fish, soup) or describes what they want clearly
      enough to identify a menu item.
```

---

## 7. Exit Lines

Each scenario needs two exit lines. These are injected by the pipeline at the appropriate moment — not embedded in checkpoint prompts.

```yaml
exit_lines:
  hangup: "*heavy sigh* I'm done. Next customer."
  completion: "Huh. You actually knew what you wanted. That's a first."
```

**Hang-up (failure):** Theatrical, dramatic, in-character. Must feel like a sitcom moment, not a cold disconnect.

**Completion (success):** Grudging acceptance. Never congratulatory. The character is impressed DESPITE themselves.

**Reference for launch scenarios:** UX Design Spec — Phase 4: The Hang-Up section.

---

## 8. Briefing

Pre-call info shown before the user's first attempt. Helps reduce anxiety without spoiling.

```yaml
briefing:
  vocabulary: "\"I'd like...\", \"soup of the day\", \"grilled / fried\""
  context: "You're ordering food at a restaurant. The waitress is not in a good mood."
  expect: "The waitress is impatient — order clearly and don't take too long deciding."
```

**Rules:**
- Helpful without being a spoiler — never reveal checkpoint specifics or exit lines
- Never list more than 3 vocabulary items
- Written in English (the user is practicing English)

---

## 9. Content Warning

Required for scenarios involving threat, confrontation, or authority pressure.

```yaml
# Non-threatening scenario:
metadata:
  content_warning: null

# Threatening scenario:
metadata:
  content_warning: >
    This scenario simulates a threatening phone call.
    The character will be verbally intimidating and demand money.
    No physical contact occurs — it's a phone conversation.
```

**When to set content_warning:**
- Physical threat (mugger) — always
- Authority pressure (cop) — always
- Emotional confrontation (girlfriend, landlord) — if intensity is high
- Non-threatening (waiter, interviewer) — `null`

---

## 10. Rive Character Assignment

The Rive file has 5 visual variants switchable via `character` EnumInput:

| Value | Character | Used for |
|-------|-----------|----------|
| `mugger` | Street criminal | Robbery, threat |
| `waiter` | Restaurant server | Food ordering, service |
| `girlfriend` | Angry partner | Relationship conflict |
| `cop` | Police officer | Authority, questioning |
| `landlord` | Property owner | Housing dispute |

Each scenario maps to exactly **one** variant. Future scenarios can reuse variants.

---

## 11. Authoring Workflow

### Step 1 — Write the scenario YAML

Create `_bmad-output/planning-artifacts/scenarios/{character-name}.yaml`. Fill in all metadata, write `base_prompt`, design checkpoints with `hint_text`, `prompt_segment`, and `success_criteria`. Write exit lines. **Do not write briefing yet** — that comes after calibration (Step 7).

### Step 2 — Configure on VPS

SSH to VPS and load the scenario for testing. During Epic 3 (no CheckpointManager yet), combine `base_prompt` + all checkpoint `prompt_segment`s into a single monolithic prompt in `prompts.py`:

```bash
ssh root@167.235.63.129
# Edit server/pipeline/prompts.py with combined prompt
systemctl restart pipecat.service
```

**Note:** Checkpoint progression is NOT enforced during Epic 3 calibration testing — the VPS pipeline uses a single combined prompt. Checkpoint mechanics are implemented in Epic 6. Epic 3 tests validate the content and calibrate difficulty.

### Step 3 — Test the scenario (2 passes minimum)

Play the scenario using the Flutter app. Two required passes per [`scenario-testing-process.md`](scenario-testing-process.md) §4:

| Pass | Play as... | Purpose |
|------|-----------|---------|
| **A: "Good B1"** | User who tries hard, some errors | Verify survival % hits upper end of target |
| **B: "Struggling B1"** | User who struggles, longer pauses | Verify survival % hits lower end, hang-up triggers |

### Step 4 — Score the transcripts

```bash
scp root@167.235.63.129:/tmp/transcript_*.json ./calibration-data/
cd server
python scripts/score_transcript.py \
  --transcript ../calibration-data/transcript_{id}.json \
  --scenario-name "The Waiter" \
  --difficulty easy \
  --expected-exchanges 6 \
  --language-focus "ordering food,polite requests,food adjectives"
```

**Note:** During Epic 3, `--expected-exchanges` equals the number of checkpoints.

### Step 5 — Validate calibration

Check survival targets in [`difficulty-calibration.md`](difficulty-calibration.md) §4.3. Fill out the calibration checklist from [`scenario-testing-process.md`](scenario-testing-process.md) §5.

### Step 6 — Adjust if needed

| Problem | Adjustment |
|---------|-----------|
| Too easy (survival > target + 10%) | Reduce silence tolerance, tighten success_criteria |
| Too hard (survival < target - 10%) | Increase patience_start, broaden success_criteria |
| Character breaks personality | Rewrite base_prompt personality rules |
| Checkpoint too hard to pass | Broaden success_criteria, simplify hint_text |

After adjusting, return to Step 2 and retest.

### Step 7 — Write briefing

Now that calibration confirms the conversation flow, write `briefing` based on what actually happened in test transcripts.

### Step 8 — Record results

Update the YAML file's `calibration` section with pass results and verdicts.

### Step 9 — Push to production

Scenario is production-ready when both passes produce PASS verdict.

---

## 12. Calibration Results

Filled after testing. Part of the YAML file:

```yaml
calibration:
  pass_a:
    date: "2026-04-15"
    transcript_file: "calibration-tests/waiter_easy_2026-04-15T14-30.json"
    survival_pct: 83
    verdict: PASS    # PASS | ADJUST | REWORK
  pass_b:
    date: "2026-04-15"
    transcript_file: "calibration-tests/waiter_easy_2026-04-15T15-00.json"
    survival_pct: 66
    verdict: PASS
```

### 12.1. Optional `pipeline_validation` sub-block

During Epic 3 (before CheckpointManager ships in Epic 6), survival % cannot be measured against checkpoint progression. To document pre-checkpoint pipeline and feel validation without polluting the `pass_a` / `pass_b` slots, an optional `pipeline_validation` sub-block may be added under `calibration`:

```yaml
calibration:
  pipeline_validation:
    date: 2026-04-15
    calls: 2
    transcript_files:
      - transcript_call_1776260510.json
      - transcript_call_1776261974.json
    findings:
      - "Prompt v1 too aggressive — character escalated without provocation. Fixed: tired-by-default..."
      - "Turn-taking cascade — VAD stop_secs 0.3→0.8 fixed interruption loops."
    verdict: pipeline-validated  # pipeline-validated | pipeline-blocked
  pass_a:
    ...
  pass_b:
    ...
```

**When to use:** Only when full survival-% calibration is deferred (e.g., scenarios shipped before Epic 6). Once the CheckpointManager is available, `pass_a` / `pass_b` become the primary source of calibration truth; `pipeline_validation` remains as historical context.

**Fields:**
- `date` — ISO date of the validation session
- `calls` — number of end-to-end calls executed
- `transcript_files` — list of transcript JSON filenames captured during validation
- `findings` — bulleted observations (prompt issues, VAD tuning, feel notes, applied fixes)
- `verdict` — `pipeline-validated` (pipeline works end-to-end, feel acceptable) or `pipeline-blocked` (issue not yet resolved)

---

## 13. Checklist Quick Reference

Before marking a scenario as production-ready:

- [ ] YAML file has all metadata fields (§4)
- [ ] `base_prompt` has character identity, personality rules, difficulty behavior, boundaries (§5)
- [ ] `base_prompt` starts with `/no_think`
- [ ] Checkpoints defined (4-6 for launch scenarios) with id, hint_text, prompt_segment, success_criteria (§6)
- [ ] Checkpoint count matches expected progression (not too many, not too few)
- [ ] hint_text is concise and actionable (max ~8 words each)
- [ ] success_criteria is specific enough for LLM classification
- [ ] Exit lines written — hang-up (theatrical) and completion (grudging) (§7)
- [ ] Briefing written after calibration (§8)
- [ ] Content warning set or explicitly null (§9)
- [ ] Rive character assigned (§10)
- [ ] Pass A tested — survival % in target range
- [ ] Pass B tested — survival % in target range, hang-up triggers correctly
- [ ] Character stays in personality throughout both passes
- [ ] Escalation feels theatrical, not hostile

---

## 14. Complete Example

See [`scenarios/the-waiter.yaml`](scenarios/the-waiter.yaml) for a fully worked example using "The Waiter" (easy difficulty).
