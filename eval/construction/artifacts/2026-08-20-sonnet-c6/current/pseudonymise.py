"""Pseudonymize direct identifiers before they cross the trust boundary to a vendor.

This module implements one control from the data map: `email` and `phone`
are direct identifiers, their purpose here is "let the analytics vendor
count distinct users," and their legal basis for leaving our systems in
this form is that they are pseudonymized, not sent raw. Everything else on
the record is left untouched — this function does not decide what other
fields belong in the export, only how the two identifiers are transformed.

Technique: salted HMAC-SHA256, not a bare hash.

    email / phone are low-entropy inputs — a bare SHA-256 over them is
    trivially reversible via a dictionary or rainbow-table attack, so it
    would not actually protect the vendor's copy. Keying the hash with a
    salt (HMAC) means the pseudonym cannot be inverted or matched against a
    guessed value without that salt. The salt must be generated with a CSPRNG,
    kept out of the exported table, and treated as a secret with the same
    handling as any key: not logged, not committed, rotated on a schedule.

Determinism (why the vendor's distinct-user count is trustworthy):

    The same (identifier, salt) pair always produces the same pseudonym, so
    the same person is not double-counted just because they show up twice.
    Inputs are normalized before hashing (case/whitespace for email,
    punctuation and formatting for phone) so that two representations of
    the same real-world identifier — "Jane@Example.com" vs
    " jane@example.com", "(555) 123-4567" vs "+15551234567" — collapse to
    one pseudonym instead of splitting one person into two.

Reversibility: this is pseudonymization, not anonymization. Anyone holding
the salt plus a candidate value can recompute the pseudonym and test for a
match — that is a deliberate, disclosed property (see
engineering/engineering-privacy-engineer.md, "Anonymization vs
Pseudonymization"), not a defect. Do not describe this output as anonymized,
and do not hand the salt to the vendor.

Rotate the salt (and therefore break linkability with any prior export) once
this vendor relationship or export no longer needs distinct-user tracking
across deliveries.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Dict, Optional

# Anything other than a digit or a leading '+' is formatting noise for a
# phone number ("(555) 123-4567", "555-123-4567", "+1 555 123 4567") and is
# stripped so equivalent numbers normalize to the same pseudonym.
_PHONE_NOISE_RE = re.compile(r"[^\d+]")


def _normalise_email(value: str) -> str:
    """Fold case and surrounding whitespace so equivalent emails match."""
    return value.strip().lower()


def _normalise_phone(value: str) -> str:
    """Strip formatting so equivalent phone numbers match."""
    return _PHONE_NOISE_RE.sub("", value.strip())


def _pseudonymise_value(value: Any, salt: str, normalise) -> Optional[str]:
    """Return a salted-HMAC pseudonym for `value`, or None for a missing value.

    `None` is passed through as `None` rather than pseudonymized into a
    misleading, seemingly-valid token — a missing identifier should stay
    visibly missing to the vendor, not collapse into "everyone with no
    email," which would silently corrupt the distinct-user count.
    """
    if value is None:
        return None

    text = value if isinstance(value, str) else str(value)
    normalised = normalise(text)
    digest = hmac.new(
        salt.encode("utf-8"),
        normalised.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return digest


def pseudonymise(record: Dict[str, Any], salt: str) -> Dict[str, Any]:
    """Return a copy of `record` with `email` and `phone` replaced by pseudonyms.

    Args:
        record: A user record. Must contain `email` and `phone` (either may
            be `None`); any other fields are copied through unchanged and
            are not otherwise inspected — this function has one job.
        salt: A secret, CSPRNG-generated string used as the HMAC key. Reuse
            the same salt across an export so the same person always gets
            the same pseudonym (that's what makes "count distinct users"
            meaningful); keep it out of the exported table and out of logs.

    Returns:
        A new dict; `record` is not mutated. `email` and `phone` are
        replaced with hex-encoded HMAC-SHA256 pseudonyms (or left as `None`
        if absent/`None`). All other keys are passed through as-is.

    Raises:
        ValueError: if `salt` is not a non-empty string.
        KeyError: if `record` has no `email` or `phone` key at all — a
            record missing the field entirely is a shape violation the
            caller should fix, distinct from the field being present but
            `None`.
    """
    if not isinstance(salt, str) or not salt:
        raise ValueError("salt must be a non-empty string")

    if "email" not in record or "phone" not in record:
        raise KeyError("record must contain 'email' and 'phone' fields")

    result = dict(record)
    result["email"] = _pseudonymise_value(record["email"], salt, _normalise_email)
    result["phone"] = _pseudonymise_value(record["phone"], salt, _normalise_phone)
    return result
