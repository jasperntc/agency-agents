"""CLDR cardinal plural categories for the locales this UI ships in.

Plural selection is grammar, not arithmetic. ``if n == 1`` is an English rule
that merely looks like a general one: it renders "5 plik" where Polish needs
"5 plików", and it invents a distinction Japanese does not make. This module
implements the CLDR cardinal rules verbatim per language, so runtime selection
agrees with the categories translators, ICU MessageFormat, and every TMS in the
pipeline already speak.

Public API::

    plural_category(n, locale) -> "zero" | "one" | "two" | "few" | "many" | "other"

Scope, and the limits that are deliberate
-----------------------------------------
* **Cardinals only.** Ordinals ("1st", "2nd") are a separate CLDR table with
  its own categories; they belong in their own function, not behind a flag.
* **Integers only.** CLDR selects on six operands (n, i, v, w, f, t), and the
  *visible decimal digits* change the answer: English 1 is "one" but 1.0 is
  "other" -- "1.0 stars", never "1.0 star". Counts in this UI are integers, so
  this module takes ``int`` and rejects everything else instead of guessing
  which operand a float was meant to be.
* **Four languages.** An unlisted one raises; see ``plural_category``.

Rules transcribed from the Unicode CLDR cardinal plural rules (``plurals.xml``).
Each function carries its source rule so a reviewer can diff it against the
upstream table without leaving the file.
"""

from collections.abc import Callable

__all__ = ["UnsupportedLocaleError", "SUPPORTED_LANGUAGES", "plural_category"]


class UnsupportedLocaleError(ValueError):
    """Raised for a locale whose plural rules are not implemented here.

    Subclasses ``ValueError`` so callers already validating input at the
    boundary keep working; catch it specifically to fall back to a locale you
    have actually shipped.
    """


# CLDR operands used below (the others are fixed by integer input):
#   n = the absolute value of the source number
#   i = the integer digits of n
#   v = number of visible fraction digits -- always 0 here, so every "v = 0"
#       clause in the transcribed rules is satisfied. The clauses are left in
#       the docstrings only to keep each rule diffable against its CLDR source.
# Taking the absolute value is not a nicety: -1 is "one" in English
# ("-1 item"), and a sign selects a category in no locale.


def _en(i: int) -> str:
    """English -- categories: one, other.

    CLDR::

        one   -> i = 1 and v = 0
        other -> everything else

    1 file / 0 files / 2 files.
    """
    return "one" if i == 1 else "other"


def _pl(i: int) -> str:
    """Polish -- categories: one, few, many (and other, fractions only).

    CLDR::

        one   -> i = 1 and v = 0
        few   -> v = 0 and i % 10 = 2..4 and i % 100 != 12..14
        many  -> v = 0 and i != 1 and i % 10 = 0..1
                 or v = 0 and i % 10 = 5..9
                 or v = 0 and i % 100 = 12..14
        other -> everything else

    1 plik / 2 pliki / 5 plików / 12 plików / 22 pliki, and 0 plików -- zero
    takes "many", not a category of its own.

    "many" is the catch-all, not "other": once "one" and "few" are excluded,
    the remaining integers are exactly CLDR's three "many" clauses, so the
    fall-through below is faithful rather than a shortcut. "other" is
    unreachable from an int -- it exists for fractions such as 1,5 pliku.
    """
    if i == 1:
        return "one"
    last, last_two = i % 10, i % 100
    if 2 <= last <= 4 and not 12 <= last_two <= 14:
        return "few"
    return "many"


def _ru(i: int) -> str:
    """Russian -- categories: one, few, many (and other, fractions only).

    CLDR::

        one   -> v = 0 and i % 10 = 1 and i % 100 != 11
        few   -> v = 0 and i % 10 = 2..4 and i % 100 != 12..14
        many  -> v = 0 and i % 10 = 0
                 or v = 0 and i % 10 = 5..9
                 or v = 0 and i % 100 = 11..14
        other -> everything else

    1 файл / 2 файла / 5 файлов / 11 файлов / 21 файл.

    The teens are the trap, and the reason Polish rules cannot be borrowed
    here: Russian calls 21 "one" while Polish calls it "many". As in Polish,
    the fall-through is CLDR's "many" and "other" is unreachable from an int.
    """
    last, last_two = i % 10, i % 100
    if last == 1 and last_two != 11:
        return "one"
    if 2 <= last <= 4 and not 12 <= last_two <= 14:
        return "few"
    return "many"


def _ja(i: int) -> str:
    """Japanese -- categories: other.

    CLDR::

        other -> everything

    Japanese does not inflect nouns for number, so the count never changes the
    noun and the operand goes unused. What the count does select is a counter
    word -- 1枚 for flat things, 1本 for long ones, 1個 for small objects --
    chosen by the shape of the thing counted, not by its quantity. That is the
    message's job, not plural selection's.
    """
    return "other"


_RULES: dict[str, Callable[[int], str]] = {
    "en": _en,
    "ja": _ja,
    "pl": _pl,
    "ru": _ru,
}

#: Language subtags with rules implemented here.
SUPPORTED_LANGUAGES = frozenset(_RULES)


def _language_subtag(locale: str) -> str:
    """Reduce a locale identifier to its primary language subtag, lowercased.

    "en" -> "en", "en-US" -> "en", "ru_RU" -> "ru", "PL" -> "pl". Both
    separators turn up in practice: BCP 47 writes "en-US", POSIX and Java write
    "en_US", and ``Accept-Language`` sends whatever the browser was set to.

    Dropping region and script is the first hop of the fallback chain, and it
    is lossless *for these four languages* -- none of them splits its cardinal
    rules by region. It is not lossless in general: CLDR gives ``pt`` and
    ``pt-PT`` different rule sets. Any language added here has to be checked
    against ``plurals.xml`` for a regional split before it inherits this
    shortcut.
    """
    if not isinstance(locale, str):
        raise TypeError(f"locale must be a str, got {type(locale).__name__}")
    return locale.strip().replace("_", "-").split("-", 1)[0].lower()


def plural_category(n: int, locale: str) -> str:
    """Return the CLDR cardinal plural category of ``n`` in ``locale``.

    Args:
        n: The count. Any int, including 0 and negatives -- CLDR selects on the
            absolute value, so -1 is "one" in English ("-1 item").
        locale: A language code or BCP 47 tag: "pl", "ru-RU", "en_US", "JA".
            Case and separator are normalised and region and script subtags are
            dropped (see ``_language_subtag``).

    Returns:
        One of "zero", "one", "two", "few", "many", "other". Which subset a
        language can return is fixed by its rules: en {one, other}, pl and ru
        {one, few, many}, ja {other}. A catalogue covering only these locales
        therefore never needs a "zero" or "two" branch. For a special
        empty-state string, use ICU's explicit-value form
        ``=0 {Your cart is empty}``, which is matched ahead of categories --
        that is a different mechanism from the "zero" category, which none of
        these locales ever selects.

    Raises:
        TypeError: ``n`` is not an int, or ``locale`` is not a str. Floats are
            rejected deliberately: CLDR selects on visible decimal digits, so
            1 and 1.0 are different categories in English, and silently
            conflating them is the class of bug this module exists to prevent.
        UnsupportedLocaleError: no rules for that language. It raises rather
            than falling back to English (wrong grammar, shipped quietly) or to
            bare "other" (CLDR root behaviour, which turns every "1 item" into
            "1 items"). A missing locale should fail at the boundary, where it
            costs one rule set to fix, not in front of a reader.

    Examples:
        >>> plural_category(1, "en"), plural_category(0, "en")
        ('one', 'other')
        >>> plural_category(-1, "en-US")
        'one'
        >>> [plural_category(k, "pl") for k in (1, 2, 5, 12, 22)]
        ['one', 'few', 'many', 'many', 'few']
        >>> [plural_category(k, "ru_RU") for k in (1, 2, 5, 11, 21)]
        ['one', 'few', 'many', 'many', 'one']
        >>> plural_category(7, "ja")
        'other'
    """
    if not isinstance(n, int):
        raise TypeError(
            f"n must be an int count, got {type(n).__name__}: {n!r}. CLDR "
            "selects on visible decimal digits, so a non-integer count needs "
            "the full operand set this module does not implement."
        )
    language = _language_subtag(locale)
    try:
        rule = _RULES[language]
    except KeyError:
        raise UnsupportedLocaleError(
            f"no CLDR plural rules for language {language!r} (resolved from "
            f"locale {locale!r}); implemented: "
            f"{', '.join(sorted(SUPPORTED_LANGUAGES))}. Add the rule set from "
            "CLDR plurals.xml rather than borrowing a similar-looking "
            "locale's -- Polish and Russian disagree on 11 and 21."
        ) from None
    return rule(abs(n))
