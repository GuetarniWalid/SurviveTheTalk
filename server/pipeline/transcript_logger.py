"""Transcript capture for voice pipeline calls.

TranscriptCollector stores turns from both user and character in a shared list.
TranscriptLogger is a passthrough FrameProcessor that observes speech frames
and records them via a shared TranscriptCollector instance.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from pipecat.frames.frames import EndFrame, Frame, TextFrame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


@dataclass
class TranscriptCollector:
    """Shared state for collecting transcript turns from multiple loggers."""

    session_id: str
    output_dir: str = "/tmp"
    transcript: list[dict] = field(default_factory=list)
    _written: bool = field(default=False, repr=False)
    _started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc), repr=False
    )
    _first_timestamp: float | None = field(default=None, repr=False)

    def add_turn(self, role: str, text: str, timestamp_ms: int) -> None:
        """Record a conversational turn."""
        self.transcript.append(
            {"role": role, "text": text, "timestamp_ms": timestamp_ms}
        )

    def get_relative_timestamp_ms(self) -> int:
        """Return milliseconds elapsed since the first frame, or 0 for the first."""
        now = time.time()
        if self._first_timestamp is None:
            self._first_timestamp = now
            return 0
        return int((now - self._first_timestamp) * 1000)

    def write_transcript(self) -> None:
        """Write transcript JSON to disk. Only writes once (prevents double-write)."""
        if self._written:
            return

        ended_at = datetime.now(timezone.utc)
        duration = (ended_at - self._started_at).total_seconds()

        data = {
            "session_id": self.session_id,
            "started_at": self._started_at.isoformat().replace("+00:00", "Z"),
            "ended_at": ended_at.isoformat().replace("+00:00", "Z"),
            "duration_seconds": int(duration),
            "transcript": self.transcript,
        }

        output_path = Path(self.output_dir) / f"transcript_{self.session_id}.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        self._written = True
        logger.info(f"Transcript written to {output_path}")


class TranscriptLogger(FrameProcessor):
    """Passthrough FrameProcessor that observes speech frames for transcript capture.

    Args:
        collector: Shared TranscriptCollector instance.
        role: Either "user" (captures TranscriptionFrame) or "character" (captures TextFrame).
    """

    def __init__(self, collector: TranscriptCollector, role: str) -> None:
        super().__init__()
        self._collector = collector
        self._role = role

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        """Observe relevant frames, record turns, then pass frame through."""
        if isinstance(frame, EndFrame):
            self._collector.write_transcript()
        elif self._role == "user" and isinstance(frame, TranscriptionFrame):
            if frame.finalized:
                ts = self._collector.get_relative_timestamp_ms()
                self._collector.add_turn("user", frame.text, ts)
        elif (
            self._role == "character"
            and isinstance(frame, TextFrame)
            and not isinstance(frame, TranscriptionFrame)
        ):
            ts = self._collector.get_relative_timestamp_ms()
            self._collector.add_turn("character", frame.text, ts)

        await self.push_frame(frame, direction)
