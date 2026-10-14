"""Turn numbers into short spoken phrases.

Piper reads digits acceptably but ``1:42.317`` comes out oddly, and at racing
speed a short phrase matters more than natural prose. Lap times are spoken to
one decimal place, deltas likewise.
"""

from __future__ import annotations

_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def number_words(n: int) -> str:
    """Integers 0..999 as words."""
    if n < 0:
        return "minus " + number_words(-n)
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] if ones == 0 else f"{_TENS[tens]}-{_ONES[ones]}"
    hundreds, rest = divmod(n, 100)
    head = f"{_ONES[hundreds]} hundred"
    return head if rest == 0 else f"{head} and {number_words(rest)}"


def _tenths(ms: int) -> tuple[int, int]:
    """Split milliseconds into (whole seconds, tenths), rounding to nearest tenth."""
    tenths_total = int(round(ms / 100.0))
    return divmod(tenths_total, 10)


def lap_time_words(ms: int) -> str:
    """``102300`` -> "one forty-two point three"; ``67200`` -> "one oh seven point two"."""
    if ms <= 0:
        return "no time"
    seconds, tenths = _tenths(ms)
    minutes, seconds = divmod(seconds, 60)
    if minutes == 0:
        return f"{number_words(seconds)} point {number_words(tenths)}"
    sec_words = f"oh {number_words(seconds)}" if seconds < 10 else number_words(seconds)
    return f"{number_words(minutes)} {sec_words} point {number_words(tenths)}"


def delta_words(ms: int) -> str:
    """Unsigned delta: ``-412`` -> "zero point four"; ``61000`` -> "over a minute"."""
    seconds, tenths = _tenths(abs(ms))
    if seconds >= 60:
        return "over a minute"
    return f"{number_words(seconds)} point {number_words(tenths)}"


def laps_words(n: int) -> str:
    return "one lap" if n == 1 else f"{number_words(n)} laps"


_ORDINALS = {
    1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth",
    7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth", 11: "eleventh",
    12: "twelfth", 13: "thirteenth", 14: "fourteenth", 15: "fifteenth",
    16: "sixteenth", 17: "seventeenth", 18: "eighteenth", 19: "nineteenth",
    20: "twentieth",
}  # fmt: skip


def ordinal_words(n: int) -> str:
    """``6`` -> "sixth"; beyond twenty falls back to "P twenty-three"."""
    if n in _ORDINALS:
        return _ORDINALS[n]
    return f"P {number_words(n)}"
