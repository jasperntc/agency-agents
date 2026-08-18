"""Naive first draft for c003. Calibration only -- never shown to an answerer.

The batch is newer, so the batch wins.
"""


def merge(existing: list[dict], batch: list[dict]) -> list[dict]:
    table = {record["key"]: record for record in existing}
    for record in batch:
        table[record["key"]] = record
    return list(table.values())
