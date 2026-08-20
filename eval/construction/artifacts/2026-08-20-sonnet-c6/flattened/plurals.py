"""CLDR plural category resolution for UI string pluralization.

Implements the plural rules published in Unicode CLDR (Common Locale Data
Repository) for a fixed set of locales, sufficient to select the correct
plural form of a translated UI string given an integer count.

Only integer counts are supported (the "v" / "f" operands used by the full
CLDR grammar for decimal fractions are always 0 here), which covers the
normal case of pluralizing UI strings around item counts, notification
counts, and the like. Passing a float or Decimal is out of scope and will
raise a TypeError rather than silently mis-categorize it.

Supported locales: "en", "pl", "ru", "ja".

Reference: CLDR language plural rules,
https://www.unicode.org/cldr/cldr-aux/charts/33/supplemental/language_plural_rules.html
"""

from __future__ import annotations

from typing import Callable, Dict

# One of "zero", "one", "two", "few", "many", "other".
PluralCategory = str


def _rule_en(i: int) -> PluralCategory:
    """English: singular only for exactly 1, plural otherwise."""
    return "one" if i == 1 else "other"


def _rule_ja(i: int) -> PluralCategory:
    """Japanese: no grammatical plural; every count is "other"."""
    return "other"


def _rule_pl(i: int) -> PluralCategory:
    """Polish: one / few / many, based on the last one and two digits.

    one:  i = 1
    few:  i % 10 in 2..4 and i % 100 not in 12..14
    many: i % 10 in 0,1,5..9 or i % 100 in 12..14
    other: anything else (unreached for non-negative integers)
    """
    if i == 1:
        return "one"

    mod10 = i % 10
    mod100 = i % 100

    if mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        return "few"

    if mod10 in (0, 1, 5, 6, 7, 8, 9) or mod100 in (12, 13, 14):
        return "many"

    return "other"


def _rule_ru(i: int) -> PluralCategory:
    """Russian: one / few / many, based on the last one and two digits.

    one:  i % 10 = 1 and i % 100 != 11
    few:  i % 10 in 2..4 and i % 100 not in 12..14
    many: i % 10 = 0, or i % 10 in 5..9, or i % 100 in 11..14
    other: anything else (unreached for non-negative integers)
    """
    mod10 = i % 10
    mod100 = i % 100

    if mod10 == 1 and mod100 != 11:
        return "one"

    if mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        return "few"

    if mod10 == 0 or mod10 in (5, 6, 7, 8, 9) or mod100 in (11, 12, 13, 14):
        return "many"

    return "other"


_RULES: Dict[str, Callable[[int], PluralCategory]] = {
    "en": _rule_en,
    "pl": _rule_pl,
    "ru": _rule_ru,
    "ja": _rule_ja,
}


def plural_category(n: int, locale: str) -> PluralCategory:
    """Return the CLDR plural category for count `n` in `locale`.

    Parameters
    ----------
    n:
        The item count being pluralized. Must be an `int` (`bool` is
        rejected even though it is technically an `int` subclass, since a
        boolean count is almost certainly a caller bug rather than an
        intentional 0/1 count).
    locale:
        A supported locale code: "en", "pl", "ru", or "ja". Matching is
        case-insensitive on the base language subtag, so locale tags like
        "en-US", "pl_PL", or "RU" all resolve to their base ruleset.

    Returns
    -------
    One of "zero", "one", "two", "few", "many", "other". None of the
    currently supported locales produce "zero" or "two" -- those categories
    exist for other CLDR locales -- but the return type covers the full
    CLDR category set for forward compatibility with future locales.

    Raises
    ------
    TypeError:
        If `n` is not an `int`, or `locale` is not a `str`.
    ValueError:
        If `locale` (after normalizing to its base language subtag) is not
        one of the supported locales.
    """
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"n must be an int, got {type(n).__name__}")
    if not isinstance(locale, str):
        raise TypeError(f"locale must be a str, got {type(locale).__name__}")

    # CLDR plural rules key off of "n", the absolute value of the source
    # number, and (for integers) "i", its integer part -- here n == i since
    # only whole counts are accepted.
    i = abs(n)

    base = locale.strip().split("-")[0].split("_")[0].lower()

    try:
        rule = _RULES[base]
    except KeyError:
        raise ValueError(
            f"unsupported locale {locale!r}; supported locales are "
            f"{sorted(_RULES)}"
        ) from None

    return rule(i)
