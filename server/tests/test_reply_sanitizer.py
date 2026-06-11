"""Story 6.29 — ReplySanitizer unit tests (AC2 + AC8).

Direct `process_frame` drives for the per-frame state machine; the
real-pipeline integration drive (PipelineTask + runner, per server/CLAUDE.md
§1) lives in `test_bot_pipeline_wiring.py::
test_reply_sanitizer_cleans_stream_and_emits_mood_via_real_pipeline_drive`.
"""

from __future__ import annotations

import asyncio

import pytest
from loguru import logger as loguru_logger
from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    OutputTransportMessageFrame,
    TextFrame,
    TTSSpeakFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from pipeline.reply_sanitizer import ReplySanitizer, sanitize_reply_text

# ---------- helpers --------------------------------------------------------


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _capture_pushed(sanitizer: ReplySanitizer) -> list[Frame]:
    captured: list[Frame] = []

    async def _recorder(frame: Frame, direction: FrameDirection) -> None:
        captured.append(frame)

    sanitizer.push_frame = _recorder  # type: ignore[assignment]
    return captured


async def _drive_reply(
    sanitizer: ReplySanitizer, chunks: list[str], *, end: bool = True
) -> None:
    await sanitizer.process_frame(
        LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM
    )
    for chunk in chunks:
        await sanitizer.process_frame(
            LLMTextFrame(text=chunk), FrameDirection.DOWNSTREAM
        )
    if end:
        await sanitizer.process_frame(
            LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM
        )


def _spoken_text(captured: list[Frame]) -> str:
    return "".join(
        f.text
        for f in captured
        if isinstance(f, TextFrame) and not isinstance(f, TTSSpeakFrame)
    )


def _emotion_envelopes(captured: list[Frame]) -> list[dict]:
    return [
        f.message
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "emotion"
    ]


# ---------- span stripping (AC2) -------------------------------------------


def test_parenthetical_span_stripped_within_one_frame() -> None:
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Grilled chicken (writes it down) coming up."]))
    spoken = _spoken_text(captured)
    assert "(" not in spoken and ")" not in spoken
    assert "writes it down" not in spoken
    assert "Grilled chicken" in spoken and "coming up." in spoken


def test_paren_span_split_across_frames_and_nested() -> None:
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(
        _drive_reply(
            sanitizer,
            ["Sure (noting", " the (full) order", ") thing.", ""],
        )
    )
    spoken = _spoken_text(captured)
    assert "noting" not in spoken and "full" not in spoken
    assert spoken == "Sure  thing."


def test_asterisk_action_stripped_but_literal_asterisk_kept() -> None:
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Two times three is 2 * 3. *sighs* Anyway."]))
    spoken = _spoken_text(captured)
    assert "sighs" not in spoken
    assert "2 * 3." in spoken  # literal math asterisk survives
    assert "Anyway." in spoken


def test_pure_meta_reply_dropped_whole_and_logged() -> None:
    """The exact call-274 P2 case: a reply that is ONLY a parenthetical must
    produce ZERO downstream text (silent turn) + the INFO log line."""
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)

    logs: list[str] = []
    sink_id = loguru_logger.add(logs.append, level="INFO")
    try:
        _run(
            _drive_reply(
                sanitizer,
                ["(Actually, I still need to confirm - you said grilled chicken.)"],
            )
        )
    finally:
        loguru_logger.remove(sink_id)

    assert _spoken_text(captured) == ""
    assert any("reply_sanitizer_empty_reply_dropped" in e for e in logs)


def test_unterminated_paren_span_dropped_at_end_of_reply() -> None:
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Okay. (and this never closes"]))
    spoken = _spoken_text(captured)
    assert spoken == "Okay. "
    assert "never closes" not in spoken


def test_text_outside_llm_response_brackets_passes_untouched() -> None:
    """AC2 — only TextFrames WITHIN Start/End brackets are transformed."""
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)

    async def _drive() -> None:
        await sanitizer.process_frame(
            LLMTextFrame(text="(stray) *outside* <mood:anger>"),
            FrameDirection.DOWNSTREAM,
        )

    _run(_drive())
    assert _spoken_text(captured) == "(stray) *outside* <mood:anger>"
    assert _emotion_envelopes(captured) == []


def test_tts_speak_frame_exit_line_passes_untouched() -> None:
    """PatienceTracker-owned exit lines (TTSSpeakFrame) keep their asterisk
    actions — pre-existing behavior, out of scope (story What-NOT-to-do)."""
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)

    async def _drive() -> None:
        await sanitizer.process_frame(
            LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM
        )
        await sanitizer.process_frame(
            TTSSpeakFrame(text="*heavy sigh* I'm done."), FrameDirection.DOWNSTREAM
        )
        await sanitizer.process_frame(
            LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM
        )

    _run(_drive())
    tts = [f for f in captured if isinstance(f, TTSSpeakFrame)]
    assert len(tts) == 1
    assert tts[0].text == "*heavy sigh* I'm done."


# ---------- mood tag (AC8) --------------------------------------------------


def test_valid_trailing_tag_emits_envelope_and_never_reaches_text() -> None:
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Took you long enough. <mood:frustration>"]))
    spoken = _spoken_text(captured)
    assert "mood" not in spoken and "<" not in spoken
    envelopes = _emotion_envelopes(captured)
    assert len(envelopes) == 1
    assert envelopes[0]["data"] == {"emotion": "frustration", "intensity": 0.5}


def test_tag_split_across_two_frames_still_extracted() -> None:
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Fine. <mood:sa", "tisfaction>"]))
    assert _spoken_text(captured) == "Fine. "
    envelopes = _emotion_envelopes(captured)
    assert len(envelopes) == 1
    assert envelopes[0]["data"]["emotion"] == "satisfaction"


def test_absent_tag_emits_no_envelope() -> None:
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Just a normal reply."]))
    assert _emotion_envelopes(captured) == []


def test_invalid_tag_value_rejected_no_envelope() -> None:
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Hmm. <mood:euphoric>"]))
    assert _emotion_envelopes(captured) == []
    # The invalid tag is still stripped from the spoken text.
    assert _spoken_text(captured) == "Hmm. "


def test_truncated_tag_at_end_of_reply_dropped_silently() -> None:
    """A max_tokens cut mid-tag must not speak the fragment."""
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["See you then. <mood:frustr"]))
    assert _spoken_text(captured) == "See you then. "
    assert _emotion_envelopes(captured) == []


def test_non_tag_angle_bracket_is_spoken() -> None:
    """A '<' that provably isn't a mood tag is released as literal text."""
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Prices are <10 dollars here."]))
    assert _spoken_text(captured) == "Prices are <10 dollars here."


def test_last_tag_wins_when_model_emits_two() -> None:
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["<mood:anger> Whatever. <mood:smirk>"]))
    envelopes = _emotion_envelopes(captured)
    assert len(envelopes) == 1
    assert envelopes[0]["data"]["emotion"] == "smirk"


def test_case_variant_tag_stripped_and_envelope_emitted() -> None:
    """Review 6.29 — a case-deviant tag ("<Mood:Anger>") must NEVER be spoken:
    match leniently, validate the lowercased value strictly."""
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Took you long enough. <Mood:Anger>"]))
    spoken = _spoken_text(captured)
    assert "<" not in spoken and "Mood" not in spoken
    envelopes = _emotion_envelopes(captured)
    assert len(envelopes) == 1
    assert envelopes[0]["data"]["emotion"] == "anger"


def test_case_variant_tag_split_across_frames_still_held_and_extracted() -> None:
    """The split-tag hold must use the same case-leniency as the whole-tag
    match, or a case-deviant split tag is released mid-hold and spoken."""
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Fine. <MO", "OD:Smirk>"]))
    assert _spoken_text(captured) == "Fine. "
    envelopes = _emotion_envelopes(captured)
    assert len(envelopes) == 1
    assert envelopes[0]["data"]["emotion"] == "smirk"


def test_case_variant_invalid_value_still_rejected_and_stripped() -> None:
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Hmm. <MOOD:ZEN>"]))
    assert _emotion_envelopes(captured) == []
    assert _spoken_text(captured) == "Hmm. "


def test_envelope_shape_is_emotion_emitter_compatible() -> None:
    """AC3/AC8 — byte-compatible wire shape with the retired EmotionEmitter:
    `{"type":"emotion","data":{"emotion":<str>,"intensity":<float>}}` on a
    queued OutputTransportMessageFrame."""
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Okay. <mood:confusion>"]))
    frames = [
        f
        for f in captured
        if isinstance(f, OutputTransportMessageFrame)
        and f.message.get("type") == "emotion"
    ]
    assert len(frames) == 1
    message = frames[0].message
    assert set(message.keys()) == {"type", "data"}
    assert set(message["data"].keys()) == {"emotion", "intensity"}
    assert isinstance(message["data"]["emotion"], str)
    assert isinstance(message["data"]["intensity"], float)


# ---------- interruption / barge-in -----------------------------------------


def test_barge_in_mid_reply_clears_buffer_and_pending_mood() -> None:
    """An InterruptionFrame mid-reply discards held text AND the pending
    mood — no envelope from a half-reply, no stale tail leaking into the
    next reply."""
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)

    async def _drive() -> None:
        await sanitizer.process_frame(
            LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM
        )
        await sanitizer.process_frame(
            LLMTextFrame(text="Look, I was going to say <mood:ang"),
            FrameDirection.DOWNSTREAM,
        )
        await sanitizer.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
        # Next reply starts clean.
        await _drive_reply(sanitizer, ["Fresh reply. <mood:smirk>"])

    _run(_drive())
    # Only the SECOND reply's tag emits — the interrupted reply's pending
    # mood/held tail were discarded.
    envelopes = _emotion_envelopes(captured)
    assert len(envelopes) == 1
    assert envelopes[0]["data"]["emotion"] == "smirk"
    spoken = _spoken_text(captured)
    assert "<" not in spoken, f"held tag fragment leaked: {spoken!r}"
    assert "Look, I was going to say " in spoken
    assert "Fresh reply. " in spoken


def test_straggler_end_frame_after_interruption_no_spurious_drop_log() -> None:
    """Review 6.29 — a straggling LLMFullResponseEndFrame AFTER an
    InterruptionFrame already reset the state (and a bare End with no Start)
    must not flush: it would log a spurious `reply_sanitizer_empty_reply_
    dropped` on every barge-in, polluting the smoke-gate journalctl grep."""
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)

    logs: list[str] = []
    sink_id = loguru_logger.add(logs.append, level="INFO")
    try:

        async def _drive() -> None:
            # Barge-in mid-reply, then the straggling End arrives.
            await sanitizer.process_frame(
                LLMFullResponseStartFrame(), FrameDirection.DOWNSTREAM
            )
            await sanitizer.process_frame(
                LLMTextFrame(text="I was saying <mood:ang"),
                FrameDirection.DOWNSTREAM,
            )
            await sanitizer.process_frame(
                InterruptionFrame(), FrameDirection.DOWNSTREAM
            )
            await sanitizer.process_frame(
                LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM
            )
            # Bare End with no Start at all (processor added mid-call).
            await sanitizer.process_frame(
                LLMFullResponseEndFrame(), FrameDirection.DOWNSTREAM
            )

        _run(_drive())
    finally:
        loguru_logger.remove(sink_id)

    assert not any("reply_sanitizer_empty_reply_dropped" in e for e in logs)
    assert _emotion_envelopes(captured) == []
    # The straggling End frames still pass through downstream.
    assert sum(isinstance(f, LLMFullResponseEndFrame) for f in captured) == 2


def test_interruption_frame_passes_through() -> None:
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)

    async def _drive() -> None:
        await sanitizer.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)

    _run(_drive())
    assert any(isinstance(f, InterruptionFrame) for f in captured)


# ---------- frame-type preservation -----------------------------------------


def test_mutated_frames_keep_their_concrete_type() -> None:
    """The sanitizer mutates frame.text in place — a re-built plain TextFrame
    would lose LLMTextFrame's `includes_inter_frame_spaces=True` and make the
    TTS re-space LLM chunks ("chick"+"en" → "chick en")."""
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Grilled (ok) chicken."]))
    text_frames = [
        f
        for f in captured
        if isinstance(f, TextFrame) and not isinstance(f, TTSSpeakFrame)
    ]
    assert text_frames, "expected the cleaned text frame downstream"
    assert all(isinstance(f, LLMTextFrame) for f in text_frames)
    assert all(f.includes_inter_frame_spaces for f in text_frames)


def test_fully_suppressed_chunk_emits_no_empty_frame() -> None:
    sanitizer = ReplySanitizer()
    captured = _capture_pushed(sanitizer)
    _run(_drive_reply(sanitizer, ["Before ", "(entirely inside a span)", " after."]))
    text_frames = [
        f
        for f in captured
        if isinstance(f, TextFrame) and not isinstance(f, TTSSpeakFrame)
    ]
    assert all(f.text for f in text_frames), "no empty TextFrame may be pushed"
    assert _spoken_text(captured) == "Before  after."


# ---------- pure helper (calibration harness parity) ------------------------


@pytest.mark.parametrize(
    ("raw", "expected_text", "expected_mood"),
    [
        ("Plain reply.", "Plain reply.", None),
        ("Reply with tag. <mood:anger>", "Reply with tag.", "anger"),
        ("(pure meta) <mood:smirk>", "", "smirk"),
        ("Keep 2 * 3 math. *wink*", "Keep 2 * 3 math.", None),
        ("Bad tag. <mood:zen>", "Bad tag.", None),
    ],
)
def test_sanitize_reply_text_pure_helper(
    raw: str, expected_text: str, expected_mood: str | None
) -> None:
    """`sanitize_reply_text` is the calibration harness's strip step — it
    must share the streaming scanner's exact behavior (golden==prod)."""
    clean, mood = sanitize_reply_text(raw)
    assert clean == expected_text
    assert mood == expected_mood
