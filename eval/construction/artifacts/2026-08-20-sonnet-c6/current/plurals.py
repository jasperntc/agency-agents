"""CLDR plural category resolution for UI string pluralization.

Plurals are grammar, not arithmetic: ``if count == 1`` only happens to work
for English, and even there it is the wrong abstraction the moment a second
locale ships. This module implements the CLDR plural rules (Unicode
Technical Standard #35, "Language Plural Rules") for cardinal numbers, so
callers can select the correct ICU-style plural branch (``{count, plural,
one {...} other {...}}``) per locale instead of hand-rolling comparisons.

Supported locales: "en", "pl", "ru", "ja".

    >>> plural_category(1, "en")
    'one'
    >>> plural_category(5, "en")
    'other'
    >>> plural_category(2, "pl")   # 2 pliki
    'few'
    >>> plural_category(5, "pl")   # 5 plikow
    'many'
    >>> plural_category(21, "ru")  # 21 fayl
    'one'
    >>> plural_category(3, "ja")   # Japanese has one category: other
    'other'

Every rule below operates on ``i``, the absolute integer value of ``n`` --
CLDR plural operands are always defined against the absolute value of the
source number, so ``plural_category(-2, "pl")`` resolves the same as
``plural_category(2, "pl")``. This module handles cardinal (count) plurals
only; ordinal plurals ("1st", "2nd") follow a separate CLDR rule set and are
out of scope here.

Only "other" is guaranteed to exist in every locale's rule set, which is why
CLDR requires every message to define it as a catch-all. None of the four
locales supported here use the "zero" or "two" categories, so this module
never returns them -- that is a property of these locales' CLDR data, not a
limitation of the implementation.
"""

from __future__ import annotations


def _en(i: int) -> str:
    # CLDR `en`: one -> i = 1; other -> everything else.
    if i == 1:
        return "one"
    return "other"


def _pl(i: int) -> str:
    # CLDR `pl` (integers only, so the `v = 0` operand is implicit):
    #   one  -> i = 1
    #   few  -> i % 10 = 2..4 and i % 100 != 12..14
    #   many -> i != 1 and i % 10 = 0..1
    #           or i % 10 = 5..9
    #           or i % 100 = 12..14
    #   other -> everything else
    mod10 = i % 10
    mod100 = i % 100
    if i == 1:
        return "one"
    if mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        return "few"
    if (i != 1 and mod10 in (0, 1)) or mod10 in (5, 6, 7, 8, 9) or mod100 in (12, 13, 14):
        return "many"
    return "other"


def _ru(i: int) -> str:
    # CLDR `ru` (integers only):
    #   one  -> i % 10 = 1 and i % 100 != 11
    #   few  -> i % 10 = 2..4 and i % 100 != 12..14
    #   many -> i % 10 = 0
    #           or i % 10 = 5..9
    #           or i % 100 = 11..14
    #   other -> everything else (fractional values; unreachable for int n)
    mod10 = i % 10
    mod100 = i % 100
    if mod10 == 1 and mod100 != 11:
        return "one"
    if mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        return "few"
    if mod10 == 0 or mod10 in (5, 6, 7, 8, 9) or mod100 in (11, 12, 13, 14):
        return "many"
    return "other"


def _ja(i: int) -> str:
    # CLDR `ja`: a single category, `other`, for every count. Japanese has
    # no grammatical plural, so ICU messages in this locale never branch.
    return "other"


_RULES = {
    "en": _en,
    "pl": _pl,
    "ru": _ru,
    "ja": _ja,
}


def plural_category(n: int, locale: str) -> str:
    """Return the CLDR cardinal plural category for `n` in `locale`.

    Args:
        n: The count being pluralized for. Must be an ``int``; CLDR's
            fractional-value operands (``v``, ``f``, ``t``) do not apply,
            since this module only resolves integer cardinal plurals.
        locale: One of "en", "pl", "ru", "ja".

    Returns:
        One of "zero", "one", "two", "few", "many", "other". Every
        supported locale defines "other", so a value is always returned.

    Raises:
        TypeError: If `n` is not an ``int`` (e.g. a ``float`` or ``bool``
            used where a count is expected).
        ValueError: If `locale` is not one of the supported locales.
    """
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"n must be an int, got {type(n).__name__}")

    try:
        rule = _RULES[locale]
    except KeyError:
        supported = ", ".join(sorted(_RULES))
        raise ValueError(
            f"Unsupported locale {locale!r}; supported locales: {supported}"
        ) from None

    return rule(abs(n))
