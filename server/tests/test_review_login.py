"""Tests for the env-gated Google-Play app-access review login (Story 10.3).

The app is passwordless (email + a RANDOM 6-digit code emailed to the user), so
a store reviewer cannot receive the code. `REVIEW_LOGIN_EMAIL` +
`REVIEW_LOGIN_CODE` let ONE designated test email sign in with a FIXED code,
skipping the email round-trip. These tests lock the contract: the bypass works
for the exact email+code, is OFF by default, only that email+code bypasses
(constant-time, no leakage to other emails / wrong codes), and a half/invalid
config fails LOUD at boot.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

_REVIEW_EMAIL = "play-review@survivethetalk.com"
_REVIEW_CODE = "246813"


def _enable_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the bypass ON for the module-level `routes_auth.settings` instance
    (the route reads it at request time, so a post-import patch is honoured)."""
    monkeypatch.setattr("api.routes_auth.settings.review_login_email", _REVIEW_EMAIL)
    monkeypatch.setattr("api.routes_auth.settings.review_login_code", _REVIEW_CODE)


def test_review_login_signs_in_with_fixed_code(
    client: TestClient, mock_resend, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_bypass(monkeypatch)
    # request-code returns success WITHOUT sending an email for the review addr.
    r1 = client.post("/auth/request-code", json={"email": _REVIEW_EMAIL})
    assert r1.status_code == 200
    mock_resend.assert_not_awaited()
    # verify-code with the FIXED code → 200 + a usable session token.
    r2 = client.post(
        "/auth/verify-code", json={"email": _REVIEW_EMAIL, "code": _REVIEW_CODE}
    )
    assert r2.status_code == 200
    body = r2.json()["data"]
    assert body["token"]
    assert body["email"] == _REVIEW_EMAIL


def test_review_login_off_by_default(client: TestClient) -> None:
    """With no env set, the review email + code is just an unknown code → 400."""
    r = client.post(
        "/auth/verify-code", json={"email": _REVIEW_EMAIL, "code": _REVIEW_CODE}
    )
    assert r.status_code == 400


def test_review_login_wrong_code_does_not_bypass(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review email with a WRONG 6-digit code falls through to the normal
    flow (no active code exists) → 400, never a bypass."""
    _enable_bypass(monkeypatch)
    r = client.post(
        "/auth/verify-code", json={"email": _REVIEW_EMAIL, "code": "000000"}
    )
    assert r.status_code == 400


def test_review_login_other_email_unaffected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A different email using the fixed code does NOT bypass."""
    _enable_bypass(monkeypatch)
    r = client.post(
        "/auth/verify-code", json={"email": "someone@example.com", "code": _REVIEW_CODE}
    )
    assert r.status_code == 400


def test_review_login_code_must_be_six_digits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boot-time validator: REVIEW_LOGIN_EMAIL set + a non-6-digit code raises
    (else the reviewer is silently locked out — verify-code wants ^\\d{6}$)."""
    from config import Settings

    monkeypatch.setenv("REVIEW_LOGIN_EMAIL", _REVIEW_EMAIL)
    monkeypatch.setenv("REVIEW_LOGIN_CODE", "abc")  # not 6 digits
    with pytest.raises(ValidationError):
        Settings()


def test_review_login_email_must_not_be_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Boot-time validator: a truthy-but-blank email (e.g. whitespace) with a
    valid code raises — otherwise the bypass is silently 'on' but unmatchable,
    locking the reviewer out (the footgun the validator exists to prevent)."""
    from config import Settings

    monkeypatch.setenv("REVIEW_LOGIN_EMAIL", "   ")  # truthy, blank after strip
    monkeypatch.setenv("REVIEW_LOGIN_CODE", _REVIEW_CODE)
    with pytest.raises(ValidationError):
        Settings()
