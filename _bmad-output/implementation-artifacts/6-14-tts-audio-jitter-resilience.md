# Story 6.14: TTS Audio Jitter Resilience + Cartesia Re-evaluation

Status: ready-for-dev

## Story

As a user on a real-world mobile connection (4G/5G/Wi-Fi with jitter),
I want the character's voice to **play smoothly without stretching or slowing down**,
so that the conversation feels natural and the app is launch-ready (the stretched/"rallongée" voice currently recurs often enough that it is a stop-ship problem).

## Background

**This is a recurring, launch-blocking problem.** Across multiple smoke tests (2026-05-27 → 2026-05-30) Tina's voice intermittently **stretches / slows down** ("les voix se sont rallongées", "syllabes à rallonge"). Walid 2026-05-30: *"ça revient tellement régulièrement, je n'imagine même pas lancer un produit dans une telle façon."*

**Root cause (diagnosed 2026-05-30, call_id=198):** it is **network jitter**, not the server and not the number of voices.
- Server logs for the affected call were **clean**: 0 TTS context churn (`Ignoring message from unavailable context`), 0 errors/tracebacks, 0 watchdog stalls, 7 normal bot turns. The pipeline behaved correctly.
- `DTLN_ENABLED=0` (the Story 6.13 A/B kill-switch) **has never changed the stretching** in prior tests → rules out the "DTLN ONNX inference starves the audio sender on the 2-core VPS" server-pacing hypothesis.
- That leaves the **client-side WebRTC playout** as the cause. When RTP audio packets arrive in irregular bursts (jitter), the receiver's NetEq engine **time-stretches** the audio to fill the gaps → the "rallongée" effect. The server can't see this in its logs (it's a receiver-side artifact).

**Why it feels worse than Cartesia.** ElevenLabs Flash v2.5 sends **larger audio frames** than Cartesia did; larger frames give the jitter buffer less to interleave, so a jittery link stretches them more. Walid's intuition ("I didn't have this with Cartesia") is consistent with this — Cartesia's smaller frames were more jitter-tolerant.

**Cartesia support reply (2026-05-28, Ege Tinmaz — full thread in Walid's Gmail, subject "Sonic-3 streaming WebSocket — multi-sentence requests stall then return type=error after 30s"):**
- The 2026-05-26 freeze ("30 % of calls" — reproduced on calls 156/157) **landed during a Cartesia platform incident** that day affecting their serving fleet; the dispatch-layer instability is **resolved on their side now**. Both of our reproductions were inside that incident window.
- No client-side pacing is required: forward LLM sentences as they arrive + `continue=false` to flush is the expected pattern. The streaming WS has internal `max_buffer_delay_ms` (default 3000 ms) batching. **Our `FreshContextCartesiaTTSService` fix attempt was unnecessary** and made things worse (Cartesia confirms).
- Documented error schema for logging: `{"type":"error","context_id":"...","status_code":<int>,"done":true,"error":"<human-readable string>"}` (5xx `error` strings are generic).

→ **The reason we left Cartesia (the freeze) is largely invalidated.** A controlled re-test of Cartesia post-incident is now warranted, especially since its smaller frames may directly reduce the stretching.

**Two tracks, one story:**
1. **(Provider-agnostic, the real fix)** Make audio playback resilient to jitter — primarily a **client-side jitter buffer / playout-delay** tune so bursty packets stop time-stretching the voice. This helps on ANY TTS provider and is the launch-blocker fix.
2. **(Provider choice)** Re-evaluate Cartesia post-incident behind the existing `TTS_PROVIDER` flag: is the freeze gone, and do its smaller frames reduce stretching vs ElevenLabs? Decide the launch default. Fold in Cartesia's documented error schema + remove the now-confirmed-unnecessary fresh-context workaround.

**Critical reading before starting:**
- `server/CLAUDE.md` §5 (TTS provider switch — `tts_factory.py`, the Cartesia stall story, ElevenLabs default rationale, the `CARTESIA_*` debug env-gates).
- `memory/project_tts_provider_switch.md` + `memory/project_post_mvp_voice_ux_tuning.md` (the 2 connection-resilience items PROMOTED to pre-MVP: "audio jitter playout" + "interim-speech-never-finalizes").
- `client/lib/features/call/views/call_screen.dart` — the Story 6.13 weak-connection indicator already maps LiveKit `ConnectionQuality` poor/lost → a banner; this story can reuse that signal.
- `server/pipeline/tts_factory.py` + `pipeline/cartesia_instrumented.py` + `pipeline/tts_watchdog.py`.
- The deployed `livekit_client` / `flutter_webrtc` versions — check what jitter-buffer / playout-delay knobs they expose on the inbound audio track.

## Acceptance Criteria (BDD)

### AC1 — Jitter root-cause confirmed with a measurement (not a guess)

Given the stretching is currently diagnosed by elimination
When this story starts
Then we capture at least one **objective measurement** of the receiver-side jitter / time-stretch (e.g. WebRTC inbound-audio stats: `jitter`, `jitterBufferDelay`, `jitterBufferEmittedCount`, `insertedSamplesForDeceleration`/`removedSamplesForAcceleration`, or `concealedSamples`) on a real device during a stretched call
And the measurement is logged/observable so the fix can be validated against it (before/after)

### AC2 — Client-side jitter buffer / playout-delay tune

Given the inbound audio track is rendered via `livekit_client` (flutter_webrtc under the hood)
When this story lands
Then the inbound audio jitter buffer target (a.k.a. playout delay) is **increased** to absorb bursty arrival (candidate range ~150–400 ms; tuned empirically against AC1's metric), using whatever knob the SDK exposes (`jitterBufferTarget` / `RTCRtpReceiver` playout-delay hint / track config)
And if the SDK does NOT expose a usable knob, the story documents that finding and falls back to AC3/AC4 (provider-side frame tuning + provider choice) as the mitigation
And the added latency stays within the PRD ceiling (perceived turn latency ≤ 2 s; target ≤ 1.5 s) — the buffer trades a little latency for smoothness, and must not reintroduce the "concept dead" latency

### AC3 — ElevenLabs streaming/frame robustness reviewed

Given ElevenLabs Flash v2.5 sends larger audio frames than Cartesia
When this story lands
Then the ElevenLabs service config in `tts_factory.py` is reviewed for any `output_format` / streaming-chunk / `optimize_streaming_latency` setting that yields a **steadier, smaller-frame** stream
And any change is validated against AC1's metric (no regression in TTFA)

### AC4 — Cartesia re-evaluated post-incident behind the flag

Given Cartesia confirmed the freeze was a resolved platform incident + no client pacing needed
When this story lands
Then a controlled device re-test of `TTS_PROVIDER=cartesia` is run on a real jittery link:
  - Box A: the multi-sentence freeze (calls 156/157 pattern) **does NOT reproduce** across ≥3 calls post-incident
  - Box B: voice stretching under jitter is **measurably less** than ElevenLabs (AC1 metric) OR equivalent
And `TTSWatchdog` (or the Cartesia path) logs the **documented error schema** (`status_code` + `error`) instead of an opaque `type=error`
And the `FreshContextCartesiaTTSService` workaround is **removed** (Cartesia confirmed it is unnecessary and counter-productive) OR explicitly justified if kept
And a **launch default is decided** (`TTS_PROVIDER`): stay ElevenLabs, switch to Cartesia, or keep both with a documented recommendation. The decision + rationale is recorded in `server/CLAUDE.md` §5 + `memory/project_tts_provider_switch.md`

### AC5 — Pre-commit gates

Given the dual-side discipline
When this story lands
Then `ruff check . && ruff format --check . && pytest` (server) + `flutter analyze && flutter test` (client) all pass, and `tests/test_migrations.py` stays green (no schema change expected)

### AC6 — Smoke Test Gate validates smoothness end-to-end

See `## Smoke Test Gate` below.

## Smoke Test Gate (Device / Walid-owned)

> **Scope rule:** jitter only reproduces on a REAL mobile link. Mandatory device gate on Pixel 9 Pro XL.

- [ ] **Baseline measurement captured.** A stretched call's WebRTC inbound-audio stats recorded (AC1 metric) BEFORE the fix.
  - _Proof:_ <!-- stats screenshot / log -->
- [ ] **After the jitter-buffer tune (AC2): stretching gone or markedly reduced** on a deliberately jittery link (5G in a weak-signal spot, or a throttled connection). Tina's voice plays at normal speed.
  - _Proof:_ <!-- before/after recording + AC1 metric delta -->
- [ ] **Latency still under ceiling.** Perceived turn latency ≤ 2 s (target ≤ 1.5 s) with the larger buffer.
  - _Proof:_ <!-- LATENCY_PROBE / felt latency note -->
- [ ] **Cartesia re-test (AC4): no freeze across ≥3 calls** with `TTS_PROVIDER=cartesia` post-incident.
  - _Proof:_ <!-- journalctl: no 30s-error, no watchdog synthetic-stop -->
- [ ] **Provider A/B on stretching** — same jittery spot, ElevenLabs vs Cartesia, which stretches less.
  - _Proof:_ <!-- 2 recordings side by side -->
- [ ] **Launch default recorded** in `server/CLAUDE.md` §5 + memory.

## Tasks / Subtasks

### Phase 1 — Measure + client jitter buffer (the core fix)

- [ ] **Task 1 — Capture the jitter measurement** (AC1)
  - [ ] 1.1 — Pull WebRTC inbound-audio stats on the client during a stretched call (`RTCPeerConnection.getStats` via livekit_client, or LiveKit's track stats): `jitter`, `jitterBufferDelay`, `concealedSamples`, `insertedSamplesForDeceleration`.
  - [ ] 1.2 — Log them (dev-only) so before/after is comparable.
- [ ] **Task 2 — Increase the inbound audio jitter buffer / playout delay** (AC2)
  - [ ] 2.1 — Find the knob in the deployed `livekit_client` / `flutter_webrtc` (`jitterBufferTarget`, playout-delay hint, or audio track config). Document what's available.
  - [ ] 2.2 — Set an empirically-tuned target (~150–400 ms); make it a named constant, easy to retune.
  - [ ] 2.3 — If no knob exists, document it and pivot to AC3/AC4 as the mitigation.

### Phase 2 — Provider robustness + Cartesia re-eval

- [ ] **Task 3 — ElevenLabs frame/streaming review** (AC3)
  - [ ] 3.1 — Audit `tts_factory.py` ElevenLabs config for steadier-stream settings; tune if it helps AC1; verify no TTFA regression.
- [ ] **Task 4 — Cartesia re-evaluation** (AC4)
  - [ ] 4.1 — Parse + log Cartesia's documented error schema (`status_code`, `error`) in the Cartesia path / `TTSWatchdog`.
  - [ ] 4.2 — Remove `FreshContextCartesiaTTSService` (or justify keeping it) — Cartesia confirmed it's unnecessary/counter-productive.
  - [ ] 4.3 — Re-test `TTS_PROVIDER=cartesia` post-incident (Walid device gate) — freeze gone? stretching better?
  - [ ] 4.4 — Decide + record the launch default in `server/CLAUDE.md` §5 + `memory/project_tts_provider_switch.md`.

### Phase 3 — Gates + smoke

- [ ] **Task 5 — Pre-commit gates** (AC5) — ruff + pytest + flutter analyze + flutter test.
- [ ] **Task 6 — WALID device smoke gate** (AC6) — the 6 boxes above; then `review → done`.

## Dev Notes

**What "jitter" means (plain words, for Walid):** when Tina speaks, her voice is cut into tiny audio packets sent over the internet. On a perfect connection they arrive at a steady beat (one every ~20 ms). On a real phone connection they arrive **in irregular bursts** — 3 at once, then nothing for 80 ms, then 5 at once. That irregularity is "jitter". The phone has a tiny waiting room (the **jitter buffer**) where packets queue up so they can be played back at a steady beat. If the buffer is **too small**, it runs dry during a gap, and to avoid a silence the phone **stretches** the last bit of sound to fill the hole — that's the "rallongée" voice. **The fix:** make the waiting room a bit bigger (a slightly larger jitter buffer / playout delay). Cost: the voice starts a fraction of a second later (a small, fixed delay) — but it plays **smoothly**. That's the trade we want.

**Is there an instant toggle? Honest answer: no.** The proper fix is the jitter-buffer tune (Task 2), which needs implementing + device tuning — it's this story, the next thing to build. The one *experiment* available immediately is flipping `TTS_PROVIDER=cartesia` (env + restart, reversible) to see if Cartesia's smaller frames + the now-resolved incident give smoother audio today — that's Task 4.3 brought forward, and it's Walid's call.

**Why the jitter buffer is provider-agnostic and the right primary fix:** it fixes the symptom at the layer where it actually happens (the receiver), so it helps whether we ship ElevenLabs or Cartesia. Provider choice (Track 2) is a secondary lever, not the cure.

**Latency guard:** a bigger buffer adds latency. The PRD's hard ceiling is 2 s perceived ("concept dead" beyond). Tune the buffer to the smallest value that kills the stretching, and validate felt latency on-device (LATENCY_PROBE + ear).

**Out of scope:** the *other* promoted connection-resilience item ("interim-speech-never-finalizes dead-air") is a separate STT/endpointing concern — track it in its own story unless it proves entangled here.

### Project Structure Notes
- Client-only for Track 1 most likely (jitter buffer lives on the receiver). Track 2 touches `server/pipeline/tts_factory.py` + Cartesia path + docs/memory.
- No DB / migration changes expected.

### References
- Cartesia support thread (Walid Gmail, 2026-05-28) — incident resolution + error schema + no-pacing guidance.
- Cartesia status incident: https://status.cartesia.ai/incidents/1j04yfp4048k (the 2026-05-26 serving-fleet incident).
- `server/CLAUDE.md` §5; `memory/project_tts_provider_switch.md`; `memory/project_post_mvp_voice_ux_tuning.md`.

## Dev Agent Record

### Agent Model Used

(filled at dev time)

### Debug Log References

(filled at dev time)

### Completion Notes List

(filled at dev time)

### File List

(filled at dev time)

## Change Log

- 2026-05-30 (update) — **Cartesia validated far smoother on device (Walid A/B).** After flipping `TTS_PROVIDER=cartesia` on the VPS, Walid confirmed the voice is fluid with no stretching, "rien à voir avec ElevenLabs", and no freeze across his post-incident test calls. → **Track 2's likely outcome is already known: make Cartesia the launch default; ElevenLabs becomes last-resort until Track 1's jitter buffer ships.** This shifts the story's center of gravity: Track 2 (flip default to Cartesia + remove fresh-context workaround + log the documented error schema + keep watching for the freeze) is the immediate launch-readiness win; Track 1 (client jitter buffer) is still needed to make ElevenLabs viable as a fallback but is no longer the only path to relief. See [[project_tts_provider_switch]] (direction reversal recorded).
- 2026-05-30 — Spec drafted. Root cause of the recurring "voix rallongée" diagnosed as network-jitter receiver-side time-stretch (server logs clean on call_id=198; DTLN-off never helped → not server pacing). Two tracks: (1) provider-agnostic client jitter-buffer/playout-delay tune (the launch-blocker fix), (2) Cartesia re-evaluation post-incident (Cartesia support 2026-05-28 confirmed the 2026-05-26 freeze was a resolved platform incident — both our reproductions were in that window — and that no client pacing is needed + the fresh-context workaround was unnecessary). Awaiting Walid sign-off / `/bmad-dev-story`.
