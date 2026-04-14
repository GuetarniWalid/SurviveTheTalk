# Tech Debt from Epic 3 Code Review

Date: 2026-04-14
Source: Story 3.0 code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor)
Status: Active — must be addressed during Epic 6 and Epic 7 implementation

---

## D1. Transcripts written to `/tmp` with no access control

**Affects:** Epic 6 (TranscriptLogger production version)
**Current behavior:** Transcripts are written as plain JSON to `/tmp/transcript_{session_id}.json` with default file permissions. Any local process can read them.
**Required action:** Epic 6 TranscriptLogger must write to database (`transcripts` table), not filesystem. If file-based fallback is kept for debugging, use restrictive permissions (`0o600`) and a non-world-readable directory.

---

## D2. Character logger captures token-level TextFrame chunks, not complete utterances

**Affects:** Epic 6 (TranscriptLogger production version)
**Current behavior:** The LLM emits one `TextFrame` per streamed token. The character logger records each fragment as a separate transcript turn (e.g., "What", " do", " you", " want", "?"). The resulting transcript has dozens of micro-turns instead of complete character utterances.
**Impact:** Transcript is noisy but still functional for AI scoring (the scorer LLM can interpret fragmented text). However, production transcripts need clean, human-readable utterances.
**Required action:** Add a buffering/aggregation layer that collects `TextFrame` chunks and flushes a single transcript turn when the character finishes speaking (e.g., on the next non-TextFrame, or on a `TTSStartedFrame`/`LLMFullResponseEndFrame` boundary).

---

## D3. Race condition on shared TranscriptCollector state

**Affects:** Epic 6 (TranscriptLogger production version)
**Current behavior:** Two `TranscriptLogger` instances share a `TranscriptCollector` with mutable fields (`transcript` list, `_written` flag, `_first_timestamp`). No synchronization primitives. Safe only because the Pipecat pipeline processes frames serially on a single asyncio event loop.
**Required action:** If the production pipeline ever uses concurrent processing (e.g., `asyncio.gather`, parallel branches), add `asyncio.Lock` around `add_turn()`, `get_relative_timestamp_ms()`, and `write_transcript()`.

---

## D4. Transcript lost if pipeline crashes without EndFrame

**Affects:** Epic 6 (TranscriptLogger production version)
**Current behavior:** `write_transcript()` is only triggered by `EndFrame`. If the process is killed, the bot crashes, or the LiveKit connection drops without `on_participant_left` firing, the in-memory transcript is lost.
**Required action:** Add a safety net — either:
- An `atexit` handler that flushes the transcript on process exit
- A periodic flush (e.g., every 30s) writing a partial transcript to disk
- A signal handler for SIGTERM/SIGINT that triggers `write_transcript()`

---

## D5. Session ID uses second-precision timestamp — collision risk

**Affects:** Epic 6 (TranscriptLogger production version)
**Current behavior:** `session_id = f"call_{int(time.time())}"` — two calls starting in the same second produce the same session ID and overwrite each other's transcript file.
**Impact:** Zero risk for manual operator testing (one call at a time). Real risk in production with concurrent users.
**Required action:** Use `uuid.uuid4()` or at minimum `f"call_{int(time.time() * 1000)}"` (millisecond precision) for production session IDs. Ideally, use the LiveKit room/session ID as the transcript session ID for traceability.
