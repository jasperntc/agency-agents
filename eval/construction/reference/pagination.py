"""Reference implementation for c002. Not shown to any answerer."""


def _sort_key(row):
    # Newest first, then id ascending. The id is not decoration: without a
    # unique tie-break the cursor cannot address a position inside a block of
    # rows sharing a timestamp.
    return (-row["created_at"], row["id"])


def page(rows: list[dict], cursor: str | None, limit: int) -> dict:
    if limit <= 0:
        raise ValueError("limit must be positive")

    ordered = sorted(rows, key=_sort_key)

    if cursor is not None:
        created_at, _, row_id = cursor.partition("|")
        after = (-int(created_at), row_id)
        ordered = [r for r in ordered if _sort_key(r) > after]

    items = ordered[:limit]
    more = len(ordered) > limit
    next_cursor = None
    if more and items:
        last = items[-1]
        next_cursor = f"{last['created_at']}|{last['id']}"

    return {"items": items, "next_cursor": next_cursor}
