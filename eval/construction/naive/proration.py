"""Naive first draft for c001. Calibration only -- never shown to an answerer.

Reads the brief, implements exactly what it says, thinks about nothing else.
"""
import math
from datetime import date


def proration(old_cents: int, new_cents: int, period_start: date,
              period_end: date, change_at: date) -> int:
    total_days = (period_end - period_start).days
    remaining_days = (period_end - change_at).days
    fraction = remaining_days / total_days
    return math.floor((new_cents - old_cents) * fraction)
