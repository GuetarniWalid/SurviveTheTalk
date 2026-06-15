"""Pipecat voice pipeline: Soniox v4 STT -> OpenRouter/Qwen3.5 Flash LLM -> Cartesia Sonic 3 TTS."""

import argparse
import asyncio
import json
import os
import sys
import time

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    EndFrame,
    OutputAudioRawFrame,
    TextFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipeline.llm_provider import (
    build_main_llm,
    resolve_llm_api_key,
    resolve_llm_chat_url,
)
from pipecat.services.soniox.stt import SonioxContextObject, SonioxSTTService
from pipecat.transcriptions.language import Language
from pipecat.transports.livekit.transport import LiveKitParams, LiveKitTransport
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from config import Settings
from pipeline.checkpoint_manager import (
    CheckpointManager,
    format_remaining_goals_block,
    format_suggested_focus_block,
)
from pipeline.debrief_teardown import (
    brief_personality,
    persist_debrief,
    resolve_end_reason,
)
from pipeline.dtln_audio_filter import DTLNAudioFilter
from pipeline.endpoint_watchdog import EndpointWatchdog
from pipeline.environment_monitor import EnvironmentMonitor
from pipeline.exchange_classifier import ExchangeClassifier
from pipeline.exit_line_generator import generate_exit_line
from pipeline.device_hesitation_collector import (
    DeviceHesitationCollector,
    merge_hesitation_sources,
)
from pipeline.hesitation_observer import HesitationObserver
from pipeline.input_gate import InputGate
from pipeline.latency_probe import LatencyProbe
from pipeline.llm_warmup import warm_up_llm
from pipeline.patience_tracker import PatienceTracker
from pipeline.prompts import (
    COHERENCE_CHARTER,
    MOOD_TAG_DIRECTIVE,
    SARCASTIC_CHARACTER_PROMPT,
)
from pipeline.reply_sanitizer import ReplySanitizer
from pipeline.tts_factory import (
    CARTESIA_MODEL,
    build_tts_service,
    resolve_cartesia_voice,
)
from pipeline.tts_warmup import warm_up_tts_cartesia
from pipeline.tts_watchdog import TTSWatchdog
from pipeline.scenarios import (
    TUTORIAL_SCENARIO_ID,
    build_stt_terms,
    load_scenario_base_prompt,
    load_scenario_checkpoints,
    load_scenario_metadata,
    resolve_patience_config,
)
from pipeline.transcript_logger import TranscriptCollector, TranscriptLogger


# Story 6.13 review (2026-05-27) — strong references to fire-and-forget
# background tasks (the LLM warm-up). asyncio keeps only a WEAK reference
# to a bare `create_task` result, so a discarded task can be garbage-
# collected before it runs ("Task was destroyed but it is pending!") and
# the warm-up silently never fires. Retaining the task here keeps it alive;
# the done-callback discards the entry so the set can't grow unbounded
# across calls.
_BACKGROUND_TASKS: set[asyncio.Task] = set()

# Story 6.17 fix — neutral fallback when a scenario YAML has no
# `metadata.opening_line`. Every shipped scenario sets its own; this only
# guards a malformed/legacy YAML so the call never opens silently.
_DEFAULT_OPENING_LINE = "Hello? Can you hear me?"


async def run_bot(url: str, room: str, token: str) -> None:
    """Configure and run the Pipecat voice pipeline in a LiveKit room.

    The system prompt is taken from the `SYSTEM_PROMPT` env var when set
    (populated by `/calls/initiate` with the scenario-specific prompt);
    otherwise it falls back to the hardcoded waiter prompt used by the
    legacy `/connect` endpoint. Env var is used instead of a CLI flag to
    sidestep platform-specific argv length limits on long prompts.
    """
    settings = Settings()
    # (Story 6.29 — the `SCENARIO_CHARACTER` env read that lived here fed the
    # retired EmotionEmitter's classifier prompt; routes_calls still sets the
    # env var but nothing reads it server-side anymore.)
    # Story 6.4 — `SCENARIO_ID` lets the bot resolve the PatienceTracker
    # config (silence ladder timing, patience meter, etc.) from the
    # scenario YAML + difficulty preset. Same fallback shape as
    # `SYSTEM_PROMPT` (docstring above): the legacy `/connect` path
    # doesn't set it, so default to the tutorial scenario.
    scenario_id = os.environ.get("SCENARIO_ID") or TUTORIAL_SCENARIO_ID
    # Story 6.19 — the learner's GLOBAL difficulty pick, threaded from the
    # client via POST /calls/initiate → SCENARIO_DIFFICULTY env. Absent (legacy
    # /connect path, older clients) → None → the loaders resolve it to the
    # server default `scenarios.DEFAULT_DIFFICULTY` ("easy") — the authored
    # per-scenario fallback is gone (Story 6.28, global-only ruling). It drives
    # THREE things for this call: the patience preset (here), the character
    # behavior block (load_scenario_base_prompt below), and the TTS speech
    # speed (AC5).
    scenario_difficulty = os.environ.get("SCENARIO_DIFFICULTY") or None
    # Story 7.1 (Option A) — the DB call_id, threaded from `/calls/initiate`
    # via the CALL_ID env (mirrors SCENARIO_ID). Absent on the legacy
    # `/connect` path → no debrief is generated at teardown.
    call_id_env = os.environ.get("CALL_ID") or None
    patience_config = resolve_patience_config(
        scenario_id, difficulty=scenario_difficulty
    )

    # Story 6.8 Phase 2 / Story 6.10 — load scenario data NOW (before LLM
    # construction) so we can compose the initial `system_instruction`
    # with the `COHERENCE_CHARTER` slotted BETWEEN `base_prompt` and the
    # goal blocks. Story 6.10 (goal-based dialogue) replaced the linear
    # "first checkpoint's prompt_segment" suffix with the full
    # REMAINING_GOALS_BLOCK + SUGGESTED_FOCUS_BLOCK (all checkpoints are
    # pending at boot). This matches EXACTLY what
    # `CheckpointManager._update_system_instruction` recomposes on every
    # successful turn (it calls the same `format_*` helpers), so the
    # charter + goal framing never drift between init and recompose.
    scenario_metadata = load_scenario_metadata(scenario_id)
    scenario_checkpoints = load_scenario_checkpoints(scenario_id)
    # Story 6.19 AC4 — compose the behavior block for the learner's GLOBAL
    # pick so a "hard" pick on any scenario actually speaks hard. None → the
    # server default easy (Story 6.28).
    scenario_base_prompt = load_scenario_base_prompt(
        scenario_id, difficulty=scenario_difficulty
    )

    # The legacy `SYSTEM_PROMPT` env var path (used historically by
    # `/connect` and the original `/calls/initiate` route) is preserved
    # as a defensive fallback in case the YAML loaders ever fail; even
    # the env-var path appends the charter so legacy entry-points inherit
    # coherence. In practice the env-var branch is dead since
    # `scenario_id` always resolves (TUTORIAL_SCENARIO_ID fallback).
    env_system_prompt = os.environ.get("SYSTEM_PROMPT")
    # Story 6.18 — the BARE persona (no COHERENCE_CHARTER, no goal decoration)
    # handed to the dynamic exit-line generator; it slots the charter back in
    # itself so the closing/warning line stays in-voice but can't fabricate
    # events. Tracked alongside `initial_system_prompt` so all three branches
    # stay in lockstep.
    # Story 6.29 (AC8) — MOOD_TAG_DIRECTIVE is appended as the LAST block of
    # EVERY branch (same invariance as the charter): the reply LLM co-generates
    # its trailing mood tag from the very first turn. CheckpointManager's
    # init-time recompose sets the identical string (its composer appends the
    # directive by default), so boot and recompose can't drift. The exit-line
    # persona deliberately does NOT carry it — exit/warning lines ride
    # `TTSSpeakFrame`s that bypass the sanitizer, so a tag there would be
    # SPOKEN.
    if scenario_base_prompt and scenario_checkpoints:
        initial_system_prompt = (
            scenario_base_prompt.rstrip()
            + "\n\n"
            + COHERENCE_CHARTER
            + "\n\n"
            + format_remaining_goals_block(scenario_checkpoints)
            + "\n\n"
            + format_suggested_focus_block(scenario_checkpoints[0])
            + "\n\n"
            + MOOD_TAG_DIRECTIVE
        )
        exit_line_persona = scenario_base_prompt.rstrip()
    elif env_system_prompt:
        initial_system_prompt = (
            env_system_prompt + "\n\n" + COHERENCE_CHARTER + "\n\n" + MOOD_TAG_DIRECTIVE
        )
        exit_line_persona = env_system_prompt
    else:
        initial_system_prompt = (
            SARCASTIC_CHARACTER_PROMPT
            + "\n\n"
            + COHERENCE_CHARTER
            + "\n\n"
            + MOOD_TAG_DIRECTIVE
        )
        exit_line_persona = SARCASTIC_CHARACTER_PROMPT

    # Story 6.9 — DTLN noise suppression on the input audio path. Wraps
    # `livekit.plugins.dtln.DTLNNoiseSuppressor` (Aloware, MIT, ~4 MB ONNX
    # bundle) behind Pipecat's `BaseAudioFilter` interface. Applied BEFORE
    # VAD + STT so every downstream observer (Silero VAD, Soniox, emotion
    # + exchange classifiers, CheckpointManager) sees clean speech. Failure
    # at init falls back to passthrough — the call never crashes due to
    # the filter. `strength=0.5` is the default wet/dry blend. We
    # briefly tried 0.8 (Story 6.9 noise-rejection tuning 2026-05-21)
    # but reverted after the smoke test showed it didn't help with
    # the YouTube/babble case (voice-vs-voice = cocktail-party problem,
    # needs voice-isolation not noise-suppression) AND slightly
    # degraded the calm-room baseline. Cocktail-party fix deferred
    # to a future paid voice-isolation Story OR client-side headphone
    # recommendation in onboarding.
    # Story 6.13 follow-up (2026-05-27) — DTLN kill-switch (`DTLN_ENABLED`,
    # default "1"). Doubles as ops control + the connection-jitter A/B:
    # DTLN runs per-frame ONNX inference on the input (mic) path, and on
    # the 2-core VPS that inference can contend with the output-audio
    # sender on the single asyncio loop → bursty audio-out pacing → the
    # WebRTC receiver time-stretches Tina's voice on a jittery 5G link
    # ("syllables to rallonge" reported 2026-05-27). Set `DTLN_ENABLED=0`
    # + restart to A/B whether the stretch is server-pacing (improves with
    # DTLN off) vs pure network jitter (no change). `audio_in_filter=None`
    # is pipecat's "no filter" default, so disabling is a clean no-op.
    if os.environ.get("DTLN_ENABLED", "1") == "1":
        audio_in_filter = DTLNAudioFilter(strength=0.5)
    else:
        audio_in_filter = None
        logger.info(
            "DTLN_ENABLED=0 — DTLN noise suppression DISABLED "
            "(connection-jitter A/B / ops kill-switch)"
        )

    transport = LiveKitTransport(
        url=url,
        token=token,
        room_name=room,
        params=LiveKitParams(
            audio_in_enabled=True,
            audio_in_filter=audio_in_filter,
            audio_out_enabled=True,
        ),
    )

    # Story 6.9 reliability patch (2026-05-21) — `vad_force_turn_endpoint=False`
    # delegates endpoint detection to Soniox's own neural VAD instead of
    # waiting on Silero's `VADUserStoppedSpeakingFrame` (the default `True`
    # bridges the two: Silero declares stop → Pipecat sends finalize to
    # Soniox). Under `True`, if Silero never declares stop (continuous
    # low-level audio: breathing, AC hum, papers rustling), Soniox keeps
    # streaming interim TFs indefinitely and the user's turn is never
    # finalized — Tina stays silent forever. Call 142 (2026-05-21,
    # "Cola" attempt) failed exactly this way: 22 s of interim TFs with
    # no finalize → user gave up and hung up.
    #
    # With `False`, Soniox uses its own endpoint-detection model trained
    # on prosody + silence + speech-completion cues — much more robust
    # to ambient noise than Silero's acoustic-energy threshold.
    #
    # Story 6.11 AC1 — `enable_speaker_diarization=True` annotates every
    # Soniox token with a `speaker` id in the `TranscriptionFrame.result`
    # token list. Zero extra cost (diarization is included in our Soniox
    # plan — it's a config flag, not a separate model) and used ONLY by
    # Story 6.11's `EnvironmentMonitor` to detect a parasitic background
    # VOICE (the cocktail-party case DTLN can't suppress — noise
    # suppression ≠ voice isolation; see Story 6.9 smoke-test finding).
    # Soniox puts the per-token speaker id on `result`, NOT on
    # `frame.metadata` (verified against pipecat 0.0.108
    # `services/soniox/stt.py` — the parser sets
    # `TranscriptionFrame(..., result=self._final_transcription_buffer)`
    # where each buffered token is the raw Soniox dict with a `speaker`
    # key). EnvironmentMonitor reads `frame.result` accordingly.
    # Story 6.19 follow-up — bias STT toward THIS scenario's proper nouns
    # (character / place / business / menu names like "Halloran's Electronics",
    # "Carver Street", "fish and chips") so a French accent doesn't mis-segment
    # them. SHORT, scenario-scoped list from `build_stt_terms`; None when the
    # scenario has no terms OR the `STT_CONTEXT_ENABLED` kill-switch is "0" → no
    # bias (today's behavior, instant rollback without a redeploy). It CANNOT
    # bias the learner's OWN self-stated name — the app stores no user name.
    stt_context = None
    if os.environ.get("STT_CONTEXT_ENABLED", "1") == "1":
        stt_terms = build_stt_terms(scenario_id)
        if stt_terms:
            stt_context = SonioxContextObject(terms=stt_terms)
            logger.info("stt_context scenario={} terms={}", scenario_id, stt_terms)
    stt = SonioxSTTService(
        api_key=settings.soniox_api_key,
        settings=SonioxSTTService.Settings(
            model="stt-rt-v4",
            enable_speaker_diarization=True,
            # Pin STT to English. The app is English-ONLY (every persona says
            # "Speak English only"), but stt-rt-v4 with NO language hint
            # auto-detects, and on a short/accented FIRST utterance it
            # mis-detected the learner's speech as Russian/Ukrainian and
            # transcribed Cyrillic gibberish ("Я шу.", "Вітанні валід."): the
            # character "couldn't catch that", NO checkpoint ever met, patience
            # drained to a hang-up in ~36 s (smoke gate 2026-06-09 — user felt
            # "unheard"). `_strict` forbids any non-English transcription so the
            # mis-detect cannot recur; relax it only if the app goes multilingual.
            language_hints=[Language.EN],
            language_hints_strict=True,
            # Story 6.19 follow-up — per-scenario proper-noun bias (built above).
            # None → unset → no bias. Complementary to language_hints: strict-EN
            # picks the LANGUAGE, `context.terms` biases WORD choice within it.
            context=stt_context,
        ),
        vad_force_turn_endpoint=False,
    )

    # Story 6.9 review patch (D3) — wall-clock backstop for Soniox
    # endpoint detection. `vad_force_turn_endpoint=False` above
    # delegates endpoint detection entirely to Soniox's neural VAD;
    # if Soniox itself never declares endpoint (long mid-utterance
    # pause, network hiccup, neural-VAD misfire), every downstream
    # observer hangs because they all gate on `finalized=True`.
    # `EndpointWatchdog` watches the post-STT TranscriptionFrame
    # stream and synthesises a `finalized=True` frame after 8 s of
    # continuous interim activity — the user gets a slightly
    # truncated turn but the call doesn't hang.
    endpoint_watchdog = EndpointWatchdog()

    # 2026-05-29 all-Groq migration + provider abstraction — the main
    # character LLM is built by `pipeline/llm_provider.build_main_llm`, the
    # SINGLE switch point for which OpenAI-compatible provider every LLM
    # call targets (`Settings.llm_base_url` + resolved key, default Groq).
    # Moving off Groq tomorrow = env change (LLM_BASE_URL + LLM_API_KEY +
    # CHARACTER_MODEL), zero code. The factory uses `OpenAILLMService`
    # (NOT pipecat's `GroqLLMService`, whose package imports `groq.tts`
    # needing the uninstalled `groq` SDK). Persona recalibration on the
    # Llama model is a deliberate follow-up.
    llm = build_main_llm(settings, system_instruction=initial_system_prompt)

    # Story 6.13 follow-up (2026-05-27) — fire a fire-and-forget LLM
    # warm-up so the user's first turn doesn't eat the provider
    # cold-start (measured ~0.5 s slower on turn 1 vs warm turns, call
    # 164). Launched here so it warms in PARALLEL with the rest of the
    # pipeline setup + LiveKit connect + greeting playback; by the time
    # the user finishes their first turn (several seconds in) the
    # connection + provider-side model are hot. Never blocks, never
    # raises — see `pipeline/llm_warmup.py`.
    _warmup_task = asyncio.create_task(
        warm_up_llm(
            api_key=resolve_llm_api_key(settings),
            model=settings.character_model,
            base_url=resolve_llm_chat_url(settings),
        )
    )
    _BACKGROUND_TASKS.add(_warmup_task)
    _warmup_task.add_done_callback(_BACKGROUND_TASKS.discard)

    # Story 6.13 → 6.14 — TTS provider is selected by
    # `Settings.tts_provider` (env: `TTS_PROVIDER=cartesia|elevenlabs`,
    # default `cartesia` since Story 6.14). The factory handles both
    # providers + the `CARTESIA_INSTRUMENT` verbose debug gate — bot.py
    # never names a provider class directly. See `pipeline/tts_factory.py`
    # for the branching + why Cartesia is the default again (resolved
    # platform incident + smoother under jitter than ElevenLabs).
    # Story 6.17 — pass the scenario's selected voice (metadata.tts_voice_id) so
    # each character speaks with its own voice (e.g. a detective vs the default
    # British female). None/empty → the Cartesia default. Before 6.17 this field
    # was stored but ignored.
    tts = build_tts_service(
        settings,
        voice_id=scenario_metadata.get("tts_voice_id"),
        # Story 6.19 AC5 — per-difficulty speech rate (easy slower/clearer →
        # hard faster), resolved from the difficulty preset (or the nullable
        # per-scenario `metadata.tts_speed` override).
        speed=patience_config["tts_speed"],
    )

    # Story 6.24 — TTS warm-up. Symmetric to the LLM warm-up above: the canned
    # opening line is the call's FIRST synthesis, so it pays the Cartesia
    # cold-start (sonic-3 model + voice load + edge) — on a cold edge that can
    # stall past the 5 s TTSWatchdog and emit total silence (call_id=226). Fire
    # a throwaway /tts/bytes synthesis of the SAME model + RESOLVED voice
    # (resolve_cartesia_voice → identical to what build_tts_service speaks with)
    # in parallel with the LiveKit connect + greeting, so the opening
    # TTSSpeakFrame hits a hot model. Provider-gated (Cartesia only; ElevenLabs
    # is the fallback + already low-TTFA) + TTS_WARMUP_ENABLED kill-switch.
    # Never blocks/raises; the TTSWatchdog stays the real safety net.
    if settings.tts_warmup_enabled and settings.tts_provider == "cartesia":
        _tts_warmup_task = asyncio.create_task(
            warm_up_tts_cartesia(
                api_key=settings.cartesia_api_key,
                model=CARTESIA_MODEL,
                voice_id=resolve_cartesia_voice(scenario_metadata.get("tts_voice_id")),
            )
        )
        _BACKGROUND_TASKS.add(_tts_warmup_task)
        _tts_warmup_task.add_done_callback(_BACKGROUND_TASKS.discard)

    # Story 6.8 Phase 1 AC2 — VAD `stop_secs` audit. Pipecat 0.0.108's
    # `SileroVADAnalyzer` consumes `stop_secs` independently of the
    # `UserTurnStrategies` block below: `stop_secs` is the silence
    # threshold the VAD uses to flip its internal speaking→silent state
    # (`VADState.QUIET` event), which then triggers downstream
    # `UserStoppedSpeakingFrame` emission. `SpeechTimeoutUserTurnStopStrategy.
    # user_speech_timeout` is a SECOND timer that runs from the
    # VAD-emitted stop signal until the turn is declared "done" and the
    # LLM is invoked. The two STACK: net silence-to-turn-end ≈
    # `stop_secs + user_speech_timeout`. With the AC1 tune below
    # (`user_speech_timeout=0.6`), keeping `stop_secs=0.8` gives ~1.4 s
    # net silence floor — comfortable under the PRD 2 s ceiling but
    # leaves room for STT finalization + LLM TTFT + TTS TTFA + network
    # jitter without spilling over. Reducing `stop_secs` below 0.5 risks
    # the VAD flipping QUIET mid-utterance on slow B1 speakers (1-3 s
    # thinking pauses); audit revisited if smoke-gate p95 exceeds 2 s.
    # See `memory/feedback_latency_kill_criterion_exceeded.md` lever #2.
    # Story 6.9 tuning revert (2026-05-21) — we briefly bumped
    # `confidence` 0.7 → 0.85 and `min_volume` 0.5 → 0.7 to try to
    # reject background voices, but the smoke test confirmed those
    # params hurt soft-voice users (long interim TFs, fragmented
    # finalizes) without solving the voice-isolation case. Reverted
    # to lenient defaults. Real cocktail-party fix needs a voice
    # isolation layer (paid: Krisp BVC, AI-coustics) — deferred.
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
                    # Turn-endpoint timeout — how long we wait after the VAD
                    # flags silence before declaring the user's turn DONE and
                    # letting the character respond. History: 1.8 s (pre-6.8) →
                    # 0.6 s (Story 6.8 latency tune) → 0.8 s default +
                    # env-configurable (Story 6.18 smoke gate, call_id=215,
                    # 2026-06-03). 0.6 s chopped B1 thinking pauses into separate
                    # turns — "Do you, uh, ooh." was finalized as its own turn
                    # and judged a FAIL (unfair -25 patience), and the character
                    # talked over the user. Now sourced from
                    # `Settings.user_speech_timeout` (USER_SPEECH_TIMEOUT) so the
                    # VPS can tune it without a redeploy. Stacks ADDITIVELY with
                    # VAD `stop_secs` above — net silence-to-turn-end ≈ 1.6 s at
                    # the 0.8 s default, still under the PRD 2 s ceiling. See
                    # `memory/feedback_latency_kill_criterion_exceeded.md` lever #1.
                    SpeechTimeoutUserTurnStopStrategy(
                        user_speech_timeout=settings.user_speech_timeout
                    ),
                ],
            ),
        ),
    )

    # Story 7.1 — tag the collector with the real DB call_id when available
    # (was a unix-ts session id). The teardown debrief keys off this call_id.
    collector = TranscriptCollector(
        session_id=call_id_env or f"call_{int(time.time())}"
    )
    transcript_user = TranscriptLogger(collector=collector, role="user")
    transcript_character = TranscriptLogger(collector=collector, role="character")

    # Story 6.29 (AC2 + AC8) — reply sanitizer. Replaces the Story 6.3
    # `EmotionEmitter` (retired): the character's face emotion is now
    # CO-GENERATED by the reply LLM as a trailing `<mood:VALUE>` tag
    # (MOOD_TAG_DIRECTIVE above), which this processor strips from the
    # streamed reply text — along with `(...)` parentheticals and `*...*`
    # stage actions (call-274 P2) — and re-emits as the SAME
    # `{"type":"emotion"}` envelope on the data channel. Sits between
    # `llm_first_text_probe` and `transcript_character` (see the Pipeline
    # list below) so probes measure raw LLM TTFT while the transcript, TTS,
    # and the downstream assistant aggregator (= the LLM context + the
    # exit-line transcript + the judge's last_character_line) all see CLEAN
    # spoken text only.
    #
    # Visemes are generated client-side (Story 6.3b) directly from the
    # PCM audio buffer about to play at the speaker — see
    # `client/.../AudioClockChannel.kt` + `FormantVisemeAnalyzer.kt`.
    # No server-side viseme emitter is required (or wanted: data-channel
    # latency made the previous server-driven approach unsyncable).
    reply_sanitizer = ReplySanitizer()

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
    #
    # Story 6.18 — build the dynamic exit/patience-warning line generator and
    # inject it into PatienceTracker. The closure reads the LIVE transcript
    # (`context.get_messages()`) at hang-up time and POSTs it to the character
    # LLM via the shared provider resolvers (same Groq config as the main
    # brain + warm-up). Keeping the LLM/context wiring HERE (not inside
    # PatienceTracker) leaves that processor transport-free + unit-testable.
    # `HANGUP_LINE_GENERATION=0` flips the whole feature back to the canned
    # YAML `exit_lines` with no logic redeploy (AC7) by injecting `None`.
    if settings.hangup_line_generation:

        async def _generate_hang_up_line(
            reason: str, extra_user_text: str | None = None
        ) -> str | None:
            transcript = context.get_messages()
            if extra_user_text:
                # P0 (Decision #2 / Option A) — the survived path passes the
                # winning user turn CheckpointManager suppressed from the LLM
                # context (Deviation #7). Append it to a NEW list (never mutate
                # the live context) so the closing line can reference the
                # answer that actually won.
                transcript = [
                    *transcript,
                    {"role": "user", "content": extra_user_text},
                ]
            return await generate_exit_line(
                reason=reason,
                transcript=transcript,
                persona=exit_line_persona,
                charter=COHERENCE_CHARTER,
                api_key=resolve_llm_api_key(settings),
                model=settings.character_model,
                base_url=resolve_llm_chat_url(settings),
            )

        hang_up_line_generator = _generate_hang_up_line
    else:
        hang_up_line_generator = None
        logger.info(
            "HANGUP_LINE_GENERATION=0 — dynamic exit/warning lines DISABLED "
            "(canned YAML exit_lines used; AC7 kill-switch)"
        )

    patience_tracker = PatienceTracker(
        initial_patience=patience_config["initial_patience"],
        fail_penalty=patience_config["fail_penalty"],
        silence_penalty=patience_config["silence_penalty"],
        recovery_bonus=patience_config["recovery_bonus"],
        silence_prompt_seconds=patience_config["silence_prompt_seconds"],
        # Story 6.13 AC3 — per-difficulty stage-1 anchor (was the deleted
        # module constant `_LADDER_IMPATIENCE_AT`). Easy 4.5 / medium 3.5
        # / hard 2.5 s; nullable YAML override via `metadata.
        # ladder_impatience_seconds`.
        ladder_impatience_seconds=patience_config["ladder_impatience_seconds"],
        silence_hangup_seconds=patience_config["silence_hangup_seconds"],
        escalation_thresholds=patience_config["escalation_thresholds"],
        total_checkpoints=patience_config["total_checkpoints"],
        hang_up_line_silence=patience_config["hang_up_line_silence"],
        hang_up_line_inappropriate=patience_config["hang_up_line_inappropriate"],
        hang_up_line_survived=patience_config["hang_up_line_survived"],
        # Story 6.11 — parasitic-voice exit line (YAML
        # `exit_lines.noisy_environment` → generic default fallback).
        hang_up_line_noisy_environment=patience_config[
            "hang_up_line_noisy_environment"
        ],
        patience_warning_line=patience_config["patience_warning_line"],
        # Story 6.18 — dynamic exit/warning-line generator (None when
        # HANGUP_LINE_GENERATION=0 → canned YAML lines).
        hang_up_line_generator=hang_up_line_generator,
    )

    # Story 6.11 — EnvironmentMonitor observes the user's finalized
    # TranscriptionFrames and detects a parasitic background VOICE via
    # Soniox speaker diarization (the cocktail-party case DTLN can't
    # suppress). On detection it emits an `env_warning` envelope + calls
    # `patience_tracker.schedule_noisy_environment_exit()`, which speaks
    # the in-character exit line and ends the call (refunded server-side).
    # Wired UPSTREAM of CheckpointManager and the user aggregator so it
    # observes raw TFs straight from STT (mirror Story 6.6 Dev #5) — see
    # the Pipeline list below.
    # Story 6.11 fix (2026-05-30) — InputGate sits at the TOP of the pipeline
    # (right after transport.input(), before STT). EnvironmentMonitor arms it
    # on noise detection so the mic is muted ("stop listening") — the loud
    # parasite can then no longer interrupt Tina's exit line (smoke
    # call_id=205: continuous interruptions flushed the line every ~1.5 s).
    input_gate = InputGate()
    # Story 6.20 follow-up — env-tunable sensitivity + kill-switch (call_id=223
    # false positive; the co-occurrence rule is the code fix, these are the live
    # safety valve). Defaults reproduce the shipped Story 6.11 behaviour.
    environment_monitor = EnvironmentMonitor(
        patience_tracker=patience_tracker,
        input_gate=input_gate,
        enabled=settings.env_monitor_enabled,
        trigger_turns=settings.env_monitor_trigger_turns,
        min_speaker_tokens=settings.env_monitor_min_speaker_tokens,
    )

    # Story 6.6 — checkpoint progression brain. ExchangeClassifier is
    # fire-and-forget (asyncio.create_task, 1.0 s timeout per call —
    # tightened from 2.0 s in Story 6.8 Phase 1 to keep terminal-zone
    # latency under the PRD ceiling). The manager swaps the live LLM
    # system instruction in-place on advance (Deviation #2 —
    # `llm._settings.system_instruction` is the single point of truth;
    # the OpenAI adapter prepends it at every invocation, the LLMContext
    # is created empty so mutating it would add a second system message)
    # and routes the all-passed completion path through
    # `PatienceTracker.schedule_completion(survival_pct=100)`.
    #
    # Story 6.8 Phase 2 — `coherence_charter` is threaded explicitly
    # (required kwarg, no default) so the manager composes the same
    # `base + charter + segment` shape we use for the initial
    # `system_instruction` above. The wiring test
    # (`test_bot_pipeline_wiring.py::test_coherence_charter_threaded_
    # to_checkpoint_manager_and_llm_settings`) source-text-asserts both
    # the import and this call shape, so a future refactor that drops
    # either breaks loud.
    # Story 6.9b — Classifier on Groq Llama 3.3 70B (2026-05-22 bench).
    # 2026-05-29 — now goes through the shared LLM provider config
    # (resolved base_url + key from Settings; default Groq). Provider
    # switch = env change (LLM_BASE_URL + LLM_API_KEY + CLASSIFIER_MODEL).
    exchange_classifier = ExchangeClassifier(
        api_key=resolve_llm_api_key(settings),
        model=settings.classifier_model,
        base_url=resolve_llm_chat_url(settings),
    )
    # Story 6.27 (D2a) — warm the classifier's OWN lazy httpx client at call
    # start. The Story 6.24 llm_warmup above warms Groq through its own
    # throwaway client, NOT this instance's: the classifier paid its cold TLS
    # handshake on the FIRST classify, which blew the 1.5 s HTTP budget and
    # silently lost the opening turn on calls 265/266. Fire-and-forget,
    # never blocks, never raises; the 6.24/6.26 strong-ref + done-callback
    # pattern keeps the task from being GC'd mid-flight. Runs at call start
    # inside run_bot (NOT pool-park time — parked bots have no call context).
    _classifier_warmup_task = asyncio.create_task(exchange_classifier.warm_up())
    _BACKGROUND_TASKS.add(_classifier_warmup_task)
    _classifier_warmup_task.add_done_callback(_BACKGROUND_TASKS.discard)
    checkpoint_manager = CheckpointManager(
        base_prompt=scenario_base_prompt,
        checkpoints=scenario_checkpoints,
        llm=llm,
        llm_context=context,
        classifier=exchange_classifier,
        patience_tracker=patience_tracker,
        scenario_description=scenario_metadata.get("title", scenario_id),
        coherence_charter=COHERENCE_CHARTER,
        # FR37 — env kill-switch for the abuse → inappropriate-content hang-up
        # (the abuse flag rides the same classify_multi call; no extra LLM call).
        abuse_detection_enabled=settings.abuse_detection_enabled,
        # Story 6.29 (D1 = bounded wait, fail-open) — hold each judged turn up
        # to this budget for the verdict's side effects to land before the LLM
        # sees the turn; 0 disables (pure parallel = pre-6.29). Env
        # VERDICT_WAIT_BUDGET_MS, validated at boot in config.py.
        verdict_wait_budget_ms=settings.verdict_wait_budget_ms,
    )

    # Story 6.8 Phase 1 AC3 — LLM→TTS streaming-overlap probe. Both
    # probes are inert in production (the `LATENCY_PROBE` env var is
    # unset by `routes_calls.initiate_call`); smoke-gate operators set
    # `LATENCY_PROBE=1` on the VPS, run one calibrated Waiter call, and
    # compute the gap from the journalctl tail:
    #   (tts_first_audio.ts_ns - llm_first_text.ts_ns) / 1_000_000 ms
    # Target: <500 ms (LLM is streaming tokens into TTS). >500 ms means
    # TTS waits for the full LLM response — enable streaming flag on
    # CartesiaTTSService.
    llm_first_text_probe = LatencyProbe(
        label="llm_first_text",
        frame_type=TextFrame,
    )
    tts_first_audio_probe = LatencyProbe(
        label="tts_first_audio",
        frame_type=OutputAudioRawFrame,
    )

    # Story 6.13 AC1 — Cartesia silent-stall watchdog. Sits between
    # `tts` and `tts_first_audio_probe` so it observes the same audio
    # stream the probe does. 5 s wall-clock timer arms on every
    # `TTSStartedFrame`, cancels on first `OutputAudioRawFrame` or
    # `TTSStoppedFrame`. On timeout, pushes a synthetic
    # `TTSStoppedFrame` downstream so the pipeline unblocks — the
    # user gets silence on their device for the stalled turn but the
    # call survives instead of soft-locking until manual hangup.
    # See `_bmad-output/implementation-artifacts/6-13-epic-6-prelaunch-hardening.md`
    # AC1 + Deviation #1 (mitigation, not root-cause fix; investigation
    # of the underlying Cartesia/pipecat bug is a follow-up).
    tts_watchdog = TTSWatchdog()

    # Story 7.1 (AC11) — hesitation gap observer. Placed IMMEDIATELY adjacent to
    # PatienceTracker below: that slot provably sees BotStoppedSpeakingFrame
    # (UPSTREAM) + UserStartedSpeakingFrame (DOWNSTREAM), so the gaps measure
    # correctly. Read via `top_hesitations()` at teardown.
    hesitation_observer = HesitationObserver(collector=collector)
    # Story 7.5 (D3-c) — collects DEVICE-measured onset gaps published by the
    # client meter over the data channel (see `on_data_received`). Teardown
    # PREFERS these (accurate, no network term) over the server observer.
    device_hesitation_collector = DeviceHesitationCollector(collector=collector)

    pipeline = Pipeline(
        [
            transport.input(),
            # Story 6.11 fix — InputGate FIRST (after the transport's mic
            # input, before STT). Inert until EnvironmentMonitor arms it on
            # noise detection; once armed it drops mic audio + VAD +
            # interruption frames so the noisy-environment exit line plays
            # uninterrupted. See `pipeline/input_gate.py`.
            input_gate,
            stt,
            # Story 6.9 review patch (D3) — sit immediately downstream
            # of STT so the watchdog observes Soniox's raw TF stream
            # before any other processor (transcript_user, emotion,
            # checkpoint, patience). On force-finalize the synthesised
            # frame propagates through every observer that follows.
            endpoint_watchdog,
            transcript_user,
            # Story 6.11 — EnvironmentMonitor observes the raw finalized
            # TranscriptionFrame (with Soniox per-token speaker ids on
            # `result`) straight from STT, before any downstream processor.
            # Same upstream-of-aggregator rule as CheckpointManager (Story
            # 6.6 Dev #5 — the user aggregator consumes TranscriptionFrames).
            # Its `env_warning` envelope rides DOWNSTREAM on the same proven
            # client-bound path as the emotion / checkpoint envelopes.
            # (Story 6.29 — the EmotionEmitter that used to sit between this
            # and CheckpointManager is retired; the face emotion now rides
            # the reply LLM's mood tag via `reply_sanitizer` below.)
            environment_monitor,
            # Story 6.6 Deviation #5 — CheckpointManager sits BEFORE the
            # user aggregator, NOT after. The user-aggregator (see
            # `pipecat.processors.aggregators.llm_response_universal`
            # line 509-510) CONSUMES TranscriptionFrames and does NOT
            # push them downstream. Placing the manager after the
            # aggregator (as the original spec said) made it inert in
            # prod for the first deploy — same class of bug as
            # Déviation #28 (test and code mutually wrong on frame
            # routing). Mirroring the then-present EmotionEmitter's
            # position (retired in 6.29) was the correct fix: observe
            # finalized TranscriptionFrames straight from STT, before
            # the aggregator absorbs them.
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
            # Story 7.1 (AC11) — adjacent to PatienceTracker so it sees the same
            # BotStoppedSpeakingFrame (UPSTREAM) + UserStartedSpeakingFrame
            # (DOWNSTREAM) stream; pairs them into >3 s hesitation gaps.
            hesitation_observer,
            context_aggregator.user(),
            llm,
            llm_first_text_probe,
            # Story 6.29 (AC2) — ReplySanitizer slots AFTER the TTFT probe
            # (probes measure raw LLM first-token latency) and BEFORE
            # transcript_character, so the transcript, TTS, and everything
            # downstream (assistant aggregator → LLM context → exit-line
            # transcript → judge's last_character_line) see only CLEAN
            # spoken text: `(...)`/`*...*` spans and the trailing
            # `<mood:...>` tag never reach the voice nor the record.
            reply_sanitizer,
            transcript_character,
            tts,
            # Story 6.13 AC1 — wedged immediately after `tts` so the
            # watchdog observes Cartesia's audio stream BEFORE the
            # `tts_first_audio_probe`. If the watchdog fires, the
            # synthetic `TTSStoppedFrame` still flows through the
            # probe to `transport.output()` and unblocks downstream.
            tts_watchdog,
            tts_first_audio_probe,
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
        # Story 6.17 fix — the canned opening line is PER-SCENARIO
        # (`metadata.opening_line`), not the hardcoded waiter greeting that used
        # to play for every scenario (a detective opening with "Welcome to The
        # Golden Fork" — call_id 2026-06-02). Falls back to a neutral line if a
        # scenario omits it.
        opening_line = scenario_metadata.get("opening_line") or _DEFAULT_OPENING_LINE
        await task.queue_frames([TTSSpeakFrame(opening_line)])
        # Story 7.1 — the canned opening is a TTSSpeakFrame (not a TextFrame),
        # so `transcript_character` never logs it; record it explicitly so the
        # debrief transcript is COMPLETE (the LLM analyses the whole conversation)
        # and a >3 s hesitation after the greeting has a real preceding line.
        collector.add_turn("character", opening_line, 0)
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
        elif envelope_type == "hesitation_onset":
            # Story 7.5 (D3-c) — a device-measured onset gap. The collector
            # ignores CENSORED envelopes (the device could not measure → the
            # server observer covers that turn) and snapshots the preceding
            # character line itself.
            device_hesitation_collector.record(
                gap_ms=payload.get("gap_ms"),
                censored=payload.get("censored"),
            )
        # Unknown types: silently ignore so future client-side
        # additions can land before the matching server handler ships.

    runner = PipelineRunner()
    try:
        await runner.run(task)
    finally:
        # Story 7.1 (Decision 1 = Option A) — the call is over; the bot owns
        # debrief generation in-process and persists it to the shared DB
        # (`GET /debriefs/{call_id}` only reads). In a `finally` so the
        # always-land progress + checkpoint-count writes are not lost if
        # `runner.run` raised on an errored shutdown. A debrief failure must
        # NEVER crash teardown (or mask a pipeline error) — a missing debrief
        # degrades gracefully to DEBRIEF_NOT_READY.
        if call_id_env and call_id_env.isdigit():
            try:
                await persist_debrief(
                    settings=settings,
                    call_id=int(call_id_env),
                    transcript=list(collector.transcript),
                    reason=resolve_end_reason(
                        patience_tracker.call_end_reason,
                        met_count=checkpoint_manager.met_count,
                        total_checkpoints=len(scenario_checkpoints),
                    ),
                    checkpoints_passed=checkpoint_manager.met_count,
                    total_checkpoints=len(scenario_checkpoints),
                    character_name=scenario_metadata.get("title", scenario_id),
                    scenario_title=(
                        scenario_metadata.get("scenario_title")
                        or scenario_metadata.get("title", scenario_id)
                    ),
                    scenario_id=scenario_id,
                    brief_personality_description=brief_personality(
                        scenario_base_prompt
                    ),
                    hesitations=merge_hesitation_sources(
                        device_hesitation_collector.top_hesitations(),
                        hesitation_observer.top_hesitations(),
                    ),
                    checkpoints=checkpoint_manager.checkpoint_breakdown,
                )
            except Exception:
                logger.exception(
                    "debrief teardown failed (non-fatal) call_id={}", call_id_env
                )
        else:
            logger.info(
                "debrief teardown skipped — no numeric CALL_ID (legacy /connect path)"
            )


# Story 6.26 — warm bot-process pool. A bot launched with `--parked` pre-pays
# the heavy module-import boot (already done by the time `main()` runs), prints
# this sentinel to stdout so the pool manager knows it is ready, then blocks
# reading ONE JSON job line from stdin. The job carries the per-call connection
# args + env (room/token + SCENARIO_*/SYSTEM_PROMPT/CALL_ID) — the SAME data the
# cold-spawn path passes via argv + the Popen `env=`. Keeping the per-call config
# OUT of argv/env-at-exec is what lets an already-booted generic process adopt a
# call. The pool (`pipeline/bot_pool.py`) matches this exact byte sequence.
PARKED_READY_SENTINEL = "BOT_PARKED_READY"

# The per-call env keys a parked job may carry (mirrors the `bot_env` the
# cold-spawn path builds in `routes_calls.initiate_call`). ONLY these are applied
# to `os.environ` — a parked bot never lets a job rewrite arbitrary process env
# (the pipeline secrets/livekit creds are already inherited from the server).
_PARKED_JOB_ENV_KEYS = frozenset(
    {
        "SYSTEM_PROMPT",
        "SCENARIO_CHARACTER",
        "SCENARIO_ID",
        "CALL_ID",
        "SCENARIO_DIFFICULTY",
    }
)


def apply_parked_job(line: str) -> tuple[str, str, str]:
    """Parse one stdin job line, apply its per-call env, return (url, room, token).

    The job is a JSON object `{"url","room","token","env":{...}}`. `env` holds the
    per-call values the cold path passes through Popen's `env=` — applied to
    `os.environ` here so `run_bot` (which reads them via `os.environ.get` at call
    time, bot.py:111-128) behaves IDENTICALLY to a cold spawn. Only the
    whitelisted `_PARKED_JOB_ENV_KEYS` are applied (a `None` value is skipped, so
    an absent `SCENARIO_DIFFICULTY` never leaks as the literal "None" — mirrors
    the cold path's AC7 guard). Raises ValueError on malformed input or a missing
    connection arg so the parked bot fails loud rather than connecting nowhere.
    """
    try:
        job = json.loads(line)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"parked job is not valid JSON: {exc}") from exc
    if not isinstance(job, dict):
        raise ValueError("parked job must be a JSON object")
    try:
        url = job["url"]
        room = job["room"]
        token = job["token"]
    except KeyError as exc:
        raise ValueError(f"parked job missing required connection key: {exc}") from exc
    env = job.get("env") or {}
    if not isinstance(env, dict):
        raise ValueError("parked job 'env' must be a JSON object")
    for key in _PARKED_JOB_ENV_KEYS:
        value = env.get(key)
        if value is not None:
            os.environ[key] = str(value)
    return str(url), str(room), str(token)


def _run_parked() -> None:
    """Parked-mode entry: signal readiness, await one job on stdin, run it once.

    The heavy imports are already paid (module load), so printing the sentinel
    here means the boot is done. Then we block on a single stdin line — zero CPU
    while parked. After the call, the process exits (single-use → clean
    isolation, identical lifecycle to a cold spawn).
    """
    print(PARKED_READY_SENTINEL, flush=True)
    line = sys.stdin.readline()
    if not line:
        # stdin closed before a job arrived (the pool is shutting us down) —
        # exit cleanly without touching the pipeline.
        logger.info("parked bot stdin closed before a job arrived; exiting")
        return
    url, room, token = apply_parked_job(line)
    asyncio.run(run_bot(url=url, room=room, token=token))


def main() -> None:
    """Parse CLI args and launch the pipeline (cold) or park for a job (pool)."""
    parser = argparse.ArgumentParser(description="Pipecat voice bot")
    parser.add_argument("--url", help="LiveKit server URL")
    parser.add_argument("--room", help="LiveKit room name")
    parser.add_argument("--token", help="LiveKit agent token")
    # Story 6.26 — warm-pool mode: ignore --url/--room/--token and wait for a
    # job on stdin instead. Default off = the unchanged cold-spawn path, whose
    # three args stay required.
    parser.add_argument(
        "--parked",
        action="store_true",
        help="Warm-pool mode: wait for a job on stdin instead of --url/--room/--token",
    )
    args = parser.parse_args()

    if args.parked:
        _run_parked()
        return

    if not (args.url and args.room and args.token):
        parser.error("--url, --room and --token are required unless --parked is set")

    asyncio.run(run_bot(url=args.url, room=args.room, token=args.token))


if __name__ == "__main__":
    main()
