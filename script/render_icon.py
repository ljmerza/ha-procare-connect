"""Generate the Procare Connect brand icon.

Original, generic artwork: a white schoolhouse on a rounded teal tile. It is not Procare's
logo. Writes the PNGs Home Assistant (2026.3+) serves from
`custom_components/procare_connect/brand/`: icon.png 256x256, icon@2x.png 512x512, and the
same square artwork as logo.png / logo@2x.png. Transparent outside the tile, trimmed (the tile
touches all four edges). Drawn with Pillow at 4x and downsampled for anti-aliasing.

    python3 script/render_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = ROOT / "custom_components" / "procare_connect" / "brand"

CANVAS = 512
SUPERSAMPLE = 4

TILE_COLOR = "#26A69A"
HOUSE_COLOR = "#FFFFFF"

TILE = (0.0, 0.0, 512.0, 512.0)
TILE_RADIUS = 104.0
# Schoolhouse: roof + walls as one polygon, with a round window and a door in the tile color.
HOUSE = [
    (256.0, 82.0),
    (430.0, 229.0),
    (393.0, 229.0),
    (393.0, 421.0),
    (119.0, 421.0),
    (119.0, 229.0),
    (82.0, 229.0),
]
WINDOW = (256.0, 217.0, 38.9)  # cx, cy, r
DOOR = (215.0, 306.0, 297.0, 421.0)


def render_png(size: int) -> Image.Image:
    """Rasterise at SUPERSAMPLE x and downsample to `size`."""
    scale = size * SUPERSAMPLE / CANVAS
    big = Image.new("RGBA", (size * SUPERSAMPLE, size * SUPERSAMPLE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(big)

    def s(value: float) -> float:
        return value * scale

    draw.rounded_rectangle([s(v) for v in TILE], radius=s(TILE_RADIUS), fill=TILE_COLOR)
    draw.polygon([(s(x), s(y)) for x, y in HOUSE], fill=HOUSE_COLOR)
    cx, cy, r = WINDOW
    draw.ellipse([s(cx - r), s(cy - r), s(cx + r), s(cy + r)], fill=TILE_COLOR)
    draw.rectangle([s(v) for v in DOOR], fill=TILE_COLOR)
    return big.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    """Write the icon and logo PNGs."""
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon", 256), ("icon@2x", 512), ("logo", 256), ("logo@2x", 512)):
        render_png(size).save(BRAND_DIR / f"{name}.png", optimize=True)


if __name__ == "__main__":
    main()
