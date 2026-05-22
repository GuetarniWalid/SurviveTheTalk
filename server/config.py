"""Server configuration loaded from environment / .env."""

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Runtime environment ("development" | "test" | "production").
    # Declared first so the jwt_secret validator can read it from info.data.
    environment: str = "development"

    # Pipeline (Pipecat / LiveKit / AI services)
    soniox_api_key: str
    # `openrouter_api_key` is STILL REQUIRED after Story 6.9b — the
    # classifier moved to Groq but EmotionEmitter + the main character
    # LLM (`OpenRouterLLMService` in `bot.py`) both still read this key.
    # Removing it from `/opt/survive-the-talk/.env` thinking "we migrated"
    # will fail boot. See the `groq_api_key` field below for the split.
    openrouter_api_key: str
    cartesia_api_key: str
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # Story 6.9b — Classifier provider migration (2026-05-22). Post-bench
    # verdict landed on Groq Llama 3.3 70B over Qwen via OpenRouter on the
    # 75-sample corpus: p50 121 ms vs 587 ms (4.8× faster), p95 320 ms vs
    # 859 ms (2.7× faster), 98.7 % vs 94.7 % accuracy, 0 false positives
    # vs 3. Full report at `_bmad-output/implementation-artifacts/
    # calibration-tests/classifier_benchmark_2026-05-22T09-29-19Z.json`.
    # `openrouter_api_key` above stays in use by EmotionEmitter (still on
    # Qwen — emotion latency has zero UX cost when slow, so the migration
    # was scoped to the exchange classifier only).
    groq_api_key: str

    # Auth
    jwt_secret: str = ""
    resend_api_key: str = ""
    resend_from_email: str = "noreply@survivethetalk.com"
    resend_from_name: str = "surviveTheTalk"

    # Database
    database_path: str = "/opt/survive-the-talk/data/db.sqlite"

    # Story 6.9b — Classifier model id sourced from env so we can pin a
    # specific Groq model snapshot (e.g. `llama-3.3-70b-versatile-128k`)
    # at deploy time without a code release. Default is the Story 6.9b
    # benchmark winner (Groq Llama 3.3 70B) — see the `groq_api_key`
    # field above for the empirical rationale. Retires `deferred-work.md`
    # line 450 (Story 6.9 Defer #3, hardcoded model id).
    #
    # NOT a Qwen rollback knob — the provider URL is hardcoded to Groq
    # in `pipeline/exchange_classifier.py:_PROVIDER_URL`. Flipping
    # `CLASSIFIER_MODEL=qwen/...` alone will post a Qwen model id to
    # `api.groq.com` and 404. A real rollback to OpenRouter+Qwen
    # requires redeploying an earlier release. Story 6.9b review D2.
    classifier_model: str = "llama-3.3-70b-versatile"

    # Story 6.9b — `extra: "ignore"` so unrelated env vars don't trip the
    # default Pydantic-v2 forbid-extras rule at Settings() construction.
    #
    # Threat model: this RELAXES validation — typos like `OPENROUER_API_KEY`
    # (missing T) are now silently ignored instead of raising
    # ValidationError. The mitigation is the test suite:
    # `tests/test_config.py::test_settings_loads_all_pipeline_env_vars`
    # explicitly asserts each declared field is present + correct, so a
    # typo'd env var would surface as a *missing* required field rather
    # than as an unknown-extra error. Net validation surface stays the same
    # (declared fields enforced) — we just stop noisy false positives on
    # adjacent env vars that aren't our concern.
    #
    # Why not declare the extras as `Optional[str] = None` fields instead:
    # would couple unrelated concerns into Settings (DASHSCOPE_API_KEY is
    # only used by the dev-machine benchmark harness; CI/CD vars belong
    # to the deploy layer; future Story 6.9c provider keys shouldn't
    # require touching this file before they can be tested). Keep Settings
    # scoped to fields the prod runtime actively reads.
    #
    # Concrete drivers (env vars currently present on dev machines OR VPS
    # that are NOT declared above): DASHSCOPE_API_KEY (Lever 1 bench),
    # CEREBRAS_API_KEY / ANTHROPIC_API_KEY (Phase A bench slots), CI vars
    # from GitHub Actions, LATENCY_PROBE (smoke gate gate), CLASSIFIER_MODEL
    # (already used here but as override of declared field). Pydantic v1
    # default behavior was "ignore"; v2 flipped to "forbid" — we're
    # restoring v1 semantics intentionally.
    model_config = {"env_file": ".env", "extra": "ignore"}

    @field_validator("jwt_secret")
    @classmethod
    def _validate_jwt_secret(cls, value: str, info) -> str:
        """Reject empty secrets in every environment; require >=32 chars in production.

        Generate one with: openssl rand -hex 32
        """
        if not value:
            raise ValueError(
                "JWT_SECRET must be set (generate with: openssl rand -hex 32)"
            )
        environment = (info.data.get("environment") or "development").strip().lower()
        if environment == "production" and len(value) < 32:
            raise ValueError(
                "JWT_SECRET must be at least 32 chars in production "
                "(generate with: openssl rand -hex 32)"
            )
        return value

    @field_validator("resend_from_name", "resend_from_email")
    @classmethod
    def _forbid_crlf_in_sender_fields(cls, value: str) -> str:
        """Reject CR/LF in sender fields to prevent email-header injection."""
        if "\r" in value or "\n" in value:
            raise ValueError(
                "CR/LF characters are not allowed in email sender fields "
                "(header-injection risk)"
            )
        return value
