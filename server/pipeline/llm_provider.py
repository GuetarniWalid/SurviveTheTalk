"""2026-05-29 — single OpenAI-compatible LLM provider switch point.

Every LLM call in the pipeline — the character brain (`bot.py`), the
emotion classifier (`EmotionEmitter`), the checkpoint judge
(`ExchangeClassifier`), and the turn-1 warm-up (`llm_warmup`) — hits ONE
provider, configured by `Settings.llm_base_url` + a resolved key. No call
site hardcodes `api.groq.com` anymore.

This mirrors `tts_factory.py`: to switch the LLM provider tomorrow (a
cheaper/newer model, or off Groq entirely), set `LLM_BASE_URL` +
`LLM_API_KEY` (and the per-role `CHARACTER_MODEL` / `EMOTION_MODEL` /
`CLASSIFIER_MODEL`) in the env and restart — ZERO code change. This works
because every provider we'd realistically use (Groq, OpenRouter,
DashScope, OpenAI, Together, Fireworks, …) speaks the same
OpenAI-compatible chat-completions format, so only the base_url + key +
model differ. A genuinely different API shape (e.g. Anthropic/Gemini
native) would still need code — but those are the exception today.

Deliberately ONE provider for all roles (not per-role provider configs).
That's the right "simple" for now; if a future need arises to split (e.g.
judge on Groq, character on OpenAI), extend `resolve_*` to take a role.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pipecat.services.openai.llm import OpenAILLMService

if TYPE_CHECKING:
    from config import Settings


# Character-LLM generation parameters. Module-level constants (NOT inlined in
# `build_main_llm`) so the Story 6.15 calibration harness — which drives a
# single character reply via the raw `openai` SDK because `OpenAILLMService`
# is pipeline-only (Story 6.15 Deviation #1) — uses the EXACT same numbers as
# prod. A drift here would make the harness validate a slightly different
# character than the one users talk to.
CHARACTER_TEMPERATURE = 0.7
CHARACTER_MAX_TOKENS = 256


def resolve_llm_base_url(settings: Settings) -> str:
    """The OpenAI-compatible BASE url (e.g. `…/openai/v1`).

    For `OpenAILLMService` / the `openai` SDK, which appends the
    `/chat/completions` path itself. The raw-httpx call sites (classifier,
    emotion, warm-up) must NOT use this directly — they POST to a full
    endpoint, so they use `resolve_llm_chat_url` below. Conflating the two
    was the 2026-05-29 checkpoints-404 regression.
    """
    return settings.llm_base_url


def resolve_llm_chat_url(settings: Settings) -> str:
    """The full chat-completions endpoint (`{base}/chat/completions`).

    For the raw-httpx call sites (`ExchangeClassifier`, `EmotionEmitter`,
    `llm_warmup`) which POST directly and need the complete URL — the
    `openai` SDK appends `/chat/completions` on its own, raw httpx does not.
    """
    return settings.llm_base_url.rstrip("/") + "/chat/completions"


def resolve_llm_api_key(settings: Settings) -> str:
    """The provider key for every LLM call.

    `LLM_API_KEY` wins when set (a deliberate provider switch); otherwise
    we fall back to `GROQ_API_KEY` so today's Groq-only deploys keep
    working without touching the `.env`.
    """
    return settings.llm_api_key or settings.groq_api_key


def build_main_llm(settings: Settings, *, system_instruction: str) -> OpenAILLMService:
    """Build the main character LLM service.

    `OpenAILLMService` (the already-present `openai` SDK) pointed at the
    configured base_url — NOT pipecat's `GroqLLMService`, whose package
    `__init__` imports `groq.tts` which hard-requires the uninstalled
    `groq` SDK (`pipecat-ai[groq]`). `_settings.system_instruction` is the
    attribute `CheckpointManager` mutates on every goal flip (Deviation #2).
    """
    return OpenAILLMService(
        api_key=resolve_llm_api_key(settings),
        base_url=resolve_llm_base_url(settings),
        settings=OpenAILLMService.Settings(
            model=settings.character_model,
            system_instruction=system_instruction,
            temperature=CHARACTER_TEMPERATURE,
            max_tokens=CHARACTER_MAX_TOKENS,
        ),
    )
