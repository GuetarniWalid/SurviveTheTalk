"""Story 8.3 (Task 5/D3) — subscription lifecycle WEBHOOKS (primary detection).

Apple App Store Server Notifications V2 + Google Play Real-Time Developer
Notifications (RTDN via Pub/Sub push) are the PRIMARY cancel / expire / renew /
refund / revoke signal; the 5-min expiry-downgrade sweep (`billing/revalidation`)
is the defense-in-depth backstop.

These routes are NOT on the app-JWT router — Apple/Google POST to them. Security:
  - Apple: the body is a signed JWS verified OFFLINE with the same
    `SignedDataVerifier` infra `validate_apple` uses (no App Store Server API
    key — D4 stays deferred). A forged/untrusted payload → 400.
  - Google: gated by a secret query token configured on the push subscription
    URL (`?token=<secret>`); mismatch/absent → 403, unconfigured → 503. The
    RTDN payload is otherwise untrusted — we re-call `validate_google` on the
    `purchaseToken` to get the AUTHORITATIVE state rather than trusting the
    notification body.

Both endpoints are IDEMPOTENT (dedup via `subscription_events`). Recovery model
(F1): the dedup row records on receipt but `processed_at` is the source of truth
for "the side effect landed". A genuine PROCESSING failure returns 500 (NOT a
swallowed 200) so the store retries on its bounded back-off; the retry hits the
already-recorded-but-UNPROCESSED row and RE-DRIVES the action, while a row whose
processing succeeded short-circuits as a benign replay. This recovers the
renewal/refund/revoke events the old always-200-on-error posture dropped forever.
(A verification/security failure stays a reject — 400/403, not a 500.)
"""

from __future__ import annotations

import base64
import binascii
import json
import secrets

from fastapi import APIRouter, HTTPException
from loguru import logger

from api.responses import now_iso, ok
from billing import (
    AppleNotification,
    AppleNotificationError,
    BillingConfigError,
    validate_google,
    verify_apple_notification,
)
from config import Settings
from db.database import get_connection
from db.queries import (
    count_user_valid_purchases,
    get_latest_purchase_by_token,
    get_purchase_by_original_transaction_id,
    get_purchase_by_transaction_id,
    mark_subscription_event_processed,
    record_subscription_event,
    update_purchase_validation,
    update_user_tier,
    user_has_active_entitlement,
)
from models.schemas import AppleWebhookIn, GoogleWebhookIn

# NO AUTH_DEPENDENCY — Apple/Google are the callers.
router = APIRouter(prefix="/subscription", tags=["subscription-webhooks"])

settings = Settings()

# Apple notification types that revert entitlement immediately.
_APPLE_DOWNGRADE_TYPES = frozenset(
    {"EXPIRED", "GRACE_PERIOD_EXPIRED", "REFUND", "REVOKE"}
)


# --------------------------------------------------------------------------
# Apple — App Store Server Notifications V2
# --------------------------------------------------------------------------


async def _process_apple_notification(db, notif: AppleNotification) -> None:
    """Act on a verified Apple notification (resolve user, flip tier/expiry).

    Resolves the user by the renewal-STABLE `originalTransactionId` (F3) — a
    DID_RENEW carries a NEW per-period `transactionId`, so resolving by it would
    miss every renewal; falls back to `transactionId` only for legacy rows
    predating the column. An unknown subscription is ACKed + logged. DID_RENEW
    re-stamps the expiry + keeps paid (atomically, F14); EXPIRED/
    GRACE_PERIOD_EXPIRED/REFUND/REVOKE downgrade to free CONDITIONALLY (F4 — not
    if the user is still entitled via another valid+future purchase);
    DID_CHANGE_RENEWAL_STATUS (cancel intent) keeps paid until expiry.
    """
    purchase = None
    if notif.original_transaction_id:
        purchase = await get_purchase_by_original_transaction_id(
            db, notif.original_transaction_id
        )
    if purchase is None and notif.transaction_id:
        purchase = await get_purchase_by_transaction_id(db, notif.transaction_id)
    if purchase is None:
        logger.info(
            f"apple webhook: no purchase row for "
            f"original_txn={notif.original_transaction_id} "
            f"txn={notif.transaction_id} type={notif.notification_type}"
        )
        return
    user_id = purchase["user_id"]
    ntype = notif.notification_type

    if ntype == "DID_RENEW":
        # F14 — re-stamp expiry + keep paid in ONE BEGIN IMMEDIATE so a crash
        # can't leave the purchase refreshed while the tier stays stale.
        await db.execute("BEGIN IMMEDIATE")
        try:
            await update_purchase_validation(
                db,
                purchase["id"],
                validation_status="valid",
                transaction_id=notif.transaction_id,
                original_transaction_id=notif.original_transaction_id,
                expires_at=notif.expires_at,
                validated_at=now_iso(),
                commit=False,
            )
            await update_user_tier(
                db, user_id, "paid", tier_changed_at=now_iso(), commit=False
            )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
        logger.info(
            f"apple webhook: DID_RENEW user={user_id} -> paid, expiry refreshed"
        )
    elif ntype in _APPLE_DOWNGRADE_TYPES:
        # F4 — downgrade CONDITIONALLY (mirror the Google webhook + expiry sweep):
        # a lapsing/refunded purchase must not clobber a user still entitled via a
        # SEPARATE valid+future purchase (e.g. a new-device re-subscribe). REFUND/
        # REVOKE void the entitlement outright → mark the row invalid so it stops
        # counting; EXPIRED/GRACE_PERIOD_EXPIRED merely lapsed it (the expiry-aware
        # check excludes a past-dated row WITHOUT rewriting its status, so a later
        # DID_RENEW can still re-grant). One BEGIN IMMEDIATE (F14).
        now = now_iso()
        await db.execute("BEGIN IMMEDIATE")
        try:
            if ntype in ("REFUND", "REVOKE"):
                await update_purchase_validation(
                    db,
                    purchase["id"],
                    validation_status="invalid",
                    transaction_id=notif.transaction_id,
                    original_transaction_id=notif.original_transaction_id,
                    expires_at=notif.expires_at,
                    validated_at=now,
                    commit=False,
                )
            still_entitled = await user_has_active_entitlement(
                db, user_id, now, exclude_purchase_id=purchase["id"]
            )
            if not still_entitled:
                await update_user_tier(
                    db, user_id, "free", tier_changed_at=now, commit=False
                )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
        if still_entitled:
            logger.info(
                f"apple webhook: {ntype} user={user_id} lapsed but keeps paid "
                "via another valid purchase"
            )
        else:
            logger.warning(f"apple webhook: {ntype} user={user_id} -> free")
    elif ntype == "DID_CHANGE_RENEWAL_STATUS":
        # Cancellation intent — keep paid until expiry (correct subscription
        # behaviour). The eventual EXPIRED notification / sweep does the revert.
        logger.info(
            f"apple webhook: DID_CHANGE_RENEWAL_STATUS (subtype={notif.subtype}) "
            f"user={user_id} — keep paid until expiry"
        )
    else:
        logger.info(f"apple webhook: unhandled type {ntype} user={user_id}")


@router.post("/webhook/apple")
async def apple_webhook(payload: AppleWebhookIn) -> dict:
    """Receive + offline-verify an App Store Server Notification V2.

    503 SUBSCRIPTION_UNAVAILABLE when Apple config is absent (pre-store-setup;
    Apple retries later). 400 WEBHOOK_INVALID on a forged/untrusted payload.
    200 (idempotent) once verified + processed. 500 WEBHOOK_PROCESSING_FAILED on
    a transient processing error so Apple retries and the event is re-driven (F1)
    — the dedup row keeps a successful replay idempotent.
    """
    try:
        notif = await verify_apple_notification(
            payload.signedPayload,
            bundle_id=settings.apple_bundle_id,
            app_apple_id=settings.apple_app_apple_id,
            accept_sandbox=settings.apple_accept_sandbox,
        )
    except BillingConfigError as exc:
        logger.error(f"apple webhook unavailable (config absent): {exc}")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SUBSCRIPTION_UNAVAILABLE",
                "message": "Subscriptions are temporarily unavailable.",
            },
        ) from exc
    except AppleNotificationError as exc:
        logger.warning(f"apple webhook rejected (verification failed): {exc}")
        raise HTTPException(
            status_code=400,
            detail={
                "code": "WEBHOOK_INVALID",
                "message": "Notification could not be verified.",
            },
        ) from exc

    if not notif.notification_uuid:
        # Can't dedup without the UUID; ACK so Apple doesn't retry-storm.
        logger.warning("apple webhook: notification without notificationUUID; acking")
        return ok({"received": True})

    async with get_connection() as db:
        status = await record_subscription_event(
            db,
            provider="apple",
            notification_id=notif.notification_uuid,
            notification_type=notif.notification_type,
            received_at=now_iso(),
        )
        if status == "replay_processed":
            # Genuine replay of an already-applied notification — no-op.
            return ok({"received": True})
        # "new" or "replay_unprocessed" (a prior delivery failed mid-processing,
        # F1) → (re-)process so a transiently-dropped lifecycle action recovers.
        try:
            await _process_apple_notification(db, notif)
            await mark_subscription_event_processed(
                db, notif.notification_uuid, now_iso()
            )
        except Exception as exc:
            # F1 — a genuine processing failure. Do NOT mark processed and do NOT
            # ack 200: return 500 so Apple RETRIES (its bounded back-off schedule),
            # and the retry hits "replay_unprocessed" above and re-drives. The
            # dedup row persists (processed_at NULL) so a SUCCESSFUL replay stays
            # idempotent. This reverses the prior always-200-on-processing-error
            # posture, which permanently dropped renewal/refund/revoke events.
            logger.exception("apple webhook processing error")
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "WEBHOOK_PROCESSING_FAILED",
                    "message": "Notification processing failed; will retry.",
                },
            ) from exc
    return ok({"received": True})


# --------------------------------------------------------------------------
# Google — Real-Time Developer Notifications (Pub/Sub push)
# --------------------------------------------------------------------------


async def _process_google_body(db, body: dict) -> None:
    """Act on a decoded RTDN body by RE-VALIDATING the purchaseToken.

    We trust the authoritative `validate_google` result, NOT the notification's
    own type: valid → keep paid + refresh expiry; invalid → mark the purchase
    invalid + downgrade (conditionally, mirroring the sweep — don't clobber a
    user still entitled via another valid purchase); unreachable → leave as-is.
    """
    sub = body.get("subscriptionNotification")
    if not isinstance(sub, dict):
        # testNotification / oneTimeProductNotification / voidedPurchase — n/a.
        logger.info("google webhook: non-subscription notification, ignored")
        return
    purchase_token = sub.get("purchaseToken")
    if not purchase_token:
        return
    purchase = await get_latest_purchase_by_token(db, purchase_token)
    if purchase is None:
        logger.info("google webhook: no purchase row for token (acking)")
        return
    user_id = purchase["user_id"]

    try:
        result = await validate_google(
            purchase_token,
            package_name=settings.google_play_package_name,
            product_id=settings.iap_product_id,
            service_account_json=settings.google_service_account_json,
        )
    except BillingConfigError:
        logger.error("google webhook: validate config absent; entitlement unchanged")
        return

    if result.status == "valid":
        # F14 — re-stamp expiry + keep paid in ONE BEGIN IMMEDIATE (mirror the
        # verify route's TX2 + the invalid branch below) so a crash can't leave
        # the purchase refreshed while the tier stays stale.
        await db.execute("BEGIN IMMEDIATE")
        try:
            await update_purchase_validation(
                db,
                purchase["id"],
                validation_status="valid",
                transaction_id=result.transaction_id,
                expires_at=result.expires_at,
                validated_at=now_iso(),
                commit=False,
            )
            await update_user_tier(
                db, user_id, "paid", tier_changed_at=now_iso(), commit=False
            )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
        logger.info(f"google webhook: user={user_id} -> paid, expiry refreshed")
    elif result.status == "invalid":
        await db.execute("BEGIN IMMEDIATE")
        try:
            await update_purchase_validation(
                db,
                purchase["id"],
                validation_status="invalid",
                transaction_id=result.transaction_id,
                expires_at=result.expires_at,
                validated_at=now_iso(),
                commit=False,
            )
            still_entitled = await count_user_valid_purchases(db, user_id) > 0
            if not still_entitled:
                await update_user_tier(
                    db, user_id, "free", tier_changed_at=now_iso(), commit=False
                )
            await db.commit()
        except BaseException:
            await db.rollback()
            raise
        if still_entitled:
            logger.info(
                f"google webhook: user={user_id} purchase invalid but keeps paid "
                "via another valid purchase"
            )
        else:
            logger.warning(f"google webhook: user={user_id} -> free (entitlement lost)")
    # 'unreachable' → leave entitlement unchanged (retry on the next signal).


@router.post("/webhook/google")
async def google_webhook(payload: GoogleWebhookIn, token: str | None = None) -> dict:
    """Receive a Google RTDN Pub/Sub push.

    Secured by the secret `?token=` configured on the push subscription URL:
    unconfigured → 503 (not wired); mismatch/absent → 403. Idempotent (dedup on
    Pub/Sub `messageId`); 200 on any handled processing error.
    """
    configured = settings.google_pubsub_verification_token
    if not configured:
        # Not wired to a live push yet — refuse rather than accept an
        # unauthenticated body (pre-store-config posture).
        logger.error("google webhook hit but GOOGLE_PUBSUB_VERIFICATION_TOKEN unset")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SUBSCRIPTION_UNAVAILABLE",
                "message": "Subscriptions are temporarily unavailable.",
            },
        )
    if token is None or not secrets.compare_digest(token, configured):
        logger.warning("google webhook rejected: bad/missing verification token")
        raise HTTPException(
            status_code=403,
            detail={
                "code": "WEBHOOK_FORBIDDEN",
                "message": "Invalid notification token.",
            },
        )

    msg = payload.message
    if not msg.data:
        # Empty push (e.g. a Pub/Sub keepalive) — ack.
        return ok({"received": True})
    try:
        body = json.loads(base64.b64decode(msg.data))
    except (ValueError, binascii.Error):
        logger.warning("google webhook: undecodable message.data; acking")
        return ok({"received": True})
    if not isinstance(body, dict):
        return ok({"received": True})

    sub = body.get("subscriptionNotification")
    ntype = str(sub.get("notificationType")) if isinstance(sub, dict) else None

    async with get_connection() as db:
        status = await record_subscription_event(
            db,
            provider="google",
            notification_id=msg.messageId,
            notification_type=ntype,
            received_at=now_iso(),
        )
        if status == "replay_processed":
            return ok({"received": True})  # replay of a handled messageId — no-op
        # "new" or "replay_unprocessed" (a prior delivery failed, F1) → (re-)process.
        try:
            await _process_google_body(db, body)
            await mark_subscription_event_processed(db, msg.messageId, now_iso())
        except Exception as exc:
            # F1 — genuine processing failure → 500 so Pub/Sub retries (bounded by
            # its ack-deadline/retention back-off); the retry hits
            # "replay_unprocessed" and re-drives. Dedup row persists so a
            # successful replay stays idempotent.
            logger.exception("google webhook processing error")
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "WEBHOOK_PROCESSING_FAILED",
                    "message": "Notification processing failed; will retry.",
                },
            ) from exc
    return ok({"received": True})
