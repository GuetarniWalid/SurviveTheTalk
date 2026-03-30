# Story 1.2: Build Pipecat Voice Pipeline with Sarcastic Character

Status: review

## Story

As a user,
I want to speak to an AI character that responds with a sarcastic, impatient personality in real-time voice,
So that the core conversational AI experience is validated end-to-end on the server.

## Acceptance Criteria

1. **AC1 — Pipeline produces voiced responses with streaming overlap:**
   Given a Pipecat pipeline configured with Soniox v4 (STT), Qwen3.5 Flash via OpenRouter (LLM), and Cartesia Sonic 3 (TTS),
   When audio is streamed into the pipeline via LiveKit transport,
   Then the pipeline produces voiced responses with streaming overlap (LLM streams to TTS before full response is generated).

2. **AC2 — Sarcastic persona maintained across turns:**
   Given a hardcoded sarcastic character system prompt,
   When the user speaks in English across multiple conversation turns,
   Then the character maintains its sarcastic/impatient persona consistently without breaking character.

3. **AC3 — HTTP endpoint spawns bot into LiveKit room:**
   Given the pipeline is running on Hetzner VPS,
   When a minimal HTTP endpoint receives a call request,
   Then it creates a LiveKit room, spawns a Pipecat bot into that room, and returns the room token to the caller.

4. **AC4 — Process-and-discard audio enforced:**
   Given voice data enters the pipeline,
   When audio is processed by STT,
   Then raw audio is never written to disk (process-and-discard pattern enforced).

## Tasks / Subtasks

- [x] **Task 1: Create Pipecat voice pipeline module** (AC: #1, #4)
  - [x] 1.1 Create `server/pipeline/bot.py` with full pipeline: Soniox v4 STT → OpenRouter/Qwen3.5 Flash LLM → Cartesia Sonic 3 TTS, orchestrated by Pipecat with LiveKit transport
  - [x] 1.2 Configure `SileroVADAnalyzer` with VADParams (confidence=0.7, start_secs=0.2, stop_secs=0.3, min_volume=0.5)
  - [x] 1.3 Configure `LLMContextAggregatorPair` with `LLMUserAggregatorParams` passing the VAD analyzer
  - [x] 1.4 Set up barge-in handling via `MinWordsUserTurnStartStrategy(min_words=3, enable_interruptions=True)` to prevent "uh huh" from interrupting bot
  - [x] 1.5 Set `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)` for turn end detection
  - [x] 1.6 Wire event handlers: `on_first_participant_joined` (character speaks first greeting), `on_participant_left` (EndFrame cleanup)
  - [x] 1.7 Accept CLI args (--url, --room, --token) for subprocess spawning pattern
  - [x] 1.8 Verify zero `AudioBufferProcessor` usage — audio must never be written to disk

- [x] **Task 2: Create sarcastic character system prompt** (AC: #2)
  - [x] 2.1 Create `server/pipeline/prompts.py` with `SARCASTIC_CHARACTER_PROMPT` constant
  - [x] 2.2 Prompt must instruct: sarcastic/impatient personality, short spoken-friendly responses (≤256 tokens), react to grammar errors with mockery, escalate frustration on hesitations, stay in character at all times, speak English only
  - [x] 2.3 Set LLM `system_instruction` to this prompt, `temperature=0.7`, `max_completion_tokens=256`

- [x] **Task 3: Create HTTP endpoint for bot spawning** (AC: #3)
  - [x] 3.1 Create `server/api/call_endpoint.py` with FastAPI app containing a `POST /connect` endpoint
  - [x] 3.2 Endpoint generates a unique room name (`room-{uuid4}`)
  - [x] 3.3 Generate agent token via `pipecat.runner.livekit.generate_token_with_agent()` for the bot
  - [x] 3.4 Spawn `server/pipeline/bot.py` as subprocess with `--url`, `--room`, `--token` args
  - [x] 3.5 Generate user token via `pipecat.runner.livekit.generate_token()` for the client
  - [x] 3.6 Return JSON: `{"room_name": str, "token": str, "livekit_url": str}`
  - [x] 3.7 Add CORS middleware (allow all origins for PoC)
  - [x] 3.8 Load config from `Settings` (config.py) for LiveKit credentials

- [x] **Task 4: Update server entry point** (AC: #1, #3)
  - [x] 4.1 Replace placeholder `server/main.py` with uvicorn runner launching the FastAPI app on `0.0.0.0:8000`
  - [x] 4.2 Add `uvicorn` dependency to `pyproject.toml` (via `uv add uvicorn`)
  - [x] 4.3 Add `fastapi` dependency to `pyproject.toml` (via `uv add fastapi`)
  - [x] 4.4 Configure structured logging with loguru (already a pipecat dependency)

- [x] **Task 5: Select Cartesia voice** (AC: #1)
  - [x] 5.1 Research and select a male English Cartesia voice ID that supports sarcastic/expressive delivery
  - [x] 5.2 Store voice ID as a constant in `server/pipeline/bot.py` or `prompts.py`
  - [x] 5.3 Configure Cartesia with `model="sonic-3"`, `speed=1.0`

- [x] **Task 6: Write tests** (AC: #1, #2, #3, #4)
  - [x] 6.1 Test `Settings` class loads all required env vars for pipeline (extend existing `test_config.py`)
  - [x] 6.2 Test system prompt constant is non-empty and contains key persona instructions
  - [x] 6.3 Test `/connect` endpoint returns expected JSON schema (mock subprocess + token generation)
  - [x] 6.4 Test no `AudioBufferProcessor` import exists anywhere in pipeline code (grep-style assertion)
  - [x] 6.5 All tests pass with `pytest`

- [x] **Task 7: Deploy to Hetzner VPS** (AC: #3)
  - [x] 7.1 SSH to VPS, pull latest code
  - [x] 7.2 Install new dependencies (`uv sync`)
  - [x] 7.3 Update `deploy/pipecat.service` ExecStart to run `main.py` (now launches uvicorn)
  - [x] 7.4 Restart pipecat service, verify `/connect` endpoint responds
  - [x] 7.5 Verify pipeline spawns bot successfully when `/connect` is called (test with curl)

- [x] **Task 8: Run pre-commit validation** (AC: all)
  - [x] 8.1 `cd server && ruff check .` — zero issues
  - [x] 8.2 `cd server && ruff format --check .` — properly formatted
  - [x] 8.3 `cd server && pytest` — all tests pass

## Dev Notes

### Architecture Compliance

This story implements the **core voice pipeline** for the PoC, the most critical component of the entire project. [Source: architecture.md#Core Architectural Decisions]

**Pipeline stack (non-negotiable):**
- Soniox v4 (STT) → Qwen3.5 Flash via OpenRouter (LLM) → Cartesia Sonic 3 (TTS)
- Pipecat orchestration with LiveKit WebRTC transport
- Streaming overlap mandatory: LLM streams to TTS before full response is generated

**PoC scope constraints:**
- No FastAPI auth middleware (no JWT, no user accounts)
- No database access
- No Rive animation data channels (story 1.3+ scope)
- No scenario selection — single hardcoded sarcastic character
- The HTTP endpoint is minimal — no rate limiting, no error recovery beyond basic try/catch

### Critical Technical Specifications

**Pipecat v0.0.108 — Verified Import Paths:**

```python
# Transport
from pipecat.transports.livekit.transport import LiveKitTransport, LiveKitParams

# Pipeline
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask, PipelineParams

# Services
from pipecat.services.soniox.stt import SonioxSTTService
from pipecat.services.openrouter import OpenRouterLLMService
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig

# VAD
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams

# Context management
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)

# Turn strategies (NOT deprecated allow_interruptions)
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

# Frames
from pipecat.frames.frames import EndFrame, TTSSpeakFrame

# Token generation
from pipecat.runner.livekit import generate_token, generate_token_with_agent
```

**Pipeline construction pattern:**

```python
pipeline = Pipeline([
    transport.input(),       # Receives user audio from LiveKit
    stt,                     # Soniox v4 STT
    user_aggregator,         # Collects user responses into context
    llm,                     # OpenRouter/Qwen3.5 Flash
    tts,                     # Cartesia Sonic 3
    transport.output(),      # Sends audio back to LiveKit
    assistant_aggregator,    # Collects assistant responses into context
])
```

**Service configuration:**

| Service | Key Config |
|---------|-----------|
| `SonioxSTTService` | `model="stt-rt-v4"`, default `api_key` from env |
| `OpenRouterLLMService` | `model="qwen/qwen3.5-flash-02-23"`, `temperature=0.7`, `max_completion_tokens=256`, `system_instruction=SARCASTIC_CHARACTER_PROMPT` |
| `CartesiaTTSService` | `model="sonic-3"`, `voice="<selected-voice-id>"`, `speed=1.0` |

**Barge-in handling (v0.0.108 pattern):**
- `allow_interruptions` on PipelineParams is DEPRECATED
- Use `MinWordsUserTurnStartStrategy(min_words=3, enable_interruptions=True)` — requires 3+ words when bot is speaking to trigger interruption, single word suffices when bot is silent
- Use `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)` for turn end

**VAD configuration:**
- `SileroVADAnalyzer` with `stop_secs=0.3` (slightly longer than default 0.2 to avoid cutting pauses for non-native speakers)
- VAD analyzer passed to `LLMUserAggregatorParams`, NOT directly to transport

**LiveKit rooms are auto-created** when first participant joins — no explicit room creation API call needed.

**Bot spawning pattern:**
- FastAPI endpoint generates room name + tokens
- Bot spawned as `subprocess.Popen(["python3", "-m", "pipeline.bot", "--url", url, "--room", room, "--token", token])`
- User token returned to client for LiveKit connection

**Process-and-discard audio:**
- Pipecat does NOT record audio by default — frames flow through memory and are garbage-collected
- Do NOT import or use `AudioBufferProcessor`
- No temp files, no disk writes at any pipeline stage

### Sarcastic Character Prompt Guidelines

The system prompt must:
- Establish a sarcastic, impatient personality (think: annoyed game show host)
- Keep responses short (1-3 sentences) for natural spoken delivery
- React to grammar errors with mockery (in-character)
- Show increasing frustration with long pauses/hesitations
- Never break character or become helpful/encouraging
- Speak English only
- Stay within scenario boundaries (no offensive content beyond sarcasm)

Example prompt direction:
```
You are Marcus, a jaded game show host who's been doing this for 20 years
and is completely over it. You're sarcastic, impatient, and unimpressed by
everything. Keep responses to 1-3 short sentences. If the contestant
hesitates or makes grammar mistakes, mock them. Never be encouraging.
Never break character. Speak as if on a live TV show.
```

### File Structure

All new files go in `server/`:

```
server/
├── main.py                  # MODIFIED — uvicorn runner for FastAPI
├── config.py                # UNCHANGED — Settings class already has all keys
├── pyproject.toml            # MODIFIED — add fastapi, uvicorn deps
├── api/
│   └── call_endpoint.py     # NEW — FastAPI app with POST /connect
├── pipeline/
│   ├── bot.py               # NEW — Pipecat pipeline (STT→LLM→TTS)
│   └── prompts.py           # NEW — SARCASTIC_CHARACTER_PROMPT constant
└── tests/
    ├── test_config.py        # MODIFIED — add pipeline env var tests
    ├── test_prompts.py       # NEW — prompt validation tests
    └── test_call_endpoint.py # NEW — /connect endpoint tests
```

### What NOT to Do

- **DO NOT** use `allow_interruptions=True` on `PipelineParams` — it is deprecated in v0.0.108. Use `MinWordsUserTurnStartStrategy` instead
- **DO NOT** use `DataBind.byName()` anywhere — causes infinite hang (Rive rule, but enforced project-wide)
- **DO NOT** import or use `AudioBufferProcessor` — violates process-and-discard requirement
- **DO NOT** add auth middleware, JWT validation, or user accounts — PoC scope
- **DO NOT** add database access or migrations — no DB until MVP
- **DO NOT** create a separate `fastapi.service` systemd file — reuse `pipecat.service` with updated ExecStart
- **DO NOT** add Rive data channel messaging — that's Epic 6 scope
- **DO NOT** hardcode API keys — all from `Settings` / `.env`
- **DO NOT** use `RiveAnimation` or any Rive 0.13.x API — irrelevant for this story but noted for awareness
- **DO NOT** add `flask`, `django`, or any other web framework — FastAPI only
- **DO NOT** create the Flutter client call UI — that's story 1.3

### Pre-Commit Checks (Non-Negotiable)

```bash
cd server && ruff check .         # Must pass with zero issues
cd server && ruff format --check . # Must pass (properly formatted)
cd server && pytest               # Must pass (all tests)
```

### Previous Story Intelligence

**From Story 1.1 (Initialize Monorepo and Deploy Server Infrastructure):**

- VPS is at `167.235.63.129` (Hetzner CPX22, Nuremberg, Ubuntu 24.04)
- DNS/HTTPS deferred — no domain purchased yet. Test via IP only
- `pipecat.service` systemd unit already exists at `/opt/survive-the-talk/` — update ExecStart
- `.env` already populated on VPS with placeholder API keys — replace with real keys
- Python 3.12 + uv 0.11.2 installed on VPS
- `server/config.py` already uses `pydantic-settings` with all required env vars
- `server/tests/test_config.py` has 1 existing test (Settings class exists)
- Directory skeleton already exists: `server/pipeline/`, `server/api/`, `server/tests/`
- Pipecat 0.0.108 with extras `[soniox,openai,cartesia,livekit]` already in `pyproject.toml`
- Caddy reverse proxy configured to forward to `localhost:8000`

**Debug lessons from 1.1:**
- pytest exit code 5 when no tests collected — always have at least one test
- Ubuntu 24.04 uses `ssh` service name not `sshd`
- `.python-version` defaulted to 3.13 by uv init — already fixed to 3.12

### Git Intelligence

Recent commits:
```
5be3cea feat: initialize monorepo and deploy server infrastructure
fb5d310 feat: initialize project with complete BMAD planning artifacts
```

Patterns established:
- Commit format: `feat:` prefix + bulleted list body
- No Co-Authored-By lines
- Pre-commit validation enforced (flutter analyze + test, ruff + pytest)

### Library Versions (Verified March 2026)

| Library | Version | Notes |
|---------|---------|-------|
| pipecat-ai | ≥0.0.108 | With extras: soniox, openai, cartesia, livekit |
| FastAPI | latest | New dependency for this story |
| uvicorn | latest | New dependency for this story |
| pydantic-settings | ≥2.13.1 | Already installed |
| SileroVAD | bundled with pipecat | ONNX runtime, CPU-only |
| livekit (Python SDK) | bundled with pipecat[livekit] | For token generation |

### References

- [Source: architecture.md#Core Architectural Decisions] — Voice pipeline stack selection
- [Source: architecture.md#Infrastructure & Deployment] — VPS specs, systemd, Caddy config
- [Source: architecture.md#API & Communication Patterns] — REST via FastAPI, error format
- [Source: architecture.md#Phased Architecture Constraint] — PoC scope definition
- [Source: epics.md#Epic 1] — Epic context and kill gates
- [Source: epics.md#Story 1.2] — Story requirements and acceptance criteria
- [Source: prd.md#Phase 0 — Proof of Concept] — PoC validation gates
- [Source: 1-1-initialize-monorepo-and-deploy-server-infrastructure.md] — Previous story learnings and VPS details

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (claude-opus-4-6)

### Debug Log References

- Used `pipecat.services.openrouter.llm` import (non-deprecated path) instead of `pipecat.services.openrouter`
- Verified `enable_interruptions` exists in `BaseUserTurnStartStrategy.__init__` — passed via `**kwargs` from `MinWordsUserTurnStartStrategy`
- Used `max_tokens` (Settings field name) instead of `max_completion_tokens` (OpenAI API name) for `OpenRouterLLMService.Settings`
- Cartesia voice selected: Jace (`6776173b-fd72-460d-89b3-d85812ee518d`) — on Cartesia's emotion-recommended list for expressive male voices

### Completion Notes List

- ✅ Task 1: Created `server/pipeline/bot.py` with complete Pipecat pipeline (Soniox v4 STT → OpenRouter/Qwen3.5 Flash LLM → Cartesia Sonic 3 TTS), LiveKit transport, VAD config, barge-in handling, event handlers, CLI args
- ✅ Task 2: Created `server/pipeline/prompts.py` with `SARCASTIC_CHARACTER_PROMPT` (Marcus the jaded game show host) and `CARTESIA_VOICE_ID`
- ✅ Task 3: Created `server/api/call_endpoint.py` with FastAPI `POST /connect` endpoint — generates room, spawns bot subprocess, returns user token
- ✅ Task 4: Replaced placeholder `server/main.py` with uvicorn runner, added `fastapi==0.135.2` + `uvicorn==0.42.0` deps
- ✅ Task 5: Selected Cartesia voice Jace (`6776173b-fd72-460d-89b3-d85812ee518d`) — male, expressive, emotion-recommended
- ✅ Task 6: Wrote 10 tests across 4 test files — all passing
- ✅ Task 7: Deployed to Hetzner VPS — cloned repo, uv sync, updated pipecat.service, verified /connect returns JSON and bot spawns into LiveKit room
- ✅ Task 8: Pre-commit validation passed — ruff check (0 issues), ruff format (0 changes), pytest (10 passed)

### Implementation Plan

1. Created character prompt with sarcastic game show host persona (Marcus)
2. Built full Pipecat pipeline with streaming overlap (LLM→TTS streaming)
3. Configured barge-in: MinWordsUserTurnStartStrategy(min_words=3) prevents single-word interruptions during bot speech
4. Created FastAPI endpoint that spawns bot as subprocess per room
5. Added comprehensive test suite covering config, prompts, endpoint, and process-and-discard compliance

### File List

- `server/pipeline/bot.py` — NEW — Pipecat voice pipeline (STT→LLM→TTS with LiveKit)
- `server/pipeline/prompts.py` — NEW — Sarcastic character prompt + Cartesia voice ID
- `server/pipeline/__init__.py` — NEW — Package init
- `server/api/call_endpoint.py` — NEW — FastAPI POST /connect endpoint
- `server/api/__init__.py` — NEW — Package init
- `server/main.py` — MODIFIED — Uvicorn runner for FastAPI
- `server/pyproject.toml` — MODIFIED — Added fastapi, uvicorn dependencies
- `server/uv.lock` — MODIFIED — Lock file updated with new deps
- `server/tests/test_config.py` — MODIFIED — Added pipeline env var tests (3 tests total)
- `server/tests/test_prompts.py` — NEW — Prompt validation tests (4 tests)
- `server/tests/test_call_endpoint.py` — NEW — /connect endpoint tests (2 tests)
- `server/tests/test_no_audio_buffer.py` — NEW — Process-and-discard compliance test (1 test)
- `deploy/pipecat.service` — MODIFIED — Updated WorkingDirectory and ExecStart to repo path

## Change Log

- 2026-03-30: Implemented voice pipeline, character prompt, HTTP endpoint, tests (Tasks 1-6, 8). Deployed to VPS (Task 7) — all services connected and operational.
