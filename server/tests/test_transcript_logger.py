"""Tests for TranscriptLogger FrameProcessor and TranscriptCollector."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from pipecat.frames.frames import EndFrame, StartFrame, TextFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection

from pipeline.transcript_logger import TranscriptCollector, TranscriptLogger


@pytest.fixture
def collector(tmp_path):
    """Create a TranscriptCollector that writes to tmp_path."""
    return TranscriptCollector(session_id="test_session", output_dir=str(tmp_path))


@pytest.fixture
def user_logger(collector):
    """Create a TranscriptLogger for user speech."""
    return TranscriptLogger(collector=collector, role="user")


@pytest.fixture
def character_logger(collector):
    """Create a TranscriptLogger for character speech."""
    return TranscriptLogger(collector=collector, role="character")


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestTranscriptCollector:
    def test_add_turn_records_entry(self, collector):
        collector.add_turn("user", "Hello there", 1000)
        assert len(collector.transcript) == 1
        assert collector.transcript[0] == {
            "role": "user",
            "text": "Hello there",
            "timestamp_ms": 1000,
        }

    def test_add_multiple_turns_preserves_order(self, collector):
        collector.add_turn("character", "Welcome!", 0)
        collector.add_turn("user", "Hi", 3200)
        collector.add_turn("character", "What do you want?", 5100)
        assert len(collector.transcript) == 3
        assert collector.transcript[0]["role"] == "character"
        assert collector.transcript[1]["role"] == "user"
        assert collector.transcript[2]["role"] == "character"

    def test_write_transcript_creates_json_file(self, collector, tmp_path):
        collector.add_turn("character", "Hello", 0)
        collector.add_turn("user", "Hi", 1000)
        collector.write_transcript()
        output_file = tmp_path / "transcript_test_session.json"
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["session_id"] == "test_session"
        assert len(data["transcript"]) == 2
        assert "started_at" in data
        assert "ended_at" in data
        assert "duration_seconds" in data

    def test_write_transcript_prevents_double_write(self, collector, tmp_path):
        collector.add_turn("character", "Hello", 0)
        collector.write_transcript()
        collector.add_turn("user", "Extra turn after write", 5000)
        collector.write_transcript()
        output_file = tmp_path / "transcript_test_session.json"
        data = json.loads(output_file.read_text())
        assert len(data["transcript"]) == 1

    def test_write_transcript_default_output_dir(self):
        collector = TranscriptCollector(session_id="default_test")
        collector.add_turn("user", "test", 0)
        with patch("pathlib.Path.write_text") as mock_write:
            collector.write_transcript()
            call_args = mock_write.call_args
            assert call_args is not None

    def test_transcript_json_schema(self, collector, tmp_path):
        collector.add_turn("character", "Welcome", 0)
        collector.add_turn("user", "Hello", 2000)
        collector.write_transcript()
        output_file = tmp_path / "transcript_test_session.json"
        data = json.loads(output_file.read_text())
        required_keys = {
            "session_id",
            "started_at",
            "ended_at",
            "duration_seconds",
            "transcript",
        }
        assert required_keys == set(data.keys())
        for turn in data["transcript"]:
            assert set(turn.keys()) == {"role", "text", "timestamp_ms"}


class TestTranscriptLogger:
    def test_user_logger_captures_transcription_frame(self, user_logger, collector):
        frame = TranscriptionFrame(
            text="Hello there", user_id="u1", timestamp="t1", finalized=True
        )
        user_logger.push_frame = AsyncMock()
        _run(user_logger.process_frame(frame, FrameDirection.DOWNSTREAM))
        assert len(collector.transcript) == 1
        assert collector.transcript[0]["role"] == "user"
        assert collector.transcript[0]["text"] == "Hello there"

    def test_user_logger_ignores_text_frame(self, user_logger, collector):
        frame = TextFrame(text="Character says something")
        user_logger.push_frame = AsyncMock()
        _run(user_logger.process_frame(frame, FrameDirection.DOWNSTREAM))
        assert len(collector.transcript) == 0

    def test_character_logger_captures_text_frame(self, character_logger, collector):
        frame = TextFrame(text="What do you want?")
        character_logger.push_frame = AsyncMock()
        _run(character_logger.process_frame(frame, FrameDirection.DOWNSTREAM))
        assert len(collector.transcript) == 1
        assert collector.transcript[0]["role"] == "character"
        assert collector.transcript[0]["text"] == "What do you want?"

    def test_character_logger_ignores_transcription_frame(
        self, character_logger, collector
    ):
        frame = TranscriptionFrame(
            text="User speech", user_id="u1", timestamp="t1", finalized=True
        )
        character_logger.push_frame = AsyncMock()
        _run(character_logger.process_frame(frame, FrameDirection.DOWNSTREAM))
        assert len(collector.transcript) == 0

    def test_passthrough_behavior_transcription(self, user_logger):
        frame = TranscriptionFrame(
            text="test", user_id="u1", timestamp="t1", finalized=True
        )
        user_logger.push_frame = AsyncMock()
        _run(user_logger.process_frame(frame, FrameDirection.DOWNSTREAM))
        user_logger.push_frame.assert_called_once_with(frame, FrameDirection.DOWNSTREAM)

    def test_passthrough_behavior_text(self, character_logger):
        frame = TextFrame(text="test")
        character_logger.push_frame = AsyncMock()
        _run(character_logger.process_frame(frame, FrameDirection.DOWNSTREAM))
        character_logger.push_frame.assert_called_once_with(
            frame, FrameDirection.DOWNSTREAM
        )

    def test_passthrough_unrelated_frame(self, user_logger, collector):
        frame = EndFrame()
        user_logger.push_frame = AsyncMock()
        _run(user_logger.process_frame(frame, FrameDirection.DOWNSTREAM))
        user_logger.push_frame.assert_called_once_with(frame, FrameDirection.DOWNSTREAM)
        assert len(collector.transcript) == 0

    def test_end_frame_triggers_write(self, user_logger, collector, tmp_path):
        collector.add_turn("character", "Hello", 0)
        user_logger.push_frame = AsyncMock()
        _run(user_logger.process_frame(EndFrame(), FrameDirection.DOWNSTREAM))
        output_file = tmp_path / "transcript_test_session.json"
        assert output_file.exists()

    def test_duplicate_end_frame_no_double_write(
        self, user_logger, character_logger, collector, tmp_path
    ):
        collector.add_turn("user", "Hello", 0)
        user_logger.push_frame = AsyncMock()
        character_logger.push_frame = AsyncMock()
        _run(user_logger.process_frame(EndFrame(), FrameDirection.DOWNSTREAM))
        collector.add_turn("user", "Extra", 5000)
        _run(character_logger.process_frame(EndFrame(), FrameDirection.DOWNSTREAM))
        output_file = tmp_path / "transcript_test_session.json"
        data = json.loads(output_file.read_text())
        assert len(data["transcript"]) == 1

    def test_timestamp_relative_to_first_frame(self, user_logger, collector):
        user_logger.push_frame = AsyncMock()
        frame1 = TranscriptionFrame(
            text="First", user_id="u1", timestamp="t1", finalized=True
        )
        frame2 = TranscriptionFrame(
            text="Second", user_id="u1", timestamp="t2", finalized=True
        )
        _run(user_logger.process_frame(frame1, FrameDirection.DOWNSTREAM))
        _run(user_logger.process_frame(frame2, FrameDirection.DOWNSTREAM))
        assert collector.transcript[0]["timestamp_ms"] == 0
        assert collector.transcript[1]["timestamp_ms"] >= 0

    def test_user_logger_skips_non_finalized_transcription(
        self, user_logger, collector
    ):
        frame = TranscriptionFrame(
            text="partial", user_id="u1", timestamp="t1", finalized=False
        )
        user_logger.push_frame = AsyncMock()
        _run(user_logger.process_frame(frame, FrameDirection.DOWNSTREAM))
        assert len(collector.transcript) == 0

    def test_process_frame_delegates_to_base_class(self, user_logger):
        """Regression guard for the super().process_frame() call.

        The base FrameProcessor.process_frame drives lifecycle state
        (StartFrame, InterruptionFrame, CancelFrame, etc.). If the
        override in TranscriptLogger stops calling super().process_frame,
        downstream processors that depend on that state will silently
        break. This test verifies that every call to process_frame
        delegates to the parent class exactly once.
        """
        frame = StartFrame()
        user_logger.push_frame = AsyncMock()
        with patch(
            "pipecat.processors.frame_processor.FrameProcessor.process_frame",
            new_callable=AsyncMock,
        ) as mock_super:
            _run(user_logger.process_frame(frame, FrameDirection.DOWNSTREAM))
            mock_super.assert_awaited_once_with(frame, FrameDirection.DOWNSTREAM)
        user_logger.push_frame.assert_called_once_with(frame, FrameDirection.DOWNSTREAM)
