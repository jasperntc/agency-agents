"""c007 -- recurring renewal dates. Acceptance suite.

`stated` checks are requirements the brief spells out. They are the FLOOR: an
answer that fails one of these failed at reading, not at engineering, and if
the stated rate is not near ceiling in every condition then nothing the
`implied` rate says is worth reading.

`implied` checks are the ones a billing engineer meets without being told.

WHY THIS TASK EXISTS, WHICH IS DIFFERENT FROM WHY c001-c006 EXIST

c001-c006 all ceilinged. Both `claude-opus-5` and `claude-sonnet-5` cleared
24/24 implied checks with no agent file, so the axis measured nothing. The
diagnosis was that those tasks' implied requirements are all NAMED best
practices -- keyset pagination, idempotent replay, HMAC over a derived key --
and frontier models recall named best practices very well.

This task deliberately avoids that shape. There is no name to recall. The
requirement is calendar case analysis, where the plausible-looking
implementation is wrong in two distinct ways:

    DRIFT     compute each date from the PREVIOUS one, so Jan 31 -> Feb 28
              clamps the anchor to 28 and every later renewal is the 28th.
    STICKY    treat a start date that is the last day of its month as
              "end of month", so Apr 30 -> May 31.

Both are wrong, they are wrong in opposite directions, and neither has a
memorable name attached to it. The correct rule is a single invariant: the
anchor is `start.day`, forever, clamped per month and never written back.
"""

# Why this task is in the set. It names the discriminator, so it lives
# HERE -- with the answer key, which is withheld while answers are being
# collected -- and never in tasks.jsonl, which any answerer can read.
WHY_THIS_TASK = (
    'The anchor is start.day, kept forever and clamped per month, never '
    'written back. Computing each date from its predecessor drifts the '
    "anchor at the first short month; inferring 'end of month' from a "
    'start on the 30th sticks it to month ends. Both are wrong, in '
    'opposite directions, and neither has a name to recall -- which is '
    'the point, because every implied check in c001-c006 did have one, '
    'and both model tiers cleared all of them.'
)
from datetime import date

CHECKS = [
    {"id": "s_returns_count_dates", "kind": "stated",
     "what": "Returns exactly `count` dates.",
     "why": "The brief says 'the next count renewal dates'."},
    {"id": "s_simple_monthly_anniversary", "kind": "stated",
     "what": "A subscription started on the 15th renews on the 15th.",
     "why": "The brief states this outright, with that example."},
    {"id": "s_every_months_is_respected", "kind": "stated",
     "what": "every_months=3 steps a quarter at a time.",
     "why": "The brief defines the parameter as the interval in months."},
    {"id": "s_returns_date_objects", "kind": "stated",
     "what": "Every element is a datetime.date, in chronological order.",
     "why": "The brief says 'list[date]', 'in chronological order'."},

    {"id": "i_month_end_does_not_drift", "kind": "implied",
     "what": "Jan 31 renews Feb 28, then MAR 31 -- not Mar 28.",
     "why": "The anchor is the day the subscription started and it never "
            "moves. Computing each date from the previous one clamps the "
            "anchor permanently at the first short month, and the customer "
            "is billed three days early for the rest of their life. This is "
            "the single most common way a renewal schedule is wrong."},
    {"id": "i_last_day_is_not_sticky", "kind": "implied",
     "what": "Apr 30 renews May 30, not May 31.",
     "why": "Apr 30 is the last day of April, and an implementation that "
            "infers 'end of month' from that bills every 31-day month a day "
            "late. The brief pins the rule -- started on the Nth, renews on "
            "the Nth -- and 30 is an N like any other. The opposite error to "
            "drift, and it survives every test that only probes Jan 31."},
    {"id": "i_leap_anchor_survives", "kind": "implied",
     "what": "Feb 29 2024, yearly, renews Feb 28 for three years and then "
             "Feb 29 again in 2028.",
     "why": "The anchor is 29. Non-leap years clamp it; the leap year must "
            "get it back. Any implementation that stores the clamped value "
            "loses the 29th permanently, which is the same defect as drift "
            "but on a four-year period where nobody notices."},
    {"id": "i_steps_calendar_months_not_30_days", "kind": "implied",
     "what": "Twelve monthly renewals from Jan 1 land on the 1st of each "
             "month and reach Jan 1 of the next year.",
     "why": "timedelta(days=30) satisfies a surprising amount of a renewal "
            "spec and then slips a full month every year. A billing schedule "
            "is calendar arithmetic, never day arithmetic."},
]


def _months(seq):
    return [(d.year, d.month) for d in seq]


def check_s_returns_count_dates(m):
    for n in (1, 3, 12):
        got = m.renewals(date(2026, 1, 15), n)
        assert len(got) == n, f"count={n} returned {len(got)}"


def check_s_simple_monthly_anniversary(m):
    got = m.renewals(date(2026, 1, 15), 3)
    assert got == [date(2026, 2, 15), date(2026, 3, 15), date(2026, 4, 15)], got


def check_s_every_months_is_respected(m):
    got = m.renewals(date(2026, 1, 15), 2, 3)
    assert got == [date(2026, 4, 15), date(2026, 7, 15)], got


def check_s_returns_date_objects(m):
    got = m.renewals(date(2026, 1, 15), 4)
    for d in got:
        assert type(d) is date, f"returned {type(d).__name__}"
    assert got == sorted(got), f"not chronological: {got}"
    assert all(d > date(2026, 1, 15) for d in got), f"not after start: {got}"


def check_i_month_end_does_not_drift(m):
    got = m.renewals(date(2026, 1, 31), 4)
    assert got == [date(2026, 2, 28), date(2026, 3, 31),
                   date(2026, 4, 30), date(2026, 5, 31)], got


def check_i_last_day_is_not_sticky(m):
    got = m.renewals(date(2026, 4, 30), 3)
    assert got == [date(2026, 5, 30), date(2026, 6, 30),
                   date(2026, 7, 30)], got


def check_i_leap_anchor_survives(m):
    got = m.renewals(date(2024, 2, 29), 4, 12)
    assert got == [date(2025, 2, 28), date(2026, 2, 28),
                   date(2027, 2, 28), date(2028, 2, 29)], got


def check_i_steps_calendar_months_not_30_days(m):
    got = m.renewals(date(2026, 1, 1), 12)
    assert _months(got) == [(2026, mth) for mth in range(2, 13)] + [(2027, 1)], \
        f"months walked {_months(got)}"
    assert all(d.day == 1 for d in got), f"days walked {[d.day for d in got]}"
