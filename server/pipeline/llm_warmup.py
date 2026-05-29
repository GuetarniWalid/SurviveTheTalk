"""Story 6.13 follow-up (2026-05-27) — LLM connection warm-up.

Kills the turn-1 cold-start. Measured on call 164: the first user turn
had a 1.15 s LLM→TTS gap vs ~0.6 s on subsequent turns — a ~0.5 s
cold-start tax paid once per call. Root cause: the provider connection
(TCP + TLS handshake) and the provider-side model load are cold on the
LLM's first real inference. The hardcoded greeting ("Hi. Welcome to The
Golden Fork…") goes straight to TTS, so the LLM's FIRST inference is the
user's first-turn response — eating the full cold-start.

Fix: fire a tiny throwaway completion (max_tokens=1) to the provider
(Groq since 2026-05-29) at call start, in parallel with the LiveKit
connection + greeting playback. By the time the user finishes their first
turn (several seconds into the call), the connection is warm and the
model is loaded, so the real inference skips the cold-start.

Fire-and-forget: a warm-up failure (network blip, rate limit, timeout)
must NEVER break the call — it is a pure optimization. Every exception is
logged at DEBUG and swallowed. The warm-up uses its own short-lived
httpx client (the main LLM path is pipecat's OpenRouterLLMService, which
manages its own connection); the shared win is the provider-side model
warmth, which OpenRouter keeps hot for a short window after any request
to the model.
"""

from __future__ import annotations

import httpx
from loguru import logger

# 2026-05-29 all-Groq migration — warm the Groq connection (was OpenRouter).
_PROVIDER_URL = "https://api.groq.com/openai/v1/chat/completions"
_WARMUP_TIMEOUT_SECONDS = 5.0


async def warm_up_llm(api_key: str, model: str, base_url: str = _PROVIDER_URL) -> None:
    """Fire a minimal throwaway completion to warm the provider connection
    + provider-side model.

    Safe to launch fire-and-forget via `asyncio.create_task`. Never
    raises — all failures are logged at DEBUG and swallowed.

    Args:
        api_key: Provider API key (same as the main character LLM).
        model: Model id to warm (same as the main character LLM, e.g.
            ``llama-3.3-70b-versatile``) so the provider loads the exact
            model the real inference will hit.
        base_url: OpenAI-compatible chat-completions URL. Injectable (from
            `Settings.llm_base_url`) so a provider switch is an env change;
            defaults to Groq.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_WARMUP_TIMEOUT_SECONDS) as client:
            await client.post(base_url, headers=headers, json=payload)
        logger.info("llm_warmup: provider connection warmed (model={})", model)
    except Exception as exc:
        # Best-effort: a cold turn-1 is a minor UX nit, a crashed call
        # is not. Swallow everything.
        logger.debug("llm_warmup failed (non-fatal): {} ({})", exc, type(exc).__name__)
