"""Library-agnostic value types for the billing/validation layer.

The public interface of `billing/` is intentionally decoupled from whatever
library does the actual Apple/Google verification (today: Apple's
`app-store-server-library` for the JWS, raw `pyjwt`+`httpx` for Google). The
route never imports a vendor type — it branches on `ValidationResult.status`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# 'valid'       — the store confirmed the purchase; flip tier to 'paid'.
# 'invalid'     — the store rejected it (bad signature, wrong product/bundle,
#                 expired, refunded, or a definitive "not active"); do NOT flip.
# 'unreachable' — we could not REACH the store (timeout / 5xx / DNS). This is
#                 the ONLY status that triggers Story 8.1 D2's optimistic
#                 grant + 'pending' + background re-check, so a paying user is
#                 never permanently blocked by a transient store outage.
ValidationStatus = Literal["valid", "invalid", "unreachable"]


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a store purchase artifact (JWS / purchaseToken)."""

    valid: bool
    status: ValidationStatus
    transaction_id: str | None = None
    expires_at: str | None = None
    reason: str | None = None
    # Story 8.3 (F3) — the renewal-STABLE id. Apple mints a fresh
    # `transaction_id` for every auto-renewal period; only
    # `original_transaction_id` is constant across the subscription lifecycle,
    # so the webhook must resolve the user by it (a DID_RENEW carries a NEW
    # transaction_id that would otherwise match no purchase row). Google's
    # `purchaseToken` is already renewal-stable, so this stays None there.
    original_transaction_id: str | None = None


class BillingConfigError(Exception):
    """Raised when a validator is invoked but its platform's server config is
    absent (e.g. no `APPLE_BUNDLE_ID`, no `GOOGLE_SERVICE_ACCOUNT_JSON`).

    A missing config is a DEPLOYMENT error, NOT a store outage and NOT fraud:
    the route maps it to a shaped 503 `SUBSCRIPTION_UNAVAILABLE` so it neither
    optimistically grants paid (the 'unreachable' path) nor tells the user
    their genuine receipt is invalid (the 'invalid' path).
    """
