"""Pydantic v2 request / response models.

These are the type-checked I/O contract for HTTP endpoints. Outer envelope
shape (`{"data": ..., "meta": ...}` / `{"error": ...}`) is built by helpers
in `api/responses.py` — these models cover the inner payloads only.
"""

from __future__ import annotations

from typing import Literal

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

    `scenario_id` is required (no default) — the server resolves it to a
    YAML in `pipeline/scenarios/` via `load_scenario_prompt`. Bounded
    length + charset prevent log-amplification (an unbounded string would
    hit `logger.exception` on lookup-miss) and reject obvious garbage at
    the schema boundary.
    """

    scenario_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")


class InitiateCallOut(BaseModel):
    call_id: int
    room_name: str
    token: str
    livekit_url: str


class EndCallIn(BaseModel):
    """Request body for POST /calls/{call_id}/end.

    `reason` MUST match one of the canonical values defined in
    `_bmad-output/planning-artifacts/call-ended-screen-design.md`
    §Variant Selection Logic. Story 6.5 review D4 — `'survived'` is
    pre-widened now so Story 6.6 (CheckpointManager) ships a server that
    already accepts it; forgetting the widen would otherwise silently 422
    the client's POST and orphan the row until the janitor's 1 h sweep.
    """

    reason: Literal[
        "user_hung_up",
        "character_hung_up",
        "inappropriate_content",
        "network_lost",
        "survived",
    ]


class EndCallOut(BaseModel):
    """Response body for POST /calls/{call_id}/end.

    `status` is `'completed'` on a first-end of a `'pending'` row. On an
    idempotent re-call against a `'failed'` row (janitor swept it before
    /end landed, OR the row was gifted on first-end), the response
    reflects the current row state. The client treats both as terminal —
    the cap counter is freed either way.

    Story 6.5 Déviation #27 — the gift fields drive a client-side notice
    screen so the user understands why they were returned to the
    scenario list AND whether the call cost them a cap slot:

    - `was_gifted` is True iff the server applied a gift (one of the
      3-per-day allowance was consumed). Coupled with `status='failed'`
      to skip the cap counter.
    - `gifts_remaining_today` is the number of gifts left in the
      user's daily allowance, AFTER this call's accounting. Drives the
      "X cadeaux restants" copy on the notice screen. Clamped to >= 0.
    """

    call_id: int
    status: Literal["completed", "failed"]
    duration_sec: int
    was_gifted: bool = False
    gifts_remaining_today: int = 3


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
    # Story 6.13 AC3 — stage-1 impatience anchor (per-difficulty preset,
    # YAML override via `metadata.ladder_impatience_seconds`). float
    # because preset values are fractional (4.5 / 3.5 / 2.5 s).
    ladder_impatience_seconds: float | None = None
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
