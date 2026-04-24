"""Composed FastAPI application — single entry point for `uvicorn`.

Wires together the three routers (`/health`, `/auth/*`, `/connect`), runs DB
migrations on startup via the lifespan context manager, exposes CORS for the
mobile client (which has no Origin header), and converts every HTTPException
or Pydantic validation error into the uniform `{"error": {...}}` envelope.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.call_endpoint import router as call_router
from api.responses import err
from api.routes_auth import router as auth_router
from api.routes_calls import router as calls_router
from api.routes_health import router as health_router
from api.routes_scenarios import router as scenarios_router
from db.database import run_migrations
from db.seed_scenarios import seed_scenarios


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run DB migrations + seed scenarios at startup; clean shutdown is a no-op.

    `seed_scenarios()` runs AFTER `run_migrations()` because it depends on the
    `scenarios` table existing. A seed failure raises and aborts startup —
    `systemd` will restart and the traceback lands in `journalctl`.
    """
    await run_migrations()
    await seed_scenarios()
    yield


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
