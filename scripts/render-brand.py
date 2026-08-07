#!/usr/bin/env python3
"""Render site/assets/logo.svg into the three raster brand files beside it.

The mark is a vector; the rasters are what formats that cannot take a vector
need. This script is how they were made, so that "regenerate the favicon" is a
command rather than an archaeology exercise -- the binaries in git are its
output, checked in because the site generator only copies bytes and must stay
byte-deterministic across its two backends (scripts/site-dist-diff.sh).

It is NOT part of the build and CI does not run it: it needs a rasterizer, and
the site build needs nothing but the compiler. Run it by hand when the SVG
changes, and commit what it writes.

    python3 -m venv /tmp/brand && /tmp/brand/bin/pip install cairosvg pillow
    /tmp/brand/bin/python scripts/render-brand.py

What each output is for, and why it is not simply the same picture three times:

  logo-512.png       og:image. Transparent, whole viewBox.
  apple-touch-icon.png  iOS home screen. OPAQUE -- iOS composites a transparent
                     icon onto black, and this mark is dark indigo at its
                     corners. White, because the site's chrome is white. The
                     viewBox already carries ~12% padding, so rendering it whole
                     onto the square gives the inset iOS expects.
  favicon.ico        16/32/48, each rendered at its own size rather than
                     downscaled from one big one, so the 16px entry is drawn by
                     the rasterizer's own hinting instead of being an average of
                     pixels it never saw. Cropped to the ink (CROP below): at
                     16px the whole viewBox spends a quarter of its 256 pixels
                     on padding, and the difference is the cat's eyes surviving
                     or not.
"""

import io
import pathlib

import cairosvg
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SVG = ROOT / "site" / "assets" / "logo.svg"

# The mark's own bounds inside the 128x128 viewBox: the brackets run x 22..106
# and y 24..104 with a 12-wide stroke, so the ink is (16,18)-(112,110). Squared
# off to 96x96 about the centre; the cat sits well inside it.
CROP = "16 16 96 96"

ICO_SIZES = (16, 32, 48)
TOUCH = 180
TOUCH_BG = (255, 255, 255, 255)
OG = 512


def render(svg: str, size: int) -> Image.Image:
    png = cairosvg.svg2png(
        bytestring=svg.encode(), output_width=size, output_height=size
    )
    return Image.open(io.BytesIO(png)).convert("RGBA")


def main() -> None:
    svg = SVG.read_text()
    cropped = svg.replace('viewBox="0 0 128 128"', f'viewBox="{CROP}"')
    if cropped == svg:
        raise SystemExit(f"{SVG}: viewBox is not the 128x128 one this script crops")
    out = SVG.parent

    render(svg, OG).save(out / "logo-512.png")

    icon = Image.new("RGBA", (TOUCH, TOUCH), TOUCH_BG)
    icon.alpha_composite(render(svg, TOUCH))
    icon.convert("RGB").save(out / "apple-touch-icon.png")

    frames = [render(cropped, s) for s in ICO_SIZES]
    frames[-1].save(
        out / "favicon.ico",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=frames[:-1],
    )

    for name in ("logo-512.png", "apple-touch-icon.png", "favicon.ico"):
        print(f"  wrote site/assets/{name}")


if __name__ == "__main__":
    main()
