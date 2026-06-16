"""Apple root certificate(s) for offline StoreKit 2 JWS verification.

`app-store-server-library`'s `SignedDataVerifier` does NOT bundle Apple's
root CAs — the caller supplies them as a `list[bytes]` of DER certificates.
We pin Apple Root CA - G3 (the root that anchors the StoreKit 2 signing
chain) as a base64 constant so it is reviewable + diffable in git history
(rather than committing an opaque binary `.cer`). It is decoded to DER bytes
at load.

Source: https://www.apple.com/certificateauthority/AppleRootCA-G3.cer
SHA-256 (DER): 63343abfb89a6a03ebb57e9b3f5fa7be7c4f5c756f3017b3a8c488c3653e9179

The fingerprint is asserted at import (`_EXPECTED_SHA256`) so a corrupted or
swapped cert fails loud at process start instead of silently accepting a
forged signing chain.
"""

from __future__ import annotations

import base64
import hashlib

# Apple Root CA - G3, DER, base64-encoded (583 bytes decoded).
APPLE_ROOT_CA_G3_B64 = (
    "MIICQzCCAcmgAwIBAgIILcX8iNLFS5UwCgYIKoZIzj0EAwMwZzEbMBkGA1UEAwwSQXBwbGUgUm9v"
    "dCBDQSAtIEczMSYwJAYDVQQLDB1BcHBsZSBDZXJ0aWZpY2F0aW9uIEF1dGhvcml0eTETMBEGA1UE"
    "CgwKQXBwbGUgSW5jLjELMAkGA1UEBhMCVVMwHhcNMTQwNDMwMTgxOTA2WhcNMzkwNDMwMTgxOTA2"
    "WjBnMRswGQYDVQQDDBJBcHBsZSBSb290IENBIC0gRzMxJjAkBgNVBAsMHUFwcGxlIENlcnRpZmlj"
    "YXRpb24gQXV0aG9yaXR5MRMwEQYDVQQKDApBcHBsZSBJbmMuMQswCQYDVQQGEwJVUzB2MBAGByqG"
    "SM49AgEGBSuBBAAiA2IABJjpLz1AcqTtkyJygRMc3RCV8cWjTnHcFBbZDuWmBSp3ZHtfTjjTuxxE"
    "tX/1H7YyYl3J6YRbTzBPEVoA/VhYDKX1DyxNB0cTddqXl5dvMVztK517IDvYuVTZXpmkOlEKMaNC"
    "MEAwHQYDVR0OBBYEFLuw3qFYM4iapIqZ3r6966/ayySrMA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0P"
    "AQH/BAQDAgEGMAoGCCqGSM49BAMDA2gAMGUCMQCD6cHEFl4aXTQY2e3v9GwOAEZLuN+yRhHFD/3m"
    "eoyhpmvOwgPUnPWTxnS4at+qIxUCMG1mihDK1A3UT82NQz60imOlM27jbdoXt2QfyFMm+YhidDkL"
    "F1vLUagM6BgD56KyKA=="
)

_EXPECTED_SHA256 = "63343abfb89a6a03ebb57e9b3f5fa7be7c4f5c756f3017b3a8c488c3653e9179"

_APPLE_ROOT_CA_G3_DER = base64.b64decode(APPLE_ROOT_CA_G3_B64)

if (
    hashlib.sha256(_APPLE_ROOT_CA_G3_DER).hexdigest() != _EXPECTED_SHA256
):  # pragma: no cover
    raise RuntimeError(
        "Apple Root CA - G3 fingerprint mismatch — the pinned cert was "
        "altered. Refusing to verify StoreKit JWS against an unknown root."
    )


def apple_root_certificates() -> list[bytes]:
    """Return Apple's trusted root certificate(s) as DER bytes.

    Passed straight to `SignedDataVerifier(root_certificates=...)`.
    """
    return [_APPLE_ROOT_CA_G3_DER]
