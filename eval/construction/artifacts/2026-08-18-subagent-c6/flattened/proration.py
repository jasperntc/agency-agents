"""Proration for mid-cycle subscription plan changes.

A customer on a plan costing ``old_cents`` for the current billing period
switches to a plan costing ``new_cents`` partway through it. They have already
been billed ``old_cents`` for the whole period, so what is owed now is the
difference between the two plans, restricted to the part of the period that has
not yet elapsed::

    amount = (new_cents - old_cents) * remaining_days / period_days

An upgrade (dearer new plan) yields a positive amount to charge; a downgrade
yields a negative amount to credit.

Conventions
-----------
Billing periods are half-open: ``period_start`` is inclusive, ``period_end`` is
exclusive. So 2026-01-01 -> 2026-02-01 is 31 days, not 32. This is what makes
consecutive periods chain cleanly -- one period's end is the next one's start,
and no day is billed twice.

Proration is at whole-day granularity, and the day of the change belongs to the
new plan.

The daily rate is derived from the period rather than fixed, so a monthly plan
prorates over 28-31 days depending on the month. That is deliberate: the plan
price buys the period, whatever its length.

Rounding
--------
Every step is exact integer arithmetic. No float and no Decimal is involved, so
there is no representation error at any magnitude. The single division rounds
halves away from zero, the usual commercial convention.

Rounding is applied once, to the net amount. Invoicing systems that emit two
line items -- a credit for the unused old plan and a charge for the new plan's
remainder -- round twice, and can therefore land a cent away from this figure.
If the caller needs those two numbers individually for an invoice, it needs a
different function: splitting this result will not reproduce them.

Guarantees
----------
* ``change_at == period_start`` returns exactly ``new_cents - old_cents``. The
  whole period is repriced and no rounding is applied.
* ``change_at == period_end`` returns 0. Nothing of the period is left to
  reprice; the new plan simply governs the next period.
* Swapping ``old_cents`` and ``new_cents`` negates the result exactly, for
  every input. An upgrade reversed the same day nets to zero rather than
  leaking a cent in either direction. This is the reason rounding is half away
  from zero rather than a floor division, which is asymmetric about zero and
  would bias every credit against the customer.
"""

from datetime import date, datetime

__all__ = ["proration"]


def proration(
    old_cents: int,
    new_cents: int,
    period_start: date,
    period_end: date,
    change_at: date,
) -> int:
    """Return the amount owed for a mid-cycle plan change, in whole cents.

    Args:
        old_cents: Price of the current plan for the whole billing period.
        new_cents: Price of the new plan for the whole billing period.
        period_start: First day of the billing period (inclusive).
        period_end: Day the billing period ends (exclusive).
        change_at: Day the new plan takes effect. Must fall within
            ``[period_start, period_end]``.

    Returns:
        Cents to settle now: positive to charge the customer, negative to
        credit them, zero if nothing is due.

    Raises:
        TypeError: If the prices are not ints, or the dates are not
            ``datetime.date`` instances.
        ValueError: If the prices are negative, if the period is empty or
            inverted, or if ``change_at`` falls outside the period.
    """
    _check_cents("old_cents", old_cents)
    _check_cents("new_cents", new_cents)
    _check_date("period_start", period_start)
    _check_date("period_end", period_end)
    _check_date("change_at", change_at)

    period_days = (period_end - period_start).days
    if period_days <= 0:
        raise ValueError(
            "period_end must be after period_start, but "
            f"{period_start} -> {period_end} spans {period_days} day(s)"
        )

    # An out-of-range change_at means the caller has matched a change event
    # against the wrong billing period. Clamping it into range would turn that
    # into a plausible-looking but wrong amount of money, so it is refused.
    if not period_start <= change_at <= period_end:
        raise ValueError(
            f"change_at ({change_at}) falls outside the billing period "
            f"[{period_start}, {period_end})"
        )

    remaining_days = (period_end - change_at).days
    return _divide_round_half_away((new_cents - old_cents) * remaining_days, period_days)


def _divide_round_half_away(numerator: int, denominator: int) -> int:
    """Divide exactly, rounding halves away from zero.

    ``denominator`` must be positive. The result is odd in ``numerator``
    (negating the input negates the output), which is what keeps a charge and
    its matching credit equal in size.
    """
    magnitude, remainder = divmod(abs(numerator), denominator)
    if 2 * remainder >= denominator:
        magnitude += 1
    return magnitude if numerator >= 0 else -magnitude


def _check_cents(name: str, value: int) -> None:
    # bool is a subclass of int; True would silently mean "one cent".
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{name} must be an int number of cents, got {type(value).__name__}"
        )
    if value < 0:
        raise ValueError(f"{name} must not be negative, got {value}")


def _check_date(name: str, value: date) -> None:
    # datetime is a subclass of date, so this check has to come first.
    if isinstance(value, datetime):
        raise TypeError(
            f"{name} must be a datetime.date, not a datetime.datetime. "
            "Narrowing a datetime here would mean choosing a timezone, and the "
            "wrong choice shifts the billing day by one; make that conversion "
            "at the call site, where the billing timezone is known."
        )
    if not isinstance(value, date):
        raise TypeError(
            f"{name} must be a datetime.date, got {type(value).__name__}"
        )
