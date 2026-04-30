"""Story 6.3 — Smoke test for `bot.py` pipeline wiring (AC3, AC9).

`run_bot` cannot be invoked synchronously in tests (it blocks on a real
LiveKit connection), so this test introspects the bot module's source and
asserts the emitters are imported AND instantiated in the right relative
positions. The test is a wiring guard — a future refactor that moves the
emitters out of order (or removes them) would fail this test loudly.
"""

from __future__ import annotations

import pathlib

_BOT_PATH = pathlib.Path(__file__).resolve().parent.parent / "pipeline" / "bot.py"


def test_bot_imports_emitter_classes() -> None:
    """`bot.py` imports both `EmotionEmitter` and `VisemeEmitter`."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert "from pipeline.emotion_emitter import EmotionEmitter" in source
    assert "from pipeline.viseme_emitter import VisemeEmitter" in source


def test_bot_instantiates_emitters() -> None:
    """`bot.py` instantiates the emitters with the expected constructor args."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    # EmotionEmitter must receive both `character` and `openrouter_api_key`.
    assert "EmotionEmitter(" in source
    assert "character=scenario_character" in source
    assert "openrouter_api_key=settings.openrouter_api_key" in source
    # VisemeEmitter takes no args.
    assert "VisemeEmitter()" in source


def test_bot_pipeline_ordering() -> None:
    """`emotion_emitter` is between `transcript_user` and the user context
    aggregator; `viseme_emitter` is between `tts` and `transport.output()`.

    Validated by scanning the Pipeline([...]) literal as a positional list.
    """
    source = _BOT_PATH.read_text(encoding="utf-8")
    start = source.find("pipeline = Pipeline(")
    assert start != -1, "Pipeline construction site not found in bot.py"
    # The construction site is followed by `task = PipelineTask(...)` —
    # use that as the end-marker so the entire list literal is captured.
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
    assert _idx("tts") < _idx("viseme_emitter") < _idx("transport.output()")


def test_bot_reads_scenario_character_env_var() -> None:
    """`bot.py` reads `SCENARIO_CHARACTER` from os.environ with a default."""
    source = _BOT_PATH.read_text(encoding="utf-8")
    assert 'os.environ.get("SCENARIO_CHARACTER")' in source
