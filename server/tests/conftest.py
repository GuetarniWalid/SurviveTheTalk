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
import shutil
from pathlib import Path
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
    # Story 6.9b — Groq is the classifier provider since the 2026-05-22
    # bench migration. Required for `Settings()` to validate at import.
    "GROQ_API_KEY": "test-groq",
    "JWT_SECRET": "0" * 32,
    "RESEND_API_KEY": "test-resend",
    "RESEND_FROM_EMAIL": "noreply@example.com",
    "RESEND_FROM_NAME": "test",
    # Story 6.26 — disable the warm bot-process pool in the test suite so the
    # TestClient lifespan never spawns real (heavy) parked bot subprocesses.
    # With size 0 the pool is a no-op: `acquire()` returns False, so
    # `initiate_call` cold-spawns via the (mocked) `subprocess.Popen` exactly as
    # the pre-6.26 tests expect. Pool mechanics are covered in `test_bot_pool.py`
    # (stub subprocess) + the pool-hit path in `test_calls.py` (injected pool).
    "BOT_POOL_SIZE": "0",
    # database_path is overridden per-test via monkeypatch
}
for _k, _v in TEST_ENV_VARS.items():
    os.environ.setdefault(_k, _v)

import sqlite3  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def register_user(
    client: TestClient, test_db_path: str, email: str = "walid@example.com"
) -> int:
    """Register a user via the real auth flow; return the user's id.

    Reads the freshly-issued OTP code straight from the SQLite test DB so
    tests can drive `/auth/verify-code` without mocking. Used by both
    `test_calls.py` and `test_scenarios.py` (and any future endpoint test
    that needs an authenticated user). Lives here to avoid duplication —
    the third caller is the threshold for DRY in tests.
    """
    client.post("/auth/request-code", json={"email": email})
    conn = sqlite3.connect(test_db_path)
    code = conn.execute(
        "SELECT code FROM auth_codes WHERE email = ? AND used = 0",
        (email,),
    ).fetchone()[0]
    conn.close()

    resp = client.post("/auth/verify-code", json={"email": email, "code": code})
    assert resp.status_code == 200
    return resp.json()["data"]["user_id"]


def _patch_database_path(path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every loaded module's `settings.database_path` to `path`.

    Each module follows the `from config import Settings; settings = Settings()`
    pattern, so a single monkeypatch on `db.database.settings` only catches
    that one consumer. Sweeping `sys.modules` future-proofs the fixture: any
    new module that adopts the same pattern is patched automatically. The
    DATABASE_PATH env var covers any module that builds a *fresh* `Settings()`
    instance after the fixture runs.
    """
    import sys

    monkeypatch.setenv("DATABASE_PATH", path)
    seen: set[int] = set()
    for mod in list(sys.modules.values()):
        # Some packages (e.g. `transformers`) define a lazy module-level
        # `__getattr__` that raises a propagating exception for unknown
        # attributes. The default `None` of `getattr` only catches
        # `AttributeError`, so a bare access would crash the whole
        # sweep on those packages.
        # Review patch — narrow the catch to the specific exception
        # classes the lazy-import machinery raises. A bare `except
        # Exception` would silently swallow legitimate import bugs
        # in our own modules (e.g. a syntax-error-in-conditional-
        # import that surfaces only on `getattr`).
        try:
            s = getattr(mod, "settings", None)
        except (ImportError, ModuleNotFoundError, AttributeError):
            continue
        if s is None or not hasattr(s, "database_path") or id(s) in seen:
            continue
        seen.add(id(s))
        monkeypatch.setattr(s, "database_path", path)


@pytest.fixture
def test_db_path(tmp_path, monkeypatch):
    """Point every module that reads `settings.database_path` at a temp file."""
    path = str(tmp_path / "test.sqlite")

    # Force-import the canonical consumer so the sweep catches it even if no
    # other test module has imported it yet.
    import db.database  # noqa: F401

    _patch_database_path(path, monkeypatch)
    return path


_PROD_SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "prod_snapshot.sqlite"


@pytest.fixture
def prod_db(tmp_path, monkeypatch):
    """Sanitised copy of the live VPS DB, point settings.database_path at it.

    Story 5.1 retro: empty test DBs hide entire bug classes (FK refs, CHECK
    on populated rows, UNIQUE collisions on rebuild). `prod_db` gives any
    test access to the real production shape — `tests/test_migrations.py`
    is the canonical consumer (asserts new migrations don't break the
    existing schema), but any test that wants "prod-like" state can use it.

    The snapshot is regenerated by `scripts/refresh_prod_snapshot.py`.
    Each test gets its own copy in tmp_path so writes don't pollute the
    committed fixture.
    """
    if not _PROD_SNAPSHOT.exists():
        # In CI the snapshot MUST be committed — silent skips would mask a
        # missing fixture as "all green". Locally, skip is fine (a new
        # contributor may not have run the refresh script yet).
        if os.getenv("CI"):
            pytest.fail(
                f"prod snapshot missing in CI: {_PROD_SNAPSHOT}. "
                "This file MUST be committed — see "
                "scripts/refresh_prod_snapshot.py."
            )
        pytest.skip(
            f"prod snapshot not found at {_PROD_SNAPSHOT}; run "
            "`python scripts/refresh_prod_snapshot.py` to generate it."
        )
    path = tmp_path / "prod.sqlite"
    shutil.copy(_PROD_SNAPSHOT, path)

    import db.database  # noqa: F401  -- ensure consumer is loaded for the sweep

    _patch_database_path(str(path), monkeypatch)
    return str(path)


async def _noop_background_loop(stop_event) -> None:
    """Test stub for the app's periodic background loops — does NO sweeps.

    The production lifespan spawns `_janitor_loop` and
    `_subscription_revalidation_loop`; the latter's INITIAL sweep calls
    `downgrade_expired_entitlements(now())` immediately, on the app's
    event-loop thread. That sweep RACES any test that seeds a `paid` user
    whose purchase `expires_at` is in the PAST (e.g. the DID_RENEW
    expiry-refresh tests): if the sweep SELECTs the expired user, the webhook
    then commits paid, and the sweep's tier WRITE lands last, the user is
    wrongly flipped to `free` — an intermittent `'free' == 'paid'` failure that
    only began once wall-clock passed those fixtures' 2026-01-01 expiry. The
    interleaving depends on cross-thread scheduling, so it flakes (worse under
    CI load). Stubbing the loops to a no-op that just awaits the shutdown event
    makes the `client` fixture deterministic; the sweep logic itself is covered
    directly against isolated connections in test_subscription.py /
    test_janitor.py.
    """
    await stop_event.wait()


@pytest.fixture
def client(test_db_path, monkeypatch):
    """Build the production app, run lifespan (migrations), yield a TestClient.

    The `with TestClient(app)` context triggers FastAPI startup/shutdown so
    `run_migrations()` populates the temp DB before any request runs. The
    background janitor / subscription-revalidation loops are stubbed to no-ops
    (`_noop_background_loop`) so their periodic sweeps can't race the test —
    see that stub's docstring for the flake it removes.
    """
    import api.app as app_module

    monkeypatch.setattr(app_module, "_janitor_loop", _noop_background_loop)
    monkeypatch.setattr(
        app_module, "_subscription_revalidation_loop", _noop_background_loop
    )

    with TestClient(app_module.app) as c:
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
