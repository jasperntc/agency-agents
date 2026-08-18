"""Naive first draft for c004. Calibration only -- never shown to an answerer.

Stable, opaque-looking, and completely reversible.
"""
import base64


def pseudonymise(record: dict, salt: str) -> dict:
    record["email"] = base64.b64encode(
        record["email"].encode("utf-8")).decode("ascii")
    record["phone"] = "***-***-" + str(record["phone"])[-4:]
    return record
