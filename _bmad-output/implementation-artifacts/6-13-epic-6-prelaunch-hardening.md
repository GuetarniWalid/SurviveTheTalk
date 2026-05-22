# Story 6.13: Epic 6 Pre-Launch Hardening

Status: ready-for-dev

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As the operator (Walid),
I want every HIGH-priority pipeline finding surfaced during Story 6.9b's smoke gate (and pre-existing 🚨 items from earlier reviews) fixed in one focused pass,
so that (a) the call pipeline stops freezing ~30% of the time on multi-frame Tina responses (the Cartesia silent-stall bug that killed call_id=149 + 151 during Pixel 9 smoke), (b) the silence ladder no longer fires "Are you still there?" prompts while Tina is actively speaking, (c) the visual impatience-shift threshold becomes difficulty-aware instead of hardcoded 3 s, (d) the auth 401 silent-loop gap (must-fix-before-MVP-launch from Story 5.5) closes, (e) classifier debug logs that leak STT-transcribed user text get removed pre-launch, (f) the Waiter `clarify` checkpoint stops penalising legitimate drink answers, and (g) Stories 6.10/6.11/6.12 can smoke-test on a stable pipeline instead of one with a known 30 % freeze rate.

## Background

**Direct successor of Story 6.9b's Pixel 9 smoke gate (2026-05-26).** The smoke gate validated the Groq classifier migration's core delivery (Boxes 1-3+5+6 all pass — Groq 121/320 ms p50/p95 VPS, 98.7 % accuracy, 0 false positives, classifier robust to café-noisy + off-topic). But 4 findings surfaced during the 3 calls that are **pre-existing pipeline bugs**, NOT Story 6.9b regressions:

1. **🚨🚨 Cartesia silent stall — pipeline freezes for 13-15 s, then user hangs up.** Reproduced 2× across different scenarios (call_id=149 café-noisy attempt + call_id=151 off-topic Mode A). Identical signature: Cartesia logs `Generating TTS [...]` for a multi-frame Tina response, but the `cleaning up TTS context <uuid>` debug line that normally fires ~1.2 s later **never appears**. No `tts_first_audio` LatencyProbe, no `TTSStoppedFrame`, no `bot_speaking_ended`, no `playback_idle` from client, no WARNING, no Traceback, no WebSocket disconnect. Pipeline soft-locks until user disconnects manually. Repro rate ~30 % on multi-frame Tina responses. **MVP-launch BLOCKER** — every third call becomes unusable.
2. **🟠 Silence ladder ticks against the user while the bot is speaking.** `PatienceTracker._run_silence_ladder` doesn't cancel on `BotStartedSpeakingFrame`. Smoke gate call_id=150 T6: ladder started at 07:50:39.498 (client `playback_idle` for prior turn), but at 07:50:39.690-816 Cartesia generated + emitted Tina's response — and the ladder kept counting. Stage 1 visual impatience fired at 42.500 while Tina was mid-sentence; stage 2 verbal prompt "Hello? Are you still there?" fired at 45.501, cutting Tina off. Walid (ground truth) was actively listening + about to respond. Pre-existing since Story 6.4.
3. **🟠 `_LADDER_IMPATIENCE_AT = 3.0` hardcoded module-level constant is too aggressive UX-wise.** Smoke gate call_id=148 T6+T7: visual `impatience@0.5` Rive enum fired exactly 3.00 s after `playback_idle`, even though Walid was actively formulating his response. 3 s window covers (a) parse Tina's last sentence ~0.5-1 s, (b) formulate answer ~0.5-1 s, (c) start articulating — natural response time is 1.5-2.5 s **after** perception, so the threshold should be 4-5 s minimum to feel respectful. Pre-existing since Story 6.4.
4. **🟡 Waiter `clarify.success_criteria` misaligned with Tina's drink-clarify prompt.** Tina asks "What about a drink? Water, juice, cola, or coffee?" at the `clarify` checkpoint, but the criteria requires a CONFIRMATION-style answer ("yes/that's right/correct"), not a new drink choice. So a user saying "cola" (literally one of the menu options Tina just offered) gets classified as `False`. Reproduced in call_id=148 T3 ("Uh, cola." → False) and call_id=151 T5 ("Water." → False). Pre-existing scenario calibration from Story 3.2 + Story 6.8 calibration pass.

PLUS one pre-existing 🚨 item from Story 5.5 (2026-04-29) tagged `MUST-FIX BEFORE MVP LAUNCH` at the top of `deferred-work.md`:

5. **🚨 Auth 401 silent loop.** The Flutter client today does not handle a 401 from any backend endpoint gracefully — there is no Dio interceptor that traps 401 and routes the user to re-authentication. If a JWT expires mid-session OR is invalidated server-side, every subsequent request fails silently and the user sees stale UI without understanding why. Flagged as MUST-FIX before MVP launch in Story 5.5 review (2026-04-29) — open ~1 month at story-draft time.

AND one pre-existing 🟠 item from Story 6.9b review D6 (carry-over) that Walid agreed to defer at the time but flagged for Story 6.10 close:

6. **🟠 Remove verbose `classifier_input` / `classifier_output` DEBUG logs from `exchange_classifier.py` before public launch.** Two `logger.debug()` calls emit raw user transcription (`user_text`) + first 80 chars of `success_criteria` + first 80 chars of `last_character_line` + verdict + first 120 chars of raw classifier response on EVERY classify call. DEBUG-level so they're inert unless `LOG_LEVEL=DEBUG` is flipped, but raw `user_text` is PII-equivalent. Originally kept to help Story 6.10 (goal-based dialogue) debugging — now bundled into this hardening pass since Story 6.10 is queued AFTER 6.13.

**The strategic framing that justifies this story's existence and its priority position:**

- Walid 2026-05-26 explicit ask after seeing the Cartesia freeze reproduce on call_id=151: "donc là, on va enquêter, puis on va faire ça en priorité. Si les stories d'après ne règlent pas ce souci, il va falloir le faire dans cette épique. Il faut que, à la fin de cette épique, on ait un appel normal."
- Stories 6.10 (goal-based dialogue), 6.11 (noisy-environment detection), 6.12 (reactive character mood) all touch different parts of the pipeline (CheckpointManager, Soniox, EmotionEmitter) but **none** touch Cartesia TTS or the silence ladder logic. Without this hardening pass, each of 6.10/6.11/6.12 would smoke-test on a pipeline that freezes 30 % of the time — debug becomes impossible (is the failure mine or the latent Cartesia bug?).
- The MVP launch readiness requires "a normal call works end-to-end on real device" — currently it works 70 % of the time. That's not shippable.

**Hard prerequisite chain:**
- ✅ Story 6.9b (Groq classifier migration) — done 2026-05-26
- ⏳ Story 6.13 (this story) — ready-for-dev
- 🔒 Story 6.10 (goal-based dialogue) — repositioned to AFTER 6.13 (was queued after 6.9b directly; now blocked on stable pipeline)
- 🔒 Story 6.11 (noisy-environment detection) — blocked on 6.10
- 🔒 Story 6.12 (reactive character mood) — blocked on 6.10

**Critical reading before starting:**
- `_bmad-output/implementation-artifacts/deferred-work.md` heading "Deferred from: Story 6.9b Pixel 9 smoke gate (2026-05-26)" — the 4 findings with their full diagnostic logs
- `_bmad-output/implementation-artifacts/deferred-work.md` ⚠️ MUST-FIX section at the top — auth 401 entry
- `server/pipeline/patience_tracker.py:127` — the hardcoded `_LADDER_IMPATIENCE_AT = 3.0`
- `server/pipeline/patience_tracker.py:494-560` — the `_cancel_silence_timer` + `handle_playback_idle` paths that lack `BotStartedSpeakingFrame` cancel
- `server/pipeline/scenarios/the-waiter.yaml` — the `clarify` checkpoint block
- `pipecat.services.cartesia.tts:run_tts` (upstream pipecat source) — the TTS call site that silently stalls
- `client/lib/services/api_client.dart` (or wherever Dio is configured) — for AC4 401 interceptor

**Up-front deviations to document in Implementation Notes:**

1. **(Deviation #1) Cartesia stall mitigation is defensive watchdog, NOT root-cause fix.** We do not yet know whether the bug is upstream Cartesia (server-side WebSocket buffer issue under rapid multi-frame requests) or in pipecat 0.0.108's `CartesiaTTSService.run_tts` (race when ≥3 text frames queue within ~150 ms). The root-cause investigation requires a packet capture of a known-repro Cartesia WebSocket session, which is dev-environment work that can run in parallel. **In the meantime**, AC1 ships a wall-clock timeout + synthetic `TTSStoppedFrame` emission so the pipeline unblocks within 5 s instead of soft-locking until user disconnect. This is a **mitigation that makes the bug recoverable**, not a fix that prevents it from happening. The investigation continues post-launch — a clean fix (root-cause identified + patched upstream OR replaced with alternative TTS) is tracked as a follow-up Story 6.13b OR rolled into the post-MVP voice-pipeline UX tuning pass.
2. **(Deviation #2) Silence ladder cancel-on-bot-speaking is the simpler of 2 options.** Two valid fixes for finding #2: (a) cancel the ladder on `BotStartedSpeakingFrame` and re-arm on the NEXT `playback_idle`, (b) suppress `playback_idle` from arming the ladder if there's a pending LLM generation in flight. Option (b) is more architecturally complete (no spurious ladder start) but needs a frame-flow signal (`LLMGenerationStartedFrame` or equivalent) which doesn't exist as a first-class pipecat frame. Option (a) is one bool flag + an `isinstance(frame, BotStartedSpeakingFrame)` check in `PatienceTracker.process_frame` — minimal blast radius. **Going with option (a).** If pipecat upstream adds an LLM-generation-pending frame later, we can migrate.
3. **(Deviation #3) `_LADDER_IMPATIENCE_AT` becomes per-difficulty via `_DIFFICULTY_PRESETS`, NOT a global constant.** Existing pattern in `scenarios.py:_DIFFICULTY_PRESETS` already maps difficulty → `silence_prompt_seconds` / `silence_hangup_seconds`. Adding `ladder_impatience_seconds` follows the same shape (easy=4.5, medium=3.5, hard=2.5). Per-scenario override stays optional via `metadata.ladder_impatience_seconds` (null = use preset). This is the difficulty-aware approach — harder scenarios get visibly more impatient characters who shift face faster, which matches the "Mugger should be impatient by design" semantic.
4. **(Deviation #4) Auth 401 fix is Dio interceptor, NOT a per-screen retry pattern.** Cross-cutting Dio interceptor that catches HTTP 401 from any backend response, calls a single `_handleAuthFailure()` handler that (a) clears local JWT, (b) navigates the user to the onboarding/login flow with a brief "Session expired, please sign in again" toast. NOT a per-screen try/catch — that would mean 20+ touch points and easy to miss one. The Dio approach is one interceptor + one navigation handler, consistent everywhere.
5. **(Deviation #5) Classifier debug logs are DELETED, not gated.** Walid 2026-05-22 D6 resolution kept them in place with corrected `deferred-work.md` framing ("delete at Story 6.10 close"). Story 6.13 supersedes that scheduling — the logs ship to prod **with this story**, so they get deleted **with this story**. If a Story 6.10 dev session genuinely needs the trace, the dev can re-add them locally on a feature branch without committing.
6. **(Deviation #6) Waiter `clarify.success_criteria` audit may overlap with Story 6.10's classifier rewrite.** Story 6.10 changes the CheckpointManager from linear state-machine to goal-tracking — at which point per-checkpoint `success_criteria` may be rephrased or merged. To avoid double-work, AC6 here scopes to **a minimal Waiter-only fix that unblocks the smoke gate** (accept drink answers at `clarify` if the prior Tina line offered drink options). Full scenario calibration remains deferred to the post-MVP voice-pipeline UX tuning pass (`deferred-work.md` line 451 area).
7. **(Deviation #7) Smoke gate is 3 calls × `reason=survived`, not the full 7-box gate from prior stories.** Story 6.13's purpose is to validate that the pipeline is stable across the calm + café + off-topic dimensions Walid already exercised. The 3-call smoke is sufficient — if all 3 complete to `reason=survived` with zero freeze AND zero unexpected silence-ladder firings DURING bot speech, the hardening pass closes. Full per-scenario calibration (Pass A/B for the 5 scenarios) stays deferred.

## Acceptance Criteria (BDD)

**AC1 — Cartesia silent-stall watchdog: pipeline never hangs >5s after a TTS request:**

Given `CartesiaTTSService.run_tts(text="...")` is called via the normal pipeline flow (LLM streams text frames → TTS converts to audio frames)

When the upstream Cartesia WebSocket fails to emit any audio frame within `5.0` seconds of the request being sent (the silent-stall failure mode reproduced in call_id=149 + 151)

Then a new `TTSWatchdog` processor wraps `CartesiaTTSService` output and emits a synthetic `TTSStoppedFrame` after the 5-second wall-clock timeout, logs a structured WARN `cartesia_tts_watchdog_fired reason=no_audio_within_5s context_id=<uuid> text_first_40_chars=<...>`, and the pipeline downstream observes `bot_speaking_ended` as if the TTS had completed normally — the user gets silence on their device, but the silence ladder can fire next turn, the conversation can continue, the call does NOT soft-lock

And the watchdog fires a maximum of once per turn (idempotent) so a downstream observer that re-emits `TTSStartedFrame` doesn't re-trigger the timeout

And the prod path under nominal conditions (Cartesia responds in <1s as normal) sees zero overhead — the watchdog only ARMS on `Generating TTS [...]` and cancels itself on the first `OutputAudioRawFrame` reaching the downstream `LatencyProbe` position

And a new test `test_cartesia_watchdog_emits_synthetic_TTSStoppedFrame_on_5s_timeout` drives a mocked TTS service that never emits audio, asserts the watchdog fires + the synthetic `TTSStoppedFrame` reaches the downstream, and the test completes within 6 seconds (5s watchdog + 1s assertion margin)

**AC2 — Silence ladder pauses while bot is speaking:**

Given the `PatienceTracker` silence ladder has been armed by a `playback_idle` envelope from the client

When a `BotStartedSpeakingFrame` arrives UPSTREAM (per the same direction-test pattern as `bot_stopped_speaking` — Pipecat 0.0.108's `BaseOutputTransport` pushes BSF in both directions, `PatienceTracker` only sees UPSTREAM)

Then the silence ladder is **paused** (current ladder task cancelled, but the patience meter unchanged — the ladder will re-arm on the NEXT `playback_idle` after the bot finishes speaking)

And no stage 1 visual impatience fires while the bot is mid-sentence

And no stage 2 verbal prompt ("Hello? Are you still there?") fires while the bot is mid-sentence

And the regression test `test_silence_ladder_pauses_on_BotStartedSpeakingFrame` drives the exact sequence from call_id=150 (T5 user speaks → playback_idle → ladder armed → bot starts speaking → ladder cancelled → bot finishes → playback_idle → ladder re-armed) and asserts stage 1 never fires during the bot-speaking window

**AC3 — `_LADDER_IMPATIENCE_AT` becomes difficulty-aware:**

Given `_DIFFICULTY_PRESETS` in `server/pipeline/scenarios.py` currently maps difficulty → `silence_prompt_seconds` / `silence_hangup_seconds` / etc.

When `Story 6.13` adds a new `ladder_impatience_seconds` key to each preset (easy=4.5, medium=3.5, hard=2.5) and adds the matching nullable override key to the scenario YAML metadata schema (`ladder_impatience_seconds: int | None`)

Then the `PatienceTracker.__init__` accepts a new required kwarg `ladder_impatience_seconds: float` (matching the existing `silence_prompt_seconds` pattern), the module-level `_LADDER_IMPATIENCE_AT = 3.0` constant is **deleted**, and `_run_silence_ladder` reads `self._ladder_impatience_seconds` instead

And `bot.py` threads `ladder_impatience_seconds=patience_config["ladder_impatience_seconds"]` from the resolved config (existing pattern from Story 6.4)

And the Waiter scenario (`waiter_easy_01`, difficulty `easy`) uses the new default 4.5s — Walid's natural-response-time finding from call_id=148 is respected on the easy scenarios

And test `test_ladder_impatience_seconds_threaded_from_yaml_through_patience_tracker` asserts the easy preset's 4.5 value reaches `PatienceTracker._ladder_impatience_seconds`

**AC4 — Auth 401 silent loop closes via Dio interceptor:**

Given the Flutter client today does not gracefully handle HTTP 401 from any backend endpoint (Story 5.5 review 2026-04-29 finding, ~1 month open)

When Story 6.13 adds a new `AuthInterceptor` (or extends the existing Dio configuration in `client/lib/services/api_client.dart` or equivalent) that catches every `DioException` with `response?.statusCode == 401`

Then the interceptor (a) clears the local JWT token from secure storage, (b) navigates to the onboarding/email-auth screen via the root navigator (using the same key pattern as Story 6.1 incoming-call routing), (c) shows a one-shot SnackBar / toast with copy "Session expired, please sign in again" (English; respects content_warning copy register from Story 5.4)

And the interceptor is idempotent: if a 401 fires while the user is ALREADY on the onboarding screen, no additional navigation + no duplicate toast

And the regression test (Flutter widget test) `test_auth_interceptor_routes_to_login_on_401` mocks a 401 response on a protected endpoint and asserts the navigator pop count + the SnackBar appearance

And the live in-app behavior is validated on Pixel 9 Pro XL during AC7 smoke gate (Box 4 — "401 on stale JWT routes user to login")

**AC5 — Classifier debug logs deleted from `exchange_classifier.py`:**

Given the two `logger.debug(...)` calls in `server/pipeline/exchange_classifier.py::_classify` (the `classifier_input` + `classifier_output` traces with raw `user_text` / `success_criteria` / `last_character_line` / verdict / raw model response)

When Story 6.13 deletes both `logger.debug` statements outright + removes the 8-line comment block explaining the ⚠️ TODO Story 6.10 carry-over

Then `LOG_LEVEL=DEBUG` on the VPS never emits user transcriptions to the journal, PII surface closes for good, and the deferred-work entry "Delete the two classifier_input / classifier_output DEBUG logs from exchange_classifier.py" gets RETIRED in `deferred-work.md`

And no existing test references those log lines (verified pre-edit), so test count delta = 0 for this AC

**AC6 — Waiter `clarify.success_criteria` accepts drink answers when Tina's prior line offered drinks:**

Given the Waiter scenario YAML at `server/pipeline/scenarios/the-waiter.yaml` `checkpoints[clarify].success_criteria` currently requires a CONFIRMATION-style answer ("yes / that's right / correct / no change")

When Story 6.13 amends the criteria to ALSO accept drink answers (Water / Juice / Cola / Coffee + common synonyms — Coke / Pepsi / Sprite already accepted from Story 6.8 calibration of the `drink` checkpoint, mirror into `clarify` too)

Then the smoke gate replay (user says "Cola" or "Water" at the `clarify` checkpoint in response to Tina's "What about a drink? Water, juice, cola, or coffee?") classifies as `True` → patience advance + recovery bonus

And the regression test (new `test_waiter_clarify_accepts_drink_answer_after_drinks_offered` in `test_scenarios.py` or equivalent) loads the Waiter YAML + asserts the updated criteria string contains a drink-accepting phrase

**AC7 — Pixel 9 Pro XL smoke gate: 3 calls all `reason=survived` with zero freeze + zero spurious silence-ladder during bot speech:**

Given the server is deployed with all AC1-AC6 changes live + `LATENCY_PROBE=1` set on `/opt/survive-the-talk/.env`

When Walid runs 3 calls on Pixel 9 Pro XL through The Waiter scenario:

  - **Call A — Calm-room happy-path** — same parcours as call_id=148 (`greet → main_course → clarify → drink → confirm → close`), all on-topic answers, no intentional silence

  - **Call B — Café-noisy retry** — same parcours under cafe-bondé audio (iPad video at modest volume, simulating real-world noise)

  - **Call C — Off-topic Mode A** — 2 off-topic turns ("What's the weather today?" + "Tell me a joke") then recovery on greet ("I would like to order"), then on-topic to close

Then **ALL 3 calls complete with `reason=survived`** (no `user_hung_up`, no `character_hung_up`, no `inappropriate_content`, no `network_lost`)

And **zero `cartesia_tts_watchdog_fired` log entries** appear in `journalctl` across the 3 calls (i.e. the underlying Cartesia stall did not reproduce — OR if it did, the watchdog fired and the call still completed cleanly per AC1)

And **zero "Hello? Are you still there?" verbal prompts** fire while Tina is mid-sentence (per AC2)

And **zero stage 1 visual impatience@0.5 events** fire under 4.5 seconds after the previous `playback_idle` (per AC3 easy preset 4.5s)

And `journalctl | grep -iE "error|traceback|exception"` returns ZERO matches across the 3-call window (no new errors introduced by Story 6.13 changes)

And the 401 path is independently validated (Box 4): manually invalidate the JWT (DB update or wait for natural expiry), make any backend request, observe app routes to login screen + toast

## Smoke Test Gate

> **Transition rule:** Every unchecked box below is a stop-ship for the `in-progress → review` transition. Paste the actual command run and its output as proof — a checked box without evidence does not count.

- [ ] **Box 1 — Deploy:** `git push origin main` triggers CI/CD; `systemctl status pipecat.service` shows `active (running)` on new SHA; `journalctl --since '<deploy time>' | grep -iE "error|traceback|exception"` returns ZERO matches
- [ ] **Box 2 — Cartesia watchdog inert on happy path:** Call A (calm-room happy-path) completes without any `cartesia_tts_watchdog_fired` log entries (the watchdog is armed but never fires when Cartesia behaves)
- [ ] **Box 3 — Cartesia watchdog fires on simulated stall:** Server-side unit test `test_cartesia_watchdog_emits_synthetic_TTSStoppedFrame_on_5s_timeout` passes locally + on CI
- [ ] **Box 4 — Silence ladder pause on bot speech:** Call A T6 (where Tina has a multi-frame response) — no stage 1 visual impatience event in `journalctl` during the bot-speaking window
- [ ] **Box 5 — `_LADDER_IMPATIENCE_AT` 4.5s respected on easy:** Call A — first stage 1 visual impatience event (if any) fires AT LEAST 4.5 seconds after the preceding `playback_idle` (per the new easy preset)
- [ ] **Box 6 — Waiter clarify accepts drink answer:** Call A T(`clarify`) — user says "Cola" or "Water" → classifier verdict `True` → patience advance
- [ ] **Box 7 — All 3 calls `reason=survived`:** Calls A + B + C — `journalctl | grep call_ended` shows `reason=survived` for all 3 entries
- [ ] **Box 8 — Auth 401 routes to login:** Manually invalidate JWT (DB UPDATE `users SET jwt_hash = NULL WHERE id = 1`), open the app, attempt any API call (scenarios list, call init, etc.) — app routes to onboarding/email-auth screen with toast "Session expired, please sign in again"
- [ ] **Box 9 — Classifier DEBUG logs deleted:** `journalctl | grep classifier_input` returns ZERO matches even with `LOG_LEVEL=DEBUG` (verifies AC5 deletion)

## Tasks / Subtasks

- [ ] **Task 1 — Cartesia silent-stall watchdog** (AC1)
  - [ ] 1.1 — Investigate Cartesia stall root cause: capture a packet trace of a known-repro WebSocket session (use `mitmproxy` or `wireshark` against `api.cartesia.ai` from the VPS while running a smoke call). Document findings in `_bmad-output/implementation-artifacts/calibration-tests/cartesia-stall-investigation-<date>.md`. If root cause is identified upstream (pipecat or Cartesia API bug), file an issue against the relevant project + link from here. **Investigation does NOT block AC1 watchdog ship** — watchdog is the mitigation, root-cause-fix is a follow-up.
  - [ ] 1.2 — Design `TTSWatchdog` processor (new file `server/pipeline/tts_watchdog.py`, ~120 LOC): observes `TTSStartedFrame` (or equivalent — the first Cartesia activity marker), arms a `asyncio.Task` that sleeps 5.0s then emits a synthetic `TTSStoppedFrame` + structured WARN log. Cancels the task on first `OutputAudioRawFrame` reaching the watchdog. Idempotent — fires max once per turn (track via `_fired_this_turn` flag, reset on `BotStoppedSpeakingFrame`).
  - [ ] 1.3 — Wire `TTSWatchdog` in `bot.py` pipeline between `CartesiaTTSService` output and the existing `LatencyProbe` (`tts_first_audio` instance). The watchdog must sit AFTER Cartesia's output so it observes the same audio-frame timing the probe does.
  - [ ] 1.4 — New test `test_cartesia_watchdog_emits_synthetic_TTSStoppedFrame_on_5s_timeout` in new `server/tests/test_tts_watchdog.py` — drives a MockTransport that responds 200 to the TTS request but never emits audio. Asserts: synthetic `TTSStoppedFrame` reaches downstream within 5.1s, WARN log captured via loguru sink, test completes <6s total.
  - [ ] 1.5 — Sanity test `test_cartesia_watchdog_inert_on_normal_completion` — normal Cartesia mock that emits audio within 100ms → watchdog cancelled, no synthetic frame, no WARN.

- [ ] **Task 2 — Silence ladder pause on `BotStartedSpeakingFrame`** (AC2)
  - [ ] 2.1 — In `PatienceTracker.process_frame`, add a `isinstance(frame, BotStartedSpeakingFrame) and direction == FrameDirection.UPSTREAM` branch that calls `self._cancel_silence_timer()` (or a new `self._pause_silence_timer()` if we want to preserve the patience meter — TBD during dev; semantic is identical since the next `playback_idle` re-arms anyway).
  - [ ] 2.2 — Cross-reference contract test: read source text of both `pipecat.transports.base_output:_bot_started_speaking` (BSF emission site) and `patience_tracker.py:process_frame` (BSF consumption site), assert they agree on direction (UPSTREAM) — same pattern as the existing `test_BSF_direction_matches_pipecat_emission_routing` for `BotStoppedSpeakingFrame`. New test `test_silence_ladder_pauses_on_BotStartedSpeakingFrame_via_real_pipeline_drive` drives a `BotStartedSpeakingFrame` through a real Pipeline + PipelineTask + PipelineRunner mid-ladder-active state, asserts the ladder task is cancelled.

- [ ] **Task 3 — `_LADDER_IMPATIENCE_AT` configurable per difficulty** (AC3)
  - [ ] 3.1 — Delete the module-level `_LADDER_IMPATIENCE_AT = 3.0` constant in `patience_tracker.py:127`.
  - [ ] 3.2 — Add `ladder_impatience_seconds: float` required kwarg to `PatienceTracker.__init__` (between `silence_prompt_seconds` and `total_checkpoints` parameters per the existing call signature). Store as `self._ladder_impatience_seconds`. Update `_run_silence_ladder` to use `self._ladder_impatience_seconds` instead of the deleted constant.
  - [ ] 3.3 — Update `_DIFFICULTY_PRESETS` in `scenarios.py`: easy=4.5, medium=3.5, hard=2.5 for the new `ladder_impatience_seconds` key.
  - [ ] 3.4 — Add `ladder_impatience_seconds: int | None` to the scenario YAML override schema (`models/schemas.py` ScenarioMetadata model + `db/queries.py` insert/update statements + `db/seed_scenarios.py` reader + `api/routes_scenarios.py` payload mapper — mirror the existing `silence_prompt_seconds` plumbing exactly).
  - [ ] 3.5 — Update `resolve_patience_config` in `scenarios.py` to include the new key in the resolved dict.
  - [ ] 3.6 — Update `bot.py` line ~295 to thread `ladder_impatience_seconds=patience_config["ladder_impatience_seconds"]` into the `PatienceTracker(...)` construction.
  - [ ] 3.7 — Validator: type check + range validation (`0.5 ≤ ladder_impatience_seconds ≤ 10.0`) in `resolve_patience_config`.
  - [ ] 3.8 — Update all 5 scenario YAMLs (`the-waiter.yaml`, `the-mugger.yaml`, `the-girlfriend.yaml`, `the-cop.yaml`, `the-landlord.yaml`) to add the new override key set to `null` (= use preset).
  - [ ] 3.9 — Tests: `test_ladder_impatience_seconds_threaded_from_yaml_through_patience_tracker` + `test_resolve_patience_config_validates_ladder_impatience_seconds_range` + `test_bot_threads_ladder_impatience_seconds_from_patience_config`.

- [ ] **Task 4 — Auth 401 Dio interceptor** (AC4)
  - [ ] 4.1 — Locate existing Dio configuration (likely `client/lib/services/api_client.dart` or `client/lib/core/network/dio_factory.dart` — confirm during dev).
  - [ ] 4.2 — Add `AuthInterceptor extends Interceptor` that overrides `onError` to catch `DioException.response?.statusCode == 401`. On 401: clear JWT from `flutter_secure_storage` (key matches the existing one — Story 4.2 `auth_jwt` or similar), navigate root-navigator to `/onboarding/email-auth` (or the equivalent route — confirm during dev), show SnackBar with `AppToast` matching the Story 5.4 EmpathicError pattern + copy "Session expired, please sign in again".
  - [ ] 4.3 — Idempotency: track an `_handling401: bool` flag on the interceptor that prevents re-entry while navigation is in progress.
  - [ ] 4.4 — Register the interceptor at Dio construction time (existing wiring or new in `main.dart` bootstrap).
  - [ ] 4.5 — Widget test `test_auth_interceptor_routes_to_login_on_401` — mocks a `DioException` with 401 response, asserts (a) JWT cleared from mocked storage, (b) `Navigator.pushReplacementNamed` called with the login route, (c) SnackBar appears.
  - [ ] 4.6 — Smoke gate Box 8 manual validation on Pixel 9 Pro XL.

- [ ] **Task 5 — Delete classifier debug logs** (AC5)
  - [ ] 5.1 — Delete the `logger.debug(...)` block at `server/pipeline/exchange_classifier.py:_classify` (the `classifier_input` log, ~lines 284-289 post Story 6.9b).
  - [ ] 5.2 — Delete the `logger.debug(...)` line for `classifier_output` (~line 335 post Story 6.9b).
  - [ ] 5.3 — Delete the explanatory comment block above (`# Story 6.9b smoke-gate carry-over (2026-05-22): per-classify trace...`).
  - [ ] 5.4 — Retire the matching `deferred-work.md` entry under "Deferred from: code review of story-6.9b (2026-05-22)" — the entry "🟠 Delete the two `classifier_input` / `classifier_output` DEBUG logs".
  - [ ] 5.5 — Verify zero test breakage: no existing test asserts those log lines (Story 6.9b review noted this — confirm).

- [ ] **Task 6 — Waiter `clarify` criteria amend** (AC6)
  - [ ] 6.1 — Read current `the-waiter.yaml` `checkpoints[clarify].success_criteria` string.
  - [ ] 6.2 — Amend to accept drink answers when Tina's prior line offered drinks. Suggested rewording: `"User answers the clarifying question about their order in any coherent way — confirmations ('yes', 'that's right', 'correct', 'no change'), drink choices when Tina just listed drinks (water, juice, cola, coffee + synonyms Coke / Pepsi / Sprite), or polite acknowledgements ('okay', 'thanks')."`
  - [ ] 6.3 — New test `test_waiter_clarify_accepts_drink_answer_after_drinks_offered` — loads the YAML via the existing scenario loader, asserts the criteria string contains a drink-accepting phrase.
  - [ ] 6.4 — Cross-reference comment in the YAML: link this calibration to Story 6.13 AC6 + the smoke-gate call_id=148 + 151 findings.

- [ ] **Task 7 — Pre-commit gates + Smoke Test Gate** (AC7)
  - [ ] 7.1 — Pre-commit gates green: `cd server && python -m ruff check . && python -m ruff format --check . && .venv/Scripts/python -m pytest`. Target server test count: 376 → ~382 (+6 net new: AC1 ×2, AC2 ×1, AC3 ×3-ish, AC6 ×1, minus AC5 which deletes 0 tests).
  - [ ] 7.2 — `cd client && flutter analyze && flutter test`. Target client test count: 373 → 374 (+1 AC4 interceptor test).
  - [ ] 7.3 — `git push` → CI/CD deploys → verify systemctl + journalctl clean.
  - [ ] 7.4 — Smoke gate Boxes 1-9 above, paste evidence (call_ids + journal grep output) into a new `## Smoke Test Gate Results` subsection at the bottom of this file.

## Dev Notes

### Why this story exists separately from 6.10/6.11/6.12

Walid 2026-05-26 explicit ask after seeing the Cartesia freeze reproduce on call_id=151: each of 6.10 (CheckpointManager rewrite), 6.11 (Soniox diarization), 6.12 (EmotionEmitter timing) touches a different part of the pipeline. None of them touch Cartesia TTS or the silence ladder logic. If we ship those 3 stories first, every smoke gate will catch the Cartesia freeze in their respective windows → developers will burn time trying to figure out if the failure is theirs or the latent bug → debug becomes impossible. Story 6.13 stabilises the pipeline so the next 3 stories have a clean reference point.

### Story 6.13 has the highest priority in Epic 6 remaining work

Re-ordered queue: **6.13 → 6.10 → 6.11 → 6.12 → Epic 6 close → MVP launch ready.**

### What this story is NOT

- NOT a calibration pass for the 5 scenarios (deferred to post-MVP voice-pipeline UX tuning per `memory/project_post_mvp_voice_ux_tuning.md`)
- NOT a Cartesia replacement / migration (the watchdog is mitigation, the underlying TTS service stays — replacement is a much bigger story if it ever comes)
- NOT a full audit of `deferred-work.md` (only the 6 specific items called out in ACs are in scope)
- NOT a refactor of the silence ladder semantics (only the cancel-on-bot-speech gap is fixed; the rest of the ladder logic stays)

### Project Structure Notes

New files:
- `server/pipeline/tts_watchdog.py` (~120 LOC)
- `server/tests/test_tts_watchdog.py` (~80 LOC)
- (optional) `client/lib/services/auth_interceptor.dart` (~40 LOC) if it makes sense as a separate file vs inlining into the existing Dio factory

Modified files:
- `server/pipeline/patience_tracker.py` (AC2 + AC3 — silence ladder bot-speech pause + ladder_impatience_seconds plumbing)
- `server/pipeline/scenarios.py` (`_DIFFICULTY_PRESETS` + `resolve_patience_config` validator)
- `server/pipeline/bot.py` (wire TTSWatchdog + thread ladder_impatience_seconds)
- `server/pipeline/exchange_classifier.py` (AC5 delete debug logs)
- `server/pipeline/scenarios/the-waiter.yaml` (AC6 criteria amend) + all 5 scenario YAMLs (AC3 nullable override key)
- `server/models/schemas.py` + `server/db/queries.py` + `server/db/seed_scenarios.py` + `server/api/routes_scenarios.py` (AC3 ladder_impatience_seconds plumbing — mirror `silence_prompt_seconds` exactly)
- `server/tests/test_patience_tracker.py` (+3-4 net new tests)
- `server/tests/test_scenarios.py` or test_waiter (+1 test)
- `server/tests/test_bot_pipeline_wiring.py` (+1 wiring assertion)
- `client/lib/services/api_client.dart` (or equivalent Dio config — AC4 interceptor wire)
- `client/test/services/auth_interceptor_test.dart` (+1 widget test)
- `_bmad-output/implementation-artifacts/deferred-work.md` (retire AC1/AC2/AC3/AC4/AC5/AC6 entries)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (in-progress flips, last_updated)

### References

- `_bmad-output/implementation-artifacts/deferred-work.md` (4 new findings from Story 6.9b smoke gate + 1 MUST-FIX-BEFORE-MVP-LAUNCH from Story 5.5)
- `_bmad-output/implementation-artifacts/6-9b-classifier-latency-slash.md` (smoke gate findings + Change Log entry 2026-05-26)
- `_bmad-output/planning-artifacts/prd.md` (FR45 perceived-latency target, performance "concept dead" line)
- `memory/feedback_vps_autonomy.md` (Walid's standing autonomous deploy auth)
- `memory/feedback_smoke_gate_analysis_mode.md` (silent-monitor convention for AC7 smoke gate)
- `server/CLAUDE.md` §1 (Pipecat FrameProcessor direction-test trap — relevant for AC2 BSF direction assertion)

## Change Log

- **2026-05-26 — Story 6.13 spec drafted post Story 6.9b Pixel 9 smoke gate.** 6 ACs (Cartesia watchdog, silence-ladder bot pause, `_LADDER_IMPATIENCE_AT` configurable, auth 401 Dio interceptor, classifier debug log removal, Waiter clarify YAML amend) + AC7 9-box smoke gate. 7 up-front deviations. Prioritised AHEAD of 6.10/6.11/6.12 per Walid 2026-05-26 ask "à la fin de cette épique, on ait un appel normal". Hard prerequisite — Story 6.9b done ✅. Test target server +6 net new → 382; client +1 → 374. Awaiting Walid `/bmad-dev-story` to flip `ready-for-dev → in-progress`.

## Dev Agent Record

### Agent Model Used

_To be populated by `/bmad-dev-story` when the story is implemented._

### Debug Log References

_To be populated by `/bmad-dev-story` when the story is implemented._

### Completion Notes List

_To be populated by `/bmad-dev-story` when the story is implemented._

### File List

_To be populated by `/bmad-dev-story` when the story is implemented._
