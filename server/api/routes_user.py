"""Story 8.3 — `GET /user/profile` (steady-state subscription status).

The canonical read endpoint for the Manage-Subscription screen (D5/AC5): the
user's tier, calls remaining in the current period, and the subscription expiry
date. `/scenarios` meta already carries tier + calls, but NOT the expiry — and
the new screen needs the renewal/expiry date — so this endpoint exists. Read-
only: no tier mutation, no store I/O. The actual enforcement gate is
`POST /calls/initiate` (server-authoritative); this just reports state.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from api.middleware import AUTH_DEPENDENCY
from api.responses import ok
from api.usage import compute_call_usage
from db.database import get_connection
from db.queries import get_active_entitlement_expiry, get_user_by_id
from models.schemas import UserProfileOut

router = APIRouter(prefix="/user", tags=["user"], dependencies=[AUTH_DEPENDENCY])


@router.get("/profile")
async def get_profile(request: Request) -> dict:
    """Return the caller's subscription status (`{data, meta}` envelope).

    `{tier, calls_remaining, calls_per_period, period, subscription_expires_at}`.
    401 is handled upstream by `AUTH_DEPENDENCY`. A user row that vanished after
    auth (race / deletion) → 401 AUTH_UNAUTHORIZED, same shape as
    `/calls/initiate`. `subscription_expires_at` is `null` when the user holds
    no `'valid'` purchase with an expiry (free users, legacy rows).
    """
    user_id: int = request.state.user_id

    async with get_connection() as db:
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
        expiry = await get_active_entitlement_expiry(db, user_id)

    return ok(
        UserProfileOut(
            tier=usage["tier"],
            calls_remaining=usage["calls_remaining"],
            calls_per_period=usage["calls_per_period"],
            period=usage["period"],
            subscription_expires_at=expiry,
        )
    )
