#!/usr/bin/env python3
"""Render the Boostlayer SVG into the PNG sizes used by AppImage and hicolor."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: render_icons.py INPUT.svg OUTPUT_DIR", file=sys.stderr)
        return 64
    source = Path(sys.argv[1]).resolve()
    destination = Path(sys.argv[2]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        print(f"Invalid SVG: {source}", file=sys.stderr)
        return 65
    for size in SIZES:
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        target = destination / f"boostlayer-{size}.png"
        if not image.save(str(target), "PNG"):
            print(f"Cannot write {target}", file=sys.stderr)
            return 66
    # Keep the base name handy for .DirIcon and desktop icon caches.
    (destination / "boostlayer.png").write_bytes(
        (destination / "boostlayer-256.png").read_bytes()
    )
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
