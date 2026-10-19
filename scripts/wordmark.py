"""Write the wordmark and icon SVGs in ``web/src/assets/`` and ``web/public/`` as
outlines, so the web app shows 走り屋 without loading a CJK font (ADR 0004 point 4).

The fonts, both SIL Open Font License 1.1:

- 走り屋: Noto Sans CJK JP, at weight 700 (the variable ``NotoSansCJK-VF.ttc``;
  Fedora's google-noto-sans-cjk-vf-fonts, or https://github.com/notofonts/noto-cjk);
- "Those Who Run": Barlow Semi Condensed 700, the Latin woff2 in
  ``web/node_modules/@fontsource/barlow-semi-condensed/files/``.

fontTools is not a project dependency: ``make wordmark NOTO=<.ttc>`` runs this with
a pinned fontTools through ``uv``, then renders the PNG icons from the SVGs.

    python scripts/wordmark.py NOTO_TTC BARLOW_SC_700_WOFF2
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTCollection, TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from those_who_run import brand  # noqa: E402

ASSETS = ROOT / "web" / "src" / "assets"
PUBLIC = ROOT / "web" / "public"
RED, BLACK, WHITE = (brand.hex_colour(c) for c in (brand.ADVAN_RED, brand.DEEP_BLACK, brand.WHITE))


def licence(fonts: str) -> str:
    """The SVG's first line: whose outlines these are, and what wrote them."""
    return (
        f"<!-- Outlines of {fonts}, SIL Open Font License 1.1."
        " Written by scripts/wordmark.py (make wordmark): never edit. -->"
    )


def run(font: TTFont, text: str, scale: float, x0: float, baseline: float):
    """Path data for ``text`` set from ``x0`` on ``baseline`` (y down), its bounds
    and where the next glyph would start."""
    glyphs = font.getGlyphSet()
    cmap = font.getBestCmap()
    pen, bounds = SVGPathPen(glyphs), BoundsPen(glyphs)
    x = x0
    for ch in text:
        glyph = glyphs[cmap[ord(ch)]]
        t = (scale, 0, 0, -scale, x, baseline)
        glyph.draw(TransformPen(pen, t))
        glyph.draw(TransformPen(bounds, t))
        x += glyph.width * scale
    return pen.getCommands(), bounds.bounds, x


def short(d: str) -> str:
    """Two decimals are plenty at these sizes."""
    return re.sub(r"(\d+\.\d{2})\d+", r"\1", d)


def wordmark(noto: TTFont, barlow: TTFont) -> str:
    """走り屋 in Advan red, then the name in white, on one line."""
    kanji, kb, end = run(noto, "走り屋", 64.0 / noto["head"].unitsPerEm, 0, 64)
    name, nb, _ = run(barlow, "Those Who Run", 40.0 / barlow["head"].unitsPerEm, end + 20, 58)
    x0, y0 = min(kb[0], nb[0]), min(kb[1], nb[1])
    x1, y1 = max(kb[2], nb[2]), max(kb[3], nb[3])
    pad = 4
    box = f"{x0 - pad:.0f} {y0 - pad:.0f} {x1 - x0 + 2 * pad:.0f} {y1 - y0 + 2 * pad:.0f}"
    return (
        f"{licence('Noto Sans CJK JP and Barlow Semi Condensed')}\n"
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{box}" role="img"'
        f' aria-label="走り屋 Those Who Run">\n'
        f'  <path fill="{RED}" d="{short(kanji)}"/>\n'
        f'  <path fill="{WHITE}" d="{short(name)}"/>\n</svg>\n'
    )


def icon(noto: TTFont, text: str, width: float, rounded: bool) -> str:
    """``text`` in red, centred on a 512 deep black square, ``width`` of its side."""
    _, b, _ = run(noto, text, 1.0, 0, 0)
    scale = 512 * width / (b[2] - b[0])
    _, b, _ = run(noto, text, scale, 0, 0)
    x = (512 - (b[2] - b[0])) / 2 - b[0]
    y = (512 - (b[3] - b[1])) / 2 - b[1]
    d, _, _ = run(noto, text, scale, x, y)
    rx = ' rx="96"' if rounded else ""
    return (
        f"{licence('Noto Sans CJK JP')}\n"
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">\n'
        f'  <rect width="512" height="512"{rx} fill="{BLACK}"/>\n'
        f'  <path fill="{RED}" d="{short(d)}"/>\n</svg>\n'
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Write the wordmark and icon SVGs as outlines.")
    p.add_argument("noto", type=Path, help="NotoSansCJK-VF.ttc (Noto Sans CJK JP is its first)")
    p.add_argument("barlow", type=Path, help="barlow-semi-condensed-latin-700-normal.woff2")
    args = p.parse_args(argv)
    noto = instantiateVariableFont(TTCollection(args.noto).fonts[0], {"wght": 700})
    barlow = TTFont(args.barlow)
    files = {
        ASSETS / "wordmark.svg": wordmark(noto, barlow),
        ASSETS / "icon.svg": icon(noto, "走り屋", 0.80, rounded=False),
        ASSETS / "icon-maskable.svg": icon(noto, "走り屋", 0.62, rounded=False),
        PUBLIC / "favicon.svg": icon(noto, "走", 0.62, rounded=True),
    }
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
