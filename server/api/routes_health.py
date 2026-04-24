"""GET /health — lightweight liveness probe for Caddy / monitoring.

Opens (and closes) a SQLite connection to prove the DB is reachable, then
returns the standard envelope. Returns 503 if the DB cannot be opened.

The response also exposes `git_sha`, read once at import time from
`server/.git_sha`. The CI deploy workflow writes that file right after
rsync, so the workflow's post-restart healthcheck can assert the SHA
matches `$GITHUB_SHA` — proving the running process is the release it
just deployed (closes the silent-ghost failure mode).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from loguru import logger

from api.responses import err, ok
from db.database import get_connection
from models.schemas import HealthOut

router = APIRouter(tags=["health"])


def _read_git_sha() -> str:
    # `server/.git_sha` sits at the project root (two levels up from this
    # file: api/routes_health.py → api/ → server/). Resolved via __file__ so
    # the lookup does not depend on the process CWD.
    path = Path(__file__).resolve().parent.parent / ".git_sha"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    return value or "unknown"


# Cached at import time — the file is immutable for the lifetime of a
# release (the CI workflow writes a fresh one per rsync, then restarts the
# service). Re-reading per-request would be wasted work.
_GIT_SHA = _read_git_sha()


@router.get("/health")
async def health():
    try:
        async with get_connection() as db:
            await db.execute("SELECT 1")
    except Exception as exc:  # noqa: BLE001 — surface any connect/exec failure
        logger.error("Health check failed to reach DB: {}", exc)
        return JSONResponse(
            status_code=503,
            content=err("DB_UNAVAILABLE", "Database connection failed."),
        )
    return ok(HealthOut(status="ok", db="ok", git_sha=_GIT_SHA))
