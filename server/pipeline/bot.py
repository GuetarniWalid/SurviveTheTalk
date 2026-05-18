"""Pipecat voice pipeline: Soniox v4 STT -> OpenRouter/Qwen3.5 Flash LLM -> Cartesia Sonic 3 TTS."""

import argparse
import asyncio
import json
import os
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
from pipeline.checkpoint_manager import CheckpointManager
from pipeline.emotion_emitter import EmotionEmitter
from pipeline.exchange_classifier import ExchangeClassifier
from pipeline.patience_tracker import PatienceTracker
from pipeline.prompts import CARTESIA_VOICE_ID, SARCASTIC_CHARACTER_PROMPT
from pipeline.scenarios import (
    TUTORIAL_SCENARIO_ID,
    load_scenario_base_prompt,
    load_scenario_checkpoints,
    load_scenario_metadata,
    resolve_patience_config,
)
from pipeline.transcript_logger import TranscriptCollector, TranscriptLogger


async def run_bot(url: str, room: str, token: str) -> None:
    """Configure and run the Pipecat voice pipeline in a LiveKit room.

    The system prompt is taken from the `SYSTEM_PROMPT` env var when set
    (populated by `/calls/initiate` with the scenario-specific prompt);
    otherwise it falls back to the hardcoded waiter prompt used by the
    legacy `/connect` endpoint. Env var is used instead of a CLI flag to
    sidestep platform-specific argv length limits on long prompts.
    """
    settings = Settings()
    system_prompt = os.environ.get("SYSTEM_PROMPT") or SARCASTIC_CHARACTER_PROMPT
    # Story 6.3 — `SCENARIO_CHARACTER` is set by `routes_calls.initiate_call`
    # from the scenario YAML's `metadata.rive_character`. The legacy
    # `/connect` path doesn't set it, so default to "waiter" to keep the
    # PoC entry alive.
    scenario_character = os.environ.get("SCENARIO_CHARACTER") or "waiter"
    # Story 6.4 — `SCENARIO_ID` lets the bot resolve the PatienceTracker
    # config (silence ladder timing, patience meter, etc.) from the
    # scenario YAML + difficulty preset. Same fallback shape as the env
    # vars above: the legacy `/connect` path doesn't set it, so default
    # to the tutorial scenario.
    scenario_id = os.environ.get("SCENARIO_ID") or TUTORIAL_SCENARIO_ID
    patience_config = resolve_patience_config(scenario_id)

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
            system_instruction=system_prompt,
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
            stop_secs=0.8,
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
                    SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=1.8),
                ],
            ),
        ),
    )

    collector = TranscriptCollector(session_id=f"call_{int(time.time())}")
    transcript_user = TranscriptLogger(collector=collector, role="user")
    transcript_character = TranscriptLogger(collector=collector, role="character")

    # Story 6.3 — emotion observer. EmotionEmitter watches user
    # TranscriptionFrames (must sit between transcript_user and the user
    # context aggregator so it sees the *finalized* transcription); the
    # async classifier never blocks the pipeline.
    #
    # Visemes are generated client-side (Story 6.3b) directly from the
    # PCM audio buffer about to play at the speaker — see
    # `client/.../AudioClockChannel.kt` + `FormantVisemeAnalyzer.kt`.
    # No server-side viseme emitter is required (or wanted: data-channel
    # latency made the previous server-driven approach unsyncable).
    emotion_emitter = EmotionEmitter(
        character=scenario_character,
        openrouter_api_key=settings.openrouter_api_key,
    )

    # Story 6.4 — server-side silence escalation + character hang-up.
    # PatienceTracker sits between `context_aggregator.user()` and `llm`
    # so it observes the user's finalized transcription frames and can
    # cancel its silence ladder the moment the aggregator publishes a
    # turn. Production wiring passes `abuse_classifier=None`; the
    # `inappropriate_content` reason path is only exercised by the
    # unit test until Story 6.6's ExchangeClassifier lands
    # (Deviation #1).
    #
    # `resolve_patience_config` returns the full scenario-metadata dict
    # (7 difficulty fields + `total_checkpoints`); all 8 are accepted by
    # PatienceTracker's constructor. `silence_penalty` /
    # `silence_prompt_seconds` / `initial_patience` / `total_checkpoints`
    # are applied by the Story 6.4 behavior; `fail_penalty` /
    # `recovery_bonus` / `silence_hangup_seconds` /
    # `escalation_thresholds` are stored dormant for Stories 6.6 / 6.7 /
    # DW1 consumption. Wired explicitly so a future preset-key rename
    # surfaces here as a KeyError instead of silently dropping a field.
    patience_tracker = PatienceTracker(
        initial_patience=patience_config["initial_patience"],
        fail_penalty=patience_config["fail_penalty"],
        silence_penalty=patience_config["silence_penalty"],
        recovery_bonus=patience_config["recovery_bonus"],
        silence_prompt_seconds=patience_config["silence_prompt_seconds"],
        silence_hangup_seconds=patience_config["silence_hangup_seconds"],
        escalation_thresholds=patience_config["escalation_thresholds"],
        total_checkpoints=patience_config["total_checkpoints"],
        hang_up_line_silence=patience_config["hang_up_line_silence"],
        hang_up_line_inappropriate=patience_config["hang_up_line_inappropriate"],
        hang_up_line_survived=patience_config["hang_up_line_survived"],
        patience_warning_line=patience_config["patience_warning_line"],
    )

    # Story 6.6 — checkpoint progression brain. ExchangeClassifier is
    # fire-and-forget (asyncio.create_task, 2.0 s timeout per call). The
    # manager swaps the live LLM system instruction in-place on advance
    # (Deviation #2 — `llm._settings.system_instruction` is the single
    # point of truth; the OpenAI adapter prepends it at every invocation,
    # the LLMContext is created empty so mutating it would add a second
    # system message) and routes the all-passed completion path through
    # `PatienceTracker.schedule_completion(survival_pct=100)`.
    scenario_metadata = load_scenario_metadata(scenario_id)
    scenario_checkpoints = load_scenario_checkpoints(scenario_id)
    scenario_base_prompt = load_scenario_base_prompt(scenario_id)
    exchange_classifier = ExchangeClassifier(
        openrouter_api_key=settings.openrouter_api_key,
    )
    checkpoint_manager = CheckpointManager(
        base_prompt=scenario_base_prompt,
        checkpoints=scenario_checkpoints,
        llm=llm,
        llm_context=context,
        classifier=exchange_classifier,
        patience_tracker=patience_tracker,
        scenario_description=scenario_metadata.get("title", scenario_id),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            transcript_user,
            emotion_emitter,
            # Story 6.6 Deviation #5 — CheckpointManager sits BEFORE the
            # user aggregator, NOT after. The user-aggregator (see
            # `pipecat.processors.aggregators.llm_response_universal`
            # line 509-510) CONSUMES TranscriptionFrames and does NOT
            # push them downstream. Placing the manager after the
            # aggregator (as the original spec said) made it inert in
            # prod for the first deploy — same class of bug as
            # Déviation #28 (test and code mutually wrong on frame
            # routing). Mirroring EmotionEmitter position is the correct
            # fix: both observe finalized TranscriptionFrames straight
            # from STT, before the aggregator absorbs them.
            checkpoint_manager,
            # Story 6.6 Deviation #29 (post-deploy 2026-05-18) — same
            # root cause as Dev #5 applied to PatienceTracker. Story 6.4
            # placed PatienceTracker AFTER `context_aggregator.user()`
            # per AD-2 ("observe the aggregator-blessed finalized
            # transcription"), but pipecat 0.0.108's LLMUserAggregator
            # `_handle_transcription` consumes the TranscriptionFrame
            # without pushing it downstream — so the tracker's
            # `_cancel_silence_timer()` path on TranscriptionFrame was
            # dead in prod since Story 6.4. The bug stayed dormant
            # because Story 6.4 / 6.5 smoke gates never exercised
            # "user speaks during the silence ladder" (Test 2 = user
            # silent → hangup expected; Tests 3/4/5 = network/user
            # hangup paths that don't trigger the ladder). Story 6.6
            # surfaced it on the very first call: the user MUST speak
            # mid-ladder to advance checkpoints, the ladder kept
            # running through stages 1→2→3→4, hangup fired even after
            # a successful checkpoint advance. Fix: move PatienceTracker
            # upstream of the aggregator so it observes TranscriptionFrames
            # directly from STT (same mechanism as CheckpointManager).
            # BSF UPSTREAM observation is unaffected — UPSTREAM frames
            # traverse every processor on the way back from
            # transport.output().
            patience_tracker,
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
            [
                TTSSpeakFrame(
                    "Hi. Welcome to The Golden Fork. I'll be taking your order. What can I get you?"
                )
            ]
        )
        # Story 6.7 AC1 + Phase 2 retouche #5 (2026-05-19) — schedule
        # the initial `checkpoint_advanced(index=0)` envelope to be
        # emitted by CheckpointManager itself on its first
        # post-StartFrame `process_frame` tick. This routes the
        # envelope through the SAME downstream chain (patience_tracker
        # → context_aggregator.user() → ... → transport.output()) as
        # the working `_classify_and_advance` envelopes, instead of
        # the source-side `task.queue_frames` path which is at risk
        # of being intercepted by an upstream processor (e.g. the
        # user aggregator). `schedule_initial_emit` only sets a
        # flag; the actual `push_frame` runs once the StartFrame
        # propagation reaches CheckpointManager.
        checkpoint_manager.schedule_initial_emit()

    @transport.event_handler("on_participant_left")
    async def on_participant_left(
        transport: LiveKitTransport, participant_id: str, reason: str = ""
    ) -> None:
        logger.info(f"Participant left: {participant_id} (reason: {reason})")
        await task.queue_frames([EndFrame()])

    @transport.event_handler("on_data_received")
    async def on_data_received(
        transport: LiveKitTransport, data: bytes, participant_id: str
    ) -> None:
        """Route client-originated data-channel envelopes.

        Story 6.4 — the client publishes `{"type":"playback_idle"}` via
        `room.localParticipant?.publishData(...)` whenever its
        speaker-side PCM stream confirms 600 ms of post-bot-speech
        silence (`VisemeScheduler.onSilenceConfirmed`). That signal is
        the canonical "the user has finished hearing the bot, the
        silence-clock starts now" trigger for `PatienceTracker`,
        replacing the server-side `BotStoppedSpeakingFrame` (which
        fired ~1 s ahead of the user's ear due to WebRTC jitter
        buffering).

        Malformed payloads / unknown types are silently ignored — a
        malformed envelope must NEVER crash the bot process.
        """
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning(
                f"on_data_received: malformed envelope from {participant_id}: {exc}"
            )
            return
        if not isinstance(payload, dict):
            return
        envelope_type = payload.get("type")
        if envelope_type == "playback_idle":
            patience_tracker.handle_playback_idle()
        # Unknown types: silently ignore so future client-side
        # additions can land before the matching server handler ships.

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
