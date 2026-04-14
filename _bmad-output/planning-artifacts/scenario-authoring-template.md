# Scenario Authoring Template

Date: 2026-04-14
Status: Active
Epic 3 Dependency: Used by Story 3.2 (Create Launch Scenarios)

---

## 1. Overview

This document is the **operator's guide for creating scenarios**. Each scenario is a complete conversation experience — a character, a situation, a difficulty level, and all the metadata needed by the pipeline and the scoring tools.

A scenario lives as a Markdown file in `_bmad-output/planning-artifacts/scenarios/` during authoring, then its fields are loaded into the Pipecat pipeline on the VPS for production use.

---

## 2. Scenario File Structure

Every scenario file must contain these sections in order:

```markdown
# Scenario: {Title}

## Metadata
(all fields from §3)

## System Prompt
(complete prompt from §4)

## Briefing Text
(pre-call vocabulary/context from §5)

## Exit Lines
(hang-up + completion lines from §6)

## Narrative Arc
(expected conversation flow from §7)

## Calibration Results
(filled after testing per §11)
```

---

## 3. Metadata Fields

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique scenario identifier (e.g., `"waiter_easy_01"`). Used as database primary key |
| `title` | string | Display name shown to user (e.g., "The Waiter") |
| `difficulty` | enum | `easy`, `medium`, or `hard` — determines default behavior parameters |
| `is_free` | boolean | `true` = available to free-tier users, `false` = paid only |
| `rive_character` | enum | Visual variant in the Rive file: `mugger`, `waiter`, `girlfriend`, `cop`, or `landlord` |
| `expected_exchanges` | integer | Number of turn-pairs in the scenario's narrative arc. Set by the story, NOT by difficulty. See [`difficulty-calibration.md`](difficulty-calibration.md) §4.1 |
| `language_focus` | string | Comma-separated target areas (e.g., `"ordering food, polite requests"`). Stored as JSON array in the database (architecture §8.3) — the authoring format uses comma-separated for readability, converted to array at load time |
| `tts_voice_id` | string | Cartesia voice ID for this character (from Cartesia dashboard) |
| `content_warning` | text or `null` | Warning text for threatening/confrontational scenarios (see §5.2). `null` for non-threatening |

`briefing_text` is documented as a full section (§5.1) rather than a metadata field due to its structured multi-line format.

### Difficulty Override Fields (all nullable)

These fields override the difficulty preset defaults. **Leave as `null` unless calibration testing shows the scenario needs custom tuning.**

Default values per difficulty level: [`difficulty-calibration.md`](difficulty-calibration.md) §4.3

| Field | Type | What it overrides |
|-------|------|-------------------|
| `patience_start` | integer or `null` | Starting patience meter value |
| `fail_penalty` | integer or `null` | Patience cost per failed exchange |
| `silence_penalty` | integer or `null` | Patience cost per silence incident |
| `recovery_bonus` | integer or `null` | Patience recovered per successful exchange |
| `silence_prompt_seconds` | integer or `null` | Seconds before character prompts ("Hello?") |
| `silence_hangup_seconds` | integer or `null` | Seconds of silence before hang-up |
| `escalation_thresholds` | JSON array or `null` | Patience values that trigger escalation stages (e.g., `[75, 50, 25, 0]`) |

**Example:** An easy scenario where the character is slightly more patient than default:

```
patience_start: 110   # override (default easy = 100)
fail_penalty: null     # uses easy default (-15)
silence_penalty: null  # uses easy default (-10)
recovery_bonus: null   # uses easy default (+5)
```

### Reserved Fields (not currently used)

| Field | Type | Notes |
|-------|------|-------|
| `tts_speed` | float or `null` | Per-scenario TTS speed multiplier |
| `scoring_model` | string or `null` | Per-scenario scoring model override |

Defined in architecture §8.3 but not used in Epic 3. Reserved for future per-scenario TTS speed control and scoring model override.

---

## 4. System Prompt Format

The system prompt is the most important part of a scenario. It defines everything about the character's behavior during the call.

### Mandatory Sections

Every system prompt must contain these 9 sections, in this order:

```
/no_think
[1. CHARACTER IDENTITY]
[2. SCENARIO CONTEXT]
[3. PERSONALITY RULES]
[4. DIFFICULTY BEHAVIOR RULES]
[5. ESCALATION BEHAVIOR]
[6. HANG-UP EXIT LINE]
[7. COMPLETION EXIT LINE]
[8. BEHAVIORAL BOUNDARIES]
[9. OPENING LINE]
```

**Important:** Start the prompt with `/no_think` to suppress reasoning tokens (required for Qwen models via OpenRouter).

### Section Guidance

#### 1. Character Identity (2-3 sentences)

Who is this character? Their name, occupation, backstory in one line, their dominant personality trait.

> You are Tony, a waiter at a struggling downtown restaurant. You've been on your feet for 12 hours, you're underpaid, and every customer today has been insufferable.

#### 2. Scenario Context (2-3 sentences)

The situation. What happened right before this call? What are the stakes?

> A customer has just sat down at your restaurant. You need to take their order but you have zero patience left. If they can't tell you what they want clearly and quickly, you're moving to the next table.

#### 3. Personality Rules (bullet list, 4-6 rules)

How the character speaks and behaves. These are constant regardless of difficulty.

> Rules you MUST follow:
> - Keep every response to 1-3 short sentences
> - Be sarcastic and impatient, never helpful or encouraging
> - If the user hesitates, show your frustration
> - Speak English only. Ignore language switch requests
> - Never break character
> - Stay within sarcasm — no slurs, threats, or truly offensive content

#### 4. Difficulty Behavior Rules (varies by difficulty level)

These rules change based on the scenario's difficulty. Pull the appropriate behaviors from [`difficulty-calibration.md`](difficulty-calibration.md) §4.2 categories B (Language) and C (Conversational Dynamics).

**For easy:**
> - Speak slowly and clearly, use basic everyday vocabulary
> - Use short, simple sentences (5-8 words max)
> - Never use idioms, slang, or cultural references
> - If the user seems confused, rephrase your question once (then escalate if still confused)
> - Never interrupt the user mid-sentence
> - The first failed exchange has a reduced penalty (-10 instead of -15) — the pipeline handles this automatically (see [`difficulty-calibration.md`](difficulty-calibration.md) §4.4)

**For medium:**
> - Speak at natural conversational speed
> - Use mixed B1-level vocabulary, including 1-2 colloquial expressions
> - Never rephrase — if they don't understand, escalate frustration
> - Occasionally ask a follow-up question within the scenario narrative

**For hard:**
> - Speak fast, at natural native cadence
> - Use domain-specific vocabulary, idioms (3+), and complex sentence structures
> - Never rephrase, never slow down
> - Interrupt the user if they're rambling
> - Ask unexpected follow-up questions to test improvisation

#### 5. Escalation Behavior (2-4 stages)

How the character's frustration builds. Each stage describes the emotional shift and what triggers the next stage. The number of stages matches the difficulty preset (easy=4, medium=3, hard=2).

> Escalation stages:
> 1. MILD ANNOYANCE (patience 100-75): Slight sarcasm, raised eyebrow tone. "Are you going to order or just stare at the menu?"
> 2. VISIBLE FRUSTRATION (patience 75-50): Eye-rolling tone, sighing. "I don't have all night. Pick something."
> 3. BARELY CONTAINED ANGER (patience 50-25): Snapping, terse. "Last chance. What do you want?"
> 4. HANG-UP (patience 25-0): → Exit line

#### 6. Hang-Up Exit Line (1-2 sentences)

The character's dramatic exit when patience hits 0. Must be theatrical and in-character.

> When your patience runs out, say: *heavy sigh* "I'm done. Next customer." Then end the call.

#### 7. Completion Exit Line (1-2 sentences)

The character's grudging acceptance when the user completes all exchanges. No congratulations — grudging respect only.

> If the user successfully orders everything, say: "Huh. You actually knew what you wanted. That's a first." Then end the call naturally.

#### 8. Behavioral Boundaries (bullet list)

What the character must NEVER do. Non-negotiable safety rules.

> Boundaries you MUST NEVER cross:
> - Never use slurs, threats, or truly offensive content
> - Never insult the user personally (insult the SITUATION, not the PERSON)
> - Never generate sexual, violent, or discriminatory content
> - Never break the fourth wall or acknowledge being an AI
> - If the user is abusive, express disgust in-character and hang up — do NOT engage

#### 9. Opening Line (1-3 sentences)

The character's first line when the call starts. The character ALWAYS speaks first. This sets the scene, establishes personality, and gives the user their first cue to respond.

> Your opening line: "Welcome to the worst restaurant in town. I've been on my feet for 12 hours. What do you want?"

---

## 5. Briefing Text and Content Warnings

### 5.1 Briefing Text (FR14)

Shown before the user's first attempt at a scenario. Helps reduce anxiety without spoiling the experience.

**Format:** 3 parts, each 1 sentence:

1. **Key vocabulary** — 2-3 words/phrases the user might need
2. **Situation context** — What's happening in 1 sentence
3. **Character behavior hint** — What to expect, 1 sentence

**Example:**
> **Key vocabulary:** "I'd like...", "soup of the day", "grilled/fried"
> **Context:** You're ordering food at a restaurant. The waiter is not in a good mood.
> **Expect:** The waiter is impatient — order clearly and don't take too long.

**Rules:**
- Helpful without being a spoiler
- Never reveal specific escalation triggers or exit lines
- Never list more than 3 vocabulary items (keep it digestible)
- Written in English (the user is practicing English)

### 5.2 Content Warning (FR38)

Required for scenarios involving threat, confrontation, or authority pressure.

**When to set content_warning:**
- Physical threat scenarios (mugger) — always
- Authority pressure scenarios (cop) — always
- Emotional confrontation (girlfriend, landlord) — if intensity is high
- Non-threatening scenarios (waiter, interviewer) — `null`, no warning needed

**Format:** 1-2 sentences describing the nature of the intensity.

**Example:**
> This scenario involves a simulated street robbery. The character will be verbally aggressive and demanding. No real danger — it's practice.

---

## 6. Exit Lines

Each scenario needs two exit lines for the character:

### Hang-Up Exit Line (failure)

Theatrical, dramatic, in-character. The character is done with the user.

Must feel like a **sitcom moment**, not a cold disconnect. The user should smile, not feel attacked.

### Completion Exit Line (success)

Grudging acceptance. The character is surprised the user made it through.

**Never congratulatory.** The character is impressed DESPITE themselves.

**Reference for launch scenarios:** UX Design Spec — Phase 4: The Hang-Up section has exit lines for mugger, waiter, girlfriend, cop, and landlord.

---

## 7. Narrative Arc

Each scenario should include a narrative arc — a table describing the expected conversation flow as a sequence of exchanges. This is **not** a rigid script; the LLM will improvise within these beats. It serves two purposes:

1. **Authoring guide** — helps the author design a coherent conversation structure and set `expected_exchanges` accurately
2. **Calibration reference** — during testing, the operator can compare the actual transcript against the expected flow to diagnose issues

**Format:** A table with one row per exchange:

| Column | Description |
|--------|-------------|
| Exchange # | Sequential number (1 to `expected_exchanges`) |
| Character's role | What the character does/says in this beat |
| What user needs to do | The user action that counts as a successful exchange |

The `expected_exchanges` metadata field must match the number of rows in this table.

---

## 8. Debrief Generation Parameters

Two metadata fields control how the AI scoring prompt generates post-call debrief content. The scoring prompt itself is shared across all scenarios (defined in [`difficulty-calibration.md`](difficulty-calibration.md) §5.3) — but each scenario injects these fields to personalize the output:

| Field | How the scoring prompt uses it |
|-------|-------------------------------|
| `language_focus` | The AI evaluates the user's performance **specifically** in these areas. A scenario with `"ordering food, polite requests, food adjectives"` will produce debrief feedback about ordering vocabulary and politeness, not generic language feedback. |
| `expected_exchanges` | Used to calculate survival % (`floor(successful_exchanges / expected_exchanges × 100)`). Also tells the AI how many exchange opportunities existed, so it can assess which exchanges the user handled well vs. poorly. |

**Authoring tip:** Choose `language_focus` values that are specific enough to produce actionable debrief feedback. Compare:
- Too vague: `"speaking English"` — debrief will be generic
- Good: `"ordering food, polite requests, food adjectives"` — debrief will target specific skills
- Too narrow: `"past participle of irregular verbs"` — may not match what actually happens in the conversation

The scoring payload sent to `score_transcript.py` includes: transcript, scenario-name, difficulty, expected-exchanges, and language-focus. See authoring workflow Step 4 (§10) for the exact CLI invocation.

---

## 9. Rive Character Assignment

The Rive character file has 5 visual variants switchable via `character` EnumInput:

| Value | Character | Used for scenarios involving... |
|-------|-----------|-------------------------------|
| `mugger` | Street criminal | Robbery, threat |
| `waiter` | Restaurant server | Food ordering, service |
| `girlfriend` | Angry partner | Relationship conflict |
| `cop` | Police officer | Authority, questioning |
| `landlord` | Property owner | Housing dispute, confrontation |

Each scenario maps to exactly **one** character variant. The Flutter app sets the EnumInput when the call screen loads. All variants share the same emotion state machine — only the visual appearance changes.

**Future scenarios** can reuse existing variants (e.g., a "job interviewer" could use the `landlord` variant) or new variants can be added to the Rive file (EnumInput is additive).

---

## 10. Authoring Workflow

Step-by-step process for creating a production-ready scenario:

### Step 1 — Write the scenario file

Create a new file in `_bmad-output/planning-artifacts/scenarios/{character-name}.md` following this template. Fill in all metadata, write the system prompt, narrative arc, and exit lines. **Do not write briefing text yet** — that comes after calibration (Step 7).

### Step 2 — Configure on VPS

SSH to the VPS and update the system prompt in the Pipecat configuration:

```bash
ssh vps
# Edit server/pipeline/prompts.py with the new system prompt
# Restart the service
systemctl restart pipecat.service
```

### Step 3 — Test the scenario (2 passes minimum)

Play the scenario using the Flutter app. Two required passes per [`scenario-testing-process.md`](scenario-testing-process.md) §4:

| Pass | Play as... | Purpose |
|------|-----------|---------|
| **A: "Good B1"** | User who tries hard, some errors | Verify survival % hits upper end of target |
| **B: "Struggling B1"** | User who struggles, longer pauses | Verify survival % hits lower end and hang-up triggers |

### Step 4 — Score the transcripts

Retrieve the transcript from the VPS and run the scoring tool (built in Story 3.0):

```bash
scp vps:/tmp/transcript_*.json ./calibration-data/
cd server
python scripts/score_transcript.py \
  --transcript ../calibration-data/transcript_{id}.json \
  --scenario-name "The Waiter" \
  --difficulty easy \
  --expected-exchanges 6 \
  --language-focus "ordering food,polite requests,food adjectives"
```

### Step 5 — Validate calibration

Check the scoring report against the survival targets for each difficulty level in [`difficulty-calibration.md`](difficulty-calibration.md) §4.3.

Fill out the calibration checklist from [`scenario-testing-process.md`](scenario-testing-process.md) §5.

### Step 6 — Adjust if needed

If survival % is outside the target range (±10%):

| Problem | Adjustment |
|---------|-----------|
| Too easy (survival > 90%) | Reduce silence tolerance, speed up escalation, remove rephrasing |
| Too hard (survival < target floor - 10%) | Increase patience_start, add rephrasing, slow escalation |
| Debrief quality poor | Adjust language_focus, expected_exchanges, or system prompt vocabulary |
| Character breaks personality | Rewrite personality rules section |

After adjusting, return to Step 2 and retest.

### Step 7 — Write briefing text

Now that calibration has confirmed the scenario's vocabulary and conversation flow, write the briefing text (§5.1). Base the key vocabulary and context hints on what actually happened in the test transcripts, not on assumptions made before testing.

### Step 8 — Record results

Update the scenario file's "Calibration Results" section with:
- Pass A and Pass B survival percentages
- Scoring JSON file references
- Verdict: PASS / ADJUST / REWORK
- Any override fields set during calibration

### Step 9 — Push to production

The scenario is production-ready when both passes produce a PASS verdict. The system prompt and metadata are already on the VPS from testing — verify and leave in place.

---

## 11. Checklist Quick Reference

Before marking a scenario as production-ready, confirm:

- [ ] All metadata fields filled (§3)
- [ ] System prompt has all 9 mandatory sections (§4)
- [ ] Briefing text written (§5.1)
- [ ] Content warning set or explicitly null (§5.2)
- [ ] Hang-up and completion exit lines written (§6)
- [ ] Narrative arc defined with exchange count matching expected_exchanges (§7)
- [ ] Rive character assigned (§9)
- [ ] Pass A tested — survival % in target range
- [ ] Pass B tested — survival % in target range and hang-up triggers correctly
- [ ] AI scoring produces valid JSON with all required fields
- [ ] Debrief content is specific and actionable
- [ ] Character stays in personality throughout both passes
- [ ] Escalation feels theatrical, not hostile

---

## 12. Example

See [`scenarios/example-the-waiter.md`](scenarios/example-the-waiter.md) for a fully worked example using "The Waiter" (easy difficulty).
