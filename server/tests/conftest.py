"""Shared pytest fixtures for the server test suite.

Strategy:
- Set every required env var at module load (before any test module imports
  `config.Settings`) so that module-level `Settings()` calls never fail.
- Per-test: monkeypatch each module's `settings.database_path` to a temp file
  so each test gets a clean DB. The TestClient's `with ...` block triggers
  the FastAPI lifespan, which runs migrations against the patched path.
- Mock `auth.email_service.send_auth_code` (referenced from
  `api.routes_auth`) for any test that exercises `/auth/request-code`.

Note: NO `from __future__ import annotations` here — FastAPI needs the runtime
type of the `Request` parameter on the test-only protected route to recognise
it as the special request object (rather than treating it as a query field).
"""

import os
from unittest.mock import AsyncMock

# Set env vars BEFORE any module reads `config.Settings()` at import time.
# Use a 32-char JWT secret so deterministic tokens can be cross-checked.
TEST_ENV_VARS = {
    "ENVIRONMENT": "test",
    "SONIOX_API_KEY": "test-soniox",
    "OPENROUTER_API_KEY": "test-openrouter",
    "CARTESIA_API_KEY": "test-cartesia",
    "LIVEKIT_URL": "wss://livekit.example.com",
    "LIVEKIT_API_KEY": "test-lk-key",
    "LIVEKIT_API_SECRET": "test-lk-secret",
    "JWT_SECRET": "0" * 32,
    "RESEND_API_KEY": "test-resend",
    "RESEND_FROM_EMAIL": "noreply@example.com",
    "RESEND_FROM_NAME": "test",
    # database_path is overridden per-test via monkeypatch
}
for _k, _v in TEST_ENV_VARS.items():
    os.environ.setdefault(_k, _v)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def test_db_path(tmp_path, monkeypatch):
    """Point every module that reads `settings.database_path` at a temp file.

    Patches each `settings` instance directly because each module instantiates
    its own `Settings()` at import time.
    """
    path = str(tmp_path / "test.sqlite")

    import db.database

    monkeypatch.setattr(db.database.settings, "database_path", path)
    return path


@pytest.fixture
def client(test_db_path):
    """Build the production app, run lifespan (migrations), yield a TestClient.

    The `with TestClient(app)` context triggers FastAPI startup/shutdown so
    `run_migrations()` populates the temp DB before any request runs.
    """
    from api.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_resend(monkeypatch):
    """Replace `send_auth_code` (as imported by routes_auth) with an AsyncMock.

    Defaults to returning None (success). Tests can flip `side_effect` to
    `EmailDeliveryError(...)` to simulate Resend outage.
    """
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr("api.routes_auth.send_auth_code", mock)
    return mock


@pytest.fixture
def protected_client(test_db_path):
    """A throwaway FastAPI app with a single AUTH_DEPENDENCY-protected route.

    Used by `test_middleware.py` to exercise every branch of `require_auth`
    without polluting the production app.
    """
    from contextlib import asynccontextmanager

    from fastapi import FastAPI, HTTPException, Request
    from fastapi.exceptions import RequestValidationError

    from api.app import http_exception_handler, validation_exception_handler
    from api.middleware import AUTH_DEPENDENCY
    from db.database import run_migrations

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await run_migrations()
        yield

    test_app = FastAPI(lifespan=lifespan)
    test_app.add_exception_handler(HTTPException, http_exception_handler)
    test_app.add_exception_handler(RequestValidationError, validation_exception_handler)

    @test_app.get("/_test_protected", dependencies=[AUTH_DEPENDENCY])
    async def protected(request: Request):
        return {"data": {"user_id": request.state.user_id}, "meta": {"timestamp": "x"}}

    with TestClient(test_app) as c:
        yield c
