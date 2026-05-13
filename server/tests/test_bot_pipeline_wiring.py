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
    """`bot.py` imports `EmotionEmitter` + `PatienceTracker` and does NOT
    import the removed `VisemeEmitter`."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert "from pipeline.emotion_emitter import EmotionEmitter" in source
    assert "from pipeline.patience_tracker import PatienceTracker" in source
    assert "VisemeEmitter" not in source


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
    assert "VisemeEmitter" not in source


def test_bot_pipeline_ordering() -> None:
    """`emotion_emitter` sits between `transcript_user` and the user context
    aggregator. `patience_tracker` sits between `context_aggregator.user()`
    and `llm` (Story 6.4 / difficulty-calibration.md AD-2). The TTS →
    transport.output() ordering is asserted on its own (no longer split by
    a viseme_emitter step).

    Validated by scanning the Pipeline([...]) literal as a positional list.
    """
    source = _BOT_PATH.read_text(encoding="utf-8")
    start = source.find("pipeline = Pipeline(")
    assert start != -1, "Pipeline construction site not found in bot.py"
    end = source.find("task = PipelineTask", start)
    assert end != -1, "Cannot find pipeline-block terminator"
    block = source[start:end]

    def _idx(needle: str) -> int:
        i = block.find(needle)
        assert i != -1, f"missing pipeline element: {needle!r}"
        return i

    assert (
        _idx("transcript_user")
        < _idx("emotion_emitter")
        < _idx("context_aggregator.user()")
        < _idx("patience_tracker")
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
