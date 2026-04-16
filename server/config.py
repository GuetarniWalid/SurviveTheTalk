"""Server configuration loaded from environment / .env."""

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Runtime environment ("development" | "test" | "production").
    # Declared first so the jwt_secret validator can read it from info.data.
    environment: str = "development"

    # Pipeline (Pipecat / LiveKit / AI services)
    soniox_api_key: str
    openrouter_api_key: str
    cartesia_api_key: str
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # Auth
    jwt_secret: str = ""
    resend_api_key: str = ""
    resend_from_email: str = "noreply@survivethetalk.com"
    resend_from_name: str = "surviveTheTalk"

    # Database
    database_path: str = "/opt/survive-the-talk/data/db.sqlite"

    model_config = {"env_file": ".env"}

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
