"""Nightly warehouse load: merge step.

Combines the current table contents with a newly arrived batch file,
producing the next table contents. Each record is a dict with a unique
``key``, an integer epoch-second ``updated_at``, and a ``value``.

Merge semantics (last-write-wins by ``updated_at``):
  - A key present only in ``existing`` is carried through unchanged.
  - A key present only in ``batch`` is inserted.
  - A key present in both is kept if its ``updated_at`` is strictly newer
    than the current version, or replaced otherwise. This makes the
    result deterministic even when ``batch`` contains a stale, delayed,
    or duplicate record for a key already reflected in ``existing``.
  - If ``batch`` itself contains multiple records for the same key, they
    are folded in order using the same rule, so the surviving record is
    always the one with the greatest ``updated_at`` (ties broken by
    latest position in ``batch``).

Row order in the result: existing rows keep their original relative
order (updated in place when superseded), followed by brand-new keys in
the order they first appear in ``batch``.
"""

from __future__ import annotations

from typing import Any


def merge(existing: list[dict[str, Any]], batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the new table contents after applying ``batch`` to ``existing``.

    Args:
        existing: Current table contents. Each record must contain
            ``key``, ``updated_at``, and ``value``.
        batch: Newly arrived records to merge in, using the same shape.

    Returns:
        A new list of records representing the merged table. Neither
        input list nor its dicts are mutated.
    """
    order: list[str] = []
    merged: dict[str, dict[str, Any]] = {}

    for record in existing:
        key = record["key"]
        if key not in merged:
            order.append(key)
        merged[key] = dict(record)

    for record in batch:
        key = record["key"]
        current = merged.get(key)
        if current is None or record["updated_at"] >= current["updated_at"]:
            if key not in merged:
                order.append(key)
            merged[key] = dict(record)

    return [merged[key] for key in order]
