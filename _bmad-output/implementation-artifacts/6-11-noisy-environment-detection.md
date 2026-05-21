# Story 6.11: Noisy Environment Detection + Gifted Call End

Status: ready-for-dev

## Story

As the operator (Walid),
I want the call to **detect when a parasitic background voice** is degrading the conversation, have the character **announce in-character that they can't hear**, end the call, and **refund the user's daily slot** (gifted),
so that the user understands their environment is the problem (not the app), gets actionable guidance, and isn't punished for an environmental issue they can fix.

## Background

**Direct successor of Story 6.9's smoke test (2026-05-21, YouTube/cocktail-party scenario)** where DTLN (noise suppression) correctly filtered ambient noise but **couldn't suppress another human voice** because it's a fundamentally different DSP problem (cocktail-party / voice-isolation requires paid solutions like Krisp BVC, ~$500/mo flat, deferred post-MVP). The honest position post-Story 6.9: **MVP can't isolate the user's voice from another nearby voice**, but we CAN detect that situation and give the user agency to fix it.

**Walid's exact ask (2026-05-21)**:
> "estce que c'est possible de capter que ça marche mal et de mettre un message à l'utilisateur […] c'est le personnage lui-même qui va l'annoncer […] sur un ton sarcastique […] qu'on coupe mais que ça ne lui comptera pas un appel"

Three intertwined deliverables: (1) **detection** via Soniox V4's built-in speaker diarization, (2) **in-character exit** via a generic sarcastic line spoken by the active scenario character, (3) **gifted call** so the user's daily quota isn't burned by an environmental issue.

**Why diarization is the right detection signal**:
- Already a Soniox V4 feature, just a config flag (`enable_speaker_diarization=True`) — no new ML model
- Per-token speaker IDs flow through Pipecat's TranscriptionFrame metadata (verified — see Pipecat SonioxSTTSettings)
- Triggers ONLY on real other voices (not on ambient noise, papers rustling, breathing — those are correctly ignored by Soniox's speaker model)
- Cost: zero — diarization is included in the Soniox plan we already pay for

**Why we don't try noise-level/energy-based detection**:
- DTLN already pulls ambient noise → energy-based metric would be polluted by DTLN's own suppression
- "Background noise" isn't the problem — "background VOICE" is. Diarization specifically targets that
- Energy thresholds are crude; diarization is the conceptually-correct signal

**Hard prerequisite chain:**
- ✅ Story 6.8 — done
- ⏳ Story 6.9 — review (Walid validating café smoke test)
- ⏳ Story 6.10 — ready-for-dev (goal-based dialogue, planned next)
- ⏳ Story 6.11 (this story) — ready-for-dev, **scheduled AFTER 6.10**

**Critical reading before starting:**
- `_bmad-output/implementation-artifacts/6-9-dtln-noise-suppression.md` — predecessor; the cocktail-party limitation is documented there
- `_bmad-output/implementation-artifacts/6-5-build-voluntary-call-end-and-no-network-screen.md` — gifted-call mechanism (network_lost / character_hung_up<30s / inappropriate_content<30s); we extend the same pattern with `noisy_environment` as a 4th gifted reason
- `server/pipeline/bot.py` (Soniox config block) — `vad_force_turn_endpoint=False` and `model="stt-rt-v4"` already there; we add `enable_speaker_diarization=True`
- `server/pipeline/patience_tracker.py` `_VALID_REASONS` tuple — we extend with `"noisy_environment"`
- `server/api/routes_calls.py` — POST /calls/{id}/end + `EndCallIn.reason` Literal; we widen the Literal + extend the gifted criteria
- `server/pipeline/scenarios/the-waiter.yaml` `exit_lines` block — we add an optional `noisy_environment` field
- `client/lib/features/call/views/screens/call_ended_notice_screen.dart` (Story 6.5) — we add a 5th copy variant for `noisy_environment`
- `client/lib/features/call/views/widgets/` — new banner widget overlaid on the Rive character canvas during the exit-line speech

**Up-front deviations to document in Implementation Notes:**

1. **(Deviation #1) Generic exit line as a top-level constant in `prompts.py`, scenario-overridable.** Per Walid's ask, the line is **scenario-agnostic by default** so future scenarios inherit the behavior for free (same principle as COHERENCE_CHARTER from Story 6.8). Each scenario YAML can OPTIONALLY override via `exit_lines.noisy_environment` — same shape as the existing `exit_lines.hangup` / `exit_lines.completion`. We ship the constant + one per-character variant in `the-waiter.yaml` as a reference.

2. **(Deviation #2) Detection is "early-warning + grace period", not instant.** A 2-speaker detection on a single turn can be a false positive (Soniox occasionally mis-classifies the same user's prosody as a different speaker, especially across long pauses). The detection requires **2+ user turns within the first 4 turns of the call containing a non-primary speaker with ≥3 tokens each** before firing. This trades latency-to-warning for false-positive rate — important because a false hangup that refunds the user is worse than a 30-second delayed real warning.

3. **(Deviation #3) `gifted=True` is automatic for `reason=noisy_environment` — no duration gate.** Unlike `character_hung_up` / `inappropriate_content` which require `<30s` to qualify (per Story 6.5's quota-protection rationale), `noisy_environment` is ALWAYS gifted. The reasoning: the user couldn't control the environment, the system detected the issue, the cleanest UX is to fully refund. Documented in `routes_calls.py` `_compute_gifted()` (new helper) as a separate branch.

4. **(Deviation #4) New envelope type `env_warning` AND existing `call_end` with new reason.** Two distinct envelopes:
   - **`env_warning`** (during the call, before exit-line) — server emits as soon as diarization confirms the 2nd speaker. Client uses this to render the in-call banner (preparing the user for the imminent hangup).
   - **`call_end { reason: "noisy_environment", ...}`** — server emits via existing PatienceTracker path right before the character's exit-line plays. Client uses this for routing to the CallEndedNoticeScreen (5th variant).

5. **(Deviation #5) Detection is server-side ONLY.** No mobile-side audio analysis. All telemetry (speaker IDs, token counts) lives in the Soniox response → server processes → emits envelopes. Mobile stays a thin consumer of envelopes.

## Acceptance Criteria (BDD)

### AC1 — Soniox speaker diarization enabled

Given today's `bot.py` constructs `SonioxSTTService(... settings=SonioxSTTService.Settings(model="stt-rt-v4"), vad_force_turn_endpoint=False)`
When this story lands
Then `Settings(model="stt-rt-v4", enable_speaker_diarization=True)` is the new shape
And the wiring test in `tests/test_bot_pipeline_wiring.py` adds a source-text assertion for `enable_speaker_diarization=True`
And the inline comment in `bot.py` explains the trade-off (zero extra cost, used only by Story 6.11's environment detection)

### AC2 — `EnvironmentMonitor` FrameProcessor detects parasitic voices

Given Pipecat exposes per-token speaker IDs on the `TranscriptionFrame` when diarization is enabled (via the `metadata` field per pipecat 0.0.108 Soniox parser)
When this story lands
Then a new module `server/pipeline/environment_monitor.py` exists
And it exports `EnvironmentMonitor(FrameProcessor)` that:
  1. Observes user `TranscriptionFrame`s (mirror EmotionEmitter pipeline position — between `transcript_user` and `emotion_emitter`)
  2. Inspects each TF's per-token speaker IDs (if diarization metadata absent → pass through, no detection)
  3. Tracks a sliding window of the last 4 user turns
  4. Triggers `_on_parasitic_voice_detected()` when: **≥2 of the last 4 turns contain a non-primary speaker with ≥3 tokens of that speaker's audio in the turn** (per Deviation #2 — early-warning + grace period to avoid false positives)
  5. Is idempotent — fires ONCE per call (cumulative detection state persists across turns)

And `bot.py` instantiates `EnvironmentMonitor` and wires it in the Pipeline BEFORE `emotion_emitter` (so it sees the raw TF before EmotionEmitter consumes anything)
And the wiring test asserts the pipeline ordering

### AC3 — `env_warning` envelope on detection

Given the `EnvironmentMonitor` triggers detection mid-call
When `_on_parasitic_voice_detected()` fires
Then an `OutputTransportMessageFrame` is pushed DOWNSTREAM with shape:

```json
{
  "type": "env_warning",
  "data": {
    "reason": "background_voice",
    "detected_speakers": 2
  }
}
```

And the envelope rides the same downstream chain as `checkpoint_advanced` (proven path for client-bound envelopes, per Story 6.7 Phase 2 retouche #5)
And a log line `env_warning emitted reason=background_voice detected_speakers={N}` lands in journalctl for the smoke-gate operator

### AC4 — Server triggers the character's noisy_environment exit line

Given the `EnvironmentMonitor` has emitted the `env_warning` envelope
And the `PatienceTracker` exposes a `schedule_noisy_environment_exit()` method (NEW — mirrors the existing `schedule_completion()` and `_schedule_hang_up()` patterns from Story 6.4/6.6)
When `_on_parasitic_voice_detected()` fires
Then `EnvironmentMonitor` calls `patience_tracker.schedule_noisy_environment_exit()` immediately after the `env_warning` envelope
And `PatienceTracker._run_hang_up(reason="noisy_environment")` plays the exit line via the existing TTSSpeakFrame mechanism
And the LLM is NOT consulted for the exit-line text (single source of truth = the YAML-resolved line)
And `_VALID_REASONS` tuple is widened to `("silence", "inappropriate", "survived", "noisy_environment")`

### AC5 — Generic exit line + per-scenario YAML override

Given the existing pattern of `exit_lines.hangup` / `exit_lines.completion` / `exit_lines.patience_warning` in scenario YAMLs (Story 6.6)
When this story lands
Then a new module-level constant `NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT` lands in `prompts.py`:

```python
NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT = (
    "Look, I can't hear you over all that background noise. "
    "Try me again when you've got somewhere quieter."
)
```

And `scenarios.resolve_patience_config(scenario_id)` loads `exit_lines.noisy_environment` from YAML (falls back to the default constant if absent)
And the loaded line is stored in the PatienceTracker config dict as `hang_up_line_noisy_environment`
And `PatienceTracker.__init__` accepts a new kwarg `hang_up_line_noisy_environment: str` (mirrors the 3 existing exit-line kwargs from Story 6.6)
And `the-waiter.yaml` ships with a per-character override demonstrating the YAML-extension pattern (Tina's voice, tired+sarcastic):

```yaml
exit_lines:
  hangup: "*heavy sigh* I'm done. Next customer."
  completion: "Huh. You actually knew what you wanted. That's a first."
  patience_warning: "*sighs heavily* Look, are you actually ordering food, or am I wasting my time here? Last chance."
  noisy_environment: "Whoever else is in that room with you needs to take a hike. Call me back when it's just you."
```

And the other 4 scenarios (Mugger, Girlfriend, Cop, Landlord) do NOT add the override yet (use the default) — author can add per-scenario lines in a follow-up calibration pass

### AC6 — `EndCallIn.reason` widened to include `noisy_environment` and gifted=True is automatic

Given `EndCallIn.reason: Literal["survived", "user_hung_up", "character_hung_up", "inappropriate_content", "network_lost"]` (Story 6.5)
And `_compute_gifted()` in `routes_calls.py` has criteria for each reason
When this story lands
Then `EndCallIn.reason` Literal is widened with `"noisy_environment"`
And `_compute_gifted()` adds a branch: `if reason == "noisy_environment": return True` (NO duration gate per Deviation #3)
And the client's `CallEndPayload` model (Story 6.5) widens its reason Literal too
And the call-end POST that PatienceTracker triggers via the data channel envelope (Story 6.5) carries `reason=noisy_environment` for this path

### AC7 — Client banner widget renders during the warning window

Given the client's `DataChannelHandler` (Story 6.6) dispatches typed callbacks for envelope types
When this story lands
Then a new typed callback `onEnvWarning(payload: EnvWarningPayload)` is added
And a new widget `NoisyEnvironmentBanner` is rendered as an overlay on the `CallScreen` (above the Rive character canvas, below any existing CheckpointStepper)
And the banner shows:
  - Icon: `Icons.volume_off` or equivalent material icon (warning context — amber color from design system)
  - Title: "Background voice detected"
  - Subtitle: "Call ending — your daily call won't be counted"
And the banner appears the moment the `env_warning` envelope arrives
And the banner persists through the character's exit-line playback (the user must SEE the warning while Tina says her line so they connect cause and effect)
And the banner does NOT block the Rive character or the End Call button
And design uses existing `AppColors.statusWarning` / `AppSpacing` tokens — NO new design tokens

### AC8 — `CallEndedNoticeScreen` 5th variant for `noisy_environment`

Given `CallEndedNoticeScreen` (Story 6.5) has 4 copy variants for network_lost / character_hung_up<30s / inappropriate_content<30s / (catch-all)
When this story lands
Then a 5th variant lands keyed by `reason=noisy_environment`:
  - Title: "Background voice was too loud"
  - Body: "We couldn't hear you clearly. Try a quieter spot or use earphones — and this call doesn't count toward your daily limit."
  - CTA: "Got it" (close button) — no retry button
  - Icon: `Icons.volume_off` (matches the in-call banner for visual continuity)
And the screen-routing logic in `call_bloc.dart` (Story 6.5) handles `reason=noisy_environment` as a "no-quota-burn" path (same UX as `network_lost`)

### AC9 — Pre-commit gates

Given the dual-side discipline
When this story lands
Then ALL pass before flipping `in-progress → review`:
- `ruff check . && ruff format --check .` → zero issues
- `pytest` → all green (server) — expect ~12-15 new tests (EnvironmentMonitor behavior, patience_tracker noisy_environment path, routes_calls gifted branch, prompts constant, wiring tests). Target ≥360 (Story 6.10's ~350 baseline + ~12).
- `flutter analyze` → clean
- `flutter test` → all green — expect ~5-8 new tests (banner widget, payload parsing, screen variant). Target ≥385 (Story 6.10's ~376 baseline + ~8).
- `tests/test_migrations.py` → still 4/4 (no schema change)

### AC10 — Smoke Test Gate validates detection + UX end-to-end

See `## Smoke Test Gate` below.

## Smoke Test Gate (Server / Deploy Story)

> **Scope rule:** Detection requires REAL parasitic voice during a REAL call. Mandatory device gate.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test. First call boot shows the EnvironmentMonitor init log line.
  - _Proof:_ <!-- paste Active line + commit SHA + init log -->

- [ ] **Baseline calm-room call — NO false positive.** Standard Waiter call alone in a quiet room. Verify `env_warning` envelope is NEVER emitted.
  - _Expected:_ no `env_warning emitted` log lines in journalctl across the full call. Call completes normally (e.g. reason=survived).
  - _Proof:_ <!-- journalctl tail showing absence + call_end reason -->

- [ ] **YouTube parasitic voice test — POSITIVE detection.** Replay the Story 6.9 cocktail-party scenario: play a YouTube video with clear narration at ~30 cm from the phone while attempting the Waiter call.
  - _Expected:_ within the first 3-4 user turns, `env_warning emitted reason=background_voice detected_speakers=2` appears in journalctl; the client banner appears; Tina (or active scenario character) speaks the noisy_environment exit line; call ends with `reason=noisy_environment`; the call_sessions row has `gifted=1`.
  - _Proof:_ <!-- journalctl + transcript + DB row + screen capture of banner -->

- [ ] **Refund verified — daily quota not decremented.** Before this test call, note `calls_remaining` from the user's profile. Run the YouTube positive test (above). After, re-fetch profile.
  - _Expected:_ `calls_remaining` is UNCHANGED (call was gifted, slot refunded).
  - _Proof:_ <!-- before/after profile snapshot -->

- [ ] **In-character exit line plays per scenario.** Run the YouTube test on at least 2 scenarios (Waiter + one other — Mugger preferred). Verify the exit line spoken matches the YAML's `exit_lines.noisy_environment` field (or the default constant for the un-overridden scenario).
  - _Expected:_ Waiter says Tina's sarcastic line; Mugger says the default generic line (or its own if author added).
  - _Proof:_ <!-- 2 transcripts side by side -->

- [ ] **Banner UI verified.** During the YouTube test, the banner appears above the character at the moment of detection, persists through the exit-line speech, and disappears when the CallEndedNoticeScreen takes over.
  - _Expected:_ banner visible during character speech, then replaced by the 5th-variant CallEndedNoticeScreen with the "your daily call won't be counted" reassurance.
  - _Proof:_ <!-- 2-3 screenshots: in-call banner, exit screen -->

- [ ] **Server logs clean — no errors during the parasitic test.** `journalctl -u pipecat.service --since "10 min ago" | grep -iE "(error|traceback|exception)" | grep -v INFO` returns zero matches.
  - _Proof:_ <!-- "no errors in window" + timestamp -->

## Tasks / Subtasks

### Phase 1 — Server detection + exit-line plumbing

- [ ] **Task 1 — Enable Soniox speaker diarization** (AC: #1)
  - [ ] 1.1 — `bot.py` adds `enable_speaker_diarization=True` to `SonioxSTTService.Settings(...)`
  - [ ] 1.2 — Inline comment cross-references Story 6.11 + Soniox docs
  - [ ] 1.3 — Extend `test_bot_pipeline_wiring.py::test_bot_imports_emitter_classes` (or new test) with source-text assertion for the flag

- [ ] **Task 2 — `EnvironmentMonitor` FrameProcessor** (AC: #2, #3)
  - [ ] 2.1 — New file `server/pipeline/environment_monitor.py` (~150 LOC)
  - [ ] 2.2 — `EnvironmentMonitor(FrameProcessor)` observes user TFs, inspects per-token speaker IDs from `frame.metadata` (per pipecat Soniox parser)
  - [ ] 2.3 — Sliding window of last 4 user turns, dict `{turn_id: {speaker_id: token_count}}`
  - [ ] 2.4 — Trigger predicate: ≥2 of last 4 turns contain a non-primary speaker with ≥3 tokens each
  - [ ] 2.5 — Idempotent — fires ONCE per call via `self._triggered: bool` flag
  - [ ] 2.6 — On trigger: push `env_warning` envelope DOWNSTREAM + call `patience_tracker.schedule_noisy_environment_exit()`
  - [ ] 2.7 — Pass-through MANDATORY (mirror EmotionEmitter / CheckpointManager pattern — never swallow TFs)

- [ ] **Task 3 — `bot.py` wire the monitor + tracker config** (AC: #2)
  - [ ] 3.1 — Import + instantiate `EnvironmentMonitor` after `emotion_emitter` decl, before pipeline list
  - [ ] 3.2 — Insert into pipeline BEFORE `emotion_emitter` (so it sees raw TFs first — mirror Story 6.6 Dev #5)
  - [ ] 3.3 — Thread the patience_tracker reference to EnvironmentMonitor constructor
  - [ ] 3.4 — Wire `hang_up_line_noisy_environment` kwarg into `PatienceTracker(...)` from the new YAML field

- [ ] **Task 4 — `PatienceTracker.schedule_noisy_environment_exit()` + `_VALID_REASONS` widening** (AC: #4)
  - [ ] 4.1 — Add new method mirroring `schedule_completion(survival_pct=100)` shape
  - [ ] 4.2 — Routes through existing `_run_hang_up(reason="noisy_environment")` infra
  - [ ] 4.3 — `_VALID_REASONS` tuple widens to 4-tuple
  - [ ] 4.4 — Exit-line resolution: `_run_hang_up` switch picks `self._hang_up_line_noisy_environment` for the new reason
  - [ ] 4.5 — `survival_pct` computation: not applicable for noisy_environment (no meaningful "performance" measure) — set to `None` in the call_end envelope (mirror existing nullable handling)

- [ ] **Task 5 — Generic prompt constant + YAML override** (AC: #5)
  - [ ] 5.1 — `prompts.py` adds `NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT` constant
  - [ ] 5.2 — `scenarios.resolve_patience_config` loads `exit_lines.noisy_environment` (fallback to constant)
  - [ ] 5.3 — `the-waiter.yaml` gets the optional `noisy_environment` line (Tina-flavored sarcastic)
  - [ ] 5.4 — Other 4 scenarios: NO YAML change (test the default-fallback path in prod)

- [ ] **Task 6 — Widen `EndCallIn.reason` + `_compute_gifted()`** (AC: #6)
  - [ ] 6.1 — `models/schemas.py` (or wherever EndCallIn lives) — widen Literal
  - [ ] 6.2 — `routes_calls.py::_compute_gifted()` (refactor inline branches into a helper if not already) — add `if reason == "noisy_environment": return True`
  - [ ] 6.3 — Tests in `test_calls.py` for the noisy_environment gifted path (mirror existing network_lost / inappropriate tests)

### Phase 2 — Client: banner + CallEndedNoticeScreen variant

- [ ] **Task 7 — `EnvWarningPayload` model + DataChannelHandler dispatch** (AC: #7)
  - [ ] 7.1 — New `client/lib/features/call/services/env_warning_payload.dart` (~30 LOC) — value class with `reason: String` + `detectedSpeakers: int`
  - [ ] 7.2 — Extend `data_channel_handler.dart` with `onEnvWarning(EnvWarningPayload)` typed callback (mirror `onCheckpointAdvanced` pattern from Story 6.7)
  - [ ] 7.3 — Widen `CallEndPayload.reason` Literal/enum to include `noisy_environment`

- [ ] **Task 8 — `NoisyEnvironmentBanner` widget** (AC: #7)
  - [ ] 8.1 — New `client/lib/features/call/views/widgets/noisy_environment_banner.dart` (~100 LOC)
  - [ ] 8.2 — Renders icon + title + subtitle on amber background (use existing `AppColors.statusWarning` token)
  - [ ] 8.3 — Wired into `CallScreen` as a top overlay (above Rive character, below status bar) with `ValueNotifier<EnvWarningPayload?>` from `_CallScreenState` (same UI-only-state pattern from Story 6.7's CheckpointStepper)
  - [ ] 8.4 — Visible from `env_warning` arrival through exit-line speech end; the route transition to CallEndedNoticeScreen replaces it

- [ ] **Task 9 — `CallEndedNoticeScreen` 5th variant** (AC: #8)
  - [ ] 9.1 — Extend the existing reason → copy mapping with `noisy_environment` → ("Background voice was too loud", "We couldn't hear you clearly...", "Got it")
  - [ ] 9.2 — Icon: `Icons.volume_off` (consistency with banner)
  - [ ] 9.3 — Route from `call_bloc.dart` `_handleCallEnd` flow to the new variant when `reason==noisy_environment`

### Phase 3 — Tests + pre-commit gates

- [ ] **Task 10 — Server tests** (AC: #9)
  - [ ] 10.1 — `tests/test_environment_monitor.py` (NEW, ~8 tests) — single-turn no-trigger, 1-turn-with-2nd-speaker no-trigger (early-warning), 2-turns-with-2nd-speaker triggers, 4-turn sliding window expiration, idempotent (fires once per call), missing diarization metadata = pass-through, ≥3 tokens threshold, envelope shape
  - [ ] 10.2 — `tests/test_patience_tracker.py` — extend with `schedule_noisy_environment_exit` test + `_VALID_REASONS` widening
  - [ ] 10.3 — `tests/test_calls.py` — gifted=True path for `reason=noisy_environment` (no duration gate)
  - [ ] 10.4 — `tests/test_prompts.py` — assert `NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT` exists + non-empty
  - [ ] 10.5 — `tests/test_scenarios.py` — assert YAML loader pulls `exit_lines.noisy_environment` with fallback
  - [ ] 10.6 — `tests/test_bot_pipeline_wiring.py` — diarization flag + EnvironmentMonitor pipeline ordering

- [ ] **Task 11 — Client tests** (AC: #9)
  - [ ] 11.1 — `test/features/call/services/env_warning_payload_test.dart` — JSON parse roundtrip
  - [ ] 11.2 — `test/features/call/views/widgets/noisy_environment_banner_test.dart` — renders with payload, hidden when null, amber color, no Rive overlap, accessibility label
  - [ ] 11.3 — `test/features/call/views/screens/call_ended_notice_screen_test.dart` — 5th variant copy + icon + close-only CTA

- [ ] **Task 12 — Pre-commit + smoke gate** (AC: #9, #10)
  - [ ] 12.1 — `ruff check .` + `ruff format --check .` + `pytest` (target ≥360)
  - [ ] 12.2 — `flutter analyze` + `flutter test` (target ≥385)
  - [ ] 12.3 — Commit (one story = one commit per project rules)
  - [ ] 12.4 — **WALID** — deploy VPS + 7-box smoke gate above
  - [ ] 12.5 — `review → done` after smoke gate proofs

## Dev Notes

**Why Soniox diarization and not a different approach?**
- Already-paid feature, just a flag flip
- Conceptually correct (we want to detect VOICES, not noise)
- Real-time stream — verdict per token
- Tested by Soniox in production for years
- Alternatives (energy-threshold, custom ML) are either crude or hugely expensive

**Why early-warning + grace period (2-of-4 turns) instead of instant trigger?**
- A single mis-diarization is common (user prosody varies; Soniox sometimes assigns a new ID to the same speaker after a pause)
- False hangup feels MORE broken than a 30-sec-delayed real warning
- 2-of-4 turns means worst-case the warning fires after ~30-60 seconds (acceptable; user is still early in the call)
- Threshold of "≥3 tokens per turn" filters out 1-2-token noise burps mis-classified as speaker

**Why scenario-overridable exit line?**
- Default works for any character — generic-but-sarcastic
- Per-scenario authors can add character-specific flavor (Tina sarcasm, Mugger threat, Girlfriend hurt) without redesigning the system
- Mirrors the existing pattern (hangup, completion, patience_warning all overridable in YAML)

**Why gifted=True automatic (no duration gate)?**
- Unlike `character_hung_up` / `inappropriate_content` where the user might be gaming the system by triggering early ends, **the user cannot control diarization detection**. It's environmental.
- The cleanest "we're sorry our app caused this exit" UX is to fully refund.
- Cost: minimal — even if abused, the user would need to play YouTube near their phone every call (annoying enough to be self-limiting)

**Why a separate `env_warning` envelope (not just `call_end`)?**
- Visual continuity: the user SEES the banner appear, hears Tina say her line, then sees the call-end screen. Three steps connect the dots ("the system detected → the character reacted → the call ended fairly")
- A single `call_end` envelope without prior warning would feel abrupt and confusing
- The banner provides ~3-5 seconds of "this is happening because of background voice" context before the exit-line plays

**Why detection lives in a new FrameProcessor (not CheckpointManager)?**
- Single Responsibility: CheckpointManager owns checkpoint progression; EnvironmentMonitor owns environment quality
- Pipeline ordering: EnvironmentMonitor needs to see TFs BEFORE EmotionEmitter consumes them, separate from CheckpointManager
- Easier to disable: a feature-flag or env-var could remove EnvironmentMonitor from the pipeline for testing without touching the rest

**Latency impact:**
- Diarization is part of Soniox's normal transcription stream — no extra round-trip
- EnvironmentMonitor processing is microseconds (in-memory dict lookups + integer comparisons)
- The exit-line spoken by character is ~5-8 seconds (similar to existing hangup paths)
- Total added latency between trigger and call-end: ~5-8 s, same as a normal character hangup

**Calibration impact:** none. This is an orthogonal feature, doesn't touch scenario YAML's `success_criteria` or patience preset. Story 6.10's goal-based dialogue + this story can coexist without conflict (detection fires whether or not a goal is met).

### Project Structure Notes

**Server — modified:**
- `server/pipeline/bot.py` — Soniox diarization flag + EnvironmentMonitor instantiation + pipeline ordering + PatienceTracker kwarg
- `server/pipeline/patience_tracker.py` — `schedule_noisy_environment_exit` + `_VALID_REASONS` widening + new exit-line kwarg
- `server/pipeline/prompts.py` — `NOISY_ENVIRONMENT_EXIT_LINE_DEFAULT` constant
- `server/pipeline/scenarios.py` — load `exit_lines.noisy_environment` with fallback
- `server/pipeline/scenarios/the-waiter.yaml` — optional `noisy_environment` exit line (Tina sarcastic)
- `server/api/routes_calls.py` — `_compute_gifted()` branch + EndCallIn Literal widening
- `server/models/schemas.py` (or wherever EndCallIn lives) — Literal widening
- `server/tests/` — new + extended tests (per Task 10)

**Server — new files:**
- `server/pipeline/environment_monitor.py` (~150 LOC)
- `server/tests/test_environment_monitor.py` (~120 LOC)

**Client — modified:**
- `client/lib/features/call/services/data_channel_handler.dart` — `onEnvWarning` typed callback + `CallEndPayload` reason widening
- `client/lib/features/call/views/screens/call_screen.dart` — banner overlay wiring + state
- `client/lib/features/call/views/screens/call_ended_notice_screen.dart` — 5th variant
- `client/lib/features/call/bloc/call_bloc.dart` — route handling for `reason=noisy_environment`

**Client — new files:**
- `client/lib/features/call/services/env_warning_payload.dart` (~30 LOC)
- `client/lib/features/call/views/widgets/noisy_environment_banner.dart` (~100 LOC)
- `client/test/features/call/services/env_warning_payload_test.dart`
- `client/test/features/call/views/widgets/noisy_environment_banner_test.dart`

**Implementation artifacts — modified:**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — new entry `6-11-noisy-environment-detection: ready-for-dev`
- `_bmad-output/implementation-artifacts/6-11-noisy-environment-detection.md` — this file

### References

- `_bmad-output/implementation-artifacts/6-9-dtln-noise-suppression.md` — predecessor; cocktail-party limitation documented
- `_bmad-output/implementation-artifacts/6-5-build-voluntary-call-end-and-no-network-screen.md` — gifted-call infra (extending the same mechanism)
- `_bmad-output/implementation-artifacts/6-7-build-checkpointstepper-overlay-for-call-screen.md` — banner pattern reference (UI overlay on call screen)
- [Soniox V4 Speaker Diarization docs](https://soniox.com/docs/speech_recognition/speaker_diarization) — feature reference
- Pipecat SonioxSTTSettings — `enable_speaker_diarization` field

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context)

### Debug Log References

(filled at dev time)

### Completion Notes List

(filled at dev time)

### File List

(filled at dev time)

## Change Log

- 2026-05-21 — Spec drafted post-Story 6.9 cocktail-party limitation analysis. Scope = detection (Soniox diarization) + in-character exit line (generic + YAML override) + gifted refund + banner UI + 5th CallEndedNoticeScreen variant. 5 up-front deviations documented. Scheduled AFTER Story 6.10 implementation. Awaiting Walid sign-off.
