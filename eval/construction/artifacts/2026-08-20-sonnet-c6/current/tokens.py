"""Signed, short-lived session tokens for the internal admin tool.

Token format: base64url(JSON payload) + "." + base64url(HMAC-SHA256 signature)

Design notes (read before touching this file):
  - Standard library only, on purpose: HMAC-SHA256 over a minimal JSON
    payload, not a hand-rolled cipher and not a JWT library we can't audit
    here. The algorithm is fixed at construction time by the code itself
    (there is no `alg` field to confuse), so there is no algorithm-negotiation
    surface for an attacker to exploit.
  - The payload carries only non-secret identifiers (subject, issued-at,
    expiry) - never credentials or PII. A token is bearer data: anyone
    holding it can read the payload, so nothing sensitive goes in it.
  - Verification always checks the signature - with a constant-time
    comparison - before it parses or trusts a single claim out of the
    payload. A forged or truncated payload never reaches the JSON parser
    under an attacker-chosen value.
  - Tokens are short-lived by default (15 minutes) and every claim
    (subject, issued-at, expiry) is validated by type before use, so a
    malformed but correctly-signed payload still fails closed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

__all__ = ["issue", "verify"]


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    # Re-pad: urlsafe_b64decode requires a length that's a multiple of 4.
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(payload_b64: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    ).digest()
    return _b64url_encode(digest)


def _is_plain_int(value: object) -> bool:
    # bool is a subclass of int in Python; exclude it so a crafted
    # payload can't smuggle True/False through an int-typed claim.
    return isinstance(value, int) and not isinstance(value, bool)


def issue(subject: str, secret: str, now: int, ttl: int = 900) -> str:
    """Issue a signed session token for `subject`, valid from `now` for `ttl` seconds.

    `now` and `ttl` are both integer epoch seconds; the token expires at
    `now + ttl` and is not valid before `now`.
    """
    if not isinstance(subject, str) or not subject:
        raise ValueError("subject must be a non-empty string")
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret must be a non-empty string")
    if not _is_plain_int(now):
        raise ValueError("now must be an int")
    if not _is_plain_int(ttl) or ttl <= 0:
        raise ValueError("ttl must be a positive int")

    payload = {"sub": subject, "iat": now, "exp": now + ttl}
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature_b64 = _sign(payload_b64, secret)
    return f"{payload_b64}.{signature_b64}"


def verify(token: str, secret: str, now: int) -> str:
    """Verify a token produced by `issue` and return the subject it was issued for.

    Raises ValueError if the token is malformed, the signature does not
    match, or the token is not valid (not yet issued, or expired) at `now`.
    The failure reason is for the caller/log, not for display to an
    end user - callers should show a generic "session expired" message.
    """
    if not isinstance(token, str):
        raise ValueError("invalid token")
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret must be a non-empty string")
    if not _is_plain_int(now):
        raise ValueError("now must be an int")

    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("invalid token")
    payload_b64, signature_b64 = parts
    if not payload_b64 or not signature_b64:
        raise ValueError("invalid token")

    # Verify the signature before parsing anything out of the payload.
    expected_signature_b64 = _sign(payload_b64, secret)
    if not hmac.compare_digest(signature_b64, expected_signature_b64):
        raise ValueError("invalid token signature")

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid token payload") from exc

    if not isinstance(payload, dict):
        raise ValueError("invalid token payload")

    subject = payload.get("sub")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")

    if not isinstance(subject, str) or not subject:
        raise ValueError("invalid token payload")
    if not _is_plain_int(issued_at) or not _is_plain_int(expires_at):
        raise ValueError("invalid token payload")
    if expires_at <= issued_at:
        raise ValueError("invalid token payload")

    if now < issued_at:
        raise ValueError("token not yet valid")
    if now >= expires_at:
        raise ValueError("token expired")

    return subject
