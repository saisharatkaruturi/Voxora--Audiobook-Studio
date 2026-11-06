"""Cover handling: normalise extracted/uploaded covers and generate a typographic
cover (title + author on a deterministic gradient) when a book has none."""

from __future__ import annotations

import hashlib
import io
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

COVER_SIZE = (900, 1350)
# VOXORA palettes: obsidian base, a deep glow, and an accent (orchid, mint, amber, coral).
PALETTES = [
    ((8, 9, 13), (104, 40, 160), (196, 92, 255)),
    ((8, 9, 13), (20, 118, 104), (95, 255, 210)),
    ((8, 9, 13), (62, 36, 96), (196, 92, 255)),
    ((8, 9, 13), (140, 76, 26), (255, 184, 107)),
    ((8, 9, 13), (140, 34, 64), (255, 107, 129)),
    ((10, 12, 18), (64, 50, 150), (95, 255, 210)),
]


def normalize_cover(data: bytes, max_side: int = 1400) -> bytes:
    """Validate an image and re-encode it as JPEG (strips metadata and any payload)."""
    img = Image.open(io.BytesIO(data))
    img.verify()
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88, optimize=True)
    return out.getvalue()


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        ["georgiab.ttf", "DejaVuSerif-Bold.ttf", "Georgia Bold.ttf", "timesbd.ttf"]
        if bold
        else ["georgia.ttf", "DejaVuSerif.ttf", "Georgia.ttf", "times.ttf"]
    )
    for name in candidates:
        for base in ("", "C:/Windows/Fonts/", "/usr/share/fonts/truetype/dejavu/", "/Library/Fonts/", "/System/Library/Fonts/Supplemental/"):
            try:
                return ImageFont.truetype(str(Path(base) / name) if base else name, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def generate_cover(title: str, author: str | None) -> bytes:
    seed = int(hashlib.sha256((title + (author or "")).encode()).hexdigest(), 16)
    dark, mid, accent = PALETTES[seed % len(PALETTES)]
    w, h = COVER_SIZE
    img = Image.new("RGB", (w, h), dark)
    # Soft radial glow for depth.
    glow = Image.new("RGB", (w, h), dark)
    gd = ImageDraw.Draw(glow)
    cx, cy = w * (0.3 + (seed % 40) / 100), h * 0.32
    for r in range(900, 0, -12):
        t = r / 900
        color = tuple(int(dark[i] * t + mid[i] * (1 - t)) for i in range(3))
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(60)), 0.9)
    draw = ImageDraw.Draw(img)
    # VOXORA signature: a small waveform under the title (book -> voice).
    bars = [0.35, 0.6, 1.0, 0.75, 0.5, 0.85, 0.4, 0.65, 0.3]
    bw, gap = 14, 12
    x0 = (w - (len(bars) * bw + (len(bars) - 1) * gap)) / 2
    for i, k in enumerate(bars):
        bh = 70 * k
        x = x0 + i * (bw + gap)
        draw.rounded_rectangle([x, h * 0.62 - bh / 2, x + bw, h * 0.62 + bh / 2], radius=bw // 2, fill=accent)

    title_font = _font(96 if len(title) < 22 else 72 if len(title) < 45 else 56, bold=True)
    lines = textwrap.wrap(title, width=14 if len(title) < 22 else 20 if len(title) < 45 else 26)[:5]
    y = h * 0.36 - len(lines) * 55
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        draw.text(((w - (bbox[2] - bbox[0])) / 2, y), line, font=title_font, fill=(234, 247, 255))
        y += (bbox[3] - bbox[1]) * 1.3
    if author:
        author_font = _font(40)
        text = author.upper()[:40]
        bbox = draw.textbbox((0, 0), text, font=author_font)
        draw.text(((w - (bbox[2] - bbox[0])) / 2, h * 0.69), text, font=author_font, fill=(157, 168, 184))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()
