"""Reference implementation for c004. Not shown to any answerer."""
import hashlib

PSEUDONYMISED = ("email", "phone")


def _token(field: str, value: object, salt: str) -> str:
    # Keyed hash, not an encoding: the output cannot be turned back into the
    # input by anyone holding the file. The field name is mixed in so one
    # person's email and phone do not collapse to the same identifier.
    digest = hashlib.blake2b(
        f"{field}:{value}".encode("utf-8"),
        key=salt.encode("utf-8")[:64],
        digest_size=16,
    )
    return f"{field}_{digest.hexdigest()}"


def pseudonymise(record: dict, salt: str) -> dict:
    # A new dict: the caller's row is a live user record, not scratch space.
    out = dict(record)
    for field in PSEUDONYMISED:
        if field in out:
            out[field] = _token(field, out[field], salt)
    return out
