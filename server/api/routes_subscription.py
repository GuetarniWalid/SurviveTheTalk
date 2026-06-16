"""Story 8.1 — `POST /subscription/verify` (validate a store purchase, flip tier).

The client sends the unified store artifact (iOS: StoreKit 2 signed-transaction
JWS; Android: Google `purchaseToken`); the server validates it FIRST-PARTY
(`billing/`) and flips `users.tier` to `'paid'` on success. Zero payment data is
ever handled (NFR11) — only the verification artifact.

Validation timing (Decision D2): synchronous validate-then-flip in the happy
path — `tier='paid'` is set only on a VALID result, closing the fraud window a
pure-optimistic flip would open. The optimistic grant (flip first, purchase
`'pending'`, background re-check) fires ONLY when the validator is UNREACHABLE
(store outage), preserving NFR26's intent (never permanently block a real buyer
on a transient outage). Scope = purchase plumbing only: Story 8.2 owns the real
paywall UI, Story 8.3 owns full tier-enforcement / cancellation handling.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from loguru import logger

from api.middleware import AUTH_DEPENDENCY
from api.responses import now_iso, ok
from billing import (
    BillingConfigError,
    ValidationResult,
    validate_apple,
    validate_google,
)
from config import Settings
from db.database import get_connection
from db.queries import (
    get_latest_purchase_by_token,
    get_user_by_id,
    insert_purchase,
    update_purchase_validation,
    update_user_tier,
)
from models.schemas import SubscriptionVerifyIn, SubscriptionVerifyOut

router = APIRouter(
    prefix="/subscription", tags=["subscription"], dependencies=[AUTH_DEPENDENCY]
)

settings = Settings()


async def _run_validation(platform: str, verification_data: str) -> ValidationResult:
    """Branch on platform → the right first-party validator.

    Passes `settings.iap_product_id` as the EXPECTED product so a valid receipt
    for a different product never unlocks ours. Raises `BillingConfigError` when
    the platform's server config is absent (caught by the handler → 503).
    """
    if platform == "ios":
        return await validate_apple(
            verification_data,
            bundle_id=settings.apple_bundle_id,
            expected_product_id=settings.iap_product_id,
            app_apple_id=settings.apple_app_apple_id,
        )
    return await validate_google(
        verification_data,
        package_name=settings.google_play_package_name,
        product_id=settings.iap_product_id,
        service_account_json=settings.google_service_account_json,
    )


@router.post("/verify")
async def verify_subscription(request: Request, payload: SubscriptionVerifyIn) -> dict:
    """Validate a store purchase artifact and flip the caller's tier to paid.

    Returns the `{data, meta}` envelope with the post-verify `tier` + the
    purchase `status` (`'valid'` on a confirmed grant, `'pending'` on a D2
    optimistic grant). 402 `PURCHASE_INVALID` on a definitively-rejected
    artifact (tier untouched). 503 `SUBSCRIPTION_UNAVAILABLE` when the store
    config is absent (a deploy problem — NOT an optimistic grant).
    """
    user_id: int = request.state.user_id

    async with get_connection() as db:
        # Idempotency — a client retry that re-POSTs an already-validated
        # artifact returns the current tier without re-validating or
        # double-inserting (Story 8.1 idempotency guard).
        existing = await get_latest_purchase_by_token(db, payload.verification_data)
        if existing is not None and existing["validation_status"] == "valid":
            user = await get_user_by_id(db, user_id)
            current_tier = user["tier"] if user is not None else "free"
            return ok(
                SubscriptionVerifyOut(
                    tier=current_tier,
                    product_id=settings.iap_product_id,
                    expires_at=existing["expires_at"],
                    status="valid",
                )
            )

        # Record the attempt up-front (validation_status defaults 'pending').
        purchase_id = await insert_purchase(
            db,
            user_id=user_id,
            platform=payload.platform,
            product_id=payload.product_id,
            verification_token=payload.verification_data,
            created_at=now_iso(),
        )

        try:
            result = await _run_validation(payload.platform, payload.verification_data)
        except BillingConfigError as exc:
            # Missing store config = a deploy problem. NOT a store outage (don't
            # optimistically grant) and NOT the user's receipt being invalid
            # (don't 402). Leave the purchase 'pending' + tier untouched.
            logger.error(f"subscription verify unavailable: {exc}")
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "SUBSCRIPTION_UNAVAILABLE",
                    "message": "Subscriptions are temporarily unavailable.",
                },
            ) from exc

        if result.status == "valid":
            await update_user_tier(db, user_id, "paid", tier_changed_at=now_iso())
            await update_purchase_validation(
                db,
                purchase_id,
                validation_status="valid",
                transaction_id=result.transaction_id,
                expires_at=result.expires_at,
                validated_at=now_iso(),
            )
            logger.info(
                f"subscription verified user={user_id} platform={payload.platform} "
                f"purchase={purchase_id} -> tier=paid"
            )
            return ok(
                SubscriptionVerifyOut(
                    tier="paid",
                    product_id=settings.iap_product_id,
                    expires_at=result.expires_at,
                    status="valid",
                )
            )

        if result.status == "unreachable":
            # D2 fallback — optimistic grant, purchase stays 'pending', the
            # background sweep (revalidate_pending_purchases) reconciles it.
            await update_user_tier(db, user_id, "paid", tier_changed_at=now_iso())
            logger.warning(
                f"subscription validator unreachable user={user_id} "
                f"platform={payload.platform} purchase={purchase_id} "
                f"({result.reason}) -> optimistic paid, pending re-check"
            )
            return ok(
                SubscriptionVerifyOut(
                    tier="paid",
                    product_id=settings.iap_product_id,
                    expires_at=result.expires_at,
                    status="pending",
                )
            )

        # Definitively invalid — do NOT flip tier; record + 402.
        await update_purchase_validation(
            db,
            purchase_id,
            validation_status="invalid",
            transaction_id=result.transaction_id,
            expires_at=result.expires_at,
            validated_at=now_iso(),
        )
        logger.warning(
            f"subscription verify rejected user={user_id} "
            f"platform={payload.platform} purchase={purchase_id} ({result.reason})"
        )
        raise HTTPException(
            status_code=402,
            detail={
                "code": "PURCHASE_INVALID",
                "message": "We couldn't validate that purchase.",
            },
        )
