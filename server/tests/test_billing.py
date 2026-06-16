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

import httpx
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

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def post(self, *args, **kwargs) -> _FakeResp:
        if self._post_exc is not None:
            raise self._post_exc
        return self._token_resp  # type: ignore[return-value]

    async def get(self, *args, **kwargs) -> _FakeResp:
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
