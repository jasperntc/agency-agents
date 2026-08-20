"""Signed, time-limited session tokens for the internal admin tool.

A token has the form:

    <base64url(subject)>.<expiry-epoch-seconds>.<hex-hmac-sha256-signature>

The signature covers the subject and expiry fields, so a token cannot be
forged or have its expiry extended without knowledge of the shared secret.
Only the Python standard library is used (hmac, hashlib, base64).
"""

import base64
import hashlib
import hmac

_SEPARATOR = "."


def _sign(message: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def issue(subject: str, secret: str, now: int, ttl: int = 900) -> str:
    """Return a new signed token for `subject`, valid from `now` for `ttl` seconds."""
    if not isinstance(subject, str):
        raise TypeError("subject must be a str")
    if not isinstance(secret, str):
        raise TypeError("secret must be a str")
    if not isinstance(now, int):
        raise TypeError("now must be an int")
    if not isinstance(ttl, int):
        raise TypeError("ttl must be an int")
    if ttl <= 0:
        raise ValueError("ttl must be positive")

    expiry = now + ttl
    encoded_subject = base64.urlsafe_b64encode(subject.encode("utf-8")).decode("ascii")
    message = f"{encoded_subject}{_SEPARATOR}{expiry}"
    signature = _sign(message, secret)
    return f"{message}{_SEPARATOR}{signature}"


def verify(token: str, secret: str, now: int) -> str:
    """Return the subject the token was issued for, or raise ValueError if invalid."""
    if not isinstance(token, str):
        raise ValueError("malformed token")

    parts = token.split(_SEPARATOR)
    if len(parts) != 3:
        raise ValueError("malformed token")

    encoded_subject, expiry_str, signature = parts

    message = f"{encoded_subject}{_SEPARATOR}{expiry_str}"
    expected_signature = _sign(message, secret)
    if not hmac.compare_digest(expected_signature, signature):
        raise ValueError("invalid signature")

    if not expiry_str.lstrip("-").isdigit():
        raise ValueError("malformed token")
    expiry = int(expiry_str)

    if now >= expiry:
        raise ValueError("token expired")

    try:
        subject_bytes = base64.urlsafe_b64decode(encoded_subject.encode("ascii"))
    except (ValueError, TypeError):
        raise ValueError("malformed token")

    try:
        return subject_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("malformed token")
