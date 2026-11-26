"""Helpers to load repo demo MP4 videos and render clean PNG avatars/logos."""

from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
# The demo MP4 files in assets/ are 5 seconds long.
DEMO_VIDEO_DURATION_SEC = 5


@lru_cache(maxsize=8)
def load_demo_video(asset_name: str) -> bytes:
    """Read one of the checked-in demo MP4 pitch files from seed/assets/."""
    path = ASSETS_DIR / asset_name
    if not path.is_file():
        raise FileNotFoundError(f"Demo video asset not found: {path}")
    return path.read_bytes()


def render_badge_png(
    monogram: str,
    bg_rgb: tuple[int, int, int],
    *,
    rounded: bool = False,
) -> bytes:
    """Render a crisp 256x256 PNG badge with a centered monogram for demo avatars and logos."""
    size = 256
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    accent = tuple(min(255, c + 36) for c in bg_rgb)
    if rounded:
        draw.rounded_rectangle([(8, 8), (size - 9, size - 9)], radius=48, fill=(*bg_rgb, 255))
        draw.rounded_rectangle(
            [(20, 20), (size - 21, size - 21)],
            radius=38,
            outline=(*accent, 255),
            width=4,
        )
    else:
        draw.ellipse([(8, 8), (size - 9, size - 9)], fill=(*bg_rgb, 255))
        draw.ellipse([(20, 20), (size - 21, size - 21)], outline=(*accent, 255), width=4)

    text = monogram.strip().upper()[:2] or "WZ"
    font = _load_font(size=96)
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    pos = ((size - text_w) // 2 - bbox[0], (size - text_h) // 2 - bbox[1])
    draw.text(pos, text, fill=(255, 255, 255, 255), font=font)

    # Convert to opaque RGB PNG when storing as company logo/avatar so all browsers render cleanly.
    flattened = Image.new("RGB", (size, size), (248, 250, 252))
    flattened.paste(canvas, mask=canvas.split()[3])
    buf = io.BytesIO()
    flattened.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default(size=size)
