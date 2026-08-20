"""c002 -- keyset pagination for a public API. Acceptance suite."""

# Why this task is in the set. It names the discriminator, so it lives
# HERE -- with the answer key, which is withheld while answers are being
# collected -- and never in tasks.jsonl, which any answerer can read.
WHY_THIS_TASK = (
    'Offset paging satisfies every stated requirement and breaks the '
    'moment a row is inserted. That distinction is the entire '
    'specialism and the brief cannot hint at it without giving the '
    'answer.'
)

ROWS = [{"id": f"r{i:02d}", "created_at": 1000 + i} for i in range(10)]
# Six rows sharing one timestamp, which is what a bulk import looks like.
TIED = ([{"id": f"t{i}", "created_at": 500} for i in range(6)]
        + [{"id": "late", "created_at": 900}, {"id": "early", "created_at": 100}])

CHECKS = [
    {"id": "s_returns_items_and_cursor", "kind": "stated",
     "what": "Returns a dict carrying 'items' and 'next_cursor'.",
     "why": "The brief gives the return shape literally."},
    {"id": "s_respects_limit", "kind": "stated",
     "what": "A page never contains more than `limit` items.",
     "why": "The brief says 'at most limit items'."},
    {"id": "s_first_page_is_newest", "kind": "stated",
     "what": "cursor=None starts at the newest row.",
     "why": "The brief says None is the first page and rows come newest "
            "first."},
    {"id": "s_last_page_cursor_is_none", "kind": "stated",
     "what": "The final page reports next_cursor None.",
     "why": "The brief says next_cursor is None on the last page."},

    {"id": "i_full_walk_returns_each_row_once", "kind": "implied",
     "what": "Walking every page yields all rows, none missing, none twice.",
     "why": "This is what pagination IS. It is never written in a brief and "
            "it is the first thing a platform engineer would assert."},
    {"id": "i_ties_do_not_break_the_walk", "kind": "implied",
     "what": "Rows sharing an identical created_at still each appear once.",
     "why": "A cursor keyed on the timestamp alone cannot separate a tie, so "
            "it either loops forever or skips the whole tied block. Needs a "
            "unique tie-break, and nothing in the brief hints at it."},
    {"id": "i_stable_when_a_newer_row_arrives", "kind": "implied",
     "what": "A row inserted at the head between pages does not shift, "
             "duplicate, or skip the rows still to come.",
     "why": "THE reason keyset pagination exists. Offset paging passes every "
            "other check here and fails this one, which is exactly the bug "
            "that reaches production because a static fixture never shows it."},
    {"id": "i_limit_is_bounded_safely", "kind": "implied",
     "what": "An oversized limit returns everything and terminates; limit=0 "
             "refuses rather than serving an endless empty page.",
     "why": "A zero limit that returns no items and a non-None cursor is an "
            "infinite client loop, and it is reachable from any caller."},
]


def _walk(m, rows, limit, cap=50):
    """Every page, in order, with a hard stop so a broken cursor cannot hang."""
    out, cursor, pages = [], None, 0
    while True:
        got = m.page(rows, cursor, limit)
        out.extend(got["items"])
        cursor = got["next_cursor"]
        pages += 1
        if cursor is None:
            return out
        assert pages < cap, "next_cursor never reached None"
        assert got["items"], "a non-final page returned no items"


def check_s_returns_items_and_cursor(m):
    got = m.page(ROWS, None, 3)
    assert isinstance(got, dict) and "items" in got and "next_cursor" in got


def check_s_respects_limit(m):
    for limit in (1, 3, 7):
        assert len(m.page(ROWS, None, limit)["items"]) <= limit


def check_s_first_page_is_newest(m):
    items = m.page(ROWS, None, 3)["items"]
    assert [r["id"] for r in items] == ["r09", "r08", "r07"]


def check_s_last_page_cursor_is_none(m):
    assert m.page(ROWS, None, 100)["next_cursor"] is None


def check_i_full_walk_returns_each_row_once(m):
    for limit in (1, 3, 4):
        seen = [r["id"] for r in _walk(m, ROWS, limit)]
        assert sorted(seen) == sorted(r["id"] for r in ROWS), \
            f"limit={limit}: {seen}"


def check_i_ties_do_not_break_the_walk(m):
    seen = [r["id"] for r in _walk(m, TIED, 2)]
    assert sorted(seen) == sorted(r["id"] for r in TIED), seen


def check_i_stable_when_a_newer_row_arrives(m):
    first = m.page(ROWS, None, 3)
    assert first["next_cursor"] is not None
    grown = [{"id": "brand_new", "created_at": 9999}] + list(ROWS)

    rest, cursor, pages = [], first["next_cursor"], 0
    while cursor is not None and pages < 50:
        got = m.page(grown, cursor, 3)
        rest.extend(r["id"] for r in got["items"])
        cursor, pages = got["next_cursor"], pages + 1

    already = [r["id"] for r in first["items"]]
    assert not set(rest) & set(already), \
        f"re-served {sorted(set(rest) & set(already))} after an insert"
    assert sorted(rest) == sorted(r["id"] for r in ROWS if r["id"] not in already), \
        f"page 2+ became {sorted(rest)}"


def check_i_limit_is_bounded_safely(m):
    # Clamping an oversized limit and refusing it are BOTH right, and the first
    # draft of this check silently required clamping. The property is that no
    # limit value leaves a client looping, so refusal counts and the walk is
    # what gets asserted.
    try:
        big = m.page(ROWS, None, 10 ** 6)
    except Exception:
        pass
    else:
        assert len(big["items"]) == len(ROWS) and big["next_cursor"] is None

    try:
        zero = m.page(ROWS, None, 0)
    except Exception:
        # ANY exception counts as a refusal -- a module raising its own
        # InvalidLimitError is doing the right thing, and demanding ValueError
        # would score the exception hierarchy rather than the behaviour.
        return
    assert zero["next_cursor"] is None or zero["items"], \
        "limit=0 served an empty page with a cursor: an infinite client loop"
