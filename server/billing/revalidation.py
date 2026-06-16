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
    get_pending_purchases,
    update_purchase_validation,
    update_user_tier,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


async def _validate_row(row: aiosqlite.Row, settings: Settings) -> ValidationResult:
    """Re-run the platform validator for one pending purchase row."""
    if row["platform"] == "ios":
        return await validate_apple(
            row["verification_token"],
            bundle_id=settings.apple_bundle_id,
            expected_product_id=settings.iap_product_id,
            app_apple_id=settings.apple_app_apple_id,
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
                expires_at=result.expires_at,
                validated_at=_now_iso(),
            )
            resolved += 1
        elif result.status == "invalid":
            await update_purchase_validation(
                db,
                row["id"],
                validation_status="invalid",
                transaction_id=result.transaction_id,
                expires_at=result.expires_at,
                validated_at=_now_iso(),
            )
            # AC3 — revoke the optimistically-granted access.
            await update_user_tier(
                db, row["user_id"], "free", tier_changed_at=_now_iso()
            )
            logger.warning(
                f"reverted user {row['user_id']} to free — purchase "
                f"id={row['id']} re-validated invalid ({result.reason})"
            )
            resolved += 1
        # 'unreachable' → leave pending.
    return resolved
