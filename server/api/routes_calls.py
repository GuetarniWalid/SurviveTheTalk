"""APIRouter for the call-session endpoints.

Introduced by Story 4.5 to replace the PoC `/connect` endpoint with an
authenticated, persisted call-initiation flow. `/connect` is deliberately
kept alive alongside this router — its tests still pass and the legacy
Flutter client continues to use it. Story 6.1 retires `/connect`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pipecat.runner.livekit import generate_token, generate_token_with_agent

from api.middleware import AUTH_DEPENDENCY
from api.responses import now_iso, ok
from config import Settings
from db.database import get_connection
from db.queries import insert_call_session
from models.schemas import InitiateCallIn, InitiateCallOut
from pipeline.scenarios import TUTORIAL_SCENARIO_ID, load_scenario_prompt

router = APIRouter(prefix="/calls", tags=["calls"], dependencies=[AUTH_DEPENDENCY])

settings = Settings()


@router.post("/initiate")
async def initiate_call(request: Request, payload: InitiateCallIn) -> dict:
    """Start the tutorial call: persist a row + spawn a bot + return room creds.

    Contract (Story 4.5):
      - Hardcoded scenario `waiter_easy_01` (full selection in Story 6.1).
      - Auth required (JWT via `AUTH_DEPENDENCY`).
      - Inserts `call_sessions(user_id, scenario_id, started_at=now_iso())`.
      - Spawns `python -m pipeline.bot` with the composed scenario prompt
        passed via the `SYSTEM_PROMPT` env var (bot reads it in `run_bot`).
      - Returns the `{data, meta}` envelope with `call_id`, `room_name`,
        user `token`, and `livekit_url` so the client can join the room.

    Failure envelope: every exception is surfaced as an HTTPException whose
    `detail.code` feeds the global envelope handler in `api/app.py`. The bot
    subprocess is the LAST side-effect — if it fails, the freshly-inserted
    `call_sessions` row is rolled back so we never leave an orphan row
    pointing at a bot that never started.
    """
    user_id: int = request.state.user_id
    scenario_id = TUTORIAL_SCENARIO_ID

    try:
        system_prompt = load_scenario_prompt(scenario_id)
    except (FileNotFoundError, RuntimeError, ValueError, KeyError) as exc:
        logger.exception(f"Failed to load scenario prompt for {scenario_id!r}")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "SCENARIO_LOAD_FAILED",
                "message": "Could not prepare the tutorial scenario.",
            },
        ) from exc

    room_name = f"call-{uuid4()}"

    try:
        agent_token = generate_token_with_agent(
            room_name=room_name,
            participant_name="tina-bot",
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
        user_token = generate_token(
            room_name=room_name,
            participant_name=f"user-{user_id}",
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
    except Exception as exc:
        logger.exception("LiveKit token generation failed")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "LIVEKIT_TOKEN_FAILED",
                "message": "Could not reach the call provider.",
            },
        ) from exc

    try:
        async with get_connection() as db:
            call_id = await insert_call_session(
                db,
                user_id=user_id,
                scenario_id=scenario_id,
                started_at=now_iso(),
            )
    except Exception as exc:
        logger.exception("Failed to persist call_sessions row")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "CALL_PERSIST_FAILED",
                "message": "Could not record the call session.",
            },
        ) from exc

    # Bot spawn is the LAST side-effect so a failure only needs to rollback
    # the DB row, not also try to kill an in-flight process.
    bot_env = {**os.environ, "SYSTEM_PROMPT": system_prompt}
    try:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pipeline.bot",
                "--url",
                settings.livekit_url,
                "--room",
                room_name,
                "--token",
                agent_token,
            ],
            env=bot_env,
        )
    except OSError as exc:
        logger.exception(f"Failed to spawn pipeline bot for room {room_name}")
        async with get_connection() as db:
            await db.execute("DELETE FROM call_sessions WHERE id = ?", (call_id,))
            await db.commit()
        raise HTTPException(
            status_code=500,
            detail={
                "code": "BOT_SPAWN_FAILED",
                "message": "Could not start the conversation agent.",
            },
        ) from exc

    logger.info(f"Spawned tutorial bot for room {room_name} (user {user_id})")

    return ok(
        InitiateCallOut(
            call_id=call_id,
            room_name=room_name,
            token=user_token,
            livekit_url=settings.livekit_url,
        )
    )
