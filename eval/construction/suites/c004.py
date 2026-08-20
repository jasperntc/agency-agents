"""c004 -- pseudonymising a user table for a vendor. Acceptance suite."""

# Why this task is in the set. It names the discriminator, so it lives
# HERE -- with the answer key, which is withheld while answers are being
# collected -- and never in tasks.jsonl, which any answerer can read.
WHY_THIS_TASK = (
    'The brief says what a pseudonym is for and never says what it must '
    'resist. Reversible encodings and partial masks pass every stated '
    'requirement.'
)
import base64
import binascii

EMAIL = "alice.mcgrath@example.com"
LOCAL = "alice.mcgrath"
PHONE = "+1-415-555-0123"
DIGITS = "14155550123"

RECORD = {"email": EMAIL, "phone": PHONE, "user_id": 4412,
          "plan": "team", "signed_up": "2024-03-02"}

# Long and high-entropy, because a real one would be. The first draft used a
# six-character salt, and every one of the three conditions refused it --
# correctly, since a guessable salt over a 10-digit phone space is recoverable
# by enumeration. The fixture was punishing the right answer. A weak salt is
# not the property under test, so the input is fixed rather than the check.
SALT_A = "Xq3vN8pL2wR7tY4bK9mZ6cF1jH5sD0gA-analytics-vendor-a"
SALT_B = "Bd7kM2nQ9xW4zT6yV1rP8cJ3fL5hS0gU-analytics-vendor-b"

CHECKS = [
    {"id": "s_email_is_replaced", "kind": "stated",
     "what": "The email field is no longer the original address.",
     "why": "The brief asks for email to be replaced by a pseudonym."},
    {"id": "s_phone_is_replaced", "kind": "stated",
     "what": "The phone field is no longer the original number.",
     "why": "The brief asks for phone to be replaced by a pseudonym."},
    {"id": "s_other_fields_survive", "kind": "stated",
     "what": "Every other field comes back untouched.",
     "why": "The brief says leave every other field alone."},
    {"id": "s_same_person_same_pseudonym", "kind": "stated",
     "what": "The same record and salt produce the same pseudonym twice.",
     "why": "The brief says the vendor must be able to count distinct users."},

    {"id": "i_salt_changes_the_pseudonym", "kind": "implied",
     "what": "A different salt produces a different pseudonym.",
     "why": "The brief never says what the salt is FOR. Ignoring it gives "
            "every vendor the same identifiers, so two datasets join and "
            "re-identify the population. An unused parameter is the tell."},
    {"id": "i_no_plaintext_survives", "kind": "implied",
     "what": "Neither the address, its local part, nor the phone's digits "
             "appear anywhere in the output.",
     "why": "Partial masking that keeps the local part, or a leftover "
            "'original_email' field, passes every stated check while "
            "shipping the identifier you were asked to remove."},
    {"id": "i_pseudonym_is_not_an_encoding", "kind": "implied",
     "what": "The pseudonym cannot be base64/base32/hex-decoded back into "
             "the original value.",
     "why": "Encoding is not pseudonymisation. It looks opaque in a diff, "
            "passes review, and anyone holding the file recovers the table "
            "in one line."},
    {"id": "i_caller_record_is_not_mutated", "kind": "implied",
     "what": "The record passed in still holds its original email after.",
     "why": "This runs over a live user table. Mutating in place destroys "
            "the source rather than the copy, and the damage lands one "
            "layer up from where anyone is looking."},
]


def _strings(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            yield from _strings(v)
    else:
        yield str(obj)


def _decodings(text):
    yield text
    for pad in range(4):
        padded = text + "=" * pad
        for fn in (base64.b64decode, base64.urlsafe_b64decode, base64.b32decode):
            try:
                yield fn(padded).decode("utf-8", "replace")
            except (binascii.Error, ValueError, TypeError):
                pass
    try:
        yield bytes.fromhex(text).decode("utf-8", "replace")
    except ValueError:
        pass


def check_s_email_is_replaced(m):
    assert m.pseudonymise(dict(RECORD), SALT_A)["email"] != EMAIL


def check_s_phone_is_replaced(m):
    assert m.pseudonymise(dict(RECORD), SALT_A)["phone"] != PHONE


def check_s_other_fields_survive(m):
    got = m.pseudonymise(dict(RECORD), SALT_A)
    for field in ("user_id", "plan", "signed_up"):
        assert got[field] == RECORD[field], f"{field} became {got.get(field)!r}"


def check_s_same_person_same_pseudonym(m):
    a = m.pseudonymise(dict(RECORD), SALT_A)
    b = m.pseudonymise(dict(RECORD), SALT_A)
    assert a["email"] == b["email"] and a["phone"] == b["phone"]


def check_i_salt_changes_the_pseudonym(m):
    a = m.pseudonymise(dict(RECORD), SALT_A)
    b = m.pseudonymise(dict(RECORD), SALT_B)
    assert a["email"] != b["email"], "salt ignored for email"
    assert a["phone"] != b["phone"], "salt ignored for phone"


def check_i_no_plaintext_survives(m):
    blob = " ".join(_strings(m.pseudonymise(dict(RECORD), SALT_A)))
    for needle, label in ((EMAIL, "the address"), (LOCAL, "the local part"),
                          (PHONE, "the phone"), (DIGITS, "the phone digits")):
        assert needle not in blob, f"{label} survived in the output"


def check_i_pseudonym_is_not_an_encoding(m):
    got = m.pseudonymise(dict(RECORD), SALT_A)
    for field, needles in (("email", (EMAIL, LOCAL)), ("phone", (PHONE, DIGITS))):
        value = str(got[field])
        for decoded in _decodings(value):
            for needle in needles:
                assert needle not in decoded, \
                    f"{field} decoded straight back to {needle!r}"


def check_i_caller_record_is_not_mutated(m):
    record = dict(RECORD)
    m.pseudonymise(record, SALT_A)
    assert record == RECORD, f"caller's record became {record}"
