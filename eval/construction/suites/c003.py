"""c003 -- warehouse merge step. Acceptance suite."""

EXISTING = [
    {"key": "a", "updated_at": 100, "value": "old-a"},
    {"key": "b", "updated_at": 200, "value": "old-b"},
]
BATCH = [
    {"key": "b", "updated_at": 300, "value": "new-b"},
    {"key": "c", "updated_at": 300, "value": "new-c"},
]

CHECKS = [
    {"id": "s_new_keys_are_added", "kind": "stated",
     "what": "A key only present in the batch appears in the result.",
     "why": "The brief asks for the new table contents."},
    {"id": "s_existing_keys_are_updated", "kind": "stated",
     "what": "A newer batch record replaces the existing one for that key.",
     "why": "The brief asks for the new table contents."},
    {"id": "s_returns_a_list_of_records", "kind": "stated",
     "what": "Returns a list of dicts, one per key, keys unique.",
     "why": "The brief gives the return type and says key is unique."},
    {"id": "s_empty_batch_changes_nothing", "kind": "stated",
     "what": "Merging an empty batch returns the existing contents.",
     "why": "Direct consequence of the stated contract."},

    {"id": "i_idempotent_on_replay", "kind": "implied",
     "what": "Applying the same batch twice gives the same table as once.",
     "why": "Every nightly loader gets replayed -- retried job, re-delivered "
            "file, backfill. A merge that is not idempotent corrupts the "
            "table the first time ops retries it, and no brief ever asks."},
    {"id": "i_dedup_within_one_batch", "kind": "implied",
     "what": "A key appearing twice in one batch resolves to the later "
             "updated_at, and appears once.",
     "why": "Source files carry multiple events per key. Last-write-by-"
            "position rather than by updated_at silently depends on file "
            "order."},
    {"id": "i_late_arriving_does_not_overwrite", "kind": "implied",
     "what": "A batch record older than the existing row does not replace it.",
     "why": "The record carries updated_at, which has no purpose unless it "
            "arbitrates. Out-of-order delivery is normal and 'batch always "
            "wins' quietly reverts the table to stale values."},
    {"id": "i_does_not_mutate_its_inputs", "kind": "implied",
     "what": "`existing` and `batch` are unchanged after the call.",
     "why": "A loader that mutates its inputs cannot be safely retried, and "
            "the corruption surfaces one layer up where nobody is looking."},
]


def _by_key(rows):
    return {r["key"]: r for r in rows}


def check_s_new_keys_are_added(m):
    assert _by_key(m.merge(EXISTING, BATCH))["c"]["value"] == "new-c"


def check_s_existing_keys_are_updated(m):
    assert _by_key(m.merge(EXISTING, BATCH))["b"]["value"] == "new-b"


def check_s_returns_a_list_of_records(m):
    got = m.merge(EXISTING, BATCH)
    assert isinstance(got, list) and all(isinstance(r, dict) for r in got)
    keys = [r["key"] for r in got]
    assert sorted(keys) == ["a", "b", "c"], keys


def check_s_empty_batch_changes_nothing(m):
    assert _by_key(m.merge(EXISTING, [])) == _by_key(EXISTING)


def check_i_idempotent_on_replay(m):
    once = m.merge(EXISTING, BATCH)
    twice = m.merge([dict(r) for r in once], BATCH)
    assert _by_key(twice) == _by_key(once)


def check_i_dedup_within_one_batch(m):
    batch = [
        {"key": "d", "updated_at": 500, "value": "later"},
        {"key": "d", "updated_at": 400, "value": "earlier"},
    ]
    got = [r for r in m.merge(EXISTING, batch) if r["key"] == "d"]
    assert len(got) == 1, f"key d appeared {len(got)} times"
    assert got[0]["value"] == "later", got[0]


def check_i_late_arriving_does_not_overwrite(m):
    stale = [{"key": "b", "updated_at": 50, "value": "stale-b"}]
    assert _by_key(m.merge(EXISTING, stale))["b"]["value"] == "old-b"


def check_i_does_not_mutate_its_inputs(m):
    existing = [dict(r) for r in EXISTING]
    batch = [dict(r) for r in BATCH]
    m.merge(existing, batch)
    assert existing == EXISTING, f"existing became {existing}"
    assert batch == BATCH, f"batch became {batch}"
