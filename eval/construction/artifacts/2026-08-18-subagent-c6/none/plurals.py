"""CLDR cardinal plural categories for integer counts.

``plural_category(n, locale)`` returns the Unicode CLDR plural category to use
when selecting a UI string for the count ``n`` -- one of "zero", "one", "two",
"few", "many" or "other".  Supported locales: "en", "pl", "ru", "ja".

Scope, and what follows from it
-------------------------------
CLDR states its rules over six operands: ``n`` (absolute value of the source
number), ``i`` (integer digits), ``v``/``w`` (fraction digit counts) and
``f``/``t`` (the fraction digits themselves).  This module accepts an ``int``,
so on every call ``i == n == abs(count)`` and ``v == w == f == t == 0``.

Two consequences are deliberate rather than missing:

* Clauses that require a visible fraction can never fire.  Russian and Polish
  reach "other" only for values like 1.5, so an integer count in those locales
  is always "one", "few" or "many" -- never "other".
* English gained a "many" category in CLDR 42 for compact and currency forms
  ("1M", where the compact exponent ``c`` is non-zero).  A plain ``int`` carries
  no compact exponent, so ``c == 0`` and "many" is unreachable here too.

``CATEGORIES`` lists the full CLDR set for reference, but a caller building a
message table wants the reachable subset for one locale, which is what
``categories_for()`` reports.

Rule source: Unicode CLDR, "Language Plural Rules"
<https://unicode.org/reports/tr35/tr35-numbers.html#Language_Plural_Rules>.
"""

from __future__ import annotations

from collections.abc import Callable

__all__ = [
    "CATEGORIES",
    "SUPPORTED_LOCALES",
    "categories_for",
    "plural_category",
]

#: Every CLDR plural category, in CLDR's canonical order.  No single locale
#: uses all six; "zero" and "two" belong to locales outside this module's set
#: (Latvian, Welsh, Arabic, ...) and are listed only for completeness.
CATEGORIES: tuple[str, ...] = ("zero", "one", "two", "few", "many", "other")


# --------------------------------------------------------------------------
# Per-locale rules.  Each takes the CLDR operand ``i`` (a non-negative int)
# and returns a category.  Keeping one function per locale means each rule can
# be read against the CLDR source text it transcribes.
# --------------------------------------------------------------------------

def _plural_en(i: int) -> str:
    """English: ``one`` when i = 1 and v = 0, otherwise ``other``."""
    return "one" if i == 1 else "other"


def _plural_ja(i: int) -> str:
    """Japanese: no count distinction at all -- every value is ``other``."""
    return "other"


def _plural_ru(i: int) -> str:
    """Russian, integer subset.

    one  -- i % 10 = 1 and i % 100 != 11         (1, 21, 101; "21 kniga")
    few  -- i % 10 = 2..4 and i % 100 != 12..14  (2, 23, 104; "23 knigi")
    many -- everything else, zero included       (0, 5, 11, 25; "5 knig")

    CLDR's "other" for Russian is reached only through a visible fraction,
    so it cannot occur for an int.
    """
    units, hundreds = i % 10, i % 100
    if units == 1 and hundreds != 11:
        return "one"
    if 2 <= units <= 4 and not 12 <= hundreds <= 14:
        return "few"
    return "many"


def _plural_pl(i: int) -> str:
    """Polish, integer subset.

    one  -- i = 1 exactly.  Note the contrast with Russian: Polish 21 is
            *not* "one" ("21 ksiazek" is many, where Russian 21 is one).
    few  -- i % 10 = 2..4 and i % 100 != 12..14  (2, 23, 104; "23 ksiazki")
    many -- everything else, zero included       (0, 5, 11, 21, 25)

    As with Russian, "other" is fraction-only and unreachable for an int.
    """
    if i == 1:
        return "one"
    units, hundreds = i % 10, i % 100
    if 2 <= units <= 4 and not 12 <= hundreds <= 14:
        return "few"
    return "many"


_RULES: dict[str, Callable[[int], str]] = {
    "en": _plural_en,
    "ja": _plural_ja,
    "pl": _plural_pl,
    "ru": _plural_ru,
}

# Categories each locale can actually produce *for integer counts*, in CLDR
# order.  Polish and Russian additionally define "other" for fractional counts;
# this integer-only module never returns it, so it is not listed.
_REACHABLE: dict[str, tuple[str, ...]] = {
    "en": ("one", "other"),
    "ja": ("other",),
    "pl": ("one", "few", "many"),
    "ru": ("one", "few", "many"),
}

#: Language subtags this module knows, sorted.
SUPPORTED_LOCALES: tuple[str, ...] = tuple(sorted(_RULES))


def _language_subtag(locale: str) -> str:
    """Reduce a locale tag to its lowercase language subtag, and validate it.

    Accepts the shapes that turn up in real string catalogues -- "en", "en-GB",
    "en_US", "PL" -- since plural rules depend on the language subtag alone;
    region and script never change them.

    Raises ``ValueError`` for anything else.  Falling back to "other" would be
    the quieter option, but a missing rule table shows up as *plausible*
    English-shaped output in a language that needed three forms, which is
    exactly the bug nobody reports.
    """
    if not isinstance(locale, str):
        raise TypeError(f"locale must be a str, got {type(locale).__name__}")
    subtag = locale.strip().replace("_", "-").split("-", 1)[0].lower()
    if subtag not in _RULES:
        raise ValueError(
            f"unsupported locale {locale!r}; supported: "
            f"{', '.join(SUPPORTED_LOCALES)}"
        )
    return subtag


def plural_category(n: int, locale: str) -> str:
    """Return the CLDR plural category for the count *n* in *locale*.

    :param n: the count.  Negative counts are folded to their absolute value,
        matching CLDR's ``n`` operand.
    :param locale: a language subtag or a tag that starts with one, e.g. "ru",
        "pt-BR", "en_US".  Case and ``-``/``_`` separators are both accepted.
    :returns: one of ``CATEGORIES``.
    :raises TypeError: if *n* is not an ``int`` or *locale* is not a ``str``.
        ``bool`` is rejected too -- it satisfies ``isinstance(x, int)``, but a
        flag arriving where a count belongs is a caller bug worth surfacing.
    :raises ValueError: if *locale* is not one of ``SUPPORTED_LOCALES``.

    A ``float`` is refused rather than coerced: CLDR distinguishes 1 from 1.0
    (the latter has one visible fraction digit, making it "other" in English),
    and this module cannot see that distinction once a float is rounded.

    >>> plural_category(1, "en")
    'one'
    >>> plural_category(0, "en")
    'other'
    >>> plural_category(5, "ja")
    'other'
    >>> plural_category(21, "ru")
    'one'
    >>> plural_category(21, "pl")
    'many'
    >>> plural_category(-3, "ru")
    'few'
    >>> plural_category(2, "en-GB")
    'other'
    """
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"n must be an int, got {type(n).__name__}")
    return _RULES[_language_subtag(locale)](abs(n))


def categories_for(locale: str) -> tuple[str, ...]:
    """Return the categories ``plural_category`` can produce for *locale*.

    In CLDR order, and limited to what an integer count can reach.  Use it to
    size a message table without shipping plural forms a locale never asks for,
    or to assert at load time that a translation supplies every form it needs.

    >>> categories_for("ja")
    ('other',)
    >>> categories_for("pl")
    ('one', 'few', 'many')
    """
    return _REACHABLE[_language_subtag(locale)]
