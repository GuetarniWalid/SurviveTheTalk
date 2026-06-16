"""Google Play Billing purchase-token validation — Android side of Story 8.1.

Validates a Google Play `purchaseToken` against the Play Developer API
`purchases.subscriptionsv2` endpoint. Authenticated with a service account:
we mint an OAuth2 assertion JWT (RS256, signed with the service-account
private key via `pyjwt`), exchange it for an access token, then call the API
— all fully async over `httpx`. We deliberately do NOT pull in `google-auth`
(its default transport is the synchronous `requests` library, which would
block the event loop / force a thread hop and isn't even installed); `pyjwt`
+ `httpx` are already first-class dependencies and keep the whole path async.

Network failures (timeout / 5xx / DNS) return `status='unreachable'` so the
route's D2 fallback grants paid optimistically rather than blocking a real
buyer on a transient Google outage. A definitively rejected token returns
`status='invalid'`. A credentials/permission problem (our service account is
misconfigured) raises `BillingConfigError` → a 503, never an optimistic grant.
"""

from __future__ import annotations

import base64
import json
import time

import httpx
import jwt
from loguru import logger

from billing.models import BillingConfigError, ValidationResult

_TOKEN_URI_DEFAULT = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/androidpublisher"
_HTTP_TIMEOUT_SECONDS = 10.0
# subscriptionsv2 subscriptionState values that count as currently entitled.
_ACTIVE_STATES = frozenset(
    {"SUBSCRIPTION_STATE_ACTIVE", "SUBSCRIPTION_STATE_IN_GRACE_PERIOD"}
)


def _load_service_account(service_account_json: str) -> dict:
    """Decode the base64 service-account blob to a dict (validated at boot)."""
    return json.loads(base64.b64decode(service_account_json))


def _mint_assertion(service_account: dict) -> tuple[str, str]:
    """Return (token_uri, signed RS256 assertion JWT) for the OAuth exchange."""
    token_uri = service_account.get("token_uri") or _TOKEN_URI_DEFAULT
    now = int(time.time())
    claims = {
        "iss": service_account["client_email"],
        "scope": _SCOPE,
        "aud": token_uri,
        "iat": now,
        "exp": now + 3600,
    }
    assertion = jwt.encode(claims, service_account["private_key"], algorithm="RS256")
    return token_uri, assertion


async def validate_google(
    purchase_token: str,
    *,
    package_name: str,
    product_id: str,
    service_account_json: str,
) -> ValidationResult:
    """Validate a Google Play subscription `purchaseToken`.

    Raises `BillingConfigError` when the Android config is absent or the
    service account lacks permission (a deploy problem, mapped to 503 by the
    route — never an optimistic grant). Returns `unreachable` on a transient
    Google outage, `invalid` on a definitively-rejected token, `valid` on an
    ACTIVE / IN_GRACE_PERIOD subscription for the expected product.
    """
    if not package_name or not service_account_json:
        raise BillingConfigError(
            "Google Play config absent (GOOGLE_PLAY_PACKAGE_NAME / "
            "GOOGLE_SERVICE_ACCOUNT_JSON) — cannot validate Android purchases."
        )

    try:
        service_account = _load_service_account(service_account_json)
        token_uri, assertion = _mint_assertion(service_account)
    except (KeyError, ValueError, TypeError) as exc:
        # The blob is validated at boot, so this is defensive.
        raise BillingConfigError(
            f"Malformed Google service account ({type(exc).__name__})"
        ) from exc

    api_url = (
        "https://androidpublisher.googleapis.com/androidpublisher/v3/"
        f"applications/{package_name}/purchases/subscriptionsv2/tokens/{purchase_token}"
    )

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
            # 1. OAuth2 token exchange (service-account JWT bearer grant).
            token_resp = await client.post(
                token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
            if token_resp.status_code >= 500:
                logger.warning("google token endpoint 5xx: {}", token_resp.status_code)
                return ValidationResult(
                    valid=False, status="unreachable", reason="token_endpoint_5xx"
                )
            if token_resp.status_code != 200:
                # 4xx on the token exchange = OUR credentials are bad. Not a
                # store outage (don't optimistic-grant), not the user's fault.
                raise BillingConfigError(
                    f"Google OAuth token exchange failed: {token_resp.status_code}"
                )
            access_token = token_resp.json().get("access_token")
            if not access_token:
                raise BillingConfigError("Google token response had no access_token")

            # 2. Query the subscription state.
            api_resp = await client.get(
                api_url, headers={"Authorization": f"Bearer {access_token}"}
            )
    except httpx.HTTPError as exc:
        logger.warning("google validation transport error: {}", exc)
        return ValidationResult(
            valid=False, status="unreachable", reason=f"transport:{type(exc).__name__}"
        )

    if api_resp.status_code in (401, 403):
        # Our service account lacks androidpublisher permission on this app.
        raise BillingConfigError(
            f"Google Play API denied access ({api_resp.status_code}) — check "
            "the service account's app permissions."
        )
    if api_resp.status_code >= 500:
        logger.warning("google subscriptionsv2 5xx: {}", api_resp.status_code)
        return ValidationResult(valid=False, status="unreachable", reason="api_5xx")
    if api_resp.status_code != 200:
        # 400 / 404 / 410 — the token is malformed, unknown, or expired.
        return ValidationResult(
            valid=False, status="invalid", reason=f"api_{api_resp.status_code}"
        )

    body = api_resp.json()
    state = body.get("subscriptionState")
    line_items = body.get("lineItems") or []
    # A token for a DIFFERENT product must not unlock ours.
    product_ids = {item.get("productId") for item in line_items}
    if product_id not in product_ids:
        return ValidationResult(
            valid=False,
            status="invalid",
            reason=f"product_mismatch:{sorted(p for p in product_ids if p)!r}",
        )

    transaction_id = body.get("latestOrderId")
    # Latest expiry across the matching line items.
    expiries = [
        item.get("expiryTime")
        for item in line_items
        if item.get("productId") == product_id and item.get("expiryTime")
    ]
    expires_at = max(expiries) if expiries else None

    if state in _ACTIVE_STATES:
        return ValidationResult(
            valid=True,
            status="valid",
            transaction_id=transaction_id,
            expires_at=expires_at,
        )
    return ValidationResult(
        valid=False,
        status="invalid",
        transaction_id=transaction_id,
        expires_at=expires_at,
        reason=f"state:{state}",
    )
