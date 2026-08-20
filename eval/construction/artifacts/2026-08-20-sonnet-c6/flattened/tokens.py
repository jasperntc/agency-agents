"""Signed, short-lived session tokens for the internal admin tool.

Token shape
-----------
A token is two base64url (unpadded) segments joined by a single ``.``:

    <payload>.<signature>

``payload`` is the base64url encoding of a compact JSON object::

    {"sub": "<subject>", "iat": <issued-at epoch seconds>, "exp": <expiry epoch seconds>}

``signature`` is HMAC-SHA256 over the *exact bytes* of the payload segment
(the base64url text, not the decoded JSON), keyed with the caller-supplied
secret. This binds the signature to the transmitted representation and
avoids any ambiguity from canonicalizing JSON before verifying.

Security properties
--------------------
- Integrity: any change to the payload (subject, iat, exp) invalidates the
  signature.
- Forgery resistance: producing a valid signature requires the secret;
  HMAC-SHA256 is used as recommended for symmetric message authentication.
- Constant-time comparison: signatures are compared with
  ``hmac.compare_digest`` to avoid leaking information via timing.
- No confidentiality: the payload is base64-encoded, not encrypted, and is
  trivially readable by anyone holding the token. Do not place secrets in
  ``subject``.
- Expiry is mandatory and enforced server-side on every ``verify`` call;
  there is no way to mint a token that does not expire.

This module intentionally implements a minimal, purpose-built scheme rather
than a general JWT library: there is exactly one algorithm (HMAC-SHA256),
no "alg": "none" downgrade path, and no header segment to manipulate.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

__all__ = ["issue", "verify"]

_ALGORITHM = hashlib.sha256


def _b64url_encode(data: bytes) -> bytes:
    """Base64url-encode ``data`` without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _b64url_decode(data: bytes) -> bytes:
    """Decode base64url ``data``, restoring padding as needed.

    Raises ``ValueError`` (via binascii.Error, a ValueError subclass) if
    ``data`` is not valid base64url.
    """
    padding_needed = (-len(data)) % 4
    return base64.urlsafe_b64decode(data + b"=" * padding_needed)


def _sign(payload_b64: bytes, secret: str) -> bytes:
    """Compute the raw HMAC-SHA256 digest over a base64url payload segment."""
    return hmac.new(secret.encode("utf-8"), payload_b64, _ALGORITHM).digest()


def issue(subject: str, secret: str, now: int, ttl: int = 900) -> str:
    """Issue a signed session token for ``subject``.

    Args:
        subject: The identity the token asserts. Stored in the token as
            plaintext (base64-encoded, not encrypted).
        secret: The symmetric key used to sign the token. The same secret
            must be supplied to ``verify``.
        now: Current time as an integer epoch second. Recorded as the
            token's issued-at time.
        ttl: How many seconds the token remains valid for, starting at
            ``now``. Must be a positive integer.

    Returns:
        The encoded, signed token string.

    Raises:
        ValueError: If ``subject`` is not a non-empty string, ``secret`` is
            not a non-empty string, or ``ttl`` is not a positive integer.
        TypeError: If ``now`` or ``ttl`` is not an ``int``.
    """
    if not isinstance(subject, str) or not subject:
        raise ValueError("subject must be a non-empty string")
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret must be a non-empty string")
    if isinstance(now, bool) or not isinstance(now, int):
        raise TypeError("now must be an int epoch second")
    if isinstance(ttl, bool) or not isinstance(ttl, int):
        raise TypeError("ttl must be an int number of seconds")
    if ttl <= 0:
        raise ValueError("ttl must be a positive integer")

    payload = {"sub": subject, "iat": now, "exp": now + ttl}
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    payload_b64 = _b64url_encode(payload_json.encode("utf-8"))
    signature_b64 = _b64url_encode(_sign(payload_b64, secret))

    return (payload_b64 + b"." + signature_b64).decode("ascii")


def verify(token: str, secret: str, now: int) -> str:
    """Verify a session token and return the subject it was issued for.

    Args:
        token: The token string produced by ``issue``.
        secret: The symmetric key the token must have been signed with.
        now: Current time as an integer epoch second, checked against the
            token's validity window.

    Returns:
        The subject the token was issued for.

    Raises:
        ValueError: If the token is malformed, its signature does not match,
            its payload is not well-formed, or it is not valid at time
            ``now`` (expired, or issued in the future relative to ``now``).
        TypeError: If ``now`` is not an ``int``.
    """
    if not isinstance(token, str) or not token:
        raise ValueError("token must be a non-empty string")
    if not isinstance(secret, str) or not secret:
        raise ValueError("secret must be a non-empty string")
    if isinstance(now, bool) or not isinstance(now, int):
        raise TypeError("now must be an int epoch second")

    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("malformed token: expected exactly one '.' separator")
    payload_b64_str, signature_b64_str = parts
    if not payload_b64_str or not signature_b64_str:
        raise ValueError("malformed token: empty segment")

    try:
        payload_b64 = payload_b64_str.encode("ascii")
        signature_b64 = signature_b64_str.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("malformed token: non-ASCII segment") from exc

    try:
        provided_signature = _b64url_decode(signature_b64)
    except Exception as exc:
        # base64.binascii.Error (a ValueError subclass) is the expected
        # failure; the broad except also guards against any other
        # decode-time failure so a malformed token never raises anything
        # but ValueError.
        raise ValueError("malformed token: invalid signature encoding") from exc

    expected_signature = _sign(payload_b64, secret)
    if not hmac.compare_digest(provided_signature, expected_signature):
        raise ValueError("invalid token signature")

    try:
        payload_json = _b64url_decode(payload_b64)
    except Exception as exc:
        raise ValueError("malformed token: invalid payload encoding") from exc

    try:
        payload = json.loads(payload_json.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("malformed token: invalid payload JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("malformed token: payload is not an object")

    subject = payload.get("sub")
    iat = payload.get("iat")
    exp = payload.get("exp")

    if not isinstance(subject, str) or not subject:
        raise ValueError("malformed token: missing or invalid subject")
    if isinstance(iat, bool) or not isinstance(iat, int):
        raise ValueError("malformed token: missing or invalid iat")
    if isinstance(exp, bool) or not isinstance(exp, int):
        raise ValueError("malformed token: missing or invalid exp")
    if exp <= iat:
        raise ValueError("malformed token: exp must be after iat")

    if now < iat:
        raise ValueError("token is not yet valid")
    if now >= exp:
        raise ValueError("token has expired")

    return subject
