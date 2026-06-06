"""Story 6.3 — Smoke test for `bot.py` pipeline wiring (AC3, AC9).

`run_bot` cannot be invoked synchronously in tests (it blocks on a real
LiveKit connection), so this test introspects the bot module's source and
asserts the emitter is imported AND instantiated in the right relative
position. The test is a wiring guard — a future refactor that moves the
emitter out of order (or removes it) would fail this test loudly.

Story 6.3b removed `VisemeEmitter` from the pipeline entirely: visemes
are now generated client-side from the PCM audio buffer about to hit the
speaker, so no server-side emitter exists. The wiring assertions below
cover the only emitter left (`EmotionEmitter`).
"""

from __future__ import annotations

import pathlib

_BOT_PATH = pathlib.Path(__file__).resolve().parent.parent / "pipeline" / "bot.py"


def test_bot_imports_emitter_classes() -> None:
    """`bot.py` imports `EmotionEmitter` + `PatienceTracker` +
    `CheckpointManager` + `ExchangeClassifier` (Story 6.6) +
    `COHERENCE_CHARTER` (Story 6.8 Phase 2) + `DTLNAudioFilter`
    (Story 6.9), and does NOT import the removed `VisemeEmitter`."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert "from pipeline.emotion_emitter import EmotionEmitter" in source
    assert "from pipeline.patience_tracker import PatienceTracker" in source
    # Story 6.10 — `bot.py` now imports CheckpointManager + the two
    # goal-composition helpers from a multi-line import block, so assert
    # the module + symbol rather than a single-line import string.
    assert "from pipeline.checkpoint_manager import (" in source
    assert "CheckpointManager," in source
    assert "format_remaining_goals_block," in source
    assert "format_suggested_focus_block," in source
    assert "from pipeline.exchange_classifier import ExchangeClassifier" in source
    # 2026-05-29 all-Groq migration + provider abstraction — the main
    # character LLM is built by the single switch-point factory
    # `pipeline/llm_provider.build_main_llm` (OpenAILLMService pointed at
    # the configured base_url lives THERE, not inline in bot.py). Was
    # OpenRouterLLMService/Qwen, which 429'd on OpenRouter's shared pool.
    assert "from pipeline.llm_provider import (" in source
    assert "build_main_llm," in source
    assert "resolve_llm_api_key," in source
    # raw-httpx sites need the FULL chat-completions URL (resolve_llm_chat_url),
    # not the base — conflating them was the checkpoints-404 regression.
    assert "resolve_llm_chat_url," in source
    assert "OpenRouterLLMService" not in source
    # Story 6.8 Phase 2 AC8 — wiring assertion for the charter import.
    assert "COHERENCE_CHARTER" in source
    # Story 6.9 — DTLN noise suppression must be imported AND wired into
    # LiveKitParams(audio_in_filter=...).
    assert "from pipeline.dtln_audio_filter import DTLNAudioFilter" in source
    # Story 6.9 review patch (D3) — EndpointWatchdog backstop for Soniox
    # endpoint detection. Imported AND positioned immediately after STT
    # in the pipeline (see `test_bot_pipeline_ordering` below).
    assert "from pipeline.endpoint_watchdog import EndpointWatchdog" in source
    # Story 6.11 — EnvironmentMonitor (parasitic-voice detection).
    assert "from pipeline.environment_monitor import EnvironmentMonitor" in source
    # Story 6.11 fix — InputGate ("stop listening" so the noise exit line
    # can't be interrupted).
    assert "from pipeline.input_gate import InputGate" in source
    assert "VisemeEmitter" not in source


def test_bot_wires_input_gate_first_and_arms_via_monitor() -> None:
    """Story 6.11 fix (call_id=205) — InputGate must sit at the TOP of the
    pipeline (after transport.input(), before stt) so muting starves the
    VAD + STT at the source, and EnvironmentMonitor must receive it so it can
    arm it on detection."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert "InputGate()" in source
    assert "input_gate=input_gate" in source  # threaded into EnvironmentMonitor

    start = source.find("pipeline = Pipeline(")
    end = source.find("task = PipelineTask", start)
    block = "\n".join(
        line
        for line in source[start:end].splitlines()
        if not line.lstrip().startswith("#")
    )

    def _idx(needle: str) -> int:
        i = block.find(needle)
        assert i != -1, f"missing pipeline element: {needle!r}"
        return i

    assert _idx("transport.input()") < _idx("input_gate") < _idx("stt")


def test_bot_enables_soniox_speaker_diarization() -> None:
    """Story 6.11 AC1 — `enable_speaker_diarization=True` on the Soniox
    settings. Without it, `TranscriptionFrame.result` carries no `speaker`
    ids and EnvironmentMonitor can never detect a parasitic voice."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "enable_speaker_diarization=True" in body


def test_bot_instantiates_and_wires_environment_monitor() -> None:
    """Story 6.11 AC2 — EnvironmentMonitor is constructed with the call's
    PatienceTracker, and the noisy-environment exit line is threaded into
    PatienceTracker from the resolved config."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    # Construction is multi-line since the Story 6.11 InputGate fix
    # (patience_tracker= + input_gate= kwargs) — assert symbol + kwarg, not a
    # single-line call string.
    assert "EnvironmentMonitor(" in source
    assert "patience_tracker=patience_tracker" in source
    assert "hang_up_line_noisy_environment=patience_config[" in source
    assert '"hang_up_line_noisy_environment"' in source


def test_bot_wires_dtln_audio_filter_into_livekit_params() -> None:
    """Story 6.9 — the DTLN noise suppression filter MUST be passed to
    `LiveKitParams(audio_in_filter=...)`. Pipecat applies `audio_in_filter`
    BEFORE VAD + STT, so the entire downstream chain (Silero VAD, Soniox,
    emotion + exchange classifiers, CheckpointManager, PatienceTracker)
    sees denoised audio. A missing wiring would silently leave the call
    on noisy audio — the smoke gate would catch it, but the wiring test
    catches the regression at pre-commit time.
    """
    source = _BOT_PATH.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "DTLNAudioFilter(" in code, (
        "bot.py must instantiate DTLNAudioFilter — found import but no "
        "construction site"
    )
    assert "audio_in_filter=audio_in_filter" in code, (
        "bot.py must pass the DTLNAudioFilter instance to "
        "LiveKitParams(audio_in_filter=...) — otherwise the filter is "
        "constructed but never wired into the audio path"
    )


def test_bot_dtln_has_env_kill_switch() -> None:
    """Story 6.13 follow-up — DTLN must be gated by `DTLN_ENABLED` (default
    on) so it can be disabled via env + restart for the connection-jitter
    A/B (does DTLN's per-frame ONNX inference on the 2-core VPS starve the
    asyncio loop → bursty audio-out → 5G playout stretch?) and for ops,
    without a code release. When disabled, `audio_in_filter` falls back to
    None — pipecat's no-filter default.
    """
    source = _BOT_PATH.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert 'os.environ.get("DTLN_ENABLED"' in code, (
        "bot.py must gate DTLN behind the DTLN_ENABLED env var so it can be "
        "toggled via env + restart"
    )
    assert "audio_in_filter = None" in code, (
        "the DTLN-disabled branch must set audio_in_filter=None "
        "(pipecat no-filter default)"
    )


def test_bot_instantiates_emitters() -> None:
    """`bot.py` instantiates `EmotionEmitter` + `PatienceTracker` with the
    expected constructor args. `VisemeEmitter` must NOT appear anywhere.

    PatienceTracker is constructed via explicit keyword extraction from
    `patience_config` (Story 6.4 cleanup) so future changes to the
    `_DIFFICULTY_PRESETS` shape don't silently break this constructor.
    """
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert "EmotionEmitter(" in source
    assert "character=scenario_character" in source
    # 2026-05-29 — EmotionEmitter runs on the shared LLM provider
    # (resolved key/base_url, asserted below) + its own emotion_model.
    assert "model=settings.emotion_model" in source
    assert "PatienceTracker(" in source
    # All 8 fields returned by `resolve_patience_config` are passed to
    # the PatienceTracker constructor (Deviation #15). The 4 dormant
    # fields are stored on the instance for forward-compat with Stories
    # 6.6 / 6.7 / DW1 — wiring them explicitly here means a future
    # rename of a preset key surfaces as a KeyError at process start,
    # not as a silent drop.
    assert 'initial_patience=patience_config["initial_patience"]' in source
    assert 'fail_penalty=patience_config["fail_penalty"]' in source
    assert 'silence_penalty=patience_config["silence_penalty"]' in source
    assert 'recovery_bonus=patience_config["recovery_bonus"]' in source
    assert 'silence_prompt_seconds=patience_config["silence_prompt_seconds"]' in source
    # Story 6.13 AC3 — per-difficulty stage-1 anchor threaded from the
    # resolved config. A forgotten thread would silently fall back to a
    # constructor default (no default exists today — would TypeError),
    # but a future default could mask a misconfigured YAML.
    assert (
        'ladder_impatience_seconds=patience_config["ladder_impatience_seconds"]'
        in source
    )
    assert 'silence_hangup_seconds=patience_config["silence_hangup_seconds"]' in source
    assert 'escalation_thresholds=patience_config["escalation_thresholds"]' in source
    assert 'total_checkpoints=patience_config["total_checkpoints"]' in source
    # Story 6.6 — new exit-line kwargs threaded into PatienceTracker.
    assert 'hang_up_line_silence=patience_config["hang_up_line_silence"]' in source
    assert (
        'hang_up_line_inappropriate=patience_config["hang_up_line_inappropriate"]'
        in source
    )
    assert 'hang_up_line_survived=patience_config["hang_up_line_survived"]' in source
    assert 'patience_warning_line=patience_config["patience_warning_line"]' in source
    # Story 6.6 — CheckpointManager + ExchangeClassifier instantiation.
    assert "ExchangeClassifier(" in source
    assert "CheckpointManager(" in source
    # 2026-05-29 — the main character LLM is built by the provider factory
    # (the single switch point); bot.py no longer constructs the service
    # inline.
    assert (
        "build_main_llm(settings, system_instruction=initial_system_prompt)" in source
    )
    # Story 6.9b — model id sourced from Settings so the operator can
    # flip providers via env override at deploy time without a code
    # release. The kwarg MUST land on the ExchangeClassifier
    # construction site (not just be referenced elsewhere) — a
    # forgotten thread would silently keep the hardcoded default.
    assert "model=settings.classifier_model" in source
    # 2026-05-29 provider abstraction — all LLM calls resolve key + base_url
    # via the `pipeline.llm_provider` helpers (the single switch point), not
    # a raw `settings.groq_api_key` / hardcoded URL. Asserted once via
    # `in source` (covers the classifier + emotion + warm-up call sites).
    assert "api_key=resolve_llm_api_key(settings)" in source
    # The raw-httpx LLM calls (classifier/emotion/warm-up) get the FULL
    # chat-completions endpoint, NOT the base — otherwise they 404.
    assert "base_url=resolve_llm_chat_url(settings)" in source
    assert "VisemeEmitter" not in source


def test_bot_pipeline_ordering() -> None:
    """`emotion_emitter`, `checkpoint_manager`, and `patience_tracker` all
    sit BEFORE `context_aggregator.user()` so they observe raw finalized
    `TranscriptionFrame`s from STT before the aggregator consumes them
    (pipecat 0.0.108 `LLMUserAggregator._handle_transcription` does not
    push downstream — verified in source line 509-510). Story 6.6
    Deviations #5 (CheckpointManager) and #29 (PatienceTracker — added
    2026-05-18 post-deploy after the silence-ladder regression). The
    TTS → transport.output() ordering is asserted on its own (no longer
    split by a viseme_emitter step).

    Validated by scanning the Pipeline([...]) literal as a positional list.
    """
    source = _BOT_PATH.read_text(encoding="utf-8")
    start = source.find("pipeline = Pipeline(")
    assert start != -1, "Pipeline construction site not found in bot.py"
    end = source.find("task = PipelineTask", start)
    assert end != -1, "Cannot find pipeline-block terminator"
    block = source[start:end]
    # Strip comment lines before scanning so a comment that happens to
    # mention a pipeline-element name (e.g. "the llm service") doesn't
    # poison the positional `find` lookup.
    block = "\n".join(
        line for line in block.splitlines() if not line.lstrip().startswith("#")
    )

    def _idx(needle: str) -> int:
        i = block.find(needle)
        assert i != -1, f"missing pipeline element: {needle!r}"
        return i

    # Story 6.6 Deviation #5 — checkpoint_manager BEFORE the aggregator
    # (pipecat consumes TranscriptionFrames internally).
    # Story 6.6 Deviation #29 — patience_tracker also BEFORE the
    # aggregator, same root cause. Its `_cancel_silence_timer()` path
    # on TranscriptionFrame observation was dormant in prod since
    # Story 6.4 (aggregator absorbed the frame). The bug surfaced on
    # the first Story 6.6 call: silence ladder ran through all stages
    # while user was actively speaking, hangup fired even after
    # checkpoint advanced.
    assert (
        # Story 6.9 review patch (D3) — endpoint_watchdog sits
        # immediately downstream of stt and BEFORE transcript_user so it
        # observes Soniox's raw TF stream first. The synthesised
        # finalized frame must propagate through transcript_user +
        # emotion_emitter + checkpoint_manager + patience_tracker.
        _idx("endpoint_watchdog")
        < _idx("transcript_user")
        # Story 6.11 — EnvironmentMonitor observes raw finalized TFs
        # BEFORE emotion_emitter (and the aggregator), same rationale.
        < _idx("environment_monitor")
        < _idx("emotion_emitter")
        < _idx("checkpoint_manager")
        < _idx("patience_tracker")
        < _idx("context_aggregator.user()")
        < _idx("llm")
    )
    assert _idx("tts") < _idx("transport.output()")


def test_bot_reads_scenario_character_env_var() -> None:
    """`bot.py` reads `SCENARIO_CHARACTER` from os.environ with a default."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert 'os.environ.get("SCENARIO_CHARACTER")' in source


def test_bot_reads_scenario_id_env_var() -> None:
    """Story 6.4 — `SCENARIO_ID` is the third env var injected by
    `routes_calls.initiate_call`. `bot.py` reads it with a fallback to
    the tutorial scenario for the legacy `/connect` path.
    """
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert 'os.environ.get("SCENARIO_ID")' in source
    assert "TUTORIAL_SCENARIO_ID" in source
    assert "resolve_patience_config(scenario_id)" in source


def test_on_first_participant_joined_queues_initial_envelope_via_task() -> None:
    """Story 6.7 AC1 + Phase 2 retouche #4 — `bot.py::
    on_first_participant_joined` MUST queue the initial
    `checkpoint_advanced(index=0)` envelope via
    `task.queue_frames([...])` (alongside the canned greeting
    `TTSSpeakFrame`), NOT via `checkpoint_manager.emit_initial_state()`.

    Why: `emit_initial_state` calls `push_frame` from the
    `CheckpointManager` processor, which pipecat's `_check_started`
    silently rejects when `StartFrame` hasn't yet propagated to that
    processor (`on_first_participant_joined` can fire BEFORE the
    StartFrame reaches `CheckpointManager`). The reject is logged as
    an ERROR but the frame is dropped — the client never sees the
    initial state envelope and the CheckpointStepper stays blank
    until the first real advance.

    `task.queue_frames` puts both frames into the task's source
    queue, which is drained AFTER StartFrame propagation. Both then
    flow downstream in order, reach `transport.output()`, and ship.
    """
    source = _BOT_PATH.read_text(encoding="utf-8")
    # Strip comment-only lines so a `# was using emit_initial_state()`
    # docstring reference doesn't false-positive the regression-guard
    # assertion below (mirrors `test_bot_pipeline_ordering`).
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert '@transport.event_handler("on_first_participant_joined")' in code
    # Story 6.7 Phase 2 retouche #5 — the initial envelope is
    # scheduled by the manager (`schedule_initial_emit`); the
    # actual `push_frame` runs from inside `process_frame` on the
    # first post-StartFrame tick, so the envelope rides the same
    # downstream chain as the working `_classify_and_advance`
    # envelopes (no source-side `task.queue_frames` injection).
    assert "checkpoint_manager.schedule_initial_emit()" in code
    # Make sure we did NOT regress to the broken
    # `await checkpoint_manager.emit_initial_state()` pattern.
    assert "checkpoint_manager.emit_initial_state()" not in code


def test_bot_routes_playback_idle_to_patience_tracker() -> None:
    """Story 6.4 — the `on_data_received` event handler must route
    `{"type":"playback_idle"}` envelopes from the client onto
    `PatienceTracker.handle_playback_idle()`. This is the canonical
    silence-clock start signal, replacing the server-side
    `BotStoppedSpeakingFrame` trigger that suffered from a ~1 s
    frame-of-reference shift due to WebRTC jitter buffering.
    """
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert '@transport.event_handler("on_data_received")' in source
    assert 'envelope_type == "playback_idle"' in source
    assert "patience_tracker.handle_playback_idle()" in source


# ============================================================
# Story 6.8 Phase 2 — COHERENCE_CHARTER wiring (AC8 second assertion)
# ============================================================


def test_coherence_charter_threaded_to_checkpoint_manager_and_llm_settings() -> None:
    """Story 6.8 Phase 2 AC8 — source-text wiring assertions for the
    charter. The charter MUST be:
      - imported from `pipeline.prompts` (else `bot.py` would crash at
        import after the constant is added);
      - threaded into the `CheckpointManager(...)` constructor as the
        `coherence_charter=COHERENCE_CHARTER` kwarg (else the manager
        would refuse construction because the kwarg is required);
      - composed into the initial `system_instruction` passed to the main
        LLM (via `build_main_llm(settings, system_instruction=...)`) so the
        FIRST LLM turn already has coherence rules (without this, the very
        first user turn would be answered under a charter-less prompt and
        the smoke gate's call_id=118 replay would fail).

    Source-text matching is fragile (renames break it) — when bot.py
    refactors, expect to re-verify the assertions.
    """
    source = _BOT_PATH.read_text(encoding="utf-8")

    # Import wiring.
    assert "COHERENCE_CHARTER" in source, (
        "bot.py must import COHERENCE_CHARTER from pipeline.prompts so "
        "the symbol is in scope for the CheckpointManager kwarg + the "
        "initial system_instruction composition"
    )

    # Manager kwarg wiring — strip comment-only lines so a docstring
    # mention of the kwarg doesn't false-positive.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "coherence_charter=COHERENCE_CHARTER" in code, (
        "bot.py must thread coherence_charter=COHERENCE_CHARTER into "
        "the CheckpointManager(...) constructor — the kwarg is required, "
        "a missing thread would surface as TypeError at call init"
    )

    # Initial composition wiring — the charter must be slotted into the
    # initial `system_instruction` so the first user turn already gets
    # coherence. Story 6.13: anchor on the composition block + the LLM's
    # consumption of it, NOT on raw proximity (the old `llm_start - 800`
    # window broke when the DTLN env-gate was added between the
    # composition and the LLM construction — exactly the "fragile on
    # refactor" caveat above).
    assert "system_instruction=initial_system_prompt" in code, (
        "the main LLM must be built with system_instruction="
        "initial_system_prompt so the first LLM turn uses the composed "
        "prompt (base + charter + remaining-goals blocks)"
    )
    comp_start = code.find("initial_system_prompt = (")
    assert comp_start != -1, (
        "expected the `initial_system_prompt = (...)` composition block in bot.py"
    )
    composition_block = code[comp_start : comp_start + 600]
    assert "COHERENCE_CHARTER" in composition_block, (
        "the initial_system_prompt composition must slot COHERENCE_CHARTER "
        "between base_prompt and the first checkpoint's prompt_segment so "
        "the first user turn already gets coherence rules — without this, "
        "call_id=118 replay would still see Tina forget the Coke 70 s later"
    )


# ============================================================
# Story 6.6 — Déviation-#28 pipeline-drive contract test
# (deferred-work line 369)
# ============================================================


def test_checkpoint_manager_observes_finalized_TranscriptionFrame_via_real_pipeline_drive():
    """**THIS IS THE DÉVIATION-#28 / #5 REGRESSION NET.**

    Background: Story 6.4 / 6.5 Déviation #28 was a silent 2-day prod
    regression because the unit test hard-coded `FrameDirection.DOWNSTREAM`
    when invoking `process_frame()` directly. Pipecat's real routing put
    `BotStoppedSpeakingFrame` UPSTREAM-only past `PatienceTracker`, so
    the production direction check (DOWNSTREAM) never fired.

    Story 6.6 Deviation #5: the FIRST deploy of CheckpointManager had it
    placed AFTER `context_aggregator.user()` (per the original spec).
    The `LLMUserAggregator` CONSUMES `TranscriptionFrame`s
    (see `llm_response_universal.py:509-510` — no `push_frame` after
    `_handle_transcription`), so the manager downstream of it never
    received a single TF. Zero classifier calls fired in prod on Test 1.
    The original version of this test used `Pipeline([manager])` alone
    (no aggregator), so it passed despite the bug — same trap as
    Déviation #28 (test setup that doesn't include the upstream
    processor that absorbs frames).

    This rewritten test now drives a TranscriptionFrame through a
    pipeline that **includes the real `LLMContextAggregatorPair.user()`**
    — i.e. the exact upstream processor the manager sits next to in
    `bot.py`. If a future refactor moves the manager to a position
    downstream of an absorber (any aggregator, gate, filter that
    consumes the frame type), this test breaks loud.

    See `server/CLAUDE.md` §1 "Frame-direction tests" for the broader
    pattern and project memory 🪤 `feedback_pipecat_frame_direction_test_trap.md`.
    """
    import asyncio
    from unittest.mock import MagicMock

    from pipecat.frames.frames import EndFrame, TranscriptionFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
    )

    from pipeline.checkpoint_manager import CheckpointManager
    from pipeline.exchange_classifier import ExchangeClassifier

    # Stub LLM that exposes the `._settings.system_instruction` field
    # CheckpointManager mutates on advance.
    class _StubSettings:
        def __init__(self) -> None:
            self.system_instruction = "initial"

    class _StubLLM:
        def __init__(self) -> None:
            self._settings = _StubSettings()

    # Track classifier invocations.
    invoked_with: list[dict] = []

    classifier = ExchangeClassifier(api_key="test-key")

    # Story 6.10 — the manager now calls `classify_multi` (goal-based
    # dialogue). Stub it so the real Groq HTTP path is never hit; return
    # all-unmet so no goal flips — we only need to prove the multi-goal
    # classify path RAN end-to-end through a real pipeline.
    async def _stub_classify_multi(**kwargs):
        invoked_with.append(kwargs)
        return {g["id"]: False for g in kwargs["pending_goals"]}

    classifier.classify_multi = _stub_classify_multi  # type: ignore[assignment]

    checkpoints = [
        dict(
            id="cp0",
            hint_text="hint",
            prompt_segment="segment",
            success_criteria="User said something.",
        )
    ]

    patience_tracker = MagicMock()
    # Story 6.22 — process_frame now early-suppresses finalized user turns when
    # `is_hanging_up` is truthy; a bare auto-Mock would drop this contract
    # test's TF before the classifier runs (and the `is_terminal_turn`
    # comparison needs real ints). Pin a real non-hang-up tracker.
    patience_tracker.is_hanging_up = False
    patience_tracker.patience = 100
    patience_tracker.fail_penalty = -15

    manager = CheckpointManager(
        base_prompt="BASE.",
        checkpoints=checkpoints,
        llm=_StubLLM(),
        llm_context=LLMContext(),
        classifier=classifier,
        patience_tracker=patience_tracker,
        scenario_description="contract-test",
        coherence_charter="CHARTER.",
    )

    # Build a pipeline that mirrors `bot.py`'s production ordering for
    # the user-side processors: manager sits BEFORE the user aggregator
    # (Deviation #5). The aggregator consumes TranscriptionFrames
    # internally; if the manager were placed AFTER it (as the original
    # spec said), this test would fail with zero classifier calls — the
    # exact prod regression we're guarding against. We use the default
    # `LLMContextAggregatorPair` constructor (no VAD, no turn strategies)
    # because the test only needs to prove the aggregator absorbs the
    # frame — full turn-boundary detection is irrelevant here AND the
    # SileroVADAnalyzer transitively imports torch which contaminates
    # the test environment for later tests.
    context = LLMContext()
    aggregator_pair = LLMContextAggregatorPair(context)
    pipeline = Pipeline([manager, aggregator_pair.user()])
    task = PipelineTask(pipeline)

    async def _drive() -> None:
        await task.queue_frames(
            [
                TranscriptionFrame(
                    text="I want chicken.",
                    user_id="user",
                    timestamp="2026-05-15T12:00:00Z",
                    finalized=True,
                ),
                EndFrame(),
            ]
        )
        runner = PipelineRunner()
        await runner.run(task)
        # The classifier task may still be in flight after the pipeline
        # tears down — drain it explicitly.
        if manager._in_flight is not None:
            await asyncio.gather(manager._in_flight, return_exceptions=True)

    asyncio.run(_drive())

    assert invoked_with, (
        "DÉVIATION-#28 REGRESSION: CheckpointManager did NOT observe the "
        "TranscriptionFrame when driven through a real PipelineTask. "
        "Either pipecat changed its frame-routing direction for "
        "TranscriptionFrame (re-verify against `pipecat.frames.frames` "
        "and `pipeline/bot.py` ordering) or the processor was moved to "
        "a position where user transcriptions don't reach it. The "
        "ExchangeClassifier will be inert in prod and no goal "
        "will ever flip — same failure mode as the Story 6.4 "
        "silence-ladder regression."
    )
    assert invoked_with[0]["user_text"] == "I want chicken."
    # Story 6.10 — the multi-goal classify path received the pending
    # goals (one entry per checkpoint on the first turn).
    pending = invoked_with[0]["pending_goals"]
    assert [g["id"] for g in pending] == ["cp0"]


# ============================================================
# Story 6.22 — post-hang-up suppression survives real pipeline routing
# ============================================================


def test_post_hangup_user_turn_suppressed_via_real_pipeline_drive():
    """Story 6.22 AC5 (pipeline-drive variant, server/CLAUDE.md §1) — drive a
    finalized user TranscriptionFrame through a REAL PipelineTask while the
    PatienceTracker is ALREADY hanging up. The CheckpointManager must DROP it:
    a recorder placed immediately downstream never sees it (so it never reaches
    `context_aggregator.user()` / the LLM, which would generate a reply over the
    exit line), and the classifier is never invoked. Proves the no-overlap
    guarantee holds under real pipecat routing, not just a mocked process_frame
    call — the mirror of the Déviation-#28 observe-the-frame contract test
    above (that one asserts the frame IS seen on a normal call; this one that
    it is NOT seen during a hang-up)."""
    import asyncio
    from unittest.mock import MagicMock

    from pipecat.frames.frames import EndFrame, TranscriptionFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineTask
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMContextAggregatorPair,
    )
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    from pipeline.checkpoint_manager import CheckpointManager
    from pipeline.exchange_classifier import ExchangeClassifier

    class _StubSettings:
        def __init__(self) -> None:
            self.system_instruction = "initial"

    class _StubLLM:
        def __init__(self) -> None:
            self._settings = _StubSettings()

    class _Recorder(FrameProcessor):
        """Records TranscriptionFrames that make it PAST the manager."""

        def __init__(self) -> None:
            super().__init__()
            self.seen: list[str] = []

        async def process_frame(self, frame: object, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, TranscriptionFrame):
                self.seen.append(frame.text)
            await self.push_frame(frame, direction)

    invoked_with: list[dict] = []
    classifier = ExchangeClassifier(api_key="test-key")

    async def _stub_classify_multi(**kwargs):
        invoked_with.append(kwargs)
        return {g["id"]: False for g in kwargs["pending_goals"]}

    classifier.classify_multi = _stub_classify_multi  # type: ignore[assignment]

    checkpoints = [
        dict(
            id="cp0",
            hint_text="hint",
            prompt_segment="segment",
            success_criteria="User said something.",
        )
    ]

    # Tracker already hanging up — the state AFTER the triggering terminal turn
    # scheduled the exit line.
    patience_tracker = MagicMock()
    patience_tracker.is_hanging_up = True
    patience_tracker.patience = 0
    patience_tracker.fail_penalty = -15

    manager = CheckpointManager(
        base_prompt="BASE.",
        checkpoints=checkpoints,
        llm=_StubLLM(),
        llm_context=LLMContext(),
        classifier=classifier,
        patience_tracker=patience_tracker,
        scenario_description="post-hangup-contract-test",
        coherence_charter="CHARTER.",
    )

    recorder = _Recorder()
    context = LLMContext()
    aggregator_pair = LLMContextAggregatorPair(context)
    pipeline = Pipeline([manager, recorder, aggregator_pair.user()])
    task = PipelineTask(pipeline)

    async def _drive() -> None:
        await task.queue_frames(
            [
                TranscriptionFrame(
                    text="Maybe you are someone else.",
                    user_id="user",
                    timestamp="2026-06-04T12:00:00Z",
                    finalized=True,
                ),
                EndFrame(),
            ]
        )
        runner = PipelineRunner()
        await runner.run(task)
        if manager._in_flight is not None:
            await asyncio.gather(manager._in_flight, return_exceptions=True)

    asyncio.run(_drive())

    assert invoked_with == [], (
        "post-hang-up turn must NOT be classified — a generated/normal reply "
        "would play over the exit line (Story 6.22 AC1/AC2)"
    )
    assert recorder.seen == [], (
        "post-hang-up turn must NOT be forwarded downstream past the "
        "CheckpointManager — it would reach the LLM and overlap the exit line"
    )


# ============================================================
# Story 6.18 — dynamic exit/patience-warning line generator wiring
# ============================================================


def test_bot_wires_dynamic_exit_line_generator_into_patience_tracker() -> None:
    """Story 6.18 — `bot.py` must:
      - import `generate_exit_line` from `pipeline.exit_line_generator`;
      - gate the feature on `settings.hangup_line_generation` (AC7 kill-switch);
      - build a closure that calls `generate_exit_line(...)` reading the LIVE
        transcript (`context.get_messages()`) + the bare persona + charter;
      - thread the resulting callable into PatienceTracker via
        `hang_up_line_generator=...`.

    Source-text matching is fragile (renames break it) — when bot.py refactors,
    re-verify these assertions.
    """
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert "from pipeline.exit_line_generator import generate_exit_line" in source

    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    # AC7 kill-switch — the whole feature is gated on the Settings flag.
    assert "settings.hangup_line_generation" in code, (
        "bot.py must gate dynamic exit-line generation on "
        "settings.hangup_line_generation (HANGUP_LINE_GENERATION env toggle)"
    )
    # The closure must actually call the generator with the live transcript.
    assert "generate_exit_line(" in code
    assert "context.get_messages()" in code, (
        "the generator closure must read the LIVE transcript at hang-up time "
        "so the line reflects what actually happened"
    )
    # Story 6.18 review (Decision #2 / Option A) — the closure must accept and
    # append the suppressed winning user turn on the survived path.
    assert "extra_user_text" in code, (
        "bot.py closure must accept extra_user_text and append the winning "
        "user turn to the transcript for the survived path"
    )
    # The callable is threaded into PatienceTracker (a missing thread would
    # silently leave the canned-line-only behaviour).
    assert "hang_up_line_generator=hang_up_line_generator" in code, (
        "bot.py must thread the generator into PatienceTracker via "
        "hang_up_line_generator=..."
    )


def test_bot_sources_user_speech_timeout_from_settings() -> None:
    """Story 6.18 smoke gate (call_id=215) — the turn-endpoint timeout must be
    sourced from Settings (USER_SPEECH_TIMEOUT), not hardcoded, so it's tunable
    on the VPS without a redeploy. 0.6 s chopped B1 hesitations ("Do you, uh,
    ooh.") into separate turns judged as failures (unfair patience drain)."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "user_speech_timeout=settings.user_speech_timeout" in code, (
        "bot.py must source user_speech_timeout from Settings, not hardcode it"
    )
    assert "user_speech_timeout=0.6" not in code, (
        "must not regress to the hardcoded 0.6 s that chopped B1 thinking pauses"
    )
