"""CLDR plural category selection for UI string pluralization.

Implements the CLDR (Unicode Common Locale Data Repository) cardinal
plural rules for a small set of locales, using only the Python standard
library.

Supported locales: "en", "pl", "ru", "ja".

Reference:
https://www.unicode.org/cldr/cldr-aux/charts/45/supplemental/language_plural_rules.html
"""

from __future__ import annotations

__all__ = ["plural_category", "UnsupportedLocaleError"]


class UnsupportedLocaleError(ValueError):
    """Raised when `plural_category` is asked about a locale it does not know."""


def _category_en(i: int) -> str:
    # one: i = 1
    # other: everything else
    if i == 1:
        return "one"
    return "other"


def _category_ja(i: int) -> str:
    # Japanese has no grammatical plural: every count takes the same form.
    return "other"


def _category_ru(i: int) -> str:
    # one:  i % 10 = 1 and i % 100 != 11
    # few:  i % 10 = 2..4 and i % 100 != 12..14
    # many: i % 10 = 0 or i % 10 = 5..9 or i % 100 = 11..14
    # other: everything else
    mod10 = i % 10
    mod100 = i % 100
    if mod10 == 1 and mod100 != 11:
        return "one"
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return "few"
    if mod10 == 0 or 5 <= mod10 <= 9 or 11 <= mod100 <= 14:
        return "many"
    return "other"


def _category_pl(i: int) -> str:
    # one:  i = 1
    # few:  i % 10 = 2..4 and i % 100 != 12..14
    # many: i != 1 and i % 10 = 0..1, or i % 10 = 5..9, or i % 100 = 12..14
    # other: everything else
    mod10 = i % 10
    mod100 = i % 100
    if i == 1:
        return "one"
    if 2 <= mod10 <= 4 and not (12 <= mod100 <= 14):
        return "few"
    if (mod10 in (0, 1) and i != 1) or (5 <= mod10 <= 9) or (12 <= mod100 <= 14):
        return "many"
    return "other"


_RULES = {
    "en": _category_en,
    "pl": _category_pl,
    "ru": _category_ru,
    "ja": _category_ja,
}


def plural_category(n: int, locale: str) -> str:
    """Return the CLDR plural category for count `n` in `locale`.

    The result is one of "zero", "one", "two", "few", "many" or "other",
    per the CLDR cardinal plural rules for the given locale. `n` is
    treated as an integer count (an operand with no fraction digits),
    which is the common case for UI strings ("0 items", "1 item", ...).

    The locale is matched on its base language subtag, case-insensitively,
    so "en-US" or "en_GB" resolve the same way as "en".

    Args:
        n: The count to categorize. May be negative; the CLDR rules are
            applied to its absolute value, as the rules themselves do.
        locale: A BCP 47 style locale tag whose base language is one of
            "en", "pl", "ru" or "ja".

    Returns:
        The CLDR plural category as a string.

    Raises:
        TypeError: If `n` is not an int.
        UnsupportedLocaleError: If `locale`'s base language isn't one of
            the supported locales.
    """
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"n must be an int, got {type(n).__name__}")
    if not isinstance(locale, str) or not locale:
        raise UnsupportedLocaleError(f"unsupported locale: {locale!r}")

    base = locale.strip().lower().replace("_", "-").split("-", 1)[0]
    rule = _RULES.get(base)
    if rule is None:
        raise UnsupportedLocaleError(f"unsupported locale: {locale!r}")

    return rule(abs(n))
