"""Signed, short-lived session tokens for the internal admin tool.

A token is URL- and header-safe ASCII in three dot-separated segments::

    v1.<payload>.<signature>

``payload`` is unpadded base64url of a compact JSON object::

    {"exp": <expiry>, "iat": <issued at>, "sub": <subject>}

``signature`` is unpadded base64url of HMAC-SHA256, computed with ``secret``
over the exact bytes ``b"session-token.v1|" + b"v1.<payload>"``.  The version
prefix sits inside the signed material, so the format cannot be downgraded by
rewriting it, and the domain-separator prefix keeps these signatures from
colliding with any other use of the same secret.

The payload is signed, not encrypted: anyone holding a token can read the
subject and the timestamps out of it.  What the signature buys is that only a
holder of ``secret`` can mint a token or alter one.  Tokens are bearer
credentials -- treat them like passwords in logs, URLs, and error messages.

Validity is a half-open window: a token issued at ``t`` with ``ttl`` seconds
verifies for ``t <= now < t + ttl``.  It is rejected one second late, and also
rejected before ``t``, so a token minted by a machine whose clock runs ahead
does not verify early.  No clock skew is tolerated; keep the issuing and
verifying hosts on NTP.

Both functions take ``now`` explicitly rather than reading the clock, so
callers control time and tests need no monkeypatching.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import re
from hashlib import sha256

__all__ = ["DEFAULT_TTL", "issue", "verify"]

#: Default token lifetime in seconds, applied by :func:`issue`.
DEFAULT_TTL = 900

_VERSION = "v1"
_CONTEXT = b"session-token.v1|"
_SIG_BYTES = sha256().digest_size
# Bounds the work an unauthenticated caller can hand the verifier.  Real
# tokens run well under 200 characters.
_MAX_TOKEN_CHARS = 4096
_B64_ALPHABET = re.compile(r"[A-Za-z0-9_-]+")


def _b64encode(raw: bytes) -> str:
    """Encode ``raw`` as unpadded base64url."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(segment: str) -> bytes:
    """Decode one unpadded base64url segment, strictly.

    ``base64.urlsafe_b64decode`` silently discards characters outside the
    alphabet and accepts non-canonical trailing bits, which would let several
    distinct token strings decode to the same signature.  Re-encoding and
    comparing rejects every such variant, so each token has exactly one
    spelling and stays usable as a cache or revocation key.
    """
    if not _B64_ALPHABET.fullmatch(segment):
        raise ValueError("token is malformed")
    try:
        raw = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))
    except (binascii.Error, ValueError):
        raise ValueError("token is malformed") from None
    if _b64encode(raw) != segment:
        raise ValueError("token is malformed")
    return raw


def _key(secret: str | bytes) -> bytes:
    """Normalise ``secret`` to the bytes used as the HMAC key."""
    if isinstance(secret, str):
        key = secret.encode("utf-8")
    elif isinstance(secret, (bytes, bytearray)):
        key = bytes(secret)
    else:
        raise TypeError("secret must be str or bytes, got " + type(secret).__name__)
    if not key:
        raise ValueError("secret must not be empty")
    return key


def _epoch(value: object, name: str) -> int:
    """Require ``value`` to be a plain int (a ``bool`` is not an epoch second)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{name} must be an int epoch second, got {type(value).__name__}"
        )
    return value


def _sign(key: bytes, signing_input: str) -> bytes:
    """HMAC-SHA256 over the domain separator followed by ``signing_input``."""
    return hmac.new(key, _CONTEXT + signing_input.encode("ascii"), sha256).digest()


def issue(subject: str, secret: str, now: int, ttl: int = DEFAULT_TTL) -> str:
    """Mint a token for ``subject``, valid from ``now`` for ``ttl`` seconds.

    Args:
        subject: Who the token is for; a non-empty string, returned verbatim
            by :func:`verify`.
        secret: The shared signing key, ``str`` or ``bytes``.
        now: Current time as an int epoch second.
        ttl: Lifetime in whole seconds; must be positive.

    Returns:
        The token, as ASCII text safe for URLs, headers, and cookies.

    Raises:
        TypeError: If an argument is of the wrong type.
        ValueError: If ``subject`` or ``secret`` is empty, or ``ttl`` is not
            positive.
    """
    if not isinstance(subject, str):
        raise TypeError("subject must be a str, got " + type(subject).__name__)
    if not subject:
        raise ValueError("subject must not be empty")
    key = _key(secret)
    _epoch(now, "now")
    _epoch(ttl, "ttl")
    if ttl <= 0:
        raise ValueError("ttl must be a positive number of seconds")

    payload = json.dumps(
        {"exp": now + ttl, "iat": now, "sub": subject},
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=True,
    ).encode("ascii")
    signing_input = _VERSION + "." + _b64encode(payload)
    return signing_input + "." + _b64encode(_sign(key, signing_input))


def verify(token: str, secret: str, now: int) -> str:
    """Check ``token`` and return the subject it was issued for.

    The signature is checked before anything in the payload is parsed or
    trusted, and it is compared in constant time so a wrong signature leaks
    nothing about the right one.

    Args:
        token: The token string to check.
        secret: The shared signing key, ``str`` or ``bytes``.
        now: Current time as an int epoch second.

    Returns:
        The subject the token was issued for.

    Raises:
        ValueError: If the token is malformed, was not signed by ``secret``,
            or is outside its validity window at ``now``.  ``token`` is
            untrusted input, so a non-string ``token`` raises ``ValueError``
            as well, rather than ``TypeError``.
        TypeError: If ``secret`` or ``now`` -- both caller-supplied, not
            attacker-supplied -- is of the wrong type.
    """
    key = _key(secret)
    _epoch(now, "now")

    if not isinstance(token, str):
        raise ValueError("token is malformed")
    if not token or len(token) > _MAX_TOKEN_CHARS:
        raise ValueError("token is malformed")

    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("token is malformed")
    version, payload_segment, signature_segment = parts
    if version != _VERSION:
        raise ValueError("unsupported token version")

    # Also validates the alphabet, so the segment is safe to encode as ASCII.
    payload_bytes = _b64decode(payload_segment)
    signature = _b64decode(signature_segment)
    if len(signature) != _SIG_BYTES:
        raise ValueError("token is malformed")

    expected = _sign(key, version + "." + payload_segment)
    if not hmac.compare_digest(signature, expected):
        raise ValueError("token signature is invalid")

    # Past this point the payload is known to be one we signed.  It is still
    # parsed defensively: the same secret may have signed an older shape.
    try:
        claims = json.loads(payload_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("token payload is malformed") from None
    if not isinstance(claims, dict):
        raise ValueError("token payload is malformed")

    subject = claims.get("sub")
    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    if not isinstance(subject, str) or not subject:
        raise ValueError("token payload is malformed")
    for value in (issued_at, expires_at):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("token payload is malformed")
    if expires_at <= issued_at:
        raise ValueError("token payload is malformed")

    if now < issued_at:
        raise ValueError("token is not valid yet")
    if now >= expires_at:
        raise ValueError("token has expired")
    return subject
