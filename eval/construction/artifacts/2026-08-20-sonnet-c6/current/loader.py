"""Nightly warehouse load: merge an incoming batch into the existing table.

This is the Silver-layer upsert step of the nightly load. It takes the
current table contents (``existing``) and a newly-arrived file
(``batch``) and produces the new table contents.

Merge semantics (deliberate, not implicit):
  - Records are conformed by ``key``, which is the primary key.
  - When a key appears in only one of the two inputs, that record passes
    through unchanged.
  - When a key appears in both, the record with the greater ``updated_at``
    wins, since ``updated_at`` is the source system's freshness signal and
    a table must never regress a row to older data.
  - On an exact ``updated_at`` tie, the batch record wins. The batch is
    the newly-arrived file, so on a tie it is treated as the more recent
    write for that key (last-writer-wins, batch-arrival order).

The merge is idempotent: re-running it with the same ``batch`` against its
own output reproduces the same output, because the newer-or-equal rule is
stable under repetition (whenMatchedUpdateAll / whenNotMatchedInsertAll
semantics, applied in memory).

Both inputs are treated as immutable; neither list nor its dict elements
is mutated. Row order in the result is not contractually meaningful, but
is kept deterministic (existing-then-batch, first-seen order) so that
output is reproducible and diffable across runs.
"""

from __future__ import annotations

from typing import Any


def merge(existing: list[dict[str, Any]], batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge a newly-arrived batch into the existing table contents.

    Args:
        existing: Current table contents. Each record is a dict with a
            unique ``key`` (str), ``updated_at`` (int epoch seconds), and
            ``value``.
        batch: Records from the file that just arrived, same shape as
            ``existing``. ``key`` values within ``batch`` are assumed
            unique, per the stated contract that ``key`` is unique.

    Returns:
        The new table contents: one record per distinct key, each the
        newer (by ``updated_at``) of the existing/batch versions, with
        batch winning ties. Neither input list nor its records are
        mutated.

    Raises:
        KeyError: if any record is missing ``key`` or ``updated_at`` —
            surfaced immediately rather than silently dropped or
            defaulted, since a malformed record must never pass through
            unnoticed into the table.
    """
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for record in existing:
        key = record["key"]
        record["updated_at"]  # presence check; raises KeyError if absent
        if key not in merged:
            order.append(key)
        merged[key] = record

    for record in batch:
        key = record["key"]
        incoming_updated_at = record["updated_at"]
        current = merged.get(key)
        if current is None:
            order.append(key)
            merged[key] = record
        elif incoming_updated_at >= current["updated_at"]:
            merged[key] = record

    return [merged[key] for key in order]
