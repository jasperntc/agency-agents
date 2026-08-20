"""Mid-cycle plan-change proration.

A customer on a monthly (or any fixed-length) billing period switches plans
partway through. `old_cents` and `new_cents` are the *whole-period* prices
of the old and new plans -- not daily rates. We prorate by the fraction of
the period that remains at the moment of the switch, on the theory that the
customer has already "consumed" the portion of the old plan up to
`change_at` and should be charged (or credited) only for the remainder.

    remaining_fraction = (period_end - change_at) / (period_end - period_start)
    delta_cents        = (new_cents - old_cents) * remaining_fraction

A switch at `period_start` has remaining_fraction == 1, so the customer
sees the full price difference, as required. A switch exactly at
`period_end` has remaining_fraction == 0 -- there is no time left to
prorate, so no charge or credit is generated.

All money is handled as integer cents. The exact remaining-fraction
multiplication is done with `fractions.Fraction` so no floating-point
error creeps into the arithmetic, and the final result is rounded to the
nearest cent with banker's rounding (Python's default `round` behavior on
a `Fraction`), which avoids a systematic bias toward over- or
under-charging across many prorations.
"""

from __future__ import annotations

from datetime import date
from fractions import Fraction


def proration(
    old_cents: int,
    new_cents: int,
    period_start: date,
    period_end: date,
    change_at: date,
) -> int:
    """Return the cents to charge (positive) or credit (negative) for a
    mid-cycle plan change.

    Args:
        old_cents: Whole-period price of the plan being switched away from,
            in integer cents. Must be >= 0.
        new_cents: Whole-period price of the plan being switched to, in
            integer cents. Must be >= 0.
        period_start: First day of the current billing period.
        period_end: Last day of the current billing period. Must be after
            `period_start`.
        change_at: Date the plan change takes effect. Must fall within
            [period_start, period_end].

    Returns:
        An integer number of cents. Positive means charge the customer now;
        negative means credit them. Zero means no money moves.

    Raises:
        ValueError: If `old_cents` or `new_cents` is negative, if
            `period_end` is not strictly after `period_start`, or if
            `change_at` falls outside [period_start, period_end].
    """
    if old_cents < 0:
        raise ValueError(f"old_cents must be >= 0, got {old_cents}")
    if new_cents < 0:
        raise ValueError(f"new_cents must be >= 0, got {new_cents}")
    if period_end <= period_start:
        raise ValueError(
            f"period_end ({period_end}) must be after period_start ({period_start})"
        )
    if not (period_start <= change_at <= period_end):
        raise ValueError(
            f"change_at ({change_at}) must fall within "
            f"period_start ({period_start}) and period_end ({period_end})"
        )

    total_days = (period_end - period_start).days
    remaining_days = (period_end - change_at).days

    price_delta = new_cents - old_cents
    remaining_amount = Fraction(price_delta * remaining_days, total_days)

    return round(remaining_amount)
