"""Merge step of the nightly warehouse load.

A *record* is a dict carrying at least these three fields:

    key         str    unique business key for the row
    updated_at  int    epoch seconds; the version stamp of this row
    value       Any    the payload -- opaque here, may be None

``merge(existing, batch)`` folds the file that just arrived (``batch``) into
the current table contents (``existing``) and returns the new table contents.
Any extra fields a record carries are passed through untouched.

Guarantees
----------
Unique by key
    Exactly one record per distinct key comes out.

Newest wins
    For each key the survivor is the record with the greatest ``updated_at``.
    A batch row older than the row already in the table is rejected, not
    applied, so re-feeding last week's file over today's table cannot walk
    rows backwards.

Ties go to the later observation
    Records are folded in ``existing`` order and then ``batch`` order; among
    the records tied at a key's highest ``updated_at``, the last one folded
    wins.  So a batch row stamped equal to the table row replaces it (the
    arriving file is the fresher observation of that same version), and a key
    repeated inside one file collapses to its last-highest occurrence.

Idempotent
    ``merge(merge(E, B), B) == merge(E, B)``.  Re-running a night's load
    duplicates nothing and moves nothing backwards, so a retry after a partial
    failure is always safe.

Canonical output
    Rows come back sorted by ``key``, which makes the result a pure function
    of the *set* of input records rather than of their arrival order.  Two
    loads that saw the same rows in a different order produce identical
    tables, so snapshot diffs and checksums mean something.

Non-mutating
    Neither argument, nor any record inside either, is modified.  The returned
    records are fresh shallow copies; ``value`` is passed through by reference
    and is never inspected.

Loud on schema drift
    A record that breaks the contract raises `SchemaContractError` naming the
    input, the row index and the key.  Nothing is silently dropped or coerced:
    a load that quietly discards malformed rows corrupts the warehouse in a
    way nobody notices until a quarterly number comes out wrong.

Limits
------
The merge is *not* order-independent when two records share a key **and** an
``updated_at`` but disagree on ``value``.  That is a source-side contract
breach -- one version, two payloads -- and this step resolves it
deterministically by arrival order rather than guessing which is true.

Deletes are out of scope: the contract has no tombstone field, so a key absent
from ``batch`` is left standing.  This is an upsert, not a full replace.

Cost
----
One pass over each input: O(n + m) time and O(k) memory for k distinct keys,
plus O(k log k) for the canonical sort.  Nothing is logged per row -- a
nightly load moves millions of rows and a line each is its own outage -- so
anomaly counts are aggregated into at most one summary line per call.
"""

import logging
from collections.abc import Mapping
from typing import Any, NamedTuple

__all__ = ["merge", "SchemaContractError"]

logger = logging.getLogger(__name__)

KEY_FIELD = "key"
UPDATED_AT_FIELD = "updated_at"
VALUE_FIELD = "value"

_EXISTING = "existing"
_BATCH = "batch"

Record = Mapping[str, Any]


class SchemaContractError(ValueError):
    """A record, or an input as a whole, broke the merge contract.

    Subclasses ``ValueError`` so callers already catching that keep working.
    Every message names the input, the row index, and the key where known --
    the three things needed to find the offending row in the source file
    without re-deriving them at 3am.
    """


class _Candidate(NamedTuple):
    """The record currently winning a key, plus what it takes to judge the next."""

    updated_at: int
    source: str
    record: Record


def _field_summary(record: Record, limit: int = 12) -> str:
    """Field names of a record, ordered and bounded, for an error message.

    Seeing what a row *does* carry is usually what identifies a rename
    upstream -- ``key`` becoming ``id``, say -- in a single read.
    """
    names = sorted(str(name) for name in record)
    if len(names) > limit:
        return f"{names[:limit]} (+{len(names) - limit} more)"
    return str(names)


def _validated(records: Any, source: str):
    """Yield ``(key, updated_at, record)`` for each record, or raise.

    Validation is per row and total: both inputs are held to the same
    contract, because a malformed row already sitting in the table is
    corruption worth hearing about too, not a fact to work around.
    """
    if records is None:
        raise SchemaContractError(
            f"{source} is None; pass an empty list to mean 'no rows'"
        )
    if isinstance(records, (str, bytes, bytearray, Mapping)):
        raise SchemaContractError(
            f"{source} is {type(records).__name__}, expected a list of records; "
            f"a single record has to be wrapped in a list"
        )

    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise SchemaContractError(
                f"{source}[{index}] is {type(record).__name__}, "
                f"expected a dict holding the record fields"
            )

        if KEY_FIELD not in record:
            raise SchemaContractError(
                f"{source}[{index}] has no {KEY_FIELD!r} field; "
                f"fields present: {_field_summary(record)}"
            )
        key = record[KEY_FIELD]
        if not isinstance(key, str):
            raise SchemaContractError(
                f"{source}[{index}] has {KEY_FIELD}={key!r} of type "
                f"{type(key).__name__}, expected str"
            )
        if not key:
            raise SchemaContractError(
                f"{source}[{index}] has an empty {KEY_FIELD}; that is usually a "
                f"null business key coalesced to '' upstream, and merging on it "
                f"would collapse unrelated rows into one"
            )

        if UPDATED_AT_FIELD not in record:
            raise SchemaContractError(
                f"{source}[{index}] (key={key!r}) has no {UPDATED_AT_FIELD!r} "
                f"field; fields present: {_field_summary(record)}"
            )
        updated_at = record[UPDATED_AT_FIELD]
        # bool is a subclass of int, and a boolean version stamp is drift
        # rather than a stamp -- so reject it before the isinstance check.
        if isinstance(updated_at, bool) or not isinstance(updated_at, int):
            raise SchemaContractError(
                f"{source}[{index}] (key={key!r}) has "
                f"{UPDATED_AT_FIELD}={updated_at!r} of type "
                f"{type(updated_at).__name__}, expected int epoch seconds"
            )

        if VALUE_FIELD not in record:
            raise SchemaContractError(
                f"{source}[{index}] (key={key!r}) has no {VALUE_FIELD!r} field; "
                f"an absent payload is drift, an empty one is data -- send it as "
                f"{VALUE_FIELD}=None; fields present: {_field_summary(record)}"
            )

        yield key, updated_at, record


def merge(existing: list[dict], batch: list[dict]) -> list[dict]:
    """Fold ``batch`` into ``existing`` and return the new table contents.

    Args:
        existing: the current table contents, unique by ``key``.
        batch: the records from the file that just arrived.

    Returns:
        A new list of new dicts, unique by ``key`` and sorted by ``key``.
        Neither argument is mutated.

    Raises:
        SchemaContractError: an input, or a record within one, broke the
            contract described in the module docstring.  Raised before
            anything is returned, so a rejected load never leaves a
            half-merged table behind.

    The full merge semantics are in the module docstring.
    """
    winners: dict[str, _Candidate] = {}
    row_counts = {_EXISTING: 0, _BATCH: 0}
    duplicate_keys = {_EXISTING: 0, _BATCH: 0}
    stale_batch_rows = 0

    for source, records in ((_EXISTING, existing), (_BATCH, batch)):
        for key, updated_at, record in _validated(records, source):
            row_counts[source] += 1
            incumbent = winners.get(key)

            if incumbent is None:
                winners[key] = _Candidate(updated_at, source, record)
                continue

            if incumbent.source == source:
                duplicate_keys[source] += 1
            elif updated_at < incumbent.updated_at:
                # Inputs are folded existing-then-batch, so a cross-source
                # clash is always a batch row meeting a row already in the
                # table -- and this one is older than what it would overwrite.
                stale_batch_rows += 1

            if updated_at >= incumbent.updated_at:
                winners[key] = _Candidate(updated_at, source, record)

    logger.debug(
        "merge: existing=%d batch=%d -> table=%d "
        "(batch rows collapsed on repeated keys: %d)",
        row_counts[_EXISTING],
        row_counts[_BATCH],
        len(winners),
        duplicate_keys[_BATCH],
    )
    if duplicate_keys[_EXISTING] or stale_batch_rows:
        # Only the anomalies that actually happened go in the alert: a warning
        # that reports "0 of X" trains people to skim past the line.
        problems = []
        if duplicate_keys[_EXISTING]:
            problems.append(
                f"{duplicate_keys[_EXISTING]} duplicate key(s) within the "
                f"existing table, which should already be unique by key -- "
                f"check whatever wrote it"
            )
        if stale_batch_rows:
            problems.append(
                f"{stale_batch_rows} batch row(s) rejected as older than the "
                f"row already in the table -- a replayed or out-of-order file, "
                f"or clock skew upstream"
            )
        logger.warning(
            "merge anomalies: %s. existing=%d batch=%d table=%d",
            "; ".join(problems),
            row_counts[_EXISTING],
            row_counts[_BATCH],
            len(winners),
        )

    # dict() both detaches the result from the caller's records and normalises
    # any other Mapping flavour to the plain dicts the signature promises.
    return [dict(winners[key].record) for key in sorted(winners)]
