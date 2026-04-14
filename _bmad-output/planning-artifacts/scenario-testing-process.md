# Scenario Testing Process

Date: 2026-04-14
Authors: Dana (QA) + Charlie (Dev), validated by Walid
Status: Active
Epic 3 Dependency: Must be operational before Story 3.2 calibration testing
References: [difficulty-calibration.md](difficulty-calibration.md)

---

## 1. Purpose

Define the end-to-end process for testing and calibrating scenarios during Epic 3, using the existing PoC pipeline on the VPS. This process bridges the gap between the current infrastructure and the automated components planned for Epics 6-7 (`PatienceTracker`, `TranscriptLogger`, `PostCallScorer`).

---

## 2. Process Overview

```
┌─────────────────────────────────────────────────────────┐
│  SCENARIO TESTING CYCLE (repeat per scenario, min 2x)   │
│                                                         │
│  1. CONFIGURE  ──→  Load scenario system prompt on VPS  │
│  2. PLAY       ──→  Walid tests as simulated B1 user    │
│  3. CAPTURE    ──→  TranscriptLogger writes JSON file   │
│  4. SCORE      ──→  score_transcript.py calls AI scorer │
│  5. VALIDATE   ──→  Walid checks feel + AI checks data  │
│  6. ADJUST     ──→  Tune system prompt if out of range   │
│  7. RETEST     ──→  Back to step 2 if adjusted           │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Technical Components to Build

### 3.1 TranscriptLogger (Mini FrameProcessor)

**What:** A lightweight Pipecat `FrameProcessor` that captures each conversational turn and writes it to a JSON file on the VPS.

**Behavior:**
- Observes `TranscriptionFrame` (user speech from STT) and `TextFrame` / `TTSSpeakFrame` (character speech from LLM/TTS)
- Passthrough only — does NOT modify frames, zero impact on pipeline latency
- Records `{role, text, timestamp_ms}` for each turn
- On call end (`EndFrame`), writes the complete transcript to `/tmp/transcript_{session_id}.json`

**Output format:**

```json
{
  "session_id": "abc123",
  "started_at": "2026-04-15T14:30:00Z",
  "ended_at": "2026-04-15T14:31:47Z",
  "duration_seconds": 107,
  "transcript": [
    {"role": "character", "text": "Welcome to the restaurant. What can I get you?", "timestamp_ms": 0},
    {"role": "user", "text": "I want the chicken please", "timestamp_ms": 3200},
    {"role": "character", "text": "Which one? We have three chicken dishes.", "timestamp_ms": 5100},
    {"role": "user", "text": "", "timestamp_ms": null, "event": "silence_timeout"}
  ]
}
```

**Location:** `server/src/transcript_logger.py` (new file)

**Integration:** Insert into the Pipecat pipeline as an observer processor. Requires minimal wiring in the pipeline setup.

**Scope:** This is a **testing tool for Epic 3 only**. It will be replaced by the production `TranscriptLogger` in Epic 6 (which writes to database instead of file).

### 3.2 score_transcript.py (Scoring Script)

**What:** A standalone Python script that takes a transcript JSON + scenario metadata and calls the AI scoring prompt via OpenRouter.

**Usage:**

```bash
python score_transcript.py \
  --transcript /tmp/transcript_abc123.json \
  --scenario-name "The Waiter" \
  --difficulty easy \
  --expected-exchanges 6 \
  --language-focus "ordering food,polite requests,food adjectives"
```

**Behavior:**
1. Read the transcript JSON file
2. Count successful exchanges (any user turn with non-empty text that is not a silence_timeout event)
3. Calculate `survival_pct = floor(successful_exchanges / expected_exchanges * 100)`, capped at 100
4. Build the scoring input payload (transcript + scenario metadata + call metadata)
5. Send to OpenRouter with the AI scoring system prompt from [difficulty-calibration.md](difficulty-calibration.md) §5.3
6. Parse the JSON response
7. Print a formatted calibration report to stdout
8. Save the full result to `_bmad-output/implementation-artifacts/calibration-tests/{scenario_id}_{difficulty}_{timestamp}.json`

**Output example (stdout):**

```
═══════════════════════════════════════════════════
 CALIBRATION REPORT — The Waiter (easy)
═══════════════════════════════════════════════════
 Survival: 60% (target: 60-80%) ✅ IN RANGE
 Exchanges: 3/5 successful
 Duration: 47s
 Hang-up reason: silence_timeout

 Language errors found: 2
 Hesitations found: 1
 Idioms encountered: 0
 Areas to work on: 2

 Debrief quality: ALL FIELDS PRESENT ✅
═══════════════════════════════════════════════════
```

**Location:** `server/scripts/score_transcript.py` (new file)

**Dependencies:** `httpx` (already in server deps for OpenRouter calls), `json`, `argparse`

**Config:** OpenRouter API key read from existing `.env` file or `OPENROUTER_API_KEY` env var.

---

## 4. Step-by-Step Testing Process

### Step 1 — Configure scenario on VPS

```bash
ssh vps
# Edit the system prompt in the Pipecat config to load the scenario under test
# Restart the service
systemctl restart pipecat.service
```

The scenario system prompt must include:
- Character personality and behavior instructions
- Difficulty-specific behavior rules (from difficulty-calibration.md §4.3)
- Expected exchanges count
- Escalation behavior description

### Step 2 — Play the scenario

Walid opens the Flutter app and initiates a call. Two test passes required per scenario:

| Pass | Walid plays as... | Purpose |
|------|-------------------|---------|
| **Pass A: "Good B1"** | B1 user who tries hard — some grammar errors, occasional hesitation, but stays on topic | Verify survival % hits the **upper end** of target range |
| **Pass B: "Struggling B1"** | B1 user who struggles — more errors, longer pauses, one off-topic response | Verify survival % hits the **lower end** of target range and hang-up triggers correctly |

### Step 3 — Retrieve transcript

```bash
# On VPS after the call ends
scp vps:/tmp/transcript_*.json ./calibration-data/
```

### Step 4 — Run AI scoring

```bash
cd server
python scripts/score_transcript.py \
  --transcript ./calibration-data/transcript_abc123.json \
  --scenario-name "The Waiter" \
  --difficulty easy \
  --expected-exchanges 6 \
  --language-focus "ordering food,polite requests,food adjectives"
```

Review the formatted report output.

### Step 5 — Validate (objective + subjective)

Fill out the calibration test checklist (see §5 below) for each test pass.

### Step 6 — Adjust if needed

If the scenario fails calibration:
- **Survival too high** → reduce silence tolerance, speed up escalation, remove rephrasing
- **Survival too low** → increase patience, add rephrasing chance, slow escalation
- **Debrief quality poor** → adjust scenario metadata (language_focus, expected_exchanges)
- **Feel wrong** → rewrite system prompt personality/escalation behavior

After adjustment, return to Step 1.

---

## 5. Calibration Test Checklist

Copy this template for each scenario test. Store completed checklists alongside the scoring JSON in `_bmad-output/implementation-artifacts/calibration-tests/`.

```markdown
# Calibration Test — [Scenario Name] / [Difficulty]

Date: YYYY-MM-DD
Pass: A (Good B1) / B (Struggling B1)
Transcript file: transcript_[id].json
Scoring file: [scenario]_[difficulty]_[timestamp].json

## Objective (AI Scoring)
- [ ] Survival % within target range (±10%)
      Obtained: ___% | Target: ___–___%
- [ ] ≥2 language errors detected in transcript
- [ ] ≥1 hesitation moment detected
- [ ] Scoring JSON valid with all required fields
- [ ] Debrief content is specific and actionable (not generic)

## Subjective (Walid Feel Check)
- [ ] Character stays in personality throughout the call
- [ ] Escalation is theatrical, not hostile or disturbing
- [ ] Hang-up moment feels narratively satisfying
- [ ] A real B1 user would find this motivating (not discouraging)
- [ ] Conversation rhythm feels natural (not robotic)
- [ ] Character replies are credible and varied (not repetitive)

## Verdict
- [ ] ✅ PASS — Scenario calibrated, ready for production
- [ ] ⚠️ ADJUST — Specific adjustments needed (detail below)
- [ ] ❌ REWORK — Fundamental issues, system prompt needs rewrite

## Adjustment Notes
_What to change and why:_
```

---

## 6. Minimum Test Coverage per Scenario

| Scenario | Difficulty | Pass A (Good B1) | Pass B (Struggling B1) | Status |
|----------|-----------|:-:|:-:|--------|
| The Waiter | easy | [ ] | [ ] | |
| The Mugger | medium | [ ] | [ ] | |
| The Girlfriend | medium | [ ] | [ ] | |
| The Cop | hard | [ ] | [ ] | |
| The Landlord | hard | [ ] | [ ] | |

A scenario is **production-ready** only when both passes produce a PASS verdict.

---

## 7. Timeline & Ownership

| Task | Owner | When | Blocks |
|------|-------|------|--------|
| Build `TranscriptLogger` FrameProcessor | Charlie (Dev) | Before Story 3.2 | Scenario calibration testing |
| Build `score_transcript.py` | Charlie (Dev) | Before Story 3.2 | Scenario calibration testing |
| Create `calibration-tests/` folder | Charlie (Dev) | With above | — |
| Run calibration tests per scenario | Walid | During Story 3.2 | Scenario sign-off |
| Review calibration results | Dana (QA) | After each scenario test | Production readiness |

---

## 8. Transition to Production (Epic 6+)

This manual testing process is **temporary for Epic 3**. The production equivalents are:

| Epic 3 (manual) | Production (Epic 6-7) |
|------------------|-----------------------|
| `TranscriptLogger` writes to `/tmp/*.json` | `TranscriptLogger` writes to database (`transcripts` table) |
| `score_transcript.py` run manually by Walid | `PostCallScorer` runs automatically after each call |
| Survival % calculated by scoring script | Survival % calculated by `PatienceTracker` in real-time |
| Checklist filled manually | Automated quality gates in CI/CD |

The manual process validates the **scoring prompt**, **difficulty presets**, and **scenario system prompts** — all of which carry forward unchanged into production.
