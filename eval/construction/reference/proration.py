"""Reference implementation for c001. Not shown to any answerer.

It exists to prove the suite is satisfiable. A check that a competent
implementation fails is a broken check, and the only way to find that out
before the run is to write the competent implementation first.
"""
from datetime import date
from fractions import Fraction


def proration(old_cents: int, new_cents: int, period_start: date,
              period_end: date, change_at: date) -> int:
    if period_end <= period_start:
        raise ValueError("period_end must be after period_start")
    if not period_start <= change_at <= period_end:
        raise ValueError("change_at is outside the billing period")

    total = (period_end - period_start).days
    remaining = (period_end - change_at).days
    delta = new_cents - old_cents

    # Fraction, not float: money never touches binary floating point. round()
    # is half-to-even, which is symmetric about zero -- floor() and
    # round-half-up are not, and leak a cent on one side only.
    return round(Fraction(delta * remaining, total))
