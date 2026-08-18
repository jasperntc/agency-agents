"""Naive first draft for c002. Calibration only -- never shown to an answerer.

Offset paging. Satisfies every stated requirement.
"""


def page(rows: list[dict], cursor: str | None, limit: int) -> dict:
    ordered = sorted(rows, key=lambda r: r["created_at"], reverse=True)
    start = int(cursor) if cursor else 0
    items = ordered[start:start + limit]
    next_cursor = str(start + limit) if start + limit < len(ordered) else None
    return {"items": items, "next_cursor": next_cursor}
