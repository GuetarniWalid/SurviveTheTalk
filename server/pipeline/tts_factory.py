"""Story 6.13 Phase 4b (2026-05-26) — TTS provider factory.

Single branching point that builds the right TTS service from
`Settings.tts_provider`. Two providers are wired today:

- **Cartesia Sonic-3** (`tts_provider="cartesia"`) — the original
  provider. Lives behind `CARTESIA_INSTRUMENT` / `CARTESIA_FRESH_CTX`
  env-gated debug paths (see `pipeline/cartesia_instrumented.py`) so a
  future Cartesia investigation can be re-enabled instantly without a
  code release.
- **ElevenLabs Flash v2.5** (`tts_provider="elevenlabs"`) — added
  after Cartesia's multi-frame stall bug surfaced (call 156 +
  call 157 on Pixel 9 Pro XL, 2026-05-26). Chosen because of lower
  TTFA (~75 ms advertised vs ~300 ms for Cartesia) AND established
  reliability. We're not waiting for a Cartesia support reply before
  shipping — switching now and waiting for their answer in
  parallel; if they ship a fix later we can flip back via the env
  var alone.

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


def build_tts_service(settings: Settings) -> Any:
    """Return the configured TTS service instance.

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
        return _build_cartesia(settings)
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


def _build_cartesia(settings: Settings) -> Any:
    """Construct a Cartesia Sonic-3 service.

    Preserves the Story 6.13 investigation env-gates:

    - `CARTESIA_FRESH_CTX=1` → `FreshContextCartesiaTTSService` (the
      Option A fix attempt — multi-frame race mitigation via fresh
      context_id per sentence). NOT a real fix per the call 157 logs
      (Cartesia just queues the freezes differently) but kept as a
      research artifact for the Cartesia support thread.
    - `CARTESIA_INSTRUMENT=1` → `InstrumentedCartesiaTTSService`
      (verbose logging of every WS send/recv + audio context
      transition). Used during the freeze diagnostic phase.
    - Both unset → vanilla `CartesiaTTSService`. The Story 6.13 AC1
      watchdog (`pipeline/tts_watchdog.py`) is the always-on 5s
      safety net regardless of which subclass is selected.

    `tts_provider` is `"cartesia"` only when an operator explicitly
    selects it via env var — default is `"elevenlabs"`. This branch
    therefore stays around for rollback / Cartesia support
    reproduction but isn't the prod default.
    """
    if not settings.cartesia_api_key:
        raise RuntimeError(
            "TTS_PROVIDER=cartesia but CARTESIA_API_KEY is empty. "
            "Set it in /opt/survive-the-talk/.env or switch to "
            "TTS_PROVIDER=elevenlabs (the post-2026-05-26 default)."
        )

    tts_cls: type[CartesiaTTSService] = CartesiaTTSService
    if os.environ.get("CARTESIA_FRESH_CTX") == "1":
        from pipeline.cartesia_instrumented import FreshContextCartesiaTTSService

        tts_cls = FreshContextCartesiaTTSService
        logger.info("CARTESIA_FRESH_CTX=1 — using FreshContextCartesiaTTSService")
    elif os.environ.get("CARTESIA_INSTRUMENT") == "1":
        from pipeline.cartesia_instrumented import InstrumentedCartesiaTTSService

        tts_cls = InstrumentedCartesiaTTSService
        logger.info("CARTESIA_INSTRUMENT=1 — using InstrumentedCartesiaTTSService")

    logger.info("TTS provider = cartesia (Sonic-3)")
    return tts_cls(
        api_key=settings.cartesia_api_key,
        settings=CartesiaTTSService.Settings(
            model="sonic-3",
            voice=CARTESIA_VOICE_ID,
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
