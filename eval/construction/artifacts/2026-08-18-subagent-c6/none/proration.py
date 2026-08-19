#!/usr/bin/env python3
"""proration.py -- mid-cycle plan change adjustments for subscription billing.

    from datetime import date
    from proration import proration

    proration(1000, 3000, date(2026, 1, 1), date(2026, 2, 1), date(2026, 1, 16))
    # -> 1032   (charge the customer $10.32 now)

WHAT THE RETURNED NUMBER IS

    An ADJUSTMENT, not an invoice total. It assumes `old_cents` has already
    been billed for the whole period. The customer keeps the old plan for the
    elapsed part of the period and the new plan for the remainder, so the only
    money that moves is the price difference on the unused remainder:

        (new_cents - old_cents) * remaining_days / total_days

    Positive means charge now, negative means credit. A switch on
    `period_start` leaves nothing elapsed, so the entire period reprices and
    the result is exactly `new_cents - old_cents`.

    If what you actually need is "what do we invoice for the rest of the period
    at the new price", that is a different figure and this is not it.

THE PERIOD IS HALF-OPEN: [period_start, period_end)

    `period_end` is the renewal date -- the first day of the NEXT period, not
    the last day of this one. January 2026 is therefore

        date(2026, 1, 1) .. date(2026, 2, 1)

    which is the correct 31 days. If the `period_end` you hold is instead the
    last billed day, pass `period_end + timedelta(days=1)`.

    Nothing here can detect which convention you meant, and the two differ by a
    day of revenue on every change, so it has to be right at the call site.

ROUNDING

    Every step is exact integer arithmetic -- no float, no Decimal. The single
    division rounds half away from zero.

    That rule is an odd function, which buys a property worth having:

        proration(a, b, s, e, c) == -proration(b, a, s, e, c)

    An upgrade reversed the same day nets to exactly zero instead of leaking a
    cent. The obvious one-liner -- `delta * remaining // total` -- does not have
    this property, because `//` floors rather than rounding: on the example
    above it returns 1032 for the upgrade but -1033 for the mirrored downgrade,
    biasing every rounded case toward the customer and leaving a cent behind on
    each reversal.

DAY GRANULARITY

    Proration is computed in whole days. `datetime` instances are accepted and
    their time-of-day is discarded, so a change at 23:59 prorates exactly like
    one at 00:01 on the same date. Sub-day proration is a different function.
"""

from datetime import date, datetime

__all__ = ["proration"]


def _as_date(value: object, name: str) -> date:
    """Coerce a date-like argument to a plain `date`, or raise TypeError.

    `datetime` is checked first because it is a subclass of `date`. Coercing
    rather than rejecting it also avoids a confusing failure mode: subtracting
    a `date` from a `datetime` raises TypeError deep inside the calculation,
    so a caller who mixes the two types would otherwise get an error that
    names neither argument.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(
        "{} must be a datetime.date, got {}".format(name, type(value).__name__)
    )


def _as_cents(value: object, name: str) -> int:
    """Coerce a money argument to `int`, or raise TypeError.

    `bool` is rejected even though it is a subclass of `int`: a price of `True`
    is a caller bug every time, never a one-cent plan. Floats are rejected
    because they are the usual way fractional cents enter a billing system.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            "{} must be an int number of cents, got {}".format(
                name, type(value).__name__
            )
        )
    return value


def _divide_round_half_away_from_zero(numerator: int, denominator: int) -> int:
    """Exact integer division rounding halves away from zero.

    `denominator` must be positive; the caller guarantees it.
    """
    sign = -1 if numerator < 0 else 1
    quotient, remainder = divmod(abs(numerator), denominator)
    if 2 * remainder >= denominator:
        quotient += 1
    return sign * quotient


def proration(
    old_cents: int,
    new_cents: int,
    period_start: date,
    period_end: date,
    change_at: date,
) -> int:
    """Return the cents to charge (positive) or credit (negative) for a plan change.

    Args:
        old_cents: Price of the outgoing plan for the whole billing period,
            assumed to have already been billed.
        new_cents: Price of the incoming plan for the whole billing period.
        period_start: First day of the billing period.
        period_end: Renewal date -- the day AFTER the last billed day. See the
            module docstring; the interval is half-open.
        change_at: Day the new plan takes effect. The customer is charged the
            new rate for this day.

    Returns:
        The adjustment in whole cents. Positive charges the customer, negative
        credits them. `change_at == period_start` returns exactly
        `new_cents - old_cents`; `change_at == period_end` returns 0.

    Raises:
        TypeError: A price is not an `int`, or a date is not a `date`.
        ValueError: The period is empty or inverted, or `change_at` falls
            outside it. Out-of-period changes are refused rather than clamped,
            because a date outside the period being billed is a caller bug and
            silently clamping it would emit a plausible but wrong amount. Clamp
            deliberately at the call site if you have a reason to.
    """
    old_cents = _as_cents(old_cents, "old_cents")
    new_cents = _as_cents(new_cents, "new_cents")
    period_start = _as_date(period_start, "period_start")
    period_end = _as_date(period_end, "period_end")
    change_at = _as_date(change_at, "change_at")

    total_days = (period_end - period_start).days
    if total_days <= 0:
        raise ValueError(
            "period_end ({}) must be after period_start ({}); the interval is "
            "half-open, so a one-day period ends on the following day".format(
                period_end, period_start
            )
        )

    if not period_start <= change_at <= period_end:
        raise ValueError(
            "change_at ({}) is outside the billing period {} .. {}".format(
                change_at, period_start, period_end
            )
        )

    remaining_days = (period_end - change_at).days

    # Multiply before dividing: the product is exact, so the whole calculation
    # rounds exactly once, here.
    return _divide_round_half_away_from_zero(
        (new_cents - old_cents) * remaining_days, total_days
    )
