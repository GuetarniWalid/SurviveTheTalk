"""Story 6.14 AC2 — LiveKit token minting carries the jitter-buffer room config.

`pipeline/livekit_tokens.py` mirrors pipecat's `generate_token` /
`generate_token_with_agent` (room-join grant, optional `agent=True`) and
attaches LiveKit's `min_playout_delay` room config when asked. These
tests decode the signed JWT and assert the grant + room config land in
the claims so the SFU actually emits the `playout-delay` RTP extension
(the receiver-side jitter buffer that stops Tina's voice stretching).
"""

from __future__ import annotations

import jwt

from pipeline.livekit_tokens import generate_token, generate_token_with_agent

_API_KEY = "devkey"
# >= 32 bytes so PyJWT doesn't emit InsecureKeyLengthWarning (HS256).
_API_SECRET = "devsecret-0123456789-0123456789-0123456789"
_ROOM = "call-abc123"


def _decode(token: str) -> dict:
    return jwt.decode(
        token,
        _API_SECRET,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )


def test_user_token_has_room_join_grant_and_no_agent() -> None:
    token = generate_token(
        room_name=_ROOM,
        participant_name="user-7",
        api_key=_API_KEY,
        api_secret=_API_SECRET,
    )
    claims = _decode(token)
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["room"] == _ROOM
    # User is NOT an agent (omitted or false).
    assert claims["video"].get("agent") in (None, False)


def test_agent_token_has_agent_grant() -> None:
    token = generate_token_with_agent(
        room_name=_ROOM,
        participant_name="tina-bot",
        api_key=_API_KEY,
        api_secret=_API_SECRET,
    )
    claims = _decode(token)
    assert claims["video"]["roomJoin"] is True
    assert claims["video"]["room"] == _ROOM
    assert claims["video"]["agent"] is True


def test_token_carries_min_playout_delay_room_config() -> None:
    """Story 6.14 AC2 — a positive `min_playout_delay_ms` lands in the
    token's `roomConfig.minPlayoutDelay` so LiveKit enlarges the
    receiver's jitter buffer."""
    token = generate_token(
        room_name=_ROOM,
        participant_name="user-7",
        api_key=_API_KEY,
        api_secret=_API_SECRET,
        min_playout_delay_ms=200,
    )
    claims = _decode(token)
    assert claims["roomConfig"]["minPlayoutDelay"] == 200


def test_agent_token_also_carries_min_playout_delay() -> None:
    """Both tokens carry the config (room auto-created on first join, so
    whichever participant creates it applies the config)."""
    token = generate_token_with_agent(
        room_name=_ROOM,
        participant_name="tina-bot",
        api_key=_API_KEY,
        api_secret=_API_SECRET,
        min_playout_delay_ms=350,
    )
    claims = _decode(token)
    assert claims["roomConfig"]["minPlayoutDelay"] == 350
    assert claims["video"]["agent"] is True


def test_zero_min_playout_delay_omits_room_config() -> None:
    """`min_playout_delay_ms=0` (the env-tunable rollback) leaves NO room
    config on the token — pure rollback of the jitter buffer, no code
    change."""
    token = generate_token(
        room_name=_ROOM,
        participant_name="user-7",
        api_key=_API_KEY,
        api_secret=_API_SECRET,
        min_playout_delay_ms=0,
    )
    claims = _decode(token)
    assert "roomConfig" not in claims


def test_default_min_playout_delay_is_zero_omits_room_config() -> None:
    """Defaulting the kwarg (no value passed) = no room config, so a
    caller that forgets the knob doesn't silently get a buffer."""
    token = generate_token(
        room_name=_ROOM,
        participant_name="user-7",
        api_key=_API_KEY,
        api_secret=_API_SECRET,
    )
    claims = _decode(token)
    assert "roomConfig" not in claims
