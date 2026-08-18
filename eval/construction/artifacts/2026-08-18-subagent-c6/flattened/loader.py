"""Merge step for the nightly warehouse load.

A landing file arrives and its records are applied onto the current table
contents, keyed on ``key``. Every record is a dict with ``key`` (a unique
string), ``updated_at`` (an int epoch second) and ``value``.

The rule is one line: for each key, the record with the greatest ``updated_at``
survives. Everything below is what that rule implies, and the places where the
obvious implementation gets it wrong.

Late-arriving records
---------------------
The obvious merge -- index ``existing`` by key, then overwrite with everything
in ``batch`` -- is last-writer-wins by arrival rather than by timestamp. It is
wrong whenever a batch record is older than the row it matches, which happens
routinely: a replayed file, a backfill of an old partition, a re-delivery after
an upstream retry. Overwriting there destroys newer state with older state, and
nothing downstream can tell that it happened.

A batch record strictly older than the row it matches is discarded instead. Per
key, the table only ever moves forward in time.

Duplicate keys within a batch
-----------------------------
``key`` is unique in the table but not within a landing file. Change feeds
routinely emit several revisions of the same row in one window. Keeping the
last by file position -- what building a dict from the batch does -- picks the
right record only if the file happens to be ordered by ``updated_at``, and
quietly picks a stale one if it is not.

Duplicates within a batch are resolved by the same timestamp rule as everything
else, so the file's ordering does not decide which record wins.

Tie-breaks
----------
Epoch seconds are coarse enough that ties are ordinary rather than exotic, so
the tie-break is part of the contract and not an accident of implementation:

* Between ``batch`` and ``existing``, the batch record wins. It is the fresher
  observation of the same source state, and for readers the substitution is a
  no-op.
* Within ``batch``, the later position in the file wins.

Guarantees
----------
* **Idempotent.** Merging a batch twice gives the same table as merging it
  once, so a nightly run that failed partway can simply be re-run. This follows
  from the tie-breaks: on the second pass every batch record either ties with
  the row it wrote itself, or loses to a strictly newer one.
* **Order-independent.** For keys that do not tie on ``updated_at``, applying
  Monday's file and then Tuesday's gives the same table as the reverse.
* **Stable output order.** Rows carried over from ``existing`` keep their
  relative order, and keys new in ``batch`` follow in the order they first
  appear there. Nothing is sorted and nothing is shuffled, so consecutive runs
  produce output that diffs cleanly.
* **Nothing is mutated.** Neither argument is modified, and the returned list
  is new.

Out of scope
------------
Deletes. The record schema carries no tombstone field, so a key that stops
appearing in batches keeps its last known value indefinitely. If the source
begins emitting deletions this function has to be told about them explicitly:
inferring them from absence would be wrong, because a batch is a window of
changes rather than a snapshot of the table.

Records are returned by reference rather than copied, so the returned list
holds the very dicts that were passed in. Copying a warehouse table's worth of
rows to defend against a caller that mutates its own inputs is not a trade
worth making; this function simply never mutates them.

Malformed records raise rather than being skipped. A row dropped quietly during
a nightly load surfaces weeks later as a gap nobody can account for, whereas a
load that fails at 02:00 naming the offending record is recoverable.
"""

from typing import Any

__all__ = ["merge"]

Record = dict[str, Any]

_KEY = "key"
_UPDATED_AT = "updated_at"
_VALUE = "value"


def merge(existing: list[Record], batch: list[Record]) -> list[Record]:
    """Apply a landing batch onto the current table contents.

    Args:
        existing: The current table contents. ``key`` must be unique across it.
        batch: The records in the file that just arrived. May legitimately hold
            several records for the same key.

    Returns:
        The new table contents: one record per key, each being the record with
        the greatest ``updated_at`` seen for that key. Rows carried over from
        ``existing`` keep their relative order, and keys new in ``batch``
        follow in first-appearance order.

    Raises:
        TypeError: If either argument is not a list of records, if a record is
            not a dict, if ``key`` is not a str, or if ``updated_at`` is not an
            int.
        ValueError: If a record lacks ``key``, ``updated_at`` or ``value``, or
            if ``existing`` contains the same key twice.
    """
    _check_records("existing", existing)
    _check_records("batch", batch)

    # key -> (updated_at, record). The timestamp rides alongside the record so
    # the comparison below does not re-read and re-validate a field per hit.
    table: dict[str, tuple[int, Record]] = {}

    for index, record in enumerate(existing):
        key, updated_at = _check_record("existing", index, record)
        if key in table:
            # `key` is the table's primary key, so two rows sharing one means
            # the table is already corrupt and there is no basis for choosing
            # between them. Picking a winner here would paper over that.
            raise ValueError(
                f"existing[{index}]: duplicate key {key!r}; the current table "
                "already violates its primary key"
            )
        table[key] = (updated_at, record)

    for index, record in enumerate(batch):
        key, updated_at = _check_record("batch", index, record)
        held = table.get(key)
        # `>=` rather than `>` applies both tie-breaks in this one comparison:
        # a batch record displaces an equally-timestamped row from `existing`,
        # and a later batch record displaces an equally-timestamped earlier one
        # from the same file. Falling through is the late-arriving case -- the
        # record is older than what is held, so it is dropped.
        if held is None or updated_at >= held[0]:
            table[key] = (updated_at, record)

    # Reassigning a key a dict already holds leaves its position alone, so this
    # is `existing` in its original order followed by the keys new in `batch`,
    # in the order they first appeared there.
    return [record for _, record in table.values()]


def _check_records(name: str, records: list[Record]) -> None:
    # A file with no rows is an empty list, never None. None here means an
    # upstream step returned nothing, which is a failure to surface rather than
    # a zero-row load to wave through -- merging it as empty would republish
    # the previous table as though tonight's file had been applied.
    if not isinstance(records, (list, tuple)):
        raise TypeError(
            f"{name} must be a list of records, got {type(records).__name__}"
        )


def _check_record(source: str, index: int, record: Record) -> tuple[str, int]:
    """Validate one record, returning the ``(key, updated_at)`` it merges on."""
    if not isinstance(record, dict):
        raise TypeError(
            f"{source}[{index}] must be a dict record, got {type(record).__name__}"
        )

    if _KEY not in record:
        raise ValueError(f"{source}[{index}] has no {_KEY!r} field")
    key = record[_KEY]
    if not isinstance(key, str):
        # Non-str keys still hash, so this would merge rather than fail: 1, 1.0
        # and True are one dict key between them, and three unrelated rows
        # would collapse into one.
        raise TypeError(
            f"{source}[{index}]: {_KEY!r} must be a str, got "
            f"{type(key).__name__} ({key!r})"
        )

    if _UPDATED_AT not in record:
        raise ValueError(
            f"{source}[{index}] (key {key!r}) has no {_UPDATED_AT!r} field"
        )
    updated_at = record[_UPDATED_AT]
    # bool is a subclass of int; True would quietly mean epoch second 1. The
    # likelier arrival is a str, from JSON with quoted numbers, and it is
    # refused rather than compared: str timestamps order lexicographically, so
    # "9" outranks "10" and the merge is wrong without ever raising.
    if isinstance(updated_at, bool) or not isinstance(updated_at, int):
        raise TypeError(
            f"{source}[{index}] (key {key!r}): {_UPDATED_AT!r} must be an int "
            f"epoch second, got {type(updated_at).__name__} ({updated_at!r})"
        )

    # Present but null is a value; absent is a truncated row.
    if _VALUE not in record:
        raise ValueError(f"{source}[{index}] (key {key!r}) has no {_VALUE!r} field")

    return key, updated_at
