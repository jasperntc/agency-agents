"""c001 -- mid-cycle proration. Acceptance suite.

`stated` checks are requirements the brief spells out. They are the FLOOR: an
answer that fails one of these failed at reading, not at engineering, and if
the stated rate is not near ceiling in every condition then nothing the
`implied` rate says is worth reading.

`implied` checks are the ones a billing engineer meets without being told. That
is the whole hypothesis of this phase.
"""

# Why this task is in the set. It names the discriminator, so it lives
# HERE -- with the answer key, which is withheld while answers are being
# collected -- and never in tasks.jsonl, which any answerer can read.
WHY_THIS_TASK = (
    'Money arithmetic has strong unwritten conventions -- symmetry of '
    'rounding, boundary handling, what to do with a date outside the '
    'period. None of it is in the brief.'
)
from datetime import date
from fractions import Fraction

JAN1, JAN16, JAN31 = date(2026, 1, 1), date(2026, 1, 16), date(2026, 1, 31)

CHECKS = [
    {"id": "s_full_period_full_difference", "kind": "stated",
     "what": "Switching at period_start charges the whole price difference.",
     "why": "The brief states this outright."},
    {"id": "s_upgrade_is_positive", "kind": "stated",
     "what": "A mid-period upgrade returns a positive number of cents.",
     "why": "The brief defines positive as 'charge the customer'."},
    {"id": "s_downgrade_is_negative", "kind": "stated",
     "what": "A mid-period downgrade returns a negative number of cents.",
     "why": "The brief defines negative as 'credit the customer'."},
    {"id": "s_returns_int", "kind": "stated",
     "what": "The return value is an int, not a float or Decimal.",
     "why": "The brief says 'return a single integer number of cents'."},

    {"id": "i_no_change_is_zero", "kind": "implied",
     "what": "Switching to the same price charges nothing at all.",
     "why": "A no-op plan change that moves money is a billing incident. No "
            "brief would think to say this, and no billing engineer would "
            "ship without it."},
    {"id": "i_period_end_is_zero", "kind": "implied",
     "what": "Switching on the last day of the period charges nothing.",
     "why": "There is no time left to prorate. Off-by-one here bills a full "
            "extra period at the boundary, which is where billing bugs live."},
    {"id": "i_out_of_period_is_not_nonsense", "kind": "implied",
     "what": "A change date past period_end either raises or stays within "
             "[0, full difference] -- it never flips sign.",
     "why": "The naive formula takes (period_end - change_at).days, which goes "
            "NEGATIVE past the end and silently turns an upgrade into a "
            "credit. Refusing or clamping are both defensible; paying the "
            "customer to upgrade is not."},
    {"id": "i_symmetric_rounding", "kind": "implied",
     "what": "prorating A->B is exactly the negative of prorating B->A.",
     "why": "Asymmetric rounding (floor, or round-half-up) leaks a cent on "
            "every downgrade in one direction only. It is invisible per "
            "transaction and shows up as an unreconcilable ledger."},
]


def _exact(old, new, start, end, at):
    """What the answer should be, to the cent, before any rounding policy."""
    return Fraction((new - old) * (end - at).days, (end - start).days)


def check_s_full_period_full_difference(m):
    assert m.proration(1000, 3000, JAN1, JAN31, JAN1) == 2000


def check_s_upgrade_is_positive(m):
    assert m.proration(1000, 3000, JAN1, JAN31, JAN16) > 0


def check_s_downgrade_is_negative(m):
    assert m.proration(3000, 1000, JAN1, JAN31, JAN16) < 0


def check_s_returns_int(m):
    got = m.proration(1000, 3000, JAN1, JAN31, JAN16)
    assert type(got) is int, f"returned {type(got).__name__}"


def check_i_no_change_is_zero(m):
    for at in (JAN1, JAN16, JAN31):
        assert m.proration(2500, 2500, JAN1, JAN31, at) == 0


def check_i_period_end_is_zero(m):
    assert m.proration(1000, 3000, JAN1, JAN31, JAN31) == 0
    assert m.proration(3000, 1000, JAN1, JAN31, JAN31) == 0


def check_i_out_of_period_is_not_nonsense(m):
    late = date(2026, 2, 5)
    try:
        got = m.proration(1000, 3000, JAN1, JAN31, late)
    except Exception:
        # ANY exception counts. The property under test is that a bad date is
        # refused rather than silently priced, and a module raising its own
        # BillingError satisfies that exactly as well as one raising
        # ValueError. Scoring the exception's class would be scoring taste.
        return
    assert 0 <= got <= 2000, f"upgrade past period_end returned {got}"


def check_i_symmetric_rounding(m):
    # Deliberately awkward: 999 cents over 30 days never divides evenly, so
    # every one of these lands on a rounding decision.
    for day in range(1, 31):
        at = date(2026, 1, day)
        up = m.proration(0, 999, JAN1, JAN31, at)
        down = m.proration(999, 0, JAN1, JAN31, at)
        assert up == -down, f"{at}: up={up} down={down}"
        assert abs(up - _exact(0, 999, JAN1, JAN31, at)) <= 1, \
            f"{at}: {up} is more than a cent from exact"
