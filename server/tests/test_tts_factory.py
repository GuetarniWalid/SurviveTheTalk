"""Story 6.13 Phase 4b — tests for `pipeline/tts_factory.build_tts_service`.

The factory is the single branching point between Cartesia and
ElevenLabs. These tests lock the contract:

- Default provider = ElevenLabs (post-2026-05-26 default after the
  Cartesia stall findings)
- Cartesia branch returns the right class based on
  `CARTESIA_INSTRUMENT` / `CARTESIA_FRESH_CTX` env gates
- Each branch raises a clear RuntimeError at process start if its
  required credentials / voice id are empty
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

from config import Settings
from pipeline.cartesia_instrumented import (
    FreshContextCartesiaTTSService,
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


def test_factory_returns_vanilla_cartesia_when_provider_is_cartesia_no_env_gate() -> (
    None
):
    """No CARTESIA_INSTRUMENT / CARTESIA_FRESH_CTX → vanilla service."""
    s = _build_settings(TTS_PROVIDER="cartesia")
    with patch.dict(os.environ, {}, clear=False):
        # Make sure no gate is leaking from the test runner env.
        for key in ("CARTESIA_INSTRUMENT", "CARTESIA_FRESH_CTX"):
            os.environ.pop(key, None)
        tts = build_tts_service(s)

    assert isinstance(tts, CartesiaTTSService)
    assert not isinstance(tts, InstrumentedCartesiaTTSService)


def test_factory_returns_instrumented_cartesia_when_CARTESIA_INSTRUMENT_set() -> None:
    s = _build_settings(TTS_PROVIDER="cartesia")
    with patch.dict(os.environ, {"CARTESIA_INSTRUMENT": "1"}, clear=False):
        # Belt-and-braces: clear FRESH_CTX so we test the INSTRUMENT-only branch.
        os.environ.pop("CARTESIA_FRESH_CTX", None)
        tts = build_tts_service(s)

    assert isinstance(tts, InstrumentedCartesiaTTSService)
    # Should NOT also be the FreshContext subclass.
    assert not isinstance(tts, FreshContextCartesiaTTSService)


def test_factory_returns_fresh_context_cartesia_when_CARTESIA_FRESH_CTX_set() -> None:
    """FRESH_CTX takes precedence over INSTRUMENT (FreshContext IS
    already instrumented via inheritance)."""
    s = _build_settings(TTS_PROVIDER="cartesia")
    with patch.dict(
        os.environ,
        {"CARTESIA_FRESH_CTX": "1", "CARTESIA_INSTRUMENT": "1"},
        clear=False,
    ):
        tts = build_tts_service(s)

    assert isinstance(tts, FreshContextCartesiaTTSService)


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


def test_factory_defaults_to_elevenlabs_provider_post_2026_05_26() -> None:
    """If no TTS_PROVIDER env var is set, Settings defaults to
    `elevenlabs` and the factory takes that branch — confirms the
    post-call-156-157 default is wired end-to-end."""
    s = _build_settings(
        ELEVENLABS_API_KEY="test-eleven-key",
        ELEVENLABS_VOICE_ID="Xb7hH8MSUJpSbSDYk0k2",
    )
    assert s.tts_provider == "elevenlabs"
    tts = build_tts_service(s)
    assert isinstance(tts, ElevenLabsTTSService)
