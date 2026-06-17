"""StoreKit 2 signed-transaction (JWS) validation — Apple side of Story 8.1.

Apple's `verifyReceipt` is DEPRECATED. The modern path is to forward the
StoreKit 2 signed-transaction JWS from the device and verify it server-side:
verify the x5c certificate chain up to Apple's root, then assert the payload's
bundleId / productId / expiry / revocation. We delegate the crypto to Apple's
official `app-store-server-library` (`SignedDataVerifier`, offline mode — no
network), supplying Apple Root CA - G3 ourselves (`billing/apple_roots.py`).

Returns a library-agnostic `ValidationResult` so the route never sees an
`appstoreserverlibrary` type. Offline JWS verification is pure crypto (no
store round-trip), so this path produces only `valid` / `invalid` — the
`unreachable` status is reserved for the Google network path (and a future
App Store Server API online-revocation check).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import jwt
from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.signed_data_verifier import (
    SignedDataVerifier,
    VerificationException,
)
from loguru import logger

from billing.apple_roots import apple_root_certificates
from billing.models import BillingConfigError, ValidationResult


def _ms_to_iso(ms: int | None) -> str | None:
    """Apple timestamps are epoch milliseconds; convert to our `Z` ISO 8601."""
    if ms is None:
        return None
    return (
        datetime.fromtimestamp(ms / 1000, UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _verify_sync(
    jws: str,
    *,
    bundle_id: str,
    expected_product_id: str,
    app_apple_id: int | None,
    accept_sandbox: bool,
) -> ValidationResult:
    """Blocking JWS verification (CPU-bound crypto). Run via `to_thread`."""
    # 1. Read the (UNVERIFIED) payload to learn the environment so we can build
    #    the verifier for the right one. The signature is verified in step 2 —
    #    this peek only selects Sandbox vs Production.
    try:
        unverified = jwt.decode(jws, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        return ValidationResult(
            valid=False,
            status="invalid",
            reason=f"unparseable_jws:{type(exc).__name__}",
        )

    raw_env = unverified.get("environment")
    try:
        environment = Environment(raw_env)
    except ValueError:
        return ValidationResult(
            valid=False, status="invalid", reason=f"unknown_environment:{raw_env!r}"
        )

    # ⚠️ SECURITY (code-review 8.1 F1) — `environment` is read from the UNVERIFIED
    # payload, and Apple's `SignedDataVerifier` SKIPS signature + x5c-chain
    # verification entirely for the Xcode / LocalTesting environments
    # (`_decode_signed_object` returns the decoded JWT unchecked, trusting the
    # caller to gate those environments). `Environment('Xcode')` /
    # `Environment('LocalTesting')` are VALID enum members, so without this guard
    # an attacker can self-sign a JWS with `environment:'Xcode'` and bypass ALL
    # crypto → a fabricated receipt grants tier=paid. Only PRODUCTION and SANDBOX
    # run the real verification path, so reject anything else BEFORE building the
    # verifier (the skip path becomes unreachable).
    if environment not in (Environment.PRODUCTION, Environment.SANDBOX):
        return ValidationResult(
            valid=False,
            status="invalid",
            reason=f"untrusted_environment:{raw_env!r}",
        )

    # A genuine Apple SANDBOX receipt is signature-valid but any tester mints
    # them for free, so a PRODUCTION deploy must not grant paid on one. Gate
    # sandbox acceptance behind an explicit opt-in (default off, see
    # `APPLE_ACCEPT_SANDBOX`) that is flipped on only for the on-device sandbox
    # smoke gate.
    if environment == Environment.SANDBOX and not accept_sandbox:
        return ValidationResult(
            valid=False, status="invalid", reason="sandbox_rejected"
        )

    # Production transaction verification requires the numeric app id (the
    # library enforces it). Absent → a config gap, not a fraud signal.
    if environment == Environment.PRODUCTION and app_apple_id is None:
        raise BillingConfigError(
            "APPLE_APP_APPLE_ID is required to verify a Production StoreKit "
            "transaction (set it once the App Store app id is known)."
        )

    verifier = SignedDataVerifier(
        root_certificates=apple_root_certificates(),
        enable_online_checks=False,
        environment=environment,
        bundle_id=bundle_id,
        app_apple_id=app_apple_id,
    )

    # 2. Verify signature + chain + bundle/environment match.
    try:
        payload = verifier.verify_and_decode_signed_transaction(jws)
    except VerificationException as exc:
        # F19 — keep the propagated `reason` a stable code; the detail (which can
        # embed chain/bundle identifiers) goes to the log, not the reason string.
        logger.warning("Apple JWS verification failed: {}", exc)
        return ValidationResult(
            valid=False, status="invalid", reason="verification_failed"
        )

    # 3. Product match — a valid receipt for the WRONG product must not unlock.
    if payload.productId != expected_product_id:
        return ValidationResult(
            valid=False,
            status="invalid",
            reason=f"product_mismatch:{payload.productId!r}",
        )

    # 4. Revoked (refunded / family-shared revoke) → not entitled.
    if payload.revocationDate is not None:
        return ValidationResult(
            valid=False,
            status="invalid",
            transaction_id=payload.transactionId,
            reason="revoked",
        )

    # 5. Expired subscription → not currently entitled.
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    if payload.expiresDate is not None and payload.expiresDate <= now_ms:
        return ValidationResult(
            valid=False,
            status="invalid",
            transaction_id=payload.transactionId,
            expires_at=_ms_to_iso(payload.expiresDate),
            reason="expired",
        )

    return ValidationResult(
        valid=True,
        status="valid",
        transaction_id=payload.transactionId,
        expires_at=_ms_to_iso(payload.expiresDate),
    )


async def validate_apple(
    jws: str,
    *,
    bundle_id: str,
    expected_product_id: str,
    app_apple_id: int | None = None,
    accept_sandbox: bool = False,
) -> ValidationResult:
    """Validate a StoreKit 2 signed-transaction JWS (offline x5c verification).

    Raises `BillingConfigError` when `bundle_id` is empty (no Apple config on
    this deploy) or a Production transaction arrives without `app_apple_id`.
    Never raises for an untrusted/forged/expired artifact — those return
    `ValidationResult(status='invalid')`. `accept_sandbox` (default off) opts
    a deploy into granting paid on genuine Apple SANDBOX receipts — only for
    the on-device sandbox smoke gate; a forged Xcode/LocalTesting environment
    is rejected regardless (code-review 8.1 F1).
    """
    if not bundle_id:
        raise BillingConfigError(
            "APPLE_BUNDLE_ID is not configured — cannot validate iOS purchases."
        )

    try:
        return await asyncio.to_thread(
            _verify_sync,
            jws,
            bundle_id=bundle_id,
            expected_product_id=expected_product_id,
            app_apple_id=app_apple_id,
            accept_sandbox=accept_sandbox,
        )
    except BillingConfigError:
        raise
    except Exception as exc:  # pragma: no cover - defensive belt
        # Any unexpected crash inside the verifier maps to 'invalid' (NOT
        # 'unreachable' — there is no network here, so this is not an outage;
        # treating it as unreachable would optimistically grant paid on a code
        # bug). Logged so the operator can see it.
        logger.exception("Unexpected error verifying Apple JWS")
        return ValidationResult(
            valid=False,
            status="invalid",
            reason=f"validator_error:{type(exc).__name__}",
        )
