"""Composed FastAPI application — single entry point for `uvicorn`.

Wires together the three routers (`/health`, `/auth/*`, `/connect`), runs DB
migrations on startup via the lifespan context manager, exposes CORS for the
mobile client (which has no Origin header), and converts every HTTPException
or Pydantic validation error into the uniform `{"error": {...}}` envelope.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from api.call_endpoint import router as call_router
from api.responses import err
from api.routes_auth import router as auth_router
from api.routes_calls import router as calls_router
from api.routes_debriefs import router as debriefs_router
from api.routes_health import router as health_router
from api.routes_scenarios import router as scenarios_router
from config import Settings
from db.database import get_connection, run_migrations
from db.janitor import sweep_abandoned_call_sessions
from db.seed_scenarios import seed_scenarios
from pipeline.bot_pool import BotPool

# 15 min cadence. See Story 6.5 §"Why the janitor sweeps every 15 min".
JANITOR_INTERVAL_SECONDS = 15 * 60

# Story 6.5 review (P8) — circuit-breaker on persistent sweep failures.
# After this many consecutive failures the loop stretches its wait to
# `JANITOR_BACKOFF_SECONDS` (1 h) so a permanently-broken DB does NOT
# spam `journalctl` every 15 min indefinitely. A single successful sweep
# resets the counter.
JANITOR_FAILURE_THRESHOLD = 3
JANITOR_BACKOFF_SECONDS = 60 * 60

# Story 6.5 review (P9) — bound the lifespan teardown so a long-running
# sweep cannot starve systemd's `TimeoutStopSec` (default 90 s on most
# distros). We give the loop 30 s to observe `stop_event` and exit
# cleanly; past that, we cancel the task and let the cancellation
# unwind through the existing `except Exception` (which logs but does
# not re-raise into the lifespan finally).
JANITOR_SHUTDOWN_TIMEOUT_SECONDS = 30


async def _janitor_loop(stop_event: asyncio.Event) -> None:
    """Periodic sweep of abandoned `'pending'` call_sessions.

    Runs ONE initial sweep on startup, then waits up to
    `JANITOR_INTERVAL_SECONDS` between cycles. Fail-soft: a sweep failure
    is logged via `logger.exception` but the loop keeps running — the
    next tick retries 15 min later (or `JANITOR_BACKOFF_SECONDS` if the
    failure streak crosses `JANITOR_FAILURE_THRESHOLD`).

    Cancellation: the lifespan signals `stop_event` to break the wait
    cleanly. Using an Event instead of `asyncio.sleep` + `task.cancel()`
    avoids interrupting an in-flight DB operation, which under aiosqlite
    can leave the worker thread posting to a closed loop — visible in
    pytest as "Event loop is closed" warnings during teardown.
    """
    consecutive_failures = 0
    while not stop_event.is_set():
        try:
            async with get_connection() as db:
                flipped = await sweep_abandoned_call_sessions(db, now=datetime.now(UTC))
                if flipped > 0:
                    logger.info(f"janitor_swept count={flipped}")
            consecutive_failures = 0
        except Exception:
            consecutive_failures += 1
            logger.exception(
                "janitor sweep failed "
                f"(consecutive_failures={consecutive_failures}); "
                "will retry"
            )
        # Stretch the wait when we are stuck in a failure streak so we
        # do not spam logs every 15 min on a permanently-broken DB.
        wait = (
            JANITOR_BACKOFF_SECONDS
            if consecutive_failures >= JANITOR_FAILURE_THRESHOLD
            else JANITOR_INTERVAL_SECONDS
        )
        # wait_for raises TimeoutError when the interval elapses without
        # the stop signal — same effect as `asyncio.sleep(...)` but
        # responsive to a clean shutdown.
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=wait)
        except asyncio.TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run DB migrations + seed scenarios at startup; clean shutdown is a no-op.

    `seed_scenarios()` runs AFTER `run_migrations()` because it depends on the
    `scenarios` table existing. A seed failure raises and aborts startup —
    `systemd` will restart and the traceback lands in `journalctl`.

    Story 6.5: spawns `_janitor_loop` as a background task so abandoned
    `'pending'` call_sessions get flipped to `'failed'` (and stop burning
    quota). The task is cancelled + awaited on lifespan exit.

    Story 6.26: builds the warm `BotPool` (`BOT_POOL_SIZE` parked bots) so calls
    skip the ~4.7 s per-call cold-import boot. `size=0` makes the pool a no-op
    (every call cold-spawns). Started after seed; stopped (idle bots terminated)
    on lifespan exit.
    """
    await run_migrations()
    await seed_scenarios()
    settings = Settings()
    app.state.bot_pool = BotPool(size=settings.bot_pool_size)
    try:
        await app.state.bot_pool.start()
    except Exception:
        # Story 6.26 review — the pool must never cost the SERVER, only ever
        # degrade to cold spawns (AC4). `start()` is internally defensive
        # (per-process failures map to None); this is the last-resort belt so
        # an unexpected pool error can't abort startup.
        logger.exception("bot_pool failed to start; calls will cold-spawn")
    stop_event = asyncio.Event()
    janitor = asyncio.create_task(_janitor_loop(stop_event))
    try:
        yield
    finally:
        stop_event.set()
        # Bound the wait so systemd's TimeoutStopSec doesn't kill us
        # mid-sweep on a slow DB. The asyncio.Event-based design lets
        # the loop body finish its current sweep cleanly; if that
        # sweep itself is wedged past the timeout we cancel and let
        # the cancellation unwind.
        try:
            await asyncio.wait_for(janitor, timeout=JANITOR_SHUTDOWN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning(
                "janitor did not exit within "
                f"{JANITOR_SHUTDOWN_TIMEOUT_SECONDS}s; cancelling"
            )
            janitor.cancel()
            try:
                await janitor
            except (asyncio.CancelledError, Exception):
                pass
        except asyncio.CancelledError:
            pass
        # Story 6.26 — terminate idle parked bots so they don't outlive the
        # server (a no-op when size=0). Bounded inside the pool's own teardown.
        await app.state.bot_pool.stop()


app = FastAPI(title="surviveTheTalk API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(call_router)
app.include_router(calls_router)
app.include_router(debriefs_router)
app.include_router(health_router)
app.include_router(scenarios_router)


_GENERIC_HTTP_MESSAGES = {
    400: "Bad request.",
    401: "Unauthorized.",
    403: "Forbidden.",
    404: "Not found.",
    405: "Method not allowed.",
    409: "Conflict.",
    413: "Payload too large.",
    415: "Unsupported media type.",
    422: "Unprocessable entity.",
    429: "Too many requests.",
}


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    """Convert HTTPException to the `{error: {...}}` envelope.

    If `detail` is already a dict with a `code` key (raised from our middleware
    or routes), pass it through; otherwise wrap as a generic HTTP_ERROR with a
    deliberately opaque message so FastAPI internals (default 404 "Not Found",
    request-body parse errors, etc.) can't leak implementation detail to
    clients. `exc.headers` is forwarded so 401 `WWW-Authenticate` challenges
    and 429 `Retry-After` survive the envelope conversion.
    """
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return JSONResponse(
            status_code=exc.status_code,
            content=err(**exc.detail),
            headers=exc.headers,
        )
    generic_message = _GENERIC_HTTP_MESSAGES.get(exc.status_code, "An error occurred.")
    return JSONResponse(
        status_code=exc.status_code,
        content=err("HTTP_ERROR", generic_message),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    """Convert Pydantic 422 validation errors to the envelope shape."""
    return JSONResponse(
        status_code=422,
        content=err(
            "VALIDATION_ERROR",
            "Request body is invalid.",
            detail={"errors": exc.errors()},
        ),
    )
