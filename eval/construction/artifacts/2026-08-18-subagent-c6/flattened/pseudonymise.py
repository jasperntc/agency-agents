"""Deterministic pseudonymisation of direct identifiers for third-party export.

Replaces the ``email`` and ``phone`` fields of a user record with keyed
pseudonyms, so an analytics vendor can count distinct users -- and follow them
across successive exports -- without ever receiving a contact detail.

How the token is built
----------------------
``HMAC-SHA256(key=salt, msg=domain || 0x00 || normalised_value)``, hex encoded.

*Keyed, not plain.* ``sha256(email)`` is not a pseudonym. Addresses are readily
enumerable from breach corpora, and phone numbers are far worse: a national
number space is on the order of 10**10 candidates, exhaustible in minutes on
commodity hardware. An unkeyed digest is undone by enumeration, not by
cryptanalysis. HMAC forces an attacker to recover the salt first. The salt is
therefore a *secret key*, not a public parameter: never ship it to the vendor,
never commit it, never log it, and keep it wherever production secrets already
live.

*Domain separated.* Email and phone derive under distinct domain strings, so a
recipient holding both tokens cannot test whether they came from the same
underlying string, and the two identifier spaces cannot collide.

*Untruncated.* The full 256-bit digest is emitted. Shortening it for tidiness
would let two people collapse onto one token and silently corrupt the
distinct-user count this export exists to produce.

Limits of what this buys you
----------------------------
1. This is pseudonymisation, not anonymisation. Determinism is the stated
   requirement -- it is what makes distinct-user counting possible -- and it is
   exactly what keeps the output linkable across exports and over time. The
   result remains personal data (GDPR Art. 4(5), Recital 26): still in scope for
   access and deletion requests, retention limits, and the processor contract.
2. Masking two fields does not protect a record that still carries other
   identifiers. A row exported alongside a name, postal address, account or
   device id, IP address, or exact date of birth is re-identifiable by join, and
   these tokens will have bought nothing. Minimise the rest of the record before
   export. This module deliberately passes other fields through untouched, so
   that judgement stays with the caller who can actually make it.
3. Rotating the salt invalidates every token. That is the intended kill switch
   for a vendor relationship, but it also breaks their historical joins, so it
   is a planned migration rather than a surprise.
"""

from __future__ import annotations

import hmac
import re
import unicodedata
from hashlib import sha256
from typing import Any, Callable

__all__ = ["pseudonymise", "MIN_SALT_BYTES", "PSEUDONYMISED_FIELDS"]


MIN_SALT_BYTES = 16
"""Shortest salt accepted, measured in UTF-8 bytes.

The confidentiality of every token rests on this one value, so a guessable salt
is equivalent to publishing the plaintext. Generate one with
``secrets.token_urlsafe(32)`` and store it as a secret.
"""

_MIN_SALT_DISTINCT_CHARS = 5

# Version the domain strings: any change to the normalisation rules below is a
# change of meaning, and must ship as a new domain so that old and new tokens
# are visibly different rather than subtly incomparable.
_EMAIL_DOMAIN = b"pseudonymise/v1/email"
_PHONE_DOMAIN = b"pseudonymise/v1/phone"

_NON_DIGIT = re.compile(r"\D+")


def _normalise_email(value: str) -> str:
    """Fold an address to the single form that represents one person.

    NFKC collapses compatibility-equivalent Unicode, so an address does not
    split into two pseudonyms over an encoding difference. Case folding is
    applied to the whole address: RFC 5321 makes the local part formally
    case-sensitive, but no mail provider in practice treats it that way, and
    fragmenting one person across ``A@x.com`` and ``a@x.com`` is a far more
    likely error than merging two genuinely distinct mailboxes.

    Provider-specific tricks (Gmail dot-insensitivity, ``+tag`` subaddressing)
    are deliberately *not* applied. They hold for some domains and not others,
    and applying them universally would merge records that the source table
    holds as separate users.
    """
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _normalise_phone(value: str) -> str:
    """Reduce a phone number to its digits.

    Punctuation, spaces and the leading ``+`` are discarded, so ``+1 (555)
    123-4567``, ``1-555-123-4567`` and ``15551234567`` all converge on one
    token.

    What this cannot do is supply a missing country context. ``020 7946 0958``
    and ``+44 20 7946 0958`` are the same London line but yield different
    tokens, and a trailing extension is concatenated onto the subscriber number.
    If the source table mixes national and international formats, canonicalise
    to E.164 upstream, otherwise the vendor's distinct-user count will
    overcount.
    """
    return _NON_DIGIT.sub("", unicodedata.normalize("NFKC", value))


_FIELD_SPEC: dict[str, tuple[bytes, Callable[[str], str]]] = {
    "email": (_EMAIL_DOMAIN, _normalise_email),
    "phone": (_PHONE_DOMAIN, _normalise_phone),
}

PSEUDONYMISED_FIELDS = tuple(_FIELD_SPEC)
"""Record fields this module rewrites. Everything else is passed through."""


def _salt_to_key(salt: str) -> bytes:
    """Validate the salt and return it as HMAC key material.

    Fails loudly rather than degrading quietly: a weak key produces output that
    looks exactly like strong output, so the mistake would otherwise surface
    only after the export had left the building.
    """
    if not isinstance(salt, str):
        raise TypeError(f"salt must be a str, got {type(salt).__name__}")

    key = salt.encode("utf-8")
    if len(key) < MIN_SALT_BYTES:
        raise ValueError(
            f"salt must be at least {MIN_SALT_BYTES} bytes, got {len(key)}; "
            "generate one with secrets.token_urlsafe(32) and store it as a secret"
        )

    # A cheap smoke test for obviously degenerate keys ("0000000000000000",
    # sixteen spaces, one repeated word). It is not an entropy measurement and
    # cannot be: a random salt of this length essentially never trips it, but a
    # low-entropy salt can still slip past. Use a CSPRNG.
    if len(set(salt)) < _MIN_SALT_DISTINCT_CHARS:
        raise ValueError(
            "salt has too few distinct characters to be a random secret; "
            "generate one with secrets.token_urlsafe(32)"
        )

    return key


def _pseudonym(key: bytes, domain: bytes, normalised: str) -> str:
    """Return the hex HMAC of one normalised value under one domain."""
    message = domain + b"\x00" + normalised.encode("utf-8")
    return hmac.new(key, message, sha256).hexdigest()


def _pseudonymise_value(
    key: bytes,
    field: str,
    value: Any,
    domain: bytes,
    normalise: Callable[[str], str],
) -> str | None:
    """Pseudonymise one value, or return ``None`` when there is nothing to hash.

    Empty and unparseable values map to ``None`` rather than to the digest of
    the empty string. Hashing "" would hand every user with no phone number on
    file the same token, fabricating one enormous "distinct user" out of a
    data-quality gap -- a false linkage that reads downstream as a real cohort.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(
            f"record[{field!r}] must be a str or None, got {type(value).__name__}"
        )

    normalised = normalise(value)
    if not normalised:
        return None
    return _pseudonym(key, domain, normalised)


def pseudonymise(record: dict, salt: str) -> dict:
    """Return a copy of ``record`` with ``email`` and ``phone`` replaced by pseudonyms.

    The same input value under the same salt always yields the same token, so
    the recipient can count distinct users and join rows across exports. Every
    other field is copied through unchanged; see the module docstring on why
    that leaves minimising them squarely with the caller.

    Args:
        record: A user record. ``email`` and ``phone`` are rewritten if present;
            a field that is absent stays absent rather than being invented.
        salt: Secret HMAC key, at least ``MIN_SALT_BYTES`` UTF-8 bytes. Must be
            withheld from the recipient of the output -- disclosing it makes
            every token trivially reversible.

    Returns:
        A new ``dict``. The pseudonymised fields hold a 64-character lowercase
        hex digest, or ``None`` where the source value was absent, empty, or
        contained nothing to normalise. Nested values under other fields are
        shared with the input rather than deep-copied; they are never mutated.

    Raises:
        TypeError: ``record`` is not a dict, ``salt`` is not a str, or a
            pseudonymised field holds something other than a str or ``None``.
        ValueError: ``salt`` is too short, or too obviously non-random to be
            safely used as a key.
    """
    if not isinstance(record, dict):
        raise TypeError(f"record must be a dict, got {type(record).__name__}")

    key = _salt_to_key(salt)

    result = dict(record)
    for field, (domain, normalise) in _FIELD_SPEC.items():
        if field in result:
            result[field] = _pseudonymise_value(
                key, field, result[field], domain, normalise
            )
    return result
