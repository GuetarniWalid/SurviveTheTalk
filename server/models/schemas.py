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

    Story 6.19 — `difficulty` is the learner's GLOBAL difficulty pick
    (set once on the hub, sent on every call). Optional + `default=None`
    for backward compatibility: older clients / the legacy `/connect`
    path omit it, and the server then uses the scenario's authored
    `metadata.difficulty` (AC7). The `Literal` rejects any other value
    with a 422 at the schema boundary, BEFORE any scenario YAML I/O.
    """

    scenario_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    difficulty: Literal["easy", "medium", "hard"] | None = Field(default=None)


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
    Story 6.11 — `'noisy_environment'` added for the parasitic-voice
    detection path (always gifted, see `routes_calls._GIFT_ANY_DURATION_
    REASONS`).
    """

    reason: Literal[
        "user_hung_up",
        "character_hung_up",
        "inappropriate_content",
        "network_lost",
        "survived",
        "noisy_environment",
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
    # Story 7.2 — Call Ended overlay theatrical phrases
    # (`{"hung_up": …, "voluntary": …, "survived": …}`). Deliberately on the
    # LIST item (not detail-only): the client carries the list `Scenario`
    # into the call, so the overlay reads the phrases at call-end without a
    # `GET /scenarios/{id}` round-trip. Nullable — legacy rows / YAMLs
    # without the block → the overlay hides the phrase element (design P-7).
    end_phrases: dict | None = None


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


# --- Story 7.1: post-call debrief ------------------------------------------


class DebriefError(BaseModel):
    """One deduplicated language error (LLM-produced). `count` >= 1; the UI
    shows an "x[N]" badge only when count >= 2 (debrief-content-strategy Q8)."""

    user_said: str
    correction: str
    context: str
    count: int


class DebriefHesitation(BaseModel):
    """A >3 s hesitation: backend-measured `duration_sec` merged (by index)
    with the LLM's situational `context` (FR12)."""

    duration_sec: float
    context: str


class DebriefIdiom(BaseModel):
    """An idiom/slang expression the CHARACTER used (FR13)."""

    expression: str
    meaning: str
    context: str


class EncouragingFraming(BaseModel):
    """FR15b data-driven framing — present only when survival > 40%.
    `improvement` is omitted unless this attempt beat a prior best."""

    proximity: str
    improvement: str | None = None


class DebriefOut(BaseModel):
    """Response body for `GET /debriefs/{call_id}` (the assembled debrief).

    The hero fields (`survival_pct`, `character_name`, `scenario_title`,
    `attempt_number`, `previous_best`) + the analysis sections + the optional
    `encouraging_framing`. Per debrief-content-strategy: `inappropriate_
    behavior` and `previous_best` are kept as `null` when absent (the client
    keys on the value), whereas `encouraging_framing` is OMITTED entirely
    below 41% (the client keys on field presence). The route therefore serves
    the stored, already-omission-correct dict rather than a model re-dump —
    this model documents + validates that contract.
    """

    survival_pct: int
    character_name: str
    scenario_title: str
    attempt_number: int
    previous_best: int | None = None
    errors: list[DebriefError]
    hesitations: list[DebriefHesitation]
    idioms: list[DebriefIdiom]
    areas_to_work_on: list[str]
    inappropriate_behavior: str | None = None
    encouraging_framing: EncouragingFraming | None = None
