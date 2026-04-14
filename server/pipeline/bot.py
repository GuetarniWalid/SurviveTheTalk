"""Pipecat voice pipeline: Soniox v4 STT -> OpenRouter/Qwen3.5 Flash LLM -> Cartesia Sonic 3 TTS."""

import argparse
import asyncio
import time

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import EndFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.openrouter.llm import OpenRouterLLMService
from pipecat.services.soniox.stt import SonioxSTTService
from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from config import Settings
from pipeline.prompts import CARTESIA_VOICE_ID, SARCASTIC_CHARACTER_PROMPT
from pipeline.transcript_logger import TranscriptCollector, TranscriptLogger


async def run_bot(url: str, room: str, token: str) -> None:
    """Configure and run the Pipecat voice pipeline in a LiveKit room."""
    settings = Settings()

    transport = LiveKitTransport(
        url=url,
        token=token,
        room_name=room,
        params=LiveKitParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
    )

    stt = SonioxSTTService(
        api_key=settings.soniox_api_key,
        settings=SonioxSTTService.Settings(model="stt-rt-v4"),
    )

    llm = OpenRouterLLMService(
        api_key=settings.openrouter_api_key,
        settings=OpenRouterLLMService.Settings(
            model="qwen/qwen3.5-flash-02-23",
            extra={"extra_body": {"reasoning": {"enabled": False}}},
            system_instruction=SARCASTIC_CHARACTER_PROMPT,
            temperature=0.7,
            max_tokens=256,
        ),
    )

    tts = CartesiaTTSService(
        api_key=settings.cartesia_api_key,
        settings=CartesiaTTSService.Settings(
            model="sonic-3",
            voice=CARTESIA_VOICE_ID,
        ),
    )

    vad_analyzer = SileroVADAnalyzer(
        params=VADParams(
            confidence=0.7,
            start_secs=0.2,
            stop_secs=0.3,
            min_volume=0.5,
        )
    )

    context = LLMContext()
    context_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=vad_analyzer,
            user_turn_strategies=UserTurnStrategies(
                start=[
                    MinWordsUserTurnStartStrategy(
                        min_words=3,
                        enable_interruptions=True,
                    ),
                ],
                stop=[
                    SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6),
                ],
            ),
        ),
    )

    collector = TranscriptCollector(session_id=f"call_{int(time.time())}")
    transcript_user = TranscriptLogger(collector=collector, role="user")
    transcript_character = TranscriptLogger(collector=collector, role="character")

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            transcript_user,
            context_aggregator.user(),
            llm,
            transcript_character,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
        ),
    )

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(
        transport: LiveKitTransport, participant_id: str
    ) -> None:
        logger.info(f"First participant joined: {participant_id}")
        await task.queue_frames(
            [TTSSpeakFrame("Oh great, another one. Let's get this over with.")]
        )

    @transport.event_handler("on_participant_left")
    async def on_participant_left(
        transport: LiveKitTransport, participant_id: str, reason: str = ""
    ) -> None:
        logger.info(f"Participant left: {participant_id} (reason: {reason})")
        await task.queue_frames([EndFrame()])

    runner = PipelineRunner()
    await runner.run(task)


def main() -> None:
    """Parse CLI args and launch the pipeline."""
    parser = argparse.ArgumentParser(description="Pipecat voice bot")
    parser.add_argument("--url", required=True, help="LiveKit server URL")
    parser.add_argument("--room", required=True, help="LiveKit room name")
    parser.add_argument("--token", required=True, help="LiveKit agent token")
    args = parser.parse_args()

    asyncio.run(run_bot(url=args.url, room=args.room, token=args.token))


if __name__ == "__main__":
    main()
