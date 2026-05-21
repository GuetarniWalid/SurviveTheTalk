# Story 6.9: DTLN Server-Side Noise Suppression

Status: review

## Story

As the operator (Walid),
I want the voice pipeline to suppress background noise BEFORE STT/VAD,
so that users can practice in normal noisy environments (cafés, transit, open offices) without their turns being misread or false-triggered.

## Background

**Direct successor of Story 6.7's smoke-test feedback (2026-05-19)** and Walid's explicit ask (2026-05-20): "Toute l'application repose sur l'utilisabilité de la voix. Si cette sensation est dégradée, l'application en sera de même". WebRTC's built-in noise suppression (already on by default via `setMicrophoneEnabled(true)`) covers stationary noise (fan, hum, distant voice) but is **insufficient for babble noise** (café, restaurant, transit) — exactly the environments a B1 learner would practice in.

**The 4 alternatives considered (full web research log in conversation)**:

| Option | Cost | Quality | Effort | Outcome |
|---|---|---|---|---|
| Krisp commercial SDK | Opaque, "Apply Now" sales gate | 🟢 Best | 2-3 days + 1-2 week sales cycle | ❌ Rejected — sales cycle + unknown $$ |
| Picovoice Koala | **$6,000/year flat** (Foundation tier) | 🟢 Claimed Krisp-comparable | 2 days | ❌ Rejected — $500/mo flat for pre-revenue MVP |
| DeepFilterNet mobile | $0 | 🟡 PESQ 3.5-4.0 (~85% Krisp) | 3-5 days (iOS = no public binding, AndroidDeepFilterNet 23 stars) | ❌ Rejected — iOS gap + immature bindings |
| **livekit-plugins-dtln (Aloware)** | **$0** | 🟢 ≈ Krisp (taxi test: cleaner than Krisp) | **~½ day** | ✅ **Chosen** |

**Why this is the right architectural call**:
- **Server-side, not client-side** — runs in our existing Pipecat pipeline on Hetzner VPS. Zero mobile code changes; works on iOS, Android, and any future Flutter web build for free.
- **MIT license, code + weights** — full forking rights if Aloware abandons the project. Underlying DTLN model is from breizhn (Interspeech 2020); pretrained weights from the official DTLN repo are bundled in the wheel (~4 MB).
- **Production-validated** — Datadog runs the same DTLN model in CoScreen in prod; Aloware's published benchmarks vs Krisp show cleaner transcripts in noisy scenes (taxi).
- **Trade-off accepted**: noisy audio still uploaded over WebRTC (Opus encoder copes fine), CPU cost on VPS instead of device (~3-4 ms inference per 8 ms block on a Hetzner-class CPU — well inside real-time at ~0.4x realtime factor).

**Hard prerequisite chain:**
- ✅ Story 6.8 (latency + coherence + Waiter calibration) — review/done
- ⏳ Story 6.9 (this story) — review

**Up-front deviations to document in Implementation Notes:**

1. **(Deviation #1) Server-side denoising, not client-side.** All 3 paid alternatives (Krisp, Picovoice, Krisp-via-LiveKit-Cloud) and the only viable open-source mobile option (DeepFilterNet) ship client-side. We chose server-side because it eliminates platform-channel work, parallel iOS/Android maintenance, and commercial license overhead. The downside (noisy audio over WebRTC) is mitigated by Opus encoder noise tolerance — and the same trade-off exists with Krisp client-side except worse (audio goes through WebRTC encode AFTER suppression, but Krisp's suppression itself doesn't change the WebRTC bandwidth profile meaningfully).

2. **(Deviation #2) Calling `_process` directly is the public hook despite the underscore prefix.** The LiveKit `rtc.FrameProcessor[T]` abstract base declares `_process(frame: T) -> T` and `_close()` as the two abstract methods every FrameProcessor must implement. The LiveKit room I/O layer calls `_process` directly when wiring `AudioInputOptions(noise_cancellation=...)`. So our wrapper calling `suppressor._process(rtc_frame)` is consistent with the intended usage pattern — not a private-API hack. Documented in the inline comment.

3. **(Deviation #3) Strength=0.5 default (50/50 wet/dry blend).** Full-strength suppression (1.0) sounds thin/metallic on borderline frames; 0.5 keeps voice timbre natural while still removing significant background noise. Walid tunes empirically toward 0.7-0.8 only if smoke-gate café test shows residual babble bleeding into STT.

4. **(Deviation #4) `livekit-plugins-dtln` upgraded `livekit` SDK 1.1.3 → 1.1.8 + `livekit-protocol` 1.1.3 → 1.1.9.** Pipecat 0.0.108 doesn't pin a specific livekit version (the extra is `livekit-agents` not `livekit`), so the upgrade went through cleanly. All 329 baseline pre-DTLN tests still pass post-upgrade; the new DTLN suite adds 11 tests = 340 total + 1 wiring test = 341.

---

### Post-Smoke-Test Amends (2026-05-21) — **CRITICAL READ FOR CODE REVIEW**

The initial Story 6.9 commit (`0e1ba96`) shipped the 4 deviations above. The smoke test revealed **4 additional issues** that triggered the amends below. These were NOT in the original spec — every one is a reaction to a real failure observed in production logs during the 2026-05-21 smoke session. Reviewers should pay special attention to these because they touch concurrency, infra-fairness, and SDK-private APIs:

5. **(Deviation #5) `verdict=None` is now patience-NEUTRAL, not patience-NEGATIVE.** Original Story 6.6 design treated classifier failure (HTTP error / timeout / parse error) as conservative `apply_exchange_outcome(success=False)` (drains -15 patience). The smoke test (2026-05-21, call 138 "Pasta. Pasta. Pasta.") proved this was wrong: a single OpenRouter HTTP timeout (821ms vs the 800ms budget) cost the user 15 patience for a turn they delivered perfectly. The fix in `checkpoint_manager.py::_classify_and_advance` — when `verdict is None`, log a WARNING but **DO NOT** call `apply_exchange_outcome`. The checkpoint still doesn't advance (no free progression). Patience stays unchanged. The next user turn gets another classification chance.
   - **Adversarial review concern**: could an attacker DoS OpenRouter to keep the call alive indefinitely without patience drain? Answer: yes in theory, but they'd already be paying for STT + TTS minutes via Soniox/Cartesia — the call would time-cap naturally; and the silence ladder (Story 6.4) still fires on truly silent turns. The fix favors infra fairness over abuse-resistance — explicit trade-off.
   - **Test 7 inversion**: `test_classifier_None_does_not_advance_applies_fail_penalty` was RENAMED + REWRITTEN to `test_classifier_None_does_not_advance_and_does_not_drain_patience`. The new test asserts `apply_exchange_outcome.assert_not_called()` — reviewers should verify this is the intended behavior and that the old contract isn't depended on elsewhere.

6. **(Deviation #6) HTTP timeout `0.8s → 1.5s` + outer `1.0s → 2.0s` — partial revert of Story 6.8 AC4.** Story 6.8 had tightened the classifier budget from 2.0s/1.8s → 1.0s/0.8s for terminal-turn latency. The smoke test revealed this left zero margin for httpx cold-start (TCP + TLS handshake ~100-200ms paid on every classify because each call created a fresh `httpx.AsyncClient`). Combined with OpenRouter qwen-flash TTFT variance (300-1500ms), ~30% of calls hit timeout. The amend restores the original Story 6.6 budget (2.0s/1.5s) so the persistent-client savings (#7) PLUS the larger budget give comfortable margin. **Trade-off**: terminal-turn synchronous classifier (Deviation #7 from Story 6.6) may now block up to 2.0s on the very last user turn — adds ~1s to perceived end-of-call latency vs Story 6.8's tight 1.0s budget. Acceptable for MVP because terminal-turn latency is invisible compared to the spoken exit line (5-8s of TTS speech) AND the call has already ended functionally. Story 6.8 AC4 docstring inline updated to reflect the new values.

7. **(Deviation #7) Persistent `httpx.AsyncClient` in `ExchangeClassifier` with `_get_client()` + `close()` lifecycle methods.** Original implementation opened a fresh client per classify call (idiomatic `async with httpx.AsyncClient() as client:` pattern, but wasteful at scale because TCP+TLS handshake repeats). The amend introduces:
   - `__init__` adds `self._client: httpx.AsyncClient | None = None` + `self._client_lock = asyncio.Lock()`
   - `_get_client()` async method does double-checked locking: first check WITHOUT lock for the fast path, take lock + recheck for the cold-start race (two classify() calls firing simultaneously at call boot)
   - `close()` async method releases the connection pool via `await self._client.aclose()`; idempotent (safe to call twice)
   - `CheckpointManager.cleanup()` now calls `self._classifier.close()` (guarded by `hasattr` for back-compat with test stubs)
   - **Adversarial review concerns**:
     - Double-checked locking pattern: is the `is None` check on first read safe across Python's memory model? Answer: yes — CPython's GIL ensures atomic read for object references; the only race is "two coroutines both see None and both create a client" which the lock+recheck handles.
     - Connection pool stale-after-server-close: httpx 0.28+ handles this internally with `httpcore`'s connection-state tracking; broken connections trigger a new TCP connect on the next request transparently. We rely on httpx defaults.
     - Idempotent close: tested in `test_close_releases_client_and_is_idempotent` — `await classifier.close()` twice without error.
   - **Tests added**: `test_persistent_client_reused_across_classify_calls` (asserts client identity is stable across 3 classify calls) + `test_close_releases_client_and_is_idempotent`.

8. **(Deviation #8) `SonioxSTTService(... vad_force_turn_endpoint=False, ...)` to fix the "interim TFs forever" freeze.** Original `bot.py` used the Pipecat default `vad_force_turn_endpoint=True` (Silero VAD declares user-stop → Pipecat sends finalize message to Soniox). The smoke test (2026-05-21, call 142 "Cola" lost) revealed that when Silero never declares stop (continuous low-level audio: breathing, AC hum, papers rustling), Soniox keeps streaming interim TranscriptionFrames indefinitely (22+ seconds observed) and the user's turn is never finalized. The amend sets `vad_force_turn_endpoint=False` which delegates endpoint detection to Soniox's own neural VAD (Soniox decides when speech ends based on its model). Much more robust against continuous low-level noise.
   - **Adversarial review concern**: are there scenarios where Soniox's endpoint detection is WORSE than Silero's? Possibly with very long pauses mid-utterance (Soniox might finalize too early if user pauses mid-sentence to think). Mitigated by the intent-first classifier prompt (Story 6.8) which tolerates fragments and re-statements.
   - **VAD tuning revert (sub-deviation)**: We had briefly experimented (2026-05-21) with `confidence=0.85`, `min_volume=0.7`, `DTLN strength=0.8` to fight the cocktail-party YouTube test. After the smoke test confirmed those params hurt soft-voice users without solving voice-isolation (a different DSP problem), we reverted all 3 back to the Story 6.9 baseline (`confidence=0.7`, `min_volume=0.5`, `strength=0.5`). The amend includes the revert with inline comments explaining the journey.

9. **(Sub-deviation under #5/#6/#7) HTTP error log line now includes exception class name.** Original log was `logger.warning("exchange classifier HTTP error: {}", exc)`. Some httpx exceptions (notably `httpx.TimeoutException`) serialize to empty `str()` → operator saw `"HTTP error: "` with no content. The amend adds `({type(exc).__name__})` suffix → smoke-gate operator can disambiguate timeout vs connect vs response error without code-diving.

### Cumulative Story 6.9 status post-amends (for reviewer scope-check):

- **Original spec**: AC1-AC10 + 4 deviations + 11 unit tests + 1 wiring assertion = 12 net new tests
- **Post-smoke-test amends**: +4 deviations + 2 new tests (`test_persistent_client_reused_across_classify_calls`, `test_close_releases_client_and_is_idempotent`) + 1 test inversion (test 7 rewrite) = 3 net delta
- **Final test count**: 343 server (341 initial + 2 new) + 373 client (unchanged)
- **Files touched post-`0e1ba96` commit**:
  - `server/pipeline/bot.py` (VAD revert + Soniox endpoint flag)
  - `server/pipeline/exchange_classifier.py` (persistent client + close() + timeout bump + log enhancement + docstring updates)
  - `server/pipeline/checkpoint_manager.py` (verdict=None patience-neutral + classifier.close in cleanup)
  - `server/tests/test_checkpoint_manager.py` (test 7 inverted)
  - `server/tests/test_exchange_classifier.py` (2 new tests for persistent client)

### What the code reviewer should focus on:

1. **Concurrency**: `_get_client()` double-checked locking, `classifier.close()` idempotency, `CheckpointManager.cleanup()` ordering (drain in-flight task BEFORE close classifier — currently correct order in the diff).
2. **Resource leaks**: Confirm `httpx.AsyncClient` is always closed on call teardown (no path that exits without calling cleanup).
3. **Failure modes**: Is `verdict=None` neutrality the right call, or should patience drain very slightly (-1 instead of -15) to discourage upstream-DoS abuse? Currently we chose pure neutrality.
4. **Backwards compat**: Test 7 was inverted — confirm no other test or production code path expects the old `apply_exchange_outcome(success=False)` on None verdict.
5. **Soniox endpoint detection**: Validate the trade-off — does delegating to Soniox introduce edge cases on long mid-utterance pauses? Smoke test didn't cover this thoroughly.
6. **VAD revert**: All 3 reverted params are documented with the journey ("we tried X then reverted because Y"). Reviewer can confirm we're back to baseline.
7. **HTTP timeout 1.5s + outer 2.0s**: Does this cumulatively undo Story 6.8 AC4's latency goal? Yes for the worst-case terminal turn, no for the median (the persistent client saves ~150ms which compensates).

## Acceptance Criteria (BDD)

**AC1 — DTLN ONNX dependency installed:**

Given `pyproject.toml`'s `dependencies` list
When this story lands
Then `livekit-plugins-dtln>=0.1.5,<0.2.0` is listed as a top-level dep
And `uv lock` has been re-run so the lockfile reflects the new dep + transitive upgrades (`livekit` 1.1.3 → 1.1.8, `livekit-protocol` 1.1.3 → 1.1.9, `onnxruntime` pulled in by the plugin)

**AC2 — `DTLNAudioFilter` wraps the plugin behind Pipecat's `BaseAudioFilter`:**

Given Pipecat's `LiveKitParams.audio_in_filter` accepts any `BaseAudioFilter`
When this story lands
Then a new module `server/pipeline/dtln_audio_filter.py` exists
And it exports `DTLNAudioFilter(BaseAudioFilter)` with constructor `__init__(*, strength=0.5, debug_logging=False)`
And it implements all 4 abstract `BaseAudioFilter` methods (`start`, `stop`, `process_frame`, `filter`)
And `start(sample_rate)` lazily instantiates `livekit.plugins.dtln.DTLNNoiseSuppressor` so the ~100-500 ms ONNX cold-start happens at call boot, not at module import
And `filter(audio: bytes) -> bytes` always returns a `bytes` object of the **same length** as input (the suppressor passes through during startup latency ~24 ms, then steady-state denoised; either way length preserved)

**AC3 — Failure mode is passthrough, not crash:**

Given the DTLN ONNX session can fail to initialize (missing model files, runtime version mismatch, OOM)
And the suppressor's `_process` can throw mid-call
When either failure happens
Then `start()` catches the init error, logs `loguru.exception`, and flips `_enabled = False` → subsequent `filter()` calls return input unchanged
And `filter()` wraps `_process` in try/except and returns input unchanged on any exception, logging `loguru.exception`
And the call NEVER crashes from a denoising failure — better to ship slightly-noisier audio than drop the call

**AC4 — Wired into bot.py's LiveKitParams:**

Given `server/pipeline/bot.py` constructs `LiveKitTransport(params=LiveKitParams(...))`
When this story lands
Then `bot.py` imports `from pipeline.dtln_audio_filter import DTLNAudioFilter`
And `bot.py` instantiates `audio_in_filter = DTLNAudioFilter(strength=0.5)` BEFORE `LiveKitTransport(...)`
And `LiveKitParams(...)` includes `audio_in_filter=audio_in_filter`
And a wiring test in `tests/test_bot_pipeline_wiring.py` asserts both the import AND the `audio_in_filter=audio_in_filter` kwarg via source-text matching

**AC5 — Runtime enable/disable via FilterEnableFrame:**

Given Pipecat ships `FilterEnableFrame(enable: bool)` for runtime toggling
When `process_frame(FilterEnableFrame(enable=False))` arrives at the filter
Then `self._enabled` flips to False
And the underlying `_suppressor.enabled` also flips
And the next `filter(audio)` call returns input unchanged (passthrough)
And the symmetric `enable=True` re-enables the suppression chain

**AC6 — Pre-commit gates green:**

Given the dual-side discipline (CLAUDE.md root + server/CLAUDE.md)
When this story lands
Then ALL pass before flipping `in-progress → review`:
- `ruff check .` → zero issues
- `ruff format --check .` → zero issues
- `pytest` → 341 passed (baseline Story 6.8 = 329; +11 new DTLN tests + 1 wiring test)
- `flutter analyze` clean, `flutter test` unchanged (zero Flutter code in this story)

**AC7 — Smoke Test Gate (deploy-side, owned by Walid):**

See `## Smoke Test Gate` section below.

## Smoke Test Gate (Server / Deploy Story)

> **Scope rule:** Server-side denoising on the call audio path. The gate is mandatory — noise-suppression quality can ONLY be validated on a real call against the real VPS pipeline, in a real noisy environment.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test. Server logs at boot show `DTLNAudioFilter started sample_rate=… strength=0.5` from at least one call session.
  - _Proof:_ <!-- paste Active line + commit SHA + first DTLN started log line -->

- [ ] **Baseline calm-room call (no regression).** 1 Waiter call in your normal calm room with DTLN active. Latency per Story 6.8 AC5 still under target.
  - _Expected:_ median user-speech-end → character-first-audio ≤ **1500ms**, p95 ≤ **2000ms** (same as Story 6.8 baseline; DTLN adds ~35 ms which is invisible)
  - _Proof:_ <!-- paste median + p95 from transcript timestamps -->

- [ ] **Café-bondé Waiter call (real noise test).** 1 Waiter call from a coffee shop or comparable babble-noise environment (TV in background, multiple conversations). Drive the same script as Story 6.8 smoke test (chicken → cola → confirm → thanks).
  - _Expected:_ STT finalizes cleanly (no spurious turn-starts from background voices), `checkpoint_advanced` events fire in the right order, `reason=survived` at the end. **Latency NOT degraded** vs baseline (≤2000ms p95).
  - _Proof:_ <!-- paste journalctl checkpoint events + transcript -->

- [ ] **A/B comparison (optional but informative).** Disable DTLN via FilterEnableFrame OR by setting `strength=0.0` in `bot.py` + redeploy. Re-run the café call. Compare transcript quality + checkpoint advance pattern vs the with-DTLN run.
  - _Expected:_ visible degradation without DTLN (more `checkpoint_unmet` or interim turns); DTLN restores cleanliness.
  - _Proof:_ <!-- side-by-side transcript samples -->

- [ ] **Server CPU sane.** During the café call, `top -p $(pidof python | tr ' ' ',')` shows pipecat.service CPU usage **below 50%** of one core (DTLN ~10-20% added on top of baseline ~10-15%).
  - _Proof:_ <!-- paste top snapshot -->

- [ ] **Server logs clean.** `journalctl -u pipecat.service --since "5 min ago" | grep -iE "(error|traceback|exception)" | grep -v INFO` returns zero matches across the test calls. In particular, NO `DTLNAudioFilter init failed` or `DTLNAudioFilter filter failed; passthrough` log lines — those indicate the filter degraded mid-call.
  - _Proof:_ <!-- "no errors in window" + timestamp -->

## Tasks / Subtasks

- [x] **Task 1 — Investigate `livekit-plugins-dtln` API + Pipecat compat** (AC1, AC2)
  - [x] 1.1 — `pip install livekit-plugins-dtln` in local venv, inspect import path (`livekit.plugins.dtln`), discover `DTLNNoiseSuppressor` class
  - [x] 1.2 — Read source `noise_suppressor.py` to understand expected input format (int16 PCM mono, arbitrary chunk size via internal buffer), API surface (`_process`, `_close`, `enabled` property)
  - [x] 1.3 — Discover Pipecat's `TransportParams.audio_in_filter: BaseAudioFilter` extension point — perfect wiring slot, no need to patch transport internals
  - [x] 1.4 — Verify `livekit` SDK upgrade 1.1.3 → 1.1.8 doesn't break Pipecat: `test_bot_pipeline_wiring.py` (9 tests) green post-install

- [x] **Task 2 — Implement `DTLNAudioFilter`** (AC2, AC3, AC5)
  - [x] 2.1 — New file `server/pipeline/dtln_audio_filter.py` (~140 LOC), `DTLNAudioFilter(BaseAudioFilter)`
  - [x] 2.2 — `__init__(*, strength=0.5, debug_logging=False)` with strength clamped to `[0.0, 1.0]`
  - [x] 2.3 — `start(sample_rate)` lazy-instantiates suppressor + rtc import; init failure → log + disable (passthrough)
  - [x] 2.4 — `filter(audio)` wraps bytes in `rtc.AudioFrame`, calls `_process`, returns bytes; any exception → passthrough this chunk
  - [x] 2.5 — `stop()` releases suppressor + rtc refs for GC
  - [x] 2.6 — `process_frame(FilterEnableFrame)` toggles `_enabled` flag on wrapper AND on underlying suppressor

- [x] **Task 3 — Wire into bot.py** (AC4)
  - [x] 3.1 — Import `DTLNAudioFilter` at top of `bot.py`
  - [x] 3.2 — Instantiate `audio_in_filter = DTLNAudioFilter(strength=0.5)` before transport construction
  - [x] 3.3 — Add `audio_in_filter=audio_in_filter` to `LiveKitParams(...)` call

- [x] **Task 4 — Tests** (AC2-AC5)
  - [x] 4.1 — New `tests/test_dtln_audio_filter.py` (7 tests): end-to-end ONNX round-trip (length preserved), disabled passthrough, init-failure passthrough, FilterEnableFrame toggle, filter-exception passthrough, stop releases resources, strength clamped
  - [x] 4.2 — Extend `tests/test_bot_pipeline_wiring.py` with `test_bot_imports_emitter_classes` (assertion on `DTLNAudioFilter` import) + new `test_bot_wires_dtln_audio_filter_into_livekit_params` (source-text wiring guard on `audio_in_filter=audio_in_filter`)

- [x] **Task 5 — Dependency manifest** (AC1)
  - [x] 5.1 — `pyproject.toml` adds `"livekit-plugins-dtln>=0.1.5,<0.2.0"` to `dependencies`
  - [x] 5.2 — `uv lock` re-runs cleanly with transitive upgrades (livekit 1.1.3 → 1.1.8, plus opentelemetry, grpcio, av, sounddevice, etc.)

- [x] **Task 6 — Pre-commit gates** (AC6)
  - [x] 6.1 — `ruff check .` → All checks passed
  - [x] 6.2 — `ruff format --check .` → 59 files already formatted
  - [x] 6.3 — `pytest` → 341 passed (329 baseline + 11 new DTLN + 1 wiring assertion)
  - [x] 6.4 — `flutter analyze` clean, `flutter test` unchanged from Story 6.8 baseline

- [ ] **Task 7 — VPS deploy + Smoke Test Gate** (AC7)
  - [ ] 7.1 — `git push` → CI/CD deploy on VPS
  - [ ] 7.2 — SSH VPS: `cd /opt/survive-the-talk/current/server && .venv/bin/pip install -r requirements.txt` (or equivalent uv command). Verify `livekit-plugins-dtln` installed.
  - [ ] 7.3 — `systemctl restart pipecat.service`; verify `active (running)` + clean boot log
  - [ ] 7.4 — **WALID** — 6-box Smoke Test Gate above on Pixel 9 Pro XL
  - [ ] 7.5 — `review → done` after smoke gate proofs

## Dev Notes

**Why server-side and not client-side?**
This decision was the longest deliberation in this story (full transcript in conversation). The trade-off matrix above shows server-side DTLN wins on every axis except one (audio still uploaded noisy over WebRTC — but Opus encoder copes fine, and even Krisp client-side encodes Opus AFTER suppression, so the bandwidth-while-suppressed wins are marginal).

**Why DTLN and not DeepFilterNet?**
DeepFilterNet3 benchmarks slightly higher PESQ (3.5-4.0 vs DTLN's 3.04) but has no official LiveKit/Pipecat integration. The Aloware plugin gave us a ready-to-use DTLN integration with Krisp-comparable real-world quality (their published benchmarks show cleaner transcripts than Krisp on the taxi scene). Shipping in ½ day vs 3-5 days dev for DeepFilterNet's ONNX integration is the decisive factor.

**Why call `_process` directly?**
The leading underscore on `_process` is a quirk of the LiveKit Python SDK's `rtc.FrameProcessor` abstract base — both `_process` AND `_close` are declared abstract there, and the room I/O layer calls them directly when wiring `AudioInputOptions(noise_cancellation=...)`. So our wrapper calling `_process` follows the intended usage pattern; it's not a private-API hack.

**Why strength=0.5 default?**
Full-strength (1.0) DTLN can sound thin/metallic on borderline frames — common with aggressive ML denoisers. The 50/50 wet/dry blend keeps voice timbre natural while still removing significant background noise. Walid will tune toward 0.7-0.8 only if the café smoke test shows residual babble bleeding into STT.

**Why passthrough on every error?**
"Better than broken" — see `server/CLAUDE.md`. A denoising failure means slightly-noisier audio for the user (recoverable, maybe a turn or two affected); an unhandled exception in the filter would crash Pipecat's audio path mid-call (call drops, user frustration, lost session). Every failure path in the filter — init crash, mid-call exception, stop-after-error — falls back to passthrough.

### Project Structure Notes

**Server — modified:**
- `server/pyproject.toml` — `livekit-plugins-dtln>=0.1.5,<0.2.0` dep added
- `server/uv.lock` — regenerated with transitive upgrades (livekit 1.1.3 → 1.1.8, livekit-protocol 1.1.3 → 1.1.9, livekit-agents added, onnxruntime added, opentelemetry stack added, grpcio, av, sounddevice, watchfiles, etc.)
- `server/pipeline/bot.py` — import `DTLNAudioFilter`; instantiate before transport; pass `audio_in_filter=audio_in_filter` to `LiveKitParams(...)`
- `server/tests/test_bot_pipeline_wiring.py` — extend `test_bot_imports_emitter_classes` with `DTLNAudioFilter` import assertion + new `test_bot_wires_dtln_audio_filter_into_livekit_params` source-text wiring guard

**Server — new files:**
- `server/pipeline/dtln_audio_filter.py` (~140 LOC) — `DTLNAudioFilter(BaseAudioFilter)`
- `server/tests/test_dtln_audio_filter.py` (~180 LOC, 7 tests)

**Client — no changes.**

**Implementation artifacts — modified:**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — new entry `6-9-dtln-noise-suppression: review`
- `_bmad-output/implementation-artifacts/6-9-dtln-noise-suppression.md` — this file

### References

- [livekit-plugins-dtln GitHub](https://github.com/aloware/livekit-plugins-dtln) — MIT, v0.1.5 (April 2026), 32 stars
- [livekit-plugins-dtln benchmarks vs Krisp](https://aloware.github.io/livekit-plugins-dtln/) — taxi/café/gym comparisons
- [Original DTLN paper](https://arxiv.org/pdf/2005.07551) — Westhausen & Meyer, Interspeech 2020
- [breizhn/DTLN](https://github.com/breizhn/DTLN) — pretrained ONNX models (bundled in the plugin)
- [Datadog dtln-rs](https://github.com/DataDog/dtln-rs) — same model in CoScreen production
- [Pipecat BaseAudioFilter source](https://github.com/pipecat-ai/pipecat) — `pipecat.audio.filters.base_audio_filter`
- [Memory: project_post_mvp_voice_ux_tuning.md](memory/project_post_mvp_voice_ux_tuning.md) — this story addresses one of the deferred items
- [Story 6.8](6-8-post-checkpointmanager-scenario-calibration.md) — direct predecessor; Story 6.7 smoke test surfaced the noise issue

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context)

### Debug Log References

- Investigation (Task 1): `pip install livekit-plugins-dtln` pulled livekit-agents 1.5.11, livekit 1.1.8 (upgrade from 1.1.3), livekit-protocol 1.1.9, livekit-blingfire, av, watchfiles, sounddevice, requests, opentelemetry stack, prometheus-client. Pipecat 0.0.108 still imports + tests pass.
- Pre-commit (Task 6): `ruff check` clean, `ruff format` clean (59 files), `pytest` 341 passed in 159 s. `flutter analyze` clean. Net new tests: 11 DTLN + 1 wiring = 12.

### Completion Notes List

**Architectural choice (server-side, not client-side):** Spent significant deliberation on Krisp vs Picovoice Koala vs DeepFilterNet vs livekit-plugins-dtln. The decisive factor was zero mobile code change. Server-side has the trade-off of CPU on VPS + noisy audio over WebRTC; both are acceptable for MVP scale (Hetzner has CPU headroom; Opus encoder tolerates background noise without ballooning bandwidth).

**Why call `_process` directly:** The LiveKit `rtc.FrameProcessor[T]` abstract base declares `_process` and `_close` as the two abstract methods. Room I/O calls them externally when wiring `AudioInputOptions(noise_cancellation=...)`. So the leading underscore is convention-only; the call is the intended public API.

**Why strength=0.5 default:** Full-strength (1.0) can sound thin/metallic. 50/50 wet/dry preserves voice timbre while removing significant noise. Tune empirically toward 0.7-0.8 if café smoke test shows residual babble in STT.

**Failure mode is passthrough:** Every error path (init crash, mid-call `_process` exception, stop-after-error) falls back to returning input audio unchanged. Better noisy than dropped — see `server/CLAUDE.md` "Better than broken".

**4 deviations documented up-front in Background.**

### File List

**Server — modified:**
- `server/pyproject.toml`
- `server/uv.lock` (regenerated)
- `server/pipeline/bot.py`
- `server/tests/test_bot_pipeline_wiring.py`

**Server — new files:**
- `server/pipeline/dtln_audio_filter.py`
- `server/tests/test_dtln_audio_filter.py`

**Implementation artifacts:**
- `_bmad-output/implementation-artifacts/sprint-status.yaml`
- `_bmad-output/implementation-artifacts/6-9-dtln-noise-suppression.md` (new)

## Change Log

- 2026-05-20 — Dev complete, all 6 pre-commit gates green. Story flipped `in-progress → review`. 11 new DTLN tests + 1 wiring test (server 329 → 341). 4 up-front deviations documented. Smoke gate (6 boxes incl. café-bondé real-noise test) reserved for Walid post-deploy. Commit `0e1ba96`.

- 2026-05-21 — **Post-smoke-test amends (uncommitted on this branch, pending code review)**. Smoke test on Pixel 9 Pro XL surfaced 2 production bugs that pre-existed in Story 6.8 but only became visible under DTLN's audio chain: (a) call 138 lost on "Pasta. Pasta. Pasta." — OpenRouter HTTP timeout (821ms vs 800ms budget) caused -15 patience drain for a perfectly-delivered turn; (b) call 142 lost on "Cola" — Soniox interim TFs kept the turn open 22s without finalizing because Silero VAD never detected stop. 4 reliability amends shipped: #5 `verdict=None` patience-neutral, #6 timeout `0.8s/1.0s → 1.5s/2.0s`, #7 persistent `httpx.AsyncClient` with `_get_client()` + `close()` lifecycle, #8 `vad_force_turn_endpoint=False` + revert of experimental VAD tuning. Test 7 inverted (`apply_exchange_outcome.assert_not_called()`); 2 new tests for persistent client lifecycle. Server tests 341 → 343 (+2 net). Café smoke test re-validated by Walid post-amends (2026-05-21) — DTLN noise suppression confirmed working in noisy environment. **Cocktail-party / parasitic-voice case acknowledged as out-of-scope** (different DSP problem — voice isolation vs noise suppression), deferred to Story 6.11 (Noisy Environment Detection — spec drafted same day). Pending: `/commit` of the 5 modified files + 2 new spec drafts (6-10, 6-11), `/bmad-code-review` of cumulative branch state, then `review → done` flip.
