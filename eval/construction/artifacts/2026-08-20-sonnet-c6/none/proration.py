"""Mid-cycle subscription plan-change proration.

Computes the cents owed (positive) or credited (negative) when a customer
switches from one plan price to another partway through a billing period.

The billing period runs from ``period_start`` (inclusive) up to
``period_end`` (treated as the exclusive start of the next period, which is
the usual convention for billing-cycle boundaries). The customer is deemed
to have consumed the old plan from ``period_start`` up to ``change_at``, and
the new plan from ``change_at`` through the remainder of the period.

The proration amount is simply the price difference between the two plans,
scaled by the fraction of the period remaining at the moment of the switch:

    proration = (new_cents - old_cents) * days_remaining / days_total

so a change made at the very start of the period (days_remaining ==
days_total) yields the full price difference, and a change made at the very
end of the period yields (approximately) nothing.

All arithmetic is done with exact rational numbers (``fractions.Fraction``)
to avoid floating-point drift, and the final result is rounded to the
nearest whole cent, with ties rounding away from zero.
"""

from __future__ import annotations

from datetime import date
from fractions import Fraction


def _round_half_away_from_zero(value: Fraction) -> int:
    """Round a Fraction to the nearest int, ties rounding away from zero."""
    if value >= 0:
        return int((value + Fraction(1, 2)).__floor__())
    return -int((-value + Fraction(1, 2)).__floor__())


def proration(
    old_cents: int,
    new_cents: int,
    period_start: date,
    period_end: date,
    change_at: date,
) -> int:
    """Compute the cents to charge (positive) or credit (negative) for a
    mid-cycle plan change.

    Args:
        old_cents: Full-period price of the plan being switched away from.
        new_cents: Full-period price of the plan being switched to.
        period_start: First day of the billing period (inclusive).
        period_end: Day the billing period ends (treated as the exclusive
            boundary, i.e. the first day of the *next* period).
        change_at: Date the plan change takes effect.

    Returns:
        Signed integer number of cents: positive means charge the customer,
        negative means credit them. A change effective at ``period_start``
        returns the full ``new_cents - old_cents`` difference.

    Raises:
        ValueError: If ``period_end`` is not after ``period_start``.
    """
    total_days = (period_end - period_start).days
    if total_days <= 0:
        raise ValueError("period_end must be after period_start")

    # Clamp change_at into the period so out-of-range switch dates degrade
    # gracefully instead of over/under-shooting the proration.
    if change_at <= period_start:
        days_remaining = total_days
    elif change_at >= period_end:
        days_remaining = 0
    else:
        days_remaining = (period_end - change_at).days

    price_diff = new_cents - old_cents
    prorated = Fraction(price_diff * days_remaining, total_days)

    return _round_half_away_from_zero(prorated)
