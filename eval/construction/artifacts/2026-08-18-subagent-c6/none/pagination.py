"""Cursor-based pagination for the public API.

The API returns rows newest first. :func:`page` takes the full result set and
hands back one window of it plus an opaque cursor marking the boundary, so the
caller can ask for the next window without carrying an offset.

Ordering
--------
Rows are placed in a *total* order: ``created_at`` descending, then ``id``
ascending to break ties. ``created_at`` alone is not enough -- epoch seconds
collide constantly, and two rows sharing a timestamp could otherwise swap
places between calls, which silently repeats one of them and drops the other
across a page boundary. ``id`` is unique, so the combined key is stable no
matter what order ``rows`` arrives in.

Cursors
-------
A cursor encodes the ordering key of the last row delivered; the next page is
everything strictly after that key. Two consequences worth knowing:

* Deleting the row a cursor points at does not break the cursor -- the
  boundary is a position in the ordering, not a reference to a row.
* Rows created after a walk begins sort newer than the boundary and so will
  not show up in later pages. That is the usual keyset trade-off: no repeats
  and no skips within a walk, at the cost of not seeing new arrivals mid-walk.

The encoding (base64url of a small JSON payload) is opaque but not signed.
Treat cursors as untrusted input: a tampered one can only shift the window
over rows the caller was already entitled to see, and anything malformed
raises :class:`InvalidCursor`.

Requires Python 3.10+.
"""

from __future__ import annotations

import base64
import binascii
import bisect
import json

__all__ = ["InvalidCursor", "page"]

_CURSOR_VERSION = 1


class InvalidCursor(ValueError):
    """Raised when a cursor is malformed or was not issued by this module.

    Subclasses :class:`ValueError`, so callers that already turn bad input
    into a 400 keep working without catching anything new.
    """


def _sort_key(row: dict) -> tuple[int, str]:
    """Ordering key for one row: newest first, ``id`` ascending on ties."""
    return (-row["created_at"], row["id"])


def _ordered(rows: list[dict]) -> list[dict]:
    """Validate every row, then return a newly sorted list.

    The input list is never mutated and the row dicts are passed through by
    reference, not copied.
    """
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise TypeError(f"rows[{index}] is {type(row).__name__}, expected dict")
        try:
            ident = row["id"]
            created_at = row["created_at"]
        except KeyError as exc:
            raise ValueError(f"rows[{index}] is missing key {exc.args[0]!r}") from exc
        if not isinstance(ident, str):
            raise TypeError(
                f"rows[{index}]['id'] is {type(ident).__name__}, expected str"
            )
        if isinstance(created_at, bool) or not isinstance(created_at, int):
            raise TypeError(
                f"rows[{index}]['created_at'] is {type(created_at).__name__}, "
                "expected int"
            )
        if ident in seen:
            # Two rows with one id can share an ordering key, and a cursor at
            # that key would then skip one of them. Fail loudly instead.
            raise ValueError(f"duplicate id {ident!r} at rows[{index}]; ids must be unique")
        seen.add(ident)
    return sorted(rows, key=_sort_key)


def _encode_cursor(row: dict) -> str:
    """Encode a row's ordering key as an opaque, URL-safe string."""
    payload = {"v": _CURSOR_VERSION, "t": row["created_at"], "i": row["id"]}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    # Padding is stripped so the cursor survives being pasted into a query
    # string without escaping; _decode_cursor puts it back.
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, str]:
    """Recover the ``(-created_at, id)`` boundary key from a cursor."""
    if not isinstance(cursor, str):
        raise InvalidCursor(f"cursor is {type(cursor).__name__}, expected str or None")

    text = cursor.strip()
    try:
        raw = base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursor("cursor is not a well-formed pagination cursor") from exc

    if not isinstance(payload, dict):
        raise InvalidCursor("cursor payload is not an object")
    if payload.get("v") != _CURSOR_VERSION:
        raise InvalidCursor(f"unsupported cursor version {payload.get('v')!r}")

    created_at = payload.get("t")
    ident = payload.get("i")
    if isinstance(created_at, bool) or not isinstance(created_at, int):
        raise InvalidCursor("cursor is missing a valid 'created_at'")
    if not isinstance(ident, str):
        raise InvalidCursor("cursor is missing a valid 'id'")
    return (-created_at, ident)


def page(rows: list[dict], cursor: str | None, limit: int) -> dict:
    """Return one page of ``rows``, newest first.

    Args:
        rows: The full result set, in any order. Each row needs a unique
            string ``id`` and an int ``created_at`` (epoch seconds).
        cursor: ``None`` for the first page, otherwise a ``next_cursor``
            this function returned earlier.
        limit: Maximum number of items in the page; must be at least 1.

    Returns:
        ``{"items": [...], "next_cursor": <str or None>}``. ``items`` holds at
        most ``limit`` rows (the same dict objects that were passed in), and
        ``next_cursor`` is ``None`` exactly when this is the last page -- so a
        caller can loop until it comes back ``None`` without a trailing empty
        request.

    Raises:
        InvalidCursor: ``cursor`` is malformed or of an unknown version.
        TypeError: ``limit`` or a row field has the wrong type.
        ValueError: ``limit`` is below 1, or a row is missing a field or
            repeats an ``id``.
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError(f"limit is {type(limit).__name__}, expected int")
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}")

    ordered = _ordered(rows)

    # Resume strictly after the boundary key. bisect_right lands past any row
    # holding that exact key, so a cursor is correct whether or not the row it
    # came from still exists.
    start = 0
    if cursor is not None:
        start = bisect.bisect_right(ordered, _decode_cursor(cursor), key=_sort_key)

    items = ordered[start : start + limit]
    exhausted = start + limit >= len(ordered)
    return {
        "items": items,
        "next_cursor": None if exhausted else _encode_cursor(items[-1]),
    }
