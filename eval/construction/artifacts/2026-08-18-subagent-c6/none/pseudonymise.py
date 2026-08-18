"""Deterministic pseudonymisation of direct identifiers for third-party export.

Replaces the ``email`` and ``phone`` fields of a user record with stable
pseudonyms, so a downstream recipient can count and group distinct users
without holding the underlying contact details.

    >>> pseudonymise({"email": "A.User@Example.COM ", "phone": "(555) 123-4567",
    ...               "plan": "pro"}, salt=SECRET)      # doctest: +SKIP
    {'email': 'eml_kv3v...', 'phone': 'tel_7q2m...', 'plan': 'pro'}


READ THIS BEFORE YOU SHIP THE EXPORT
====================================

Three properties of this module are load-bearing.  If any one of them is
broken at the call site, the output is not protected, even though it will
look exactly as scrambled as it does now.

1.  **The salt is a secret key, not a salt.**  It must be high-entropy,
    generated once (``secrets.token_urlsafe(32)``), stored in your secrets
    manager, and *never* sent to the vendor, committed, logged, or included
    in the export.  This is the only thing standing between the vendor and
    the original values: phone numbers occupy a space of roughly 10**10
    candidates, so anyone holding both the pseudonyms and the salt can
    recover every number by brute force.  Reversal is the *designed*
    behaviour for a key holder, which is why the key does not travel.

2.  **Pseudonymisation is not anonymisation.**  Under GDPR Art. 4(5) the
    exported table is still personal data, and the vendor is still a
    processor: you still need a DPA, a lawful basis, a retention limit, and
    a deletion path.  The reason to do this anyway is blast radius -- a
    breach at the vendor leaks pseudonyms rather than a contactable list.

3.  **This module only covers the two fields it was asked to cover.**  Per
    the brief, every other field is passed through untouched.  That is a
    real limitation and not a safe default: a record carrying
    ``full_name``, ``date_of_birth``, ``postcode``, ``device_id`` or a
    last-seen IP address is trivially re-identifiable no matter what the
    ``email`` column says.  Before exporting, walk the actual column list
    and decide, per column, whether the vendor needs it at all.  Dropping a
    column beats pseudonymising it.

Rotation: changing the salt changes every pseudonym, which deliberately
breaks joins against previously exported data.  Rotate when the key is
exposed or the vendor relationship ends -- and treat the resulting inability
to join as the feature it is.


Design notes
============

*Stability.*  The vendor's distinct-user count is only correct if one person
maps to one pseudonym, so raw values are normalised before hashing:
``" A.User@Example.COM "`` and ``"a.user@example.com"`` are one user, and so
are ``"+1 (555) 123-4567"`` and ``"+1-555-123-4567"``.  See the caveats on
``_normalise_phone`` for the case this cannot fix.

*Construction.*  The salt is stretched once (PBKDF2-HMAC-SHA256) into a
256-bit key; each value is then pseudonymised with HMAC-SHA256 under that
key, with a per-field context string so the same string appearing in
``email`` and ``phone`` yields different pseudonyms.  HMAC under a secret key
is not brute-forceable regardless of how small the identifier space is,
which is what makes this safe for phone numbers; the stretching is
defence-in-depth for the case where someone passes a weak human-chosen salt
despite the advice above.  Stretching is cached per salt, so the cost is
paid once per process rather than once per row -- the per-record cost is a
single HMAC, which is fine for a full-table export.

Standard library only.  No third-party imports.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import unicodedata
from functools import lru_cache
from typing import Any, Dict, Mapping, Optional

__all__ = ["pseudonymise", "PseudonymisationError", "EMAIL_FIELD", "PHONE_FIELD"]


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------

#: Bumping this changes every pseudonym; treat it like a salt rotation.
_SCHEME = b"pseudonymise/v1"

#: Applied once per distinct salt (see the caching note above), so a high
#: count costs a fraction of a second per process, not per record.
_KEY_ITERATIONS = 600_000
_KEY_SALT = _SCHEME + b"/root-key"

#: 128 bits of pseudonym.  At 10**9 users the chance of any collision is
#: about 10**-21, i.e. collisions will not distort the vendor's counts.
_TOKEN_BYTES = 16

#: Rejecting a weak salt loudly matters more than usual here: a one-character
#: salt produces output that looks every bit as scrambled as a good one.
_MIN_SALT_LENGTH = 16

EMAIL_FIELD = "email"
PHONE_FIELD = "phone"

_EMAIL_PREFIX = "eml_"
_PHONE_PREFIX = "tel_"

#: Field context strings.  Fixed literals containing no 0x1f byte, so the
#: separator below is unambiguous no matter what the value contains.
_EMAIL_CONTEXT = b"email"
_PHONE_CONTEXT = b"phone"
_SEPARATOR = b"\x1f"

# "Jasper Ng <jasper@example.com>" -- common in exported tables.
_ANGLE_ADDR = re.compile(r"<([^<>]+)>")
# Trailing extensions: "555-0100 x89", "555-0100 ext. 89".
_EXTENSION = re.compile(r"(?:\s|^)(?:e?xt?n?)[.:]?\s*\d+\s*$", re.IGNORECASE)
_NON_DIALLABLE = re.compile(r"[^\d+]")


class PseudonymisationError(ValueError):
    """Raised when the inputs cannot be pseudonymised safely."""


# --------------------------------------------------------------------------
# Key derivation
# --------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _root_key(salt: str) -> bytes:
    """Stretch ``salt`` into a 256-bit key.

    Cached because the export loop calls this once per record with the same
    salt and PBKDF2 is deliberately slow.  The cache holds key material in
    memory for the life of the process -- which the caller's ``salt``
    variable does anyway -- so this is not a new exposure, but it is a
    reason not to hand this module a salt you would not hold in memory.
    """
    return hashlib.pbkdf2_hmac(
        "sha256", salt.encode("utf-8"), _KEY_SALT, _KEY_ITERATIONS, dklen=32
    )


def _token(context: bytes, value: str, salt: str) -> str:
    """Return the pseudonym for an already-normalised ``value``."""
    payload = context + _SEPARATOR + value.encode("utf-8")
    digest = hmac.new(_root_key(salt), payload, hashlib.sha256).digest()
    return base64.b32encode(digest[:_TOKEN_BYTES]).decode("ascii").rstrip("=").lower()


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


def _coerce(value: Any) -> Optional[str]:
    """Return ``value`` as text, or ``None`` if it carries no identifier.

    Missing values stay missing rather than being hashed.  Hashing the empty
    string would give every user without a phone number the *same*
    pseudonym, which the vendor would read as one improbably busy user.
    """
    if value is None:
        return None
    # Phone numbers are often stored as integers by well-meaning ETL.
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    return text or None


def _normalise_email(raw: str) -> str:
    """Fold away the variations that are the same mailbox in practice."""
    text = unicodedata.normalize("NFKC", raw).strip()

    angle = _ANGLE_ADDR.search(text)
    if angle:  # drop any display name
        text = angle.group(1).strip()

    # RFC 5321 permits case-sensitive local parts; no mail provider in
    # practice treats them that way, and matching people is the job here.
    local, at, domain = text.rpartition("@")
    if not at:
        # Not an address.  Still pseudonymised rather than rejected -- the
        # brief does not ask this module to validate the table -- but see
        # the placeholder caveat in `pseudonymise`.
        return text.casefold()

    # Sub-addressing ("user+tag@") and provider-specific dot-folding are
    # deliberately NOT stripped: they are distinct mailboxes at some
    # providers, and collapsing them would merge two people into one
    # pseudonym, which is a worse failure than counting one person twice.
    return local.casefold() + "@" + domain.casefold().rstrip(".")


def _normalise_phone(raw: str, default_calling_code: Optional[str]) -> str:
    """Reduce a dialled number to digits, in E.164 form where possible.

    Handles the formatting noise -- spaces, dashes, parentheses, extensions,
    a ``00`` international prefix.

    What it *cannot* do without a region hint is reconcile a national number
    with its international form: ``"555 0100"`` and ``"+1 555 0100"`` are the
    same person but normalise differently, so that person is counted twice.
    Doing this properly needs a full numbering-plan database
    (libphonenumber), which is out of scope for a standard-library module.
    If your table mixes the two formats, pass ``default_calling_code`` (e.g.
    ``"+1"``) to attach a region to bare national numbers -- and only do that
    if the table really is single-region, because attaching the wrong code
    silently merges distinct people into one pseudonym.
    """
    text = unicodedata.normalize("NFKC", raw).strip()
    text = _EXTENSION.sub("", text)

    if text.startswith("00"):  # international access prefix
        text = "+" + text[2:]

    international = text.startswith("+")
    digits = _NON_DIALLABLE.sub("", text).lstrip("+")

    if not digits:
        # Punctuation only.  Return it normalised rather than empty so that
        # different junk does not collapse to one pseudonym.
        return text.casefold()

    if international:
        return "+" + digits
    if default_calling_code:
        # Drop a national trunk prefix ("0") before attaching the code.
        return "+" + default_calling_code.lstrip("+") + digits.lstrip("0")
    return digits


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def pseudonymise(
    record: dict,
    salt: str,
    *,
    default_calling_code: Optional[str] = None,
) -> dict:
    """Return a copy of ``record`` with ``email`` and ``phone`` pseudonymised.

    Every other field is copied through untouched, and key order is
    preserved.  ``record`` itself is never modified.

    The mapping is deterministic: the same person, under the same salt,
    always gets the same pair of pseudonyms, so the recipient can count
    distinct users and join across exports.  It is one-way to anyone without
    the salt, and reversible by anyone with it -- see the module docstring.

    Args:
        record: The user row.  ``email`` and ``phone`` are pseudonymised if
            present; absent fields stay absent, and empty or ``None`` values
            stay ``None`` rather than becoming a shared pseudonym.
        salt: The secret key.  High-entropy, at least 16 characters, never
            shared with the recipient.
        default_calling_code: Optional region hint (e.g. ``"+44"``) used to
            put bare national phone numbers into E.164 form.  Only for
            single-region tables; see ``_normalise_phone``.

    Returns:
        A new ``dict``.

    Raises:
        PseudonymisationError: If ``record`` is not a mapping, or ``salt`` is
            missing, too short, or not a string.

    Note:
        Placeholder values are not detected.  If your table uses ``"n/a"``,
        ``"none"`` or ``"unknown"`` in place of a null, every such row gets
        one shared pseudonym and the recipient will see a single user with
        implausible activity.  Convert placeholders to ``None`` upstream.
    """
    if not isinstance(record, Mapping):
        raise PseudonymisationError(
            "record must be a mapping, got " + type(record).__name__
        )
    if not isinstance(salt, str):
        raise PseudonymisationError("salt must be a str, got " + type(salt).__name__)
    if len(salt.strip()) < _MIN_SALT_LENGTH:
        raise PseudonymisationError(
            "salt must be at least {n} characters of high-entropy secret (try "
            "secrets.token_urlsafe(32)); a weak salt yields output that looks "
            "scrambled but is recoverable by brute force".format(n=_MIN_SALT_LENGTH)
        )

    out: Dict[str, Any] = dict(record)

    if EMAIL_FIELD in out:
        raw = _coerce(out[EMAIL_FIELD])
        out[EMAIL_FIELD] = (
            None
            if raw is None
            else _EMAIL_PREFIX + _token(_EMAIL_CONTEXT, _normalise_email(raw), salt)
        )

    if PHONE_FIELD in out:
        raw = _coerce(out[PHONE_FIELD])
        out[PHONE_FIELD] = (
            None
            if raw is None
            else _PHONE_PREFIX
            + _token(_PHONE_CONTEXT, _normalise_phone(raw, default_calling_code), salt)
        )

    return out
