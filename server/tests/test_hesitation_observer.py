"""Story 7.1 (AC11) — tests for the hesitation gap observer.

Frames are driven through `process_frame` in their REAL directions (BSF
UPSTREAM from the output transport, UserStartedSpeakingFrame DOWNSTREAM from
VAD) with `push_frame` swapped for a recorder — the same standalone-processor
pattern as `test_patience_tracker.py`. A fake monotonic clock makes the gap
arithmetic deterministic.
"""

from __future__ import annotations

import asyncio

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    UserStartedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from pipeline.hesitation_observer import HesitationObserver


class _FakeCollector:
    def __init__(self, transcript=None):
        self.transcript = transcript or []


def _clock(values):
    it = iter(values)
    return lambda: next(it)


def _observer(*, transcript=None, clock_values, **kwargs) -> HesitationObserver:
    obs = HesitationObserver(
        collector=_FakeCollector(transcript), clock=_clock(clock_values), **kwargs
    )

    async def _recorder(frame: Frame, direction: FrameDirection) -> None:
        obs._pushed.append(frame)  # type: ignore[attr-defined]

    obs._pushed = []  # type: ignore[attr-defined]
    obs.push_frame = _recorder  # type: ignore[assignment]
    return obs


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_records_gap_above_threshold():
    obs = _observer(
        transcript=[{"role": "character", "text": "Talk properly.", "timestamp_ms": 0}],
        clock_values=[0.0, 5.0],  # BSF@0, UserStart@5 → 5 s gap
    )

    async def _drive():
        await obs.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await obs.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    _run(_drive())
    assert obs.top_hesitations() == [
        {
            "id": "h1",
            "duration_sec": 5.0,
            "preceding_character_line": "Talk properly.",
            "resolved": True,
        }
    ]


def test_ignores_gap_at_or_below_threshold():
    obs = _observer(
        transcript=[{"role": "character", "text": "x", "timestamp_ms": 0}],
        clock_values=[0.0, 2.5],  # 2.5 s < 3 s
    )

    async def _drive():
        await obs.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await obs.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    _run(_drive())
    assert obs.top_hesitations() == []


def test_user_start_without_pending_stop_is_ignored():
    # An interruption (user starts while/ before the bot-stop is registered).
    obs = _observer(transcript=[], clock_values=[1.0])

    async def _drive():
        await obs.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    _run(_drive())
    assert obs.top_hesitations() == []


def test_keeps_only_top_three_longest():
    obs = _observer(
        transcript=[{"role": "character", "text": "line", "timestamp_ms": 0}],
        # gaps: 10, 4, 7, 5  → top-3 desc: 10, 7, 5
        clock_values=[0, 10, 20, 24, 30, 37, 40, 45],
    )

    async def _drive():
        for _ in range(4):
            await obs.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
            await obs.process_frame(
                UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM
            )

    _run(_drive())
    durations = [h["duration_sec"] for h in obs.top_hesitations()]
    assert durations == [10.0, 7.0, 5.0]


def test_preceding_line_snapshotted_at_bot_stop():
    transcript = [{"role": "character", "text": "first line", "timestamp_ms": 0}]
    obs = _observer(transcript=transcript, clock_values=[0.0, 6.0])

    async def _drive():
        await obs.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        # A later character turn must NOT retroactively change the captured line.
        transcript.append({"role": "character", "text": "later", "timestamp_ms": 9})
        await obs.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    _run(_drive())
    assert obs.top_hesitations()[0]["preceding_character_line"] == "first line"


def test_frames_pass_through_untouched():
    obs = _observer(
        transcript=[{"role": "character", "text": "x", "timestamp_ms": 0}],
        clock_values=[0.0, 5.0],
    )
    bsf = BotStoppedSpeakingFrame()
    usf = UserStartedSpeakingFrame()

    async def _drive():
        await obs.process_frame(bsf, FrameDirection.UPSTREAM)
        await obs.process_frame(usf, FrameDirection.DOWNSTREAM)

    _run(_drive())
    # observe-never-consume: every frame is forwarded.
    assert obs._pushed == [bsf, usf]  # type: ignore[attr-defined]


def test_captures_hesitation_through_a_real_pipeline_setup():
    """server/CLAUDE.md §1 regression net — drive the frames through a REAL
    PipelineTask so pipecat runs `setup()` on the observer. pipecat's base
    FrameProcessor.setup() overwrites `self._clock` with a non-callable
    BaseClock; if the observer stored its monotonic callable there (the
    original bug) the first BotStoppedSpeakingFrame read raises TypeError under
    setup() and NOTHING is captured — while every direct-process_frame unit test
    above stays green. This test fails loudly on that regression because it
    exercises the setup() path the unit tests never reach.
    """
    from pipecat.frames.frames import EndFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineTask

    # Inject a fake clock (0 on the BSF read, 5 on the user-start read → 5 s gap)
    # so the assertion is deterministic without a 3 s real sleep. The injected
    # clock is stored as `self._now`, which setup() must NOT clobber.
    values = [0.0, 5.0]
    state = {"i": 0}

    def _clk() -> float:
        v = values[min(state["i"], len(values) - 1)]
        state["i"] += 1
        return v

    obs = HesitationObserver(
        collector=_FakeCollector(
            [{"role": "character", "text": "Talk properly.", "timestamp_ms": 0}]
        ),
        clock=_clk,
    )
    task = PipelineTask(Pipeline([obs]))

    async def _drive() -> None:
        await task.queue_frames(
            [BotStoppedSpeakingFrame(), UserStartedSpeakingFrame(), EndFrame()]
        )
        await PipelineRunner().run(task)

    _run(_drive())

    assert obs.top_hesitations() == [
        {
            "id": "h1",
            "duration_sec": 5.0,
            "preceding_character_line": "Talk properly.",
            "resolved": True,
        }
    ], "hesitation not captured through a real pipeline — _clock clobber regression?"


def test_records_unresolved_gap_on_character_respeak():
    """Story 7.5 C2 — a freeze so long the character re-speaks before the user
    replies is captured at the re-speak's BotStartedSpeakingFrame, tagged
    resolved=False. In v1 this gap was OVERWRITTEN by the re-speak's
    BotStoppedSpeakingFrame and lost entirely."""
    obs = _observer(
        transcript=[{"role": "character", "text": "Answer me.", "timestamp_ms": 0}],
        clock_values=[
            0.0,
            6.0,
        ],  # BSF@0, character re-speaks (BotStarted)@6 → 6 s freeze
    )

    async def _drive():
        await obs.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await obs.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)

    _run(_drive())
    assert obs.top_hesitations() == [
        {
            "id": "h1",
            "duration_sec": 6.0,
            "preceding_character_line": "Answer me.",
            "resolved": False,
        }
    ]


def test_respeak_then_user_start_records_two_distinct_gaps():
    """The freeze (closed at re-speak, unresolved) and the post-re-speak gap
    (closed at the user start, resolved) are TWO separate measurements over
    disjoint intervals — never double-counted."""
    obs = _observer(
        transcript=[{"role": "character", "text": "Talk properly.", "timestamp_ms": 0}],
        # BSF@0 -> BotStarted@5 (freeze 5, unresolved) -> BSF@8 -> UserStart@12 (gap 4, resolved)
        clock_values=[0.0, 5.0, 8.0, 12.0],
    )

    async def _drive():
        await obs.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await obs.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        await obs.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await obs.process_frame(UserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)

    _run(_drive())
    assert obs.top_hesitations() == [
        {
            "id": "h1",
            "duration_sec": 5.0,
            "preceding_character_line": "Talk properly.",
            "resolved": False,
        },
        {
            "id": "h2",
            "duration_sec": 4.0,
            "preceding_character_line": "Talk properly.",
            "resolved": True,
        },
    ]


def test_respeak_below_threshold_ignored():
    """A short re-speak gap (the character barely pauses then continues) is NOT
    a hesitation — the same >3 s threshold applies on the re-speak path."""
    obs = _observer(
        transcript=[{"role": "character", "text": "x", "timestamp_ms": 0}],
        clock_values=[0.0, 2.0],  # 2 s < 3 s
    )

    async def _drive():
        await obs.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        await obs.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)

    _run(_drive())
    assert obs.top_hesitations() == []


def test_bot_start_without_pending_stop_is_ignored():
    """The very FIRST character turn fires BotStartedSpeakingFrame with no gap
    pending — it must be a no-op (not a spurious zero-gap)."""
    obs = _observer(transcript=[], clock_values=[1.0])

    async def _drive():
        await obs.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)

    _run(_drive())
    assert obs.top_hesitations() == []


def test_captures_respeak_freeze_through_a_real_pipeline_setup():
    """server/CLAUDE.md §1 net for the NEW BotStartedSpeakingFrame branch — drive
    it through a real PipelineTask so pipecat runs setup(); proves the re-speak
    capture fires on the setup() path the direct-call unit tests never reach."""
    from pipecat.frames.frames import EndFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.pipeline.task import PipelineTask

    values = [0.0, 6.0]
    state = {"i": 0}

    def _clk() -> float:
        v = values[min(state["i"], len(values) - 1)]
        state["i"] += 1
        return v

    obs = HesitationObserver(
        collector=_FakeCollector(
            [{"role": "character", "text": "Answer me.", "timestamp_ms": 0}]
        ),
        clock=_clk,
    )
    task = PipelineTask(Pipeline([obs]))

    async def _drive() -> None:
        await task.queue_frames(
            [BotStoppedSpeakingFrame(), BotStartedSpeakingFrame(), EndFrame()]
        )
        await PipelineRunner().run(task)

    _run(_drive())

    assert obs.top_hesitations() == [
        {
            "id": "h1",
            "duration_sec": 6.0,
            "preceding_character_line": "Answer me.",
            "resolved": False,
        }
    ], "re-speak freeze not captured through a real pipeline"
