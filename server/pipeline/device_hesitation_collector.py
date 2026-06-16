"""Story 7.5 (D3-c) — bot-side collector for DEVICE-measured hesitation gaps.

The client's `HesitationMeter` measures the felt onset gap ON the phone (removing
every network term) and publishes it over the LiveKit data channel as a
`{"type":"hesitation_onset","gap_ms":int,"censored":bool}` envelope. The bot's
`on_data_received` handler routes those here. The device only knows the timing;
the BOT owns the transcript, so on receipt this collector snapshots the
character line that just finished (for the LLM context) and assigns a stable id
— exactly mirroring `HesitationObserver` so the two are interchangeable at
teardown.

At teardown `merge_hesitation_sources` PREFERS the device gaps (accurate,
`source="device"`) and ADDS the server observer's UNRESOLVED freezes — the
re-speak gaps the device can never see because it DISARMS the instant the
character speaks again (C2). When no device gaps arrived at all (an old app
build, or a data-channel failure) it falls back entirely to the server observer.
"""

from __future__ import annotations

import math

from loguru import logger

# Mirror HesitationObserver's contract (debrief-content-strategy Q6). 4.0 since
# 2026-06-15 (a ~3 s reply beat is natural — count a hesitation from 4 s).
_THRESHOLD_SECONDS = 4.0
_TOP_N = 3


class DeviceHesitationCollector:
    """Gathers `hesitation_onset` envelopes into the same shape
    `HesitationObserver.top_hesitations()` produces, tagged `source="device"`.

    Args:
        collector: the shared `TranscriptCollector` — snapshots the character
            line that preceded each device-measured gap.
        threshold_seconds: gaps must EXCEED this to count (default 4 s — matches
            the client meter's own `minGap`, belt-and-suspenders).
        top_n: how many longest gaps `top_hesitations()` returns (default 3).
    """

    def __init__(
        self,
        *,
        collector,
        threshold_seconds: float = _THRESHOLD_SECONDS,
        top_n: int = _TOP_N,
    ) -> None:
        self._collector = collector
        self._threshold = threshold_seconds
        self._top_n = top_n
        # {"id", "duration", "line"} for every accepted device gap.
        self._gaps: list[dict] = []
        self._counter = 0

    def record(self, *, gap_ms: object, censored: object) -> None:
        """Record one device onset envelope. CENSORED envelopes (a quiet-speaker
        miss / max-gap timeout — the device could not measure) are ignored so
        the server observer covers that turn. A non-numeric / sub-threshold gap
        is dropped. NEVER raises — a malformed envelope must not crash the bot."""
        if censored:
            return
        if not isinstance(gap_ms, (int, float)) or isinstance(gap_ms, bool):
            return
        if not math.isfinite(gap_ms):
            return
        duration = float(gap_ms) / 1000.0
        if duration <= self._threshold:
            return
        self._counter += 1
        self._gaps.append(
            {
                "id": f"d{self._counter}",
                "duration": duration,
                "line": self._last_character_line(),
            }
        )

    def _last_character_line(self) -> str:
        """The most-recent character turn text from the collector, or ''."""
        for turn in reversed(self._collector.transcript):
            if isinstance(turn, dict) and turn.get("role") == "character":
                return str(turn.get("text", "")).strip()
        return ""

    @property
    def has_device_gaps(self) -> bool:
        return bool(self._gaps)

    def top_hesitations(self) -> list[dict]:
        """The longest `top_n` device gaps, longest first — same shape as
        `HesitationObserver.top_hesitations()`, tagged `source="device"` and
        `resolved=True` (a measured onset means the user DID speak)."""
        ranked = sorted(self._gaps, key=lambda g: g["duration"], reverse=True)[
            : self._top_n
        ]
        result = [
            {
                "id": g["id"],
                "duration_sec": round(g["duration"], 2),
                "preceding_character_line": g["line"],
                "resolved": True,
                "source": "device",
            }
            for g in ranked
        ]
        if result:
            logger.info("device_hesitation_collector captured {} gaps", len(result))
        return result


def merge_hesitation_sources(
    device: list[dict], server: list[dict], *, top_n: int = _TOP_N
) -> list[dict]:
    """Story 7.5 D3-c teardown merge — prefer the device-measured gaps.

    - No device gaps (old app / channel failure) → fall back entirely to the
      server observer (already `source`-tagged "server").
    - Device gaps present → use them (accurate, resolved) AND add the server
      observer's UNRESOLVED freezes (the re-speak gaps the device cannot see, C2
      — the meter disarms when the character speaks again). Re-rank by duration,
      cap at `top_n`.

    Story 7.6 (AC5) — the no-device branch returns a FRESH list (`list(server)`),
    never the caller's `server` reference: the teardown merge result must be
    independent of the observer's internal list so a later mutation of either
    can't alias the other.
    """
    if not device:
        return list(server)
    server_unresolved = [h for h in server if not h.get("resolved", True)]
    merged = sorted(
        [*device, *server_unresolved],
        key=lambda h: h.get("duration_sec", 0.0),
        reverse=True,
    )
    return merged[:top_n]
