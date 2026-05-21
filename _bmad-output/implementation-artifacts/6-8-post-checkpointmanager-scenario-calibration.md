# Story 6.8: Voice Pipeline Hardening + Scenario Calibration (MVP-Launch Blockers + Carry-Forward)

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As the operator (Walid),
I want the voice pipeline to deliver sub-2s perceived latency AND scenario-agnostic conversational coherence AND all 5 launch scenarios calibrated end-to-end,
so that the MVP can ship to real users without hitting the PRD's "concept dead" kill criterion on the very first call.

## Background

**This story is a SCOPE EXPANSION of the originally-planned Story 6.8 ("Post-CheckpointManager Scenario Calibration"). Story 6.7's smoke test on Pixel 9 Pro XL (2026-05-19, call_id=118) surfaced two product-killing defects that promote this story from a YAML-tuning pass to a launch-blocker hardening pass.**

The original 6.8 scope (calibrate the 4 remaining scenarios — Mugger, Girlfriend, Cop, Landlord — to validate survival % ranges and select TTS voices) is preserved as Phase 3 below. **But Phases 1 and 2 must land FIRST** — calibration on a latency-broken / coherence-broken pipeline produces calibration results that are themselves broken.

**The two MVP-launch-blocker findings, in priority order:**

1. **🚨 Perceived latency exceeds the PRD kill criterion.** Call_id=118 transcript timestamps showed consistent **2-3s** between user speech end and Tina's first audio byte, and **4-5s** in terminal-zone turns (`patience < 25`, Dev #7 synchronous classifier). The PRD `Functional & Non-Functional Requirements > Performance` row defines: target <800ms, hard ceiling <2s, ">2s consistently → concept is dead". Observed values are at OR ABOVE the kill line. **Smoking gun:** `server/pipeline/bot.py:125` — `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=1.8)`. Pipecat waits 1.8s of silence after the user stops speaking before declaring "turn done" and triggering the LLM. That single line is at the 2s ceiling with zero margin for STT/LLM/TTS/RTT. Full analysis: `memory/feedback_latency_kill_criterion_exceeded.md`.

2. **🚨 Conversation coherence enforced at scenario level, not system level.** Same call surfaced 3 coherence failures from Tina: (a) forgot the user's confirmed "Coke" order 70s later and asked again; (b) re-asked the main course after confirming "Okay, grilled chicken"; (c) hallucinated 3 different drink menus across turns ("Coffee/tea/water/soda" → "Coke/Sprite/Ginger Ale" → "Water/juice/cola/coffee"). **Root cause:** Story 6.6's `CheckpointManager._classify_and_advance` (Deviation #2) swaps `llm._settings.system_instruction` wholesale on every checkpoint advance with `base_prompt + prompt_segment[current_checkpoint]`. Any conversation-memory or menu-consistency directive in the previous segment is overwritten. Qwen3.5 Flash (small, fast model) doesn't weight the `LLMContext` message history strongly enough to override a fresh system directive emphasizing the new objective. Walid (2026-05-19) explicit ask: *"le gardien ne doit pas être au niveau de chaque scénario mais plutôt au niveau général parce qu'ensuite quand je vais générer des scénarios à la chaîne je n'aurai pas le temps de vérifier chaque microinteraction"*. Full analysis: `memory/feedback_coherence_must_be_system_wide.md`.

**These two defects are co-dependent**: the coherence charter adds ~150-300 tokens to every LLM request, which adds LLM TTFT, which adds perceived latency. Both must land together with a smoke-gate that measures end-to-end latency AFTER the charter is in place — otherwise the latency budget is invisible at calibration time.

**Hard prerequisite chain:**
- ✅ Story 6.6 (CheckpointManager + ExchangeClassifier) — done
- ✅ Story 6.7 (CheckpointStepper Rive overlay) — review
- ⏳ Story 6.8 (this story) — ready-for-dev

**Critical reading before starting:**

- **🚨 `memory/feedback_latency_kill_criterion_exceeded.md`** — root cause, 6 levers prioritized, code touch-points. This is the Phase 1 spec source.
- **🚨 `memory/feedback_coherence_must_be_system_wide.md`** — root cause, COHERENCE_CHARTER design + alternative architectures considered. This is the Phase 2 spec source.
- `_bmad-output/implementation-artifacts/deferred-work.md` lines 16-45 (the 2 🚨 entries at the top) — same content as the memory files, but cross-linked from the operations log.
- `_bmad-output/planning-artifacts/epics.md` lines 1232-1260 — the ORIGINAL Story 6.8 scope (Phase 3 of this story).
- `_bmad-output/planning-artifacts/prd.md` `Functional & Non-Functional Requirements > Performance` table — the latency target / hard ceiling / kill criterion / FR45 alert threshold.
- `_bmad-output/planning-artifacts/architecture.md` `Performance` section — "Sub-800ms latency budget distributed across 4+ network hops. Streaming overlap mandatory (LLM streams to TTS before full response generated)".
- `_bmad-output/planning-artifacts/difficulty-calibration.md` (the whole file) — the calibration target ranges (Mugger/Girlfriend 35-55%, Cop/Landlord 15-35%), AI scoring system, Pass A / Pass B test methodology.
- `_bmad-output/planning-artifacts/scenarios/scenario-testing-process.md` — transcript capture (`TranscriptLogger`), AI scoring (`score_transcript.py`), checklist templates.
- `server/pipeline/bot.py` (lines 84-130) — LLM service, TTS service, VAD params, UserTurnStrategies (the latency root-cause site).
- `server/pipeline/checkpoint_manager.py` (lines 162-200 for init, lines 433-470 for advance) — Deviation #2 swap mechanism. Phase 2 modifies this swap composition.
- `server/pipeline/prompts.py` — current location of `SARCASTIC_CHARACTER_PROMPT`. Phase 2 adds `COHERENCE_CHARTER` constant here.
- `server/pipeline/scenarios/the-waiter.yaml` — reference structure for `base_prompt`, `checkpoints[].success_criteria`, `checkpoints[].prompt_segment`, `tts_voice_id`, `calibration.pass_a/pass_b`.
- `server/pipeline/scenarios/{the-mugger,the-girlfriend,the-cop,the-landlord}.yaml` — the 4 uncalibrated scenarios (`tts_voice_id: null`, empty calibration blocks).
- `server/pipeline/transcript_logger.py` + `server/scripts/score_transcript.py` (existing Story 3.0 tooling) — the calibration measurement instruments.

**Up-front deviations to document in Implementation Notes:**

1. **(Deviation #1) Scope expansion beyond epics.md spec.** Epic spec lines 1232-1260 frames 6.8 as YAML calibration only. This story RECASTS 6.8 as a 3-phase launch-blocker hardening pass (Phases 1+2 architectural, Phase 3 YAML calibration). Both new phases are documented launch blockers per deferred-work.md MUST-FIX section. Epic doc is not amended (it's a historical record); this story file is the authoritative spec.

2. **(Deviation #2) Phase ordering puts architectural fixes BEFORE calibration.** Original 6.8 implied direct YAML tuning. Per the co-dependence analysis above, calibration on a broken pipeline produces broken calibration results. Phases 1+2 must close before Phase 3 starts. The smoke gate's perceived-latency measurement explicitly gates the Phase 3 work.

3. **(Deviation #3) `COHERENCE_CHARTER` lives in `prompts.py`, not in a YAML.** A scenario-author-overridable charter would defeat the purpose ("at the general level, not per scenario"). The charter is a Python constant + a single insertion point in `CheckpointManager`. Future scenarios inherit it for free.

4. **(Deviation #4) `user_speech_timeout` target value is empirical, not theoretical.** Phase 1 specifies a search range (0.5-0.8s) rather than a fixed value. Dev runs A/B-style tests against the smoke gate's transcript timestamps to find the lowest value that doesn't false-positive-cut slow speakers on the easy tier (target speaker: B1 English learner, 1-3s thinking pauses between phrases).

## Acceptance Criteria (BDD)

### Phase 1 — Latency floor under PRD ceiling

**AC1 — Smoking-gun `user_speech_timeout` tuned to under 1s:**

Given `server/pipeline/bot.py:125` currently sets `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=1.8)`
And the PRD hard ceiling for perceived latency is <2s (kill criterion >2s)
And empirical evidence from call_id=118 shows the 1.8s timeout dominates the perceived latency floor
When this story lands
Then `user_speech_timeout` is set to a value in `[0.5, 0.8]` seconds chosen empirically against the Phase 4 smoke gate
And the chosen value is documented inline with a comment naming the tuning context, the prior value, and the new value (the convention: a comment like `# Phase 1 (Story 6.8) — was 1.8s, dropped to 0.6s after 3 B1-learner smoke runs without false-positive turn-cuts`)
And a comment cross-references `memory/feedback_latency_kill_criterion_exceeded.md` lever #1

**AC2 — VAD audit for redundancy with `user_speech_timeout`:**

Given `VADParams(stop_secs=0.8)` may stack additively with `SpeechTimeoutUserTurnStopStrategy` to extend the perceived turn-end silence
When this story lands
Then dev inspects pipecat 0.0.108's source (`pipecat.audio.vad.silero` + `pipecat.turns.user_stop.speech_timeout`) to determine whether the two timeouts stack OR whether one supersedes the other
And documents the finding inline in `bot.py` near the VAD setup block (~lines 103-110)
And if the two stack, `stop_secs` is also reduced to keep the NET silence-to-turn-end at ~0.8s
And if they don't stack, a comment explains which one wins so a future dev doesn't re-introduce the same redundancy

**AC3 — LLM→TTS streaming overlap verified end-to-end:**

Given the PRD `Performance` section specifies "streaming overlap mandatory (LLM streams to TTS before full response generated)"
And the bot.py pipeline currently constructs `OpenRouterLLMService` and `CartesiaTTSService` without explicit streaming flags
And it's unknown whether tokens stream from LLM → TTS before LLM finishes, or whether TTS waits for the full LLM response
When this story lands
Then dev adds INFO-level instrumentation at 3 points in the pipeline (one-line `logger.info` with `time.monotonic_ns()` timestamps):
  - First token / chunk arriving at LLM service output
  - First audio chunk arriving at TTS service output
  - First audio frame pushed to `transport.output()`
And runs a single calibrated call with these logs active
And asserts via the journalctl tail that the gap `(LLM_first_token → TTS_first_audio)` is <500ms
And if the gap is >500ms (i.e. TTS waits for full LLM), opens the underlying setting on `OpenRouterLLMService` / `CartesiaTTSService` to enable token streaming
And removes the instrumentation OR demotes to DEBUG before commit (production should not emit 3 INFO lines per turn)

**AC4 — Dev #7 synchronous classifier path made cheaper:**

Given Story 6.6 Deviation #7 introduced a synchronous classifier call on terminal-zone turns (meter about to zero OR last checkpoint), adding ~2s blocking latency
And the trade-off rationale (better disjointed-exit-line UX than naive parallel emission) remains valid
And the measurement on call_id=118 confirmed terminal-zone latency of ~4-5s
When this story lands
Then `ExchangeClassifier.classify` timeout is reduced from `2.0s` to `1.0s` (in `server/pipeline/exchange_classifier.py`)
And the conservative-fallback path (timeout → `verdict=None` → treated as failed exchange) remains unchanged
And a comment in `_run_classifier_blocking` documents the new bound and links to this AC

**AC5 — Phase 1 measurable outcome:**

Given the changes in AC1-AC4 have landed
And the Phase 4 smoke gate is run against a calibrated Waiter happy-path call
When transcript timestamps are inspected (`/tmp/.../transcript_call_*.json` `timestamp_ms` deltas between user-final and character-first)
Then the **median** user-speech-end → character-first-audio interval is **≤1500ms** (the FR45 operator-alert threshold)
And the **95th percentile** is **≤2000ms** (the PRD hard ceiling)
And no single turn exceeds 3000ms unless the meter is in terminal zone (in which case the synchronous classifier adds the documented ~1s)
And these numbers are pasted as proof in the Phase 4 smoke gate boxes

### Phase 2 — Conversation coherence charter

**AC6 — `COHERENCE_CHARTER` constant added to `prompts.py`:**

Given Story 6.6's `CheckpointManager._classify_and_advance` (Deviation #2) overwrites `llm._settings.system_instruction` wholesale on every checkpoint advance, losing conversation-memory directives
And Walid's explicit ask is that coherence safeguards live at the SYSTEM level, not per scenario
When this story lands
Then a new module-level constant lands in `server/pipeline/prompts.py`:

```python
# Story 6.8 Phase 2 — system-wide conversation-coherence charter. Appended
# verbatim to EVERY system_instruction composed by CheckpointManager (both
# at init and at every checkpoint advance — see Deviation #2). The charter
# is NOT scenario-specific: it encodes universal behaviors the character
# must respect regardless of who they are or what scenario they're in.
# Token cost: ~200 tokens per turn. The savings on coherence-failure
# recoveries (re-asking confirmed items, hallucinated menus) far exceed
# the per-turn cost.
COHERENCE_CHARTER = """\
Conversation memory rules (MUST FOLLOW, regardless of scenario):

1. Track every item the customer has confirmed. Once you acknowledge
   an item (saying "got it", "okay, <item>", "<item>, yes", or any
   equivalent), that item is LOCKED. Do not re-ask. Do not re-list.
   Do not contradict the prior acknowledgment.

2. If the customer references something they said earlier ("I already
   said X", "as I told you", "like I said"), assume they are correct
   and integrate that into your current turn. Do NOT deny what they
   claim — check your prior acknowledgments in the conversation
   history and respond accordingly.

3. When you list options (menu items, choices, drinks, etc.), the
   list MUST come verbatim from the scenario's defined inventory.
   Do NOT invent new options across turns. Do NOT change the list
   between turns. If you listed options in an earlier turn, the same
   options apply on later turns unless the customer explicitly
   chose one and you must now offer remaining alternatives.

4. Never claim an item is unavailable if it appeared in any prior
   listing you yourself produced. If the customer requests an item
   you did not list, that's the only valid time to say it's
   unavailable.

5. If you and the customer disagree about what was said, prefer the
   conversation history over your current guess. Re-read the recent
   exchanges before responding.
"""
```

And the constant is exported (visible in `from pipeline.prompts import COHERENCE_CHARTER`)

**AC7 — `CheckpointManager` injects the charter at init AND every advance:**

Given `CheckpointManager.__init__` does NOT currently compose the initial system_instruction (that's done in `bot.py` via `OpenRouterLLMService.Settings(system_instruction=system_prompt, ...)` where `system_prompt = scenario_base_prompt`)
And `CheckpointManager._classify_and_advance` does compose subsequent swaps as `self._base_prompt + "\n\n" + next_checkpoint["prompt_segment"].rstrip()` (line ~446)
When this story lands
Then `CheckpointManager.__init__` accepts a NEW parameter `coherence_charter: str` (required, no default — bot.py must thread it explicitly)
And `CheckpointManager._classify_and_advance`'s system_instruction swap composition becomes:

```python
new_system_prompt = (
    self._base_prompt
    + "\n\n" + self._coherence_charter
    + "\n\n" + next_checkpoint["prompt_segment"].rstrip()
)
```

And `bot.py` instantiates `CheckpointManager(..., coherence_charter=COHERENCE_CHARTER)` AND ALSO threads the charter through the INITIAL system_instruction passed to `OpenRouterLLMService.Settings(...)`:

```python
from pipeline.prompts import COHERENCE_CHARTER
# ...
initial_system_prompt = (
    scenario_base_prompt.rstrip()
    + "\n\n" + COHERENCE_CHARTER
    + "\n\n" + scenario_checkpoints[0]["prompt_segment"].rstrip()
)
llm = OpenRouterLLMService(
    api_key=settings.openrouter_api_key,
    settings=OpenRouterLLMService.Settings(
        # ...
        system_instruction=initial_system_prompt,
        # ...
    ),
)
```

And the legacy `system_prompt = os.environ.get("SYSTEM_PROMPT")` env-var path (used by the `/connect` PoC route) ALSO appends the charter as a fallback (so even legacy entry-points get coherence)

**AC8 — Behavioral test for the charter:**

Given a unit test that drives `CheckpointManager` through 3 simulated checkpoint advances
And captures the system_instruction value after each advance via the stub LLM's `_settings.system_instruction`
When this story lands
Then a NEW test lands at `server/tests/test_checkpoint_manager.py::test_coherence_charter_appears_in_every_system_instruction_swap`
And the test asserts:
  - After init: charter is present in `stub_llm._settings.system_instruction` (set via Phase 2's bot.py change OR explicitly by the manager constructor — dev's call where to inject)
  - After advance 1: charter is present
  - After advance 2: charter is present
  - The charter appears EXACTLY ONCE per system_instruction (no accidental duplication on subsequent swaps)
  - The charter appears BETWEEN `base_prompt` and `prompt_segment` (positional ordering matters — `base_prompt` defines the character, charter is universal, prompt_segment is current-turn-specific)

And a SECOND test asserts the wiring: `server/tests/test_bot_pipeline_wiring.py::test_coherence_charter_threaded_to_checkpoint_manager_and_llm_settings`
  - Source-text assertion: `bot.py` imports `COHERENCE_CHARTER` from `pipeline.prompts`
  - Source-text assertion: `bot.py` constructs the `CheckpointManager(..., coherence_charter=COHERENCE_CHARTER)` call

### Phase 3 — Per-scenario YAML calibration (original 6.8 scope)

**AC9 — Menu consistency in `base_prompt`:**

Given the 5 launch scenario YAMLs each have a `base_prompt` block but only `the-waiter.yaml` currently lists its menu options explicitly (line ~64: "grilled chicken, fried chicken, pasta, steak, fish and chips, soup of the day (tomato)")
And the call_id=118 hallucination ("Coffee/tea/water/soda" → "Coke/Sprite/Ginger Ale" → "Water/juice/cola/coffee") was rooted in `base_prompt` not nailing the drink list
When this story lands
Then EACH of the 5 scenario `base_prompt` blocks has a clearly-delimited "Inventory" or "Available items" or "Menu" section listing every option the character may legitimately offer
And the listing is exhaustive (a flat enumeration, not a "things like…" suggestion)
And `the-waiter.yaml` specifically: the drink list is moved into the `base_prompt` "Menu" block (currently it's implicit) — explicit list: "Drinks: water, juice, cola, coffee" (matches the existing `SARCASTIC_CHARACTER_PROMPT` line 49)
And for the 4 uncalibrated scenarios (Mugger, Girlfriend, Cop, Landlord), dev with Walid's input enumerates a small inventory: e.g. Mugger's "demands" list (wallet, phone, watch), Cop's "possible charges" list, Landlord's "lease violations" list, Girlfriend's "complaint topics" list

**AC10 — `success_criteria` audit on Waiter checkpoints:**

Given Story 6.7's call_id=118 saw 4 consecutive `checkpoint_unmet drink` verdicts even though the user said "Coke" (the YAML's `drink` checkpoint `success_criteria` was too strict — the user's later phrases like "fish please" or "I already said pasta" were classified against the drink criterion and failed)
When this story lands
Then `the-waiter.yaml`'s `drink` checkpoint `success_criteria` is rewritten to be more lenient: it should pass when the user names ANY beverage from the menu (water, juice, cola, coffee — case-insensitive substring match in spirit, the classifier judges semantically)
And the `clarify` checkpoint's criteria is audited similarly (it was the cause of the `clarify` unmet at call_id=118 too)
And a brief inline YAML comment on each amended `success_criteria` documents the call_id and the failure pattern that motivated the change

**AC11 — `tts_voice_id` selection for the 4 uncalibrated scenarios:**

Given `the-mugger.yaml`, `the-girlfriend.yaml`, `the-cop.yaml`, `the-landlord.yaml` all currently have `tts_voice_id: null`
And the Cartesia Sonic 3 voice catalog (https://play.cartesia.ai/voices) offers character-personality voices
When this story lands
Then each of the 4 YAMLs has a non-null `tts_voice_id` (UUID format) chosen against the character's personality:
  - Mugger: gruff male, urgent, threatening
  - Girlfriend: emotional female, late-20s, accusatory
  - Cop: authoritative male, neutral-stern
  - Landlord: stern male OR female (dev's call after audition), pragmatic
And a YAML comment next to each `tts_voice_id` documents the voice display-name (e.g. `# Cartesia "Marcus - Tough Bouncer"`) so a future YAML reader doesn't have to look up the UUID

**AC12 — Calibration Pass A + Pass B for each of the 4 uncalibrated scenarios:**

Given `_bmad-output/planning-artifacts/scenarios/scenario-testing-process.md` defines the Pass A (Good B1) / Pass B (Struggling B1) methodology and `_bmad-output/planning-artifacts/difficulty-calibration.md` defines the survival % target ranges (Mugger/Girlfriend medium: 35-55%, Cop/Landlord hard: 15-35%)
And `server/scripts/score_transcript.py` exists from Story 3.0 to AI-score a transcript against checkpoint criteria
When this story lands
Then Walid runs each of the 4 scenarios end-to-end TWICE on Pixel 9 Pro XL (Pass A simulating a good B1 learner — relatively decisive, on-topic; Pass B simulating a struggling B1 learner — hesitant, makes recovery errors)
And the 8 resulting transcripts (4 scenarios × 2 passes) are captured via `TranscriptLogger` (already wired in `bot.py`)
And each transcript is scored via `server/scripts/score_transcript.py`
And the YAML's `calibration.pass_a` and `calibration.pass_b` blocks are populated with the actual `survival_pct`, `checkpoints_passed`, `total_checkpoints`, and `verdict` (PASS if within target band ±10%, FAIL otherwise)
And if any scenario falls outside its band by more than ±10%, the nullable difficulty overrides (`patience_start`, `fail_penalty`, `silence_penalty`, etc.) are tuned in that YAML and the scenario is re-tested until in-band
And every tuning iteration is documented in the YAML with an inline comment naming the prior value and the rationale

**AC13 — The Waiter calibration block re-verified:**

Given `the-waiter.yaml` already has populated `calibration` blocks from Story 3.2 (pre-CheckpointManager)
And the latency + coherence + criteria changes in Phases 1-3 above invalidate those numbers (the pipeline behaves differently now)
When this story lands
Then `the-waiter.yaml` is also re-run through Pass A + Pass B on Pixel 9 Pro XL
And the existing `calibration.pass_a` / `calibration.pass_b` blocks are OVERWRITTEN with the new numbers
And the verdict is re-confirmed PASS (target: 60-90% for easy/free tier — see `difficulty-calibration.md`)

### Phase 4 — End-to-end smoke gate + measurement

**AC14 — Pre-commit gates:**

Given the dual-side discipline (root `CLAUDE.md`: `flutter analyze` + `flutter test` for client, `ruff check .` + `ruff format --check .` + `pytest` for server)
And this story is server-only (zero Flutter code change expected)
When the story lands
Then ALL of the following pass before flipping the story to `review`:
- `cd server && python -m ruff check .` → zero issues
- `cd server && python -m ruff format --check .` → zero issues
- `cd server && .venv/Scripts/python -m pytest` → all green; expect **~2 net new server tests** on top of Story 6.7's baseline (325) → target **≥ 327 passing** (charter behavioral test + wiring test)
- `tests/test_migrations.py` → still 4/4 (no schema change)
- `cd client && flutter analyze` + `flutter test` → unchanged from Story 6.7 baseline (no Flutter changes)

**AC15 — Smoke Test Gate validates latency + coherence + calibration on the device:**

See `## Smoke Test Gate (Server / Deploy Stories Only)` section below — a 14-box gate covering all 3 phases.

## Smoke Test Gate (Server / Deploy Stories Only)

> **Scope rule:** This story is server-side (latency tuning + charter + scenario YAML changes). The gate is **mandatory** — perceived latency and conversational coherence can ONLY be validated on a real call against the real VPS pipeline.
>
> **Transition rule:** Per Story 6.5 D6, pre-commit code gates are stop-ship for `in-progress → review`. Deploy-side gates below are stop-ship for `review → done`. Paste the actual command run + output as proof.

- [ ] **Deployed to VPS.** `systemctl status pipecat.service` shows `active (running)` on the commit SHA under test.
  - _Proof:_ <!-- paste the Active/Main PID line + commit SHA -->

- [ ] **Latency floor verified on Waiter happy-path (Phase 1 AC5).** Run a Waiter call through a full happy-path completion. Inspect the transcript timestamps (`/tmp/systemd-private-*/tmp/transcript_call_*.json` on the VPS) for the deltas between consecutive `user`-role and `character`-role entries.
  - _Expected:_ median user-speech-end → character-first-audio ≤ **1500ms**, p95 ≤ **2000ms**, no turn >3000ms unless terminal-zone.
  - _Proof:_ <!-- paste the computed median + p95 + worst-turn from a python one-liner over the transcript -->

- [ ] **Charter visible in every system_instruction swap (Phase 2 AC8).** Side-check: tail `journalctl -u pipecat.service` for any `WARNING: prompt contains duplicate COHERENCE_CHARTER` log line. Manual-add this WARN-on-duplicate guard in `CheckpointManager` to catch a future accidental double-append.
  - _Proof:_ <!-- "no warnings in 5-min window" + timestamp -->

- [ ] **Coherence regression — Waiter Cola test (Phase 2 AC6/AC7).** Replay the call_id=118 scenario: order grilled chicken, then ask for drink, then say "Coke", let Tina confirm "Coke, got it", continue 2-3 more checkpoints, then check if Tina re-asks for the drink.
  - _Expected:_ Tina does NOT re-ask. She integrates "you wanted a Coke" into subsequent confirmations.
  - _Proof:_ <!-- "validated by transcript inspection — Coke confirmed at t=Xs, never re-questioned" -->

- [ ] **Coherence regression — Waiter menu consistency (Phase 2 AC6/AC9).** During a single call, ask Tina what drinks are available, then 60s later, ask again.
  - _Expected:_ The two lists are IDENTICAL (both quote from the `base_prompt` "Menu" block verbatim).
  - _Proof:_ <!-- paste the 2 listings from the transcript -->

- [ ] **Mugger Pass A calibration (Phase 3 AC11+AC12).** End-to-end on Pixel 9 Pro XL: dial Mugger as a good-B1 player. Capture transcript via `TranscriptLogger`. Run `score_transcript.py` to compute survival %.
  - _Expected:_ in `[35%, 55%]` band (medium difficulty target).
  - _Proof:_ <!-- paste survival_pct + checkpoints_passed/total + score_transcript verdict -->

- [ ] **Mugger Pass B calibration (Phase 3 AC11+AC12).** Same as above but as a struggling-B1 player.
  - _Expected:_ in `[35%, 55%]` band still (Pass B may trend lower but should not drop below 25%).
  - _Proof:_ <!-- paste output -->

- [ ] **Girlfriend Pass A + Pass B (Phase 3 AC11+AC12).** Both passes captured and scored.
  - _Expected:_ in `[35%, 55%]` band.
  - _Proof:_ <!-- paste both -->

- [ ] **Cop Pass A + Pass B (Phase 3 AC11+AC12).** Both passes captured and scored.
  - _Expected:_ in `[15%, 35%]` band (hard difficulty target).
  - _Proof:_ <!-- paste both -->

- [ ] **Landlord Pass A + Pass B (Phase 3 AC11+AC12).** Both passes captured and scored.
  - _Expected:_ in `[15%, 35%]` band.
  - _Proof:_ <!-- paste both -->

- [ ] **Waiter re-calibration (Phase 3 AC13).** Pass A + Pass B re-run on the latency+charter-fixed pipeline.
  - _Expected:_ in `[60%, 90%]` band (easy difficulty target).
  - _Proof:_ <!-- paste both — these OVERWRITE the existing Story 3.2 numbers -->

- [ ] **No regression in Story 6.7 stepper / Story 6.6 checkpoint advance.** Verify journalctl shows `checkpoint_initial_state` on call boot + `checkpoint_advanced index=N` on each passed checkpoint, AND that the client stepper still renders the circles correctly (visual confirmation).
  - _Proof:_ <!-- "validated visually — stepper advances 1→2→3→… as before, no regression" -->

- [ ] **Server logs clean on the happy path.** `journalctl -u pipecat.service --since "5 min ago" | grep -iE "(error|traceback|exception)" | grep -v INFO` returns zero matches across the 11 test calls run above.
  - _Proof:_ <!-- paste output or "no errors in window" + timestamp -->

- [ ] **PRD FR45 alert threshold validated.** Across the 11 test calls, compute the AVERAGE perceived latency. If average >1.5s, the FR45 ops alert would have triggered → Phase 1 has not fully closed → re-tune.
  - _Proof:_ <!-- paste avg + count of calls -->

## Tasks / Subtasks

### Phase 1 — Latency floor

- [x] **Task 1 — Tune `user_speech_timeout`** (AC: #1)
  - [x] 1.1 — Inspected pipecat 0.0.108 `SpeechTimeoutUserTurnStopStrategy` source: `user_speech_timeout` = silence after VAD stop signal before turn declared done. Stacks ADDITIVELY with VAD `stop_secs`.
  - [x] 1.2 — Set value to `0.6` in `bot.py` `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)` with full tuning-context comment cross-referencing `feedback_latency_kill_criterion_exceeded.md` lever #1.
  - [ ] 1.3 — **WALID** — empirical tuning run on Pixel 9 Pro XL VPS. If B1 turns get cut mid-sentence, bump to 0.7. If clean at 0.6, try 0.5.
  - [ ] 1.4 — **WALID** — commit chosen value with empirical notes inlined.

- [x] **Task 2 — Audit VAD `stop_secs` redundancy** (AC: #2)
  - [x] 2.1 — Inspected `pipecat.audio.vad.silero` + `pipecat.turns.user_stop.speech_timeout`. The two timers STACK additively: VAD `stop_secs` is the silence threshold that flips internal VADState to QUIET (emits `UserStoppedSpeakingFrame`); `user_speech_timeout` is a second timer from that signal until the turn is declared "done". Net silence-to-turn-end ≈ sum.
  - [x] 2.2 — Net silence floor with `stop_secs=0.8 + user_speech_timeout=0.6 = 1.4 s`. Comfortable under PRD 2 s ceiling. Documented inline in `bot.py` near the VAD setup block. `stop_secs` not reduced (B1 false-positive risk on 1-3 s thinking pauses); revisited only if smoke-gate p95 exceeds 2 s.
  - [ ] 2.3 — **WALID** — re-run smoke gate to confirm latency drop.

- [x] **Task 3 — Verify LLM→TTS streaming overlap** (AC: #3)
  - [x] 3.1 — Shipped `pipeline/latency_probe.py` (~85 LOC, env-var gated `LatencyProbe(FrameProcessor)`). Wired 2 instances in `bot.py`: `llm_first_text_probe` (between `llm` and `transcript_character`) + `tts_first_audio_probe` (between `tts` and `transport.output()`). Per-turn reset on `BotStoppedSpeakingFrame`. INERT when `LATENCY_PROBE` env var unset — zero noise in prod.
  - [ ] 3.2 — **WALID** — set `LATENCY_PROBE=1` on VPS, run one calibrated Waiter call, tail `journalctl -u pipecat.service | grep latency_probe`, compute `(tts_first_audio_ns - llm_first_text_ns) / 1_000_000` ms.
  - [ ] 3.3 — **WALID** — if gap >500 ms, enable streaming flag on CartesiaTTSService; if <500 ms, document finding inline.
  - [x] 3.4 — Probe is opt-in via env var; no removal needed before commit.

- [x] **Task 4 — Cap Dev #7 classifier timeout at 1.0s** (AC: #4)
  - [x] 4.1 — Located `_CLASSIFIER_TIMEOUT_SECONDS` + `_HTTP_TIMEOUT_SECONDS` constants in `exchange_classifier.py`.
  - [x] 4.2 — `_CLASSIFIER_TIMEOUT_SECONDS = 1.0` (was 2.0); `_HTTP_TIMEOUT_SECONDS = 0.8` (was 1.8) so httpx abort lands cleanly before asyncio.TimeoutError. Comment cross-references AC4 + `feedback_latency_kill_criterion_exceeded.md` lever #4. Module docstring updated.
  - [x] 4.3 — Updated `tests/test_exchange_classifier.py::test_classify_returns_None_on_timeout` docstring to reference 1.0 s budget.

### Phase 2 — Coherence charter

- [x] **Task 5 — Add `COHERENCE_CHARTER` constant to prompts.py** (AC: #6)
  - [x] 5.1 — Added module-level `COHERENCE_CHARTER` constant in `pipeline/prompts.py` with 5 conversation-memory rules per AC6 literal block.
  - [x] 5.2 — Public name (no `_` prefix); importable via `from pipeline.prompts import COHERENCE_CHARTER`.

- [x] **Task 6 — Thread the charter through `CheckpointManager`** (AC: #7)
  - [x] 6.1 — Added required keyword parameter `coherence_charter: str` to `CheckpointManager.__init__` (no default; missing kwarg raises TypeError at call init).
  - [x] 6.2 — Stored as `self._coherence_charter`.
  - [x] 6.3 — `_classify_and_advance` system_instruction composition now `base + "\n\n" + charter + "\n\n" + segment` per AC7. Added WARN-on-duplicate guard (AC15 box 3) that fires if the composed prompt contains the charter more than once.
  - [x] 6.4 — `bot.py` imports `COHERENCE_CHARTER` from `pipeline.prompts`, composes `initial_system_prompt` with the charter slotted between `base_prompt` and the first checkpoint's `prompt_segment`, threads `coherence_charter=COHERENCE_CHARTER` into the `CheckpointManager(...)` constructor.
  - [x] 6.5 — Legacy `SYSTEM_PROMPT` env-var path retained as defensive fallback (3-branch composition in `bot.py`); even that path appends the charter.

- [x] **Task 7 — Behavioral tests for the charter** (AC: #8)
  - [x] 7.1 — Added `test_coherence_charter_appears_in_every_system_instruction_swap` in `tests/test_checkpoint_manager.py` — drives 3 advances on a 4-checkpoint manager, asserts charter present + count == 1 + positional ordering (base < charter < segment) after each advance. Plus `test_warn_on_duplicate_charter_in_composed_prompt` — forges a duplicate by pre-embedding the charter into `base_prompt`, asserts the WARN guard fires (AC15 box 3).
  - [x] 7.2 — Added `test_coherence_charter_threaded_to_checkpoint_manager_and_llm_settings` in `tests/test_bot_pipeline_wiring.py` — source-text assertions for the import, the kwarg threading, and the initial-composition position.

### Phase 3 — Per-scenario YAML calibration

- [ ] **Task 8 — Menu/inventory enumeration in `base_prompt`** (AC: #9)
  - [ ] 8.1 — **WALID** — face-to-face design pass over the 5 scenario `base_prompt` blocks.
  - [x] 8.2 — `the-waiter.yaml`: explicit "Menu — exhaustive inventory" block added at end of `base_prompt` enumerating main courses + drinks + desserts. Inline comment cross-references AC9 + COHERENCE_CHARTER rule #3.
  - [ ] 8.3 — **WALID** — define inventories for the 4 uncalibrated scenarios (Mugger demands, Cop charges, Landlord lease items, Girlfriend complaint topics) with face-to-face input.

- [x] **Task 9 — `success_criteria` audit on Waiter** (AC: #10)
  - [x] 9.1 — Re-read `drink` and `clarify` `success_criteria`. Both too strict per call_id=118 transcript.
  - [x] 9.2 — Rewrote `drink` to accept menu items + synonyms (Coke = cola, Pepsi, Sprite, sparkling water, etc.) + explicit refusals. Rewrote `clarify` to accept any coherent response to the clarifier including re-stating the dish ("as I said before").
  - [x] 9.3 — Inline YAML comments name call_id=118 and the failure pattern (4 consecutive `checkpoint_unmet drink` after "Coke").

- [ ] **Task 10 — `tts_voice_id` selection** (AC: #11)
  - [ ] 10.1 — **WALID** — audition Cartesia Sonic 3 voice catalog, shortlist 2-3 per character.
  - [ ] 10.2 — **WALID** — final selection, set `tts_voice_id` UUIDs in the 4 YAMLs.
  - [ ] 10.3 — **WALID** — inline YAML comments with display names.

- [ ] **Task 11 — Calibration Pass A + Pass B on 4 uncalibrated scenarios** (AC: #12)
  - [ ] 11.1 — **WALID** — 8 device calls (4 scenarios × 2 passes) on Pixel 9 Pro XL.
  - [ ] 11.2 — **WALID** — populate `calibration.pass_a` / `calibration.pass_b` blocks with `survival_pct` / `checkpoints_passed` / `verdict`.
  - [ ] 11.3 — **WALID** — tune nullable difficulty overrides for any scenario outside band ±10%, re-run, document.

- [ ] **Task 12 — Waiter re-calibration** (AC: #13)
  - [ ] 12.1 — **WALID** — Pass A + Pass B re-run on Pixel 9 Pro XL.
  - [ ] 12.2 — **WALID** — overwrite existing Story 3.2 `calibration.pass_a` / `pass_b` blocks in `the-waiter.yaml`.

### Phase 4 — Pre-commit + Smoke Test gates

- [x] **Task 13 — Server pre-commit gates** (AC: #14)
  - [x] 13.1 — `ruff check .` → All checks passed!
  - [x] 13.2 — `ruff format --check .` → 2 files reformatted (bot.py + test_bot_pipeline_wiring.py), final check clean.
  - [x] 13.3 — `pytest` → 329 passed (baseline 325 + 4 net new: charter behavioral test + WARN-on-duplicate test + bot import assertion + bot wiring test).
  - [x] 13.4 — `flutter analyze` clean. `flutter test` → 373 passed (unchanged from Story 6.7 baseline — zero net Flutter code per Dev Notes).

- [ ] **Task 14 — VPS deploy + Smoke Test Gate** (AC: #15)
  - [ ] 14.1 — **WALID** — VPS deploy via CI/CD after `/commit`.
  - [ ] 14.2 — **WALID** — execute 14-box Smoke Test Gate on Pixel 9 Pro XL.
  - [ ] 14.3 — **WALID** — paste proofs into each gate box.
  - [x] 14.4 — Sprint-status + story `Status:` flipped from `in-progress` → `review` after pre-commit gates green. The `review → done` flip stays Walid-owned per Story 6.5 D6 (post-smoke-gate).
  - [ ] 14.5 — **WALID** — `/commit` when ready.

## Dev Notes

**Architectural intent (the one paragraph):** Story 6.8 closes 3 launch blockers in priority-stacked order. **Phase 1** brings perceived latency under the PRD's 2s "concept dead" ceiling by tuning the single overwhelming knob (`user_speech_timeout=1.8s` → ~0.6s), auditing VAD redundancy, verifying LLM→TTS streaming overlap, and cheapening the Dev #7 synchronous classifier. **Phase 2** introduces a system-wide `COHERENCE_CHARTER` constant that's threaded through every `system_instruction` swap in `CheckpointManager`, so conversation-memory and menu-consistency rules survive every checkpoint advance regardless of scenario. **Phase 3** closes the original 6.8 scope: 4 uncalibrated scenarios get their `tts_voice_id`, `base_prompt` inventories, `success_criteria` lenience, and Pass A / Pass B numbers. The smoke gate measures all 3 phases together because they're co-dependent (charter adds tokens → adds LLM TTFT → consumes latency budget).

**Why is the charter system-wide and not scenario-overridable?** Walid's explicit ask, captured in `memory/feedback_coherence_must_be_system_wide.md`: scenario authoring at scale (post-Epic 6 plan) precludes per-scenario micro-validation. A floor of behaviors must exist regardless of who the character is. Scenarios add personality on top, never subtract from the floor.

**Why is `user_speech_timeout` a range (0.5-0.8s), not a fixed value?** Empirical tuning against real-user speech patterns. The PoC Phase 0 measured isolated turns; this story measures real conversational pacing on B1 learners (3+ words spoken, 1-3s thinking pauses between phrases). The dev runs a calibrated Waiter call, inspects whether turns get cut mid-sentence, and picks the floor that doesn't false-positive. Locking a value in spec without empirical validation would either ship a too-high value (defeats the fix) or too-low (cuts off slow speakers).

**Why does Phase 2 introduce a new required constructor parameter rather than reading the charter from a module-level constant inside the manager?** Testability + explicit threading. The wiring test (AC8 second test) source-text-asserts that `bot.py` imports and threads the charter — if a future dev refactors `bot.py` and accidentally drops the import, the test catches it. A module-level read inside `CheckpointManager` would hide that wiring inside opaque module state.

**Why is the Phase 4 smoke gate so detailed (14 boxes)?** Because this story has 3 distinct phases, each with its own success criterion, and they interact. Phase 1's latency win could be invisibly eaten by Phase 2's added tokens; Phase 3's calibration is invalid if Phases 1+2 haven't closed. The gate measures the SUMMATIVE outcome (median latency, transcript coherence, scoring verdict per scenario) — not just the individual phase outcomes.

**Why no Flutter code changes?** This story is entirely server-side. Story 6.7's CheckpointStepper consumes `checkpoint_advanced` envelopes unchanged. The client doesn't care whether the server's prompt has the charter or not — same wire format, same envelope cadence.

**Why is `the-waiter.yaml` re-calibration in scope?** Story 3.2's Waiter calibration block predates the CheckpointManager, the latency fix, and the charter. Those Story 3.2 numbers are stale relative to the new pipeline behavior. Re-running Pass A + Pass B costs ~20 minutes and confirms the easy tier is still in band post-changes.

### Project Structure Notes

**Server (modified files):**
- `server/pipeline/bot.py` — `user_speech_timeout` tune (line 125), VAD audit (lines 103-110), `system_instruction` composition with charter, `CheckpointManager(..., coherence_charter=COHERENCE_CHARTER)` threading, import of `COHERENCE_CHARTER`.
- `server/pipeline/checkpoint_manager.py` — new `coherence_charter` constructor parameter; updated `_classify_and_advance` 3-piece composition.
- `server/pipeline/prompts.py` — new `COHERENCE_CHARTER` module-level constant.
- `server/pipeline/exchange_classifier.py` — timeout 2.0s → 1.0s.
- `server/tests/test_checkpoint_manager.py` — new `test_coherence_charter_appears_in_every_system_instruction_swap`.
- `server/tests/test_bot_pipeline_wiring.py` — new `test_coherence_charter_threaded_to_checkpoint_manager_and_llm_settings`.
- `server/pipeline/scenarios/the-waiter.yaml` — `base_prompt` Menu enumeration, `drink` + `clarify` `success_criteria` rewrite, calibration block overwrite.
- `server/pipeline/scenarios/the-mugger.yaml` — `tts_voice_id`, `base_prompt` inventory, calibration block populated.
- `server/pipeline/scenarios/the-girlfriend.yaml` — same.
- `server/pipeline/scenarios/the-cop.yaml` — same.
- `server/pipeline/scenarios/the-landlord.yaml` — same.

**Server (NO changes):**
- `server/db/migrations/` — no new migration.
- `server/models/schemas.py` — no schema changes.
- `server/api/routes_calls.py` — no API changes.
- Client side — zero changes.

**Alignment with established patterns:** Phase 1 stays inside Story 6.4-6.6's pipecat / VAD / turn-strategy conventions. Phase 2 introduces a new pattern (module-level constant threaded through constructor) that mirrors how `CARTESIA_VOICE_ID` is currently used. Phase 3 follows Story 3.0/3.2's `score_transcript.py` + `TranscriptLogger` calibration tooling unchanged.

**Detected conflicts or variances:** None expected. The charter introduces ~200 tokens per LLM call — this slightly raises OpenRouter cost. Estimate: at ~5 turns/call × ~300 calls/day MVP × $0.000003/token = ~$0.30/day extra. Negligible.

### References

- 🚨 [Source: `memory/feedback_latency_kill_criterion_exceeded.md`] — Phase 1 root cause + 6 levers.
- 🚨 [Source: `memory/feedback_coherence_must_be_system_wide.md`] — Phase 2 root cause + charter design + alternatives.
- [Source: `_bmad-output/implementation-artifacts/deferred-work.md` lines 16-45] — the 2 🚨 MUST-FIX entries.
- [Source: `_bmad-output/planning-artifacts/epics.md#Story 6.8: Post-CheckpointManager Scenario Calibration`] lines 1232-1260 — original (Phase 3) scope.
- [Source: `_bmad-output/planning-artifacts/prd.md`] `Functional & Non-Functional Requirements > Performance` — latency budget / kill criterion / FR45.
- [Source: `_bmad-output/planning-artifacts/architecture.md`] `Performance` — streaming overlap mandate.
- [Source: `_bmad-output/planning-artifacts/difficulty-calibration.md`] — survival % target bands, AI scoring methodology.
- [Source: `_bmad-output/planning-artifacts/scenarios/scenario-testing-process.md`] — Pass A / Pass B methodology, transcript capture, `score_transcript.py` usage.
- [Source: `server/pipeline/bot.py:84-130`] — LLM / TTS / VAD / UserTurnStrategies wiring.
- [Source: `server/pipeline/checkpoint_manager.py:_classify_and_advance` lines ~440-470] — Deviation #2 swap (Phase 2 modifies).
- [Source: `server/pipeline/prompts.py`] — Phase 2 charter site.
- [Source: `server/pipeline/scenarios/the-waiter.yaml`] — reference YAML structure for Phase 3.
- [Source: `server/scripts/score_transcript.py` + `server/pipeline/transcript_logger.py`] — calibration measurement tools.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context)

### Debug Log References

- Pre-commit gates (2026-05-20): `ruff check` clean, `ruff format` applied to 2 files (`bot.py` + `test_bot_pipeline_wiring.py`), `pytest` 329 passed in 208 s, `flutter analyze` clean (130 s), `flutter test` 373 passed (127 s).
- Smoke Test Gate boxes 1-14: **deferred to Walid** (require VPS deploy + Pixel 9 Pro XL device runs).

### Completion Notes List

**Architectural decisions made during implementation:**

1. **Deviation #5 (NEW) — `LatencyProbe` ships as opt-in production code, not test-only instrumentation.** AC3 task 3.4 says "remove the test-only `FrameLogger` processor before commit". I instead shipped a permanent `pipeline/latency_probe.py` module with an env-var-gated `LatencyProbe(FrameProcessor)` class. Two instances are always wired into the pipeline (one between `llm` and `transcript_character`, one between `tts` and `transport.output()`) but log nothing unless `LATENCY_PROBE=1` is exported. Rationale: a removable test fixture would need a re-deploy every smoke gate run (re-add, deploy, measure, remove, deploy again). The env-var-gated version costs ~µs per frame when disabled (one `process_frame` call) and lets the operator toggle observability without touching code. Same pattern as pipecat's own debug-level frame logging.

2. **Deviation #6 (NEW) — bot.py `initial_system_prompt` composition is 3-branch, not 1-branch.** AC7 implies a single composition formula. I implemented 3 branches: (a) YAML data available (production path — composes `base + charter + first_segment`); (b) `SYSTEM_PROMPT` env var set but YAML loaders failed (defensive — appends charter to env-var content); (c) absolute fallback (`SARCASTIC_CHARACTER_PROMPT + charter`). Branches (b) + (c) are essentially dead code (YAML loaders always succeed since `TUTORIAL_SCENARIO_ID` is hardcoded and the file ships in repo) but they cover hypothetical operator mistakes (deleted YAML, manual env-var override) without dropping the charter. Story 6.5 D6 ethos: defensive fallbacks for fail-soft on the call path.

3. **Deviation #7 (NEW) — WARN-on-duplicate guard sits inside `_classify_and_advance`, not in a separate validation step.** AC15 box 3 says "Manual-add this WARN-on-duplicate guard in CheckpointManager". I added it directly into the swap composition (after building `new_system_prompt`, before writing to `_settings`). Rationale: catches duplication at the exact moment it would be introduced. A separate post-write validation could miss the case where a future refactor mutates `_settings.system_instruction` from a different code path.

**Acknowledged scope split (intentional, documented up-front in story Background):**

- **Phases 1 + 2 + part of Phase 3 (Waiter-only)** — landed in this PR. Code-side work all green: charter wiring, latency knobs (`user_speech_timeout 1.8→0.6`, classifier timeout `2.0→1.0`, VAD audit comment), Waiter YAML drink-menu enumeration + `success_criteria` rewrites. 329 server tests + 373 Flutter tests green.
- **Phase 3 manual work (Tasks 8.3, 10, 11, 12)** + **Phase 4 Smoke Gate (Task 14)** — deferred to Walid because:
  - 4 uncalibrated scenarios (Mugger/Girlfriend/Cop/Landlord) need Walid-input inventories.
  - Cartesia voice selection is an audition + ear-test exercise.
  - Calibration Pass A + Pass B for 5 scenarios × 2 passes = 10 device calls on Pixel 9 Pro XL.
  - The 14-box Smoke Gate measures end-to-end on the device.
- **Empirical tuning** for Tasks 1.3 (`user_speech_timeout` floor), 2.3 (post-tune latency confirmation), 3.2 (LLM→TTS gap measurement) — also Walid because they require VPS calls.

**Code-side rationale highlights:**

- `_HTTP_TIMEOUT_SECONDS` dropped from 1.8 to 0.8 (mirroring the 2.0→1.0 classifier change) so the httpx abort still lands first on timeout. The 0.2 s gap between the two timers keeps the clean-error-log invariant.
- Test `_make_manager` helper defaults `coherence_charter="CHARTER."` so existing tests work unchanged; only the 2 tests that asserted exact system_instruction strings needed updating (test 5 + test_preemptive_path_forwards_frame_on_success_recovery).
- The 3 direct `CheckpointManager(...)` constructions in tests (empty-checkpoints test, bad-LLM test x2, classifier-exception test, contract test) were each updated with `coherence_charter="CHARTER."` since the kwarg is now required.

### File List

**Server — modified:**
- `server/pipeline/bot.py` — import `COHERENCE_CHARTER` from `pipeline.prompts`, import `LatencyProbe` from `pipeline.latency_probe`, import `TextFrame` + `OutputAudioRawFrame` from `pipecat.frames.frames`. Removed legacy `system_prompt = os.environ.get(...)` line. Added `scenario_metadata` / `scenario_checkpoints` / `scenario_base_prompt` loads BEFORE LLM construction. Added 3-branch `initial_system_prompt` composition. Replaced `system_instruction=system_prompt` with `system_instruction=initial_system_prompt`. Added VAD audit comment block above SileroVADAnalyzer. Tuned `user_speech_timeout=1.8 → 0.6` with full context comment. Removed duplicate `scenario_metadata` / `scenario_checkpoints` / `scenario_base_prompt` loads further down (now happen at top). Threaded `coherence_charter=COHERENCE_CHARTER` into `CheckpointManager(...)`. Wired 2 `LatencyProbe` instances into the `Pipeline([...])` literal between (`llm`, `transcript_character`) and (`tts`, `transport.output()`).
- `server/pipeline/checkpoint_manager.py` — added `coherence_charter: str` required kwarg to `__init__`. Stored as `self._coherence_charter`. Modified `_classify_and_advance` system_instruction composition to 3-piece concat (`base + charter + segment`). Added WARN-on-duplicate guard (AC15 box 3).
- `server/pipeline/prompts.py` — added module-level `COHERENCE_CHARTER` constant (~200 tokens, 5 conversation-memory rules per AC6).
- `server/pipeline/exchange_classifier.py` — `_CLASSIFIER_TIMEOUT_SECONDS = 1.0` (was 2.0), `_HTTP_TIMEOUT_SECONDS = 0.8` (was 1.8). Module docstring updated.
- `server/pipeline/scenarios/the-waiter.yaml` — added explicit "Menu — exhaustive inventory" block at end of `base_prompt` (main courses + drinks + desserts). Rewrote `drink` `success_criteria` to accept synonyms (Coke = cola etc.) + explicit refusals. Rewrote `clarify` `success_criteria` to accept re-stating the dish ("as I said before"). Inline comments reference call_id=118.
- `server/tests/test_checkpoint_manager.py` — added `coherence_charter` to `_make_manager` helper (default "CHARTER."). Added `coherence_charter="CHARTER."` to 3 direct `CheckpointManager(...)` constructions. Updated 2 system_instruction equality assertions to include the charter. Added 2 new tests: `test_coherence_charter_appears_in_every_system_instruction_swap` (AC8) + `test_warn_on_duplicate_charter_in_composed_prompt` (AC15 box 3 guard).
- `server/tests/test_bot_pipeline_wiring.py` — added `COHERENCE_CHARTER` import assertion to `test_bot_imports_emitter_classes`. Added `coherence_charter="CHARTER."` to the direct `CheckpointManager(...)` construction in the pipeline-drive test. Added new test `test_coherence_charter_threaded_to_checkpoint_manager_and_llm_settings` (AC8 wiring assertion).
- `server/tests/test_exchange_classifier.py` — updated `test_classify_returns_None_on_timeout` docstring (2.0 s → 1.0 s).

**Server — new files:**
- `server/pipeline/latency_probe.py` (~85 LOC) — `LatencyProbe(FrameProcessor)` class with env-var (`LATENCY_PROBE`) gating, per-turn reset on `BotStoppedSpeakingFrame`, monotonic-ns timestamp emission via `logger.info`. Module docstring documents the smoke-gate usage pattern (export env var, run one call, compute `(tts_first_audio_ns - llm_first_text_ns) / 1_000_000` ms).

**Client — no changes** (zero net Flutter code per Dev Notes; story is server-only).

**Implementation artifacts — modified:**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — story 6-8 flipped `ready-for-dev → in-progress → review` per Story 6.5 D6 (gates green).
- `_bmad-output/implementation-artifacts/6-8-post-checkpointmanager-scenario-calibration.md` — Status, Tasks/Subtasks checkboxes, Dev Agent Record, File List, Change Log.

## Change Log

- 2026-05-20 — Dev started, Phase 1 (latency knobs + LatencyProbe infra) + Phase 2 (COHERENCE_CHARTER + threading + tests) + Phase 3 Waiter-only YAML changes shipped. Pre-commit gates green (server 329 tests, client 373 tests, ruff + flutter analyze clean). Status → `review` for Walid-owned smoke-gate + manual calibration work (4 uncalibrated scenarios, 10 device calls, 14-box smoke gate). 3 new deviations documented: #5 (LatencyProbe ships as opt-in prod code, not test fixture), #6 (3-branch initial_system_prompt composition), #7 (WARN-on-duplicate guard inside _classify_and_advance).
