"""Reference implementation for c005. Not shown to any answerer.

CLDR plural rules for en, pl, ru, ja, integer counts only.
"""


def plural_category(n: int, locale: str) -> str:
    lang = locale.split("-")[0].split("_")[0].lower()
    n = abs(int(n))
    mod10, mod100 = n % 10, n % 100

    if lang == "ja":
        return "other"

    if lang == "en":
        return "one" if n == 1 else "other"

    if lang == "ru":
        if mod10 == 1 and mod100 != 11:
            return "one"
        if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
            return "few"
        return "many"

    if lang == "pl":
        if n == 1:
            return "one"
        if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
            return "few"
        return "many"

    raise ValueError(f"unsupported locale: {locale}")
