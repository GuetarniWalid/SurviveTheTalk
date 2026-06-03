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


def test_settings_classifier_model_defaults_to_scout() -> None:
    """2026-05-29 — `classifier_model` defaults to Llama 4 Scout. The
    multi-goal judge uses Groq STRICT structured outputs
    (`response_format=json_schema`), which 70B does NOT support (HTTP 400);
    Scout does. The default is what the prod VPS uses when `CLASSIFIER_MODEL`
    is unset and MUST stay a structured-output-capable Groq model (see
    `config.Settings.classifier_model` + `server/CLAUDE.md` §4).

    Story 6.9b review P2 — `clear=True` so a developer's shell with
    `CLASSIFIER_MODEL` exported (e.g. left over from a benchmark run)
    doesn't shadow the default and make the test silently fail.
    """
    env = {**REQUIRED_ENV_VARS, "JWT_SECRET": "0" * 32}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.classifier_model == "meta-llama/llama-4-scout-17b-16e-instruct"


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


# ---------- 2026-05-29 all-Groq migration — character + emotion models -----


def test_settings_character_and_emotion_models_default_to_groq() -> None:
    """The all-Groq migration moved the main character LLM + EmotionEmitter
    off Qwen/OpenRouter onto Groq. Both model ids default to the model we
    already trust in prod and are env-overridable (CHARACTER_MODEL /
    EMOTION_MODEL) for a future tuning pass. `clear=True` for a hermetic
    env (a stray CHARACTER_MODEL in the dev shell mustn't shadow)."""
    env = {**REQUIRED_ENV_VARS, "JWT_SECRET": "0" * 32}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.character_model == "llama-3.3-70b-versatile"
        assert s.emotion_model == "llama-3.3-70b-versatile"


def test_settings_character_and_emotion_models_override_via_env() -> None:
    overrides = {
        **REQUIRED_ENV_VARS,
        "JWT_SECRET": "0" * 32,
        "CHARACTER_MODEL": "llama-3.1-8b-instant",
        "EMOTION_MODEL": "llama-3.1-8b-instant",
    }
    with patch.dict(os.environ, overrides, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.character_model == "llama-3.1-8b-instant"
        assert s.emotion_model == "llama-3.1-8b-instant"


def test_settings_llm_provider_defaults_to_groq() -> None:
    """The single LLM provider switch defaults to Groq; llm_api_key empty
    (the resolver falls back to groq_api_key)."""
    env = {**REQUIRED_ENV_VARS, "JWT_SECRET": "0" * 32}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.llm_base_url == "https://api.groq.com/openai/v1"
        assert s.llm_api_key == ""


def test_settings_llm_provider_override_via_env() -> None:
    """Switching provider tomorrow = LLM_BASE_URL + LLM_API_KEY env, no code.

    NOTE — `LLM_BASE_URL` is the OpenAI-compatible BASE url (ends at
    `/v1`), NOT a full chat-completions endpoint. `resolve_llm_chat_url`
    appends `/chat/completions` and `OpenAILLMService` appends it too, so
    a full-endpoint value here would double-append → 404 (the 2026-05-29
    checkpoints-404 regression). See `pipeline/llm_provider.py` docstrings.
    """
    overrides = {
        **REQUIRED_ENV_VARS,
        "JWT_SECRET": "0" * 32,
        "LLM_BASE_URL": "https://openrouter.ai/api/v1",
        "LLM_API_KEY": "or-key",
    }
    with patch.dict(os.environ, overrides, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.llm_base_url == "https://openrouter.ai/api/v1"
        assert s.llm_api_key == "or-key"


def test_settings_boots_without_openrouter_key() -> None:
    """Post all-Groq migration, OPENROUTER_API_KEY is optional (legacy).
    Settings must parse cleanly when it's absent."""
    env = {k: v for k, v in REQUIRED_ENV_VARS.items() if k != "OPENROUTER_API_KEY"}
    env["JWT_SECRET"] = "0" * 32
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.openrouter_api_key == ""
        assert s.groq_api_key == "test-groq-key"


# ---------- Story 6.18 — dynamic exit/warning-line generation toggle --------


def test_settings_hangup_line_generation_defaults_to_on() -> None:
    """Story 6.18 — dynamic exit/patience-warning line generation is ON by
    default (Walid decision). bot.py only injects the generator into
    PatienceTracker when this is True."""
    env = {**REQUIRED_ENV_VARS, "JWT_SECRET": "0" * 32}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.hangup_line_generation is True


def test_settings_hangup_line_generation_kill_switch_via_env() -> None:
    """AC7 — `HANGUP_LINE_GENERATION=0` flips the whole feature back to the
    canned YAML exit_lines with no logic redeploy."""
    overrides = {
        **REQUIRED_ENV_VARS,
        "JWT_SECRET": "0" * 32,
        "HANGUP_LINE_GENERATION": "0",
    }
    with patch.dict(os.environ, overrides, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.hangup_line_generation is False


# ---------- Story 6.13 Phase 4b — TTS provider switch -----------------------


def test_settings_tts_provider_defaults_to_cartesia() -> None:
    """Story 6.14 (2026-05-30) — DIRECTION REVERSAL: the default is now
    Cartesia (was ElevenLabs since 2026-05-26). Cartesia's smaller frames
    play smoother under network jitter (Walid on-device A/B) and the
    2026-05-26 freeze was a resolved Cartesia platform incident.
    ElevenLabs stays in the codebase as the last-resort fallback."""
    env = {**REQUIRED_ENV_VARS, "JWT_SECRET": "0" * 32}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.tts_provider == "cartesia"


def test_settings_tts_provider_can_be_flipped_to_elevenlabs() -> None:
    """Operator can switch to ElevenLabs via env var alone (no code
    release) — the last-resort fallback until the jitter buffer makes
    its larger frames viable again."""
    overrides = {
        **REQUIRED_ENV_VARS,
        "JWT_SECRET": "0" * 32,
        "TTS_PROVIDER": "elevenlabs",
    }
    with patch.dict(os.environ, overrides, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.tts_provider == "elevenlabs"


# ---------- Story 6.14 AC2 — LiveKit min playout delay (jitter buffer) -------


def test_settings_min_playout_delay_defaults_to_200ms() -> None:
    """Story 6.14 AC2 — the server-side jitter buffer knob defaults to
    200 ms: a starting point inside the spec's 150-400 ms candidate band,
    well under the 2 s PRD perceived-latency ceiling. Tuned empirically
    on the Pixel 9 smoke gate; env-overridable for retune without a code
    release."""
    env = {**REQUIRED_ENV_VARS, "JWT_SECRET": "0" * 32}
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.livekit_min_playout_delay_ms == 200


def test_settings_min_playout_delay_overrides_via_env() -> None:
    """`LIVEKIT_MIN_PLAYOUT_DELAY_MS` lets an operator retune the jitter
    buffer (or set 0 to disable it) at deploy time without a code release."""
    overrides = {
        **REQUIRED_ENV_VARS,
        "JWT_SECRET": "0" * 32,
        "LIVEKIT_MIN_PLAYOUT_DELAY_MS": "350",
    }
    with patch.dict(os.environ, overrides, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.livekit_min_playout_delay_ms == 350


def test_settings_min_playout_delay_zero_disables_buffer() -> None:
    """`LIVEKIT_MIN_PLAYOUT_DELAY_MS=0` is the documented rollback — it
    parses cleanly to 0 (no room config attached at the token layer)."""
    overrides = {
        **REQUIRED_ENV_VARS,
        "JWT_SECRET": "0" * 32,
        "LIVEKIT_MIN_PLAYOUT_DELAY_MS": "0",
    }
    with patch.dict(os.environ, overrides, clear=True):
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.livekit_min_playout_delay_ms == 0


def test_settings_rejects_negative_min_playout_delay() -> None:
    """Story 6.14 review — a negative jitter-buffer value is rejected at
    boot (fail-loud) instead of silently producing a bad room config."""
    overrides = {
        **REQUIRED_ENV_VARS,
        "JWT_SECRET": "0" * 32,
        "LIVEKIT_MIN_PLAYOUT_DELAY_MS": "-1",
    }
    with patch.dict(os.environ, overrides, clear=True):
        with pytest.raises(ValidationError, match="LIVEKIT_MIN_PLAYOUT_DELAY_MS"):
            Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_rejects_min_playout_delay_above_prd_ceiling() -> None:
    """Story 6.14 review — a value past the PRD 2 s perceived-latency
    ceiling is rejected at process start. Without this guard an over-large
    value would either overflow the protobuf int32 (→ 502 on every call)
    or silently breach the latency kill-criterion."""
    overrides = {
        **REQUIRED_ENV_VARS,
        "JWT_SECRET": "0" * 32,
        "LIVEKIT_MIN_PLAYOUT_DELAY_MS": "2001",
    }
    with patch.dict(os.environ, overrides, clear=True):
        with pytest.raises(ValidationError, match="LIVEKIT_MIN_PLAYOUT_DELAY_MS"):
            Settings(_env_file=None)  # type: ignore[call-arg]


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
