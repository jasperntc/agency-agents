"""Mid-cycle plan change proration.

Computes the net amount to move when a subscription switches plans partway
through a billing period that the customer has already paid for.

Money model
-----------
Every amount is an integer in the currency's minor unit, and every amount in a
single call is the same currency. "cents" in the signature is shorthand: for a
zero-decimal currency such as JPY the minor unit is the yen itself. The
arithmetic here is exponent-agnostic precisely because it never leaves whole
minor units -- there is no float anywhere in this module, and no intermediate
value is ever a fraction of a minor unit.

Period model
------------
The billing period is half-open: ``[period_start, period_end)``. ``period_end``
is the instant the *next* period begins, which is what Stripe, Adyen and
friends report as ``current_period_end``. If your subscription rows instead
store an inclusive last day, pass ``last_day + timedelta(days=1)``.

Dates, not timestamps
---------------------
Proration is computed in whole days. Resolve the change instant to a calendar
date in the *billing* timezone before calling. Doing that conversion in UTC
puts a late-evening change on the wrong calendar day for customers west of it,
which is a one-day pricing error rather than a display quirk. Passing a
``datetime`` is rejected rather than silently truncated, for the same reason.

Rounding
--------
The whole-period price difference is prorated once, in a single
round-half-to-even step, rather than rounding an old-plan credit and a new-plan
charge separately and subtracting them. One rounding instead of two halves the
worst-case error and makes the result exactly antisymmetric: switching A -> B
and then B -> A at the same moment nets to zero, so a mistaken plan change that
is immediately undone cannot leak a minor unit in either direction. Ties go to
even so the sub-unit residue does not accumulate in the merchant's favour
across a large book of subscriptions; it reconciles to zero drift over time,
which round-half-up does not.

Be aware that a processor which issues proration as two invoice line items -- a
credit for unused time on the old plan and a charge for the remaining time on
the new one -- can land one minor unit away from this function on the same
inputs, because it rounds twice. When reconciling, compare against the *sum* of
the invoice's proration lines and allow a one-minor-unit tolerance; better
still, treat the processor's invoice as truth for what is owed, and use this
function to quote the change and to assert the sign and magnitude before
committing it.

Operational notes
-----------------
This is a pure calculation. It decides *how much*, never *whether* or *how many
times*. The caller still owes the two things that keep a plan change from
moving money twice:

* An idempotency key derived from the business operation -- subscription id
  plus the plan-change id, not a fresh UUID per HTTP attempt -- on whatever
  mutation carries this amount to the processor. A double-clicked upgrade and a
  retried request must resolve to one charge.
* A recorded decision, per plan change, about where a negative result goes:
  refunded to the original payment method, held as customer credit balance, or
  applied as a line item on the next invoice. Those three are not
  interchangeable, and the difference is visible to both the customer and the
  ledger.
"""

import datetime

__all__ = ["proration"]


def _validate_amount(value: int, name: str) -> None:
    """Reject anything that is not a whole, non-negative count of minor units."""
    # bool is a subclass of int; a flag must never be mistaken for a price.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            "{0} must be an int number of minor units, got {1!r} ({2}). "
            "Money is never a float.".format(name, value, type(value).__name__)
        )
    if value < 0:
        raise ValueError(
            "{0} must be non-negative, got {1}. A negative plan price would "
            "invert the direction of the resulting money movement.".format(
                name, value
            )
        )


def _validate_date(value: datetime.date, name: str) -> None:
    """Require a plain ``date``; a ``datetime`` is a caller bug, not a coercion."""
    # datetime subclasses date, so it must be excluded before the date check.
    if isinstance(value, datetime.datetime):
        raise TypeError(
            "{0} must be a datetime.date, got a datetime. Convert it in the "
            "billing timezone first -- silently dropping the time component "
            "can shift the change onto the wrong day.".format(name)
        )
    if not isinstance(value, datetime.date):
        raise TypeError(
            "{0} must be a datetime.date, got {1!r} ({2}).".format(
                name, value, type(value).__name__
            )
        )


def _divide_round_half_even(numerator: int, denominator: int) -> int:
    """Divide ``numerator`` by a positive ``denominator``, nearest, ties to even.

    Symmetric about zero, so ``_divide_round_half_even(-n, d)`` equals
    ``-_divide_round_half_even(n, d)``. Uses only integer arithmetic: exact at
    any magnitude, with no float and no dependence on decimal context state.
    """
    # Python's divmod floors, so 0 <= remainder < denominator for any numerator.
    quotient, remainder = divmod(numerator, denominator)
    doubled = 2 * remainder
    if doubled > denominator:
        quotient += 1
    elif doubled == denominator and quotient % 2 != 0:
        quotient += 1
    return quotient


def proration(
    old_cents: int,
    new_cents: int,
    period_start: datetime.date,
    period_end: datetime.date,
    change_at: datetime.date,
) -> int:
    """Net minor units to move for a mid-cycle plan change.

    The customer has paid ``old_cents`` for the whole period. From ``change_at``
    onward they are on a plan worth ``new_cents`` for the whole period, so the
    amount at stake is the price difference scaled by the unused fraction of the
    period.

    Args:
        old_cents: Whole-period price of the plan being left, in minor units.
        new_cents: Whole-period price of the plan being joined, in minor units,
            in the same currency as ``old_cents``.
        period_start: First day of the current billing period.
        period_end: Start of the *next* billing period. The period is
            half-open, so this day is not billed by it.
        change_at: Day the new plan takes effect, in the billing timezone. Must
            fall within ``[period_start, period_end]``.

    Returns:
        A signed integer in the same minor units. Positive means charge the
        customer now, negative means credit them, zero means nothing moves.

    Raises:
        TypeError: An amount is not an ``int``, or a date is not a plain
            ``datetime.date``.
        ValueError: An amount is negative, the period is empty or inverted, or
            ``change_at`` falls outside the period.

    Invariants worth relying on:
        * ``change_at == period_start`` returns exactly
          ``new_cents - old_cents`` -- the full difference between the two plan
          prices, with no rounding applied.
        * ``change_at == period_end`` returns ``0``. The change lands on the
          renewal boundary, so the new price is simply what the next period
          bills; there is no unused time to settle.
        * ``old_cents == new_cents`` returns ``0`` for any ``change_at``.
        * The result is antisymmetric in the two prices: swapping them negates
          the result exactly.

    Example:
        A 31-day period running 1 Jan to 1 Feb, upgrading from $10.00 to $30.00
        on 16 Jan, leaves 16 unused days, so 16/31 of the $20.00 difference is
        charged now::

            >>> import datetime
            >>> proration(1000, 3000, datetime.date(2026, 1, 1),
            ...           datetime.date(2026, 2, 1), datetime.date(2026, 1, 16))
            1032
    """
    _validate_amount(old_cents, "old_cents")
    _validate_amount(new_cents, "new_cents")
    _validate_date(period_start, "period_start")
    _validate_date(period_end, "period_end")
    _validate_date(change_at, "change_at")

    period_days = (period_end - period_start).days
    if period_days <= 0:
        raise ValueError(
            "period_end ({0}) must be strictly after period_start ({1}); the "
            "billing period is half-open and cannot be empty.".format(
                period_end.isoformat(), period_start.isoformat()
            )
        )

    # Out of range is a caller bug -- the wrong period was loaded, or a timezone
    # slipped a day. Clamping would hide that behind a plausible-looking
    # invoice, so refuse to price it at all.
    if not period_start <= change_at <= period_end:
        raise ValueError(
            "change_at ({0}) falls outside the billing period [{1}, {2}]; "
            "refusing to prorate against a period the change does not belong "
            "to.".format(
                change_at.isoformat(),
                period_start.isoformat(),
                period_end.isoformat(),
            )
        )

    # Unused whole days remaining, counted to the half-open period end. Equals
    # period_days at period_start, and 0 at period_end.
    remaining_days = (period_end - change_at).days

    # Prorate the difference itself: one rounding, exactly antisymmetric, and
    # exact (remainder 0) whenever remaining_days == period_days.
    difference = new_cents - old_cents
    return _divide_round_half_even(difference * remaining_days, period_days)
