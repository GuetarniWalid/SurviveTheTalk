"""2026-05-29 — tests for the LLM provider switch point.

`pipeline/llm_provider.py` is the single place that decides which
OpenAI-compatible provider every LLM call hits. These lock in the
resolution rules (env override vs groq fallback) + that `build_main_llm`
wires the resolved provider/model/system_instruction onto the service.
"""

from __future__ import annotations

from types import SimpleNamespace

from pipecat.services.openai.llm import OpenAILLMService

from pipeline.llm_provider import (
    build_main_llm,
    resolve_llm_api_key,
    resolve_llm_base_url,
    resolve_llm_chat_url,
)


def _settings(**overrides):
    base = dict(
        llm_base_url="https://api.groq.com/openai/v1",
        llm_api_key="",
        groq_api_key="groq-key",
        character_model="llama-3.3-70b-versatile",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_resolve_base_url_returns_settings_value() -> None:
    assert (
        resolve_llm_base_url(_settings(llm_base_url="https://example/v1"))
        == "https://example/v1"
    )


def test_resolve_chat_url_appends_chat_completions() -> None:
    """Regression guard for the 2026-05-29 checkpoints-404 bug: the
    raw-httpx call sites need the FULL chat-completions endpoint, not the
    base url (the openai SDK appends the path itself, raw httpx does not)."""
    assert (
        resolve_llm_chat_url(_settings(llm_base_url="https://api.groq.com/openai/v1"))
        == "https://api.groq.com/openai/v1/chat/completions"
    )
    # Tolerates a trailing slash on the configured base.
    assert (
        resolve_llm_chat_url(_settings(llm_base_url="https://api.groq.com/openai/v1/"))
        == "https://api.groq.com/openai/v1/chat/completions"
    )


def test_resolve_base_url_has_no_chat_completions_suffix() -> None:
    """The base (for OpenAILLMService) must NOT carry the path — the SDK
    appends it; a doubled `/chat/completions` would 404."""
    base = resolve_llm_base_url(
        _settings(llm_base_url="https://api.groq.com/openai/v1")
    )
    assert base == "https://api.groq.com/openai/v1"
    assert "chat/completions" not in base


def test_resolve_api_key_falls_back_to_groq_when_llm_key_empty() -> None:
    """Today's GROQ_API_KEY-only deploys keep working: empty LLM_API_KEY
    falls back to groq_api_key."""
    assert resolve_llm_api_key(_settings(llm_api_key="", groq_api_key="g")) == "g"


def test_resolve_api_key_override_wins() -> None:
    """A deliberate provider switch (LLM_API_KEY set) overrides the
    groq fallback."""
    assert (
        resolve_llm_api_key(_settings(llm_api_key="override", groq_api_key="g"))
        == "override"
    )


def test_build_main_llm_wires_model_and_system_instruction() -> None:
    llm = build_main_llm(
        _settings(character_model="some-model"), system_instruction="SYSTEM"
    )
    assert isinstance(llm, OpenAILLMService)
    # `_settings.system_instruction` is the attribute CheckpointManager
    # mutates on every goal flip — it MUST be present + carry our value.
    assert llm._settings.system_instruction == "SYSTEM"
    assert llm._settings.model == "some-model"
