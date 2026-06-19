"""User account endpoints (auth-gated).

- `GET /user/profile` (Story 8.3) — steady-state subscription status for the
  Manage-Subscription screen (D5/AC5): tier, calls remaining in the current
  period, subscription expiry. `/scenarios` meta carries tier + calls but NOT
  the expiry, so this endpoint exists. Read-only.
- `DELETE /user/me` (Story 10.1, D4) — GDPR Art 17 self-serve account deletion:
  removes the caller and ALL their personal rows in one transaction.
- `GET /user/data-export` (Story 10.1, D4) — GDPR Art 20 data portability: the
  caller's stored data as JSON.

None of these mutate tier via store I/O; the actual call-cap enforcement gate is
`POST /calls/initiate` (server-authoritative).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from api.middleware import AUTH_DEPENDENCY
from api.responses import ok
from api.usage import compute_call_usage
from db.database import get_connection
from db.queries import (
    delete_user_account,
    gather_user_data,
    get_active_entitlement_expiry,
    get_user_by_id,
)
from models.schemas import AccountDeletionOut, UserProfileOut

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


@router.delete("/me")
async def delete_account(request: Request) -> dict:
    """Permanently delete the caller's account and ALL their personal data (D4).

    GDPR Art 17. Removes `users` + `auth_codes` + `call_sessions` + `debriefs` +
    `user_progress` + `purchases` for this user in ONE transaction, FK-safe order
    (`delete_user_account`). Wrapped in `BEGIN IMMEDIATE` so a mid-delete failure
    rolls back wholesale — never a half-deleted account.

    Idempotent by construction: once the row is gone the JWT resolves to no user,
    so a repeat `DELETE` (or any later authed call) is rejected at
    `AUTH_DEPENDENCY` with a 401 before reaching here — same shape as a stale
    token. The `user is None` guard below covers the narrow race where the row
    vanished between auth and this read.

    Does NOT cancel the user's App Store / Google Play subscription — the client
    and the Privacy Policy both state the user must cancel that in the store.
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
        email = user["email"]
        await db.execute("BEGIN IMMEDIATE")
        try:
            await delete_user_account(db, user_id, email)
            await db.commit()
        except BaseException:
            await db.rollback()
            raise

    logger.info(f"account_deleted user_id={user_id}")
    return ok(AccountDeletionOut(deleted=True))


@router.get("/data-export")
async def export_data(request: Request) -> dict:
    """Return all of the caller's stored data as JSON (GDPR Art 20, D4).

    Read-only sibling of `DELETE /user/me` sharing the same "gather my rows"
    logic (`gather_user_data`), wrapped in the canonical `{data, meta}` envelope.
    Excludes internal credentials (jwt_hash, verification_token) — see the query.
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
        data = await gather_user_data(db, user_id, user["email"])

    return ok(data)
