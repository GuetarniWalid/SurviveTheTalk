"""Pydantic v2 request / response models.

These are the type-checked I/O contract for HTTP endpoints. Outer envelope
shape (`{"data": ..., "meta": ...}` / `{"error": ...}`) is built by helpers
in `api/responses.py` — these models cover the inner payloads only.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


# RFC 5321 caps the full email at 254 octets; we enforce it at the schema
# boundary so a pathological client can't amplify memory via long strings.
_MAX_EMAIL_LEN = 254


class RequestCodeIn(BaseModel):
    email: EmailStr = Field(max_length=_MAX_EMAIL_LEN)


class VerifyCodeIn(BaseModel):
    email: EmailStr = Field(max_length=_MAX_EMAIL_LEN)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class RequestCodeOut(BaseModel):
    message: str


class VerifyCodeOut(BaseModel):
    token: str
    user_id: int
    email: EmailStr = Field(max_length=_MAX_EMAIL_LEN)


class HealthOut(BaseModel):
    status: str
    db: str


class Meta(BaseModel):
    timestamp: str


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: dict | None = None
