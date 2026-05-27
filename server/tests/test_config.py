"""Tests for server configuration."""

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from config import Settings


def test_settings_class_exists() -> None:
    assert Settings is not None


REQUIRED_ENV_VARS = {
    "SONIOX_API_KEY": "test-soniox-key",
    "OPENROUTER_API_KEY": "test-openrouter-key",
    "CARTESIA_API_KEY": "test-cartesia-key",
    "LIVEKIT_URL": "wss://livekit.example.com",
    "LIVEKIT_API_KEY": "test-lk-key",
    "LIVEKIT_API_SECRET": "test-lk-secret",
    # Story 6.9b — required since the classifier migrated to Groq.
    "GROQ_API_KEY": "test-groq-key",
}


def test_settings_loads_all_pipeline_env_vars() -> None:
    with patch.dict(os.environ, REQUIRED_ENV_VARS, clear=False):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.soniox_api_key == "test-soniox-key"
        assert s.openrouter_api_key == "test-openrouter-key"
        assert s.cartesia_api_key == "test-cartesia-key"
        assert s.livekit_url == "wss://livekit.example.com"
        assert s.livekit_api_key == "test-lk-key"
        assert s.livekit_api_secret == "test-lk-secret"
        assert s.groq_api_key == "test-groq-key"


def test_settings_fails_without_required_vars() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]


# ---------- Story 6.9b — Classifier model id sourced from Settings --------


def test_settings_classifier_model_defaults_to_groq_70b() -> None:
    """Story 6.9b — `classifier_model` defaults to the post-migration
    Groq Llama 3.3 70B winner (2026-05-22 bench). The default is what
    the prod VPS uses when `CLASSIFIER_MODEL` is unset. A future bench
    that points elsewhere would update both this default AND the
    `groq_api_key` provider field (or rename to `classifier_api_key`).

    Story 6.9b review P2 — `clear=True` so a developer's shell with
    `CLASSIFIER_MODEL` exported (e.g. left over from a benchmark run)
    doesn't shadow the default and make the test silently fail.
    """
    env = {**REQUIRED_ENV_VARS, "JWT_SECRET": "0" * 32}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.classifier_model == "llama-3.3-70b-versatile"


def test_settings_classifier_model_overrides_via_env() -> None:
    """Story 6.9b — `CLASSIFIER_MODEL` env override lets the operator
    pin a specific Groq model snapshot at deploy time without a code
    release. NOT a Qwen rollback path — see Story 6.9b review D2 +
    `server/CLAUDE.md` §4: a Qwen rollback requires redeploying an
    earlier release because `_PROVIDER_URL` is hardcoded to Groq.

    Story 6.9b review P2 — `clear=True` for the same hermetic-env
    reason as the default test above.
    """
    overrides = {
        **REQUIRED_ENV_VARS,
        "JWT_SECRET": "0" * 32,
        "CLASSIFIER_MODEL": "llama-3.3-70b-versatile-128k",
    }
    with patch.dict(os.environ, overrides, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.classifier_model == "llama-3.3-70b-versatile-128k"


# ---------- Story 6.13 Phase 4b — TTS provider switch -----------------------


def test_settings_tts_provider_defaults_to_elevenlabs() -> None:
    """Story 6.13 Phase 4b — post-2026-05-26 default is ElevenLabs.
    Cartesia stays in the codebase for rollback but the production
    default after the call 156-157 freeze findings is ElevenLabs."""
    env = {**REQUIRED_ENV_VARS, "JWT_SECRET": "0" * 32}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.tts_provider == "elevenlabs"


def test_settings_tts_provider_can_be_flipped_to_cartesia() -> None:
    """Operator can switch back to Cartesia via env var alone (no
    code release). Used for rollback once Cartesia ships a fix."""
    overrides = {
        **REQUIRED_ENV_VARS,
        "JWT_SECRET": "0" * 32,
        "TTS_PROVIDER": "cartesia",
    }
    with patch.dict(os.environ, overrides, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.tts_provider == "cartesia"


def test_settings_rejects_unknown_tts_provider() -> None:
    """The `Literal["cartesia", "elevenlabs"]` type makes any other
    value fail at parse — `Settings()` raises ValidationError instead
    of accepting a misconfigured value that would 500 at first call."""
    overrides = {
        **REQUIRED_ENV_VARS,
        "JWT_SECRET": "0" * 32,
        "TTS_PROVIDER": "openai",
    }
    with patch.dict(os.environ, overrides, clear=True):
        with pytest.raises(ValidationError, match="tts_provider"):
            Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_elevenlabs_fields_default_empty_when_unset() -> None:
    """Cartesia-only deploys (no ELEVENLABS_* env vars) must still
    parse Settings cleanly — runtime validation in `tts_factory`
    enforces non-empty values only when the provider is selected."""
    env = {**REQUIRED_ENV_VARS, "JWT_SECRET": "0" * 32}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.elevenlabs_api_key == ""
        assert s.elevenlabs_voice_id == ""
        assert s.elevenlabs_model == "eleven_flash_v2_5"


def test_settings_elevenlabs_fields_load_from_env() -> None:
    """ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID + ELEVENLABS_MODEL
    env overrides propagate to Settings."""
    overrides = {
        **REQUIRED_ENV_VARS,
        "JWT_SECRET": "0" * 32,
        "ELEVENLABS_API_KEY": "test-elevenlabs-key",
        "ELEVENLABS_VOICE_ID": "Xb7hH8MSUJpSbSDYk0k2",  # Alice
        "ELEVENLABS_MODEL": "eleven_turbo_v2_5",
    }
    with patch.dict(os.environ, overrides, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.elevenlabs_api_key == "test-elevenlabs-key"
        assert s.elevenlabs_voice_id == "Xb7hH8MSUJpSbSDYk0k2"
        assert s.elevenlabs_model == "eleven_turbo_v2_5"
