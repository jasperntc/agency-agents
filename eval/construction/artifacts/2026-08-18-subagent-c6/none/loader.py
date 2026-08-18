"""Merge step for the nightly warehouse load.

The table is keyed by ``key``.  Folding a batch into it is an upsert with
last-update-wins conflict resolution: an incoming record replaces the one on
file only when its ``updated_at`` is at least as recent.

That guard is the point of this module.  Arrival order is not update order --
a failed run gets replayed, a delayed file lands behind the one it precedes, a
backfill re-sends a week of history -- and a plain ``dict.update`` would let
any of those quietly roll rows backwards onto older values.  Here they are
no-ops instead: re-loading a file changes nothing, and a late file cannot undo
a newer one that already landed.

Three conventions worth checking against the upstream feed:

* ``updated_at`` has to be comparable across every source that writes to this
  table.  Last-update-wins is exactly as trustworthy as that timestamp; two
  producers on unsynchronised clocks hand their skew straight to this merge.
* Ties go to the batch.  A record corrected upstream and re-sent under its
  original timestamp still lands, at the price of making a tie order-dependent
  -- two files carrying one key at the same second resolve to whichever is
  loaded second.
* Nothing is ever deleted.  Keys absent from the batch are left untouched and
  there is no tombstone convention, so a row dropped at the source survives
  here until something upstream supplies an explicit delete signal.

Record order in the result is stable and diffable: rows already in the table
hold their positions, and keys new to the batch are appended in the order the
batch first mentions them.
"""

__all__ = ["merge"]


def merge(existing: list[dict], batch: list[dict]) -> list[dict]:
    """Fold ``batch`` into ``existing`` and return the new table contents.

    Each record is a dict carrying at least ``key`` (a unique string) and
    ``updated_at`` (an int epoch second).  Every other field, ``value``
    included, is passed through untouched, so extra columns survive the merge.

    A key appearing more than once within a single list is collapsed by the
    same rule, which keeps the result independent of row order inside a file.

    Neither argument is mutated and every returned record is a fresh shallow
    copy, so writing to the returned table cannot reach back into the inputs.
    ``value`` itself is shared rather than deep-copied: a mutable value is
    still common to both.

    Raises:
        TypeError: a record is not a dict, or its ``key`` is not a str, or its
            ``updated_at`` is not an int.  Floats are refused as well -- a
            timestamp that changed type upstream deserves a loud failure
            rather than a silently mixed comparison.
        ValueError: a record is missing ``key`` or ``updated_at``.
    Both messages name the list and index of the offending record.
    """
    table: dict[str, dict] = {}
    for index, record in enumerate(existing):
        _absorb(table, record, "existing", index)
    for index, record in enumerate(batch):
        _absorb(table, record, "batch", index)
    return list(table.values())


def _absorb(table: dict[str, dict], record: dict, source: str, index: int) -> None:
    """Apply one record to ``table``, keeping whichever version is newer."""
    key, updated_at = _identify(record, source, index)
    held = table.get(key)
    # >= rather than >, so a tie resolves in favour of the later arrival.
    if held is None or updated_at >= held["updated_at"]:
        # Re-assigning a key already present leaves its insertion order alone,
        # which is what stops updated rows from jumping to the end of the table.
        table[key] = dict(record)


def _identify(record: dict, source: str, index: int) -> tuple[str, int]:
    """Return one record's ``(key, updated_at)``, or raise saying why not."""
    where = f"{source}[{index}]"
    if not isinstance(record, dict):
        raise TypeError(f"{where} is a {type(record).__name__}, expected a dict")
    for field in ("key", "updated_at"):
        if field not in record:
            raise ValueError(f"{where} has no {field!r} field")
    key, updated_at = record["key"], record["updated_at"]
    if not isinstance(key, str):
        raise TypeError(f"{where} has a non-str 'key': {key!r}")
    # bool is a subclass of int, and True would otherwise pass as epoch 1.
    if isinstance(updated_at, bool) or not isinstance(updated_at, int):
        raise TypeError(f"{where} has a non-int 'updated_at': {updated_at!r}")
    return key, updated_at
