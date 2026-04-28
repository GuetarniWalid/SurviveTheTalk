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


def ok(data: BaseModel | dict, *, extra_meta: dict | None = None) -> dict:
    """Wrap `data` in the success envelope.

    `extra_meta` lets list-style endpoints fold pagination/count keys into
    `meta` without breaking the historic `ok(data)` call sites.
    """
    payload = data.model_dump() if isinstance(data, BaseModel) else data
    meta: dict = {"timestamp": now_iso()}
    if extra_meta:
        meta.update(extra_meta)
    return {"data": payload, "meta": meta}


def ok_list(items: list, *, extra_meta: dict | None = None) -> dict:
    """Envelope helper for list endpoints — sets `meta.count` for the caller.

    Accepts a list of Pydantic models OR raw dicts. Models are dumped via
    `model_dump()`; dicts pass through unchanged. The convention going forward
    is: every list endpoint returns `ok_list(items)` so clients can read
    `meta.count` without recomputing `len(data)`.

    `extra_meta` lets list endpoints fold aggregate keys (e.g. usage policy
    per Story 5.3) alongside `count`/`timestamp` without bypassing this
    helper.

    Implementation note: delegates to `ok()` so there is one canonical place
    that builds the `{data, meta}` envelope. Future `meta` keys (pagination,
    cursors) stay in a single codepath.
    """
    payload = [
        item.model_dump() if isinstance(item, BaseModel) else item for item in items
    ]
    meta = {"count": len(payload), **(extra_meta or {})}
    return ok(payload, extra_meta=meta)


def err(code: str, message: str, detail: dict | None = None) -> dict:
    """Build the error envelope.

    `code` is SCREAMING_SNAKE; `message` is a human-readable sentence; `detail`
    is an optional structured payload (e.g. Pydantic validation errors).
    """
    body: dict = {"code": code, "message": message}
    if detail is not None:
        body["detail"] = detail
    return {"error": body}
