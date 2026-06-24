"""Passwordless email auth endpoints: /auth/request-code and /auth/verify-code.

See story §AC2, §AC3, §Concrete User Walk-Through for the full behavioural
contract. Both endpoints normalise the email (lowercase + strip), use raw-SQL
through `db/queries.py`, and wrap their response in the `{data, meta}` envelope.

NOTE: rate limiting is intentionally NOT implemented — see TODO(story-10).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import aiosqlite
from fastapi import APIRouter, HTTPException
from loguru import logger

from api.responses import now_iso, ok
from auth.email_service import (
    EmailDeliveryError,
    EmailRateLimitedError,
    send_auth_code,
)
from auth.jwt_service import hash_token, issue_token
from config import Settings
from db.database import get_connection
from db.queries import (
    ClaimOutcome,
    claim_active_code,
    get_user_by_email,
    insert_auth_code,
    insert_user,
    invalidate_previous_codes,
    update_user_jwt_hash,
)
from models.schemas import (
    RequestCodeIn,
    RequestCodeOut,
    VerifyCodeIn,
    VerifyCodeOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Module-level Settings (same pattern as `routes_calls`): read once at import.
settings = Settings()

CODE_TTL_MINUTES = 15

# TODO(story-10): add rate limiting on /auth/request-code (max 5/hour per email).


def _normalise_email(email: str) -> str:
    return email.lower().strip()


def _redact_email_for_log(email: str) -> str:
    """Non-reversible fingerprint so log files never store plaintext emails."""
    return f"email:{hashlib.sha256(email.encode()).hexdigest()[:10]}"


def _generate_six_digit_code() -> str:
    """Cryptographically random 6-digit decimal code, zero-padded."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _expires_at_iso() -> str:
    """ISO 8601 UTC timestamp 15 minutes in the future, trailing Z."""
    return (
        (datetime.now(UTC) + timedelta(minutes=CODE_TTL_MINUTES))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _is_review_email(email: str) -> bool:
    """True iff the env-gated Google-Play review bypass is configured for this
    email. OFF (False) unless REVIEW_LOGIN_EMAIL is set."""
    configured = settings.review_login_email
    return bool(configured) and email == _normalise_email(configured)


def _is_review_login(email: str, code: str) -> bool:
    """True iff this email+code is the configured review bypass. Constant-time
    code compare, gated behind `_is_review_email` so an unset bypass never
    short-circuits a real verify."""
    return _is_review_email(email) and secrets.compare_digest(
        code, settings.review_login_code
    )


async def _issue_session(db: aiosqlite.Connection, email: str) -> VerifyCodeOut:
    """Get-or-create the user for `email`, mint a JWT, persist its hash, and
    return the verify-code response. Shared by the normal claimed-code path and
    the review-login bypass so both create the session identically."""
    user = await get_user_by_email(db, email)
    if user is None:
        try:
            user_id = await insert_user(db, email, now_iso())
        except aiosqlite.IntegrityError:
            # Concurrent first-time verify for the same email can race past the
            # get check; UNIQUE(users.email) blocks the dup INSERT — re-read.
            user = await get_user_by_email(db, email)
            if user is None:  # truly unexpected
                raise
            user_id = user["id"]
    else:
        user_id = user["id"]

    token = issue_token(user_id)
    await update_user_jwt_hash(db, user_id, await hash_token(token))
    return VerifyCodeOut(token=token, user_id=user_id, email=email)


@router.post("/request-code")
async def request_code(payload: RequestCodeIn):
    """Issue a fresh 6-digit code, invalidating any previous active code."""
    email = _normalise_email(payload.email)

    if _is_review_email(email):
        # Env-gated review bypass: verify-code accepts the fixed
        # REVIEW_LOGIN_CODE, so no real code is needed — and the test inbox may
        # not be deliverable. Return success (sending NOTHING) so the app
        # advances to the code-entry screen. See config.review_login_email.
        logger.warning(
            "Review-login request-code (no email sent) for {}",
            _redact_email_for_log(email),
        )
        return ok(RequestCodeOut(message="Code sent"))

    code = _generate_six_digit_code()
    expires_at = _expires_at_iso()

    async with get_connection() as db:
        await invalidate_previous_codes(db, email)
        await insert_auth_code(db, email, code, expires_at)

    try:
        await send_auth_code(email, code)
    except EmailRateLimitedError:
        # Log without PII: the code itself is never logged (would defeat the
        # whole auth factor). The redacted email fingerprint is enough to
        # correlate repeat failures across requests.
        logger.warning("Resend rate-limited for {}", _redact_email_for_log(email))
        raise HTTPException(
            status_code=429,
            detail={
                "code": "EMAIL_RATE_LIMITED",
                "message": "Too many attempts. Please wait a moment and try again.",
            },
            headers={"Retry-After": "60"},
        ) from None
    except EmailDeliveryError as exc:
        logger.error(
            "Resend delivery failed for {}: {}",
            _redact_email_for_log(email),
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": "EMAIL_DELIVERY_FAILED",
                "message": "Could not send email. Please try again.",
            },
        ) from exc

    return ok(RequestCodeOut(message="Code sent"))


@router.post("/verify-code")
async def verify_code(payload: VerifyCodeIn):
    """Verify the code, issue a JWT, create the user on first login."""
    email = _normalise_email(payload.email)

    if _is_review_login(email, payload.code):
        # Env-gated Google-Play app-access review bypass — see
        # config.review_login_email. Skips the random-code claim so a store
        # reviewer can sign in without receiving an emailed code.
        logger.warning("Review-login bypass used for {}", _redact_email_for_log(email))
        async with get_connection() as db:
            return ok(await _issue_session(db, email))

    async with get_connection() as db:
        # Atomic CAS claim: closes the TOCTOU window where two concurrent
        # requests could both see `used = 0` and both succeed.
        outcome, row = await claim_active_code(db, email, payload.code, now_iso())

        if outcome == ClaimOutcome.EXPIRED:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "AUTH_CODE_EXPIRED",
                    "message": "This code has expired. Please request a new one.",
                },
            )
        if outcome in (ClaimOutcome.NOT_FOUND, ClaimOutcome.ALREADY_USED):
            # Don't leak whether the code exists-but-used vs never-existed:
            # an attacker testing guessed codes would learn nothing useful.
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "AUTH_CODE_INVALID",
                    "message": "Invalid code. Please check and try again.",
                },
            )
        assert outcome == ClaimOutcome.CLAIMED and row is not None

        return ok(await _issue_session(db, email))
