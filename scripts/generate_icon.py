"""
scripts/generate_icon.py — Generate assets/afro.ico for Project Afro

Creates a multi-resolution .ico file (16,32,48,64,128,256 px).
Each frame: neon-green filled circle with "A" glyph centred in white.

Run:  python scripts/generate_icon.py
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def _make_frame(size: int) -> "Image.Image":
    from PIL import Image, ImageDraw, ImageFont

    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Circle: neon green fill, white outline
    pad = max(1, size // 16)
    draw.ellipse(
        [pad, pad, size - pad - 1, size - pad - 1],
        fill=(34, 197, 94),
        outline=(255, 255, 255),
        width=max(1, size // 32),
    )

    # "A" glyph — use a proportional font size if possible
    glyph = "A"
    font_size = max(8, int(size * 0.55))
    font = None
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), glyph, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1]
    draw.text((tx, ty), glyph, fill=(255, 255, 255), font=font)

    return img


def generate(output_path: Path) -> None:
    from PIL import Image

    output_path.parent.mkdir(parents=True, exist_ok=True)

    sizes  = [16, 32, 48, 64, 128, 256]
    frames = [_make_frame(s) for s in sizes]

    # Save as ICO — Pillow writes multi-size ICO when sizes kwarg provided
    frames[0].save(
        str(output_path),
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print(f"[generate_icon] Saved {output_path}  ({len(sizes)} sizes: {sizes})")


if __name__ == "__main__":
    out = ROOT / "assets" / "afro.ico"
    generate(out)
