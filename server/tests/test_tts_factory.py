"""Story 6.13 Phase 4b — tests for `pipeline/tts_factory.build_tts_service`.

The factory is the single branching point between Cartesia and
ElevenLabs. These tests lock the contract:

- Default provider = Cartesia (Story 6.14 reversal — smoother under
  jitter; the 2026-05-26 freeze was a resolved Cartesia incident)
- Cartesia branch returns the always-on `ErrorLoggingCartesiaTTSService`
  by default, or `InstrumentedCartesiaTTSService` under `CARTESIA_INSTRUMENT`
- Each branch raises a clear RuntimeError at process start if its
  required credentials / voice id are empty
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

from config import Settings
from pipeline.cartesia_instrumented import (
    ErrorLoggingCartesiaTTSService,
    InstrumentedCartesiaTTSService,
)
from pipeline.tts_factory import build_tts_service


_BASE_ENV = {
    "SONIOX_API_KEY": "test-soniox",
    "OPENROUTER_API_KEY": "test-openrouter",
    "CARTESIA_API_KEY": "test-cartesia",
    "LIVEKIT_URL": "wss://livekit.example.com",
    "LIVEKIT_API_KEY": "test-lk-key",
    "LIVEKIT_API_SECRET": "test-lk-secret",
    "GROQ_API_KEY": "test-groq",
    "JWT_SECRET": "0" * 32,
}


def _build_settings(**extra: str) -> Settings:
    env = {**_BASE_ENV, **extra}
    with patch.dict(os.environ, env, clear=True):
        return Settings(_env_file=None)  # type: ignore[call-arg]


# ---------- Cartesia branch ----------


def test_factory_returns_error_logging_cartesia_when_no_env_gate() -> None:
    """No CARTESIA_INSTRUMENT → always-on `ErrorLoggingCartesiaTTSService`
    (surfaces Cartesia's documented `type=error` schema), NOT the verbose
    instrumented sibling."""
    s = _build_settings(TTS_PROVIDER="cartesia")
    with patch.dict(os.environ, {}, clear=False):
        # Make sure no gate is leaking from the test runner env.
        os.environ.pop("CARTESIA_INSTRUMENT", None)
        tts = build_tts_service(s)

    assert isinstance(tts, ErrorLoggingCartesiaTTSService)
    assert not isinstance(tts, InstrumentedCartesiaTTSService)


def test_factory_returns_instrumented_cartesia_when_CARTESIA_INSTRUMENT_set() -> None:
    s = _build_settings(TTS_PROVIDER="cartesia")
    with patch.dict(os.environ, {"CARTESIA_INSTRUMENT": "1"}, clear=False):
        tts = build_tts_service(s)

    assert isinstance(tts, InstrumentedCartesiaTTSService)
    # Sibling, not subclass — the verbose service is distinct from the
    # always-on error-logging default.
    assert not isinstance(tts, ErrorLoggingCartesiaTTSService)


def test_factory_raises_when_cartesia_selected_but_api_key_empty() -> None:
    """Loud at process start; better than 401-on-first-call."""
    # Override CARTESIA_API_KEY to empty via Settings construction.
    env = {**_BASE_ENV, "TTS_PROVIDER": "cartesia", "CARTESIA_API_KEY": ""}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]

    with pytest.raises(RuntimeError, match="CARTESIA_API_KEY is empty"):
        build_tts_service(s)


# ---------- ElevenLabs branch ----------


def test_factory_returns_elevenlabs_when_provider_is_elevenlabs() -> None:
    s = _build_settings(
        TTS_PROVIDER="elevenlabs",
        ELEVENLABS_API_KEY="test-eleven-key",
        ELEVENLABS_VOICE_ID="Xb7hH8MSUJpSbSDYk0k2",
    )
    tts = build_tts_service(s)
    assert isinstance(tts, ElevenLabsTTSService)


def test_factory_raises_when_elevenlabs_selected_but_api_key_empty() -> None:
    s = _build_settings(
        TTS_PROVIDER="elevenlabs",
        ELEVENLABS_VOICE_ID="Xb7hH8MSUJpSbSDYk0k2",
    )
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY is empty"):
        build_tts_service(s)


def test_factory_raises_when_elevenlabs_selected_but_voice_id_empty() -> None:
    s = _build_settings(
        TTS_PROVIDER="elevenlabs",
        ELEVENLABS_API_KEY="test-eleven-key",
    )
    with pytest.raises(RuntimeError, match="ELEVENLABS_VOICE_ID is empty"):
        build_tts_service(s)


# ---------- Default behaviour ----------


def test_factory_defaults_to_cartesia_provider() -> None:
    """Story 6.14 reversal — if no TTS_PROVIDER env var is set, Settings
    defaults to `cartesia` and the factory builds the always-on
    error-logging Cartesia service. Confirms the launch default is wired
    end-to-end."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("CARTESIA_INSTRUMENT", None)
        s = _build_settings()
        assert s.tts_provider == "cartesia"
        tts = build_tts_service(s)
    assert isinstance(tts, ErrorLoggingCartesiaTTSService)
