# Story 6.24: TTS connection warm-up (kill the first-utterance Cartesia cold-start)

Status: done

> **Bug-surfaced story (2026-06-05).** During the Story 6.20 smoke testing, call_id=226 opened with **total silence**: the canned opening line was sent to Cartesia but Cartesia returned NO audio for 5 s → the Story 6.13 TTS watchdog fired (`cartesia_tts_watchdog_fired reason=no_audio_within_5.0s`) → the user heard nothing and hung up. Even when it does not fully stall, the FIRST utterance is noticeably slow. Cartesia's API was confirmed up at the time (`GET /voices` = 200), so this is the classic **first-synthesis cold-start** (sonic-3 model + voice load + edge routing) paid on the opening line. There is already an **LLM** warm-up (`pipeline/llm_warmup.py`) that kills the turn-1 LLM cold-start; this story adds the symmetric **TTS** warm-up. Design + API verified via a research/verify workflow (the warm-up replays pipecat's own `CartesiaHttpTTSService.run_tts` call, every param checked against the live Cartesia docs).

## Story

As the learner,
I want the character to start speaking **immediately and without stalling** when the call connects —
so the very first line (the greeting) lands fast like every later turn, instead of arriving late or as dead air.

(Maintainer angle: I want the TTS provider connection + model/voice warmed at call start, mirroring the existing LLM warm-up, so the opening `TTSSpeakFrame` never pays the cold-start.)

## Background

The opening line is delivered as a canned `TTSSpeakFrame` (`bot.py::on_first_participant_joined` → `task.queue_frames([TTSSpeakFrame(opening_line)])`). That is the **first** synthesis request of the call, so it pays the full Cartesia cold-start: the provider must load the `sonic-3` model + the specific voice UUID and route the edge for our key on the first inference. On a cold edge this can take ~5 s — long enough to trip the 5 s `TTSWatchdog` and emit total silence (call_id=226).

The pipecat `CartesiaTTSService` opens its WebSocket on the `StartFrame` (pipeline start), so the socket handshake is **not** the cold part — the **first model+voice inference** is. A provider-side warm-up (a throwaway one-shot synthesis to Cartesia's REST `/tts/bytes` endpoint with the same model + voice) pre-loads exactly that, so the real opening-line WS send a few seconds later hits a hot model. This is the same accepted pattern as `llm_warmup.py` (warms provider-side model/connection, not pipecat's own socket — the documented, accepted win).

## Design Decisions (RESOLVED 2026-06-05 via research+verify workflow)

- **D1 — mechanism.** Fire ONE throwaway HTTP `POST https://api.cartesia.ai/tts/bytes` (one-shot synthesis) at call start, fire-and-forget, mirroring `llm_warmup.py`. NOT a second WebSocket (Cartesia confirmed multi-context choking; a duplicate warm-up WS could collide with the real one). The HTTP ping and the real WS share the server-side model+voice, so it warms the cold part.
- **D2 — exact call.** Replay pipecat's own `CartesiaHttpTTSService.run_tts`: headers `Cartesia-Version: 2026-03-01` (the REST surface version — intentionally different from the WS path's `2025-04-16`; both hit the same model backend) + `X-API-Key` + `Content-Type: application/json`; body `{model_id: "sonic-3", transcript: "Hi.", voice: {mode: "id", id: <resolved_voice>}, output_format: {container: "raw", encoding: "pcm_s16le", sample_rate: 24000}}`.
- **D3 — voice drift killed structurally.** Extract a single `resolve_cartesia_voice(voice_id)` helper in `tts_factory.py` (`return voice_id or CARTESIA_VOICE_ID`) used by BOTH `_build_cartesia` AND the warm-up wiring, so the warmed voice is ALWAYS the spoken voice.
- **D4 — provider-gated.** Only fire for `tts_provider == "cartesia"` (the launch default + the one that stalls). ElevenLabs (last-resort fallback, ~75 ms TTFA) is skipped in v1; a follow-up branch can warm it.
- **D5 — never-raise, own client, 8 s timeout.** A warm-up failure must NEVER break a paid call (logged DEBUG + swallowed). 8 s (vs the LLM warm-up's 5 s) because a cold sonic-3 synthesis is exactly the multi-second op being paid down. Registered in `_BACKGROUND_TASKS` so it can't be GC'd mid-flight; never awaited in the call path.
- **D6 — kill switch.** `TTS_WARMUP_ENABLED` (default True) env toggle, matching the project's env-knob convention (the throwaway synthesis costs a tiny bit of Cartesia quota per call).
- **Relationship to the watchdog.** The warm-up REDUCES the cold-stall rate; it does NOT replace the `TTSWatchdog` (the 5 s safety net stays). Warm-up is best-effort, not a guarantee.

## Acceptance Criteria (BDD)

### AC1 — Warm-up fires at call start (Cartesia)
Given `tts_provider == "cartesia"`, when the bot session starts, then a fire-and-forget task POSTs one throwaway synthesis to `https://api.cartesia.ai/tts/bytes` with `model_id=sonic-3` + the **resolved** scenario voice, in parallel with the LLM warm-up + LiveKit connect.

### AC2 — Right voice warmed (no drift)
Given a scenario with a custom `metadata.tts_voice_id`, when the warm-up fires, then it warms THAT voice (the same one `build_tts_service` will speak with) — both resolved through the single `resolve_cartesia_voice` helper.

### AC3 — Never breaks the call
Given the warm-up POST fails (connect error / timeout / non-2xx / any exception), then `warm_up_tts_cartesia` returns without raising; the call proceeds normally and the `TTSWatchdog` remains the safety net.

### AC4 — Provider-gated + kill switch
Given `tts_provider == "elevenlabs"` OR `TTS_WARMUP_ENABLED=0`, then NO Cartesia warm-up task is created.

### AC5 — No regression
Given the warm-up is additive + fire-and-forget, then the pipeline, the LLM warm-up, and the existing TTS path are unchanged; the warm-up is never awaited in the call path.

### AC6 — Pre-commit gates
Server: `ruff check . && ruff format --check . && pytest` green (incl. the new `test_tts_warmup.py`). Client untouched.

### AC7 — Smoke gate (device)
On a fresh call right after a deploy, the opening line speaks **promptly with no dead-air stall**; `journalctl | grep tts_warmup` shows the warm-up fired; no `cartesia_tts_watchdog_fired` on the opening line. See `## Smoke Test Gate`.

## Tasks / Subtasks

- [x] **T1 — Voice resolve helper.** Added `resolve_cartesia_voice(voice_id: str | None) -> str` to `tts_factory.py`; `_build_cartesia` now uses it.
- [x] **T2 — Warm-up module.** Added `pipeline/tts_warmup.py` with `async def warm_up_tts_cartesia(*, api_key, model, voice_id)` — POST `/tts/bytes` (D2 payload), own `httpx.AsyncClient(timeout=8.0)`, never raises, INFO on success / DEBUG on failure (mirrors `llm_warmup.py`).
- [x] **T3 — Config toggle.** Added `tts_warmup_enabled: bool = True` (`TTS_WARMUP_ENABLED`) to `config.py`.
- [x] **T4 — Wire in bot.py.** After `tts = build_tts_service(...)`, gated on `tts_warmup_enabled and tts_provider == "cartesia"`, creates the warm-up task (resolved voice via the helper), registered in `_BACKGROUND_TASKS`.
- [x] **T5 — Tests.** `tests/test_tts_warmup.py` mirrors `test_llm_warmup.py` (`_CapturingClient`): correct URL/headers/body, resolved/custom voice lands in body, 8 s timeout, ConnectError/Timeout/generic all swallowed (6 tests).
- [x] **T6 — Gates (AC6); smoke gate (AC7) reserved for Walid's device.**

## Dev Notes

**Code references:**
- `pipeline/llm_warmup.py` — the exact pattern to mirror (own httpx client, never-raise, fire-and-forget).
- `pipeline/tts_factory.py` — `_build_cartesia` (voice resolve at ~`:141`, `CARTESIA_VOICE_ID` import); the new helper goes here.
- `pipeline/bot.py` — LLM warm-up wiring (`:263-271`), `tts = build_tts_service(...)` (`:284`), `_BACKGROUND_TASKS` (`:76`, `:270-271`), opening line `TTSSpeakFrame` (`:658`). Fire the TTS warm-up right after `:284`.
- pipecat `CartesiaHttpTTSService.run_tts` (`.venv/.../pipecat/services/cartesia/tts.py`) — the warm-up replays its `/tts/bytes` call shape (verified against live Cartesia docs: `Cartesia-Version: 2026-03-01`, `model_id: sonic-3`).

**Reuse / do-not-reinvent:**
- `resolve_cartesia_voice` is the single source of truth for the voice default — both the factory and the warm-up call it (kills voice drift by construction).
- `sample_rate: 24000` is hardcoded: non-load-bearing for warm-up (model+voice load dominates; sample_rate only affects transcode) and matches the LiveKit WS path default anyway.

**Gotchas:**
- `Cartesia-Version` for `/tts/bytes` is `2026-03-01` — do NOT "fix" it to the WS path's `2025-04-16`; they are independently-versioned API surfaces hitting the same backend.
- Warm-up must NOT be awaited in the call path; it's fire-and-forget and best-effort. The `TTSWatchdog` stays the real safety net.

### Project Structure Notes
- Server-only, no DB migration, client untouched. Not in `epics.md` — bug-surfaced story (same path as 6.18–6.23).

## Smoke Test Gate (Server / Deploy Story)

**Outcome — 2026-06-05, Pixel 9, calls 230 & 231 (deployed `git_sha bca3331`):** the TTS warm-up is VALIDATED working — `tts_warmup: cartesia warmed` fired on BOTH calls (and, post-review-fix, that line only logs on HTTP 200, so it proves a *real* warm-up, not a phantom), the per-scenario **resolved voice** was warmed (two different voice UUIDs across the two scenarios → AC2 confirmed in the wild), TTS first-audio was **~150 ms** after synth-start (hot model), and there was **ZERO `cartesia_tts_watchdog_fired`** — the call_id=226 stall this story targets is dead. ✅ **Story goal met.** **However**, Walid still perceived a blank on the opening line: the call-230 timeline shows it is the per-call bot-subprocess **cold boot** (~4.7 s spawn→first pipeline work) + ~1.4 s transport connect, NOT the TTS (150 ms). That opening-latency cause is out of 6.24's scope → spun off as **Story 6.26 (opening-latency / bot pre-warm)**.

- [x] **Deployed** to the VPS (`git_sha bca3331` confirmed via `/health`).
- [x] **Prompt opening line — TTS half:** `tts_warmup` fired + **NO** `cartesia_tts_watchdog_fired` on the opening line (server proof on calls 230/231). _Perceived promptness is bounded by bot cold-boot, not the TTS → Story 6.26._
- [x] **No regression:** both calls behaved normally (LLM warm-up logged; clean `reason=user_hung_up`; no `cartesia_ws_error`).
- [x] **Server logs clean** on the happy path.

## Dev Agent Record

### Agent Model Used
claude-opus-4-8 (`/bmad-dev-story`, ultracode — research+verify design workflow then implement)

### Debug Log References
- Server gates: `ruff check .` clean, `ruff format --check .` clean, full `pytest` **636 passed** (was 630; +6 `test_tts_warmup.py`).

### Completion Notes List
- `warm_up_tts_cartesia` mirrors `llm_warmup.warm_up_llm` exactly: own short-lived `httpx.AsyncClient(timeout=8.0)`, fire-and-forget, **never raises** (DEBUG-logs + swallows every exception). Replays pipecat's own `CartesiaHttpTTSService.run_tts` call — `POST https://api.cartesia.ai/tts/bytes`, `Cartesia-Version: 2026-03-01`, `X-API-Key`, body `{model_id: sonic-3, transcript: "Hi.", voice: {mode:id, id:<resolved>}, output_format: {raw/pcm_s16le/24000}}`.
- **Voice drift killed structurally:** `resolve_cartesia_voice(voice_id)` in `tts_factory.py` is the single default-resolver, called by BOTH `_build_cartesia` and the bot.py warm-up wiring → warmed voice == spoken voice by construction.
- **Provider-gated + kill switch:** the warm-up task is created only when `settings.tts_warmup_enabled and settings.tts_provider == "cartesia"`; registered in `_BACKGROUND_TASKS` (anti-GC), never awaited in the call path. ElevenLabs intentionally not warmed (fallback, ~75 ms TTFA).
- **Relationship to the watchdog:** reduces the cold-stall rate; the 5 s `TTSWatchdog` stays the real safety net (warm-up is best-effort, not a guarantee).
- **Process (ultracode):** a research+verify workflow confirmed the exact Cartesia `/tts/bytes` API against the live docs + pipecat source and judged the approach `sound=True, will_actually_help=True` (not cargo-cult — WS opens on StartFrame, so the cold cost is the first model+voice inference, which the HTTP ping pre-loads; both paths share the server-side model+voice).

### File List
- `server/pipeline/tts_warmup.py` — NEW: `warm_up_tts_cartesia` (the warm-up ping).
- `server/pipeline/tts_factory.py` — NEW `resolve_cartesia_voice` helper; `_build_cartesia` uses it.
- `server/config.py` — NEW `tts_warmup_enabled` (`TTS_WARMUP_ENABLED`) toggle.
- `server/pipeline/bot.py` — import + fire the warm-up task after `build_tts_service` (provider-gated, anti-GC).
- `server/tests/test_tts_warmup.py` — NEW: 6 tests (payload/headers, resolved voice, 8 s timeout, never-raise ×3).

## Review Findings

_Code review 2026-06-05 (`/bmad-code-review`, ultracode — 3 adversarial layers + per-finding adversarial verification). **Blind Hunter: 0 findings. Acceptance Auditor: 0 findings** (all of AC1–AC7 + D1–D6 honored). **Edge-Case Hunter: 2 findings**, both confirmed real-but-minor by the verifier (the first was raised as `high` and downgraded to `low`: its "AC7 false-pass" claim was refuted — AC7's load-bearing signals are device-side, i.e. prompt opening line + no `cartesia_tts_watchdog_fired`, independent of the INFO log line). No `decision-needed`, no `defer`, no `dismiss`._

- [x] [Review][Patch] Warm-up logs INFO `tts_warmup: cartesia warmed` even on a non-2xx response (401/429/5xx) — `httpx` `client.post()` does not raise on 4xx/5xx and the response is discarded, so a swallowed 401/429 prints "warmed" while nothing was warmed and the `except` DEBUG line never fires. Low: never breaks the call (by-design per AC3, mirrors `llm_warmup.py`), but it's a false-success breadcrumb and the smoke gate greps this very line. Fix: inspect `response.status_code` (or `raise_for_status()`); only log "warmed" on 2xx, log non-2xx at WARNING with the status. [server/pipeline/tts_warmup.py:83-90]
  - **✅ Fixed 2026-06-05:** status check added — success log gated on HTTP 200; non-2xx now logs WARNING with the status; +1 regression test (`test_warmup_non_2xx_does_not_claim_warmed`).
- [x] [Review][Patch] Cartesia model `"sonic-3"` is a duplicated hardcoded literal — warmed (`bot.py:301`) vs spoken (`tts_factory.py:162`) — with no shared constant. Identical today (no current misbehavior), but it's the exact drift class D3 eliminated for the *voice* via the single `resolve_cartesia_voice` helper, left open for the model. If a maintainer later changes the spoken model and forgets the warm-up arg, the warm-up silently primes the wrong model and the turn-1 cold-start returns with no error. Fix: a single source of truth for the model (a `resolve_cartesia_model()` helper or a module constant) consumed by both paths, mirroring the voice resolver. [server/pipeline/bot.py:301 + server/pipeline/tts_factory.py:162]
  - **✅ Fixed 2026-06-05:** introduced a `CARTESIA_MODEL` constant in `tts_factory.py` as the single source of truth; both `_build_cartesia` and the `bot.py` warm-up now consume it (warmed model == spoken model by construction).

## Change Log
- 2026-06-05 — **Smoke gate run (Pixel 9, calls 230/231) → `review` → `done`.** TTS warm-up validated server-side (fired both calls, first-audio ~150 ms = hot, ZERO watchdog fire — the call_id=226 stall is dead; AC2 per-scenario voice confirmed live). Walid still heard an opening blank → diagnosed as the per-call bot-subprocess cold-boot (~4.7 s) + transport connect (~1.4 s), NOT the TTS (150 ms) → spun off as **Story 6.26 (opening-latency / bot pre-warm)**. 6.24 flipped `done` on its TTS merit. Review fixes live at `git_sha bca3331`.
- 2026-06-05 — `/bmad-code-review` (ultracode). Adversarial multi-layer review: Blind Hunter 0, Acceptance Auditor 0, Edge-Case Hunter 2 (both `low` after verification) → 2 `patch` findings both APPLIED in the same pass (non-2xx false-success log now gated on HTTP 200 + WARNING; duplicated `sonic-3` literal replaced by a shared `CARTESIA_MODEL` constant). Gates re-run green: ruff clean, `pytest 637` (+1 regression test). Code-review-complete; awaiting ONLY the Pixel 9 smoke gate for `review → done`.
- 2026-06-05 — `/bmad-dev-story` implementation (ultracode). Added the Cartesia TTS warm-up (symmetric to the existing LLM warm-up) + `resolve_cartesia_voice` single-source voice resolver + `TTS_WARMUP_ENABLED` toggle. Gates green: ruff + `pytest 636`. Status → review; Pixel 9 smoke gate (prompt opening line, no `cartesia_tts_watchdog_fired`) reserved for Walid.
- 2026-06-05 — Drafted (bug-surfaced from Story 6.20 smoke call_id=226 silent opening). Design + Cartesia `/tts/bytes` API verified via a research+verify workflow; mirrors `llm_warmup.py`. Ready for `/bmad-dev-story`.
