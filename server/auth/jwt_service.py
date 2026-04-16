"""JWT issuance, decoding, and bcrypt hashing for the passwordless auth system.

Stateless HS256 tokens with a 30-day lifetime. The bcrypt-hashed token is
stored in `users.jwt_hash` for forward-compat (future "log out all devices");
it is NOT verified on subsequent requests today (see story §Security Decisions).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from config import Settings

JWT_ALGORITHM = "HS256"
JWT_LIFETIME_DAYS = 30

settings = Settings()


def issue_token(user_id: int) -> str:
    """Sign a JWT with `user_id` and a 30-day expiry."""
    payload = {
        "user_id": user_id,
        "exp": datetime.now(UTC) + timedelta(days=JWT_LIFETIME_DAYS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode a JWT, validating signature + expiry.

    Raises `jwt.ExpiredSignatureError` for expired tokens and
    `jwt.InvalidTokenError` (or subclass) for everything else invalid. We set
    `require=["exp"]` so a forged token without an `exp` claim is rejected
    even though the library default would accept it.
    """
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp"]},
    )


def _prehash_for_bcrypt(token: str) -> bytes:
    """Hash-then-base64 a token to side-step bcrypt's 72-byte password limit.

    Our JWTs are ~200+ bytes, so raw `token.encode()` would be silently
    truncated by bcrypt. We SHA-256 first (32 bytes) then base64-encode (44
    bytes) to stay well under 72 bytes while preserving entropy.
    """
    digest = hashlib.sha256(token.encode()).digest()
    return base64.b64encode(digest)


async def hash_token(token: str) -> str:
    """bcrypt-hash a JWT for storage in `users.jwt_hash`.

    `bcrypt.hashpw` is CPU-bound (~100–250 ms with the default cost factor),
    which would block the event loop if awaited directly. We delegate to a
    worker thread via `asyncio.to_thread` so concurrent requests stay
    responsive. The SHA-256 pre-hash avoids bcrypt's 72-byte truncation.
    """

    def _blocking_hash() -> str:
        return bcrypt.hashpw(_prehash_for_bcrypt(token), bcrypt.gensalt()).decode()

    return await asyncio.to_thread(_blocking_hash)
