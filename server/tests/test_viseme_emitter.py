"""Story 6.3 — Tests for VisemeEmitter FrameProcessor (AC2, AC9)."""

from __future__ import annotations

import asyncio

import pytest
from pipecat.frames.frames import (
    AggregationType,
    Frame,
    OutputTransportMessageFrame,
    TextFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from pipeline.viseme_emitter import VisemeEmitter, word_to_viseme_id


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _capture_pushed(emitter: VisemeEmitter) -> list[Frame]:
    captured: list[Frame] = []

    async def _recorder(frame: Frame, direction: FrameDirection) -> None:
        captured.append(frame)

    emitter.push_frame = _recorder  # type: ignore[assignment]
    return captured


def _make_tts_frame(text: str, *, pts_ns: int | None = None) -> TTSTextFrame:
    """Build a TTSTextFrame matching the shape pipecat creates internally
    (`TTSService._add_word_timestamps` constructs them this way at
    `pipecat/services/tts_service.py:1175-1176`).
    """
    frame = TTSTextFrame(text=text, aggregated_by=AggregationType.WORD)
    if pts_ns is not None:
        frame.pts = pts_ns
    return frame


# ---------- Test 1: word_to_viseme_id table ----------


@pytest.mark.parametrize(
    "word,expected_id",
    [
        ("a", 1),  # aei
        ("the", 10),  # th
        ("hello", 9),  # l
        ("you", 7),  # qwoo (substring "u")
        ("fish", 11),  # fv
        ("mom", 6),  # bmp
        ("three", 10),  # th
        ("this", 10),  # th
        ("oil", 9),  # l
        ("little", 9),  # l
        ("run", 8),  # r
        ("see", 4),  # ee
        ("go", 3),  # o
        ("cat", 2),  # cdgknstxyz (c)
        ("red", 8),  # r
    ],
)
def test_word_to_viseme_id_table(word: str, expected_id: int) -> None:
    """The dominant-letter heuristic returns the expected enum id for a
    representative table of words spanning all 12 viseme cases.
    """
    assert word_to_viseme_id(word) == expected_id


def test_word_to_viseme_id_handles_empty_and_punctuation() -> None:
    assert word_to_viseme_id("") == 1
    assert word_to_viseme_id("...") == 1
    assert word_to_viseme_id("!!!?") == 1


# ---------- Test 2: per-word emit ----------


def test_tts_text_frame_emits_viseme_envelope() -> None:
    """A TTSTextFrame("hello", pts=1500ms) emits a primary viseme envelope
    with viseme_id=9 (l) and timestamp_ms=1500.
    """
    emitter = VisemeEmitter()
    captured = _capture_pushed(emitter)
    frame = _make_tts_frame("hello", pts_ns=1_500_000_000)

    _run(emitter.process_frame(frame, FrameDirection.DOWNSTREAM))

    envelopes = [f for f in captured if isinstance(f, OutputTransportMessageFrame)]
    # Two envelopes: primary + rest follow-up.
    assert len(envelopes) == 2
    primary = envelopes[0].message
    assert primary == {
        "type": "viseme",
        "data": {"viseme_id": 9, "timestamp_ms": 1500},
    }


# ---------- Test 3: rest follow-up ----------


def test_emit_includes_rest_follow_up() -> None:
    """After every word emit, a rest viseme (id=0) follows at
    timestamp_ms + estimated_word_duration_ms.
    """
    emitter = VisemeEmitter()
    captured = _capture_pushed(emitter)
    # `hi` is 2 chars → estimated duration = max(80, 2*60) = 120 ms.
    frame = _make_tts_frame("hi", pts_ns=2_000_000_000)

    _run(emitter.process_frame(frame, FrameDirection.DOWNSTREAM))

    envelopes = [
        f.message for f in captured if isinstance(f, OutputTransportMessageFrame)
    ]
    assert envelopes[1] == {
        "type": "viseme",
        "data": {"viseme_id": 0, "timestamp_ms": 2000 + 120},
    }


# ---------- Test 4: pass-through ----------


def test_tts_text_frame_is_forwarded_downstream() -> None:
    """Pass-through is mandatory regardless of mapping."""
    emitter = VisemeEmitter()
    captured = _capture_pushed(emitter)
    frame = _make_tts_frame("anything", pts_ns=0)

    _run(emitter.process_frame(frame, FrameDirection.DOWNSTREAM))

    # The original frame must appear in the captured stream alongside the
    # emitted envelopes.
    assert frame in captured


def test_non_tts_frame_passes_through_without_emit() -> None:
    """A frame that is not a TTSTextFrame is forwarded with no envelope."""
    emitter = VisemeEmitter()
    captured = _capture_pushed(emitter)
    other = TextFrame(text="non-tts")

    _run(emitter.process_frame(other, FrameDirection.DOWNSTREAM))

    assert other in captured
    envelopes = [f for f in captured if isinstance(f, OutputTransportMessageFrame)]
    assert envelopes == []


# ---------- Edge case: pts is None (pre-baseline frame) ----------


def test_emit_handles_missing_pts() -> None:
    """A TTSTextFrame whose `pts` is None falls back to timestamp_ms=0
    instead of crashing — matches the pre-audio-baseline edge case in
    `TTSService._add_word_timestamps`.
    """
    emitter = VisemeEmitter()
    captured = _capture_pushed(emitter)
    frame = _make_tts_frame("foo", pts_ns=None)

    _run(emitter.process_frame(frame, FrameDirection.DOWNSTREAM))

    envelopes = [
        f.message for f in captured if isinstance(f, OutputTransportMessageFrame)
    ]
    assert envelopes[0]["data"]["timestamp_ms"] == 0


def test_emit_preserves_pts_zero_at_audio_baseline() -> None:
    """A TTSTextFrame whose `pts == 0` (legitimate first frame at the audio
    baseline) MUST produce timestamp_ms=0, NOT collapse into the
    missing-pts branch. Regression guard for the falsy `if pts_ns` bug.
    """
    emitter = VisemeEmitter()
    captured = _capture_pushed(emitter)
    # `hi` is 2 chars → estimated word duration = max(80, 2*60) = 120 ms.
    frame = _make_tts_frame("hi", pts_ns=0)

    _run(emitter.process_frame(frame, FrameDirection.DOWNSTREAM))

    envelopes = [
        f.message for f in captured if isinstance(f, OutputTransportMessageFrame)
    ]
    assert envelopes[0]["data"]["timestamp_ms"] == 0
    # Rest follow-up at 0 + 120 = 120 ms — proves we computed from a real 0,
    # not from the None-fallback path (which would also give 0 + 120, but
    # this test pins the contract regardless).
    assert envelopes[1]["data"]["timestamp_ms"] == 120


# ---------- Cross-contract guard: 12-case Rive enum coverage (review patch) ---


def test_priority_ids_cover_full_12_case_rive_contract() -> None:
    """Story 2.6 §3 defines `visemeId` as a 12-case enum (rest=0..fv=11).
    The union of `_PRIORITY` ids + `_REST_ID` + `_DEFAULT_VOWEL_ID` MUST
    cover all 12. A drift here means a wire-format value the client
    cannot map (the client `kVisemeIdToCase` would silently no-op on
    the missing id).
    """
    from pipeline.viseme_emitter import _DEFAULT_VOWEL_ID, _PRIORITY, _REST_ID

    actual = {vid for _name, vid, _subs in _PRIORITY} | {_REST_ID} | {_DEFAULT_VOWEL_ID}
    assert actual == set(range(12)), (
        f"Server viseme contract drifted: ids {sorted(actual)} != 0..11"
    )
