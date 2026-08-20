"""Reference implementation for c007. Never shown to an answerer.

Exists so that --self-test can prove every check in the suite is satisfiable
by a competent implementation. A check a competent implementation fails is a
broken check, and this is the only way to learn that before the run.

The whole task is one invariant: the anchor is `start.day` and it is never
written back. Each renewal is computed from `start` and an index, not from
its predecessor, which is what makes drift structurally impossible rather
than merely tested for.
"""
from calendar import monthrange
from datetime import date

__all__ = ["renewals"]


def _shift(start: date, months: int) -> date:
    total = (start.year * 12 + start.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    # The anchor is clamped to fit the target month, never mutated. Feb takes
    # the 28th (or 29th); the month after takes the original day back.
    return date(year, month, min(start.day, monthrange(year, month)[1]))


def renewals(start: date, count: int, every_months: int = 1) -> list[date]:
    """Return the next `count` renewal dates after `start`."""
    if count < 0:
        raise ValueError("count must not be negative")
    if every_months < 1:
        raise ValueError("every_months must be at least 1")
    return [_shift(start, every_months * i) for i in range(1, count + 1)]
