"""Cursor-based pagination for the public API.

Rows are ordered newest-first by ``created_at``, with ``id`` as a secondary,
deterministic tiebreaker for rows that share a ``created_at`` value (so the
ordering — and therefore pagination — is stable even when many rows land in
the same second). The cursor returned by :func:`page` is an opaque, base64
encoded token; callers must treat it as a black box and pass it back
unmodified to fetch the next page. It intentionally encodes the last
returned row's sort position rather than an offset, so pagination stays
correct even if rows are inserted or deleted between requests.
"""

from __future__ import annotations

import base64
import binascii
import bisect
import json

_CURSOR_ENCODING = "ascii"


def _sort_key(row: dict) -> tuple[int, str]:
    """Sort key producing newest-first order, tiebroken by id."""
    return (-row["created_at"], row["id"])


def _encode_cursor(created_at: int, id_: str) -> str:
    payload = json.dumps([created_at, id_], separators=(",", ":"))
    token = base64.urlsafe_b64encode(payload.encode("utf-8"))
    return token.decode(_CURSOR_ENCODING)


def _decode_cursor(cursor: str) -> tuple[int, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode(_CURSOR_ENCODING))
        decoded = json.loads(raw.decode("utf-8"))
        created_at, id_ = decoded
        if not isinstance(created_at, int) or not isinstance(id_, str):
            raise ValueError
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ) as exc:
        raise ValueError(f"invalid cursor: {cursor!r}") from exc
    return created_at, id_


def page(rows: list[dict], cursor: str | None, limit: int) -> dict:
    """Return one page of ``rows``, newest first.

    Args:
        rows: The full result set, in arbitrary order. Each row must have
            a unique string ``id`` and an integer epoch-second
            ``created_at``.
        cursor: ``None`` to fetch the first page, otherwise a value
            previously returned by this function as ``next_cursor``.
        limit: Maximum number of items to return. Must be positive.

    Returns:
        A dict with:
            - ``items``: up to ``limit`` rows, newest first.
            - ``next_cursor``: an opaque cursor for the following page,
              or ``None`` if this is the last page.

    Raises:
        ValueError: if ``limit`` is not positive, or ``cursor`` is not a
            value this function produced.
    """
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit!r}")

    ordered = sorted(rows, key=_sort_key)
    keys = [_sort_key(row) for row in ordered]

    if cursor is None:
        start = 0
    else:
        after_created_at, after_id = _decode_cursor(cursor)
        start = bisect.bisect_right(keys, (-after_created_at, after_id))

    items = ordered[start : start + limit]

    next_cursor = None
    if start + limit < len(ordered):
        last = items[-1]
        next_cursor = _encode_cursor(last["created_at"], last["id"])

    return {"items": items, "next_cursor": next_cursor}
