"""Story 7.1 — `GET /debriefs/{call_id}` (read the post-call debrief).

Decision 1 (Option A): the per-call bot subprocess generates + persists the
debrief at teardown; this route is a thin authenticated READER. It enforces
ownership through the owning `call_session` (cross-user → 404 `CALL_NOT_FOUND`,
info-leak parity with `/calls/{id}/end`) and returns 404 `DEBRIEF_NOT_READY`
when the call exists for the user but no debrief has landed yet (Story 7.2's
overlay treats that as "still generating" and shows its loader).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from pydantic import ValidationError

from api.middleware import AUTH_DEPENDENCY
from api.responses import ok
from db.database import get_connection
from db.queries import get_call_session, get_debrief_by_call_id
from models.schemas import DebriefOut

router = APIRouter(
    prefix="/debriefs", tags=["debriefs"], dependencies=[AUTH_DEPENDENCY]
)


@router.get("/{call_id}")
async def get_debrief(call_id: int, request: Request) -> dict:
    """Return the assembled debrief for `call_id` in the `{data, meta}` envelope.

    404 `CALL_NOT_FOUND` when the call does not exist OR belongs to another
    user (same envelope so an enumerator can't tell them apart). 404
    `DEBRIEF_NOT_READY` when the call is the caller's but its debrief has not
    been generated yet.
    """
    user_id: int = request.state.user_id

    async with get_connection() as db:
        call = await get_call_session(db, call_id)
        # 404 covers BOTH "no such call" AND "another user's call" — info-leak
        # prevention, mirroring the `/calls/{id}/end` pre-check.
        if call is None or call["user_id"] != user_id:
            raise HTTPException(
                status_code=404,
                detail={"code": "CALL_NOT_FOUND", "message": "Call not found."},
            )
        debrief_row = await get_debrief_by_call_id(db, call_id)

    if debrief_row is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "DEBRIEF_NOT_READY",
                "message": "Debrief is still being generated.",
            },
        )

    try:
        data = json.loads(debrief_row["debrief_json"])
        # Contract gate — a corrupt / legacy blob fails loudly with a shaped
        # envelope instead of serving garbage to the client.
        DebriefOut.model_validate(data)
    except (ValueError, TypeError, ValidationError) as exc:
        logger.error(
            "debrief blob unreadable for call_id={}: {} ({})",
            call_id,
            exc,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail={
                "code": "DEBRIEF_UNAVAILABLE",
                "message": "Debrief could not be loaded.",
            },
        ) from exc

    # Story 10.7 (Bug B — progressive debrief) — surface the two-phase lifecycle
    # so the client can tell "score-only, analysis still coming" (keep polling)
    # from a terminal row (full OR degraded). The flag is the `status` COLUMN, not
    # part of the stored blob (single source of truth). A `pending` row carries
    # the real survival % + checkpoints (renders the scorecard now) but empty
    # analysis arrays; a `ready` row is terminal. A missing row still 404s
    # DEBRIEF_NOT_READY above.
    #
    # Back-compat decision (Story 10.7 review): a PRE-10.7 client that ignored
    # this `pending` flag would treat a score-only `pending` payload as terminal
    # (empty analysis → a false "flawless call"). This is accepted: 10.7 is a
    # PRE-LAUNCH blocker, so the FIRST public build is already 10.7+ — no pre-10.7
    # client will ever exist in the field. If a future debrief change ships
    # post-launch and old builds must be guarded, gate this injection on a
    # client-capability header instead of serving 404 to all (which would cost new
    # clients the instant scorecard this story delivers).
    data["pending"] = debrief_row["status"] == "pending"

    # Serve the STORED dict (not a model re-dump): assemble_debrief already
    # encodes the null-omission convention — `encouraging_framing` is ABSENT
    # (not null) below 41%, and the client keys on field presence (FR15b).
    return ok(data)
