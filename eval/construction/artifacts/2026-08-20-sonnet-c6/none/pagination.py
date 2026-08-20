"""Pagination helper for the public API.

Rows are dicts with a unique string ``id`` and an integer epoch-second
``created_at``. Results are always returned newest first. Because
``rows`` is handed in as the full result set in arbitrary order on
every call, the cursor must be self-contained: it encodes the sort
key of the last item returned so the next call can locate that same
position after re-sorting, regardless of the order ``rows`` arrives
in or whether rows have been added/removed between calls.
"""

from __future__ import annotations

import base64
import json

__all__ = ["page"]

_SEP_ENCODING = "utf-8"


def _sort_key(row: dict) -> tuple:
    # Newest first; ``id`` breaks ties so the ordering (and therefore
    # pagination) is fully deterministic even when multiple rows share
    # the same created_at second.
    return (-row["created_at"], row["id"])


def _encode_cursor(row: dict) -> str:
    payload = json.dumps(
        {"created_at": row["created_at"], "id": row["id"]},
        separators=(",", ":"),
    ).encode(_SEP_ENCODING)
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decode_cursor(cursor: str) -> tuple:
    try:
        payload = base64.urlsafe_b64decode(cursor.encode("ascii"))
        data = json.loads(payload.decode(_SEP_ENCODING))
        return (-int(data["created_at"]), str(data["id"]))
    except Exception as exc:
        raise ValueError("invalid cursor") from exc


def page(rows: list[dict], cursor: str | None, limit: int) -> dict:
    """Return one page of ``rows``, newest first.

    Args:
        rows: The full result set, in arbitrary order.
        cursor: ``None`` for the first page, otherwise a value
            previously returned by this function as ``next_cursor``.
        limit: The maximum number of items to return.

    Returns:
        A dict with ``items`` (at most ``limit`` rows, newest first)
        and ``next_cursor`` (``None`` when there are no more rows).
    """
    if limit <= 0:
        return {"items": [], "next_cursor": None}

    ordered = sorted(rows, key=_sort_key)

    start = 0
    if cursor is not None:
        after_key = _decode_cursor(cursor)
        lo, hi = 0, len(ordered)
        while lo < hi:
            mid = (lo + hi) // 2
            if _sort_key(ordered[mid]) <= after_key:
                lo = mid + 1
            else:
                hi = mid
        start = lo

    selected = ordered[start : start + limit]

    next_cursor = None
    if start + limit < len(ordered) and selected:
        next_cursor = _encode_cursor(selected[-1])

    return {"items": selected, "next_cursor": next_cursor}
