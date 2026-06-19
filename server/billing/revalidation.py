"""Background re-validation of `'pending'` purchases (Story 8.1, D2 fallback).

The ONLY producer of a `'pending'` purchase is the D2 optimistic-grant path:
`POST /subscription/verify` could not REACH Apple/Google (a transient outage),
so it granted `tier='paid'` immediately to avoid blocking a real buyer and left
the purchase `'pending'` for a later re-check. This sweep is that re-check — the
concrete mechanism behind AC3 ("reverted on the next API call"):

  - re-validate `'valid'`  → mark the purchase `'valid'` (user stays paid).
  - re-validate `'invalid'`→ mark `'invalid'` AND flip the user back to `'free'`
    (stamp `tier_changed_at`). In 8.1 the only pending→invalid case is a forged
    artifact slipped through during an outage, so revoking is correct.
  - still `'unreachable'` / config absent → leave `'pending'`, retry next sweep.

Lives in `billing/` (not `api/`) for the same reason `db/janitor.py` does:
background maintenance is a cross-cutting concern, not API-layer code. The
validators are imported at module level so tests can patch them.
"""

from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite
from loguru import logger

from billing.apple_validator import validate_apple
from billing.google_validator import validate_google
from billing.models import BillingConfigError, ValidationResult
from config import Settings
from db.queries import (
    count_user_valid_purchases,
    get_pending_purchases,
    get_users_with_expired_entitlement,
    update_purchase_validation,
    update_user_tier,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


async def _validate_row(row: aiosqlite.Row, settings: Settings) -> ValidationResult:
    """Re-run the platform validator for one pending purchase row."""
    if row["platform"] == "ios":
        # (iOS offline crypto never returns 'unreachable', so an iOS row is never
        # actually 'pending' here — kept consistent with the route regardless.)
        return await validate_apple(
            row["verification_token"],
            bundle_id=settings.apple_bundle_id,
            expected_product_id=settings.iap_product_id,
            app_apple_id=settings.apple_app_apple_id,
            accept_sandbox=settings.apple_accept_sandbox,
        )
    return await validate_google(
        row["verification_token"],
        package_name=settings.google_play_package_name,
        product_id=settings.iap_product_id,
        service_account_json=settings.google_service_account_json,
    )


async def revalidate_pending_purchases(
    db: aiosqlite.Connection, *, settings: Settings, limit: int = 100
) -> int:
    """Re-validate up to `limit` pending purchases. Return the count resolved.

    Resolved = a definitive `'valid'` or `'invalid'` outcome was recorded this
    sweep. `'unreachable'` (still outage) and config-absent rows are left
    `'pending'` and counted as NOT resolved, so a permanently-broken store does
    not spin. Each validator does its own network I/O; a single row's failure is
    isolated so one bad row can't abort the batch.
    """
    rows = await get_pending_purchases(db, limit)
    resolved = 0
    for row in rows:
        try:
            result = await _validate_row(row, settings)
        except BillingConfigError:
            # Config not ready yet (pre-D4) — leave pending, try next sweep.
            continue
        except Exception:
            logger.exception(
                f"revalidation failed for purchase id={row['id']}; leaving pending"
            )
            continue

        if result.status == "valid":
            await update_purchase_validation(
                db,
                row["id"],
                validation_status="valid",
                transaction_id=result.transaction_id,
                original_transaction_id=result.original_transaction_id,
                expires_at=result.expires_at,
                validated_at=_now_iso(),
            )
            resolved += 1
        elif result.status == "invalid":
            # AC3 — revoke the optimistically-granted access, but CONDITIONALLY
            # (code-review 8.1 F2): mark this row invalid always, and downgrade
            # the user to 'free' ONLY when they hold no OTHER 'valid' purchase,
            # so a single stale pending row can't clobber a separately-entitled
            # user. Both writes commit together under one BEGIN IMMEDIATE so the
            # verify route can't interleave an opposite flip on the same user.
            await db.execute("BEGIN IMMEDIATE")
            try:
                await update_purchase_validation(
                    db,
                    row["id"],
                    validation_status="invalid",
                    transaction_id=result.transaction_id,
                    original_transaction_id=result.original_transaction_id,
                    expires_at=result.expires_at,
                    validated_at=_now_iso(),
                    commit=False,
                )
                still_entitled = (
                    await count_user_valid_purchases(db, row["user_id"]) > 0
                )
                if not still_entitled:
                    await update_user_tier(
                        db,
                        row["user_id"],
                        "free",
                        tier_changed_at=_now_iso(),
                        commit=False,
                    )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
            if still_entitled:
                logger.info(
                    f"purchase id={row['id']} re-validated invalid "
                    f"({result.reason}) — user {row['user_id']} keeps paid via "
                    "another valid purchase"
                )
            else:
                logger.warning(
                    f"reverted user {row['user_id']} to free — purchase "
                    f"id={row['id']} re-validated invalid ({result.reason})"
                )
            resolved += 1
        # 'unreachable' → leave pending.
    return resolved


async def downgrade_expired_entitlements(
    db: aiosqlite.Connection, *, now: datetime | None = None
) -> int:
    """Flip lapsed paid users back to free (Story 8.3 Task 4, AC6 backstop).

    The lifecycle WEBHOOKS (Task 5) are the PRIMARY cancel/expiry signal; this
    5-min sweep is the defense-in-depth backstop for a missed / misconfigured
    webhook. A user is "expired" when they are `tier='paid'` but hold NO
    `'valid'` purchase with `expires_at > now`
    (`get_users_with_expired_entitlement`). For each, atomically flip
    `tier->'free'` and stamp `tier_changed_at`.

    The purchase row is deliberately NOT mutated — it was validly issued and
    simply stopped granting because `expires_at <= now`, so a later
    `DID_RENEW` / re-verify can re-grant without re-inserting. Idempotent (a
    user already free is not in the worklist) and fail-soft per user (one
    failure cannot abort the batch). Returns the count downgraded.
    """
    if now is None:
        now = datetime.now(UTC)
    now_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    users = await get_users_with_expired_entitlement(db, now_iso)
    downgraded = 0
    for user in users:
        try:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await update_user_tier(
                    db, user["id"], "free", tier_changed_at=now_iso, commit=False
                )
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
        except Exception:
            logger.exception(
                f"expiry-downgrade failed for user {user['id']}; leaving paid"
            )
            continue
        downgraded += 1
        logger.warning(
            f"expiry-downgrade: user {user['id']} paid->free (entitlement lapsed)"
        )
    return downgraded
