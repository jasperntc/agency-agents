"""Cursor-based pagination for the public API.

Rows are paginated newest-first by ``created_at``. Because ``created_at``
has one-second resolution, two rows can share a value; ties are broken by
``id`` so that the sort order used to build any given page is total and
reproducible across calls. Without that tiebreak, a page boundary drawn
inside a tied group would be arbitrary and a cursor built from it could
skip or repeat rows on the next call.

The cursor returned to the caller is an opaque, base64url-encoded token
carrying the ``(created_at, id)`` of the last row on the page it closed.
Callers must treat it as opaque: obtain it only from this function's own
``next_cursor`` and pass it back unmodified. The encoding is an
implementation detail, not part of the API contract, and may change
between releases without notice.
"""

from __future__ import annotations

import base64
import bisect
import json

__all__ = ["page"]


def _sort_key(row: dict) -> tuple[int, str]:
    # Newest first: created_at descending, id ascending to break ties.
    return (-row["created_at"], row["id"])


def _encode_cursor(created_at: int, id_: str) -> str:
    payload = json.dumps(
        {"created_at": created_at, "id": id_}, separators=(",", ":")
    )
    token = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    return token.rstrip("=")


def _decode_cursor(cursor: str) -> tuple[int, str]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        data = json.loads(payload)
        created_at = data["created_at"]
        id_ = data["id"]
    except Exception as exc:
        raise ValueError(f"invalid cursor: {cursor!r}") from exc

    if not isinstance(created_at, int) or isinstance(created_at, bool):
        raise ValueError(f"invalid cursor: {cursor!r}")
    if not isinstance(id_, str):
        raise ValueError(f"invalid cursor: {cursor!r}")

    return created_at, id_


def page(rows: list[dict], cursor: str | None, limit: int) -> dict:
    """Return one page of ``rows``, newest first.

    Args:
        rows: The full result set, in arbitrary order. Each row must have
            a unique string ``id`` and an integer epoch-second
            ``created_at``.
        cursor: ``None`` to fetch the first page; otherwise a value
            previously returned as ``next_cursor`` from this function.
        limit: Maximum number of items to return. Must be a positive
            integer.

    Returns:
        A dict with:
            - ``items``: up to ``limit`` rows, ordered newest first.
            - ``next_cursor``: an opaque string to pass back for the next
              page, or ``None`` if this page reaches the end of the
              result set.

    Raises:
        ValueError: if ``limit`` is not a positive integer, or ``cursor``
            is not ``None`` and cannot be decoded as a value this
            function produced.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError(f"limit must be a positive integer, got {limit!r}")

    ordered = sorted(rows, key=_sort_key)
    keys = [_sort_key(row) for row in ordered]

    if cursor is None:
        start = 0
    else:
        boundary_created_at, boundary_id = _decode_cursor(cursor)
        boundary_key = (-boundary_created_at, boundary_id)
        # First row strictly newer-ordered than the one the cursor closed on.
        start = bisect.bisect_right(keys, boundary_key)

    end = start + limit
    items = ordered[start:end]

    if end < len(ordered):
        last = items[-1]
        next_cursor = _encode_cursor(last["created_at"], last["id"])
    else:
        next_cursor = None

    return {"items": items, "next_cursor": next_cursor}
