"""Brand constants for Those Who Run (走り屋).

Everything user-facing that carries the name or the colours reads it from
here, so the results cards, the pit wall and any dashboard use the same
palette as the README. The palette is a 90s Japanese track-day shop: Advan
red on black, carbon grey for secondary panels, white type.
"""

from __future__ import annotations

NAME = "Those Who Run"
KANJI = "走り屋"
TAGLINE = "a self-hosted voice race engineer for Gran Turismo 7"

# Colours as 24-bit ints, the form discord.Embed(colour=...) and most UI kits take.
ADVAN_RED = 0xD21F1B
DEEP_BLACK = 0x111111
CARBON_GREY = 0x333333
WHITE = 0xFFFFFF

ACCENT = ADVAN_RED
BACKGROUND = DEEP_BLACK
PANEL = CARBON_GREY
TEXT = WHITE

# Trackside glyphs for text readouts, kept here so they are used consistently.
GLYPH_TIMER = "⏱️"
GLYPH_FLAG = "🚩"
GLYPH_FUEL = "⛽"


def hex_colour(value: int) -> str:
    """0xD21F1B -> '#D21F1B', for CSS, Streamlit and docs."""
    return f"#{value:06X}"


def banner(version: str) -> str:
    """One-line startup banner: name, kanji, version."""
    return f"{NAME} {KANJI} {version}"
