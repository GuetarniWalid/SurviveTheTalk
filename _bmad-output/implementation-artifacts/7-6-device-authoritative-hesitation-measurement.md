# Story 7.6: Device-Authoritative Hesitation Measurement

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

> **Origin.** Follow-up to Story 7.5, ratified by Walid 2026-06-16. The 7.5 code
> review (2026-06-15) found the device-measurement path (`DeviceHesitationCollector`
> + `merge_hesitation_sources`) **built but DORMANT** — the client onset detector
> under-produces, so 7.5 shipped the **server hybrid** (the `HesitationObserver`
> re-anchored on the client `playback_idle` signal) as a reliable interim. This
> story finishes 7.5 decision **D3-c**: make the on-device meter RELIABLE, then
> make device-measured gaps the AUTHORITATIVE hesitation source (server observer =
> fallback).
> Full origin: `deferred-work.md` ("Device-authoritative hesitation measurement =
> follow-up story") + `7-5-overhaul-debrief-report.md` ("Review Findings — Client"
> + the "D3-c architecture" SHIPPED-DELTA note).

## Story

As a **learner reviewing my post-call debrief** (and the product owner who needs the hesitation number to be trustworthy),
I want the **felt pause** between the character finishing speaking and me starting to speak to be **measured on my own phone** (character audio ends in my ear → my speech onset at the mic, both timed on-device, only the final number shipped),
so that the reported hesitation is **network-immune** — accurate even on a bad connection, where the server hybrid (which includes downlink jitter-buffer + uplink + VAD lag) over-states the gap.

## Context — what already exists (DO NOT rebuild)

The entire D3-c machinery is **already coded and partly unit-tested**. This story
makes it RELIABLE; it does not re-architect it. Foundation that must be **kept and
fixed, not replaced**:

| Piece | File | State |
|-------|------|-------|
| Bot-side collector + teardown merge | `server/pipeline/device_hesitation_collector.py` | `DeviceHesitationCollector` + `merge_hesitation_sources` — **implemented + unit-tested** (`server/tests/test_device_hesitation_collector.py`, 6 tests). `merge` is **never called**. |
| Envelope routing | `server/pipeline/bot.py` `on_data_received` (≈L877-894) | Already records `hesitation_onset` envelopes into the collector (live, but its output is discarded). |
| Server fallback observer | `server/pipeline/hesitation_observer.py` | The 7.5 shipped source — anchored on `playback_idle`, threshold 4.0 s, C2 unresolved-freeze capture. **Stays as the fallback — never remove it.** |
| Dart onset state machine | `client/lib/features/call/services/hesitation_meter.dart` | `HesitationMeter` (adaptive floor + SNR + debounce + max-gap censor). Present; **under-produces**. |
| Native record-side RMS tap | `client/android/app/src/main/kotlin/com/surviveTheTalk/client/AudioCaptureChannel.kt` | Reflects flutter_webrtc's `recordSamplesReadyCallbackAdapter`, pushes per-frame RMS on `com.surviveTheTalk.client/onset_rms`. Present; **fails soft with NO retry**. |
| Client wiring | `client/lib/features/call/views/call_screen.dart` (`_startHesitationMeter`, the arming gate at the viseme apply, `_publishHesitationOnset`, the `onset_rms_alive` diag) | Present + complete; arm on `onSilenceConfirmed`, disarm on any non-REST viseme, publish onset upstream. |
| Diagnostics | client `bool.fromEnvironment('HESITATION_DIAG')` → `onset_rms_alive`; server `os.environ['HESITATION_DIAG']=='1'` → `DIAG hesitation_onset` / `DIAG onset_rms` logs | Built, gated OFF in prod. Re-arm for this story's smoke gate. |

## Acceptance Criteria

1. **Root cause confirmed by diagnostics BEFORE the fix.** With `HESITATION_DIAG`
   armed on both ends, a diagnostic Pixel 9 call distinguishes the two
   under-production hypotheses: (a) the native tap is **dead** (`onset_rms_alive`
   never logs, or `peak_max_rms == 0` for the whole call → `tryAttachCallback`
   never attached) vs (b) the tap **delivers** but the meter never fires
   (`onset_rms_alive` shows `peak_max_rms > 0` and `armed` toggling, yet no
   `hesitation_onset` for a real freeze → seed-window contamination / SNR). The
   fix targets the CONFIRMED cause; the Debug Log records which it was.

2. **The native tap survives a cold record path.** `AudioCaptureChannel.kt::tryAttachCallback`
   no longer fails permanently when `FlutterWebRTCPlugin.sharedSingleton` /
   `recordSamplesReadyCallbackAdapter` are still null at `onListen` (the WebRTC
   record path isn't warm yet): it retries on a bounded schedule and attaches once
   the path warms. A successful late attach is logged; exhausting the retries logs
   the feature UNAVAILABLE (loud, not silent — a silent failure here corrupts DATA,
   not just visuals).

3. **Device accuracy on a GOOD connection.** On a deliberate stopwatch-timed
   freeze in a quiet room, the debrief's longest hesitation reads **within ±0.5 s**
   of the stopwatch (tighter than the hybrid's ±1 s), and that entry carries
   `source: "device"`.

4. **The NOISE money-test.** With steady background noise in the room (a TV or fan
   left on), a real freeze STILL reports a hesitation — **not 0 s, not erased**.
   The steady noise must neither raise the floor so high the onset never fires nor
   collapse the gap to ~0. (Non-stationary noise — TV dialogue / a second talker —
   remains a documented honest limit handled by the server `env_warning` path, not
   this story.)

5. **Graceful fallback preserved + de-aliased.** When NO device gaps arrive (an
   old client build, or the native tap permanently fails), the server
   `HesitationObserver` fallback still produces hesitations. `merge_hesitation_sources`
   returns a **fresh list** in the no-device branch (`return list(server)`, not
   `return server` — kill the latent aliasing).

6. **The teardown merge is actually wired.** `bot.py` teardown calls
   `merge_hesitation_sources(device_hesitation_collector.top_hesitations(),
   hesitation_observer.top_hesitations())` (replacing the bare
   `hesitation_observer.top_hesitations()` at ≈`bot.py:950`). Device gaps are
   authoritative; the server's UNRESOLVED re-speak freezes (C2) are still added;
   `source: "device"` appears in real debrief rows.

7. **Meter correctness fixes.** In `hesitation_meter.dart`: the measured gap is
   clamped to ≥ 0 (a defensive `max(0, …)` so no offset arithmetic can yield a
   negative gap), and the 600 ms `confirmationOffset` inflation is reconciled (kept
   only to the extent the Pixel 9 tuning proves it; the fixed estimate is revisited
   against the ±0.5 s target — AC3). `disarm()` resets the seed/floor accumulators
   (`_seedSum`, `_seedCount`, `_floor`, `_aboveSince`) so a re-arm cannot inherit a
   stale floor. Seed-window contamination is fixed: the floor is seeded ONLY from
   genuine post-character ambient frames (no TTS-tail / pre-arm frame leaks in).

8. **Native + wiring hardening.** `AudioCaptureChannel.kt::rmsOf` honors
   `channelCount` (stereo must not skew SNR). The `call_screen.dart` `onset_rms`
   listener **logs** (does not silently drop) a non-`num` event. `_kRestVisemeId`
   (already doc'd as "REST = mouth closed") gains an explicit note that its literal
   `0` is COUPLED to the Rive viseme id scheme — a future re-id must not silently
   break the arming gate. The native 100 Hz
   `mainHandler.post` flood + post-`onCancel` race is bounded (throttle/guard) so
   it can't starve the main thread or fire after teardown.

9. **Tests re-pinned to LOGIC, not timing-luck.** `hesitation_meter_test.dart`
   `seedFloor` / `arm-idempotent` cases assert the seed boundary and re-arm
   semantics by construction (not by a frame count that happens to land on the
   window edge). New tests cover: the gap ≥ 0 clamp, `disarm()` accumulator reset,
   and the floor seeded only from ambient. The MONEY TEST (steady noise → censored,
   never 0) stays green. Server gains a teardown-merge integration test proving
   `merge_hesitation_sources` is called and a `source: "device"` gap flows into
   `persist_debrief`. The `call_screen.dart` non-`num`-event log path is unit-tested.

10. **All gates green.** `cd client && flutter analyze` (No issues) + `flutter test`
    (all pass); `cd server && python -m ruff check .` + `ruff format --check .` +
    `pytest` (all pass, incl. `test_migrations` — no migration here, must stay
    green); **Pixel 9 smoke gate INCLUDING the noise money-test**.

## Tasks / Subtasks

- [ ] **Task 1 — Re-arm diagnostics + confirm the root cause on-device (AC1).** Do this FIRST; the fix follows the evidence.
  - [ ] Build the client with `--dart-define=HESITATION_DIAG=true` (flips `_kHesitationDiag`, enabling the `onset_rms_alive` periodic publish in `call_screen.dart`).
  - [ ] Set server env `HESITATION_DIAG=1` on the VPS (`/opt/survive-the-talk/.env`) and `systemctl restart pipecat.service` (re-arms the `DIAG hesitation_onset` + `DIAG onset_rms` logs in `bot.py`).
  - [ ] Run ONE diagnostic Pixel 9 call with a deliberate ~6 s freeze; `journalctl -u pipecat.service` and classify: tap-dead (no `onset_rms_alive` / `peak_max_rms == 0`) vs meter-silent (`peak_max_rms > 0`, `armed` toggling, but no `hesitation_onset`). Record the verdict in the Debug Log. (This is an agent-run call ONLY if the agent can place it; otherwise it folds into the Pixel 9 smoke gate as the first call — see the smoke script.)

- [ ] **Task 2 — Fix the native record-side tap (AC2, AC8).** `AudioCaptureChannel.kt`.
  - [ ] In `tryAttachCallback`, replace the one-shot soft-fail with a **bounded retry**: when `sharedSingleton` / `methodCallHandler` / `recordSamplesReadyCallbackAdapter` is still null, re-post the attach on `mainHandler` with a short backoff (e.g. ~100–250 ms) up to a capped number of attempts; stop on first success. Keep the existing `attachedCallback != null` idempotency guard. Log a successful LATE attach at INFO and exhaustion at WARN/ERROR ("onset tap UNAVAILABLE — server fallback covers hesitations").
  - [ ] `rmsOf` honors `channelCount`: don't treat interleaved stereo as mono (de-interleave or average channels) so the RMS — and thus the SNR the Dart meter computes — isn't skewed.
  - [ ] Bound the per-frame `mainHandler.post` so a 100 Hz flood can't starve the main thread, and guard against a `post` landing after `onCancel`/`stopListening` (the `eventSink` null-check exists; ensure no posted runnable references a stale sink). Throttle only the DELIVERY cadence — never coalesce in a way that hides onset energy.

- [ ] **Task 3 — Fix the Dart onset detector (AC1, AC4-noise, AC7).** `hesitation_meter.dart`.
  - [ ] Clamp the emitted gap to ≥ 0 (`max(0, gap)`) on BOTH the measured (`onHesitation(... gapMs: gap …)`) and censored (`now - _gapStartTime`) paths — defensive against any future offset arithmetic.
  - [ ] `disarm()` resets `_seedSum`, `_seedCount`, `_floor`, `_aboveSince` (today it only sets `_state = idle`, leaving stale accumulators for the next `arm()`).
  - [ ] Eliminate seed-window contamination: ensure the floor is seeded ONLY from genuine post-character ambient frames (the echo-tail/seed guard already blocks onset during seeding — verify no pre-arm or TTS-tail frame can enter `_seedSum`, and that the seed window length vs the real REST-confirmation timing doesn't ingest the character's decaying audio). If the diagnostics (Task 1) prove contamination is the cause, this is THE fix.
  - [ ] Reconcile the 600 ms `confirmationOffset`: keep it only to the extent the Pixel 9 tuning (Task 7) shows it makes the gap reflect the FELT pause; the fixed estimate is the prime suspect for the ±0.5 s accuracy AC. Document the final value + why.
  - [ ] Reconcile the threshold/minGap semantics: the client emits at `minGap = 3 s` but the server `DeviceHesitationCollector` threshold is 4.0 s (and `HesitationObserver` is 4.0 s). A 3–4 s device gap is emitted then dropped server-side. Either align the client `minGap` to 4 s or document the intentional margin (and fix the stale "matches `minGap`" docstring in `device_hesitation_collector.py` and the "2 s < 3 s threshold" test comment).

- [ ] **Task 4 — Harden the client wiring (AC8).** `call_screen.dart`.
  - [ ] The `onset_rms` `EventChannel` listener currently silently ignores a non-`num` event (`if (event is num)`); add an `else` that `dev.log`s the unexpected type (gated like the other `call.onset` diagnostics) so a future native contract change surfaces.
  - [ ] `_kRestVisemeId = 0` already has a doc comment ("REST = mouth closed → any other id = character speaking → disarm"); ADD the explicit coupling warning — the literal `0` is bound to the Rive viseme id scheme, so a future Rive re-id silently breaks the arming gate. (Optional: reference the single source of the REST id rather than re-hardcoding it.)

- [ ] **Task 5 — Wire the teardown merge (AC5, AC6).** `bot.py` + `device_hesitation_collector.py`.
  - [ ] In `device_hesitation_collector.py::merge_hesitation_sources`, change the no-device branch `return server` → `return list(server)` (de-alias — the caller must not mutate the observer's internal list).
  - [ ] In `bot.py` teardown (the `persist_debrief(... hesitations=hesitation_observer.top_hesitations() …)` call at ≈L950), replace the argument with `merge_hesitation_sources(device_hesitation_collector.top_hesitations(), hesitation_observer.top_hesitations())`. Update the now-stale "stays wired but DORMANT" comment block (≈L941-949) to describe the LIVE device-authoritative behavior. Keep the whole thing inside the existing `try/except` (a hesitation-merge failure must never crash teardown).

- [ ] **Task 6 — Tests (AC9).**
  - [ ] `hesitation_meter_test.dart`: re-pin `seedFloor` and `arm-idempotent` to assert by logic; add gap-≥-0-clamp, `disarm()`-resets-accumulators, and floor-seeded-only-from-ambient tests; keep the MONEY TEST green.
  - [ ] `call_screen` (or a focused service test): the non-`num` `onset_rms` event logs rather than silently drops.
  - [ ] Server: extend `test_device_hesitation_collector.py` (de-alias regression — mutating the merge result must not mutate the input `server` list) AND add a teardown-merge integration test that drives a device `hesitation_onset` + a server gap through to `persist_debrief` and asserts a `source: "device"` entry is what gets persisted (mock `persist_debrief`/DB; this closes the "merge never called" review finding with a permanent assertion).

- [ ] **Task 7 — On-device tuning + smoke (AC3, AC4, AC10).**
  - [ ] On the Pixel 9 with `HESITATION_DIAG` armed, tune `confirmationOffset` / `snrThreshold` / `seedWindow` / `debounce` against stopwatch-timed freezes until the debrief reads within ±0.5 s on a good connection.
  - [ ] Run the Pixel 9 smoke gate (script below), INCLUDING the noise money-test (steady TV/fan → a real freeze still reported).
  - [ ] After sign-off: turn `HESITATION_DIAG` back OFF on the VPS (and ship the prod client WITHOUT the dart-define) so prod logs stay clean — the diagnostics are a smoke-gate tool, not a prod feature.

## Smoke Test Gate (Server / Deploy Story)

> This story changes `server/pipeline/bot.py` (the per-call bot subprocess teardown) and requires a VPS deploy + a temporary `HESITATION_DIAG=1` env flip. **No HTTP route changes and NO DB migration** — the new behavior is exercised by a real LiveKit call writing a `debriefs` row, validated on the Pixel 9 gate. Every unchecked box is a stop-ship for `in-progress → review`. Paste real command output as proof.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test, with `HESITATION_DIAG=1` set for the smoke window.
  - _Proof:_ <!-- paste the Active/Main PID line + the env confirmation -->

- [ ] **Device-source proof (replaces the HTTP round-trip box).** After a real device-measured call (quiet room, deliberate freeze), the persisted debrief's hesitations carry `source: "device"`, and journalctl shows the matching `DIAG hesitation_onset gap_ms=… censored=false` line.
  - _Command (read the row):_ <!-- /opt/survive-the-talk/current/server/.venv/bin/python -c 'import sqlite3,json; c=sqlite3.connect("/opt/survive-the-talk/data/db.sqlite"); r=c.execute("SELECT hesitations FROM debriefs ORDER BY id DESC LIMIT 1").fetchone(); print(r[0])' -->
  - _Expected:_ <!-- at least one hesitation with "source":"device" and duration_sec ≈ stopwatch -->
  - _Actual:_ <!-- paste -->

- [ ] **HTTP happy/error envelope boxes — N/A.** No FastAPI route added or changed; the teardown path is not an HTTP endpoint. (Rationale recorded; the device-source box above is the equivalent functional proof.)

- [ ] **DB backup / migration boxes — N/A.** No schema change, no migration; the `debriefs.hesitations` column already exists. `test_migrations` must still pass unchanged.

- [ ] **Server logs clean on the happy path.** `journalctl -u pipecat.service -n 80 --since "5 min ago"` shows the expected `DIAG` lines and NO ERROR / Traceback for the call(s).
  - _Proof:_ <!-- paste tail or "no errors in window" + timestamp -->

## Pixel 9 Smoke Gate — ready-to-play script

> **Agent prep BEFORE Walid calls** (the agent does ALL of this — Walid only places the calls):
> 1. Land the code, run all gates green, commit, deploy to VPS (`pipecat.service` on the new SHA).
> 2. Set `HESITATION_DIAG=1` in `/opt/survive-the-talk/.env` + `systemctl restart pipecat.service`.
> 3. Build the **release APK with `--dart-define=HESITATION_DIAG=true`**; install on the Pixel 9.
> 4. Reset Walid's daily call quota (he needs 2–3 calls) — `infra_reset_daily_call_quota.md`, user_id=1, back up first.
> 5. Reset `user_progress` for the Waiter so the debrief renders fresh.
> 6. Arm the journalctl monitor (`grep -E 'DIAG (hesitation_onset|onset_rms)|Traceback'`). During the calls: **stay silent, monitor only, compile ONE report at the end** (smoke-gate analysis-mode rule).
>
> Responses are approximate — it's a live LLM, not deterministic. The goal is a no-think replay; Walid reads lines, freezes on cue with a stopwatch, watches the HUD + the debrief.

**Scenario to open:** **Order your dinner** (The Waiter) — low-stakes, a pause is natural.

### CALL 1 — Device ACCURACY, quiet room, good Wi-Fi (the primary money moment)
1. Waiter greets ("Good evening, what can I get you?"). → **You: stay COMPLETELY SILENT and start the stopwatch. Hold for ~6 seconds. Then say:** "I'd like the grilled chicken, please."
   - _Expect:_ the waiter waits, then takes the order. **Watch the HUD:** the order checkpoint should tick.
   - **💰 MONEY MOMENT:** your ~6 s silence is the felt freeze.
2. Continue normally to finish the order (a drink, then "that's all, thank you").
3. **After the call, on the debrief:** the longest hesitation should read **≈ 6 s (±0.5 s)**. Tell the agent the stopwatch value. → The agent confirms in journalctl that the gap was `source=device` (`DIAG hesitation_onset gap_ms≈6000 censored=false`) and that the persisted row says `"source":"device"`.

### CALL 2 — NOISE money-test, **TV or fan ON** in the room, good Wi-Fi
1. **Turn on a TV (talk/news at moderate volume) or a fan BEFORE the call** so the room has steady background noise.
2. Waiter greets. → **You: stay SILENT, stopwatch, hold ~6 seconds, then order** ("Can I get the salmon?").
   - **💰 MONEY MOMENT (the noise test):** the steady noise must NOT erase the freeze.
3. Finish the order normally.
4. **Debrief:** the hesitation should STILL show **≈ 6 s** — NOT 0 s, NOT missing. (If it reads ~0 or vanishes, the noise defeated the floor — a FAIL, report it.)

### CALL 3 — OPTIONAL: bad-connection accuracy (the device's whole point)
1. Throttle the link (move to a weak-signal spot or enable a network limiter) and repeat CALL 1's ~6 s freeze.
   - **💰 MONEY MOMENT:** on a bad connection the OLD server hybrid over-states the gap; the device measure should STILL read ≈ 6 s because no network term enters it.
2. **Debrief:** hesitation ≈ 6 s despite the bad link.

**What a PASS looks like:** CALL 1 device gap within ±0.5 s + `source=device`; CALL 2 freeze still reported under steady noise; (CALL 3 if run) still accurate on a throttled link. **Report at the end:** the stopwatch vs debrief delta per call, whether `source=device` appeared, and any tap-dead / meter-silent diagnostic from the logs.

## Dev Notes

### Architecture & data flow (how a device hesitation is born)
1. The character's TTS finishes; the Rive viseme stack's `VisemeScheduler.onSilenceConfirmed` fires (~600 ms after the audio actually ended — the REST-viseme confirmation window). This is the SAME callback that publishes `playback_idle` upstream.
2. `call_screen.dart` `arm()`s the `HesitationMeter` at that moment → gap-start anchored (offset-compensated by `confirmationOffset`).
3. The native `AudioCaptureChannel.kt` streams per-~10 ms-frame mic RMS on `com.surviveTheTalk.client/onset_rms`; `call_screen.dart` feeds each frame to `meter.onMicFrame(rms)`.
4. Any non-REST viseme (character speaks again) → `meter.disarm()` (the arming gate — the character's audio bleeding into the mic can never be read as the user's onset). A re-speak freeze is therefore INVISIBLE to the device; the **server observer** captures it as an UNRESOLVED gap (C2) — which is exactly why the merge ADDS server-unresolved freezes.
5. The meter detects onset by **SNR above an adaptive floor seeded from the known-silent arm window** (NOT an absolute level — this is the structural defeat of "steady noise reads as permanent speech"), confirmed by a ~200 ms debounce. On onset it `onHesitation(HesitationOnset(gapMs, censored:false))`.
6. `_publishHesitationOnset` ships `{"type":"hesitation_onset","gap_ms":…,"censored":…}` over the LiveKit data channel.
7. `bot.py` `on_data_received` → `device_hesitation_collector.record(...)`.
8. At teardown, `merge_hesitation_sources(device, server)` PREFERS device gaps and ADDS server-unresolved freezes → `persist_debrief`.

### The two competing root-cause hypotheses — diagnose, don't assume
- **(Review's "likely"):** `tryAttachCallback` fails soft with NO retry → the meter gets ZERO frames all call → no onset ever. Signature in logs: NO `onset_rms_alive` lines / `peak_max_rms == 0`.
- **(7.5 dev's note):** seed-window contamination → floor seeded too high → onset never clears SNR. Signature: `onset_rms_alive` shows `peak_max_rms > 0` and `armed` toggling, but no `hesitation_onset` on a real freeze.
- **Both may be true** (a dead tap on cold calls AND a contaminated floor on warm ones). Task 1's diagnostic call tells you which to fix first. Don't blind-add a retry and call it done.

### Server-side traps (server/CLAUDE.md — read before touching `bot.py`/observers)
- **§1 / Déviation #28 — FrameProcessor direction/attribute traps.** `HesitationObserver` already dodged the `_clock`-shadow trap by storing its clock as `self._now` (pipecat's base `FrameProcessor` owns `self._clock` and `setup()` clobbers it). If you add ANY new FrameProcessor or instance attribute, do NOT name it after a base attr; prefer a real-pipeline drive test. **You should not need a new FrameProcessor for this story** — the device collector is a plain object, not a processor.
- **§3 — loguru ≠ caplog.** To assert a `DIAG` log in a test, use a temporary loguru sink (`logger.add(list.append)`), not `caplog`.
- **A hesitation-merge failure must never crash teardown.** The merge call stays inside the existing `try/except Exception` in the `finally` block; a missing debrief degrades to `DEBRIEF_NOT_READY`.
- **No migration in this story.** Do NOT add a `server/db/migrations/` file; `debriefs.hesitations` already stores the JSON. `test_migrations` must stay green untouched.

### Client-side traps (client/CLAUDE.md)
- **Token-enforcement test** (gotcha #6): no new hex color literals — none expected here.
- **`pumpAndSettle` hangs on continuous animations** (gotcha #3): the call screen has a live canvas; in any new widget test use explicit `pump(Duration)`.
- **`FlutterSecureStorage.setMockInitialValues({})`** in `setUp` for any call-screen widget test (gotcha #1).
- **Native code is NOT exercised by `flutter test`** — `AudioCaptureChannel.kt` (the retry, the `channelCount` fix) can only be validated on-device. Cover the Dart-testable seams (meter logic, the non-`num` log path) in tests; cover the native seams in the Pixel 9 gate.
- **Keep it fail-soft.** Every device path is best-effort: a missing/erroring native tap, a null `localParticipant`, a data-channel throw — all must degrade to "the server observer covers hesitations", never a crash or a wrong gap. The existing code already does this; preserve it.

### Decisions already locked (Walid 2026-06-16) — do NOT re-litigate
- Device direction ratified; **client-first** sequencing (fix detector → wire merge → smoke).
- The server hybrid (`HesitationObserver` on `playback_idle`) **stays as the fallback — never remove it**.
- Trade-off accepted: device = network-immune timing (the win, esp. on bad connections); onset DETECTION is noise-fragile (the hard part). Non-stationary noise stays a documented honest limit (server `env_warning` path + a future on-device VAD upgrade), NOT in scope here.
- The "gate the whole client machinery OFF in prod vs leave it running as the foundation" question from the 7.5 review is **settled by the client-first ratification**: leave it running — it IS the foundation this story makes reliable.

### Previous-story intelligence (7.5)
- 7.5 pivoted the LIVE source to the server `HesitationObserver` re-anchored on `playback_idle` (commits `5498388` "anchor on playback_idle (no inflation)", `208185e` "threshold 3s→4s") because the device source over-stated gaps and merging an unreliable device source DROPPED accurate server gaps. That pivot is WHY this story must make the device source reliable BEFORE flipping the merge on — wiring the merge against an under-producing detector would regress coverage.
- 7.5 left precise review breadcrumbs (all in `7-5-overhaul-debrief-report.md` "Review Findings — Client" + `deferred-work.md`): the 9 client specifics (no-retry attach, gap inflation/clamp, `channelCount`, 100 Hz post flood + cancel race, `disarm()` accumulators, silent non-`num` drop, `_kRestVisemeId` magic, timing-luck tests, machinery-gating decision) ARE this story's task list.
- The DIAG plumbing 7.5 left in place (`onset_rms_alive` client publish, `DIAG hesitation_onset`/`DIAG onset_rms` server logs, both behind `HESITATION_DIAG`) is the instrument for Task 1 — it exists specifically so this follow-up can localize the failure on-device.

### Git intelligence (recent commits)
`64bb990` docs: story 7.5 review→done + Epic 7 complete · `f3c83d0` checkpoint sheet fixes · `ebfcf5e` debrief polish · `e068a20` smoke-script align · `e84a24e` 7.5 client code-review patches. The 7.5 client review patches (`e84a24e`) are the patches that DEFERRED the device-meter bundle here — read that diff for the exact lines already touched vs. left for this story.

### Project Structure Notes
- All touched files exist; no new modules required. Server change is a 1-line teardown swap + a 1-word de-alias + a stale-comment refresh. Client change is localized to `hesitation_meter.dart`, `AudioCaptureChannel.kt`, and a small `call_screen.dart` logging seam.
- Server change deploys via the normal VPS path (`systemctl restart pipecat.service`); the warm bot-pool (`bot_pool.py`) re-imports `bot.py` on restart, so the teardown change takes effect on the next call. No migration, no `prod_snapshot` refresh.
- `HESITATION_DIAG` is a smoke-gate-only flag on BOTH ends — it must be OFF in prod after sign-off (Task 7).

### References
- Origin / decisions: [deferred-work.md](_bmad-output/implementation-artifacts/deferred-work.md) "Device-authoritative hesitation measurement = follow-up story" (+ the Group-2 client-review specifics); [7-5-overhaul-debrief-report.md](_bmad-output/implementation-artifacts/7-5-overhaul-debrief-report.md) "Review Findings — Client", "D3-c architecture" SHIPPED-DELTA, Task 2.0 noise-robustness ADDENDUM.
- Requirement: [prd.md:429](_bmad-output/planning-artifacts/prd.md) FR12 "Debrief highlights longest hesitation moments and their context"; [prd.md:258](_bmad-output/planning-artifacts/prd.md) the Sofia debrief-hesitation narrative.
- Spec authority: [debrief-content-strategy.md](_bmad-output/planning-artifacts/debrief-content-strategy.md) Q6 (top-3 longest gaps, threshold).
- Foundation code: [device_hesitation_collector.py](server/pipeline/device_hesitation_collector.py), [hesitation_observer.py](server/pipeline/hesitation_observer.py), [hesitation_meter.dart](client/lib/features/call/services/hesitation_meter.dart), [AudioCaptureChannel.kt](client/android/app/src/main/kotlin/com/surviveTheTalk/client/AudioCaptureChannel.kt), [call_screen.dart](client/lib/features/call/views/call_screen.dart) (`_startHesitationMeter` ≈L500, arming gate ≈L700, `_publishHesitationOnset` ≈L567), [bot.py](server/pipeline/bot.py) (`on_data_received` ≈L842, teardown merge point ≈L950).
- Existing tests: [test_device_hesitation_collector.py](server/tests/test_device_hesitation_collector.py), [hesitation_meter_test.dart](client/test/features/call/services/hesitation_meter_test.dart).
- Traps: [server/CLAUDE.md](server/CLAUDE.md) §1 (FrameProcessor direction/attribute), §3 (loguru sink); [client/CLAUDE.md](client/CLAUDE.md) #1/#3/#6/#7.

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

<!-- Task 1: record the diagnostic verdict — tap-dead vs meter-silent — with the journalctl evidence. -->

### Completion Notes List

### File List
