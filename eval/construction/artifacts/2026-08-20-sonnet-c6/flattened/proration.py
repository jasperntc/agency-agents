"""Mid-cycle plan change proration for subscription billing.

Computes the net charge (or credit) owed when a subscriber switches plans
partway through an already-priced billing period.

The period is treated as a whole made of whole days: ``period_start`` and
``period_end`` are both inside the billed period (i.e. the period spans
``(period_end - period_start).days + 1`` calendar days), and a switch on
``change_at`` takes effect starting on that day. The customer is credited
the unused, remaining-day value of the old plan and charged the
remaining-day value of the new plan; the two are netted into one figure so
callers issue a single charge or a single credit rather than two entries.

All arithmetic is done in integer cents using exact integer division with
round-half-away-from-zero on ties, so results never depend on binary
floating-point rounding.
"""

from datetime import date

__all__ = ["proration"]


def _round_half_away_from_zero(numerator: int, denominator: int) -> int:
    """Divide two integers, rounding ties away from zero.

    ``denominator`` must be positive. Kept entirely in integer arithmetic
    (no floats, no Decimal) so the result is exact and reproducible.
    """
    if denominator <= 0:
        raise ValueError("denominator must be positive")

    negative = numerator < 0
    magnitude = -numerator if negative else numerator

    quotient, remainder = divmod(magnitude, denominator)
    if 2 * remainder >= denominator:
        quotient += 1

    return -quotient if negative else quotient


def proration(
    old_cents: int,
    new_cents: int,
    period_start: date,
    period_end: date,
    change_at: date,
) -> int:
    """Return the net cents owed for a mid-cycle plan change.

    ``old_cents`` and ``new_cents`` are the full-period prices, in cents,
    of the plan being left and the plan being switched to. ``period_start``
    and ``period_end`` are the first and last calendar day of the billing
    period (inclusive). ``change_at`` is the calendar day the new plan
    takes effect; it must fall within the period, inclusive of both ends.

    The result is positive when the customer owes an additional charge and
    negative when they are owed a credit. A switch on ``period_start``
    prices the entire remaining period at the new plan and credits the
    entire period at the old plan, so it returns exactly
    ``new_cents - old_cents``, matching a full-period plan swap.

    Raises:
        ValueError: if ``period_end`` precedes ``period_start``, if
            ``change_at`` falls outside ``[period_start, period_end]``, or
            if either price is negative.
    """
    if period_end < period_start:
        raise ValueError("period_end must not precede period_start")
    if change_at < period_start or change_at > period_end:
        raise ValueError("change_at must fall within [period_start, period_end]")
    if old_cents < 0 or new_cents < 0:
        raise ValueError("plan prices must not be negative")

    total_days = (period_end - period_start).days + 1
    remaining_days = (period_end - change_at).days + 1

    # Net price delta for the remaining portion of the period. Folding the
    # credit and the charge into one subtraction before rounding (rather
    # than rounding each leg separately) avoids a spurious off-by-one cent
    # from the two legs rounding in opposite directions.
    price_delta = new_cents - old_cents

    return _round_half_away_from_zero(price_delta * remaining_days, total_days)
