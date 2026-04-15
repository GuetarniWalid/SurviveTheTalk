# Difficulty Calibration & AI Scoring Framework

Date: 2026-04-14
Authors: Alice (PO), Winston (Architect)
Status: Active
Epic 3 Dependency: Must be finalized before Story 3.2 (Create Launch Scenarios)

---

## 1. Purpose

This document defines:

1. **Objective difficulty criteria** for scenario levels (easy / medium / hard)
2. **Exchange evaluation rules** — when an exchange counts as "successful"
3. **AI scoring prompt** for post-call transcript evaluation (structured JSON output)
4. **Calibration targets** — expected survival ranges per level for a B1 user

This framework is **scenario-agnostic**. Individual scenario calibration (waiter, mugger, girlfriend, cop, landlord) happens in Story 3.2 using these rules as constraints.

---

## 2. Target User Profile

| Attribute | Value |
|-----------|-------|
| CEFR Level | **B1 (Intermediate)** |
| Can do | Handle most everyday situations, express opinions, describe experiences |
| Struggles with | Idiomatic expressions, fast speech, complex grammar under pressure |
| Goal | Build conversational confidence through realistic practice |

All calibration targets assume a **first-attempt B1 user** — someone who has never played the scenario before.

---

## 3. Core Scoring Definitions

### 3.1 What Is a "Checkpoint"?

A **checkpoint** = a structured goal within the scenario that the user must achieve to progress. Each checkpoint defines:
- **id**: unique identifier (e.g., "react", "refuse", "challenge")
- **hint_text**: short phrase shown to the user during the call
- **prompt_segment**: system prompt fragment active while waiting for this checkpoint to be met — defines character behavior for this phase
- **success_criteria**: what the user must do/say to pass (used by the ExchangeClassifier)

Scenarios progress linearly: checkpoint 1 → 2 → ... → N. The user cannot skip ahead.

### 3.2 What Is an "Exchange"?

An **exchange** = one complete turn pair:
1. Character says something (prompt, question, reaction)
2. User responds

The character's opening line does NOT count as an exchange (it's the setup). Exchanges still occur within each checkpoint — a single checkpoint may span multiple exchanges before the user meets its success_criteria.

### 3.3 When Is a Checkpoint "Passed"?

A checkpoint is **passed** when the ExchangeClassifier (async parallel LLM) confirms the user's response meets the current checkpoint's success_criteria. The classifier evaluates after each user turn.

| User Response Quality | Checkpoint Result | Example |
|-----------------------|-------------------|---------|
| Meets success_criteria (any grammar level) | **Passed** | "No, I'm not paying you." (criteria: explicit refusal) |
| Comprehensible but doesn't meet criteria | Not passed (patience penalty) | "Who are you?" (criteria was: refuse to pay) |
| Off-topic or incomprehensible | Not passed (patience penalty) | "The weather is nice today." |
| Silence (no response within tolerance) | Not passed (silence penalty) | User freezes, character escalates |
| Inappropriate / abusive content | Not passed (+ instant hang-up) | Slurs, threats, harassment |

**Key principle:** Grammar errors are punished in the **debrief**, not in the survival score. Survival measures the user's ability to navigate the scenario's challenges — can you figure out what to do and do it under pressure?

### 3.4 Survival Percentage Formula

```
survival_pct = min(100, floor(checkpoints_passed / total_checkpoints × 100))
```

- Integer 0–100
- Uses `floor()` to prevent false 100%
- Only exact 100% displays green (#2ECC40); all others display red (#E74C3C)
- Backend-calculated, deterministic, reproducible
- A checkpoint is "passed" only when the classifier confirms success_criteria met

### 3.5 Character Hang-Up Trigger

The character hangs up when **any** of these conditions is met:

1. **Patience meter** reaches 0 (accumulated failed exchanges + silence penalties)
2. **Maximum silence** exceeded (level-dependent, see §4)
3. **Inappropriate content** detected (instant hang-up, no tolerance)
4. **All checkpoints passed** (character ends call naturally — this is 100% survival)

---

## 4. Difficulty Level Definitions

### 4.1 Key Principle: Checkpoint Count Is Scenario-Defined, Not Difficulty-Defined

Each scenario has a **fixed checkpoint sequence** (e.g., react → refuse → challenge → deflect → stand firm). The number of checkpoints is determined by the **scenario content**, not by the difficulty level. Difficulty controls the patience/penalty parameters, not the number of goals. Typical range: 4-6 checkpoints for short scenarios, up to 10-12 for complex ones.

**Difficulty controls HOW the character behaves during those exchanges** — not how many there are. A hard scenario with 6 exchanges is harder because the character is less patient, speaks faster, and gives fewer second chances, not because it has more exchanges.

The `expected_exchanges` field is set **per scenario** in Story 3.2.

### 4.2 Difficulty Levers Catalog

Every lever available to tune scenario difficulty, organized by category. When authoring a scenario in Story 3.2, these are the knobs to turn.

#### A. Timing & Patience (how forgiving the character is)

| Lever | What it controls | Easy end | Hard end |
|-------|-----------------|----------|----------|
| **Patience meter start** | Total error budget before hang-up | 100 (many mistakes allowed) | 60 (few mistakes before game over) |
| **Failed exchange penalty** | How much patience each failed turn costs | -15 (gentle) | -25 (punishing) |
| **Silence penalty** | Patience cost when user freezes | -10 | -20 |
| **Recovery per success** | Patience regained after a good response | +5 (forgiving, mistakes can be offset) | +0 (no recovery, every error is permanent) |
| **First-error leniency** | Reduced penalty on the very first mistake | Yes (-10 instead of full) | No (full penalty from the start) |
| **Silence tolerance (prompt)** | Seconds before character says "hello? you there?" | 6s | 3s |
| **Silence tolerance (hang-up)** | Seconds of total silence before character hangs up | 10s | 5s |
| **Escalation stages** | Warning steps before hang-up (eye-roll → sigh → verbal → hang-up) | 4 stages (gradual) | 2 stages (abrupt) |

#### B. Language & Comprehension (how hard it is to understand the character)

| Lever | What it controls | Easy end | Hard end |
|-------|-----------------|----------|----------|
| **Speech speed** | How fast the character talks | Slow, clearly articulated | Fast, natural cadence |
| **Vocabulary level** | Word complexity in character's dialogue | Basic A2–B1 (everyday words) | Advanced B1–B2 (domain-specific, formal) |
| **Idiomatic expressions** | Slang, idioms, cultural references | 0 (plain English) | 3+ per conversation |
| **Sentence complexity** | Character's grammar structures | Short, simple sentences | Compound/complex sentences, subordinate clauses |
| **Accent strength** | How "clean" the TTS pronunciation is | Neutral, standard | Stronger regional character (via TTS voice selection) |

#### C. Conversational Dynamics (how the character interacts)

| Lever | What it controls | Easy end | Hard end |
|-------|-----------------|----------|----------|
| **Rephrasing on confusion** | Character repeats/simplifies when user seems lost | Yes (1 free chance) | No (figure it out or lose patience) |
| **Interruption behavior** | Character cuts off the user mid-sentence | Never | Sometimes (adds pressure) |
| **Follow-up questions** | Character asks unexpected sub-questions within the narrative | None (stays on script) | Yes (tests improvisation) |
| **Emotional escalation speed** | How quickly the character goes from neutral to angry | Gradual (theatrical) | Rapid (character snaps fast) |
| **Emotional register** | The character's emotional range | Mild (sarcasm, sighs) | Intense (anger, accusation, urgency) |
| **Topic predictability** | How obvious the expected response is | High (clear what to say next) | Lower (user must infer what the character wants) |

#### D. Scenario Design (set per scenario, not per difficulty level)

These are NOT difficulty levers — they are fixed by the scenario narrative. Listed here for clarity on what is NOT tunable via difficulty.

| Property | What it defines | Set by |
|----------|----------------|--------|
| **Expected exchanges** | How many turns the narrative needs | Scenario script |
| **Character identity** | Who the character is (waiter, cop, etc.) | Scenario definition |
| **Narrative context** | The situation (restaurant, street, phone call) | Scenario definition |
| **Language focus** | Target vocabulary/grammar areas | Scenario definition |
| **Content warning** | Whether scenario has intense themes | Scenario definition |

### 4.3 Difficulty Presets Table

| Parameter | Easy | Medium | Hard |
|-----------|------|--------|------|
| Character speech speed | Slow, clear | Normal | Fast, natural |
| Vocabulary complexity | Basic (A2–B1) | Mixed (B1) | Advanced (B1–B2), idioms |
| Silence tolerance (before prompt) | 6s | 4s | 3s |
| Silence tolerance (before hang-up) | 10s | 7s | 5s |
| Patience meter starting value | 100 | 80 | 60 |
| Failed exchange penalty | -15 | -20 | -25 |
| Silence penalty (per incident) | -10 | -15 | -20 |
| Recovery per successful exchange | +5 | +3 | +0 |
| Escalation stages before hang-up | 4 | 3 | 2 |
| Character interrupts user | Never | Rarely | Sometimes |
| Character rephrases on confusion | Yes (1 chance) | No | No |
| Idiomatic expressions used | 0 | 1–2 | 3+ |
| B1 first-attempt survival target | 60–80% | 35–55% | 15–35% |

### 4.4 Easy Level — Design Intent

**User must feel:** "I can do this. I almost made it. One more try."

- Character is impatient but gives the user **time to think**
- Vocabulary stays within basic everyday English
- Character **repeats or rephrases** if user seems confused (1 chance)
- Escalation is theatrical, not aggressive — eye-rolls, sighs, not threats
- The first failed exchange has **reduced penalty** (-10 instead of -15)
- 4 escalation stages = multiple chances to recover

**Calibration goal:** A B1 user should reach 60–80% on first attempt. Below 60% means the scenario is too hard for Easy. Above 80% means it lacks tension.

### 4.5 Medium Level — Design Intent

**User must feel:** "That was intense. I need to prepare better."

- Character speaks at natural speed with some colloquialisms
- No rephrasing — if the user doesn't understand, the character escalates
- 1–2 idiomatic expressions the user may not know (debrief explains them)
- Emotional pressure increases (character shows frustration vocally)
- Recovery is limited (+3 per success) — mistakes compound

**Calibration goal:** A B1 user should reach 35–55% on first attempt. This level is designed to show the user that real English conversations are harder than classroom exercises.

### 4.6 Hard Level — Design Intent

**User must feel:** "I wasn't ready for that. I need to actually improve."

- Character speaks fast, uses idioms, may interrupt
- No recovery from failed exchanges — patience only decreases
- Short silence tolerance (5s to hang-up) forces quick responses
- Vocabulary includes domain-specific terms (legal, emotional, idiomatic)
- Only 2 escalation stages before hang-up — character patience is thin
- Character may ask unexpected follow-up questions within the scenario narrative

**Calibration goal:** A B1 user should reach 15–35% on first attempt. This level is aspirational — it's where the user sees how far they have to go.

---

## 5. AI Scoring Prompt for Transcript Evaluation

### 5.1 Context

After each call ends, the backend sends the **full transcript** (STT output + LLM character responses) to a dedicated evaluation LLM call. This is separate from the in-call character LLM — it's a post-processing step.

### 5.2 Input Schema

```json
{
  "transcript": [
    {"role": "character", "text": "Welcome to...", "timestamp_ms": 0},
    {"role": "user", "text": "I want...", "timestamp_ms": 3200},
    {"role": "character", "text": "Which one?", "timestamp_ms": 5100},
    {"role": "user", "text": "", "timestamp_ms": null, "event": "silence_timeout"}
  ],
  "scenario": {
    "character_name": "The Waiter",
    "difficulty": "easy",
    "expected_exchanges": 5,
    "language_focus": ["ordering food", "polite requests", "food adjectives"]
  },
  "call_metadata": {
    "duration_seconds": 47,
    "successful_exchanges": 3,
    "survival_pct": 60,
    "hang_up_reason": "patience_depleted"
  }
}
```

### 5.3 AI Scoring System Prompt

```
You are an English language evaluator for a conversation practice app. You analyze transcripts of voice conversations between a language learner (B1 intermediate level) and an AI character.

Your task is to produce a structured evaluation in JSON format. Be specific, honest, and constructive. Never praise without merit. Never soften the truth.

## Rules

1. **Language errors**: Identify grammar, vocabulary, and syntax errors the USER made. For each error, provide the exact quote, the correction, and brief context. Deduplicate — if the same error pattern appears multiple times, report it once with a repetition count. Maximum 5 errors, prioritized by frequency and severity.

2. **Hesitations**: Identify moments where the user paused for more than 3 seconds before responding. Use timestamp gaps between character speech end and user speech start. Report the duration and what the character said just before the pause (the trigger). Maximum 3 hesitations, longest first.

3. **Idioms and slang**: Identify idiomatic expressions or slang the CHARACTER used that a B1 learner might not know. Provide the expression, its meaning, and the context in which it appeared. Maximum 3 idioms.

4. **Areas to work on**: Based on the error patterns and hesitations, suggest 2–3 specific, actionable improvement areas. Be concrete — not "improve grammar" but "practice negative sentence structures (don't/doesn't instead of 'not want')". Each area must reference at least one specific error from the transcript.

5. **Call summary**: One sentence describing what happened in the call (factual, no judgment). If the character hung up, state why objectively.

## Output format

Return ONLY valid JSON matching the schema below. No markdown, no explanation, no preamble.
```

### 5.4 Output Schema

```json
{
  "language_errors": [
    {
      "user_said": "I am agree with you",
      "correction": "I agree with you",
      "context": "When responding to the character's suggestion",
      "error_type": "grammar",
      "repetitions": 3
    }
  ],
  "hesitations": [
    {
      "duration_seconds": 4.2,
      "trigger": "The character asked 'So what are you having?'",
      "position_in_conversation": "exchange_3"
    }
  ],
  "idioms_encountered": [
    {
      "expression": "pull the other one",
      "meaning": "I don't believe you",
      "context": "The mugger said this when the user claimed to have no money"
    }
  ],
  "areas_to_work_on": [
    {
      "area": "Negative sentence structures",
      "detail": "Use 'don't/doesn't' instead of 'not + verb'. You said 'I not want' 3 times — correct form is 'I don't want'.",
      "referenced_errors": ["I not want the soup"]
    }
  ],
  "call_summary": "The user ordered food at a restaurant. The waiter hung up after the user froze for 8 seconds when asked about dessert."
}
```

### 5.5 Evaluation Boundaries

The AI scoring prompt must **NOT**:
- Generate the survival percentage (backend-calculated)
- Judge pronunciation (STT handles speech-to-text, not phonetics)
- Assess fluency as a numerical score (qualitative analysis only)
- Comment on the user's accent or speaking speed
- Provide encouragement or discouragement (the app UI handles tone)

The AI scoring prompt **MUST**:
- Analyze only what the user SAID (text from STT), not how they said it
- Reference specific quotes from the transcript
- Deduplicate errors (same pattern = 1 entry with repetition count)
- Respect maximum counts (5 errors, 3 hesitations, 3 idioms, 3 areas)
- Return valid JSON parseable by the backend

---

## 6. Calibration Testing Process

**Detailed process document:** [`scenario-testing-process.md`](scenario-testing-process.md) — Defines the complete step-by-step testing workflow, technical tooling (TranscriptLogger, score_transcript.py), checklist templates, and minimum test coverage matrix. The sections below provide the high-level summary; refer to the process document for operational details.

### 6.1 How to Validate Calibration

For each scenario, before marking it as production-ready:

1. **Author plays the scenario** as a simulated B1 user (intentional errors, some hesitations)
2. **Capture the transcript** from the call
3. **Run the AI scoring prompt** on the transcript
4. **Verify survival %** matches the expected range for the difficulty level
5. **Verify debrief quality** — errors are specific, hesitations are real, areas are actionable
6. **Adjust system prompt parameters** if survival % is outside the target range:
   - Too easy → reduce silence tolerance, increase exchange count, speed up escalation
   - Too hard → increase silence tolerance, add character rephrasing, slow escalation

### 6.2 Calibration Checklist

For each scenario, confirm:

- [ ] B1 simulated user achieves survival % within target range (±10%)
- [ ] Character hangs up naturally (not abruptly, not too late)
- [ ] At least 2 language errors are detectable in a typical B1 transcript
- [ ] At least 1 hesitation moment occurs naturally
- [ ] AI scoring prompt produces valid JSON with all required fields
- [ ] Debrief content is specific, honest, and actionable
- [ ] Character stays in personality throughout the call
- [ ] Escalation feels theatrical, not hostile or disturbing

---

## 7. Integration Notes for Story 3.2

When creating individual scenarios in Story 3.2, each scenario file must include:

1. **Difficulty level** (easy / medium / hard) — determines character behavior parameters from §4.2
2. **Expected exchanges** — defined by the scenario's narrative arc (how many turns the story needs), independent of difficulty
3. **Language focus** — 2–3 vocabulary/grammar areas the scenario targets
4. **Escalation triggers** — scenario-specific behaviors that deplete patience
5. **Character-specific patience adjustments** — overrides to the base patience meter if needed
6. **Calibration test results** — survival % from author testing (§6.1)

**Important:** `expected_exchanges` is a property of the scenario narrative, not of the difficulty level. A 6-exchange restaurant scenario stays 6 exchanges whether it's easy or hard. Difficulty affects how the character *reacts* during those exchanges, not how many there are.

The scoring prompt (§5.3) is **shared across all scenarios** — it does not change per difficulty level. Difficulty is encoded in the scenario metadata passed as input, not in the evaluation logic.

---

## 8. Technical Implementation Mapping (Architect)

This section maps every calibration lever and scoring concept to its concrete technical implementation. Added by Winston (Architect) to ensure the framework is implementable within the existing Pipecat + LiveKit + FastAPI stack.

### 8.1 Architectural Decisions

#### AD-1: Exchange success is determined by an async parallel classifier LLM

A lightweight LLM classifier evaluates each user turn for comprehensibility and contextual relevance. It runs **in parallel** with the character LLM — zero impact on conversation latency.

**Architecture:**

```
User speaks → STT text
                ├──→ [Main pipeline] LLM character → TTS → audio output
                │     (zero delay — works exactly as today)
                │
                └──→ [Async parallel] Classifier LLM
                      (evaluates user turn: success / fail)
                      (result arrives while character is still speaking)
                      (PatienceTracker updated before next turn)
```

**Implementation:** When the STT produces a `TranscriptionFrame`, the `CheckpointManager` processor:
1. Forwards the frame to the main pipeline immediately (no blocking)
2. Launches an `asyncio.create_task()` that calls a lightweight LLM with the user text + scenario context + current checkpoint's success_criteria
3. The classifier returns `{met: true/false}` in ~200-400ms
4. The CheckpointManager receives the result: if met, advances checkpoint and swaps prompt segment; the PatienceTracker updates patience meter accordingly
5. If the classifier is slow (>2s), fallback = checkpoint NOT advanced (conservative, no free progression). The PatienceTracker treats the exchange as a normal failure.

**Classifier prompt (minimal):**
```
Given this scenario context: "{scenario_description}"
The character just said: "{last_character_line}"
The user responded: "{user_text}"
Current checkpoint success criteria: "{current_checkpoint.success_criteria}"

Does the user's response meet the checkpoint success criteria?
Return ONLY: {"met": true} or {"met": false}
```

**Cost:** ~$0.0003/turn using a fast model (e.g., Qwen 3.5 Flash). For 6 turns/call × 1500 calls/day at scale = ~$2.70/day. Negligible vs TTS costs.

**Latency impact on conversation:** Zero. The classifier runs in parallel — the user hears the character respond at full speed.

**Fallback:** If the classifier fails or times out, the checkpoint is NOT advanced. This is conservative — better to make the user repeat a goal than to give them unearned progression. The PatienceTracker treats the exchange as a normal failure.

**Alternatives considered:**
- LLM implicit (character behavior parsing): Rejected — non-deterministic, fragile, "too sarcastic" character would unfairly penalize users
- Function calling (character LLM calls report_exchange tool): Rejected — adds 50-100ms to the critical path, LLM may forget to call the function
- Mechanical only (spoke = success): Rejected by PO — intelligent judgment needed for off-topic and incomprehensible responses

#### AD-2: Patience meter lives in a backend state tracker (not the LLM)

LLMs cannot reliably maintain numerical state across turns. The patience meter must be a **server-side component** that:

1. Initializes with the difficulty preset value (100 / 80 / 60)
2. Observes each exchange outcome (success / failure / silence)
3. Applies penalties and recovery per the difficulty preset
4. Injects current patience level into the LLM context each turn (e.g., appended to system prompt: "Your patience level is now 35/80. You are visibly frustrated.")
5. Triggers `EndFrame` when patience reaches 0 (character hangs up)

**Implementation:** A custom Pipecat `FrameProcessor` inserted between the LLM aggregator and the LLM service. It intercepts context frames, updates state, and modifies the system prompt with current patience context. On patience=0, it emits a `TTSSpeakFrame` with the character's hang-up line followed by an `EndFrame`.

**Data flow:**
```
STT → Context Aggregator → [PatienceTracker] → LLM → TTS → Transport
                                ↓
                         (tracks state,
                          modifies prompt,
                          triggers hang-up)
```

#### AD-3: Transcript capture requires a pipeline logging processor

The current PoC pipeline does not capture transcripts. A `TranscriptLogger` processor must be added that:

1. Captures every STT output frame (user speech) with `timestamp_ms`
2. Captures every LLM output frame (character speech) with `timestamp_ms`
3. Stores the ordered transcript in memory during the call
4. On call end, persists the transcript to the database (`call_sessions` table or a new `transcripts` table)

**Hesitation calculation:** `gap_ms = user_frame.timestamp_ms - previous_character_frame.end_timestamp_ms`. Gaps > 3000ms are flagged as hesitations.

**Implementation:** A `FrameProcessor` that observes `TranscriptionFrame` (STT) and `TextFrame` / `TTSSpeakFrame` (LLM/TTS) without modifying them (passthrough with side-effect logging).

#### AD-4: Post-call scoring model selection

The in-call LLM (Qwen 3.5 Flash) is optimized for speed (<200ms TTFT). The post-call scoring prompt requires **analytical precision**, not speed — latency budget is generous (<5s per the PRD's debrief generation target).

**Decision:** Use the same OpenRouter API but with a more capable model for scoring. Candidate: `qwen/qwen3-235b-a22b` or equivalent. The model choice should be a **configuration parameter** (not hardcoded) so it can be upgraded without code changes.

**Cost consideration:** One scoring call per completed call. At ~500 tokens output, cost is negligible vs. the TTS cost of the call itself.

#### AD-5: Silence detection is a timer in the PatienceTracker, not VAD

The existing Silero VAD detects speech start/stop. Silence tolerance (§4) requires a **timer** that counts seconds of no user speech after the character finishes speaking:

- Timer starts when TTS output completes (character done talking)
- Timer resets when STT detects user speech
- At `silence_prompt_threshold` → character says a prompt ("Hello? You still there?")
- At `silence_hangup_threshold` → patience penalty applied, potential hang-up

**Implementation:** Part of the `PatienceTracker` processor (AD-2). Uses `asyncio` timers triggered by frame observation.

### 8.2 Lever-to-Implementation Mapping

#### A. Timing & Patience Levers

| Lever | Technical Implementation | Component |
|-------|------------------------|-----------|
| Patience meter start | `PatienceTracker.initial_patience` loaded from scenario config | PatienceTracker processor |
| Failed exchange penalty | `PatienceTracker.fail_penalty` loaded from difficulty preset | PatienceTracker processor |
| Silence penalty | `PatienceTracker.silence_penalty` applied when silence timer fires | PatienceTracker processor |
| Recovery per success | `PatienceTracker.recovery_bonus` added on successful exchange | PatienceTracker processor |
| First-error leniency | `PatienceTracker.first_fail_penalty` (reduced value for first failure only) | PatienceTracker processor |
| Silence tolerance (prompt) | `PatienceTracker.silence_prompt_seconds` — asyncio timer threshold | PatienceTracker processor |
| Silence tolerance (hang-up) | `PatienceTracker.silence_hangup_seconds` — asyncio timer threshold | PatienceTracker processor |
| Escalation stages | `PatienceTracker.escalation_thresholds` — list of patience values that trigger escalation context injection (e.g., [75, 50, 25, 0] for 4 stages) | PatienceTracker processor → LLM prompt |

#### B. Language & Comprehension Levers

| Lever | Technical Implementation | Component |
|-------|------------------------|-----------|
| Speech speed | Cartesia TTS `speed` parameter if supported; otherwise LLM system prompt instruction ("speak in short, slow sentences" vs "speak naturally and fast") | TTS service settings / LLM system prompt |
| Vocabulary level | LLM system prompt instruction ("use only basic everyday English" vs "use idioms, slang, and domain-specific vocabulary") | LLM system prompt |
| Idiomatic expressions | LLM system prompt instruction ("never use idioms" vs "use 3+ idiomatic expressions naturally in conversation") | LLM system prompt |
| Sentence complexity | LLM system prompt instruction ("keep sentences to 5-8 words" vs "use natural complex sentences") | LLM system prompt |
| Accent strength | Cartesia TTS voice selection — different voice IDs for different character accents. Selected per scenario, not per turn | TTS service settings (voice ID per scenario) |

#### C. Conversational Dynamics Levers

| Lever | Technical Implementation | Component |
|-------|------------------------|-----------|
| Rephrasing on confusion | LLM system prompt instruction ("if the user seems confused, rephrase your last question once" vs "never rephrase, escalate frustration instead") | LLM system prompt |
| Interruption behavior | Pipecat `allow_interruptions` + `MinWordsUserTurnStartStrategy.min_words` (lower = easier to interrupt). Per-scenario config | Pipecat pipeline params |
| Follow-up questions | LLM system prompt instruction ("stay strictly on the scenario script" vs "ask unexpected follow-up questions to test improvisation") | LLM system prompt |
| Emotional escalation speed | Combination of patience thresholds (AD-2) + LLM prompt context ("Your patience is at 60/80, you're getting irritated" injected by PatienceTracker) | PatienceTracker → LLM prompt |
| Emotional register | LLM system prompt instruction defining emotional range ("mild sarcasm only" vs "express anger, accusation, urgency") | LLM system prompt |
| Topic predictability | LLM system prompt — how explicit the character is about what they want ("clearly state what you want from the user" vs "imply what you want, make the user figure it out") | LLM system prompt |

### 8.3 Scenario Config Schema (Technical)

Each scenario in the database will need these fields to implement the calibration framework:

```python
# Extends the existing `scenarios` table from architecture.md
scenario_config = {
    # Core fields
    "id": "scenario_001",
    "title": "Order at the restaurant",
    "base_prompt": "...",             # Character identity, personality, boundaries
    "checkpoints": [                  # Ordered progression
        {
            "id": "greet",
            "hint_text": "Tell the waitress what you'd like to order.",
            "prompt_segment": "...",  # Active system prompt for this phase
            "success_criteria": "User states a food order clearly."
        },
        # ... more checkpoints
    ],
    "difficulty": "easy",             # Determines preset values below
    "rive_character": "waiter",       # Rive EnumInput value
    "is_free": True,
    "content_warning": None,

    # Derived fields
    "total_checkpoints": 6,           # len(checkpoints)
    "language_focus": ["ordering food", "polite requests"],

    # Difficulty preset overrides (nullable — defaults from §4.3 preset)
    "patience_start": None,           # Override preset if needed
    "fail_penalty": None,
    "silence_penalty": None,
    "recovery_bonus": None,
    "silence_prompt_seconds": None,
    "silence_hangup_seconds": None,
    "escalation_thresholds": None,    # JSON array e.g. [75, 50, 25, 0]

    # TTS config
    "tts_voice_id": "cd6256ef-...",   # Cartesia voice per character
    "tts_speed": None,                # Override if Cartesia supports it

    # Scoring
    "scoring_model": None,            # Override default scoring LLM if needed
}
```

Fields set to `None` inherit from the difficulty preset defaults (§4.3). This allows most scenarios to just specify `difficulty: "easy"` and get all defaults, while allowing per-scenario tuning when calibration testing reveals the need.

### 8.4 New Pipeline Components Required (Epic 4+)

| Component | Type | Purpose | Epic |
|-----------|------|---------|------|
| `CheckpointManager` | Pipecat FrameProcessor | Checkpoint progression, prompt segment swapping, data channel event pushing. Works alongside PatienceTracker | Epic 6 (Call Experience) |
| `PatienceTracker` | Pipecat FrameProcessor | Patience state, silence timers, escalation, hang-up trigger | Epic 6 (Call Experience) |
| `ExchangeClassifier` | Async LLM service | Parallel lightweight LLM that evaluates each user turn against current checkpoint's success_criteria. Called by CheckpointManager, never blocks pipeline | Epic 6 (Call Experience) |
| `TranscriptLogger` | Pipecat FrameProcessor | Capture timestamped transcript for scoring + debrief | Epic 6 (Call Experience) |
| `PostCallScorer` | FastAPI service | Runs AI scoring prompt on transcript, stores debrief | Epic 7 (Debrief) |
| `ScenarioConfigLoader` | FastAPI service | Loads scenario config + difficulty presets, passes to pipeline | Epic 5 or 6 |

These components do not exist in the PoC. They will be built in their respective epics. This calibration document provides the specification they must implement.
