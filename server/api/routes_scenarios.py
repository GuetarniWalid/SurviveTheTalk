"""APIRouter for the scenarios endpoints (Story 5.1).

`GET /scenarios` — list view with the caller's progression LEFT JOIN.
`GET /scenarios/{scenario_id}` — full authoring body + progression.

Tier-aware filtering is intentionally NOT done here: every authenticated user
sees the full catalog. The lock affordance lives in the client (Story 5.3).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import ValidationError

from api.middleware import AUTH_DEPENDENCY
from api.responses import ok, ok_list
from api.usage import compute_call_usage
from db.database import get_connection
from db.queries import (
    get_all_scenarios_with_progress,
    get_scenario_by_id_with_progress,
    get_user_by_id,
)
from models.schemas import ScenarioDetail, ScenarioListItem


_CORRUPT_SCENARIO = HTTPException(
    status_code=500,
    detail={"code": "SCENARIO_CORRUPT", "message": "Scenario data is malformed."},
)

router = APIRouter(
    prefix="/scenarios", tags=["scenarios"], dependencies=[AUTH_DEPENDENCY]
)


def _safe_json_load(value: str | None, *, scenario_id: str, column: str):
    """Decode a JSON-in-TEXT column with a clear error envelope on corruption.

    Schema enforces NOT NULL on the structural columns and the seeder uses
    `json.dumps`, so corruption is theoretical (manual SQL edit). When it
    DOES happen we want a clean 500 with a code clients can branch on,
    not an unhelpful FastAPI default error.
    """
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error(f"Corrupt JSON in scenarios.{column} for {scenario_id!r}: {exc}")
        raise _CORRUPT_SCENARIO from exc


@router.get("")
async def list_scenarios(request: Request) -> dict:
    """Return every scenario with the caller's `best_score` / `attempts`.

    Order is fixed to the difficulty bucket (easy → medium → hard) then
    alphabetically by id. The full list is returned regardless of `is_free`
    — the client renders the lock state.
    """
    user_id: int = request.state.user_id
    async with get_connection() as db:
        rows = await get_all_scenarios_with_progress(db, user_id)
        user = await get_user_by_id(db, user_id)
        if user is None:
            # Cannot happen for a JWT-authenticated request (middleware would
            # have 401'd already). Guard anyway — silent NoneType access on
            # `user["tier"]` would be much worse than a clean 401.
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "AUTH_UNAUTHORIZED",
                    "message": "Missing or invalid token.",
                },
            )
        usage = await compute_call_usage(db, user_id, user["tier"])

    try:
        items = [
            ScenarioListItem(
                id=row["id"],
                title=row["title"],
                difficulty=row["difficulty"],
                is_free=bool(row["is_free"]),
                rive_character=row["rive_character"],
                language_focus=_safe_json_load(
                    row["language_focus"],
                    scenario_id=row["id"],
                    column="language_focus",
                ),
                content_warning=row["content_warning"],
                best_score=row["best_score"],
                # `attempts` is COALESCE'd to 0 in the SQL query, so it is
                # already a non-nullable int here — no runtime fallback needed.
                attempts=row["attempts"],
            )
            for row in rows
        ]
    except ValidationError as exc:
        # A JSON-in-TEXT column held valid JSON of the wrong shape (e.g.
        # `language_focus` stored as `{"a": 1}` instead of `[...]`). Decode
        # succeeded so `_safe_json_load` didn't fire; Pydantic catches it
        # here. Surface the same SCENARIO_CORRUPT code so clients can branch.
        logger.error(f"Pydantic shape mismatch in scenarios list: {exc}")
        raise _CORRUPT_SCENARIO from exc
    return ok_list(items, extra_meta=usage)


@router.get("/{scenario_id}")
async def get_scenario(request: Request, scenario_id: str) -> dict:
    """Return one scenario's full authoring body + the caller's progression."""
    user_id: int = request.state.user_id
    async with get_connection() as db:
        row = await get_scenario_by_id_with_progress(db, user_id, scenario_id)

    if row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "SCENARIO_NOT_FOUND",
                "message": "Scenario not found.",
            },
        )

    sid = row["id"]
    try:
        detail = ScenarioDetail(
            id=sid,
            title=row["title"],
            difficulty=row["difficulty"],
            is_free=bool(row["is_free"]),
            rive_character=row["rive_character"],
            language_focus=_safe_json_load(
                row["language_focus"], scenario_id=sid, column="language_focus"
            ),
            content_warning=row["content_warning"],
            best_score=row["best_score"],
            # `attempts` is COALESCE'd to 0 in the SQL query.
            attempts=row["attempts"],
            base_prompt=row["base_prompt"],
            checkpoints=_safe_json_load(
                row["checkpoints"], scenario_id=sid, column="checkpoints"
            ),
            briefing=_safe_json_load(
                row["briefing"], scenario_id=sid, column="briefing"
            ),
            exit_lines=_safe_json_load(
                row["exit_lines"], scenario_id=sid, column="exit_lines"
            ),
            patience_start=row["patience_start"],
            fail_penalty=row["fail_penalty"],
            silence_penalty=row["silence_penalty"],
            recovery_bonus=row["recovery_bonus"],
            silence_prompt_seconds=row["silence_prompt_seconds"],
            silence_hangup_seconds=row["silence_hangup_seconds"],
            escalation_thresholds=_safe_json_load(
                row["escalation_thresholds"],
                scenario_id=sid,
                column="escalation_thresholds",
            ),
            tts_voice_id=row["tts_voice_id"],
            tts_speed=row["tts_speed"],
            scoring_model=row["scoring_model"],
        )
    except ValidationError as exc:
        # JSON column held valid JSON of the wrong shape — surface the same
        # clean SCENARIO_CORRUPT code that `_safe_json_load` uses for the
        # parse-failure branch.
        logger.error(f"Pydantic shape mismatch in scenarios.{sid!r} detail: {exc}")
        raise _CORRUPT_SCENARIO from exc
    return ok(detail)
