"""Signed, short-lived session tokens for the internal admin tool.

A token here is a symmetric bearer credential: whoever holds it is treated as
the subject named inside it. The module is therefore written to make the
dangerous mistakes hard rather than to be maximally flexible.

Wire format (ASCII; safe in URLs, cookies and headers)::

    stj1.<payload>.<signature>

``payload`` is unpadded base64url of a compact JSON object::

    {"exp":1755500000,"iat":1755499100,"jti":"...","sub":"alice"}

``signature`` is unpadded base64url of ``HMAC-SHA256(key, "stj1." + payload)``.

Design notes, in the order they matter:

* **The algorithm is pinned by the version prefix, never read from the token.**
  A caller cannot talk the verifier into a weaker algorithm, and there is no
  ``"none"`` to negotiate down to. Algorithm confusion is the single most
  common way both homegrown and JWT-based token schemes get broken.
* **The MAC covers the encoded payload, not a re-serialisation of it.**
  Verification never has to reproduce byte-identical JSON, so canonicalisation
  differences can never become signature bypasses.
* **Nothing inside the token is parsed before the MAC verifies.** Subject,
  expiry and every other claim are read only from authenticated bytes.
* **The signature is compared as its canonical base64 text, in constant time.**
  Exactly one token string is valid for a given payload and key, so the token
  (or its ``jti``) is safe to use as a replay or revocation key.
* **The secret is not used as the MAC key directly.** A per-purpose key is
  derived from it, so a secret that is also used elsewhere cannot produce a MAC
  that is meaningful in two different contexts.

Validity is the half-open interval ``[iat, exp)``: a token is already dead at
exactly ``exp``. There is deliberately no built-in clock-skew grace period --
a hidden grace period silently extends every token's lifetime, and the caller
supplies ``now`` anyway, so skew is theirs to decide.

Out of scope, deliberately: revocation before expiry. Tokens are short-lived
and self-contained, so a leaked token stays usable until ``exp``; keep the TTL
small. ``jti`` is present as the join key for a deny-list should one ever be
needed, and as the audit handle for a single session.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import secrets
import string

__all__ = [
    "DEFAULT_TTL_SECONDS",
    "InvalidToken",
    "MAX_SUBJECT_LENGTH",
    "MAX_TTL_SECONDS",
    "MIN_SECRET_LENGTH",
    "issue",
    "verify",
]

# Format version. It is part of the signed material, so a future "stj2" with
# different semantics can never have its payload replayed as an stj1 token.
_VERSION = "stj1"

# Domain-separation label for key derivation. Changing it invalidates every
# outstanding token, which is exactly what you want from a version bump.
_KEY_INFO = b"stj1/session-token/hmac-sha256"

_DIGEST = "sha256"
_JTI_BYTES = 16

#: Default token lifetime. Short by design; see the module docstring.
DEFAULT_TTL_SECONDS = 900

#: Hard ceiling on a token's lifetime, enforced when issuing *and* when
#: verifying. The verify-side check means a buggy or outdated issuer cannot
#: mint a long-lived token that this verifier will honour.
MAX_TTL_SECONDS = 86_400

#: Minimum secret length in UTF-8 bytes. RFC 2104 discourages HMAC keys shorter
#: than the hash output (32 bytes for SHA-256), and a short secret here is a
#: brute-forceable token forgery, not a minor weakness.
MIN_SECRET_LENGTH = 32

#: Subjects are user or service identifiers, not free text.
MAX_SUBJECT_LENGTH = 256

# Ceiling on the length of a token we are willing to look at, so hostile input
# cannot make us decode megabytes. Derived from MAX_SUBJECT_LENGTH rather than
# hardcoded, so raising the subject limit can never leave issue() minting
# tokens that verify() rejects on length. JSON escaping can expand one
# character to six (\uXXXX) and base64 adds a further 4/3.
MAX_TOKEN_LENGTH = 256 + ((6 * MAX_SUBJECT_LENGTH + 128) * 4 + 2) // 3

_B64URL_CHARS = frozenset(string.ascii_letters + string.digits + "-_")


class InvalidToken(ValueError):
    """A token was malformed, unauthentic, or outside its validity window.

    Subclasses :class:`ValueError`, so ``except ValueError`` behaves exactly as
    the API contract promises. Catch this class specifically when you need to
    tell "reject this request" apart from "this deployment is misconfigured" --
    configuration and programming errors raise plain :class:`ValueError` or
    :class:`TypeError` instead.
    """


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(segment: str) -> bytes:
    # validate=True keeps decoding strict: the default silently discards
    # characters outside the alphabet, which would let several distinct strings
    # decode to the same bytes.
    padding = "=" * (-len(segment) % 4)
    return base64.b64decode(segment + padding, altchars=b"-_", validate=True)


def _is_b64url(segment: str) -> bool:
    return bool(segment) and _B64URL_CHARS.issuperset(segment)


def _derive_signing_key(secret: str) -> bytes:
    """Derive the MAC key from the shared secret.

    This is HKDF-Expand truncated to a single output block: cheap domain
    separation, so a secret that is also used for some other purpose cannot
    yield a MAC that is meaningful in both places.
    """
    if not isinstance(secret, str):
        raise TypeError(f"secret must be a str, got {type(secret).__name__}")
    key = secret.encode("utf-8")
    if len(key) < MIN_SECRET_LENGTH:
        # Deliberately does not echo the secret, in case this ends up in a log.
        raise ValueError(
            f"secret must be at least {MIN_SECRET_LENGTH} bytes of "
            "high-entropy material; generate one with secrets.token_urlsafe(32)"
        )
    return hmac.digest(key, _KEY_INFO, _DIGEST)


def _check_epoch_second(name: str, value: object) -> int:
    # bool is a subclass of int, so True would otherwise sail through as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{name} must be an int epoch second, got {type(value).__name__}"
        )
    if value < 0:
        raise ValueError(f"{name} must not be negative, got {value}")
    return value


def _check_subject(subject: object) -> str:
    if not isinstance(subject, str):
        raise TypeError(f"subject must be a str, got {type(subject).__name__}")
    if not subject:
        raise ValueError("subject must not be empty")
    if len(subject) > MAX_SUBJECT_LENGTH:
        raise ValueError(
            f"subject must be at most {MAX_SUBJECT_LENGTH} characters, "
            f"got {len(subject)}"
        )
    # Control characters in an identifier are never legitimate, and would let a
    # subject forge line breaks in whatever audit log it lands in.
    if not subject.isprintable():
        raise ValueError("subject must not contain control characters")
    return subject


def issue(subject: str, secret: str, now: int, ttl: int = DEFAULT_TTL_SECONDS) -> str:
    """Issue a session token for ``subject``, valid from ``now`` for ``ttl`` seconds.

    Args:
        subject: Identifier the token authenticates. Printable, 1 to
            ``MAX_SUBJECT_LENGTH`` characters.
        secret: Shared signing secret, at least ``MIN_SECRET_LENGTH`` bytes.
        now: Current time as an int epoch second. Becomes the token's ``iat``.
        ttl: Lifetime in seconds; ``1`` to ``MAX_TTL_SECONDS``.

    Returns:
        The token as an ASCII string, safe to place in a URL, cookie or header.

    Raises:
        TypeError: An argument has the wrong type.
        ValueError: An argument is the right type but unusable -- an empty or
            unprintable subject, a weak secret, a negative ``now``, or a ``ttl``
            outside ``1..MAX_TTL_SECONDS``.

    The returned token is a bearer credential: treat it like a password, send it
    only over TLS, and keep it out of logs.
    """
    subject = _check_subject(subject)
    now = _check_epoch_second("now", now)
    if isinstance(ttl, bool) or not isinstance(ttl, int):
        raise TypeError(f"ttl must be an int, got {type(ttl).__name__}")
    if not 1 <= ttl <= MAX_TTL_SECONDS:
        raise ValueError(
            f"ttl must be between 1 and {MAX_TTL_SECONDS} seconds, got {ttl}"
        )
    signing_key = _derive_signing_key(secret)

    claims = {
        "sub": subject,
        "iat": now,
        "exp": now + ttl,
        # 128 bits of randomness: makes otherwise identical tokens distinct, and
        # gives every session a stable handle for audit or future revocation.
        "jti": _b64url_encode(secrets.token_bytes(_JTI_BYTES)),
    }
    payload = _b64url_encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signed = f"{_VERSION}.{payload}"
    signature = _b64url_encode(
        hmac.digest(signing_key, signed.encode("ascii"), _DIGEST)
    )
    return f"{signed}.{signature}"


def verify(token: str, secret: str, now: int) -> str:
    """Verify ``token`` and return the subject it was issued for.

    Args:
        token: A token string as produced by :func:`issue`.
        secret: The same shared signing secret it was issued with.
        now: Current time as an int epoch second.

    Returns:
        The subject named in the token.

    Raises:
        InvalidToken: A :class:`ValueError` subclass, raised when the token is
            malformed, of an unknown version, not authentic under ``secret``, or
            not valid at ``now``.
        TypeError, ValueError: Configuration or programming errors -- a
            non-string token, a weak secret, a ``now`` that is not a
            non-negative int. These mean the caller is broken, not that this
            particular request should be rejected.

    A successful return authenticates *only* the subject. Whether that subject
    may do the thing being attempted is a separate authorisation decision, and
    is not this module's job.
    """
    if not isinstance(token, str):
        raise TypeError(f"token must be a str, got {type(token).__name__}")
    now = _check_epoch_second("now", now)
    # Derived before the token is touched, so a misconfigured secret surfaces as
    # a configuration error instead of masquerading as a failed verification.
    signing_key = _derive_signing_key(secret)

    if len(token) > MAX_TOKEN_LENGTH:
        raise InvalidToken("token is too long")
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidToken("token is malformed: expected three '.'-separated segments")
    version, payload_segment, signature_segment = parts
    # Error messages never echo token content: it is attacker-controlled, and it
    # tends to end up in logs.
    if version != _VERSION:
        raise InvalidToken("token is of an unsupported version")
    if not _is_b64url(payload_segment) or not _is_b64url(signature_segment):
        raise InvalidToken("token is malformed: segments are not base64url")

    expected = hmac.digest(
        signing_key, f"{_VERSION}.{payload_segment}".encode("ascii"), _DIGEST
    )
    # Compare the canonical base64 text rather than decoded bytes: constant
    # time, and it rejects re-encodings of an otherwise valid signature, so each
    # payload has exactly one valid token string.
    if not hmac.compare_digest(signature_segment, _b64url_encode(expected)):
        raise InvalidToken("token signature does not verify")

    # --- Past this point, and not before it, the payload is authenticated. ---

    try:
        claims = json.loads(_b64url_decode(payload_segment).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidToken("token payload is not readable") from None
    if not isinstance(claims, dict):
        raise InvalidToken("token payload is not an object")

    subject = claims.get("sub")
    if (
        not isinstance(subject, str)
        or not subject
        or len(subject) > MAX_SUBJECT_LENGTH
        or not subject.isprintable()
    ):
        raise InvalidToken("token subject is missing or unusable")

    issued_at = claims.get("iat")
    expires_at = claims.get("exp")
    for value in (issued_at, expires_at):
        if isinstance(value, bool) or not isinstance(value, int):
            raise InvalidToken("token timestamps are missing or malformed")
    if expires_at <= issued_at:
        raise InvalidToken("token validity window is empty")
    if expires_at - issued_at > MAX_TTL_SECONDS:
        raise InvalidToken("token lifetime exceeds the maximum allowed")

    if now < issued_at:
        raise InvalidToken(
            "token is not valid yet; check for clock skew between issuer and verifier"
        )
    if now >= expires_at:
        raise InvalidToken("token has expired")

    return subject
