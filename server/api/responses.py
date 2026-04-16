"""Helpers that build the uniform `{data, meta}` / `{error}` JSON envelope.

All NEW endpoints introduced from Story 4.2 onwards must wrap their payload
in `ok(...)` or `err(...)`. The `/connect` endpoint keeps its legacy shape
because the PoC Flutter client is still in production until Story 6.1.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel


def now_iso() -> str:
    """UTC ISO 8601 timestamp with trailing `Z`, no microseconds.

    Example: `2026-04-16T10:30:00Z`.
    """
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def ok(data: BaseModel | dict) -> dict:
    """Wrap `data` in the success envelope."""
    payload = data.model_dump() if isinstance(data, BaseModel) else data
    return {"data": payload, "meta": {"timestamp": now_iso()}}


def err(code: str, message: str, detail: dict | None = None) -> dict:
    """Build the error envelope.

    `code` is SCREAMING_SNAKE; `message` is a human-readable sentence; `detail`
    is an optional structured payload (e.g. Pydantic validation errors).
    """
    body: dict = {"code": code, "message": message}
    if detail is not None:
        body["detail"] = detail
    return {"error": body}
