"""#335: the docs' brand assets in docs/assets/ come from brand.py and the wordmark."""

import importlib.util
import re
import shutil
import struct
from pathlib import Path

import pytest

from those_who_run import brand

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "docs" / "assets"
_spec = importlib.util.spec_from_file_location("brand_assets", ROOT / "scripts" / "brand_assets.py")
assert _spec is not None and _spec.loader is not None
brand_assets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brand_assets)

RED, BLACK, GREY, WHITE = (
    brand.hex_colour(c) for c in (brand.ADVAN_RED, brand.DEEP_BLACK, brand.CARBON_GREY, brand.WHITE)
)


def fills(name: str) -> list[str]:
    return re.findall(r'fill="([^"]+)"', (ASSETS / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # R1: on light, the Latin name in deep black, 走り屋 in Advan red.
        ("banner-dark.svg", [BLACK, RED, WHITE, RED, WHITE]),
        ("banner-light.svg", [RED, BLACK, RED, GREY]),
        ("wordmark-dark.svg", [RED, WHITE]),
        ("wordmark-light.svg", [RED, BLACK]),
    ],
)
def test_every_fill_is_a_brand_colour(name, expected):
    """AC3: the SVGs' fills are brand.py's colours, in the order drawn."""
    assert fills(name) == expected


def test_the_svgs_say_what_wrote_them_and_carry_no_text():
    """R2, R3: a first-line comment naming the script, and outlines only (no <text>,
    so GitHub, which loads no fonts for an SVG image, shows them as drawn)."""
    for name in ("banner-dark.svg", "banner-light.svg", "wordmark-dark.svg", "wordmark-light.svg"):
        text = (ASSETS / name).read_text(encoding="utf-8")
        first = text.splitlines()[0]
        assert first.startswith("<!--") and "scripts/brand_assets.py" in first, name
        assert "<text" not in text and "font-family" not in text, name
        assert f'aria-label="{brand.KANJI} {brand.NAME}' in text, name


def test_the_wordmark_shapes_are_the_apps_wordmark():
    """R2: the paths are web/src/assets/wordmark.svg's, recoloured."""
    _, kanji, name = brand_assets.wordmark_parts(brand_assets.WORDMARK.read_text())
    for asset in ("banner-dark.svg", "wordmark-light.svg"):
        text = (ASSETS / asset).read_text(encoding="utf-8")
        assert f'd="{kanji}"' in text and f'd="{name}"' in text


def test_the_script_holds_no_colour_literal():
    """AC3: colours come from brand.py, never a hex literal in the script."""
    source = (ROOT / "scripts" / "brand_assets.py").read_text(encoding="utf-8")
    assert re.findall(r"#[0-9A-Fa-f]{6}", source) == []


def test_the_committed_svgs_are_fresh():
    """R6: make check runs --check, which passes on the committed files."""
    assert brand_assets.main(["--check"]) == 0


def test_a_palette_change_makes_the_check_fail(tmp_path, monkeypatch, capsys):
    """AC5: changing ADVAN_RED without running make brand-assets fails --check."""
    for svg in ASSETS.glob("*.svg"):
        shutil.copy(svg, tmp_path / svg.name)
    monkeypatch.setattr(brand_assets, "RED", brand.hex_colour(0xD21F1C))
    assert brand_assets.main(["--check"], out=tmp_path) == 1
    assert "make brand-assets" in capsys.readouterr().err


def test_a_missing_svg_makes_the_check_fail(tmp_path):
    for svg in ASSETS.glob("*.svg"):
        shutil.copy(svg, tmp_path / svg.name)
    (tmp_path / "wordmark-light.svg").unlink()
    assert brand_assets.main(["--check"], out=tmp_path) == 1


def test_the_social_preview_is_a_link_card():
    """AC1: 1280x640 and under 1 MB."""
    png = (ASSETS / "social-preview.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (1280, 640)
    assert len(png) < 1_000_000
    assert b"tIME" not in png  # R3: no timestamp chunk


def test_the_readme_hero_follows_the_theme():
    """R4: a <picture> with the dark banner for a dark theme, the light one otherwise."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    picture = re.search(r"<picture>.*?</picture>", readme, re.S)
    assert picture is not None
    hero = picture.group(0)
    assert re.search(
        r'<source media="\(prefers-color-scheme: dark\)" srcset="docs/assets/banner-dark.svg"',
        hero,
    )
    assert 'src="docs/assets/banner-light.svg"' in hero
    assert 'alt="走り屋 Those Who Run"' in hero
