"""Story 6.24 — Cartesia TTS connection warm-up.

Kills the turn-1 TTS cold-start. The canned opening line is the call's FIRST
synthesis (`bot.py::on_first_participant_joined` queues a `TTSSpeakFrame`), so it
pays the full Cartesia cold-start: the provider must load the `sonic-3` model +
the specific voice UUID and route the edge for our key on the first inference. On
a cold edge that can take ~5 s — long enough to trip the 5 s `TTSWatchdog` and
emit total silence (call_id=226, 2026-06-05).

Fix (mirrors `llm_warmup.py`): fire ONE throwaway one-shot synthesis to Cartesia's
REST `/tts/bytes` endpoint at call start, in parallel with the LiveKit connect +
greeting. By the time the opening `TTSSpeakFrame` is sent a few seconds later, the
`sonic-3` model + the resolved voice are hot provider-side. The pipecat WS (opened
on the `StartFrame`) is NOT the cold part — the first model+voice inference is, and
that is exactly what this pre-loads. The HTTP `/tts/bytes` ping and the live WS
`/tts/websocket` path share the same server-side model+voice, so warming one warms
the other (same accepted-win caveat as `llm_warmup.py`).

This replays pipecat's OWN `CartesiaHttpTTSService.run_tts` call shape (endpoint,
`Cartesia-Version: 2026-03-01` — the REST surface version, distinct from the WS
path's `2025-04-16`; both hit the same model backend — headers, and body), so it
is guaranteed to hit a real, working endpoint.

Fire-and-forget: a warm-up failure (network blip, rate limit, timeout, non-2xx)
must NEVER break the call — it is a pure optimization. Every exception is logged at
DEBUG and swallowed. It uses its own short-lived httpx client. The `TTSWatchdog`
(5 s) remains the real safety net for a genuine stall; this warm-up REDUCES how
often it fires, it does not replace it.
"""

from __future__ import annotations

import httpx
from loguru import logger

# Cartesia REST one-shot synthesis endpoint (same as pipecat's
# CartesiaHttpTTSService). The WS path the call actually speaks on uses
# `wss://api.cartesia.ai/tts/websocket`; this HTTP ping warms the shared
# server-side model+voice, not the socket.
_CARTESIA_TTS_BYTES_URL = "https://api.cartesia.ai/tts/bytes"
# REST API surface version (NOT the WS path's 2025-04-16 — independently
# versioned, same backend). Matches pipecat's CartesiaHttpTTSService default.
_CARTESIA_REST_VERSION = "2026-03-01"
# Slightly above the LLM warm-up's 5 s: a COLD sonic-3 synthesis is exactly the
# multi-second op we are paying down (call_id=226 cold synth ~5 s). Harmless to
# wait longer — it is fire-and-forget in the background.
_WARMUP_TIMEOUT_SECONDS = 8.0


async def warm_up_tts_cartesia(*, api_key: str, model: str, voice_id: str) -> None:
    """Fire a minimal throwaway Cartesia synthesis to warm the provider-side
    model + voice (and the edge/TLS path) before the opening line is spoken.

    Safe to launch fire-and-forget via `asyncio.create_task`. Never raises — all
    failures are logged at DEBUG and swallowed.

    Args:
        api_key: Cartesia API key (same `sk_car_...` the live WS path uses).
        model: Cartesia model id to warm — pass the SAME one the call speaks
            with (``sonic-3``, from `tts_factory._build_cartesia`).
        voice_id: The RESOLVED voice id (via `tts_factory.resolve_cartesia_voice`)
            so the warmed voice is exactly the spoken voice (no drift).
    """
    payload = {
        "model_id": model,
        "transcript": "Hi.",
        "voice": {"mode": "id", "id": voice_id},
        # Matches the WS path defaults (raw / pcm_s16le / 24 kHz). Non-load-
        # bearing for warm-up (model+voice load dominates; sample_rate only
        # affects the transcode stage) — hardcoded to avoid StartFrame ordering
        # coupling.
        "output_format": {
            "container": "raw",
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
        },
    }
    headers = {
        "Cartesia-Version": _CARTESIA_REST_VERSION,
        "X-API-Key": api_key,
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_WARMUP_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _CARTESIA_TTS_BYTES_URL, headers=headers, json=payload
            )
        # httpx does NOT raise on 4xx/5xx — a non-2xx means the synthesis never
        # ran, so NOTHING was warmed and the opening line still pays the cold-
        # start. Only emit the success breadcrumb on 200 (AC7's journalctl grep
        # of `tts_warmup` must not report a phantom warm-up); surface a non-2xx
        # at WARNING with the status so a swallowed 401/429 is visible to ops.
        if response.status_code == 200:
            logger.info(
                "tts_warmup: cartesia warmed (model={} voice={})", model, voice_id
            )
        else:
            logger.warning(
                "tts_warmup: cartesia warm-up returned HTTP {} — nothing warmed "
                "(model={} voice={})",
                response.status_code,
                model,
                voice_id,
            )
    except Exception as exc:
        # Best-effort: a cold/stalled turn-1 utterance is a UX nit; a crashed
        # call is not. Swallow everything (same contract as llm_warmup).
        logger.debug("tts_warmup failed (non-fatal): {} ({})", exc, type(exc).__name__)
