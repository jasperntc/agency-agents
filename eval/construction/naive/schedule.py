"""Naive first draft for c007. Calibration only -- never shown to an answerer.

Walks forward from the PREVIOUS renewal, clamping to the length of each
month. Satisfies every stated requirement. Drifts the anchor permanently at
the first short month.
"""
from calendar import monthrange
from datetime import date


def renewals(start: date, count: int, every_months: int = 1) -> list[date]:
    out = []
    cur = start
    for _ in range(count):
        total = (cur.year * 12 + cur.month - 1) + every_months
        year, month = divmod(total, 12)
        month += 1
        cur = date(year, month, min(cur.day, monthrange(year, month)[1]))
        out.append(cur)
    return out
