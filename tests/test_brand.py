import pytest

from those_who_run import __version__, brand
from those_who_run.__main__ import build_parser


def test_palette_matches_brand_guidelines():
    assert brand.hex_colour(brand.ADVAN_RED) == "#D21F1B"
    assert brand.hex_colour(brand.DEEP_BLACK) == "#111111"
    assert brand.hex_colour(brand.CARBON_GREY) == "#333333"
    assert brand.hex_colour(brand.WHITE) == "#FFFFFF"
    assert brand.ACCENT == brand.ADVAN_RED


def test_name_and_kanji():
    assert brand.NAME == "Those Who Run"
    assert brand.KANJI == "走り屋"
    assert brand.banner("1.2.3") == "Those Who Run 走り屋 1.2.3"


def test_cli_carries_the_brand(capsys):
    p = build_parser()
    assert p.prog == "those-who-run"
    assert brand.NAME in (p.description or "")
    with pytest.raises(SystemExit):
        p.parse_args(["--version"])
    assert capsys.readouterr().out.strip() == brand.banner(__version__)
