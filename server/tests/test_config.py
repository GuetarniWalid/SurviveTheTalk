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


def test_settings_fails_without_required_vars() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]
