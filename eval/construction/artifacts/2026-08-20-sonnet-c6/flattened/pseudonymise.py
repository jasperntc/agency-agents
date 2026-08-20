"""Pseudonymise direct identifiers before handing records to a third party.

`pseudonymise` replaces the `email` and `phone` fields of a record with
deterministic, salted pseudonyms so an external party (e.g. an analytics
vendor) can count and join on distinct individuals without ever seeing the
underlying identifiers.

Design notes:

- Pseudonyms are computed with HMAC-SHA256, keyed by the caller-supplied
  salt. A keyed MAC is used instead of a bare hash (e.g. plain SHA-256 of
  the value) because emails and phone numbers are low-entropy: a bare hash
  is trivially reversible by brute-forcing or rainbow-tabling the space of
  plausible values. HMAC with a secret salt as the key defeats that attack
  as long as the salt itself stays confidential and is not shipped
  alongside the pseudonymised data.
- Values are normalised before hashing (case-folded and whitespace-trimmed
  for email; punctuation/whitespace stripped for phone) so that trivial
  formatting differences ("Jane@Example.com" vs "jane@example.com", or
  "+1 (555) 010-0000" vs "555-010-0000") still collapse to the same
  pseudonym. Without normalisation the vendor's distinct-user count would
  be inflated by formatting noise rather than reflecting real users.
- A missing/empty/None value is pseudonymised to None rather than hashed
  as an empty string. Hashing an empty (or otherwise absent) value would
  give every record with no email, say, the same non-null pseudonym,
  which silently manufactures a fake "shared identity" between unrelated
  people who simply have no email on file.
- The input record is never mutated; a shallow copy is returned with only
  `email` and `phone` replaced. Every other field is passed through
  untouched.
- Standard library only: `hashlib`/`hmac` for the MAC, `re` for
  normalisation.
"""

from __future__ import annotations

import hashlib
import hmac
import re

# Digits only; phone normalisation strips everything else (spaces,
# hyphens, parentheses, dots, a leading "+", extension markers, etc.).
_NON_DIGIT_RE = re.compile(r"\D+")


def _normalise_email(value: str) -> str:
    """Fold an email to a canonical comparable form.

    Email local parts are technically case-sensitive per RFC 5321, but in
    practice virtually every real-world mail provider treats them as
    case-insensitive. For pseudonymisation purposes, treating visually
    identical addresses that differ only in case or surrounding
    whitespace as the same person is the correct trade-off: the goal is
    an accurate distinct-user count, and case differences in the wild are
    overwhelmingly copy/paste or input noise rather than distinct
    mailboxes.
    """
    return value.strip().lower()


def _normalise_phone(value: str) -> str:
    """Fold a phone number to a canonical comparable form.

    Strips everything but digits, discarding spaces, hyphens, dots,
    parentheses, and leading "+" so that equivalent numbers entered in
    different formats hash identically.
    """
    return _NON_DIGIT_RE.sub("", value)


def _pseudonymise_value(value, salt: str, *, normalise) -> "str | None":
    """Return a deterministic HMAC-SHA256 pseudonym for `value`, or None.

    `value` that is None or, once stripped, empty is treated as "no
    identifier present" and pseudonymised to None rather than to the hash
    of an empty string.
    """
    if value is None:
        return None

    text = str(value)
    normalised = normalise(text)
    if not normalised:
        return None

    digest = hmac.new(
        salt.encode("utf-8"),
        normalised.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def pseudonymise(record: dict, salt: str) -> dict:
    """Return a copy of `record` with `email` and `phone` pseudonymised.

    Every field other than `email` and `phone` is copied through
    unchanged. The same (email, salt) or (phone, salt) pair always
    produces the same pseudonym, so a vendor can count and join on
    distinct users without ever seeing the real email address or phone
    number.

    Args:
        record: A mapping with `email` and `phone` keys plus arbitrary
            other fields. Either of `email`/`phone` may be absent, None,
            or empty; in that case the corresponding output field is
            None.
        salt: Secret key mixed into the pseudonym via HMAC. Must be kept
            confidential and separate from the pseudonymised data — an
            attacker who has both the salt and the output can trivially
            re-derive the pseudonym for any candidate email or phone
            number.

    Returns:
        A new dict with `email` and `phone` replaced by their pseudonyms
        and all other fields left as-is. The input `record` is not
        mutated.

    Raises:
        TypeError: If `record` is not a dict or `salt` is not a str.
        ValueError: If `salt` is empty.
    """
    if not isinstance(record, dict):
        raise TypeError(f"record must be a dict, got {type(record).__name__}")
    if not isinstance(salt, str):
        raise TypeError(f"salt must be a str, got {type(salt).__name__}")
    if not salt:
        raise ValueError("salt must not be empty")

    result = dict(record)
    result["email"] = _pseudonymise_value(
        record.get("email"), salt, normalise=_normalise_email
    )
    result["phone"] = _pseudonymise_value(
        record.get("phone"), salt, normalise=_normalise_phone
    )
    return result
