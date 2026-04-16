"""Resend email-delivery client for sending the 6-digit auth code.

Uses Resend's HTTP API (`POST https://api.resend.com/emails`) with a Bearer
token. The sender (`from`) address and display name are NEVER hardcoded —
they live in `settings.resend_from_email` / `settings.resend_from_name` so
Walid can switch sender domains by editing `.env` only.
"""

from __future__ import annotations

import hashlib

import httpx
from loguru import logger

from config import Settings

settings = Settings()

RESEND_API_URL = "https://api.resend.com/emails"
EMAIL_SUBJECT = "Your surviveTheTalk code"
EMAIL_BODY_TEMPLATE = "Your 6-digit code: {code}\nIt expires in 15 minutes."
HTTP_TIMEOUT_SECONDS = 10.0


class EmailDeliveryError(Exception):
    """Raised when Resend returns a non-2xx status or the call times out."""


class EmailRateLimitedError(EmailDeliveryError):
    """Raised when Resend responds 429 (upstream rate limit)."""


def _redact_email(email: str) -> str:
    """Return a stable, non-reversible fingerprint for logs.

    We must not write plaintext email addresses to log files (PII / GDPR).
    `sha256(email)[:10]` lets an operator correlate repeated failures for the
    same user without retaining the address itself.
    """
    return f"email:{hashlib.sha256(email.encode()).hexdigest()[:10]}"


async def send_auth_code(email: str, code: str) -> None:
    """Send the 6-digit auth code via Resend.

    Raises `EmailDeliveryError` (or its `EmailRateLimitedError` subclass) on
    any non-2xx response or transport error so the route handler can surface
    a 502 / 429 to the client. The auth_codes DB row is intentionally NOT
    rolled back on failure (see Scenario F): the user can retry without DB
    churn.

    Some Resend endpoints return 2xx with `{"error": ...}` in the body rather
    than an HTTP error code, so we double-check the JSON payload before
    declaring success.
    """
    from_address = f"{settings.resend_from_name} <{settings.resend_from_email}>"
    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": from_address,
        "to": [email],
        "subject": EMAIL_SUBJECT,
        "text": EMAIL_BODY_TEMPLATE.format(code=code),
    }
    redacted = _redact_email(email)

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(RESEND_API_URL, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        logger.error("Resend transport error for {}: {}", redacted, exc)
        raise EmailDeliveryError(str(exc)) from exc

    if response.status_code == 429:
        logger.error("Resend rate-limited for {}", redacted)
        raise EmailRateLimitedError(f"Resend rate limited: {response.status_code}")

    if response.status_code >= 300:
        logger.error(
            "Resend returned {} for {}",
            response.status_code,
            redacted,
        )
        raise EmailDeliveryError(f"Resend returned {response.status_code}")

    # Some Resend responses are 2xx but carry an error body; inspect the JSON
    # payload defensively. A malformed / non-JSON body is treated as success
    # because httpx would have raised before getting here for a transport
    # error, and the HTTP status already reported 2xx.
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and body.get("error"):
        logger.error("Resend 2xx-with-error body for {}", redacted)
        raise EmailDeliveryError("Resend returned 2xx with error payload")

    logger.info("Auth code delivered to {} via Resend", redacted)
