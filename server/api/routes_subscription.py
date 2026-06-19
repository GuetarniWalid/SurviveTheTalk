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

import aiosqlite
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
            accept_sandbox=settings.apple_accept_sandbox,
        )
    return await validate_google(
        verification_data,
        package_name=settings.google_play_package_name,
        product_id=settings.iap_product_id,
        service_account_json=settings.google_service_account_json,
    )


def _respond_existing(existing: aiosqlite.Row, user_id: int, current_tier: str) -> dict:
    """Idempotent / replay response for a token already recorded (code-review 8.1).

    Called when `get_latest_purchase_by_token` already found a row, so the
    artifact must NOT be re-inserted or re-validated:

    - **Cross-user (F7):** the token belongs to a DIFFERENT account → 409. A
      store artifact proves the SUBSCRIPTION is active, not that the submitting
      account is the buyer, so a leaked/shared token must not entitle whoever
      replays it. (Full appAccountToken / obfuscatedAccountId buyer-binding is
      8.3; this closes the cheap cross-account replay now.)
    - **`valid`:** return the current tier (idempotent — a client retry of an
      already-validated artifact).
    - **`pending`:** a D2 optimistic grant is still being reconciled; return the
      current tier with `status='pending'` WITHOUT re-inserting/re-validating
      (F6 — the old guard fell through and double-inserted).
    - **`invalid`:** definitively rejected; 402 without re-validating (F6 —
      stops unbounded re-POST validator amplification of a forged token).
    """
    if existing["user_id"] != user_id:
        logger.warning(
            f"subscription cross-user replay user={user_id} "
            f"token-owner={existing['user_id']} purchase={existing['id']}"
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PURCHASE_CONFLICT",
                "message": "That purchase belongs to a different account.",
            },
        )

    status = existing["validation_status"]
    if status == "invalid":
        raise HTTPException(
            status_code=402,
            detail={
                "code": "PURCHASE_INVALID",
                "message": "We couldn't validate that purchase.",
            },
        )
    # 'valid' or 'pending' — echo the recorded state without side effects.
    return ok(
        SubscriptionVerifyOut(
            tier=current_tier,
            product_id=settings.iap_product_id,
            expires_at=existing["expires_at"],
            status=status,
        )
    )


@router.post("/verify")
async def verify_subscription(request: Request, payload: SubscriptionVerifyIn) -> dict:
    """Validate a store purchase artifact and flip the caller's tier to paid.

    Returns the `{data, meta}` envelope with the post-verify `tier` + the
    purchase `status` (`'valid'` on a confirmed grant, `'pending'` on a D2
    optimistic grant). 402 `PURCHASE_INVALID` on a definitively-rejected
    artifact (tier untouched). 409 `PURCHASE_CONFLICT` on a cross-account
    replay. 503 `SUBSCRIPTION_UNAVAILABLE` when the store config is absent.

    Transaction shape (code-review 8.1 F3): the idempotency check + the
    pending-row insert run together under one `BEGIN IMMEDIATE` (TX1) so two
    concurrent POSTs of the same artifact can't both insert; the store
    validation then runs WITHOUT holding any lock (it is 1-4 s of network I/O —
    holding the write lock across it would stall every other writer); finally
    the tier flip + audit stamp commit together under a second `BEGIN IMMEDIATE`
    (TX2) so a crash can't leave `paid` with an un-stamped row.
    """
    user_id: int = request.state.user_id

    async with get_connection() as db:
        # --- TX1: atomic idempotency check + insert (no network) ------------
        await db.execute("BEGIN IMMEDIATE")
        existing: aiosqlite.Row | None
        purchase_id: int | None = None
        try:
            existing = await get_latest_purchase_by_token(db, payload.verification_data)
            if existing is None:
                purchase_id = await insert_purchase(
                    db,
                    user_id=user_id,
                    platform=payload.platform,
                    # F9 — persist the SERVER-validated product id, never the
                    # client-supplied payload.product_id (audit-trail integrity).
                    product_id=settings.iap_product_id,
                    verification_token=payload.verification_data,
                    created_at=now_iso(),
                    commit=False,
                )
            await db.commit()
        except aiosqlite.IntegrityError:
            # UNIQUE(verification_token) backstop: a concurrent request inserted
            # the same artifact between our SELECT and INSERT. Re-read and treat
            # it as an idempotent re-entry.
            await db.rollback()
            existing = await get_latest_purchase_by_token(db, payload.verification_data)
        except BaseException:
            await db.rollback()
            raise

        if existing is not None:
            user = await get_user_by_id(db, user_id)
            current_tier = user["tier"] if user is not None else "free"
            return _respond_existing(existing, user_id, current_tier)

        assert purchase_id is not None  # fresh insert above set it

        # --- Validation: network I/O, NO lock held --------------------------
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
            # --- TX2: atomic tier flip + audit stamp ------------------------
            await db.execute("BEGIN IMMEDIATE")
            try:
                await update_user_tier(
                    db, user_id, "paid", tier_changed_at=now_iso(), commit=False
                )
                await update_purchase_validation(
                    db,
                    purchase_id,
                    validation_status="valid",
                    transaction_id=result.transaction_id,
                    # F3 — stamp the Apple renewal-stable id at first verify so
                    # later auto-renewal webhooks (new transaction_id) resolve
                    # back to this row. None for Google (purchaseToken-stable).
                    original_transaction_id=result.original_transaction_id,
                    expires_at=result.expires_at,
                    validated_at=now_iso(),
                    commit=False,
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
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
            original_transaction_id=result.original_transaction_id,
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
