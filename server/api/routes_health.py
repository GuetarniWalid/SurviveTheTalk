"""GET /health — lightweight liveness probe for Caddy / monitoring.

Opens (and closes) a SQLite connection to prove the DB is reachable, then
returns the standard envelope. Returns 503 if the DB cannot be opened.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from loguru import logger

from api.responses import err, ok
from db.database import get_connection
from models.schemas import HealthOut

router = APIRouter(tags=["health"])


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
    return ok(HealthOut(status="ok", db="ok"))
