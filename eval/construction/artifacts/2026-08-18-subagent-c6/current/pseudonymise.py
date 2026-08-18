"""Deterministic pseudonymisation of direct identifiers for third-party export.

:func:`pseudonymise` replaces the two direct identifiers in a user record --
``email`` and ``phone`` -- with keyed pseudonyms before the record crosses the
trust boundary to an analytics vendor. The mapping is deterministic, so one
person yields one pseudonym on every export and the vendor can still count
distinct users. Every other field is passed through untouched.

What this is, precisely
-----------------------
This is *pseudonymisation*, not anonymisation. The output is still personal
data under GDPR Art. 4(5): anyone holding ``salt`` can re-derive the pseudonym
for a known email or phone and re-identify the row. Three consequences follow,
and they are part of the control rather than footnotes to it:

1. The salt is a **secret key**. It must never be sent to the vendor, written
   to a log, committed, or shipped alongside an export. Store it where signing
   keys are stored, not in the config file next to the vendor's API endpoint.
2. Use a **different salt per recipient**. One shared salt lets two vendors
   join their datasets on the pseudonym column; per-recipient salts make those
   pseudonym spaces disjoint, so a join across them yields nothing.
3. Rotating the salt invalidates every pseudonym issued under the old one, and
   counts will not join across the rotation. Rotate on a schedule agreed with
   the recipient, and record when it happened, or the vendor will read a
   rotation as their entire user base churning overnight.

Why a keyed hash and not a plain digest
---------------------------------------
``sha256(phone)`` is not a control. The phone space is roughly 10^10 values;
anyone can enumerate all of them and invert the whole column in seconds. Email
falls the same way to any breach corpus. HMAC under a secret key of real
entropy is what makes the mapping non-invertible to a party that lacks the key,
which is why a weak ``salt`` is rejected outright here rather than accepted
with a warning nobody reads.

What this does NOT protect
--------------------------
Every other field is passed through as specified, including any identifier
still sitting among them: name, address, IP, device id, free-text notes, and
the classic re-identifying trio of postcode, birthdate and gender. Masking
email and phone while exporting those does not make the export anonymous -- it
just moves the re-identification path one column to the right. Review the full
field list against the data map before shipping, and drop, bucket, or
aggregate whatever has no purpose at the vendor. Minimisation is a separate
control, and this module cannot perform it for you.

The export itself needs a legal basis, a processing agreement with the vendor,
and an entry in the data-flow map. Pseudonymisation lowers the risk of the
flow; it does not create the basis for it.

Requires Python 3.9+.
"""

from __future__ import annotations

import hmac
import re
import secrets
import unicodedata
from hashlib import sha256
from typing import Any, Callable, Optional

__all__ = ["pseudonymise", "generate_salt", "PSEUDONYMISED_FIELDS"]


#: The fields replaced with pseudonyms. Everything else passes through as-is.
PSEUDONYMISED_FIELDS = ("email", "phone")

# Length of the hex pseudonym, in characters: 32 hex chars = 128 bits of the
# HMAC-SHA256 digest. The birthday bound puts the chance of *any* collision
# across a 10^9-row table below 1e-20, so truncation cannot distort a distinct
# count, and the export carries half the bytes of a full digest.
_PSEUDONYM_HEX_LENGTH = 32

# Minimum accepted salt length, in characters. A salt short enough to guess
# makes the whole control decorative (see "Why a keyed hash" above), so this is
# enforced rather than advised. 32 chars is the width of a 128-bit hex secret;
# :func:`generate_salt` produces something comfortably past it.
_MIN_SALT_LENGTH = 32

_NON_DIGITS = re.compile(r"[^0-9]")


def generate_salt() -> str:
    """Mint a fresh 256-bit salt as hex.

    Use one per recipient, store it as a secret, and keep it out of the export.
    """
    return secrets.token_hex(32)


def _validate_salt(salt: str) -> None:
    if not isinstance(salt, str):
        raise TypeError(f"salt must be a str, got {type(salt).__name__}")
    if len(salt) < _MIN_SALT_LENGTH:
        raise ValueError(
            f"salt must be at least {_MIN_SALT_LENGTH} characters of "
            f"high-entropy secret, got {len(salt)}. A guessable salt lets "
            f"anyone brute-force the pseudonyms back to the original email or "
            f"phone. Use generate_salt()."
        )


def _normalise_email(value: str) -> str:
    """Canonicalise an address so that one mailbox yields one pseudonym.

    Case differences and Unicode encoding differences are the two ways the same
    mailbox reaches us as two different strings, and either one would split a
    single person into two "distinct users" in the vendor's counts. NFKC folds
    the encoding variants; lowercasing folds the case. Lowercasing the local
    part goes slightly beyond RFC 5321, which permits it to be case-sensitive,
    but no mailbox provider in practice treats it that way, and the theoretical
    over-merge is a smaller error than the routine miscount.

    Deliberately *not* done: stripping ``+tag`` suffixes or dots from the local
    part. Those rules are provider-specific; applying them universally would
    fuse genuinely separate accounts into one pseudonym, which is an
    irreversible and invisible corruption of the counts.
    """
    return unicodedata.normalize("NFKC", value.strip()).lower()


def _normalise_phone(value: str) -> str:
    """Reduce a number to digits, preserving international form.

    ``"+1 (555) 010-9999"``, ``"+1-555-010-9999"`` and ``"+15550109999"`` are
    one person and must produce one pseudonym. A leading ``00`` is the
    international access prefix and folds to ``+`` for the same reason.

    Limitation worth knowing before trusting the counts: a national-format
    number (``"5550109999"``) cannot be reconciled with its international form
    (``"+15550109999"``) without knowing the country, and this function will
    not guess one -- a guess would silently mint a confidently wrong pseudonym.
    If the table mixes formats, normalise to E.164 upstream. This strips
    punctuation; it cannot repair a missing country code.
    """
    text = value.strip()
    if text.startswith("00"):
        text = "+" + text[2:]
    digits = _NON_DIGITS.sub("", text)
    if not digits:
        return ""
    return "+" + digits if text.startswith("+") else digits


def _pseudonym(field: str, normalised: str, salt: str) -> str:
    # The field name is bound into the message (domain separation) so the same
    # string in two different columns does not hash to the same pseudonym, and
    # so a pseudonym taken from one column can never be tested against another.
    message = f"{field}:{normalised}".encode("utf-8")
    digest = hmac.new(salt.encode("utf-8"), message, sha256).hexdigest()
    return digest[:_PSEUDONYM_HEX_LENGTH]


def _pseudonymise_value(
    field: str,
    value: Any,
    normalise: Callable[[str], str],
    salt: str,
) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        # Coercing here would be worse than failing: a number stored as an int
        # and the same number stored as text must not silently become two
        # different pseudonyms for one person. Fix the type upstream.
        raise TypeError(
            f"record[{field!r}] must be a str or None, got "
            f"{type(value).__name__}"
        )
    normalised = normalise(value)
    if not normalised:
        # An empty or punctuation-only value is an absent identifier, and an
        # absent identifier must not be given an identity: hashing "" would
        # hand every record missing this field the same pseudonym, which the
        # vendor would read as one improbably busy user.
        return None
    return _pseudonym(field, normalised, salt)


def pseudonymise(record: dict, salt: str) -> dict:
    """Return a copy of ``record`` with ``email`` and ``phone`` pseudonymised.

    The same identifier under the same salt always produces the same pseudonym,
    so distinct-user counts survive the transformation. Different salts produce
    unrelated pseudonyms, and no pseudonym can be reversed without the salt.

    :param record: A user record. ``email`` and ``phone`` are replaced; all
        other fields are copied through untouched, in their original order.
        A ``str`` value is normalised then pseudonymised; ``None``, an empty
        value, or one that normalises to nothing becomes ``None``. A field
        absent from ``record`` stays absent -- this does not invent identifiers
        that were never there.
    :param salt: The secret key for the HMAC. Not a per-record salt: it is a
        long-lived secret, one per recipient, and it never leaves your systems.
        See the module docstring.
    :returns: A new dict. ``record`` is never mutated. The copy is shallow, so
        any nested mutable values are shared with the input -- do not mutate
        them afterwards expecting the two to stay independent.
    :raises TypeError: if ``record`` is not a dict, ``salt`` is not a str, or a
        pseudonymised field holds something other than a str or ``None``.
    :raises ValueError: if ``salt`` is too short to be a meaningful secret.
    """
    if not isinstance(record, dict):
        raise TypeError(f"record must be a dict, got {type(record).__name__}")
    _validate_salt(salt)

    normalisers = {"email": _normalise_email, "phone": _normalise_phone}

    result = dict(record)
    for field in PSEUDONYMISED_FIELDS:
        if field not in result:
            continue
        result[field] = _pseudonymise_value(
            field, result[field], normalisers[field], salt
        )
    return result
