"""Pseudonymise user records before handing them to an analytics vendor.

Replaces the ``email`` and ``phone`` fields of a record with salted,
deterministic pseudonyms so the vendor can still count distinct users
without ever seeing the real contact details. All other fields are
passed through unchanged.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Dict

_DIGITS_RE = re.compile(r"\D+")


def _normalise_email(email: str) -> str:
    """Fold an email address to a canonical form.

    Emails are case-insensitive and often surrounded by stray
    whitespace, so lowercase and trim before hashing. This ensures
    ``Alice@Example.com`` and ``alice@example.com `` collapse to the
    same pseudonym.
    """
    return email.strip().lower()


def _normalise_phone(phone: str) -> str:
    """Fold a phone number to a canonical form.

    Phone numbers can arrive with varying punctuation and spacing
    (e.g. ``"(555) 123-4567"`` vs ``"555-123-4567"``). Stripping
    everything but the digits keeps the same underlying number stable
    across formatting differences.
    """
    return _DIGITS_RE.sub("", phone)


def _pseudonym(value: str, field: str, salt: str) -> str:
    """Derive a deterministic, salted pseudonym for a normalised value.

    Uses HMAC-SHA256 keyed by the salt, with the field name mixed into
    the message so that an email and a phone number that happen to
    normalise to the same string never collide.
    """
    message = f"{field}:{value}".encode("utf-8")
    digest = hmac.new(salt.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{field}_{digest}"


def pseudonymise(record: Dict[str, Any], salt: str) -> Dict[str, Any]:
    """Return a copy of ``record`` with ``email`` and ``phone`` pseudonymised.

    Args:
        record: A user record containing ``email`` and ``phone`` fields
            plus arbitrary other fields.
        salt: A secret salt used to key the pseudonym derivation. The
            same salt must be used across runs for pseudonyms to stay
            consistent for the same person.

    Returns:
        A new dict with every field from ``record`` preserved, except
        that ``email`` and ``phone`` are replaced with deterministic,
        salted pseudonyms. The same person (same email or phone,
        modulo formatting) always yields the same pseudonym for a
        given salt, so the vendor can count distinct users.
    """
    result = dict(record)

    email = record.get("email")
    if email is not None:
        result["email"] = _pseudonym(_normalise_email(email), "email", salt)

    phone = record.get("phone")
    if phone is not None:
        result["phone"] = _pseudonym(_normalise_phone(phone), "phone", salt)

    return result
