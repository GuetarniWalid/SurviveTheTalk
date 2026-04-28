"""Call-usage policy: tier → cap → period → calls_remaining.

Centralises the FR21 rule (free = 3 lifetime, paid = 3/day) so both
`/scenarios` (display state) and `/calls/initiate` (enforcement) share
one source of truth. A future rebalance lands here and propagates to
both endpoints + the client BOC for free.
"""

from __future__ import annotations

from datetime import UTC, datetime

import aiosqlite

from db.queries import (
    count_user_call_sessions_since,
    count_user_call_sessions_total,
)

CALLS_PER_PERIOD: int = 3  # FR21 — same literal for both tiers today.


def _utc_day_start_iso(now: datetime) -> str:
    """Return the ISO 8601 UTC start-of-day for `now` (microseconds stripped)."""
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat(timespec="seconds").replace("+00:00", "Z")


async def compute_call_usage(
    db: aiosqlite.Connection,
    user_id: int,
    tier: str,
    *,
    now: datetime | None = None,
) -> dict:
    """Return the canonical `{tier, calls_remaining, calls_per_period, period}` dict.

    `now` is injectable for tests; defaults to `datetime.now(UTC)`.
    """
    if now is None:
        now = datetime.now(UTC)

    if tier == "free":
        used = await count_user_call_sessions_total(db, user_id)
        period = "lifetime"
    elif tier == "paid":
        used = await count_user_call_sessions_since(
            db, user_id, _utc_day_start_iso(now)
        )
        period = "day"
    else:
        # Defensive: the CHECK constraint on users.tier limits values to
        # {'free','paid'} (migration 003), so this branch is unreachable
        # under normal operation. Raising preserves the invariant loud
        # rather than degrading silently.
        raise ValueError(f"Unsupported tier: {tier!r}")

    remaining = max(0, CALLS_PER_PERIOD - used)
    return {
        "tier": tier,
        "calls_remaining": remaining,
        "calls_per_period": CALLS_PER_PERIOD,
        "period": period,
    }
