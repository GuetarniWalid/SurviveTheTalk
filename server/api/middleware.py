"""JWT bearer-token authentication dependency.

Wired but not (yet) applied to any production route. Story 4.2 only ships the
mechanism; Story 5.1 (scenarios) and Story 6.1 (call initiation) are the
first consumers. A test-only protected route exercises every branch in
`tests/test_middleware.py`.

Usage in future routers:
    from api.middleware import AUTH_DEPENDENCY
    router = APIRouter(prefix="/scenarios", dependencies=[AUTH_DEPENDENCY])
    # then in handlers: user_id = request.state.user_id
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.jwt_service import decode_token
from db.database import get_connection
from db.queries import get_user_by_id

bearer_scheme = HTTPBearer(auto_error=False)


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> int:
    """FastAPI dependency: enforce a valid Bearer JWT and resolve `user_id`.

    On success: sets `request.state.user_id` and returns the int.
    On failure: raises HTTPException with envelope-shaped detail dicts that
    `api/app.py`'s exception handler converts into the `{"error": {...}}` body.
    """
    # `HTTPBearer(auto_error=False)` only yields credentials when the scheme is
    # `Bearer`, so the explicit scheme check below is a belt-and-braces guard
    # against future changes to the FastAPI dependency. An empty credential
    # string also counts as "missing" — there's no token to decode.
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
    ):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_UNAUTHORIZED",
                "message": "Missing or invalid token.",
            },
        )

    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_TOKEN_EXPIRED",
                "message": "Your session has expired. Please sign in again.",
            },
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_UNAUTHORIZED",
                "message": "Missing or invalid token.",
            },
        ) from exc

    user_id = payload.get("user_id")
    # `bool` is a subclass of `int` in Python, so `isinstance(True, int)` is
    # True. We reject booleans explicitly to avoid a forged `user_id: true`
    # claim resolving to user #1 via boolean coercion.
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "AUTH_UNAUTHORIZED",
                "message": "Missing or invalid token.",
            },
        )

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

    request.state.user_id = user_id
    return user_id


# Reusable dependency object so future routers can write
# `APIRouter(dependencies=[AUTH_DEPENDENCY])` without boilerplate.
AUTH_DEPENDENCY = Depends(require_auth)
