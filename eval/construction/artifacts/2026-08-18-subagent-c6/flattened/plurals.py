"""CLDR cardinal plural categories for integer counts.

Choosing between "1 file" and "5 files" is grammar, not arithmetic, and the
grammar differs by language. ``plural_category`` maps a count and a locale to
one of the six CLDR category names -- "zero", "one", "two", "few", "many",
"other" -- and the translation catalogue holds one message per category the
language actually uses. Nothing here formats a number or a message; this
answers only the question a catalogue lookup needs answered first.

The category names are labels, not descriptions
-----------------------------------------------
"one" does not mean the count is 1, and "zero" does not mean it is 0. In
Russian 21, 101 and 1001 are all "one". In Polish 0 is "many". In Latvian --
not supported here, but the clearest warning -- "zero" covers 0, 10 to 20, 30,
40 and more besides. Code that branches on ``n == 1`` and calls the rest
plural is an English rule wearing a general-purpose name, and it is wrong in
most of the languages it will meet.

The category a language does *not* use matters as much as the ones it does.
English has two, Japanese has one, Polish and Russian have four apiece. Asking
a translator for an "en" catalogue with singular and plural is right; asking
for the same two forms in Polish silently drops two grammatical forms.

Operands
--------
CLDR rules are written over operands taken from the *formatted* number: n (its
absolute value), i (its integer digits), v and w (how many fraction digits are
visible, with and without trailing zeros), f and t (those digits as an
integer), and c/e (the exponent of a compact or scientific form). An integer
count pins v, w, f, t and c to 0 and leaves i = n = abs(count), so every rule
below reduces to arithmetic on i alone.

Two consequences are load-bearing:

* The count must be an ``int``, and 1.0 is not 1. English "1.0 stars" takes
  the "other" form, because the rule is ``i = 1 and v = 0`` and the rendered
  ".0" makes v = 1. A float has already lost what the rule needs -- 1.5 and
  1.50 are one float but two different operand sets -- so floats are refused
  rather than rounded into a confident wrong answer.
* Compact notation is out of scope. Where a UI renders 1000000 as "1M", CLDR
  selects on the operands of that compact form, and the c/e operands this
  function does not model begin to matter.

Sign
----
Operand n is defined as the absolute value of the source number, so -1 is
"one" in English exactly as 1 is, and -22 is "few" in Polish exactly as 22 is.
That is deliberate in CLDR: "-1 degree" inflects like "1 degree".

Cardinal only
-------------
These are cardinal rules, for counting things. Ordinals -- "3rd file" -- are a
separate CLDR rule set that disagrees: English cardinals use one/other, while
English ordinals use one/two/few/other, which is what makes 1st, 2nd, 3rd and
4th differ. Do not route ordinal messages through this function.

Locale matching
---------------
Plural rules are keyed by language, so an identifier is reduced to its primary
subtag and matched case-insensitively: "pl", "pl-PL", "pl_PL.UTF-8" and "PL"
all select the Polish rules. That shortcut is safe for these four languages
but is not universal, and anyone extending the table should check before
relying on it -- CLDR gives pt-PT different rules from pt, so a Portuguese
entry would have to be keyed more finely than a bare "pt".

Source
------
Each rule is transcribed from the cardinal rules in the Unicode CLDR
(``plurals.xml``, specified by UTS #35, Language Plural Rules) and quoted
verbatim above its implementation, so it can be diffed against a future
release without reverse-engineering the code.
"""

import re

__all__ = [
    "plural_category",
    "UnsupportedLocaleError",
    "CATEGORIES",
    "SUPPORTED_LOCALES",
]

#: Every category CLDR defines, in its conventional order. No single language
#: uses all six, and "other" is the only one every language has.
CATEGORIES = ("zero", "one", "two", "few", "many", "other")


class UnsupportedLocaleError(ValueError):
    """No plural rules are implemented for the requested locale.

    A ValueError subclass, so callers that already guard against bad
    arguments keep working without knowing this type exists.
    """


def plural_category(n: int, locale: str) -> str:
    """Return the CLDR cardinal plural category of ``n`` in ``locale``.

    Args:
        n: The count being described. A negative count is categorised by its
            absolute value, per the CLDR definition of operand n.
        locale: A locale identifier. Only the primary language subtag is
            significant, so "ru", "ru-RU" and "ru_RU.UTF-8" are equivalent.

    Returns:
        One of ``CATEGORIES``. Which of them are reachable depends on the
        language: "one" and "other" for en; "one", "few" and "many" for pl
        and ru; always "other" for ja.

    Raises:
        TypeError: If ``n`` is not an int -- bools and floats included -- or
            ``locale`` is not a str.
        UnsupportedLocaleError: If no rules are implemented for the
            language. Raised rather than falling back to English or to
            "other", because either fallback returns a category that looks
            perfectly valid, leaving the caller no way to tell it is
            guessing; the failure would then surface as mis-inflected text
            in front of a reader instead of as an error at the call site.
    """
    # bool is a subclass of int, and True would quietly mean a count of one.
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(
            f"n must be an int count, got {type(n).__name__}. A fractional "
            "count is categorised from its visible fraction digits, which "
            "this function does not model; format it and select on the "
            "formatted operands instead."
        )
    if not isinstance(locale, str):
        raise TypeError(f"locale must be a str, got {type(locale).__name__}")

    language = _language_subtag(locale)
    rule = _RULES.get(language)
    if rule is None:
        raise UnsupportedLocaleError(
            f"no plural rules for locale {locale!r} (language subtag "
            f"{language!r}); supported languages are "
            f"{', '.join(sorted(SUPPORTED_LOCALES))}"
        )
    return rule(abs(n))


def _english(i: int) -> str:
    # CLDR en:
    #   one: i = 1 and v = 0
    return "one" if i == 1 else "other"


def _polish(i: int) -> str:
    # CLDR pl:
    #   one:  i = 1 and v = 0
    #   few:  v = 0 and i % 10 = 2..4 and i % 100 != 12..14
    #   many: v = 0 and i != 1 and i % 10 = 0..1
    #      or v = 0 and i % 10 = 5..9
    #      or v = 0 and i % 100 = 12..14
    #
    # Those three cover every integer between them, so the "other" form that
    # Polish does have is unreachable from here; it is reserved for fractions
    # such as 1.5. A Polish catalogue still needs it if the UI shows decimals.
    if i == 1:
        return "one"
    if 2 <= i % 10 <= 4 and not 12 <= i % 100 <= 14:
        return "few"
    return "many"


def _russian(i: int) -> str:
    # CLDR ru:
    #   one:  v = 0 and i % 10 = 1 and i % 100 != 11
    #   few:  v = 0 and i % 10 = 2..4 and i % 100 != 12..14
    #   many: v = 0 and i % 10 = 0
    #      or v = 0 and i % 10 = 5..9
    #      or v = 0 and i % 100 = 11..14
    #
    # Exhaustive over the integers as in Polish, and the teens are the trap in
    # both: 1 and 21 are "one" but 11 is "many", 2 and 22 are "few" but 12 is
    # "many". The i % 100 guards are what separate them.
    if i % 10 == 1 and i % 100 != 11:
        return "one"
    if 2 <= i % 10 <= 4 and not 12 <= i % 100 <= 14:
        return "few"
    return "many"


def _japanese(i: int) -> str:
    # CLDR ja: no rules at all beyond the implicit "other". Japanese nouns do
    # not inflect for number, so one message serves every count -- which means
    # a message written as an English sentence with the count spliced in will
    # read as a translation. The count is ignored here by design.
    return "other"


_RULES = {
    "en": _english,
    "pl": _polish,
    "ru": _russian,
    "ja": _japanese,
}

#: Language subtags with rules implemented. Membership is by subtag, so
#: "en-GB" is supported even though only "en" appears here.
SUPPORTED_LOCALES = frozenset(_RULES)

# BCP 47 uses "-", Python and gettext conventionally use "_", and POSIX names
# append an encoding or a modifier ("sr_RS@latin"). All that is wanted is the
# primary subtag, so the first of any of them ends the interesting part.
_SUBTAG_END = re.compile(r"[-_.@]")


def _language_subtag(locale: str) -> str:
    """Return the lowercased primary language subtag of a locale identifier."""
    return _SUBTAG_END.split(locale.strip(), maxsplit=1)[0].lower()
