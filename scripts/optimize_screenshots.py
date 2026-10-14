#!/usr/bin/env python3
"""Shrinks docs/screenshots/*.png to at most 400 KB each (Pillow: palette quantization, then a resize if needed).
No editing beyond that: the pixels are the app's. Usage: python scripts/optimize_screenshots.py [dir]"""
import sys
from pathlib import Path

from PIL import Image

LIMIT = 400 * 1024


def shrink(path: Path) -> str:
    before = path.stat().st_size
    img = Image.open(path).convert("RGB")
    scale = 1.0
    for colors in (256, 128, 64):
        q = img.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        q.save(path, optimize=True)
        if path.stat().st_size <= LIMIT:
            break
    while path.stat().st_size > LIMIT and scale > 0.5:
        scale -= 0.1
        r = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)
        r.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)
    return f"{path.name}: {before // 1024} KB -> {path.stat().st_size // 1024} KB, {Image.open(path).size}"


if __name__ == "__main__":
    folder = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "docs" / "screenshots")
    for p in sorted(folder.glob("*.png")):
        print(shrink(p))
