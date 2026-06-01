"""Story 6.14 AC2 — LiveKit access tokens with a jitter-buffer room config.

The recurring "voix rallongée" (stretched/slow Tina) is receiver-side
WebRTC NetEq **time-stretching** audio to fill bursty-packet gaps, i.e.
network jitter (diagnosed call_id=198, 2026-05-30 — server logs clean,
`DTLN_ENABLED=0` never helped → not server pacing). The fix is a bigger
jitter buffer so it doesn't run dry during a gap.

`flutter_webrtc` 1.3.0 exposes NO client-side per-receiver jitter-buffer
/ playout-delay knob, so the lever is LiveKit's room config
`min_playout_delay` (milliseconds). Attached to the access token via
`AccessToken.with_room_config(...)`, it makes the SFU emit the
`playout-delay` RTP header extension on forwarded media, instructing the
receiver's NetEq to keep at least that much playout delay → a larger
jitter buffer → no stretching. It trades a small fixed latency for smooth
playback (keep it the smallest value that kills the stretching; the PRD
ceiling is 2 s perceived).

These mirror `pipecat.runner.livekit.generate_token` /
`generate_token_with_agent` (same names + grant shape) and ADD the room
config — the pipecat helpers don't accept one, so `routes_calls` imports
these instead. The room is auto-created on first join, so the caller
attaches the SAME room config to BOTH the user and agent tokens —
whichever participant creates the room applies it; the other is ignored
because the room already exists.
"""

from __future__ import annotations

from livekit import api
from livekit.protocol.room import RoomConfiguration


def _room_config(min_playout_delay_ms: int) -> RoomConfiguration | None:
    """Build a `RoomConfiguration` enabling the jitter buffer, or None to
    leave the token without a room config (knob disabled).

    `min_playout_delay_ms <= 0` → None (no playout-delay extension; pure
    rollback of the jitter-buffer behaviour via the
    `LIVEKIT_MIN_PLAYOUT_DELAY_MS=0` env override, no code change).
    """
    if min_playout_delay_ms and min_playout_delay_ms > 0:
        return RoomConfiguration(min_playout_delay=min_playout_delay_ms)
    return None


def _generate(
    room_name: str,
    participant_name: str,
    api_key: str,
    api_secret: str,
    *,
    agent: bool,
    min_playout_delay_ms: int,
) -> str:
    """Mint a signed LiveKit JWT with a room-join grant + optional
    `agent=True` + optional jitter-buffer room config."""
    token = api.AccessToken(api_key, api_secret)
    token.with_identity(participant_name).with_name(participant_name).with_grants(
        api.VideoGrants(
            room_join=True,
            room=room_name,
            agent=agent,
        )
    )
    room_config = _room_config(min_playout_delay_ms)
    if room_config is not None:
        token.with_room_config(room_config)
    return token.to_jwt()


def generate_token(
    room_name: str,
    participant_name: str,
    api_key: str,
    api_secret: str,
    *,
    min_playout_delay_ms: int = 0,
) -> str:
    """Generate a LiveKit access token for a regular participant (the user).

    Mirrors `pipecat.runner.livekit.generate_token` and additionally
    attaches the Story 6.14 jitter-buffer room config when
    `min_playout_delay_ms > 0`.
    """
    return _generate(
        room_name,
        participant_name,
        api_key,
        api_secret,
        agent=False,
        min_playout_delay_ms=min_playout_delay_ms,
    )


def generate_token_with_agent(
    room_name: str,
    participant_name: str,
    api_key: str,
    api_secret: str,
    *,
    min_playout_delay_ms: int = 0,
) -> str:
    """Generate a LiveKit access token for the pipeline bot (`agent=True`).

    Mirrors `pipecat.runner.livekit.generate_token_with_agent` and
    additionally attaches the Story 6.14 jitter-buffer room config when
    `min_playout_delay_ms > 0`.
    """
    return _generate(
        room_name,
        participant_name,
        api_key,
        api_secret,
        agent=True,
        min_playout_delay_ms=min_playout_delay_ms,
    )
