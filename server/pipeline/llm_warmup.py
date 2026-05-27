"""Story 6.13 follow-up (2026-05-27) — LLM connection warm-up.

Kills the turn-1 cold-start. Measured on call 164: the first user turn
had a 1.15 s LLM→TTS gap vs ~0.6 s on subsequent turns — a ~0.5 s
cold-start tax paid once per call. Root cause: the OpenRouter connection
(TCP + TLS handshake) and the provider-side model load are cold on the
LLM's first real inference. The hardcoded greeting ("Hi. Welcome to The
Golden Fork…") goes straight to TTS, so the LLM's FIRST inference is the
user's first-turn response — eating the full cold-start.

Fix: fire a tiny throwaway completion (max_tokens=1) to OpenRouter at
call start, in parallel with the LiveKit connection + greeting playback.
By the time the user finishes their first turn (several seconds into the
call), the connection is warm and OpenRouter has routed + loaded the
model, so the real inference skips the cold-start.

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

_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_WARMUP_TIMEOUT_SECONDS = 5.0


async def warm_up_llm(api_key: str, model: str) -> None:
    """Fire a minimal throwaway completion to warm the OpenRouter
    connection + provider-side model.

    Safe to launch fire-and-forget via `asyncio.create_task`. Never
    raises — all failures are logged at DEBUG and swallowed.

    Args:
        api_key: OpenRouter API key (same as the main character LLM).
        model: Model id to warm (same as the main character LLM, e.g.
            ``qwen/qwen3.5-flash-02-23``) so the provider loads the
            exact model the real inference will hit.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        # Mirror the main LLM's reasoning-disabled flag so the warmed
        # model variant matches the real request path.
        "reasoning": {"enabled": False},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=_WARMUP_TIMEOUT_SECONDS) as client:
            await client.post(_OPENROUTER_URL, headers=headers, json=payload)
        logger.info("llm_warmup: OpenRouter connection warmed (model={})", model)
    except Exception as exc:
        # Best-effort: a cold turn-1 is a minor UX nit, a crashed call
        # is not. Swallow everything.
        logger.debug("llm_warmup failed (non-fatal): {} ({})", exc, type(exc).__name__)
