"""Cursor pagination for the public API.

The API returns rows newest first. This module turns a result set into stable,
resumable pages using *keyset* (a.k.a. seek) pagination rather than offset
pagination.

Why keyset
----------
Offset pagination (``LIMIT n OFFSET k``) is wrong for a public API whose data
changes underneath the client. If a row is inserted ahead of the client's
position between two requests, every later page shifts by one and the client
silently re-reads a row; if a row is deleted, the client silently skips one.
Keyset pagination anchors the next page to the *sort position* of the last row
already delivered, so churn elsewhere in the set cannot shift it.

The total order
---------------
``created_at`` alone is not a total order: two rows can share an epoch second,
and their relative order is then undefined and free to change between
requests -- which reintroduces exactly the skip-and-duplicate bugs that keyset
pagination exists to prevent. The sort key here is therefore

    (created_at DESC, id ASC)

which is a strict total order because ``id`` is unique. The cursor encodes both
halves of that key. That is also why a cursor keeps working after the row it
was minted from is deleted: it names a *position*, not a row.

Cursors are opaque
------------------
Callers pass ``next_cursor`` back verbatim and never parse or construct one.
The encoding carries a version tag so the format can change without breaking
cursors already in flight, and a short digest so a truncated or mangled cursor
fails cleanly instead of quietly returning the wrong page. That digest is an
integrity check, not a security signature: it is unkeyed and anyone can forge
one. Nothing here is an authorization boundary -- a cursor only picks a
position within the ``rows`` the caller already decided this client may see.

Scope
-----
This is an in-memory helper: it receives the whole result set and does the
filtering itself, costing O(n) time and O(limit) extra space per page. That is
the right shape for a result set already in hand and the wrong shape for a
large table, where the same predicate belongs in the query instead:

    WHERE created_at < :cursor_created_at
       OR (created_at = :cursor_created_at AND id > :cursor_id)
    ORDER BY created_at DESC, id ASC
    LIMIT :limit + 1

(Spelled out rather than as a row-value comparison, which inverts confusingly
for a mixed-direction key.) The cursor format and the ``limit + 1`` lookahead
carry over to that version unchanged, so the migration is not a contract
change.
"""

from __future__ import annotations

import base64
import hashlib
import heapq
import hmac
import json
from typing import Any, Dict, Iterator, List, Optional, Tuple, TypedDict

__all__ = [
    "MAX_LIMIT",
    "InvalidCursor",
    "InvalidLimit",
    "Page",
    "PaginationError",
    "Row",
    "page",
]

Row = Dict[str, Any]


class Page(TypedDict):
    """One page of results. ``next_cursor`` is None on the last page."""

    items: List[Row]
    next_cursor: Optional[str]


MAX_LIMIT = 100
"""Largest page a client may request.

Part of the published contract, so raise it freely but lower it only through
the deprecation process. An uncapped ``limit`` lets a single request become an
unbounded response.
"""

_CURSOR_VERSION = 1

# 4 bytes catches accidental corruption comfortably and keeps the cursor short.
# It is not sized to resist a forger; see the module docstring.
_DIGEST_SIZE = 4

# A cursor we issue is well under 100 chars. Anything far larger is not ours,
# and refusing it early avoids base64-decoding and parsing attacker-sized input.
_MAX_CURSOR_CHARS = 512


class PaginationError(ValueError):
    """Base class for bad pagination input.

    Subclasses ``ValueError`` so existing handlers keep working. Catch this at
    the transport edge and map it to 400: every subclass is the client's
    mistake, never ours.
    """


class InvalidCursor(PaginationError):
    """The cursor was not one this module issued, or was corrupted in transit."""


class InvalidLimit(PaginationError):
    """``limit`` was outside the documented range."""


def _key(created_at: int, row_id: str) -> Tuple[int, str]:
    """The ascending sort key realising ``(created_at DESC, id ASC)``.

    Negating ``created_at`` flips only that half of the key, so ids stay
    ascending within a shared timestamp -- which a plain ``reverse=True`` would
    not do. Unique ids make this a strict total order, and a strict total order
    is what makes a page boundary reproducible across requests.
    """
    return (-created_at, row_id)


def _row_key(row: Row) -> Tuple[int, str]:
    return _key(row["created_at"], row["id"])


def _validate_row(row: Any, index: int) -> None:
    """Fail loudly on a malformed row, naming which one and why.

    Without this, a missing or wrongly typed field surfaces as an opaque
    ``TypeError`` from deep inside a sort, with nothing identifying the row.
    """
    if not isinstance(row, dict):
        raise TypeError(f"rows[{index}] is {type(row).__name__}, expected dict")
    try:
        row_id = row["id"]
        created_at = row["created_at"]
    except KeyError as exc:
        raise KeyError(
            f"rows[{index}] is missing required key {exc.args[0]!r}"
        ) from None
    if not isinstance(row_id, str):
        raise TypeError(f"rows[{index}]['id'] is {type(row_id).__name__}, expected str")
    if not isinstance(created_at, int) or isinstance(created_at, bool):
        raise TypeError(
            f"rows[{index}]['created_at'] is {type(created_at).__name__}, "
            "expected int epoch seconds"
        )


def _encode_cursor(row: Row) -> str:
    """Encode a row's sort position as an opaque, URL-safe token."""
    body = json.dumps(
        {"v": _CURSOR_VERSION, "t": row["created_at"], "i": row["id"]},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.blake2b(body, digest_size=_DIGEST_SIZE).digest()
    # Padding is stripped so the cursor survives query strings, logs and shells
    # without escaping; it is restored on the way back in.
    return base64.urlsafe_b64encode(digest + body).rstrip(b"=").decode("ascii")


def _decode_cursor(cursor: Any) -> Tuple[int, str]:
    """Recover ``(created_at, id)`` from a cursor, or raise ``InvalidCursor``.

    Every failure path raises the same exception type: a client that sends a
    broken cursor gets one clear error, not a menu of internal ones.
    """
    if not isinstance(cursor, str):
        raise InvalidCursor(
            f"cursor must be a str or None, got {type(cursor).__name__}"
        )
    if not cursor:
        raise InvalidCursor("cursor is empty; pass None to request the first page")
    if len(cursor) > _MAX_CURSOR_CHARS:
        raise InvalidCursor(
            f"cursor is {len(cursor)} chars, over the {_MAX_CURSOR_CHARS} limit"
        )

    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
    except ValueError:  # covers binascii.Error and non-ascii input
        raise InvalidCursor("cursor is not valid base64url") from None

    if len(raw) <= _DIGEST_SIZE:
        raise InvalidCursor("cursor is truncated")
    digest, body = raw[:_DIGEST_SIZE], raw[_DIGEST_SIZE:]
    expected = hashlib.blake2b(body, digest_size=_DIGEST_SIZE).digest()
    if not hmac.compare_digest(digest, expected):
        raise InvalidCursor(
            "cursor failed its integrity check; it was altered or truncated"
        )

    try:
        payload = json.loads(body)
    except ValueError:  # covers malformed JSON and bad UTF-8
        raise InvalidCursor("cursor payload is not valid JSON") from None
    if not isinstance(payload, dict):
        raise InvalidCursor("cursor payload is not an object")
    if payload.get("v") != _CURSOR_VERSION:
        raise InvalidCursor(
            f"cursor version {payload.get('v')!r} is not supported by this build "
            f"(expected {_CURSOR_VERSION}); restart pagination without a cursor"
        )

    created_at = payload.get("t")
    row_id = payload.get("i")
    # The digest is unkeyed, so these checks -- not the digest -- are what stop
    # a hand-rolled cursor from putting arbitrary types into the comparison.
    if (
        not isinstance(created_at, int)
        or isinstance(created_at, bool)
        or not isinstance(row_id, str)
    ):
        raise InvalidCursor("cursor payload is malformed")
    return created_at, row_id


def _eligible(rows: List[Row], after_key: Optional[Tuple[int, str]]) -> Iterator[Row]:
    """Yield validated rows that sort strictly after the cursor position.

    A generator, so the heap below never materialises an intermediate copy of
    the result set.
    """
    for index, row in enumerate(rows):
        _validate_row(row, index)
        if after_key is None or _row_key(row) > after_key:
            yield row


def page(rows: list[dict], cursor: str | None, limit: int) -> Page:
    """Return one page of ``rows``, newest first.

    Args:
        rows: The full result set, in any order. Every row needs a unique
            string ``id`` and an int ``created_at`` in epoch seconds. The list
            is not modified, and the returned items are the caller's own dict
            objects rather than copies.
        cursor: None for the first page; otherwise the ``next_cursor`` from the
            previous call, passed back verbatim. Normalise a missing query
            parameter to None -- ``""`` is rejected rather than read as "first
            page", so a dropped parameter cannot silently restart iteration.
        limit: Rows per page, from 1 to ``MAX_LIMIT``.

    Returns:
        ``{"items": [...], "next_cursor": ...}``: at most ``limit`` items
        ordered newest first, and ``next_cursor`` None on the last page. A full
        page does not imply another page exists -- the end is detected by
        reading one row past the page, so iteration finishes without a trailing
        empty page.

    Raises:
        InvalidLimit: ``limit`` is not an int in range. Map to 400.
        InvalidCursor: ``cursor`` is not one we issued. Map to 400.
        TypeError, KeyError: A malformed row or ``rows`` argument. This is our
            bug, not the client's; let it surface as a 500 rather than
            reporting it as bad input.

    Iterating a whole result set:

        >>> rows = [{"id": "b", "created_at": 2}, {"id": "a", "created_at": 2},
        ...         {"id": "c", "created_at": 1}]
        >>> cursor, seen = None, []
        >>> while True:
        ...     result = page(rows, cursor, 2)
        ...     seen.extend(row["id"] for row in result["items"])
        ...     cursor = result["next_cursor"]
        ...     if cursor is None:
        ...         break
        >>> seen
        ['a', 'b', 'c']

    ``a`` precedes ``b`` there because they share a timestamp and the unique id
    breaks the tie -- the detail that makes the page boundary stable.

    Caveat: a cursor records a position, not the query that produced it. This
    helper cannot see the filters or sort behind ``rows``, so changing them
    mid-iteration produces meaningless results. Bind a cursor to its query at
    the layer that owns both, or require clients to restart pagination when the
    query changes.
    """
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise InvalidLimit(f"limit must be an int, got {type(limit).__name__}")
    if limit < 1:
        raise InvalidLimit(f"limit must be at least 1, got {limit}")
    if limit > MAX_LIMIT:
        raise InvalidLimit(f"limit must be at most {MAX_LIMIT}, got {limit}")
    if not isinstance(rows, list):
        raise TypeError(f"rows must be a list, got {type(rows).__name__}")

    after_key = _key(*_decode_cursor(cursor)) if cursor is not None else None

    # Only limit + 1 rows can matter: enough to fill the page, plus one to
    # answer "is there another page?" without counting the rest. Selecting them
    # costs O(n log limit) instead of sorting the whole set.
    window = heapq.nsmallest(limit + 1, _eligible(rows, after_key), key=_row_key)

    if len(window) > limit:
        items = window[:limit]
        return {"items": items, "next_cursor": _encode_cursor(items[-1])}
    return {"items": window, "next_cursor": None}
