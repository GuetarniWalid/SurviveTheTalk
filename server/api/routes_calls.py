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

import yaml
from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pipecat.runner.livekit import generate_token, generate_token_with_agent

from api.middleware import AUTH_DEPENDENCY
from api.responses import now_iso, ok
from api.usage import compute_call_usage
from config import Settings
from db.database import get_connection
from db.queries import get_user_by_id, insert_call_session
from models.schemas import InitiateCallIn, InitiateCallOut
from pipeline.scenarios import load_scenario_prompt

router = APIRouter(prefix="/calls", tags=["calls"], dependencies=[AUTH_DEPENDENCY])

settings = Settings()


@router.post("/initiate")
async def initiate_call(request: Request, payload: InitiateCallIn) -> dict:
    """Start a scenario call: persist a row + spawn a bot + return room creds.

    Contract:
      - `scenario_id` arrives in the request body (Story 6.1 widened
        `InitiateCallIn` from empty to `{scenario_id: str}`); resolved to a
        YAML in `pipeline/scenarios/` via `load_scenario_prompt`.
      - Auth required (JWT via `AUTH_DEPENDENCY`).
      - Cap-check (FR21 via `compute_call_usage`) runs BEFORE token mint,
        BEFORE INSERT, BEFORE bot spawn — a blocked call leaves zero
        side-effects (no row, no process, no token consumed).
      - Inserts `call_sessions(user_id, scenario_id, started_at=now_iso())`.
      - Spawns `python -m pipeline.bot` with the composed scenario prompt
        passed via the `SYSTEM_PROMPT` env var (bot reads it in `run_bot`).
      - Returns the `{data, meta}` envelope with `call_id`, `room_name`,
        user `token`, and `livekit_url` so the client can join the room.
    """
    user_id: int = request.state.user_id
    scenario_id = payload.scenario_id
    room_name = f"call-{uuid4()}"

    try:
        async with get_connection() as db:
            # 1. Cap-check (DB).
            user = await get_user_by_id(db, user_id)
            if user is None:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "code": "AUTH_UNAUTHORIZED",
                        "message": "Missing or invalid token.",
                    },
                )
            usage = await compute_call_usage(db, user_id, user["tier"])
            if usage["calls_remaining"] == 0:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "CALL_LIMIT_REACHED",
                        "message": "You've used all your calls for now.",
                    },
                )

            # 2. Scenario prompt (file IO, no DB) — fail fast on bad YAML.
            try:
                system_prompt = load_scenario_prompt(scenario_id)
            except (
                FileNotFoundError,
                RuntimeError,
                ValueError,
                KeyError,
                yaml.YAMLError,
            ) as exc:
                logger.exception(f"Failed to load scenario prompt for {scenario_id!r}")
                raise HTTPException(
                    status_code=500,
                    detail={
                        "code": "SCENARIO_LOAD_FAILED",
                        "message": "Could not prepare the scenario.",
                    },
                ) from exc

            # 3. LiveKit tokens (no DB).
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

            # 4. Persist (DB) — atomic cap-check + INSERT inside BEGIN
            # IMMEDIATE so two concurrent /calls/initiate requests cannot
            # both pass the gate and both INSERT (TOCTOU race fix). The
            # early cap-check above is a fast-fail before token mint; this
            # transactional re-check is the authoritative enforcement,
            # paired with `PRAGMA busy_timeout = 5000` in `get_connection()`
            # so a contending second request blocks until the first commits
            # rather than raising `database is locked`.
            await db.execute("BEGIN IMMEDIATE")
            try:
                final_usage = await compute_call_usage(db, user_id, user["tier"])
                if final_usage["calls_remaining"] == 0:
                    await db.rollback()
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": "CALL_LIMIT_REACHED",
                            "message": "You've used all your calls for now.",
                        },
                    )
                call_id = await insert_call_session(
                    db,
                    user_id=user_id,
                    scenario_id=scenario_id,
                    started_at=now_iso(),
                )
                await db.commit()
            except HTTPException:
                # Already rolled back above on cap-hit; bubble untouched.
                raise
            except BaseException:
                await db.rollback()
                raise
    except HTTPException:
        # Already-shaped failures bubble untouched — they carry their own
        # status code + envelope (401 / 403 / 500 / 502).
        raise
    except Exception as exc:
        # Catch-all for unexpected DB / connection-level failures around
        # the hot path (lost lock, disk full, etc.). Surfaces the same
        # envelope as a failed INSERT so clients have one error to branch
        # on for "couldn't record the call".
        logger.exception("Unexpected error during /calls/initiate hot path")
        raise HTTPException(
            status_code=500,
            detail={
                "code": "CALL_PERSIST_FAILED",
                "message": "Could not record the call session.",
            },
        ) from exc

    # Bot spawn is the LAST side-effect so a failure only needs to rollback
    # the DB row, not also try to kill an in-flight process. The rollback
    # opens a fresh connection because the hot-path connection closed when
    # `async with` exited above.
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
