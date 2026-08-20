"""c005 -- CLDR plural categories. Acceptance suite."""

# Why this task is in the set. It names the discriminator, so it lives
# HERE -- with the answer key, which is withheld while answers are being
# collected -- and never in tasks.jsonl, which any answerer can read.
WHY_THIS_TASK = (
    'A named public standard with famous edge cases. If a specialist '
    'file cannot help here it is hard to say where it would.'
)

VALID = {"zero", "one", "two", "few", "many", "other"}

CHECKS = [
    {"id": "s_english_one", "kind": "stated",
     "what": "en 1 is 'one'.",
     "why": "The brief asks for the CLDR category and this is the base case."},
    {"id": "s_english_other", "kind": "stated",
     "what": "en 2, 3 and 17 are 'other'.",
     "why": "English has exactly two categories."},
    {"id": "s_japanese_has_one_form", "kind": "stated",
     "what": "ja is 'other' for every count.",
     "why": "The brief names ja as a supported locale; it has a single form."},
    {"id": "s_returns_a_valid_category", "kind": "stated",
     "what": "Every answer is one of the six CLDR category names.",
     "why": "The brief lists the six permitted return values."},

    {"id": "i_english_zero_is_other", "kind": "implied",
     "what": "en 0 is 'other', not 'one'.",
     "why": "'0 items' is plural in English. The n<=1 shortcut passes every "
            "stated check and produces '0 item' in the shipped UI."},
    {"id": "i_russian_teens_are_many", "kind": "implied",
     "what": "ru 11, 12, 14 and 111 are 'many'.",
     "why": "The teen exception is the single most-missed rule in Slavic "
            "pluralisation: n % 10 == 1 is true for 11, and the naive rule "
            "puts it in 'one'."},
    {"id": "i_russian_twenty_one_is_one", "kind": "implied",
     "what": "ru 21 and 101 are 'one'.",
     "why": "The mirror of the teen trap. Testing n == 1 rather than the "
            "modulus gets every count above 20 wrong in the other "
            "direction."},
    {"id": "i_polish_bands_are_right", "kind": "implied",
     "what": "pl 2-4 are 'few'; 5, 0, 25 and 13 are 'many'.",
     "why": "Polish needs the three-way split and the same 12-14 exception. "
            "Treating it as a copy of English or of Russian fails here, and "
            "the brief gives no hint that the locales differ in shape."},
]

RU_MANY = (0, 5, 8, 11, 12, 14, 100, 111, 114)
RU_FEW = (2, 3, 4, 22, 23, 104)
RU_ONE = (1, 21, 101, 1001)
PL_FEW = (2, 3, 4, 22, 23)
PL_MANY = (0, 5, 8, 12, 13, 14, 25, 111)


def check_s_english_one(m):
    assert m.plural_category(1, "en") == "one"


def check_s_english_other(m):
    for n in (2, 3, 17):
        assert m.plural_category(n, "en") == "other", n


def check_s_japanese_has_one_form(m):
    for n in (0, 1, 2, 5, 11, 21):
        assert m.plural_category(n, "ja") == "other", n


def check_s_returns_a_valid_category(m):
    for locale in ("en", "pl", "ru", "ja"):
        for n in range(0, 130):
            got = m.plural_category(n, locale)
            assert got in VALID, f"{locale}/{n} returned {got!r}"


def check_i_english_zero_is_other(m):
    assert m.plural_category(0, "en") == "other"


def check_i_russian_teens_are_many(m):
    for n in (11, 12, 14, 111, 114):
        assert m.plural_category(n, "ru") == "many", n


def check_i_russian_twenty_one_is_one(m):
    for n in RU_ONE:
        assert m.plural_category(n, "ru") == "one", n


def check_i_polish_bands_are_right(m):
    for n in PL_FEW:
        assert m.plural_category(n, "pl") == "few", n
    for n in PL_MANY:
        assert m.plural_category(n, "pl") == "many", n
    assert m.plural_category(1, "pl") == "one"
