"""Cursor-based pagination for the public API.

Contract
--------
    page(rows, cursor, limit) -> {"items": [...], "next_cursor": str | None}

``rows`` is the full result set in arbitrary order; this module owns the
ordering and the slicing.  Items come back **newest first** (``created_at``
descending) with ties broken by ascending ``id``, so the ordering is a *total*
order and therefore identical on every call.

Why keyset, not offset
----------------------
The cursor encodes the *position* of the last item handed out, not a count of
items skipped.  A row inserted at the head of the result set between two calls
therefore does not shift the reader's window.  With an offset the reader would
see the boundary item twice after an insert, and skip one after a delete;
keyset pagination is immune to both, which is the only reason it earns its
extra machinery.

Ties are the whole game.  Any number of rows may share a ``created_at`` --
bulk imports produce them constantly -- and a cursor that remembers only the
timestamp must then either re-emit or drop every row in the tied group.  The
``id`` tiebreak is what makes the resume point unambiguous, so ``id``
uniqueness is a load-bearing invariant here and is checked, not assumed.

The cursor is opaque
--------------------
``next_cursor`` is an opaque, versioned string.  Clients must round-trip it
verbatim and must never parse it, build one, or store assumptions about its
shape.  The ``v1.`` prefix exists so the encoding can be replaced later while
cursors already in flight keep working: a cursor whose version we no longer
recognise is rejected as ``invalid_cursor`` rather than silently mis-decoded.

Opaque is not authenticated.  The encoding guards against accidental
corruption and truncation, not against a motivated caller.  It carries no
authorization, so a forged cursor can only move a caller around inside a
result set they were already entitled to read.

Errors
------
Every failure raises a ``PaginationError`` subclass carrying a stable,
machine-readable ``code`` that maps straight onto the platform error body:

    invalid_cursor  -> 400  the caller sent a cursor we cannot decode
    invalid_limit   -> 400  the caller sent a limit outside the allowed range
    invalid_row     -> 500  our own result set violated its schema

The codes are part of the contract.  The messages are for humans and may be
reworded at any time, so callers must branch on ``code``, never on prose.
"""

from __future__ import annotations

import base64
import bisect
import json
from typing import Any

__all__ = [
    "MAX_LIMIT",
    "InvalidCursorError",
    "InvalidLimitError",
    "InvalidRowError",
    "PaginationError",
    "page",
]

#: Largest page this endpoint will serve.  A caller asking for more is clamped
#: to this rather than rejected: the request is well-intentioned, the response
#: still honours "at most ``limit`` items", and ``next_cursor`` lets them walk
#: the rest.  An unbounded page size is a denial-of-service surface, so the
#: ceiling is not optional -- but ambushing a good client with a 400 over it is
#: gratuitous.
MAX_LIMIT = 100

_CURSOR_VERSION = "v1"
_CURSOR_PREFIX = _CURSOR_VERSION + "."


class PaginationError(Exception):
    """Base class for every pagination failure.

    Carries a stable ``code`` for machine handling alongside the human-readable
    message, so a gateway can serialise any of these into the platform's single
    error shape without inspecting the exception type.
    """

    code = "pagination_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidCursorError(PaginationError):
    """The caller supplied a cursor this version cannot decode.  Maps to 400."""

    code = "invalid_cursor"


class InvalidLimitError(PaginationError):
    """The caller supplied a limit outside the allowed range.  Maps to 400."""

    code = "invalid_limit"


class InvalidRowError(PaginationError):
    """A row in our own result set violated the schema.  Maps to 500.

    This is never the caller's fault: it means the data we were handed is
    missing a field, has the wrong type, or repeats an ``id``.  Failing loudly
    beats paginating a result set whose ordering cannot be made total, because
    that silently loses or repeats rows at page boundaries.
    """

    code = "invalid_row"


def page(rows: list[dict], cursor: str | None, limit: int) -> dict[str, Any]:
    """Return one page of ``rows``, newest first.

    Args:
        rows: The full result set, in arbitrary order.  Each row must be a dict
            with a unique ``id`` (``str``) and a ``created_at`` (``int`` epoch
            seconds).  Extra keys are passed through untouched.
        cursor: ``None`` for the first page; otherwise a ``next_cursor`` value
            this function returned earlier.  The row it names need not still
            exist -- if it has since been deleted, the next page resumes at
            whatever now falls immediately after it.
        limit: Maximum items to return.  Must be an ``int`` >= 1.  Values above
            :data:`MAX_LIMIT` are clamped to it, so a page may be shorter than
            requested while still not being the last one; that is precisely
            what ``next_cursor`` is for.

    Returns:
        ``{"items": [...], "next_cursor": str | None}``.  ``items`` holds at
        most ``limit`` rows -- the same dict objects that were passed in, not
        copies -- ordered newest first.  ``next_cursor`` is ``None`` if and only
        if this is the last page, so a caller never needs a trailing empty
        request to discover the end.

    Raises:
        InvalidLimitError: ``limit`` is not an ``int``, or is < 1.
        InvalidCursorError: ``cursor`` is not a string this version can decode.
        InvalidRowError: a row is malformed or an ``id`` is duplicated.
    """
    limit = _normalise_limit(limit)
    entries = _ordered_entries(rows)

    if cursor is None:
        start = 0
    else:
        # bisect_right lands on the first entry strictly after the cursor's
        # key.  That is the resume point whether or not the cursor's own row is
        # still present, which is exactly the behaviour we want when a row is
        # deleted between two pages.
        keys = [key for key, _row in entries]
        start = bisect.bisect_right(keys, _sort_key(*_decode_cursor(cursor)))

    window = entries[start : start + limit]
    items = [row for _key, row in window]

    next_cursor = None
    if start + limit < len(entries):
        # There is at least one entry past this window, so the window is
        # non-empty and its last row is a valid resume point.
        last = items[-1]
        next_cursor = _encode_cursor(last["created_at"], last["id"])

    return {"items": items, "next_cursor": next_cursor}


def _normalise_limit(limit: int) -> int:
    """Validate ``limit`` and clamp it to :data:`MAX_LIMIT`."""
    # bool is a subclass of int; page(rows, None, True) is a caller bug, not a
    # request for one item.
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise InvalidLimitError(
            f"limit must be an integer, got {type(limit).__name__}"
        )
    if limit < 1:
        raise InvalidLimitError(f"limit must be at least 1, got {limit}")
    return min(limit, MAX_LIMIT)


def _sort_key(created_at: int, row_id: str) -> tuple[int, str]:
    """Total order over rows: ``created_at`` descending, then ``id`` ascending.

    Negating the timestamp lets a single ascending sort express "newest first,
    ties broken by ascending id", which keeps the resume comparison a plain
    tuple comparison instead of a hand-written predicate -- the usual home of
    off-by-one bugs in keyset pagination.
    """
    return (-created_at, row_id)


def _ordered_entries(rows: list[dict]) -> list[tuple[tuple[int, str], dict]]:
    """Validate every row and return ``(sort_key, row)`` pairs, newest first."""
    entries: list[tuple[tuple[int, str], dict]] = []
    seen: set[str] = set()

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise InvalidRowError(
                f"row at index {index} must be a dict, got {type(row).__name__}"
            )
        try:
            row_id = row["id"]
            created_at = row["created_at"]
        except KeyError as exc:
            raise InvalidRowError(
                f"row at index {index} is missing required field {exc.args[0]!r}"
            ) from exc

        if not isinstance(row_id, str):
            raise InvalidRowError(
                f"row at index {index} has a non-string id "
                f"({type(row_id).__name__})"
            )
        if isinstance(created_at, bool) or not isinstance(created_at, int):
            raise InvalidRowError(
                f"row {row_id!r} has a non-integer created_at "
                f"({type(created_at).__name__}); epoch seconds are required"
            )
        if row_id in seen:
            raise InvalidRowError(
                f"duplicate id {row_id!r} in the result set; ids must be unique "
                "for the page boundary to be unambiguous"
            )

        seen.add(row_id)
        entries.append((_sort_key(created_at, row_id), row))

    # Sorting on the key alone: the rows themselves are never compared, so a
    # dict landing in a comparison is impossible regardless of the data.
    entries.sort(key=lambda entry: entry[0])
    return entries


def _encode_cursor(created_at: int, row_id: str) -> str:
    """Encode a resume point as an opaque, versioned, URL-safe string."""
    payload = json.dumps(
        {"i": row_id, "t": created_at}, separators=(",", ":"), sort_keys=True
    ).encode("ascii")  # json escapes non-ASCII by default, so this is total
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return _CURSOR_PREFIX + encoded


def _decode_cursor(cursor: str) -> tuple[int, str]:
    """Decode a cursor into ``(created_at, id)``.

    Every malformed input funnels into :class:`InvalidCursorError`.  Nothing
    from base64 or json is allowed to escape: a caller who fumbled a cursor
    should get one documented error code, not a decoder's internals.
    """
    if not isinstance(cursor, str):
        raise InvalidCursorError(
            f"cursor must be a string or None, got {type(cursor).__name__}"
        )
    if not cursor.startswith(_CURSOR_PREFIX):
        raise InvalidCursorError(
            "cursor was not issued by this version of the API; pass cursor=None "
            "to start again from the first page"
        )

    encoded = cursor[len(_CURSOR_PREFIX) :]
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        # validate=True: the default silently discards characters outside the
        # alphabet, which would let a corrupted cursor decode to a plausible
        # but wrong position.
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        # binascii.Error, UnicodeDecodeError and JSONDecodeError are all
        # ValueError subclasses, so this single clause is exhaustive.
        raise InvalidCursorError("cursor is malformed and cannot be decoded") from exc

    if not isinstance(payload, dict):
        raise InvalidCursorError("cursor is malformed and cannot be decoded")

    created_at = payload.get("t")
    row_id = payload.get("i")
    if (
        isinstance(created_at, bool)
        or not isinstance(created_at, int)
        or not isinstance(row_id, str)
    ):
        raise InvalidCursorError("cursor is malformed and cannot be decoded")

    return created_at, row_id
