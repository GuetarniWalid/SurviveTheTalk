"""Story 6.11 fix (2026-05-30) — InputGate: "stop listening" on noise exit.

The problem (smoke call_id=205): when a LOUD, CONTINUOUS parasitic voice is
present, it keeps tripping the VAD → `UserStartedSpeakingFrame` →
interruptions every 1-2 s. Each interruption flushes the TTS queue, so the
noisy-environment exit line ("I can't hear you — there's another voice…")
is cut after ~4 ms and never heard. You cannot speak a calm goodbye OVER a
continuous interrupter.

Walid's fix (2026-05-30): once we've DETECTED the noise, we don't need to
listen anymore — so MUTE the input. With nothing coming in, the bot can't
be interrupted and gets to finish its line before the call ends.

This processor sits immediately AFTER `transport.input()` (before STT). When
`arm()` is called it DROPS the user-speech / VAD / interruption / raw-audio
frames flowing downstream — the exact set pipecat's own (now-deprecated)
`STTMuteFilter` suppresses while muted (see
`pipecat/processors/filters/stt_mute_filter.py` lines ~219-236). With the
mic audio dropped at the top of the pipeline:
  - the VAD (in the user aggregator) never sees audio → no
    `UserStartedSpeakingFrame` → no interruption → the exit line plays
    uninterrupted;
  - STT gets no audio → no new `TranscriptionFrame` → the character LLM +
    checkpoint classifier stop reacting to the parasite.

Everything else passes through untouched (StartFrame/EndFrame/CancelFrame,
TTS frames, OutputTransportMessageFrame data envelopes, etc.) so the hang-up
sequence + `call_end` envelope + clean teardown are unaffected. The
client→server data channel (`playback_idle`) rides `on_data_received`, NOT
the audio path, so muting the mic does not break the hang-up's
client-drain wait.

One-way + idempotent: `arm()` is terminal for the call (we only mute when
the call is ending), so there is no `disarm()`.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# The frame types that carry user speech / VAD / interruption / raw mic
# audio. Mirrors the suppression set of pipecat's STTMuteFilter — these are
# exactly the frames that, when dropped, stop the bot from being
# interrupted and stop new user turns from being processed.
_MUTED_FRAME_TYPES = (
    InputAudioRawFrame,
    InterruptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)


class InputGate(FrameProcessor):
    """Pass-through until `arm()`; then drops user-speech/VAD/interruption/
    raw-audio frames so the bot can speak its final line uninterrupted.

    Wire IMMEDIATELY after `transport.input()` (before STT) so dropping the
    mic audio starves both the VAD (interruptions) and the STT (new turns)
    at the source.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._armed = False

    def arm(self) -> None:
        """Stop listening: from now on, mic audio + user-speech +
        interruption frames are dropped. Idempotent + terminal for the call."""
        if not self._armed:
            logger.info(
                "InputGate ARMED — muting mic input so the final line "
                "cannot be interrupted (noisy-environment exit)"
            )
        self._armed = True

    @property
    def is_armed(self) -> bool:
        return self._armed

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if self._armed and isinstance(frame, _MUTED_FRAME_TYPES):
            # Dropped: do NOT push downstream. This is the "stop listening"
            # behaviour — no audio reaches the VAD/STT, so no interruption
            # fires and no new user turn is produced.
            return

        await self.push_frame(frame, direction)
