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
    """`bot.py` imports `EmotionEmitter` and does NOT import the removed
    `VisemeEmitter`."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert "from pipeline.emotion_emitter import EmotionEmitter" in source
    assert "VisemeEmitter" not in source


def test_bot_instantiates_emitters() -> None:
    """`bot.py` instantiates `EmotionEmitter` with the expected constructor
    args. `VisemeEmitter` must NOT appear anywhere."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert "EmotionEmitter(" in source
    assert "character=scenario_character" in source
    assert "openrouter_api_key=settings.openrouter_api_key" in source
    assert "VisemeEmitter" not in source


def test_bot_pipeline_ordering() -> None:
    """`emotion_emitter` sits between `transcript_user` and the user context
    aggregator. The TTS → transport.output() ordering is asserted on its own
    (no longer split by a viseme_emitter step).

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
    )
    assert _idx("tts") < _idx("transport.output()")


def test_bot_reads_scenario_character_env_var() -> None:
    """`bot.py` reads `SCENARIO_CHARACTER` from os.environ with a default."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert 'os.environ.get("SCENARIO_CHARACTER")' in source
