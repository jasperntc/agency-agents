"""Merge step for the nightly warehouse load.

Combines the current table contents with a newly arrived batch of records,
keeping exactly one record per key and preferring whichever version of that
record is most recently updated.
"""

from typing import Any, Dict, List

Record = Dict[str, Any]


def merge(existing: List[Record], batch: List[Record]) -> List[Record]:
    """Merge ``batch`` into ``existing`` and return the new table contents.

    Each record is a dict with a unique ``key``, an integer epoch-second
    ``updated_at``, and a ``value``. For any key present in both inputs, the
    record with the greater ``updated_at`` wins; on a tie, the batch record
    wins, since it represents the most recently arrived data for that key.

    The relative order of records is preserved: records already present in
    ``existing`` keep their original position, and new keys introduced by
    ``batch`` are appended in the order they appear in ``batch``.

    Neither ``existing`` nor ``batch`` is mutated.
    """
    merged: Dict[str, Record] = {}
    order: List[str] = []

    for record in existing:
        key = record["key"]
        if key not in merged:
            order.append(key)
        merged[key] = record

    for record in batch:
        key = record["key"]
        if key not in merged:
            order.append(key)
            merged[key] = record
            continue

        current = merged[key]
        if record["updated_at"] >= current["updated_at"]:
            merged[key] = record

    return [merged[key] for key in order]
