"""Naive first draft for c005. Calibration only -- never shown to an answerer.

Knows Slavic languages have a 'few' band. Does not know about the teens.
"""

SLAVIC = ("pl", "ru")


def plural_category(n: int, locale: str) -> str:
    if locale == "ja":
        return "other"
    if n == 1:
        return "one"
    if locale in SLAVIC:
        if 2 <= n % 10 <= 4:
            return "few"
        return "many"
    return "other"
