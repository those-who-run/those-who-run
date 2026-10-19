import importlib.util
from pathlib import Path

import pytest

from those_who_run import __version__, brand
from those_who_run.__main__ import build_parser

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("brand_css", ROOT / "scripts" / "brand_css.py")
assert _spec is not None and _spec.loader is not None
brand_css = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brand_css)


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


def test_the_web_app_has_the_brand_colours():
    """#294 R1: web/src/styles/brand.css is brand.py's palette, and make check fails
    when it is stale."""
    assert brand_css.main(["--check"]) == 0, "run `make brand-css` and commit brand.css"
    css = (ROOT / "web" / "src" / "styles" / "brand.css").read_text(encoding="utf-8")
    assert "  --brand-advan-red: #D21F1B;" in css.splitlines()
    assert "  --brand-deep-black: #111111;" in css.splitlines()


def test_a_changed_brand_colour_makes_brand_css_stale(tmp_path, monkeypatch, capsys):
    """AC1: change ADVAN_RED without running the generator and the check fails."""
    out = tmp_path / "brand.css"
    assert brand_css.main([], out=out) == 0
    assert brand_css.main(["--check"], out=out) == 0
    monkeypatch.setattr(brand, "ADVAN_RED", 0xC00000)
    assert brand_css.main(["--check"], out=out) == 1
    assert "is stale: run `make brand-css`" in capsys.readouterr().err
    assert brand_css.main(["--check"], out=tmp_path / "missing.css") == 1
