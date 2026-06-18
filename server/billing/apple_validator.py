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
from dataclasses import dataclass
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


# --- Story 8.3 (Task 5) — App Store Server Notifications V2 (webhook) -------


@dataclass(frozen=True)
class AppleNotification:
    """The fields of an offline-verified App Store Server Notification V2 the
    webhook acts on. `notification_type` (+ optional `subtype`) drives the
    lifecycle action; `notification_uuid` is the dedup key; the nested
    transaction info (when present) supplies `transaction_id` / `product_id` /
    `expires_at` used to resolve the user + re-stamp the entitlement.
    """

    notification_type: str | None
    subtype: str | None
    notification_uuid: str | None
    transaction_id: str | None
    product_id: str | None
    expires_at: str | None
    environment: str | None


class AppleNotificationError(Exception):
    """Raised when an App Store Server Notification fails OFFLINE verification
    (forged signature, untrusted/sandbox-rejected environment, unparseable
    payload). The webhook route maps it to a 400 reject — DISTINCT from
    `BillingConfigError` (no Apple config → 503) so a genuine misconfig retries
    later while a forged payload is rejected outright."""


def _verify_notification_sync(
    signed_payload: str,
    *,
    bundle_id: str,
    app_apple_id: int | None,
    accept_sandbox: bool,
) -> AppleNotification:
    """Blocking offline verification of a notification JWS (run via to_thread).

    Mirrors `_verify_sync`'s F1 guard: the environment is read from the
    UNVERIFIED payload only to select the verifier; Xcode/LocalTesting (which
    `SignedDataVerifier` would skip-verify) are rejected BEFORE the verifier is
    built so a self-signed `environment:'Xcode'` notification cannot forge a
    downgrade/renewal.
    """
    try:
        unverified = jwt.decode(signed_payload, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise AppleNotificationError(f"unparseable_jws:{type(exc).__name__}") from exc

    data = unverified.get("data") if isinstance(unverified, dict) else None
    raw_env = data.get("environment") if isinstance(data, dict) else None
    try:
        environment = Environment(raw_env)
    except ValueError as exc:
        raise AppleNotificationError(f"unknown_environment:{raw_env!r}") from exc

    if environment not in (Environment.PRODUCTION, Environment.SANDBOX):
        raise AppleNotificationError(f"untrusted_environment:{raw_env!r}")
    if environment == Environment.SANDBOX and not accept_sandbox:
        raise AppleNotificationError("sandbox_rejected")
    if environment == Environment.PRODUCTION and app_apple_id is None:
        raise BillingConfigError(
            "APPLE_APP_APPLE_ID is required to verify a Production notification."
        )

    verifier = SignedDataVerifier(
        root_certificates=apple_root_certificates(),
        enable_online_checks=False,
        environment=environment,
        bundle_id=bundle_id,
        app_apple_id=app_apple_id,
    )
    try:
        decoded = verifier.verify_and_decode_notification(signed_payload)
    except VerificationException as exc:
        logger.warning("Apple notification verification failed: {}", exc)
        raise AppleNotificationError("verification_failed") from exc

    txn_id: str | None = None
    product_id: str | None = None
    expires_at: str | None = None
    data_obj = decoded.data
    if data_obj is not None and data_obj.signedTransactionInfo:
        try:
            txn = verifier.verify_and_decode_signed_transaction(
                data_obj.signedTransactionInfo
            )
            txn_id = txn.transactionId
            product_id = txn.productId
            expires_at = _ms_to_iso(txn.expiresDate)
        except VerificationException as exc:
            # The notification itself verified; only the nested txn JWS didn't.
            # Keep the type + uuid so type-driven actions still fire.
            logger.warning("Apple notification txn-info verification failed: {}", exc)

    return AppleNotification(
        notification_type=decoded.rawNotificationType,
        subtype=decoded.rawSubtype,
        notification_uuid=decoded.notificationUUID,
        transaction_id=txn_id,
        product_id=product_id,
        expires_at=expires_at,
        environment=raw_env,
    )


async def verify_apple_notification(
    signed_payload: str,
    *,
    bundle_id: str,
    app_apple_id: int | None = None,
    accept_sandbox: bool = False,
) -> AppleNotification:
    """Offline-verify an App Store Server Notification V2 `signedPayload`.

    Raises `BillingConfigError` when `bundle_id` is empty (no Apple config) or a
    Production notification arrives without `app_apple_id`; raises
    `AppleNotificationError` for a forged / untrusted / unparseable payload.
    Returns the extracted `AppleNotification` on success. Uses the SAME
    `SignedDataVerifier` infra as `validate_apple` — NO App Store Server API key
    needed (D4 stays deferred); the pushed JWS is self-contained.
    """
    if not bundle_id:
        raise BillingConfigError(
            "APPLE_BUNDLE_ID is not configured — cannot verify Apple notifications."
        )
    return await asyncio.to_thread(
        _verify_notification_sync,
        signed_payload,
        bundle_id=bundle_id,
        app_apple_id=app_apple_id,
        accept_sandbox=accept_sandbox,
    )
