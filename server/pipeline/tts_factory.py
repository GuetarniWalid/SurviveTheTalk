"""Story 6.13 Phase 4b (2026-05-26) → Story 6.14 (2026-05-30) — TTS factory.

Single branching point that builds the right TTS service from
`Settings.tts_provider`. Two providers are wired today:

- **Cartesia Sonic-3** (`tts_provider="cartesia"`, the launch DEFAULT
  since Story 6.14 2026-05-30). The default service is
  `ErrorLoggingCartesiaTTSService` — always-on surfacing of Cartesia's
  documented `type=error` schema (see `pipeline/cartesia_instrumented.py`).
  The `CARTESIA_INSTRUMENT=1` env-gate swaps in the verbose
  `InstrumentedCartesiaTTSService` for a future investigation, no code
  release needed.
- **ElevenLabs Flash v2.5** (`tts_provider="elevenlabs"`) — now the
  LAST-RESORT fallback. It has lower raw TTFA (~75 ms vs ~300 ms) but
  its larger audio frames time-stretch ("voix rallongée") more under
  network jitter, which is the launch-blocker; viable again once the
  Story 6.14 `min_playout_delay` jitter buffer absorbs the bursty
  arrival. Flip with `TTS_PROVIDER=elevenlabs` (env only, no code).

Why Cartesia is the default again: Cartesia support confirmed
(2026-05-28) the 2026-05-26 multi-frame freeze (calls 156/157) was a
RESOLVED platform incident, not a fundamental bug — both reproductions
landed in the incident window. Walid's on-device A/B (2026-05-30) found
Cartesia far smoother under jitter. The `FreshContextCartesiaTTSService`
"fix attempt" Cartesia confirmed unnecessary/counter-productive was
removed.

The factory is the ONLY place that names a provider class. Pipeline
construction (`bot.py`) calls `build_tts_service(settings)` and uses
the returned service like any other pipecat TTS service. Adding a
third provider later (OpenAI gpt-4o-mini-tts, Deepgram Aura, etc.)
means adding one branch here + matching Settings fields — bot.py
stays untouched.

Voice character (Tina the tired British waitress) must be cast in
both provider catalogs. Per-provider voice IDs are set via
`CARTESIA_VOICE_ID` (constant in `pipeline.prompts`) and
`ELEVENLABS_VOICE_ID` (env var). The character prompts in YAML stay
provider-agnostic.
"""

from __future__ import annotations

import os
from typing import Any

from loguru import logger
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

from config import Settings
from pipeline.prompts import CARTESIA_VOICE_ID


def build_tts_service(settings: Settings, *, voice_id: str | None = None) -> Any:
    """Return the configured TTS service instance.

    Story 6.17 — `voice_id` is the scenario's `metadata.tts_voice_id` (a Cartesia
    voice UUID, threaded from `bot.py`). When set AND the provider is Cartesia,
    that voice is used; when `None` (or for ElevenLabs, whose per-scenario voice
    is out of scope — it uses its single env voice), the Cartesia default
    `CARTESIA_VOICE_ID` is used. This is what makes a scenario's chosen voice
    (e.g. a detective's voice vs the default British female) actually take effect
    — before 6.17 the field was stored but ignored.

    Reads `settings.tts_provider` and returns either a Cartesia or
    ElevenLabs service constructed with the matching credentials +
    voice. Raises `RuntimeError` at process start if the chosen
    provider's required fields are missing, so a misconfigured deploy
    fails loud at boot instead of mid-call.

    Args:
        settings: Parsed `Settings` instance (loaded from .env).

    Returns:
        A pipecat `WebsocketTTSService` ready to wire into the
        pipeline. Type is `Any` rather than `WebsocketTTSService`
        because the Cartesia debug subclasses live in
        `pipeline.cartesia_instrumented` and we only import them
        lazily inside the cartesia branch.

    Raises:
        RuntimeError: If the chosen provider's required credentials
            or voice id are empty.
    """
    provider = settings.tts_provider
    if provider == "cartesia":
        return _build_cartesia(settings, voice_id=voice_id)
    if provider == "elevenlabs":
        return _build_elevenlabs(settings)
    # The Literal[...] type on settings.tts_provider already makes this
    # branch unreachable under Pydantic validation, but defensive guard
    # in case a future operator adds a new provider to the Literal
    # without updating this factory.
    raise RuntimeError(
        f"Unknown tts_provider {provider!r}; expected 'cartesia' or 'elevenlabs'. "
        "Update pipeline/tts_factory.py to handle the new provider."
    )


def _build_cartesia(settings: Settings, *, voice_id: str | None = None) -> Any:
    """Construct a Cartesia Sonic-3 service (the Story 6.14 launch default).

    Story 6.17 — `voice_id` (the scenario's `metadata.tts_voice_id`) overrides the
    default `CARTESIA_VOICE_ID` when provided, so each scenario speaks with its
    own selected voice. Falls back to the default when `None`/empty.

    - Default (no env-gate) → `ErrorLoggingCartesiaTTSService` (always-on
      WARNING surfacing of Cartesia's documented `type=error` schema).
    - `CARTESIA_INSTRUMENT=1` → `InstrumentedCartesiaTTSService` (verbose
      logging of every WS send/recv + audio context transition). Used
      during a freeze diagnostic phase.

    The Story 6.13 AC1 watchdog (`pipeline/tts_watchdog.py`) is the
    always-on 5 s safety net regardless of which subclass is selected.

    `CARTESIA_FRESH_CTX` is gone: Cartesia confirmed (2026-05-28) the
    fresh-context-per-sentence workaround was unnecessary and
    counter-productive (it multiplied the contexts the platform incident
    choked on), so Story 6.14 removed it.
    """
    if not settings.cartesia_api_key:
        raise RuntimeError(
            "TTS_PROVIDER=cartesia but CARTESIA_API_KEY is empty. "
            "Set it in /opt/survive-the-talk/.env or switch to "
            "TTS_PROVIDER=elevenlabs (the last-resort fallback)."
        )

    # Lazy import: the Cartesia debug subclasses pull in pipecat's
    # cartesia service module; only import inside this branch.
    from pipeline.cartesia_instrumented import (
        ErrorLoggingCartesiaTTSService,
        InstrumentedCartesiaTTSService,
    )

    tts_cls: type[CartesiaTTSService] = ErrorLoggingCartesiaTTSService
    if os.environ.get("CARTESIA_INSTRUMENT") == "1":
        tts_cls = InstrumentedCartesiaTTSService
        logger.info("CARTESIA_INSTRUMENT=1 — using InstrumentedCartesiaTTSService")

    resolved_voice = voice_id or CARTESIA_VOICE_ID
    logger.info(
        "TTS provider = cartesia (Sonic-3) voice={} [launch default]",
        resolved_voice,
    )
    return tts_cls(
        api_key=settings.cartesia_api_key,
        settings=CartesiaTTSService.Settings(
            model="sonic-3",
            voice=resolved_voice,
        ),
    )


def _build_elevenlabs(settings: Settings) -> ElevenLabsTTSService:
    """Construct an ElevenLabs Flash v2.5 service.

    Required env: `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID`. Voice
    id is the public Voice Library identifier (or a custom-cloned
    voice id from the operator's ElevenLabs account); Tina the
    waitress character profile (tired British female, low-energy,
    becomes sarcastic when provoked) maps best to voices in the
    "Conversational" / "British Female" categories — operator picks
    via the ElevenLabs Voice Library and pins the id via env var.
    Optional override: `ELEVENLABS_MODEL` to pin a specific model
    snapshot.

    Defaults are documented in `config.py::Settings` field comments.
    The model `eleven_flash_v2_5` is the lowest-TTFA option in their
    catalog (~75 ms advertised).

    Story 6.14 AC3 — frame/streaming review (the "larger frames stretch
    more under jitter" angle). Pipecat 0.0.108's `ElevenLabsTTSService`
    exposes three levers, NONE changed here because each needs on-device
    AC1-metric validation (a wrong move regresses TTFA — and ElevenLabs
    is now the last-resort fallback, so the jitter buffer + Cartesia
    default are the primary fixes, not this):
      - `output_format` — derived from `sample_rate` (default service
        sample rate → e.g. `pcm_24000`). A lower sample rate yields
        smaller per-chunk payloads but coarser audio; not obviously a
        steadier stream and risks quality.
      - `params.auto_mode` (default `True`) — ElevenLabs buffers to
        sentence boundaries and ignores `chunk_length_schedule`. Setting
        it `False` would let us pin a `chunk_length_schedule` for
        smaller, steadier chunks, at a latency cost.
      - `params.enable_ssml_parsing` — irrelevant to framing.
    The real receiver-side fix is `Settings.livekit_min_playout_delay_ms`
    (the jitter buffer), which helps EVERY provider. If a future device
    A/B shows a smaller-frame ElevenLabs config measurably reduces
    `concealedSamples`/stretch without a TTFA regression, wire it here
    behind a Settings field.
    """
    if not settings.elevenlabs_api_key:
        raise RuntimeError(
            "TTS_PROVIDER=elevenlabs but ELEVENLABS_API_KEY is empty. "
            "Generate one at https://elevenlabs.io/app/settings/api-keys "
            "and set it in /opt/survive-the-talk/.env."
        )
    if not settings.elevenlabs_voice_id:
        raise RuntimeError(
            "TTS_PROVIDER=elevenlabs but ELEVENLABS_VOICE_ID is empty. "
            "Browse https://elevenlabs.io/app/voice-library, pick a voice "
            "for Tina (tired British female waitress, e.g. Alice / "
            "Charlotte / Dorothy as starting candidates), copy its id "
            "into /opt/survive-the-talk/.env as ELEVENLABS_VOICE_ID=..."
        )

    logger.info(
        "TTS provider = elevenlabs (model={} voice_id={})",
        settings.elevenlabs_model,
        settings.elevenlabs_voice_id,
    )
    return ElevenLabsTTSService(
        api_key=settings.elevenlabs_api_key,
        settings=ElevenLabsTTSService.Settings(
            model=settings.elevenlabs_model,
            voice=settings.elevenlabs_voice_id,
        ),
    )
