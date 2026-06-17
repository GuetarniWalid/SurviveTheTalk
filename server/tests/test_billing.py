"""Unit tests for the billing validators (Story 8.1).

The Apple path is exercised only for its config-guard + the pinned-root
integrity (full JWS verification needs a real Apple-signed transaction, which
arrives at the on-device smoke gate gated on D4 / Story 10-4). The Google path
is exercised end-to-end with a FAKE httpx client + a patched assertion minter,
so the HTTP-status → ValidationResult branching is covered without a network
call or a real RSA key.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime

import httpx
import jwt
import pytest

from billing import validate_apple, validate_google
from billing.apple_roots import apple_root_certificates
from billing.models import BillingConfigError

_SA_JSON_B64 = base64.b64encode(
    b'{"client_email":"x@y.iam.gserviceaccount.com",'
    b'"private_key":"-----BEGIN PRIVATE KEY-----\\n...","token_uri":'
    b'"https://oauth2.googleapis.com/token"}'
).decode()


class _FakeResp:
    def __init__(self, status_code: int, json_data: dict | None = None) -> None:
        self.status_code = status_code
        self._json = json_data or {}

    def json(self) -> dict:
        return self._json


class _FakeClient:
    """Minimal stand-in for httpx.AsyncClient as an async context manager."""

    def __init__(
        self,
        token_resp: _FakeResp | None = None,
        api_resp: _FakeResp | None = None,
        post_exc: Exception | None = None,
    ) -> None:
        self._token_resp = token_resp
        self._api_resp = api_resp
        self._post_exc = post_exc
        self.last_get_url: str | None = None  # F8 — capture the subscriptionsv2 URL

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, *args, **kwargs) -> _FakeResp:
        if self._post_exc is not None:
            raise self._post_exc
        return self._token_resp  # type: ignore[return-value]

    async def get(self, url: str, *args, **kwargs) -> _FakeResp:
        self.last_get_url = url
        return self._api_resp  # type: ignore[return-value]


def _patch_google(monkeypatch, fake_client: _FakeClient) -> None:
    """Skip real RSA minting + inject the fake httpx client."""
    monkeypatch.setattr(
        "billing.google_validator._mint_assertion",
        lambda sa: ("https://oauth2.googleapis.com/token", "fake-assertion"),
    )
    monkeypatch.setattr(
        "billing.google_validator.httpx.AsyncClient", lambda *a, **k: fake_client
    )


# --------------------------------------------------------------------------
# Apple
# --------------------------------------------------------------------------


def test_apple_roots_integrity() -> None:
    """Exactly one pinned Apple root, and it survived the fingerprint check
    at import (a tampered cert would have raised RuntimeError)."""
    roots = apple_root_certificates()
    assert len(roots) == 1
    assert isinstance(roots[0], bytes)


def test_validate_apple_config_absent_raises() -> None:
    """No APPLE_BUNDLE_ID → BillingConfigError (route maps to 503)."""
    with pytest.raises(BillingConfigError):
        asyncio.run(
            validate_apple(
                "any.jws", bundle_id="", expected_product_id="stt_weekly_199"
            )
        )


_BUNDLE = "com.surviveTheTalk.client"


def _forged_jws(environment: str, **extra) -> str:
    """A self-signed (attacker) JWS — NO Apple key, NO x5c chain. The payload's
    `environment` is what the validator peeks at before verification."""
    return jwt.encode(
        {
            "environment": environment,
            "bundleId": _BUNDLE,
            "productId": "stt_weekly_199",
            **extra,
        },
        "attacker-secret-key-padded-to-32-bytes-min",
        algorithm="HS256",
    )


def _run_apple(jws: str, **kwargs):
    defaults = dict(bundle_id=_BUNDLE, expected_product_id="stt_weekly_199")
    defaults.update(kwargs)
    return asyncio.run(validate_apple(jws, **defaults))


def test_validate_apple_forged_xcode_environment_is_invalid() -> None:
    """🔴 F1 regression — a forged `environment:'Xcode'` JWS must be REJECTED.

    Apple's SignedDataVerifier skips signature/x5c verification for the Xcode /
    LocalTesting environments, so without the allowlist guard a self-signed JWS
    would validate as paid. This drives the REAL unverified-environment path
    (no verifier mock) and asserts it fails closed."""
    result = _run_apple(_forged_jws("Xcode"))
    assert result.valid is False
    assert result.status == "invalid"
    assert "untrusted_environment" in (result.reason or "")


def test_validate_apple_forged_localtesting_environment_is_invalid() -> None:
    """F1 sibling — LocalTesting also skips verification; must be rejected."""
    result = _run_apple(_forged_jws("LocalTesting"))
    assert result.status == "invalid"
    assert "untrusted_environment" in (result.reason or "")


def test_validate_apple_unknown_environment_is_invalid() -> None:
    result = _run_apple(_forged_jws("Bogus"))
    assert result.status == "invalid"
    assert "unknown_environment" in (result.reason or "")


def test_validate_apple_unparseable_jws_is_invalid() -> None:
    result = _run_apple("not-a-jws")
    assert result.status == "invalid"
    assert "unparseable_jws" in (result.reason or "")


def test_validate_apple_sandbox_rejected_by_default() -> None:
    """A GENUINE Sandbox receipt must NOT grant paid on a default deploy — the
    rejection fires before verification (so a forged Sandbox JWS suffices)."""
    result = _run_apple(_forged_jws("Sandbox"))  # accept_sandbox defaults False
    assert result.status == "invalid"
    assert result.reason == "sandbox_rejected"


def test_validate_apple_sandbox_accepted_reaches_verification() -> None:
    """With APPLE_ACCEPT_SANDBOX on, a Sandbox JWS gets PAST the gate to real
    verification — a forged one then fails the signature (verification_failed),
    proving the flag opens the gate rather than short-circuiting on sandbox."""
    result = _run_apple(_forged_jws("Sandbox"), accept_sandbox=True)
    assert result.status == "invalid"
    assert result.reason == "verification_failed"


def test_validate_apple_production_without_app_id_is_config_error() -> None:
    """A Production transaction needs the numeric app id; absent → config error
    (503), NOT a fraud signal. Fires before the verifier."""
    with pytest.raises(BillingConfigError):
        _run_apple(_forged_jws("Production"), app_apple_id=None)


class _FakePayload:
    def __init__(
        self, productId, expiresDate=None, revocationDate=None, transactionId="TX1"
    ):
        self.productId = productId
        self.expiresDate = expiresDate
        self.revocationDate = revocationDate
        self.transactionId = transactionId


def _patch_apple_verifier(monkeypatch, payload: _FakePayload) -> None:
    """Stand in for SignedDataVerifier so the post-signature branches
    (product / revoked / expired / valid) are testable without a real Apple
    transaction. Only reached for Production/Sandbox env past the F1 guard."""

    class _FakeVerifier:
        def __init__(self, **kwargs) -> None:
            pass

        def verify_and_decode_signed_transaction(self, jws):
            return payload

    monkeypatch.setattr("billing.apple_validator.SignedDataVerifier", _FakeVerifier)


def _future_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000) + 86_400_000


def _past_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000) - 86_400_000


def test_validate_apple_production_valid(monkeypatch) -> None:
    _patch_apple_verifier(
        monkeypatch,
        _FakePayload("stt_weekly_199", expiresDate=_future_ms(), transactionId="TX9"),
    )
    result = _run_apple(_forged_jws("Production"), app_apple_id=123)
    assert result.valid is True
    assert result.status == "valid"
    assert result.transaction_id == "TX9"


def test_validate_apple_product_mismatch_is_invalid(monkeypatch) -> None:
    _patch_apple_verifier(
        monkeypatch, _FakePayload("some_other_product", expiresDate=_future_ms())
    )
    result = _run_apple(_forged_jws("Production"), app_apple_id=123)
    assert result.status == "invalid"
    assert "product_mismatch" in (result.reason or "")


def test_validate_apple_revoked_is_invalid(monkeypatch) -> None:
    _patch_apple_verifier(
        monkeypatch,
        _FakePayload(
            "stt_weekly_199", expiresDate=_future_ms(), revocationDate=_past_ms()
        ),
    )
    result = _run_apple(_forged_jws("Production"), app_apple_id=123)
    assert result.status == "invalid"
    assert result.reason == "revoked"


def test_validate_apple_expired_is_invalid(monkeypatch) -> None:
    _patch_apple_verifier(
        monkeypatch, _FakePayload("stt_weekly_199", expiresDate=_past_ms())
    )
    result = _run_apple(_forged_jws("Production"), app_apple_id=123)
    assert result.status == "invalid"
    assert result.reason == "expired"


# --------------------------------------------------------------------------
# Google
# --------------------------------------------------------------------------


def test_validate_google_config_absent_raises() -> None:
    with pytest.raises(BillingConfigError):
        asyncio.run(
            validate_google(
                "token",
                package_name="",
                product_id="stt_weekly_199",
                service_account_json="",
            )
        )


def test_validate_google_active_is_valid(monkeypatch) -> None:
    fake = _FakeClient(
        token_resp=_FakeResp(200, {"access_token": "ya29.abc"}),
        api_resp=_FakeResp(
            200,
            {
                "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
                "latestOrderId": "GPA.1",
                "lineItems": [
                    {
                        "productId": "stt_weekly_199",
                        "expiryTime": "2026-06-23T00:00:00Z",
                    }
                ],
            },
        ),
    )
    _patch_google(monkeypatch, fake)

    result = asyncio.run(
        validate_google(
            "token",
            package_name="com.surviveTheTalk.client",
            product_id="stt_weekly_199",
            service_account_json=_SA_JSON_B64,
        )
    )
    assert result.valid is True
    assert result.status == "valid"
    assert result.transaction_id == "GPA.1"
    assert result.expires_at == "2026-06-23T00:00:00Z"


def test_validate_google_wrong_product_is_invalid(monkeypatch) -> None:
    fake = _FakeClient(
        token_resp=_FakeResp(200, {"access_token": "ya29.abc"}),
        api_resp=_FakeResp(
            200,
            {
                "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
                "lineItems": [{"productId": "some_other_product"}],
            },
        ),
    )
    _patch_google(monkeypatch, fake)

    result = asyncio.run(
        validate_google(
            "token",
            package_name="com.surviveTheTalk.client",
            product_id="stt_weekly_199",
            service_account_json=_SA_JSON_B64,
        )
    )
    assert result.status == "invalid"
    assert "product_mismatch" in (result.reason or "")


def test_validate_google_expired_state_is_invalid(monkeypatch) -> None:
    fake = _FakeClient(
        token_resp=_FakeResp(200, {"access_token": "ya29.abc"}),
        api_resp=_FakeResp(
            200,
            {
                "subscriptionState": "SUBSCRIPTION_STATE_EXPIRED",
                "lineItems": [{"productId": "stt_weekly_199"}],
            },
        ),
    )
    _patch_google(monkeypatch, fake)

    result = asyncio.run(
        validate_google(
            "token",
            package_name="com.surviveTheTalk.client",
            product_id="stt_weekly_199",
            service_account_json=_SA_JSON_B64,
        )
    )
    assert result.status == "invalid"


def test_validate_google_transport_error_is_unreachable(monkeypatch) -> None:
    fake = _FakeClient(post_exc=httpx.ConnectError("dns boom"))
    _patch_google(monkeypatch, fake)

    result = asyncio.run(
        validate_google(
            "token",
            package_name="com.surviveTheTalk.client",
            product_id="stt_weekly_199",
            service_account_json=_SA_JSON_B64,
        )
    )
    assert result.status == "unreachable"


def test_validate_google_token_4xx_is_config_error(monkeypatch) -> None:
    """A 4xx on the OAuth token exchange = OUR credentials are bad → config
    error (503), NOT an optimistic grant."""
    fake = _FakeClient(token_resp=_FakeResp(400, {"error": "invalid_grant"}))
    _patch_google(monkeypatch, fake)

    with pytest.raises(BillingConfigError):
        asyncio.run(
            validate_google(
                "token",
                package_name="com.surviveTheTalk.client",
                product_id="stt_weekly_199",
                service_account_json=_SA_JSON_B64,
            )
        )


def test_validate_google_api_5xx_is_unreachable(monkeypatch) -> None:
    fake = _FakeClient(
        token_resp=_FakeResp(200, {"access_token": "ya29.abc"}),
        api_resp=_FakeResp(503),
    )
    _patch_google(monkeypatch, fake)

    result = asyncio.run(
        validate_google(
            "token",
            package_name="com.surviveTheTalk.client",
            product_id="stt_weekly_199",
            service_account_json=_SA_JSON_B64,
        )
    )
    assert result.status == "unreachable"


def _run_google(monkeypatch, fake: _FakeClient, token: str = "token"):
    _patch_google(monkeypatch, fake)
    return asyncio.run(
        validate_google(
            token,
            package_name="com.surviveTheTalk.client",
            product_id="stt_weekly_199",
            service_account_json=_SA_JSON_B64,
        )
    )


def test_validate_google_in_grace_period_is_valid(monkeypatch) -> None:
    """F24 — IN_GRACE_PERIOD (paying user mid renewal-failure) stays entitled."""
    fake = _FakeClient(
        token_resp=_FakeResp(200, {"access_token": "ya29.abc"}),
        api_resp=_FakeResp(
            200,
            {
                "subscriptionState": "SUBSCRIPTION_STATE_IN_GRACE_PERIOD",
                "latestOrderId": "GPA.2",
                "lineItems": [{"productId": "stt_weekly_199"}],
            },
        ),
    )
    result = _run_google(monkeypatch, fake)
    assert result.valid is True
    assert result.status == "valid"


@pytest.mark.parametrize("code", [401, 403])
def test_validate_google_api_401_403_is_config_error(monkeypatch, code) -> None:
    """F21 — a 401/403 on subscriptionsv2 means OUR service account lacks
    androidpublisher permission → BillingConfigError (503), NOT 'unreachable'
    (which would optimistically grant) nor 'invalid' (which would 402 a real
    buyer)."""
    fake = _FakeClient(
        token_resp=_FakeResp(200, {"access_token": "ya29.abc"}),
        api_resp=_FakeResp(code),
    )
    _patch_google(monkeypatch, fake)
    with pytest.raises(BillingConfigError):
        asyncio.run(
            validate_google(
                "token",
                package_name="com.surviveTheTalk.client",
                product_id="stt_weekly_199",
                service_account_json=_SA_JSON_B64,
            )
        )


def test_validate_google_api_404_is_invalid(monkeypatch) -> None:
    """F24 — a 404 (unknown/expired token) is a definitive 'invalid', not an
    'unreachable' optimistic-grant."""
    fake = _FakeClient(
        token_resp=_FakeResp(200, {"access_token": "ya29.abc"}),
        api_resp=_FakeResp(404),
    )
    result = _run_google(monkeypatch, fake)
    assert result.status == "invalid"


def test_validate_google_token_percent_encoded_in_url(monkeypatch) -> None:
    """F8 — an attacker-shaped purchaseToken must be percent-encoded into the
    URL path, never interpolated raw (no '?'/'/'/'#' reshaping the request)."""
    fake = _FakeClient(
        token_resp=_FakeResp(200, {"access_token": "ya29.abc"}),
        api_resp=_FakeResp(
            200,
            {
                "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
                "lineItems": [{"productId": "stt_weekly_199"}],
            },
        ),
    )
    _run_google(monkeypatch, fake, token="a/b?c#d../e")
    assert fake.last_get_url is not None
    # The raw special chars must NOT survive into the path; the encoded forms do.
    assert "a/b?c#d../e" not in fake.last_get_url
    assert "a%2Fb%3Fc%23d..%2Fe" in fake.last_get_url
