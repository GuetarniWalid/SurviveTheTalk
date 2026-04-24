"""Pydantic v2 request / response models.

These are the type-checked I/O contract for HTTP endpoints. Outer envelope
shape (`{"data": ..., "meta": ...}` / `{"error": ...}`) is built by helpers
in `api/responses.py` — these models cover the inner payloads only.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


# RFC 5321 caps the full email at 254 octets; we enforce it at the schema
# boundary so a pathological client can't amplify memory via long strings.
_MAX_EMAIL_LEN = 254


class RequestCodeIn(BaseModel):
    email: EmailStr = Field(max_length=_MAX_EMAIL_LEN)


class VerifyCodeIn(BaseModel):
    email: EmailStr = Field(max_length=_MAX_EMAIL_LEN)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class RequestCodeOut(BaseModel):
    message: str


class VerifyCodeOut(BaseModel):
    token: str
    user_id: int
    email: EmailStr = Field(max_length=_MAX_EMAIL_LEN)


class InitiateCallIn(BaseModel):
    """Request body for POST /calls/initiate.

    Empty in Story 4.5 — the tutorial scenario is hardcoded server-side.
    Full scenario selection (a `scenario_id` field) lands with Story 6.1
    once the scenarios table exists (Story 5.1).
    """


class InitiateCallOut(BaseModel):
    call_id: int
    room_name: str
    token: str
    livekit_url: str


class HealthOut(BaseModel):
    status: str
    db: str
    # Git SHA of the deployed release, read from `server/.git_sha` at startup.
    # Set by the CI workflow (.github/workflows/deploy-server.yml) right after
    # the rsync step, so the workflow's post-restart healthcheck can assert
    # the running process IS the release it just deployed (closes the silent-
    # ghost failure mode). `"unknown"` when the file is absent (local dev,
    # tests, manual VPS edits).
    git_sha: str


class Meta(BaseModel):
    timestamp: str


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict | None = None


class ScenarioListItem(BaseModel):
    """Card-view payload for `GET /scenarios`. Heavy authoring fields
    (`base_prompt`, `checkpoints`, `briefing`, `exit_lines`, override knobs)
    are deliberately omitted — they are only needed by `GET /scenarios/{id}`.
    """

    id: str
    title: str
    difficulty: str
    is_free: bool
    rive_character: str
    language_focus: list[str]
    content_warning: str | None = None
    best_score: int | None = None
    attempts: int


class ScenarioDetail(ScenarioListItem):
    """Full payload for `GET /scenarios/{id}`. Adds the authoring body and
    every nullable difficulty-override column from ADR 001.
    """

    base_prompt: str
    checkpoints: list[dict]
    briefing: dict
    exit_lines: dict
    patience_start: int | None = None
    fail_penalty: int | None = None
    silence_penalty: int | None = None
    recovery_bonus: int | None = None
    silence_prompt_seconds: int | None = None
    silence_hangup_seconds: int | None = None
    escalation_thresholds: list[int] | None = None
    tts_voice_id: str | None = None
    tts_speed: float | None = None
    scoring_model: str | None = None


class _ListMeta(BaseModel):
    """Envelope `meta` block for list endpoints — documents `timestamp` +
    `count` so the generated OpenAPI schema matches what `ok_list` returns
    at runtime.
    """

    timestamp: str
    count: int


class ScenariosListOut(BaseModel):
    """Documentation-only model for `GET /scenarios`. The route returns the
    envelope dict directly via `ok_list`; this model exists so the OpenAPI
    schema captures the response shape — including the `meta.count` key that
    clients rely on.
    """

    data: list[ScenarioListItem]
    meta: _ListMeta
