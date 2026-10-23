"""Monochrome SVG icon factory.

Icons live in ``assets/icons`` as white-on-transparent SVG files.  They are
rendered once per colour/size and tinted with the active theme colour, which
keeps the binary bundles small and the palette consistent.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap

try:  # PyQt6 ships QtSvg as a separate module
    from PyQt6.QtSvg import QSvgRenderer
except ImportError:  # pragma: no cover - extremely unusual install
    QSvgRenderer = None  # type: ignore[assignment]


def _icon_dir() -> Path:
    candidates = [
        Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)),
        Path(__file__).resolve().parent,
    ]
    for base in candidates:
        folder = base / "assets" / "ui"
        if folder.is_dir():
            return folder
    return candidates[0] / "assets" / "ui"


@lru_cache(maxsize=512)
def pixmap(name: str, color: str = "#FFFFFF", size: int = 20) -> QPixmap:
    """Return a tinted icon pixmap at 2x resolution for crisp HiDPI output."""
    dpr = 2
    canvas = QPixmap(size * dpr, size * dpr)
    canvas.fill(Qt.GlobalColor.transparent)
    path = _icon_dir() / f"{name}.svg"
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    try:
        if path.is_file() and QSvgRenderer is not None:
            renderer = QSvgRenderer(str(path))
            if renderer.isValid():
                renderer.render(painter)
            else:
                painter.setBrush(QColor(color))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(4, 4, size * dpr - 8, size * dpr - 8)
        else:
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(4, 4, size * dpr - 8, size * dpr - 8)
    finally:
        painter.end()

    tint = QPainter(canvas)
    try:
        tint.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        tint.fillRect(canvas.rect(), QColor(color))
    finally:
        tint.end()

    canvas.setDevicePixelRatio(dpr)
    return canvas


def icon(name: str, color: str = "#FFFFFF", size: int = 20) -> QIcon:
    """Return a themed :class:`QIcon` for *name*."""
    return QIcon(pixmap(name, color, size))


def set_button_icon(button, name: str, color: str, size: int = 18) -> None:
    """Assign *name* to a button and remember it for theme refreshes."""
    from PyQt6.QtCore import QSize

    button.setIcon(icon(name, color, size))
    button.setIconSize(QSize(size, size))
    button.setProperty("themeIconName", name)
    button.setProperty("themeIconSize", size)


def refresh_button_icon(button, color: str) -> None:
    """Re-tint a button previously configured through :func:`set_button_icon`."""
    name = button.property("themeIconName")
    if not name:
        return
    size = int(button.property("themeIconSize") or 18)
    button.setIcon(icon(str(name), color, size))
