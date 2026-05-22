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
    assert "from pipeline.checkpoint_manager import CheckpointManager" in source
    assert "from pipeline.exchange_classifier import ExchangeClassifier" in source
    # Story 6.8 Phase 2 AC8 — wiring assertion for the charter import.
    assert "COHERENCE_CHARTER" in source
    # Story 6.9 — DTLN noise suppression must be imported AND wired into
    # LiveKitParams(audio_in_filter=...).
    assert "from pipeline.dtln_audio_filter import DTLNAudioFilter" in source
    # Story 6.9 review patch (D3) — EndpointWatchdog backstop for Soniox
    # endpoint detection. Imported AND positioned immediately after STT
    # in the pipeline (see `test_bot_pipeline_ordering` below).
    assert "from pipeline.endpoint_watchdog import EndpointWatchdog" in source
    assert "VisemeEmitter" not in source


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
    assert "openrouter_api_key=settings.openrouter_api_key" in source
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
    # Story 6.9b — model id sourced from Settings so the operator can
    # flip providers via env override at deploy time without a code
    # release. The kwarg MUST land on the ExchangeClassifier
    # construction site (not just be referenced elsewhere) — a
    # forgotten thread would silently keep the hardcoded default.
    assert "model=settings.classifier_model" in source
    # Story 6.9b migration (2026-05-22) — ExchangeClassifier now uses
    # Groq Llama 3.3 70B. The provider-neutral `api_key` kwarg replaced
    # `openrouter_api_key`, and it MUST be threaded from
    # `Settings.groq_api_key`. EmotionEmitter stays on Qwen via
    # OpenRouter (asserted above on `openrouter_api_key=settings.
    # openrouter_api_key`), so the two assertions co-exist intentionally.
    assert "api_key=settings.groq_api_key" in source
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
      - composed into the initial `OpenRouterLLMService.Settings(
        system_instruction=...)` call so the FIRST LLM turn already
        has coherence rules (without this, the very first user turn
        would be answered under a charter-less prompt and the smoke
        gate's call_id=118 replay would fail).

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
    # coherence. The composition uses string concatenation with
    # COHERENCE_CHARTER as a substring; check the symbol appears near
    # the OpenRouterLLMService construction site.
    llm_start = code.find("OpenRouterLLMService(")
    assert llm_start != -1, "OpenRouterLLMService construction not found"
    llm_end = code.find(")", llm_start) + 1
    # Walk back a bit to capture the `initial_system_prompt = (...)`
    # block that's typically just above the LLM construction.
    window_start = max(0, llm_start - 800)
    composition_window = code[window_start:llm_end]
    assert "COHERENCE_CHARTER" in composition_window, (
        "the initial OpenRouterLLMService system_instruction must be "
        "composed with COHERENCE_CHARTER so the first user turn already "
        "gets coherence rules — without this, call_id=118 replay would "
        "still see Tina forget the Coke 70 s later"
    )
    assert "initial_system_prompt" in composition_window, (
        "expected the initial_system_prompt local to compose the charter "
        "between base_prompt and the first checkpoint's prompt_segment"
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

    async def _stub_classify(**kwargs):
        invoked_with.append(kwargs)
        return False  # Don't advance, just observe the call happened.

    classifier.classify = _stub_classify  # type: ignore[assignment]

    checkpoints = [
        dict(
            id="cp0",
            hint_text="hint",
            prompt_segment="segment",
            success_criteria="User said something.",
        )
    ]

    patience_tracker = MagicMock()

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
        "ExchangeClassifier will be inert in prod and no checkpoint "
        "will ever advance — same failure mode as the Story 6.4 "
        "silence-ladder regression."
    )
    assert invoked_with[0]["user_text"] == "I want chicken."
