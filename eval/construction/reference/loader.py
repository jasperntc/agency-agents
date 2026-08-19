"""Reference implementation for c003. Not shown to any answerer."""


def merge(existing: list[dict], batch: list[dict]) -> list[dict]:
    out = {r["key"]: dict(r) for r in existing}

    # Oldest first, so the newest event for a key is applied last and the
    # >= below lets it win. Resolving by position in the file instead would
    # make the result depend on how the source happened to order its rows.
    for record in sorted(batch, key=lambda r: r["updated_at"]):
        current = out.get(record["key"])
        if current is None or record["updated_at"] >= current["updated_at"]:
            out[record["key"]] = dict(record)

    return [out[key] for key in sorted(out)]
