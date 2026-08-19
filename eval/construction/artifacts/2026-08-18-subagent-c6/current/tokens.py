"""Signed session tokens for the internal admin tool.

Contract
--------
    issue(subject, secret, now, ttl=900) -> str
    verify(token, secret, now) -> str        # the subject, or raises ValueError

A session token is a *bearer credential*: whoever holds the string is the
subject until it expires.  Every decision below follows from that one sentence.

What the signature covers
-------------------------
The MAC is computed over the **whole** payload -- subject, issued-at and
expiry together -- and not over the subject alone.  That is the difference
between a token and a decoration.  A signature covering only the subject
round-trips perfectly and is forgeable in exactly the direction that matters:
the holder of one valid token edits the expiry sitting beside it and mints
themselves a credential that outlives their access, or stretches fifteen
minutes into a year.  Here, nothing outside the MAC is trusted, and nothing
inside it can be changed without the key.

Wire format
-----------
ASCII, URL- and cookie-safe, unpadded::

    v1.<payload>.<mac>

    payload = base64url(UTF-8 JSON {"exp": int, "iat": int, "jti": str, "sub": str})
    mac     = base64url(HMAC-SHA256(K, b"stok.v1." + payload))
    K       = HMAC-SHA256(secret, b"stok.v1 session-token signing key")

Three deliberate choices are packed into that:

* **The label is signed.**  ``stok.v1.`` binds every MAC to this scheme and
  this version, so a token minted by a future v2 -- or by some other feature
  that happens to share the secret -- can never be replayed as a v1 session.
  The base64url alphabet excludes ``.``, so the concatenation is unambiguous
  and no subject can smuggle in a separator.
* **The key is derived, not used raw.**  The same domain separation is applied
  to the key itself, so reusing ``secret`` for another purpose cannot yield
  bytes that verify here.
* **The encoding is canonical.**  Padding and out-of-alphabet characters are
  rejected, and the MAC is compared in its encoded form, so one token means
  one string.  A replay cache or an audit log keyed on the token text cannot
  be fooled by a re-encoded twin of a token we already accepted.

Signed is not encrypted.  Anyone holding the token can read the payload, so
``subject`` should be an opaque user identifier, and must never carry a secret,
a role grant, or anything you would not be willing to print in a log.

Clock and validity window
-------------------------
Neither function reads the clock.  The caller passes ``now``, so one request is
judged against one instant and tests can name their times.  A token is valid on
``[iat, iat + ttl)`` -- live at the second it is issued, dead at the second it
expires.  There is no skew allowance in either direction: issuing and verifying
happen against the same clock here, and a token dated in the future is a
symptom (a mis-set host, a replayed mint), not something to accommodate.

Lifetime and revocation
-----------------------
There is no revocation.  A stateless MAC cannot be un-issued, so the only thing
bounding the blast radius of a stolen token is its lifetime -- hence the
900-second default, which should stay in minutes.  If the admin tool needs "log
this person out *now*", the choices are a denylist of ``jti`` values (each token
carries a random one) holding each entry only until its ``exp`` passes, or an
opaque server session that can be deleted outright.  Neither belongs in here.

Key management
--------------
``secret`` should be at least 32 random bytes from a password manager or KMS,
never a memorable string: an HMAC key that can be guessed is not a key.  To
rotate, verify with the new secret and, on ``BadSignatureError`` only, retry
once with the previous one for the length of a single token lifetime -- then
delete the old secret.

Transport and audit
-------------------
TLS only, in an ``HttpOnly; Secure; SameSite=Lax`` cookie or an
``Authorization`` header -- never in a query string, where it lands in access
logs, referrers and browser history.  Every rejection is logged through
``logging`` under this module's name with a stable code.  Those codes and the
exception messages are for that log and for your own error handling; do not
echo them to the caller.  The response to a bad token is a flat 401, because
"expired" and "bad signature" are free information for someone probing.
"""

import base64
import binascii
import hmac
import json
import logging
import re
import secrets
from hashlib import sha256
from typing import Any

__all__ = [
    "DEFAULT_TTL",
    "BadSignatureError",
    "ExpiredTokenError",
    "MalformedTokenError",
    "TokenError",
    "TokenNotYetValidError",
    "issue",
    "verify",
]

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())

#: Token format version.  Matched exactly on the way in, so that an old token
#: meets a clear rejection instead of a mis-parse once the format moves on.
_VERSION = "v1"
_SEP = "."

#: Domain separation.  Both labels name the scheme *and* the version, which is
#: what stops a signature made in one context from being accepted in another.
_SIGN_LABEL = b"stok.v1."
_KEY_LABEL = b"stok.v1 session-token signing key"

#: Unpadded base64url alphabet.  A ``fullmatch`` against this rejects ``=`` and
#: any stray whitespace, which is what keeps the encoding canonical.
_B64 = re.compile(r"[A-Za-z0-9_-]+")

#: Ceiling on what we will even attempt to authenticate.  A real token is a
#: couple of hundred characters; anything vastly larger is someone arranging
#: for us to hash megabytes on their behalf.
_MAX_TOKEN_CHARS = 8192

#: Default lifetime in seconds.  Fifteen minutes: long enough for an admin
#: session, short enough that a leaked token is a quarter-hour problem.
DEFAULT_TTL = 900


class TokenError(ValueError):
    """A token was rejected.

    Subclasses ``ValueError`` because that is ``verify``'s documented contract.
    The subclasses exist so a caller can tell "expired, send them back to the
    login page" apart from "forged, raise an alert" without matching strings.
    """

    code = "invalid_token"


class MalformedTokenError(TokenError):
    """Not shaped like one of our tokens at all.  Never authenticated."""

    code = "malformed_token"


class BadSignatureError(TokenError):
    """The MAC did not match: forged, tampered with, or signed by another key.

    This is the one worth alerting on.  Users do not produce these by accident.
    """

    code = "bad_signature"


class ExpiredTokenError(TokenError):
    """Authentic, but its window has closed.  The ordinary end of a session."""

    code = "expired_token"


class TokenNotYetValidError(TokenError):
    """Authentic, but dated in the future.  Suspect a clock, then a replay."""

    code = "token_not_yet_valid"


def _is_int(value: Any) -> bool:
    """True for a real ``int``.  ``bool`` is an ``int`` subclass and is not one."""
    return isinstance(value, int) and not isinstance(value, bool)


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    # Safe only because the caller has already fullmatched the alphabet.
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signing_key(secret: str) -> bytes:
    """Derive this scheme's signing key from the shared secret."""
    if not isinstance(secret, str):
        raise TypeError("secret must be a str")
    if not secret:
        # An HMAC under an empty key is a public checksum: anyone can compute
        # it, so every token would be forgeable.  Refuse rather than pretend.
        raise ValueError("refusing to sign or verify with an empty secret")
    return hmac.new(secret.encode("utf-8"), _KEY_LABEL, sha256).digest()


def _mac(key: bytes, encoded_payload: str) -> str:
    signed = _SIGN_LABEL + encoded_payload.encode("ascii")
    return _b64e(hmac.new(key, signed, sha256).digest())


def _reject(error: type[TokenError], detail: str, **context: Any) -> TokenError:
    """Record the auth event, and hand back the exception for the caller to raise."""
    _log.warning(
        "session_token.rejected code=%s detail=%s context=%s",
        error.code,
        detail,
        context,
    )
    return error(detail)


def issue(subject: str, secret: str, now: int, ttl: int = DEFAULT_TTL) -> str:
    """Mint a token for ``subject``, valid on ``[now, now + ttl)``.

    Args:
        subject: Identifier of the authenticated principal.  Readable by anyone
            holding the token, so prefer an opaque user id.
        secret: The shared signing secret.  See "Key management" above.
        now: Current time as an int epoch second.  It is written into the token
            verbatim, which is why it must be a whole second and not a float.
        ttl: Seconds the token stays valid.  Keep it in minutes; there is no
            revocation.  Zero or less is not rejected here -- it simply mints a
            token that is already expired, which ``verify`` then turns away
            like any other.

    Returns:
        The token string ``v1.<payload>.<mac>``, URL- and cookie-safe.

    Raises:
        TypeError: ``subject`` is not a str, or ``now``/``ttl`` is not an int.
        ValueError: the secret is empty, or the subject cannot be encoded as
            UTF-8 (an unpaired surrogate).
    """
    if not isinstance(subject, str):
        raise TypeError("subject must be a str")
    if not _is_int(now):
        raise TypeError("now must be an int epoch second")
    if not _is_int(ttl):
        raise TypeError("ttl must be an int number of seconds")

    key = _signing_key(secret)
    payload = {
        "exp": now + ttl,
        "iat": now,
        # A random token id.  Nothing here reads it back, but it gives the
        # audit log a handle on one specific token, and gives a future denylist
        # something to hold that is not the credential itself.
        "jti": _b64e(secrets.token_bytes(9)),
        "sub": subject,
    }
    try:
        raw = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("subject is not encodable as UTF-8") from exc

    encoded = _b64e(raw)
    _log.debug(
        "session_token.issued sub=%s jti=%s exp=%s", subject, payload["jti"], payload["exp"]
    )
    return _SEP.join((_VERSION, encoded, _mac(key, encoded)))


def verify(token: str, secret: str, now: int) -> str:
    """Return the subject ``token`` was issued for, if it is valid at ``now``.

    Args:
        token: The token string exactly as ``issue`` returned it.  Treated as
            hostile input until the MAC has been checked.
        secret: The shared signing secret it was issued under.
        now: Current time in epoch seconds.  Only ever compared here, never
            stored, so a float from ``time.time()`` is accepted as well as an
            int.

    Returns:
        The subject, read out of the payload only after that payload has been
        authenticated.

    Raises:
        TokenError: a ``ValueError`` subclass -- ``MalformedTokenError``,
            ``BadSignatureError``, ``ExpiredTokenError`` or
            ``TokenNotYetValidError``.  Every rejection is one of these, so a
            caller catching ``ValueError`` catches all of them.  The message
            says which; the HTTP response must not.
        TypeError: ``secret`` is not a str, or ``now`` is not a number.  Those
            are bugs in the calling code, not bad tokens.
    """
    if not isinstance(now, (int, float)) or isinstance(now, bool):
        raise TypeError("now must be a number of epoch seconds")
    # Configuration errors surface as themselves, before any attacker-supplied
    # bytes are touched.
    key = _signing_key(secret)

    if not isinstance(token, str):
        raise _reject(MalformedTokenError, "token must be a str", got=type(token).__name__)
    if not token or len(token) > _MAX_TOKEN_CHARS:
        raise _reject(
            MalformedTokenError, "token is empty or implausibly long", size=len(token)
        )

    parts = token.split(_SEP)
    if len(parts) != 3:
        raise _reject(MalformedTokenError, "token is not three dot-separated segments")
    version, encoded, mac = parts
    if version != _VERSION:
        raise _reject(MalformedTokenError, "unsupported token version", version=version[:8])
    if not _B64.fullmatch(encoded) or not _B64.fullmatch(mac):
        raise _reject(MalformedTokenError, "segments are not canonical base64url")

    # Authenticate first, parse second.  Below this line the bytes are known to
    # come from a holder of the key; above it they are a stranger's.  Handing
    # unauthenticated input to a parser buys nothing and costs a decode surface.
    # compare_digest keeps the comparison constant-time, so a near miss cannot
    # be walked byte by byte into a hit.
    if not hmac.compare_digest(_mac(key, encoded), mac):
        raise _reject(BadSignatureError, "signature does not match")

    try:
        payload = json.loads(_b64d(encoded).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _reject(MalformedTokenError, "payload is not valid UTF-8 JSON") from exc

    if not isinstance(payload, dict):
        raise _reject(MalformedTokenError, "payload is not an object")
    subject = payload.get("sub")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    if not isinstance(subject, str) or not _is_int(issued_at) or not _is_int(expires_at):
        raise _reject(MalformedTokenError, "payload claims are missing or mistyped")

    # Both bounds came out of the MAC, so neither can be moved by the holder.
    # The order matters only to the log: a future-dated token is a different
    # incident from an expired one.
    if now < issued_at:
        raise _reject(
            TokenNotYetValidError,
            "token is dated in the future",
            sub=subject,
            skew=issued_at - now,
        )
    if now >= expires_at:
        raise _reject(
            ExpiredTokenError, "token has expired", sub=subject, age=now - expires_at
        )

    _log.debug("session_token.accepted sub=%s jti=%s", subject, payload.get("jti"))
    return subject
