# Story 3.0: Build Scenario Calibration Testing Tools

Status: done

## UX Intention

These tools exist so Walid can test and calibrate each scenario's difficulty BEFORE users ever see it. Without them, Story 3.2 (Create Launch Scenarios) cannot validate that survival percentages land in the correct range. The tools are invisible to end users — they are operator-only infrastructure for the authoring workflow.

## Story

As an operator (Walid),
I want a transcript capture tool and an AI scoring script available on the VPS,
So that I can test scenarios, capture transcripts, and validate difficulty calibration before publishing.

## Acceptance Criteria

1. **Given** the Pipecat pipeline runs a voice call
   **When** the call completes (EndFrame)
   **Then** a JSON transcript file is written to `/tmp/transcript_{session_id}.json` containing all turns with `{role, text, timestamp_ms}` in chronological order

2. **Given** a transcript JSON file and scenario metadata
   **When** `score_transcript.py` is executed with the correct CLI arguments
   **Then** survival_pct is calculated using the formula `floor(successful_exchanges / expected_exchanges * 100)` capped at 100
   **And** the AI scoring prompt is called via OpenRouter
   **And** a formatted calibration report is printed to stdout
   **And** the full result is saved to `_bmad-output/implementation-artifacts/calibration-tests/`

3. **Given** the existing pipeline in `bot.py`
   **When** the TranscriptLogger is integrated
   **Then** two instances are inserted (one after STT for user speech, one after LLM for character speech) without modifying any existing frame processing or conversation latency

4. **Given** the testing tools are code
   **When** pre-commit checks are run
   **Then** `ruff check .` and `ruff format --check .` pass with zero issues
   **And** `pytest` passes with all tests green

## Tasks / Subtasks

- [x] Task 1: Create TranscriptLogger FrameProcessor (AC: #1, #3)
  - [x] Create `server/pipeline/transcript_logger.py`
  - [x] Implement `TranscriptLogger(FrameProcessor)` with `role` parameter ("user" or "character")
  - [x] Observe relevant frame types, record `{role, text, timestamp_ms}` per turn
  - [x] On `EndFrame`, write complete transcript JSON to `/tmp/transcript_{session_id}.json`
  - [x] Generate `session_id` from timestamp or UUID at pipeline init
- [x] Task 2: Integrate TranscriptLogger into pipeline (AC: #3)
  - [x] Insert user-speech instance after `stt` in pipeline list (line ~99 of bot.py)
  - [x] Insert character-speech instance after `llm` in pipeline list (line ~101 of bot.py)
  - [x] Verify passthrough behavior — frames must NOT be consumed or modified
- [x] Task 3: Create score_transcript.py CLI script (AC: #2)
  - [x] Create `server/scripts/` directory
  - [x] Create `server/scripts/score_transcript.py`
  - [x] Implement argparse CLI with required args (--transcript, --scenario-name, --difficulty, --expected-exchanges, --language-focus)
  - [x] Calculate survival_pct from transcript (count non-empty user turns excluding silence_timeout events)
  - [x] Call OpenRouter API with the AI scoring system prompt
  - [x] Parse JSON response and validate all required fields present
  - [x] Print formatted calibration report to stdout
  - [x] Save full result JSON to `_bmad-output/implementation-artifacts/calibration-tests/`
  - [x] Create `_bmad-output/implementation-artifacts/calibration-tests/` directory (gitkeep)
- [x] Task 4: Add httpx dependency (AC: #2)
  - [x] Add `httpx` to `[project].dependencies` in `server/pyproject.toml`
  - [x] Run `uv sync` to update lockfile
- [x] Task 5: Write tests (AC: #4)
  - [x] Unit tests for TranscriptLogger (frame observation, JSON output structure, passthrough behavior)
  - [x] Unit tests for score_transcript.py (survival_pct calculation, JSON parsing, report formatting — mock OpenRouter)
- [x] Task 6: Pre-commit validation (AC: #4)
  - [x] `ruff check .` passes
  - [x] `ruff format --check .` passes
  - [x] `pytest` passes — ALL tests (existing + new)

## Dev Notes

### Story Type: Python Server Code (No Flutter)

This story only touches the `server/` directory. No Flutter code. Pre-commit is Python-only:

```bash
cd server && python -m ruff check .
cd server && python -m ruff format --check .
cd server && python -m pytest
```

### TranscriptLogger — Implementation Spec

**Source spec:** [`scenario-testing-process.md`](../planning-artifacts/scenario-testing-process.md) §3.1

**What it is:** A Pipecat `FrameProcessor` that observes speech frames and writes a JSON transcript file. It is a passthrough processor — it does NOT consume, modify, or block any frame. Zero impact on conversation latency.

**Constructor parameters:**
- `role: str` — either `"user"` or `"character"`, determines which frame types to observe
- `session_id: str` — unique ID for the transcript file, generated at pipeline init

**Shared state:** Both instances (user + character) must write to the SAME transcript list to produce one chronological file. Use a shared `TranscriptCollector` object (a simple dataclass/dict) that both instances reference. Pass it as a constructor parameter.

**Frame types to observe:**

| Instance | Role | Frame Types | Import From |
|----------|------|-------------|-------------|
| After STT | `"user"` | `TranscriptionFrame` | `pipecat.frames.frames` |
| After LLM | `"character"` | `TextFrame` | `pipecat.frames.frames` |

**Important:** Check Pipecat's actual frame class names in the installed version. The imports in `bot.py` already use `from pipecat.frames.frames import EndFrame, TTSSpeakFrame`. Verify `TranscriptionFrame` and `TextFrame` exist in that module — if not, search for the correct frame classes (e.g., `STTFrame`, `LLMTextFrame`, etc.). Pipecat is at version >=0.0.108 (see pyproject.toml).

**Timestamp:** Use `time.time()` converted to integer milliseconds, relative to the first frame (first frame = timestamp 0).

**Output JSON format:**

```json
{
  "session_id": "abc123",
  "started_at": "2026-04-15T14:30:00Z",
  "ended_at": "2026-04-15T14:31:47Z",
  "duration_seconds": 107,
  "transcript": [
    {"role": "character", "text": "Oh great, another one.", "timestamp_ms": 0},
    {"role": "user", "text": "Hello, I want to order", "timestamp_ms": 3200},
    {"role": "character", "text": "What do you want?", "timestamp_ms": 5100}
  ]
}
```

**EndFrame handling:** When either instance receives an `EndFrame`, the shared collector writes the transcript to `/tmp/transcript_{session_id}.json`. Use a flag to prevent double-write (both instances will see EndFrame).

**Pipeline insertion (bot.py lines 96-106):**

Current pipeline:
```python
pipeline = Pipeline(
    [
        transport.input(),    # 0
        stt,                  # 1
        context_aggregator.user(),  # 2
        llm,                  # 3
        tts,                  # 4
        transport.output(),   # 5
        context_aggregator.assistant(),  # 6
    ]
)
```

Target pipeline:
```python
pipeline = Pipeline(
    [
        transport.input(),
        stt,
        transcript_user,      # NEW — captures user speech
        context_aggregator.user(),
        llm,
        transcript_character,  # NEW — captures character speech
        tts,
        transport.output(),
        context_aggregator.assistant(),
    ]
)
```

**Initialization in bot.py** (before pipeline construction):
```python
from pipeline.transcript_logger import TranscriptCollector, TranscriptLogger

collector = TranscriptCollector(session_id=f"call_{int(time.time())}")
transcript_user = TranscriptLogger(collector=collector, role="user")
transcript_character = TranscriptLogger(collector=collector, role="character")
```

### score_transcript.py — Implementation Spec

**Source spec:** [`scenario-testing-process.md`](../planning-artifacts/scenario-testing-process.md) §3.2

**CLI interface:**

```bash
python scripts/score_transcript.py \
  --transcript /tmp/transcript_abc123.json \
  --scenario-name "The Waiter" \
  --difficulty easy \
  --expected-exchanges 6 \
  --language-focus "ordering food,polite requests,food adjectives"
```

**Survival % calculation** (from [`difficulty-calibration.md`](../planning-artifacts/difficulty-calibration.md) §3.3):

```python
# Count successful exchanges:
# - A user turn with non-empty text AND no "silence_timeout" event = 1 successful exchange
# - A user turn with empty text or event="silence_timeout" = failed exchange
successful = sum(
    1 for t in transcript
    if t["role"] == "user" and t.get("text", "").strip() and t.get("event") != "silence_timeout"
)
survival_pct = min(100, successful * 100 // expected_exchanges)
```

**AI scoring prompt:** Use the EXACT system prompt from [`difficulty-calibration.md`](../planning-artifacts/difficulty-calibration.md) §5.3. Do NOT modify or paraphrase it.

**OpenRouter API call:**
- Endpoint: `https://openrouter.ai/api/v1/chat/completions`
- Model: `qwen/qwen3-235b-a22b` (analytical model, not the fast in-call model)
- API key: read from `OPENROUTER_API_KEY` env var, or from `.env` file in server root (use `python-dotenv` or manual parsing — the key already exists in `.env` on the VPS)
- Use `httpx` (NOT `openai` SDK) for this standalone script — keep it minimal
- Request the LLM to return JSON only (set `response_format` if supported, or rely on the prompt instruction)
- Add `"reasoning": {"enabled": false}` in `extra_body` (same as bot.py does for Qwen) to suppress thinking tokens

**Output schema validation:** The LLM response MUST contain these top-level keys: `language_errors`, `hesitations`, `idioms_encountered`, `areas_to_work_on`, `call_summary`. Log a warning and continue if any key is missing — do not crash.

**Formatted report (stdout):**

```
═══════════════════════════════════════════════════
 CALIBRATION REPORT — {scenario_name} ({difficulty})
═══════════════════════════════════════════════════
 Survival: {pct}% (target: {range}) {status}
 Exchanges: {successful}/{expected} successful
 Duration: {duration}s
 Hang-up reason: {last event or "completed"}

 Language errors found: {count}
 Hesitations found: {count}
 Idioms encountered: {count}
 Areas to work on: {count}

 Debrief quality: {ALL FIELDS PRESENT or MISSING: list}
═══════════════════════════════════════════════════
```

Target survival ranges for the `{status}` field:
- easy: 60-80% → IN RANGE / TOO LOW / TOO HIGH
- medium: 35-55% → same
- hard: 15-35% → same

**Result file:** Save to `_bmad-output/implementation-artifacts/calibration-tests/{scenario_name}_{difficulty}_{timestamp}.json` containing the full input + output + survival_pct + target_range + status.

### Dependencies

**Add to `server/pyproject.toml`** under `[project].dependencies`:
- `httpx` — for OpenRouter API calls in score_transcript.py

Do NOT add `python-dotenv` — parse `.env` manually or use `os.environ.get()` (the VPS has the env var set via systemd). The script should work with just the env var.

### Test Strategy

**TranscriptLogger tests** (`server/tests/test_transcript_logger.py`):
- Test that the processor passes frames through unmodified (passthrough behavior)
- Test that transcript entries are collected with correct role and text
- Test that JSON file is written on EndFrame with correct schema
- Test that duplicate EndFrame doesn't cause double-write
- Do NOT test with real Pipecat pipeline — test the class methods directly with mock frames

**score_transcript tests** (`server/tests/test_score_transcript.py`):
- Test survival_pct calculation with various inputs (0 successful, all successful, partial)
- Test survival_pct caps at 100
- Test CLI argument parsing
- Test report formatting
- Mock the OpenRouter HTTP call — do NOT make real API calls in tests
- Test handling of missing keys in LLM response (graceful degradation)

### What NOT to Do

1. **Do NOT build a PatienceTracker** — that's Epic 6 scope. The TranscriptLogger only records; it does not evaluate exchange success or manage patience state
2. **Do NOT build an automatic PostCallScorer** — that's Epic 7 scope. score_transcript.py is a manual CLI tool
3. **Do NOT write transcripts to database** — write to `/tmp/` files only. Database persistence is Epic 6
4. **Do NOT modify the system prompt, LLM behavior, or TTS configuration** — the pipeline behavior stays identical
5. **Do NOT add Flutter/Dart code or modify anything in `client/`**
6. **Do NOT install the `openai` package for score_transcript.py** — use raw `httpx` calls to keep it minimal
7. **Do NOT add `python-dotenv` dependency** — use `os.environ.get()` for the API key

### Project Structure Notes

**New files:**
```
server/
  pipeline/
    transcript_logger.py    # NEW — TranscriptCollector + TranscriptLogger
  scripts/
    score_transcript.py     # NEW — CLI scoring tool (new directory)
  tests/
    test_transcript_logger.py  # NEW
    test_score_transcript.py   # NEW
```

**Modified files:**
```
server/
  pipeline/bot.py           # MODIFIED — insert 2 TranscriptLogger instances
  pyproject.toml            # MODIFIED — add httpx dependency
```

**New directories:**
```
server/scripts/                                          # NEW
_bmad-output/implementation-artifacts/calibration-tests/  # NEW (with .gitkeep)
```

### Existing Code Context

**bot.py pipeline (lines 96-106):** The pipeline is a linear list of processors. Insert TranscriptLogger instances as shown in the pipeline insertion section above. Import `time` at the top of bot.py for session_id generation.

**config.py:** `Settings` class loads `OPENROUTER_API_KEY` from `.env`. The score_transcript.py script is standalone — it does NOT use the Settings class. It reads the API key directly from `os.environ.get("OPENROUTER_API_KEY")`.

**pyproject.toml:** Current dependencies at lines 6-10. Add `httpx` to the list. Dev dependencies (pytest, ruff) are in `[dependency-groups].dev`.

**Existing tests:** 4 test files exist. The new tests must coexist — run `pytest` without arguments to verify ALL tests pass (existing + new).

### References

- [Source: _bmad-output/planning-artifacts/scenario-testing-process.md — §3.1 TranscriptLogger spec, §3.2 score_transcript.py spec]
- [Source: _bmad-output/planning-artifacts/difficulty-calibration.md — §3.3 survival formula, §5.3 AI scoring prompt, §5.4 output schema]
- [Source: server/pipeline/bot.py — existing pipeline structure, frame imports]
- [Source: server/config.py — Settings class, env var loading]
- [Source: server/pyproject.toml — current dependencies]
- [Source: _bmad-output/implementation-artifacts/epic-2-retro-2026-04-14.md — Epic 3 preparation tasks confirming these tools are needed]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (claude-opus-4-6)

### Debug Log References

- Verified Pipecat frame classes: `TranscriptionFrame`, `TextFrame`, `EndFrame` all exist in `pipecat.frames.frames` (v0.0.108)
- `TranscriptionFrame` inherits from `TextFrame` — character logger uses `isinstance(frame, TextFrame) and not isinstance(frame, TranscriptionFrame)` to avoid capturing user speech
- `TranscriptionFrame` has `finalized` boolean — only finalized transcriptions are recorded (partial/interim results skipped)

### Completion Notes List

- TranscriptCollector dataclass with shared transcript list, relative timestamps (first frame = 0), and double-write prevention flag
- TranscriptLogger FrameProcessor: pure passthrough, observes TranscriptionFrame (user) or TextFrame (character), writes JSON on EndFrame
- Pipeline integration: transcript_user after STT, transcript_character after LLM — zero latency impact
- score_transcript.py CLI: argparse with 5 required args, survival_pct formula matching spec exactly, OpenRouter API call with Qwen3-235b-a22b, formatted calibration report, result file saving
- AI scoring prompt copied verbatim from difficulty-calibration.md §5.3
- 44 new tests (17 TranscriptLogger + 27 score_transcript), 54 total passing (10 existing + 44 new)
- All pre-commit checks pass: ruff check, ruff format, pytest

### Change Log

- 2026-04-14: Implemented all 6 tasks for Story 3.0 — TranscriptLogger, pipeline integration, score_transcript.py CLI, httpx dependency, tests, pre-commit validation

### File List

**New files:**
- `server/pipeline/transcript_logger.py` — TranscriptCollector + TranscriptLogger classes
- `server/scripts/score_transcript.py` — CLI scoring tool
- `server/tests/test_transcript_logger.py` — 17 unit tests
- `server/tests/test_score_transcript.py` — 27 unit tests
- `_bmad-output/implementation-artifacts/calibration-tests/.gitkeep` — calibration output directory

**Modified files:**
- `server/pipeline/bot.py` — Added TranscriptLogger integration (import, collector init, 2 logger instances in pipeline)
- `server/pyproject.toml` — Added httpx dependency
